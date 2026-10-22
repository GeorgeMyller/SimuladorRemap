/* eslint-disable @typescript-eslint/require-await -- mocks assíncronos */
/** T183 — EngineAutopsyView: piston_failure no cilindro 3 destaca o pistão 3, lista ≥ 2 elos e aceita restauração (RF-15, RF-16). */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { fetchForensicReportWithRetry } from "./api";
import { componentStates, EngineAutopsyView } from "./EngineAutopsyView";
import { installCanvasMock } from "./test-utils/mocks";
import { makeApi, notFound, openSocket, renderCockpit, reportFixture } from "./test-utils/harness";

vi.mock("uplot", () => import("./test-utils/uplotMock"));

const failurePayload = {
  failure_event_id: "01JAB0000000000000000000",
  session_id: "s",
  run_id: "r-01J9Z",
  tick: 13118,
  t_sim_s: 13.118,
  cylinder: 3,
  component_id: "piston:3",
  mode: "piston_failure" as const,
  mechanism: "knock_erosion",
  catastrophic: true,
  simulated_only: false,
  health_after: 0,
  causal_variables: { knock_signal_raw: 7.9, knock_intensity: 1, piston_temp_eff_c: 371 },
};

describe("EngineAutopsyView", () => {
  it("destaca o pistão 3 em vermelho e lista a cadeia causal ordenada no tempo com valores", async () => {
    render(<EngineAutopsyView runId="r-01J9Z" nCyl={4} turbo failure={failurePayload} onClose={() => undefined} onRestore={async () => undefined} loadReport={async () => reportFixture} locale="pt-BR" />);
    const dialog = screen.getByRole("dialog", { name: /Laudo forense: falha de pistão/ });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    const piston3 = dialog.querySelector('[data-component-id="piston:3"]')!;
    expect(piston3).toHaveAttribute("data-state", "failed");
    expect(piston3.querySelector("rect")).toHaveAttribute("fill", "#dc2626");
    expect(dialog.querySelector('[data-component-id="piston:1"]')).toHaveAttribute("data-state", "ok");
    expect(dialog.querySelector('[data-component-id="turbo:turbine"]')).not.toBeNull();
    const chain = await screen.findByRole("list", { name: "Cadeia causal" });
    expect(dialog.querySelector('[data-component-id="rod:3"]')).toHaveAttribute("data-state", "damaged");
    const links = within(chain).getAllByRole("listitem");
    expect(links.length).toBeGreaterThanOrEqual(2);
    expect(links.map((l) => l.getAttribute("data-causal-order"))).toEqual(["1", "2", "3"]);
    expect(links[1]).toHaveTextContent("12,90 s");
    expect(links[1]).toHaveTextContent("knock_intensity_cyl3 = 0,98");
    expect(screen.getByText(/Reduzir o avanço/)).toBeInTheDocument();
    expect(screen.getByText("O pistão 3 derreteu")).toBeInTheDocument();
  });

  it("laudo indisponível mostra o FailureEvent bruto e retry manual (EC-07)", async () => {
    const load = vi.fn().mockRejectedValueOnce(notFound("FORENSIC_REPORT_NOT_FOUND")).mockResolvedValueOnce(reportFixture);
    render(<EngineAutopsyView runId="r" nCyl={4} turbo={false} failure={failurePayload} onClose={() => undefined} onRestore={async () => undefined} loadReport={load} />);
    expect(await screen.findByText("laudo indisponível, tentar de novo")).toBeInTheDocument();
    expect(screen.getByTestId("raw-failure")).toHaveTextContent('"component_id": "piston:3"');
    expect(document.querySelector('[data-component-id="piston:3"]')).toHaveAttribute("data-state", "failed");
    fireEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByRole("list", { name: "Cadeia causal" })).toBeInTheDocument();
  });

  it("fetchForensicReportWithRetry faz 3 retries (1 s, 2 s, 4 s) em 404/409", async () => {
    vi.useFakeTimers();
    const get = vi.fn().mockRejectedValueOnce(notFound("FORENSIC_REPORT_NOT_FOUND")).mockRejectedValueOnce(notFound("X")).mockResolvedValueOnce(reportFixture);
    const p = fetchForensicReportWithRetry("r", { getForensicReport: get });
    await vi.advanceTimersByTimeAsync(1000);
    expect(get).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(2000);
    await expect(p).resolves.toBe(reportFixture);
    const always = vi.fn().mockRejectedValue(notFound("FORENSIC_REPORT_NOT_FOUND"));
    const p2 = fetchForensicReportWithRetry("r", { getForensicReport: always });
    const assertion = expect(p2).rejects.toMatchObject({ code: "FORENSIC_REPORT_NOT_FOUND" });
    await vi.advanceTimersByTimeAsync(7000);
    await assertion;
    expect(always).toHaveBeenCalledTimes(4);
    vi.useRealTimers();
  });

  it("Esc fecha o diálogo e o foco fica preso dentro dele", async () => {
    const onClose = vi.fn();
    render(<EngineAutopsyView runId="r" nCyl={4} turbo={false} failure={null} onClose={onClose} onRestore={async () => undefined} loadReport={async () => reportFixture} />);
    await screen.findByRole("list", { name: "Cadeia causal" });
    const dialog = screen.getByRole("dialog");
    expect(dialog.contains(document.activeElement)).toBe(true);
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("componentStates combina damaged_components e failure_event", () => {
    const s = componentStates(null, failurePayload);
    expect(s.get("piston:3")).toBe("failed");
    expect(componentStates(reportFixture, null).get("rod:3")).toBe("damaged");
  });

  it("na cockpit: event.failure catastrófico abre o laudo (≤ 2 s) e a restauração volta a 'pronto'", async () => {
    const canvas = installCanvasMock({ ctx2d: true });
    const api = makeApi();
    await renderCockpit(api);
    const ws = openSocket();
    await waitFor(() => expect(screen.getByRole("button", { name: "Iniciar" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Iniciar" }));
    await waitFor(() => expect(screen.getByTestId("run-status")).toHaveTextContent("puxada em curso"));
    const t0 = performance.now();
    act(() => ws.receive({ v: 1, type: "event.failure", seq: 30, t_sim_s: 13.118, payload: failurePayload }));
    const dialog = await screen.findByRole("dialog", { name: /Laudo forense/ });
    await within(dialog).findByRole("list", { name: "Cadeia causal" });
    expect(performance.now() - t0).toBeLessThan(2000);
    expect(screen.getByTestId("run-status")).toHaveTextContent("motor destruído");
    expect(screen.getByRole("button", { name: "Iniciar" })).toBeDisabled();
    expect(screen.getByText(/Gauges congelados/)).toBeInTheDocument();
    expect(screen.getAllByText("Motor destruído: falha de pistão").length).toBeGreaterThan(0);
    fireEvent.click(within(dialog).getByRole("button", { name: "Restaurar motor" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(api.restoreEngine).toHaveBeenCalled();
    expect(screen.getByTestId("run-status")).toHaveTextContent("pronto");
    expect(screen.queryByText(/Gauges congelados/)).toBeNull();
    expect(screen.getByRole("button", { name: "Iniciar" })).toBeEnabled();
    canvas.spy.mockRestore();
  });
});
