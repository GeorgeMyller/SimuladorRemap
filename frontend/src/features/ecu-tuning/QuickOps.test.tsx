/* eslint-disable @typescript-eslint/require-await -- mocks assíncronos */
/**
 * Feature 002 — Quick Tune e H/V/B no editor (RF-08, RF-09; T032), calibração de série somente
 * leitura com "Clonar e editar" (RF-04; T052) e aplicação automática após o PATCH (RF-07).
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MSG } from "./messages";
import { nearestCell } from "./OperationCursor";
import { ECU_SHORTCUTS } from "./ShortcutsDialog";
import { StockCalibrationBanner } from "./StockCalibrationBanner";
import { calibrationFixture, makeApi, problem, sessionFixture } from "./test-utils/fixtures";
import { loadedStore, renderTable } from "./test-utils/harness";
import { isStockCalibration, type LiveChannelSource, type WorkspaceStore } from "./workspaceStore";

let store: WorkspaceStore;
beforeEach(() => localStorage.clear());
afterEach(() => store?.stop());

/** rpm 3000 → coluna 5; MAP 100 kPa → linha 4 (VE fixture = 60 + linha + coluna = 69). */
const AT_3000_100 = { rpm: 3000, map_kpa: 100 };

function live(channels: Record<string, number> | null): LiveChannelSource {
  return () => channels;
}

const ve = (r: number, c: number) => store.getSnapshot().tables.ve!.values[r]![c]!;
const notices = () => store.getSnapshot().notices.map((n) => n.text);

describe("WorkspaceStore.quickTune (RF-08, RN-04)", () => {
  it("sem seleção múltipla corrige a célula do cursor de operação", async () => {
    store = await loadedStore(makeApi(), { liveSource: live({ ...AT_3000_100, lambda_measured: 0.935, lambda_target: 0.85 }) });
    expect(store.activeCell("ve")).toEqual({ row: 4, col: 5 });
    expect(store.quickTune("ve")).toBe(true);
    expect(ve(4, 5)).toBeCloseTo(75.9);
    expect(ve(0, 0)).toBe(60);
    expect(store.getSnapshot().dirtyTables).toEqual(["ve"]);
  });

  it("sem canal lambda_target usa a tabela lambda alvo no ponto de operação e o canal lambda como medido", async () => {
    store = await loadedStore(makeApi(), { liveSource: live({ ...AT_3000_100, lambda: 0.935 }) });
    store.quickTune("ve");
    expect(ve(4, 5)).toBeCloseTo(75.9);
  });

  it("sem canais dos eixos usa a célula focada", async () => {
    store = await loadedStore(makeApi(), { liveSource: live({ lambda_measured: 0.88, lambda_target: 0.8 }) });
    store.setSelection("ve", { anchor: { row: 1, col: 2 }, focus: { row: 1, col: 2 }, mode: "cells" });
    store.quickTune("ve");
    expect(ve(1, 2)).toBeCloseTo(63 * 1.1);
  });

  it("com seleção múltipla corrige todas as células selecionadas", async () => {
    store = await loadedStore(makeApi(), { liveSource: live({ ...AT_3000_100, lambda_measured: 0.9, lambda_target: 0.9 * 1.1 }) });
    store.setSelection("ve", { anchor: { row: 0, col: 0 }, focus: { row: 0, col: 1 }, mode: "cells" });
    store.quickTune("ve");
    expect(ve(0, 0)).toBeCloseTo(60 / 1.1);
    expect(ve(0, 1)).toBeCloseTo(61 / 1.1);
    expect(ve(4, 5)).toBe(69);
  });

  it("cada Quick Tune é 1 passo de desfazer", async () => {
    store = await loadedStore(makeApi(), { liveSource: live({ ...AT_3000_100, lambda_measured: 1.0, lambda_target: 0.8 }) });
    store.quickTune("ve");
    store.quickTune("ve");
    expect(ve(4, 5)).toBeCloseTo(69 * 1.25 * 1.25);
    store.undo();
    expect(ve(4, 5)).toBeCloseTo(69 * 1.25);
    store.undo();
    expect(ve(4, 5)).toBe(69);
  });

  it("fora da tabela VE avisa 'Quick Tune só atua na tabela VE'", async () => {
    store = await loadedStore(makeApi(), { liveSource: live({ ...AT_3000_100, lambda: 0.9 }) });
    expect(store.quickTune("ignition_base")).toBe(false);
    expect(notices()).toContain("Quick Tune só atua na tabela VE");
    expect(store.quickTune("nao_existe")).toBe(false);
  });

  it("sem telemetria avisa a falta de lambda e não altera a VE", async () => {
    store = await loadedStore();
    expect(store.liveChannels()).toBeNull();
    expect(store.activeCell("ve")).toEqual({ row: 0, col: 0 });
    expect(store.activeCell("nao_existe")).toBeNull();
    expect(store.quickTune("ve")).toBe(false);
    expect(notices()).toContain(MSG.quickTuneNoLambda);
    expect(store.getSnapshot().canUndo).toBe(false);
  });
});

