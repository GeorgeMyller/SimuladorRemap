/** T181 — RunControls: 4 tipos, abort "abortada" ≤ 500 ms, borboleta por teclado, 409 RUN_IN_PROGRESS (RF-12, RF-13; D-14). */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { cockpitReducer, type CockpitState } from "./cockpitState";
import { clampThrottle, RunControls, ThrottleSender, throttleStep } from "./RunControls";
import { installCanvasMock } from "./test-utils/mocks";
import { conflict, makeApi, openSocket, renderCockpit } from "./test-utils/harness";

vi.mock("uplot", () => import("./test-utils/uplotMock"));

const noop = () => undefined;

function renderControls(state: CockpitState, over: Partial<Parameters<typeof RunControls>[0]> = {}) {
  const props = { state, defaultEndRpm: 6600, onStart: vi.fn(), onAbort: vi.fn(), onThrottle: vi.fn(), ...over };
  const utils = render(<RunControls {...props} />);
  return { ...utils, props };
}

afterEach(() => vi.useRealTimers());

describe("RunControls", () => {
  it("oferece os 4 tipos de puxada", () => {
    renderControls({ kind: "ready" });
    const options = [...screen.getByRole("combobox", { name: "Tipo de puxada" }).querySelectorAll("option")].map((o) => o.getAttribute("value"));
    expect(options).toEqual(["baseline_pull", "sweep_pull", "steady_state_hold", "multi_pull"]);
  });

  it("Iniciar envia o DynoRunRequest; fica desativado durante a puxada ativa", () => {
    const { props, rerender } = renderControls({ kind: "ready" });
    fireEvent.change(screen.getByRole("combobox", { name: "Tipo de puxada" }), { target: { value: "multi_pull" } });
    fireEvent.change(screen.getByLabelText("Número de puxadas"), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "Iniciar" }));
    expect(props.onStart).toHaveBeenCalledWith(expect.objectContaining({ run_type: "multi_pull", pull_count: 4, start_rpm: 2000, end_rpm: 6600, gear: 4 }));
    rerender(<RunControls {...props} state={{ kind: "running", runId: "r1" }} />);
    expect(screen.getByRole("button", { name: "Iniciar" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Abortar" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Abortar" }));
    expect(props.onAbort).toHaveBeenCalled();
  });

  it("Enter com foco nos controles inicia a puxada", () => {
    const { props } = renderControls({ kind: "empty" });
    fireEvent.keyDown(screen.getByLabelText("Marcha"), { key: "Enter" });
    expect(props.onStart).toHaveBeenCalledTimes(1);
  });

  it("motor destruído ou backend indisponível desativam Iniciar", () => {
    const { rerender, props } = renderControls({ kind: "destroyed", runId: "r" });
    expect(screen.getByRole("button", { name: "Iniciar" })).toBeDisabled();
    rerender(<RunControls {...props} state={{ kind: "ready" }} disabledReason="backend indisponível" />);
    expect(screen.getByRole("button", { name: "Iniciar" })).toBeDisabled();
    expect(screen.getByText("backend indisponível")).toBeInTheDocument();
  });

  it("run.state aborted muda o estado para 'abortada' em ≤ 500 ms", () => {
    const running: CockpitState = { kind: "running", runId: "r1" };
    const { props, rerender } = renderControls(running);
    const t0 = performance.now();
    const next = cockpitReducer(running, { type: "runState", payload: { run_id: "r1", state: "aborted", abort_reason: "user_abort" } });
    rerender(<RunControls {...props} state={next} />);
    expect(screen.getByTestId("run-status")).toHaveTextContent("abortada");
    expect(performance.now() - t0).toBeLessThan(500);
  });

  it("borboleta: seta-cima +5 %, seta-baixo −5 %, Shift ±1 %, presa em 0–100", () => {
    vi.useFakeTimers();
    const { props } = renderControls({ kind: "ready" });
    fireEvent.change(screen.getByRole("combobox", { name: "Tipo de puxada" }), { target: { value: "steady_state_hold" } });
    const slider = screen.getByRole("slider", { name: "Borboleta" });
    expect(slider).toBeEnabled();
    fireEvent.keyDown(slider, { key: "ArrowDown" });
    expect(slider).toHaveValue("0");
    fireEvent.keyDown(slider, { key: "ArrowUp" });
    expect(slider).toHaveValue("5");
    fireEvent.keyDown(slider, { key: "ArrowUp", shiftKey: true });
    expect(slider).toHaveValue("6");
    fireEvent.keyDown(slider, { key: "End" });
    fireEvent.keyDown(slider, { key: "ArrowUp" });
    expect(slider).toHaveValue("100");
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(props.onThrottle).toHaveBeenLastCalledWith(100);
    expect(throttleStep(98, "ArrowUp", false)).toBe(100);
    expect(throttleStep(3, "ArrowDown", false)).toBe(0);
    expect(throttleStep(3, "a", false)).toBeNull();
    expect(clampThrottle(-4)).toBe(0);
  });

  it("arrastar o slider 0→100 em 1 s gera ≤ 20 mensagens control.throttle", () => {
    vi.useFakeTimers();
    let now = 0;
    const sent: number[] = [];
    const times: number[] = [];
    const sender = new ThrottleSender(
      (v) => {
        sent.push(v);
        times.push(now);
      },
      20,
      () => now,
    );
    for (let v = 0; v <= 100; v += 1) {
      sender.push(v);
      now += 9.9; // 101 eventos em 1 s
      vi.advanceTimersByTime(9.9);
    }
    vi.advanceTimersByTime(100);
    // Durante o arrasto de 1 s: ≤ 20 mensagens; em qualquer janela deslizante de 1 s também.
    expect(times.filter((t) => t < 1000).length).toBeLessThanOrEqual(20);
    for (const t0 of times) expect(times.filter((t) => t >= t0 && t < t0 + 1000).length).toBeLessThanOrEqual(20);
    expect(sent.at(-1)).toBe(100);
    sender.dispose();
  });

  it("borboleta desativada durante puxada ativa ou motor destruído", () => {
    const { rerender } = renderControls({ kind: "running", runId: "r1" }, { onThrottle: noop });
    expect(screen.getByRole("slider", { name: "Borboleta" })).toBeDisabled();
    rerender(<RunControls state={{ kind: "destroyed", runId: "r1" }} defaultEndRpm={6600} onStart={noop} onAbort={noop} onThrottle={noop} />);
    expect(screen.getByRole("slider", { name: "Borboleta" })).toBeDisabled();
  });
});

