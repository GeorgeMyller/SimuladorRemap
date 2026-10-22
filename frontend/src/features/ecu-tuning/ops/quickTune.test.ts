/** T011 — Quick Tune e interpolação rápida H/V/B (feature 002, RF-08, RF-09, RN-04). */
import { describe, expect, it } from "vitest";

import type { GridTable, Selection } from "../model";
import { blockSmooth, interpolateH, interpolateV, quickTune, quickTuneFactor } from "./quickTune";

function grid(values: number[][], opts: { kind?: string; min?: number; max?: number; x?: number[]; y?: number[] } = {}): GridTable {
  const cols = values[0]!.length;
  return {
    tableId: "ve",
    kind: opts.kind ?? "ve",
    unit: "%",
    min: opts.min ?? 0,
    max: opts.max ?? 150,
    decimals: 1,
    liveTunable: true,
    cylinder: null,
    description: "",
    x: { quantity: "rpm", values: opts.x ?? Array.from({ length: cols }, (_, i) => (i + 1) * 1000), unit: "rpm", sourceChannel: "rpm" },
    y: { quantity: "map_kpa", values: opts.y ?? values.map((_, i) => (i + 1) * 20), unit: "kPa", sourceChannel: "map_kpa" },
    values,
  };
}

const sel = (r0: number, c0: number, r1: number, c1: number): Selection => ({ anchor: { row: r0, col: c0 }, focus: { row: r1, col: c1 }, mode: "cells" });

describe("quickTune (RN-04)", () => {
  it("VE 80, λ medido 0,90, λ alvo 0,80 → 90", () => {
    const out = quickTune(grid([[80, 70]]), [{ row: 0, col: 0 }], 0.9, 0.8);
    expect(out.ok).toBe(true);
    if (!out.ok) return;
    expect(out.result.values[0]![0]).toBeCloseTo(90, 10);
    expect(out.result.values[0]![1]).toBe(70);
    expect(out.result.delta.op).toBe("quick_tune");
    expect(out.result.delta.cells).toHaveLength(1);
    expect(out.result.clamped).toBe(0);
  });

  it("limita a correção a ±25 % por aplicação", () => {
    expect(quickTuneFactor(1.2, 0.8)).toBe(1.25);
    expect(quickTuneFactor(0.5, 1.0)).toBe(0.75);
    const up = quickTune(grid([[80]]), [{ row: 0, col: 0 }], 1.2, 0.8);
    const down = quickTune(grid([[80]]), [{ row: 0, col: 0 }], 0.5, 1.0);
    expect(up.ok && up.result.values[0]![0]).toBe(100);
    expect(down.ok && down.result.values[0]![0]).toBe(60);
  });

  it("respeita min/max da tabela e conta as células limitadas", () => {
    const out = quickTune(grid([[140, 10]], { min: 9, max: 150 }), [{ row: 0, col: 0 }, { row: 0, col: 1 }], 1.2, 1.0);
    expect(out.ok).toBe(true);
    if (!out.ok) return;
    expect(out.result.values[0]).toEqual([150, 12]);
    expect(out.result.clamped).toBe(1);
    const low = quickTune(grid([[10]], { min: 9 }), [{ row: 0, col: 0 }], 0.8, 1.0);
    expect(low.ok && low.result.values[0]![0]).toBe(9);
  });

  it("corrige todas as células indicadas e ignora índices fora da grade", () => {
    const out = quickTune(grid([[50, 60], [70, 80]]), [{ row: 0, col: 0 }, { row: 1, col: 1 }, { row: 5, col: 5 }], 1.1, 1.0);
    expect(out.ok).toBe(true);
    if (!out.ok) return;
    expect(out.result.values[0]![0]).toBeCloseTo(55);
    expect(out.result.values[1]![1]).toBeCloseTo(88);
    expect(out.result.values[0]![1]).toBe(60);
  });

  it("recusa tabela que não é VE", () => {
    expect(quickTune(grid([[20]], { kind: "ignition_base" }), [{ row: 0, col: 0 }], 0.9, 0.8)).toEqual({ ok: false, reason: "not_ve" });
  });

  it("recusa λ ausente, zero, negativo ou não finito", () => {
    const t = grid([[80]]);
    const c = [{ row: 0, col: 0 }];
    for (const [m, a] of [[null, 0.8], [0.9, null], [0, 0.8], [0.9, 0], [-1, 0.8], [Number.NaN, 0.8], [0.9, Number.POSITIVE_INFINITY]] as const) {
      expect(quickTune(t, c, m, a)).toEqual({ ok: false, reason: "invalid_lambda" });
    }
  });

  it("recusa sem células válidas", () => {
    expect(quickTune(grid([[80]]), [], 0.9, 0.8)).toEqual({ ok: false, reason: "no_cells" });
    expect(quickTune(grid([[80]]), [{ row: 3, col: 0 }], 0.9, 0.8)).toEqual({ ok: false, reason: "no_cells" });
  });
});

describe("interpolateH / interpolateV / blockSmooth (RF-09)", () => {
  it("H numa linha com extremos 10 e 40 em eixo uniforme dá 20 e 30 no meio", () => {
    const r = interpolateH(grid([[10, 0, 0, 40]]), sel(0, 0, 0, 3));
    expect(r?.values[0]).toEqual([10, 20, 30, 40]);
  });

  it("H usa os breakpoints do eixo X e trata cada linha selecionada", () => {
    const t = grid([[0, 0, 100], [10, 0, 30]], { x: [1000, 1500, 3000] });
    const r = interpolateH(t, sel(0, 0, 1, 2));
    expect(r?.values[0]![1]).toBeCloseTo(25);
    expect(r?.values[1]![1]).toBeCloseTo(15);
  });

  it("V interpola cada coluna entre a primeira e a última linha", () => {
    const t = grid([[10, 0], [0, 0], [30, 60]]);
    const r = interpolateV(t, sel(0, 0, 2, 1));
    expect(r?.values.map((row) => row[0])).toEqual([10, 20, 30]);
    expect(r?.values.map((row) => row[1])).toEqual([0, 30, 60]);
  });

  it("H/V degenerados devolvem null", () => {
    expect(interpolateH(grid([[1, 2], [3, 4]]), sel(0, 0, 1, 0))).toBeNull();
    expect(interpolateV(grid([[1, 2], [3, 4]]), sel(0, 0, 0, 1))).toBeNull();
  });

  it("B aplica o núcleo 3×3 ÷ 16 só às células selecionadas", () => {
    const t = grid([
      [0, 0, 0],
      [0, 16, 0],
      [0, 0, 0],
    ]);
    const r = blockSmooth(t, sel(1, 1, 1, 1));
    expect(r.values[1]![1]).toBe(4);
    expect(r.values[0]).toEqual([0, 0, 0]);
    const all = blockSmooth(t, { anchor: { row: 0, col: 0 }, focus: { row: 0, col: 0 }, mode: "all" });
    expect(all.values[0]![0]).toBe(1);
    expect(all.values[0]![1]).toBe(2);
    expect(all.delta.op).toBe("smooth");
  });
});