describe("nearestCell e λ alvo pela tabela", () => {
  it("tabela 2D usa só o eixo X; falta de canal devolve null", () => {
    const x = { quantity: "rpm", values: [1000, 2000, 3000], unit: "rpm", sourceChannel: "rpm" };
    const y = { quantity: "map_kpa", values: [50, 100], unit: "kPa", sourceChannel: "map_kpa" };
    expect(nearestCell(x, null, { rpm: 2600 })).toEqual({ row: 0, col: 2 });
    expect(nearestCell(x, y, { rpm: 2600 })).toBeNull();
    expect(nearestCell(x, y, { map_kpa: 80 })).toBeNull();
    expect(nearestCell({ ...x, quantity: "x", sourceChannel: "desconhecido" }, null, { rpm: 1 })).toBeNull();
    expect(nearestCell(x, y, { rpm: 1400, map_kpa: 80 })).toEqual({ row: 1, col: 0 });
  });

  it("sem MAP nem canal lambda_target não há λ alvo: recusa sem alterar", async () => {
    store = await loadedStore(makeApi(), { liveSource: live({ rpm: 3000, lambda: 0.9 }) });
    expect(store.quickTune("ve")).toBe(false);
    expect(notices()).toContain(MSG.quickTuneNoLambda);
  });

  it("sem tabela lambda_target na calibração também recusa", async () => {
    const cal = calibrationFixture();
    delete cal.tables.lambda_target;
    store = await loadedStore(makeApi({}, cal), { liveSource: live({ ...AT_3000_100, lambda: 0.9 }) });
    expect(store.quickTune("ve")).toBe(false);
  });
});

describe("operações H/V/B na store (RF-09)", () => {
  it("interp_h, interp_v e block_smooth usam a seleção e entram no desfazer", async () => {
    store = await loadedStore();
    store.setSelection("ve", { anchor: { row: 0, col: 0 }, focus: { row: 0, col: 3 }, mode: "cells" });
    store.editCell("ve", 0, 3, 90);
    expect(store.applyOperation("ve", { op: "interp_h" })).toBe(true);
    expect(ve(0, 1)).toBeCloseTo(60 + (90 - 60) * (400 / 1200));
    store.setSelection("ve", { anchor: { row: 0, col: 0 }, focus: { row: 2, col: 0 }, mode: "cells" });
    store.editCell("ve", 2, 0, 100);
    expect(store.applyOperation("ve", { op: "interp_v" })).toBe(true);
    expect(ve(1, 0)).toBeCloseTo(80);
    expect(store.applyOperation("ve", { op: "block_smooth" })).toBe(true);
    store.setSelection("ve", { anchor: { row: 0, col: 0 }, focus: { row: 0, col: 0 }, mode: "cells" });
    expect(store.applyOperation("ve", { op: "interp_h" })).toBe(false);
    expect(notices()).toContain(MSG.interpHint);
  });
});

