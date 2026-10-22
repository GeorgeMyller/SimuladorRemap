/** T190 — UndoStack com ≥ 50 passos; operação de bloco = 1 passo (tuning RF-09, EC-08). */
import { describe, expect, it } from "vitest";

import { applyDelta, type GridTable, type TableDelta } from "../model";
import { scalePct } from "../ops/selectionOps";
import { DEFAULT_UNDO_CAPACITY, MIN_UNDO_CAPACITY, UndoStack } from "./UndoStack";

const delta = (i: number): TableDelta => ({ tableId: "ve", op: "set", cells: [{ row: 0, col: 0, before: i, after: i + 1 }] });

describe("UndoStack", () => {
  it("capacidade padrão 100 e mínimo 50", () => {
    expect(new UndoStack().capacity).toBe(DEFAULT_UNDO_CAPACITY);
    expect(new UndoStack(10).capacity).toBe(MIN_UNDO_CAPACITY);
  });

  it("60 edições com capacidade 50 permitem desfazer 50; a 51.ª fica desativada", () => {
    const s = new UndoStack(50);
    for (let i = 0; i < 60; i += 1) s.push(delta(i));
    let undone = 0;
    while (s.canUndo) {
      s.undo();
      undone += 1;
    }
    expect(undone).toBe(50);
    expect(s.undo()).toBeUndefined();
  });

  it("com a capacidade padrão as 60 edições ficam todas na pilha", () => {
    const s = new UndoStack();
    for (let i = 0; i < 60; i += 1) s.push(delta(i));
    expect(s.past).toHaveLength(60);
  });

  it("descarta o passo mais antigo (FIFO) acima da capacidade", () => {
    const s = new UndoStack(50);
    for (let i = 0; i < 51; i += 1) s.push(delta(i));
    expect(s.past[0]!.cells[0]!.before).toBe(1);
  });

  it("refazer após nova edição é limpo", () => {
    const s = new UndoStack();
    s.push(delta(1));
    s.push(delta(2));
    s.undo();
    expect(s.canRedo).toBe(true);
    s.push(delta(3));
    expect(s.canRedo).toBe(false);
    expect(s.redo()).toBeUndefined();
  });

  it("undo/redo devolvem o delta para aplicar", () => {
    const s = new UndoStack();
    s.push(delta(5));
    expect(s.undo()!.cells[0]!.after).toBe(6);
    expect(s.redo()!.cells[0]!.before).toBe(5);
  });

  it("delta vazio não ocupa passo", () => {
    const s = new UndoStack();
    s.push({ tableId: "ve", op: "set", cells: [] });
    expect(s.canUndo).toBe(false);
  });

  it("operação de bloco (+5 % em 16 células) é 1 passo e desfaz tudo", () => {
    const t: GridTable = {
      tableId: "ve", kind: "ve", unit: "%", min: 0, max: 150, decimals: 1, liveTunable: true, cylinder: null, description: "",
      x: { quantity: "rpm", values: [1, 2, 3, 4], unit: "", sourceChannel: "rpm" },
      y: { quantity: "map_kpa", values: [1, 2, 3, 4], unit: "", sourceChannel: "map_kpa" },
      values: [[20, 20, 20, 20], [20, 20, 20, 20], [20, 20, 20, 20], [20, 20, 20, 20]],
    };
    const r = scalePct(t, { r0: 0, r1: 3, c0: 0, c1: 3 }, 5);
    const s = new UndoStack();
    s.push(r.delta);
    expect(s.past).toHaveLength(1);
    const back = applyDelta(r.values, s.undo()!, "backward");
    expect(back).toEqual(t.values);
  });
});
