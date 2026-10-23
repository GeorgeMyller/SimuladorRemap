/* eslint-disable @typescript-eslint/require-await -- mocks assíncronos */
/** T198 — LiveTuneIndicator: cadeado e "bloqueada durante a puxada"; aplicação entre puxadas com confirmação (tuning RF-17, RF-18, EC-12; D-15). */
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MockWebSocket } from "@/test/mocks";

import { ApplyToSessionButton, LiveTuneIndicator } from "./LiveTuneIndicator";
import { DEFAULT_PREFS, PREFS_KEY } from "./prefs";
import { CAL_ID, makeApi, problem, SESSION_ID } from "./test-utils/fixtures";
import { loadedStore, renderWorkspace } from "./test-utils/harness";

beforeEach(() => localStorage.clear());

const tables = [
  { tableId: "ve", label: "VE", live: true },
  { tableId: "boost_target_gear", label: "Pressão por marcha", live: false },
];

describe("LiveTuneIndicator (RF-17)", () => {
  it("com run.state = running a tabela live aceita edição e a outra mostra cadeado", () => {
    render(<LiveTuneIndicator runActive telemetryFresh tables={tables} activeTableId="boost_target_gear" />);
    expect(screen.getByTestId("active-locked")).toHaveTextContent("Pressão por marcha: bloqueada durante a puxada");
    const locked = screen.getByRole("heading", { name: "Bloqueadas" }).nextElementSibling as HTMLElement;
    expect(within(locked).getByRole("img", { name: "cadeado" })).toBeInTheDocument();
    expect(within(locked).getByText("bloqueada durante a puxada")).toBeInTheDocument();
    const live = screen.getByRole("heading", { name: "Editáveis ao vivo" }).nextElementSibling as HTMLElement;
    expect(live).toHaveTextContent("VE");
  });

  it("sem telemetria mostra 'sem dados da bancada' (EC-12)", () => {
    render(<LiveTuneIndicator runActive={false} telemetryFresh={false} tables={tables} activeTableId={null} />);
    expect(screen.getByRole("status")).toHaveTextContent("sem dados da bancada");
  });
});

describe("aplicar à sessão (RF-18)", () => {
  it("entre puxadas pede confirmação e depois aplica", () => {
    const onApply = vi.fn();
    render(<ApplyToSessionButton version={7} runActive={false} onlyLiveChanges={false} disabled={false} applying={false} onApply={onApply} />);
    fireEvent.click(screen.getByRole("button", { name: "Aplicar à sessão" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Aplicar a revisão 7 à sessão?");
    fireEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    expect(onApply).toHaveBeenCalledTimes(1);
  });

  it("durante a puxada fica desativado exceto com alterações só em tabelas live-tunable", () => {
    const { rerender } = render(<ApplyToSessionButton version={7} runActive onlyLiveChanges={false} disabled={false} applying={false} onApply={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Aplicar à sessão" })).toBeDisabled();
    const onApply = vi.fn();
    rerender(<ApplyToSessionButton version={7} runActive onlyLiveChanges disabled={false} applying={false} onApply={onApply} />);
    fireEvent.click(screen.getByRole("button", { name: "Aplicar à sessão" }));
    expect(onApply).toHaveBeenCalled();
  });

  it("após 200 a barra de estado mostra 'revisão N aplicada'", async () => {
    localStorage.setItem(PREFS_KEY, JSON.stringify({ ...DEFAULT_PREFS, autoApply: "off" }));
    const api = makeApi();
    renderWorkspace(api);
    await screen.findByTestId("workspace-profile");
    fireEvent.click(screen.getByRole("button", { name: "Aplicar à sessão" }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    });
    expect(api.applyToSession).toHaveBeenCalledWith(SESSION_ID, { calibration_id: CAL_ID, version: 6, profile_options: {} });
    expect(await screen.findByTestId("applied")).toHaveTextContent("revisão 6 aplicada à sessão");
  });

  it("aplicação automática (padrão) esconde o botão; desligá-la mostra-o e grava a preferência", async () => {
    const api = makeApi();
    renderWorkspace(api);
    await screen.findByTestId("workspace-profile");
    const toggle = screen.getByRole("checkbox", { name: "Aplicar automaticamente" });
    expect(toggle).toBeChecked();
    expect(screen.queryByRole("button", { name: "Aplicar à sessão" })).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Aplicar à sessão" })).toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem(PREFS_KEY)!)).toMatchObject({ autoApply: "off" });
  });

  it("store: puxada ativa só aplica com alterações live; 409 TABLE_NOT_LIVE_TUNABLE vira aviso", async () => {
    const api = makeApi({
      applyToSession: vi.fn(async () => {
        throw problem(409, "TABLE_NOT_LIVE_TUNABLE", { items: ["strategies.rev_limiter"] }, "Alteração não live", "Há itens não live-tunable.");
      }),
    });
    const store = await loadedStore(api);
    store.setRunState("running");
    expect(store.canApply()).toBe(false);
    store.editCell("ve", 0, 0, 70);
    expect(store.onlyLiveChanges()).toBe(true);
    expect(store.canApply()).toBe(true);
    await store.applyToSession();
    expect(store.getSnapshot().notices.at(-1)!.text).toContain("strategies.rev_limiter");
    store.setRunState("completed");
    expect(store.canApply()).toBe(true);
    store.stop();
  });

  it("run.state do WebSocket bloqueia tabelas e o fim da puxada libera o rascunho retido", async () => {
    vi.useFakeTimers();
    const patchTable = vi.fn().mockRejectedValueOnce(problem(409, "TABLE_NOT_LIVE_TUNABLE")).mockImplementation(async (_c: string, tableId: string, body: { base_version: number }) => ({ version: body.base_version + 1, content_hash: "c", table: (await makeApi().getCalibration("x")).tables[tableId]! }));
    const api = makeApi({ patchTable });
    const store = await loadedStore(api, { telemetry: true, wsOrigin: "http://localhost" });
    store.start();
    const ws = MockWebSocket.last()!;
    expect(ws.url).toBe(`ws://localhost/ws/v1/sessions/${SESSION_ID}/telemetry`);
    ws.open();
    store.editCell("boost_target_gear", 0, 0, 160);
    await vi.advanceTimersByTimeAsync(300);
    expect(store.getSnapshot().heldTables).toEqual(["boost_target_gear"]);
    ws.receive({ v: 1, type: "run.state", seq: 1, t_sim_s: 1, payload: { run_id: "r1", state: "running" } });
    expect(store.isLocked("boost_target_gear")).toBe(true);
    expect(store.isLocked("ve")).toBe(false);
    ws.receive({ v: 1, type: "run.state", seq: 2, t_sim_s: 9, payload: { run_id: "r1", state: "completed" } });
    await vi.advanceTimersByTimeAsync(10);
    expect(patchTable).toHaveBeenCalledTimes(2);
    expect(store.getSnapshot().heldTables).toEqual([]);
    store.stop();
    vi.useRealTimers();
  });
});