describe("atalhos Q, H, V, B no TableEditorCore (T032)", () => {
  it("Q aplica o Quick Tune; H/V/B operam a seleção; o diálogo lista as teclas", async () => {
    store = await loadedStore(makeApi(), { liveSource: live({ ...AT_3000_100, lambda_measured: 0.935, lambda_target: 0.85 }) });
    const { grid } = renderTable(store, "ve", "VE");
    fireEvent.keyDown(grid, { key: "q" });
    expect(ve(4, 5)).toBeCloseTo(75.9);

    act(() => store.setSelection("ve", { anchor: { row: 0, col: 0 }, focus: { row: 0, col: 2 }, mode: "cells" }));
    act(() => void store.editCell("ve", 0, 2, 80));
    fireEvent.keyDown(grid, { key: "H" });
    expect(ve(0, 1)).toBeCloseTo(60 + 20 * (400 / 800));

    act(() => store.setSelection("ve", { anchor: { row: 0, col: 0 }, focus: { row: 2, col: 0 }, mode: "cells" }));
    act(() => void store.editCell("ve", 2, 0, 70));
    fireEvent.keyDown(grid, { key: "v" });
    expect(ve(1, 0)).toBeCloseTo(65);

    const before = ve(1, 1);
    act(() => store.setSelection("ve", { anchor: { row: 1, col: 1 }, focus: { row: 1, col: 1 }, mode: "cells" }));
    fireEvent.keyDown(grid, { key: "b" });
    expect(ve(1, 1)).not.toBe(before);

    for (const keys of ["Q", "H / V", "B"]) expect(ECU_SHORTCUTS.some((s) => s.keys === keys)).toBe(true);
  });

  it("Q na tabela de avanço mostra o aviso; Alt+H e teclas dentro do campo de edição não disparam", async () => {
    store = await loadedStore(makeApi(), { liveSource: live({ ...AT_3000_100, lambda: 0.9 }) });
    const { grid } = renderTable(store, "ignition_base", "Avanço");
    fireEvent.keyDown(grid, { key: "Q" });
    expect(notices()).toContain("Quick Tune só atua na tabela VE");
    fireEvent.keyDown(grid, { key: "h", altKey: true });
    fireEvent.keyDown(grid, { key: "Enter" });
    const input = screen.getByRole("textbox", { name: /Editar/ });
    fireEvent.keyDown(input, { key: "b" });
    expect(store.getSnapshot().canUndo).toBe(false);
  });

  it("botões da barra: Quick Tune, Interpolar H/V e Suavizar bloco", async () => {
    store = await loadedStore(makeApi(), { liveSource: live({ ...AT_3000_100, lambda_measured: 0.935, lambda_target: 0.85 }) });
    renderTable(store, "ve", "VE");
    fireEvent.click(screen.getByRole("button", { name: "Quick Tune" }));
    expect(ve(4, 5)).toBeCloseTo(75.9);
    expect(screen.getByRole("button", { name: "Interpolar H" })).toBeDisabled();
    act(() => store.setSelection("ve", { anchor: { row: 0, col: 0 }, focus: { row: 2, col: 2 }, mode: "cells" }));
    fireEvent.click(screen.getByRole("button", { name: "Interpolar H" }));
    fireEvent.click(screen.getByRole("button", { name: "Interpolar V" }));
    fireEvent.click(screen.getByRole("button", { name: "Suavizar bloco" }));
    expect(store.getSnapshot().canUndo).toBe(true);
  });
});