describe("RunControls integrado na cockpit", () => {
  it("409 RUN_IN_PROGRESS mostra 'Já existe uma puxada em curso' e sincroniza com GET da sessão", async () => {
    const canvas = installCanvasMock({ ctx2d: true });
    const api = makeApi({ startRun: vi.fn(async () => Promise.reject(conflict("RUN_IN_PROGRESS"))) });
    await renderCockpit(api);
    openSocket();
    api.getSession.mockResolvedValueOnce({ session_id: "s", vehicle_id: "hatch-20t-gdi", profile_id: "oem-stage", state: "running", active_run_id: "r-other", engine_locked: false });
    await waitFor(() => expect(screen.getByRole("button", { name: "Iniciar" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Iniciar" }));
    expect(await screen.findByText("Já existe uma puxada em curso")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("run-status")).toHaveTextContent("puxada em curso"));
    expect(api.startRun).toHaveBeenCalledTimes(1);
    canvas.spy.mockRestore();
  });

  it("abort envia o POST e a UI muda para 'abortada' ao receber run.state aborted", async () => {
    const canvas = installCanvasMock({ ctx2d: true });
    const api = makeApi({ abortRun: vi.fn(() => new Promise(() => undefined)) });
    await renderCockpit(api);
    const ws = openSocket();
    await waitFor(() => expect(screen.getByRole("button", { name: "Iniciar" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Iniciar" }));
    await waitFor(() => expect(screen.getByTestId("run-status")).toHaveTextContent("puxada em curso"));
    fireEvent.click(screen.getByRole("button", { name: "Abortar" }));
    expect(api.abortRun).toHaveBeenCalledWith(expect.any(String), "r-01J9Z");
    const t0 = performance.now();
    act(() => ws.receive({ v: 1, type: "run.state", seq: 5, t_sim_s: 3, payload: { run_id: "r-01J9Z", state: "aborted", previous_state: "running", abort_reason: "user_abort" } }));
    expect(screen.getByTestId("run-status")).toHaveTextContent("abortada");
    expect(performance.now() - t0).toBeLessThan(500);
    canvas.spy.mockRestore();
  });
});

describe("RunControls: teclas globais W/S e setas (arrowKeys)", () => {
  const holdState: CockpitState = { kind: "ready" };

  it("W/S e ↑/↓ fora de campos mexem na borboleta e não rolam a página", () => {
    const { props } = renderControls(holdState, { arrowKeys: true });
    expect(fireEvent.keyDown(document.body, { key: "w" })).toBe(false);
    expect(screen.getByRole("slider", { name: "Borboleta" })).toHaveValue("5");
    expect(props.onThrottle).toHaveBeenLastCalledWith(5);
    fireEvent.keyDown(document.body, { key: "W", shiftKey: true });
    expect(screen.getByRole("slider", { name: "Borboleta" })).toHaveValue("6");
    fireEvent.keyDown(document.body, { key: "s" });
    expect(screen.getByRole("slider", { name: "Borboleta" })).toHaveValue("1");
    expect(fireEvent.keyDown(document.body, { key: "ArrowLeft" })).toBe(false);
    expect(screen.getByRole("slider", { name: "Borboleta" })).toHaveValue("1");
  });

  it("com a borboleta inativa (puxada em curso) as setas só bloqueiam a rolagem", () => {
    const { props } = renderControls({ kind: "running", runId: "r1" }, { arrowKeys: true });
    expect(fireEvent.keyDown(document.body, { key: "ArrowDown" })).toBe(false);
    expect(props.onThrottle).not.toHaveBeenCalled();
  });

  it("não interceta teclas em campos numéricos nem sem arrowKeys", () => {
    const { rerender, props } = renderControls(holdState, { arrowKeys: true });
    expect(fireEvent.keyDown(screen.getByLabelText("Marcha"), { key: "ArrowUp" })).toBe(true);
    rerender(<RunControls {...props} arrowKeys={false} />);
    expect(fireEvent.keyDown(document.body, { key: "ArrowUp" })).toBe(true);
  });
});
