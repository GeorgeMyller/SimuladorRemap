/* eslint-disable @typescript-eslint/require-await -- mocks assíncronos */
/** T194 — fila de PATCH: debounce de 300 ms, lote único com base_version, 409 e retry (tuning RF-13, EC-01 a EC-03; D-15). */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiProblem } from "@/lib/api";

import { draftKey } from "./prefs";
import { calibrationFixture, CAL_ID, makeApi, problem } from "./test-utils/fixtures";
import { loadedStore } from "./test-utils/harness";
import type { TablePatchBody, TablePatchResult } from "./types";
import { PatchQueue, usePatchQueue } from "./usePatchQueue";

const tableView = calibrationFixture().tables.ve!;

function okPatch() {
  return vi.fn(async (_c: string, _t: string, body: TablePatchBody): Promise<TablePatchResult> => ({ version: body.base_version + 1, content_hash: "c".repeat(64), table: tableView }));
}

beforeEach(() => {
  vi.useFakeTimers();
  localStorage.clear();
});
afterEach(() => vi.useRealTimers());

describe("PatchQueue", () => {
  it("10 edições em 200 ms geram 1 PATCH com base_version", async () => {
    const patch = okPatch();
    const q = new PatchQueue({ calibrationId: CAL_ID, version: 6, patch, storage: localStorage });
    for (let i = 0; i < 10; i += 1) {
      q.enqueue("ve", [{ row: 0, col: i % 4, value: 80 + i }]);
      await vi.advanceTimersByTimeAsync(20);
    }
    expect(patch).not.toHaveBeenCalled();
    expect(q.state).toBe("pending");
    await vi.advanceTimersByTimeAsync(300);
    expect(patch).toHaveBeenCalledTimes(1);
    const [cal, table, body] = patch.mock.calls[0]!;
    expect(cal).toBe(CAL_ID);
    expect(table).toBe("ve");
    expect(body.base_version).toBe(6);
    expect(body.op).toBe("set");
    expect(body.cells).toEqual([
      { row: 0, col: 0, value: 88 },
      { row: 0, col: 1, value: 89 },
      { row: 0, col: 2, value: 86 },
      { row: 0, col: 3, value: 87 },
    ]);
    expect(q.state).toBe("saved");
    expect(q.version).toBe(7);
  });

  it("lotes seguintes usam a versão devolvida (envio em série por tabela)", async () => {
    const patch = okPatch();
    const q = new PatchQueue({ calibrationId: CAL_ID, version: 6, patch, storage: localStorage });
    q.enqueue("ve", [{ row: 0, col: 0, value: 1 }]);
    q.enqueue("lambda_target", [{ row: 0, col: 0, value: 0.8 }]);
    await vi.advanceTimersByTimeAsync(300);
    expect(patch.mock.calls.map((c) => [c[1], c[2].base_version])).toEqual([
      ["ve", 6],
      ["lambda_target", 7],
    ]);
    expect(q.version).toBe(8);
  });

  it("o pendente fica no rascunho até gravar", async () => {
    const q = new PatchQueue({ calibrationId: CAL_ID, version: 6, patch: okPatch(), storage: localStorage });
    q.enqueue("ve", [{ row: 2, col: 3, value: 91 }]);
    expect(JSON.parse(localStorage.getItem(draftKey(CAL_ID))!)).toMatchObject({ base_version: 6, tables: { ve: [{ row: 2, col: 3, value: 91 }] } });
    await vi.advanceTimersByTimeAsync(300);
    expect(localStorage.getItem(draftKey(CAL_ID))).toBeNull();
  });

  it("5xx: 3 novas tentativas (1 s, 2 s, 4 s) e depois 'failed' com retry manual (EC-01)", async () => {
    const patch = vi.fn(async () => {
      throw problem(503, "DATABASE_UNAVAILABLE");
    });
    const q = new PatchQueue({ calibrationId: CAL_ID, version: 6, patch, storage: localStorage });
    q.enqueue("ve", [{ row: 0, col: 0, value: 1 }]);
    await vi.advanceTimersByTimeAsync(300);
    expect(patch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(patch).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(2000);
    expect(patch).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(4000);
    expect(patch).toHaveBeenCalledTimes(4);
    expect(q.state).toBe("failed");
    await vi.advanceTimersByTimeAsync(10_000);
    expect(patch).toHaveBeenCalledTimes(4);
    expect(localStorage.getItem(draftKey(CAL_ID))).not.toBeNull();
    patch.mockImplementation(async () => ({ version: 7, content_hash: "c", table: tableView }) as never);
    q.retry();
    await vi.advanceTimersByTimeAsync(0);
    expect(q.state).toBe("saved");
  });

  it("timeout do cliente conta como falha transitória", async () => {
    const patch = vi.fn().mockRejectedValueOnce(ApiProblem.synthetic(0, "CLIENT_TIMEOUT", "lento")).mockImplementation(async (_c, _t, body: TablePatchBody) => ({ version: body.base_version + 1, content_hash: "c", table: tableView }));
    const q = new PatchQueue({ calibrationId: CAL_ID, version: 6, patch, storage: localStorage });
    q.enqueue("ve", [{ row: 0, col: 0, value: 1 }]);
    await vi.advanceTimersByTimeAsync(1300);
    expect(patch).toHaveBeenCalledTimes(2);
    expect(q.state).toBe("saved");
  });

  it("409 CALIBRATION_VERSION_CONFLICT pausa a fila e chama onConflict com latest_version", async () => {
    const onConflict = vi.fn();
    const patch = vi.fn(async () => {
      throw problem(409, "CALIBRATION_VERSION_CONFLICT", { latest_version: 9 });
    });
    const q = new PatchQueue({ calibrationId: CAL_ID, version: 6, patch, storage: localStorage, onConflict });
    q.enqueue("ve", [{ row: 0, col: 0, value: 1 }]);
    await vi.advanceTimersByTimeAsync(300);
    expect(q.state).toBe("conflict");
    expect(onConflict).toHaveBeenCalledWith(expect.any(ApiProblem), "ve", 9);
    q.enqueue("ve", [{ row: 0, col: 1, value: 2 }]);
    await vi.advanceTimersByTimeAsync(1000);
    expect(patch).toHaveBeenCalledTimes(1);
    patch.mockImplementation(async () => ({ version: 10, content_hash: "c", table: tableView }) as never);
    q.resolveConflict("overwrite", 9);
    await vi.advanceTimersByTimeAsync(0);
    expect(patch).toHaveBeenLastCalledWith(CAL_ID, "ve", expect.objectContaining({ base_version: 9, cells: [{ row: 0, col: 0, value: 1 }, { row: 0, col: 1, value: 2 }] }));
    expect(q.version).toBe(10);
  });

  it("409 TABLE_NOT_LIVE_TUNABLE retém as células até releaseHeld (EC-03)", async () => {
    const onLocked = vi.fn();
    const patch = vi.fn().mockRejectedValueOnce(problem(409, "TABLE_NOT_LIVE_TUNABLE")).mockImplementation(async (_c, _t, body: TablePatchBody) => ({ version: body.base_version + 1, content_hash: "c", table: tableView }));
    const q = new PatchQueue({ calibrationId: CAL_ID, version: 6, patch, storage: localStorage, onLocked });
    q.enqueue("boost_target_gear", [{ row: 0, col: 0, value: 180 }]);
    await vi.advanceTimersByTimeAsync(300);
    expect(q.state).toBe("locked");
    expect(onLocked).toHaveBeenCalled();
    expect(q.heldTables()).toEqual(["boost_target_gear"]);
    expect((JSON.parse(localStorage.getItem(draftKey(CAL_ID))!) as { tables: Record<string, unknown[]> }).tables.boost_target_gear).toHaveLength(1);
    q.releaseHeld();
    await vi.advanceTimersByTimeAsync(0);
    expect(patch).toHaveBeenCalledTimes(2);
    expect(q.state).toBe("saved");
  });

  it("422 recusa o lote e chama onRejected", async () => {
    const onRejected = vi.fn();
    const patch = vi.fn(async () => {
      throw problem(422, "TABLE_VALUE_OUT_OF_RANGE", { row: 0, col: 0 });
    });
    const q = new PatchQueue({ calibrationId: CAL_ID, version: 6, patch, storage: localStorage, onRejected });
    q.enqueue("ve", [{ row: 0, col: 0, value: 999 }]);
    await vi.advanceTimersByTimeAsync(300);
    expect(q.state).toBe("error");
    expect(onRejected).toHaveBeenCalledWith(expect.objectContaining({ code: "TABLE_VALUE_OUT_OF_RANGE" }), "ve", [{ row: 0, col: 0, value: 999 }]);
    expect(q.hasPending()).toBe(false);
  });

  it("usePatchQueue expõe o estado e a versão", async () => {
    const q = new PatchQueue({ calibrationId: CAL_ID, version: 6, patch: okPatch(), storage: localStorage });
    const { result } = renderHook(() => usePatchQueue(q));
    expect(result.current).toEqual({ state: "idle", version: 6 });
    act(() => q.enqueue("ve", [{ row: 0, col: 0, value: 1 }]));
    expect(result.current.state).toBe("pending");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(result.current).toEqual({ state: "saved", version: 7 });
    const { result: none } = renderHook(() => usePatchQueue(null));
    expect(none.current.state).toBe("idle");
  });
});

describe("workspace: conflito recarrega a tabela (EC-02)", () => {
  it("409 busca a versão do servidor, calcula o diff e 'Recarregar' aplica a tabela do servidor", async () => {
    const server = calibrationFixture({ version: 9 });
    server.tables.ve = { ...server.tables.ve!, values: (server.tables.ve!.values as number[][]).map((r) => r.map(() => 77)) };
    const api = makeApi({
      patchTable: vi.fn(async () => {
        throw problem(409, "CALIBRATION_VERSION_CONFLICT", { latest_version: 9 });
      }),
    });
    const store = await loadedStore(api);
    api.getCalibration.mockImplementation(async () => server);
    store.setSelection("ve", { anchor: { row: 0, col: 0 }, focus: { row: 0, col: 0 }, mode: "cells" });
    store.applyOperation("ve", { op: "add", value: 5 });
    await vi.advanceTimersByTimeAsync(300);
    expect(api.patchTable).toHaveBeenCalledTimes(1);
    expect(api.patchTable.mock.calls[0]![2]).toMatchObject({ base_version: 6, cells: [{ row: 0, col: 0, value: 65 }] });
    await vi.advanceTimersByTimeAsync(0);
    const conflict = store.getSnapshot().conflict!;
    expect(conflict.latestVersion).toBe(9);
    expect(conflict.diff!.changedCells).toBeGreaterThan(0);
    await store.resolveConflict("reload");
    expect(store.getSnapshot().conflict).toBeNull();
    expect(store.getSnapshot().tables.ve!.values[0]![0]).toBe(77);
    expect(store.queue!.version).toBe(9);
    store.stop();
  });

  it("'Sobrescrever' reenvia com a versão do servidor", async () => {
    const patchTable = vi.fn().mockRejectedValueOnce(problem(409, "CALIBRATION_VERSION_CONFLICT", { latest_version: 9 })).mockImplementation(async (_c, tableId: string, body: TablePatchBody) => ({ version: body.base_version + 1, content_hash: "c", table: calibrationFixture().tables[tableId]! }));
    const api = makeApi({ patchTable });
    const store = await loadedStore(api);
    store.editCell("ve", 0, 0, 70);
    await vi.advanceTimersByTimeAsync(300);
    await vi.advanceTimersByTimeAsync(0);
    await store.resolveConflict("overwrite");
    await vi.advanceTimersByTimeAsync(0);
    expect(patchTable).toHaveBeenLastCalledWith(CAL_ID, "ve", expect.objectContaining({ base_version: 9 }));
    expect(store.getSnapshot().calibration!.version).toBe(10);
    store.stop();
  });

  it("valores são arredondados a decimals ao gravar", async () => {
    const api = makeApi();
    const store = await loadedStore(api);
    store.applyOperation("ve", { op: "scale", value: 3.3333 });
    await vi.advanceTimersByTimeAsync(300);
    expect(api.patchTable.mock.calls[0]![2].cells[0]!.value).toBe(62);
    store.stop();
  });
});