describe("calibração stock-* somente leitura (RF-04, T052)", () => {
  const stockCal = calibrationFixture({ calibration_id: "stock-classic-20t-swap", metadata: { name: "Série", notes: "", source: "oem_stock", change_summary: "", extra: {} } });

  it("identifica stock-* e bloqueia a edição com a mensagem de clonar", async () => {
    expect(isStockCalibration("stock-x")).toBe(true);
    expect(isStockCalibration("cal-1")).toBe(false);
    store = await loadedStore(makeApi({}, stockCal));
    expect(store.getSnapshot()).toMatchObject({ stock: true, readOnly: true });
    expect(store.editCell("ve", 0, 0, 80)).toBe(false);
    expect(notices()).toContain(MSG.stockReadOnly);
    const { grid } = renderTable(store, "ve", "VE");
    fireEvent.keyDown(grid, { key: "h" });
    expect(notices().filter((n) => n === MSG.stockReadOnly)).toHaveLength(2);
  });

  it("'Clonar e editar' cria a cópia, aplica-a à sessão e recarrega editável", async () => {
    const clone = { ...stockCal, calibration_id: "user-clone-1", version: 1, metadata: { ...stockCal.metadata, name: "Série (cópia)", source: "clone" } };
    let sessionCal = stockCal.calibration_id;
    const api = makeApi({
      // O backend mantém `calibration_id` (inicial) e move `active_calibration_id` (T031).
      getSession: vi.fn(async () => ({ ...sessionFixture, calibration_id: stockCal.calibration_id, active_calibration_id: sessionCal })),
      getCalibration: vi.fn(async (id: string) => (id === clone.calibration_id ? clone : stockCal)),
      cloneCalibration: vi.fn(async () => clone),
      applyToSession: vi.fn(async (_s: string, body: { calibration_id: string; version?: number }) => {
        sessionCal = body.calibration_id;
        return { session_id: "s", calibration_id: body.calibration_id, version: body.version ?? 1, content_hash: "d", mode: "full" as const, changed_tables: [], applied_t_sim_s: 0 };
      }),
    });
    store = await loadedStore(api);
    render(<StockCalibrationBanner store={store} />);
    fireEvent.click(screen.getByRole("button", { name: MSG.cloneAndEdit }));
    await waitFor(() => expect(store.getSnapshot().stock).toBe(false));
    expect(api.cloneCalibration).toHaveBeenCalledWith({
      vehicle_id: "classic-20t-swap",
      profile_id: "ft-pro",
      source: "clone",
      clone_from_id: "stock-classic-20t-swap",
      clone_from_version: 6,
      metadata: { name: "Série (cópia)", source: "clone", change_summary: "cópia de stock-classic-20t-swap" },
    });
    expect(api.applyToSession).toHaveBeenCalledWith(expect.any(String), { calibration_id: "user-clone-1", version: 1, profile_options: {} });
    expect(store.getSnapshot()).toMatchObject({ readOnly: false, cloning: false });
    expect(store.getSnapshot().calibration?.calibration_id).toBe("user-clone-1");
    expect(screen.queryByTestId("stock-banner")).toBeNull();
    expect(store.editCell("ve", 0, 0, 80)).toBe(true);
    const reloaded = await loadedStore(api);
    expect(reloaded.getSnapshot()).toMatchObject({ stock: false, readOnly: false });
    expect(reloaded.getSnapshot().calibration?.calibration_id).toBe("user-clone-1");
    reloaded.stop();
  });

  it("load abre a calibração ativa da sessão e cai na inicial sem o campo (T031)", async () => {
    const active = { ...stockCal, calibration_id: "user-active-1", version: 4 };
    const getCalibration = vi.fn(async (id: string) => (id === active.calibration_id ? active : stockCal));
    store = await loadedStore(
      makeApi({ getSession: vi.fn(async () => ({ ...sessionFixture, calibration_id: stockCal.calibration_id, active_calibration_id: active.calibration_id })), getCalibration }),
    );
    expect(getCalibration).toHaveBeenCalledWith("user-active-1", { includeVersions: true });
    expect(store.getSnapshot()).toMatchObject({ stock: false, readOnly: false });
    store.stop();
    store = await loadedStore(makeApi({ getSession: vi.fn(async () => ({ ...sessionFixture, calibration_id: stockCal.calibration_id, active_calibration_id: null })), getCalibration }));
    expect(getCalibration).toHaveBeenLastCalledWith("stock-classic-20t-swap", { includeVersions: true });
    expect(store.getSnapshot().stock).toBe(true);
  });

  it("instala a cópia mesmo se a sessão ainda apontar para a stock", async () => {
    const clone = { ...stockCal, calibration_id: "user-clone-2", version: 1 };
    const api = makeApi({
      getSession: vi.fn(async () => ({ ...sessionFixture, calibration_id: stockCal.calibration_id })),
      getCalibration: vi.fn(async (id: string) => (id === clone.calibration_id ? clone : stockCal)),
      cloneCalibration: vi.fn(async () => clone),
    });
    store = await loadedStore(api);
    await store.cloneAndEdit();
    expect(store.getSnapshot().calibration?.calibration_id).toBe("user-clone-2");
    expect(store.getSnapshot().stock).toBe(false);
  });

  it("falha ao clonar mostra o erro e mantém a stock", async () => {
    const api = makeApi({ cloneCalibration: vi.fn(async () => { throw problem(422, "VALIDATION_FAILED", {}, "Inválido", "nome inválido"); }) }, stockCal);
    store = await loadedStore(api);
    expect(await store.cloneAndEdit()).toBeNull();
    expect(notices().some((n) => n.includes("VALIDATION_FAILED"))).toBe(true);
    expect(store.getSnapshot()).toMatchObject({ stock: true, cloning: false });
  });

  it("409 CALIBRATION_STOCK_IMMUTABLE no PATCH e no PUT vira somente leitura com mensagem clara", async () => {
    const api = makeApi({
      patchTable: vi.fn(async () => { throw problem(409, "CALIBRATION_STOCK_IMMUTABLE"); }),
      putCalibration: vi.fn(async () => { throw problem(409, "CALIBRATION_STOCK_IMMUTABLE"); }),
    });
    store = await loadedStore(api);
    store.editCell("ve", 0, 0, 80);
    await store.queue!.flush();
    await waitFor(() => expect(store.getSnapshot().stock).toBe(true));
    expect(store.getSnapshot().readOnly).toBe(true);
    expect(notices()).toContain(MSG.stockImmutable);
    expect(await store.saveVersion("x")).toBeNull();
  });
});

