import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { filenameFromDisposition } from "./api";
import { EvaluationResult } from "./EvaluationResult";
import ScenariosPage from "./ScenariosPage";
import { evaluation, makeApi, renderWithApi, result, SESSION_ID, STAGE1 } from "./test-utils/fixtures";

const RUN = "01JABCDEFGHJKMNPQRSTVWXYZ2";

const failed = evaluation({
  passed: false,
  total_score: 95,
  results: [
    result({ criterion_id: "delta-whp", kind: "min_delta_whp", comparator: "ge", measured: 43.2, threshold: 40, weight: 2 }),
    result({
      criterion_id: "egt",
      kind: "max_egt_c",
      measured: 962,
      threshold: 950,
      passed: false,
      score: 76,
      evidence: [{ run_id: RUN, log_id: RUN, channel: "egt_collector_c", t_sim_s: 12.34, rpm: 6100, cylinder: null, value: 962, url: `/api/v1/runs/${RUN}/log?format=json` }],
    }),
  ],
  revealed_defect: { kind: "fuel_pump_weak", fuel_pump_max_lph: 90 },
  hints_revealed: [1],
});

afterEach(() => vi.useRealTimers());

describe("EvaluationResult", () => {
  it("mostra selo reprovado com texto, pontuação e EvidenceLink por critério", async () => {
    renderWithApi(<EvaluationResult attemptId="att-1" />, makeApi({ getEvaluation: vi.fn(() => Promise.resolve(failed)) }));
    expect(await screen.findByText(/Pontuação total/)).toHaveTextContent("Pontuação total: 95,0 / 100");
    expect(screen.getAllByText("Reprovado").length).toBeGreaterThan(0);
    const row = document.querySelector<HTMLElement>('[data-criterion="egt"]');
    expect(row).not.toBeNull();
    const cells = within(row!);
    expect(cells.getByText("962,0 °C")).toBeInTheDocument();
    expect(cells.getByText(/egt_collector_c = 962,0 a 6.100 rpm em t = 12,34 s/)).toBeInTheDocument();
    const cockpit = await cells.findByRole("link", { name: /na bancada/ });
    expect(cockpit).toHaveAttribute("href", `/sessions/${SESSION_ID}/dyno?run=${RUN}&t=12.34`);
    expect(cells.getByRole("link", { name: "Ver log" })).toHaveAttribute("href", `/api/v1/runs/${RUN}/log?format=json`);
    const ok = document.querySelector<HTMLElement>('[data-criterion="delta-whp"]');
    expect(within(ok!).getByText("Aprovado")).toBeInTheDocument();
    expect(screen.getByText("Bomba de combustível fraca")).toBeInTheDocument();
    expect(screen.getByText("Dicas reveladas: 1")).toBeInTheDocument();
  });

  it("pending mostra 'Sonda de knock em execução' quando há critério de margem e faz polling", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const getEvaluation = vi
      .fn()
      .mockResolvedValueOnce(evaluation({ status: "pending", passed: null, total_score: null }))
      .mockResolvedValue(evaluation());
    const withProbe = {
      ...STAGE1,
      criteria: { ...STAGE1.criteria, criteria: [{ criterion_id: "margin", kind: "min_knock_margin_deg" as const, comparator: "ge" as const, threshold: 2, weight: 1, mandatory: true }] },
    };
    renderWithApi(<EvaluationResult attemptId="att-1" pollMs={50} />, makeApi({ getEvaluation, getScenario: vi.fn(() => Promise.resolve(withProbe)) }));
    expect(await screen.findByRole("progressbar", { name: "Sonda de knock em execução" })).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    expect(await screen.findByText("Aprovado")).toBeInTheDocument();
  });

  it("status error mostra o código da avaliação", async () => {
    renderWithApi(
      <EvaluationResult attemptId="att-1" />,
      makeApi({ getEvaluation: vi.fn(() => Promise.resolve(evaluation({ status: "error", error_code: "PROBE_FAILED", passed: null, total_score: null }))) }),
    );
    expect(await screen.findByText("PROBE_FAILED")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Exportar pacote" })).toBeNull();
  });

  it("exporta o pacote da tentativa com o nome do Content-Disposition", async () => {
    const exportPackage = vi.fn(() => Promise.resolve({ filename: "simremap-attempt-att-1-abcdef12.simremap.json", content: "{}" }));
    const createObjectURL = vi.fn(() => "blob:x");
    Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    renderWithApi(<ScenariosPage />, makeApi({ exportPackage }), "/attempts/att-1/result?submission=1", "/attempts/*");
    await userEvent.click(await screen.findByRole("button", { name: "Exportar pacote" }));
    expect(exportPackage).toHaveBeenCalledWith({ kind: "attempt", attempt_id: "att-1", include_full_logs: false });
    expect(createObjectURL).toHaveBeenCalled();
    expect(click).toHaveBeenCalled();
  });

  it("filenameFromDisposition", () => {
    expect(filenameFromDisposition('attachment; filename="simremap-challenge-x-1234abcd.simremap.json"', "f")).toBe(
      "simremap-challenge-x-1234abcd.simremap.json",
    );
    expect(filenameFromDisposition(null, "f")).toBe("f");
  });
});