describe("aplicação automática após o PATCH (RF-07)", () => {
  it("após cada lote gravado chama applyToSession; desligada não chama", async () => {
    const api = makeApi();
    store = await loadedStore(api, { debounceMs: 1 });
    store.editCell("ve", 0, 0, 80);
    await store.queue!.flush();
    expect(api.applyToSession).not.toHaveBeenCalled();

    store.setAutoApply(true);
    store.editCell("ve", 0, 1, 81);
    await store.queue!.flush();
    await waitFor(() => expect(api.applyToSession).toHaveBeenCalledTimes(1));
    expect(api.patchTable.mock.invocationCallOrder[1]!).toBeLessThan(api.applyToSession.mock.invocationCallOrder[0]!);
    await waitFor(() => expect(store.getSnapshot().applied?.version).toBe(8));
    expect(store.getSnapshot().dirtyTables).toEqual([]);
  });

  it("lote gravado durante uma aplicação em curso reaplica no fim", async () => {
    let release: () => void = () => undefined;
    const api = makeApi();
    const original = api.applyToSession.getMockImplementation()!;
    api.applyToSession.mockImplementationOnce(async (s, body) => {
      await new Promise<void>((r) => (release = r));
      return original(s, body);
    });
    store = await loadedStore(api, { debounceMs: 1 });
    store.setAutoApply(true);
    store.editCell("ve", 0, 0, 80);
    await store.queue!.flush();
    await waitFor(() => expect(store.getSnapshot().applying).toBe(true));
    store.editCell("ve", 0, 1, 81);
    await store.queue!.flush();
    expect(api.applyToSession).toHaveBeenCalledTimes(1);
    release();
    await waitFor(() => expect(api.applyToSession).toHaveBeenCalledTimes(2));
  });

  it("durante a puxada respeita canApply (sem alterações live, não aplica)", async () => {
    const api = makeApi();
    store = await loadedStore(api, { debounceMs: 1 });
    store.setAutoApply(true);
    store.setRunState("running");
    expect(store.editCell("boost_target_gear", 0, 0, 160)).toBe(false);
    expect(store.canApply()).toBe(false);
    await store.queue!.flush();
    await new Promise((r) => setTimeout(r, 5));
    expect(api.applyToSession).not.toHaveBeenCalled();
  });
});

describe("WorkspaceStore.aiTune (LAYA.ai)", () => {
  it("aplica correções neurais retornadas pela API e atualiza tabela e aviso de sucesso", async () => {
    const api = makeApi();
    store = await loadedStore(api);
    expect(ve(0, 0)).toBe(60);

    const ok = await store.aiTune("ve");
    expect(ok).toBe(true);
    expect(api.aiTune).toHaveBeenCalledWith(store.getSnapshot().calibration?.calibration_id, {
      target_table_ids: ["ve"],
      aggressiveness: "balanced",
    });
    expect(ve(0, 0)).toBe(65);
    expect(notices().some((n) => n.includes("LAYA.ai"))).toBe(true);
  });

  it("em calibração de série recusa com aviso stockImmutable", async () => {
    const api = makeApi({}, calibrationFixture({ calibration_id: "stock-hatch" }));
    store = await loadedStore(api);

    const ok = await store.aiTune("ve");
    expect(ok).toBe(false);
    expect(api.aiTune).not.toHaveBeenCalled();
    expect(notices()).toContain(MSG.stockImmutable);
  });

  it("quando a IA não sugere correções informa que já está otimizada", async () => {
    const api = makeApi({
      aiTune: vi.fn(async () => ({
        corrections: [],
        total_cells_modified: 0,
        summary: "0 células ajustadas",
        safety_risk: false,
        risk_confidence: 0.99,
        estimated_torque_gain_pct: 0.0,
      })),
    });
    store = await loadedStore(api);

    const ok = await store.aiTune("ve");
    expect(ok).toBe(true);
    expect(notices().some((n) => n.includes("já estão otimizadas"))).toBe(true);
  });

  it("trata erro da API exibindo aviso com detalhes", async () => {
    const api = makeApi({
      aiTune: vi.fn(async () => {
        throw problem(500, "MODEL_ERROR", {}, "Falha no modelo", "Erro na inferência LAYA");
      }),
    });
    store = await loadedStore(api);

    const ok = await store.aiTune("ve");
    expect(ok).toBe(false);
    expect(notices().some((n) => n.includes("Falha no ajuste por IA"))).toBe(true);
  });
});
