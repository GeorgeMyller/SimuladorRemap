/** T189 — operações puras de tabela (tuning RF-05 a RF-08, RF-16; EC-04, EC-06, EC-07). */
import { describe, expect, it } from "vitest";

import { selectionRect, type GridTable, type Rect } from "../model";
import { diffCalibrations } from "./diffCalibrations";
import { interpolateBlock, interpolateLine, lineDirection, smooth } from "./interpolate";
import { addValue, scalePct, setValue } from "./selectionOps";
import { parseCellNumber, parseTsv, pasteGrid, toTsv } from "./tsv";

function grid(values: number[][], x?: number[], y?: number[], min = -1000, max = 1000): GridTable {
  const cols = values[0]!.length;
  return {
    tableId: "t",
    kind: "ve",
    unit: "%",
    min,
    max,
    decimals: 1,
    liveTunable: true,
    cylinder: null,
    description: "",
    x: { quantity: "rpm", values: x ?? Array.from({ length: cols }, (_, i) => (i + 1) * 1000), unit: "rpm", sourceChannel: "rpm" },
    y: { quantity: "map_kpa", values: y ?? values.map((_, i) => (i + 1) * 20), unit: "kPa", sourceChannel: "map_kpa" },
    values,
  };
}

const R = (r0: number, r1: number, c0: number, c1: number): Rect => ({ r0, r1, c0, c1 });

describe("setValue / addValue / scalePct (RF-05)", () => {
  it("= define o valor na seleção", () => {
    const r = setValue(grid([[1, 2], [3, 4]]), R(0, 1, 0, 0), 9);
    expect(r.values).toEqual([[9, 2], [9, 4]]);
    expect(r.delta.op).toBe("set");
    expect(r.delta.cells).toEqual([
      { row: 0, col: 0, before: 1, after: 9 },
      { row: 1, col: 0, before: 3, after: 9 },
    ]);
  });

  it("+2 em 4 células de 10 resulta 12", () => {
    const r = addValue(grid([[10, 10], [10, 10]]), R(0, 1, 0, 1), 2);
    expect(r.values.flat()).toEqual([12, 12, 12, 12]);
    expect(r.delta.cells).toHaveLength(4);
  });

  it("− subtrai (soma negativa)", () => {
    expect(addValue(grid([[10]]), R(0, 0, 0, 0), -3).values).toEqual([[7]]);
  });

  it("+5 % em 20 resulta 21", () => {
    const r = scalePct(grid([[20]]), R(0, 0, 0, 0), 5);
    expect(r.values[0]![0]).toBeCloseTo(21, 10);
    expect(r.delta.op).toBe("scale");
  });

  it("prende aos limites min/max e conta as células limitadas (EC-04)", () => {
    const t = grid([[140, 100]], undefined, [1], 0, 150);
    const r = addValue(t, R(0, 0, 0, 1), 20);
    expect(r.values).toEqual([[150, 120]]);
    expect(r.clamped).toBe(1);
    expect(setValue(t, R(0, 0, 0, 1), -5).values).toEqual([[0, 0]]);
  });

  it("não altera células fora da seleção nem a grade original", () => {
    const t = grid([[1, 2, 3]]);
    const r = addValue(t, R(0, 0, 1, 1), 10);
    expect(r.values).toEqual([[1, 12, 3]]);
    expect(t.values).toEqual([[1, 2, 3]]);
  });
});

describe("interpolação pelos eixos (RF-06, EC-07)", () => {
  it("linha: rpm 1000, 2000, 4000 com extremos 10 e 40 dá 20 no meio (não 25)", () => {
    const t = grid([[10, 0, 40]], [1000, 2000, 4000]);
    const r = interpolateLine(t, R(0, 0, 0, 2))!;
    expect(r.values[0]![1]).toBeCloseTo(20, 10);
    expect(r.delta.op).toBe("interp_line");
  });

  it("coluna usa os breakpoints do eixo Y", () => {
    const t = grid([[0], [99], [30]], [1000], [100, 120, 160]);
    const r = interpolateLine(t, R(0, 2, 0, 0))!;
    expect(r.values[1]![0]).toBeCloseTo(10, 10);
  });

  it("bloco 3×3 com cantos 0, 10, 20, 30 dá o centro 15", () => {
    const t = grid([
      [0, 5, 10],
      [5, 99, 5],
      [20, 5, 30],
    ]);
    const r = interpolateBlock(t, R(0, 2, 0, 2))!;
    expect(r.values[1]![1]).toBeCloseTo(15, 10);
    expect(r.values[0]![1]).toBeCloseTo(5, 10);
    expect(r.values[2]![1]).toBeCloseTo(25, 10);
  });

  it("seleção degenerada não interpola e nunca divide por zero", () => {
    const t = grid([[1, 2], [3, 4]]);
    expect(lineDirection(R(1, 1, 1, 1))).toBeNull();
    expect(interpolateLine(t, R(1, 1, 1, 1))).toBeNull();
    expect(interpolateBlock(t, R(0, 0, 0, 1))).toBeNull();
    const flat = grid([[1, 2, 3]], [1000, 1000, 2000]);
    expect(interpolateLine(flat, R(0, 0, 0, 1))).toBeNull();
  });
});

describe("suavização 3×3 (RF-07)", () => {
  it("pico 100 rodeado de 0 resulta 25 após 1 passagem", () => {
    const t = grid([
      [0, 0, 0],
      [0, 100, 0],
      [0, 0, 0],
    ]);
    const r = smooth(t, R(1, 1, 1, 1));
    expect(r.values[1]![1]).toBe(25);
  });

  it("células fora da seleção ficam iguais bit a bit", () => {
    const values = [
      [1.1, 2.2, 3.3, 4.4],
      [5.5, 60.6, 7.7, 8.8],
      [9.9, 10.1, 11.11, 12.12],
    ];
    const r = smooth(grid(values), R(1, 1, 1, 2));
    for (const [row, col] of [[0, 0], [0, 3], [2, 2], [1, 0], [1, 3]] as const) {
      expect(Object.is(r.values[row]![col], values[row]![col])).toBe(true);
    }
  });

  it("bordas replicadas: canto suaviza com os próprios valores", () => {
    const r = smooth(grid([[8, 8], [8, 8]]), R(0, 1, 0, 1));
    expect(r.values.flat()).toEqual([8, 8, 8, 8]);
  });

  it("cada passagem lê o resultado da anterior", () => {
    const t = grid([
      [0, 0, 0],
      [0, 160, 0],
      [0, 0, 0],
    ]);
    const all = R(0, 2, 0, 2);
    const two = smooth(t, all, 2);
    const once = smooth({ ...t, values: smooth(t, all).values }, all);
    expect(two.values).toEqual(once.values);
  });
});

describe("TSV (RF-08, EC-06)", () => {
  it("copiar 2×3 gera a\\tb\\tc\\nd\\te\\tf", () => {
    expect(toTsv([[1, 2, 3], [4, 5, 6]], R(0, 1, 0, 2))).toBe("1\t2\t3\n4\t5\t6");
  });

  it("aceita vírgula ou ponto decimal", () => {
    expect(parseTsv("1,5\t2.5")).toEqual([[1.5, 2.5]]);
    expect(parseCellNumber(" -0,25 ")).toBe(-0.25);
    expect(parseCellNumber("=SOMA(A1)")).toBeNull();
    expect(parseCellNumber("<b>1</b>")).toBeNull();
    expect(parseTsv("1\r\n2\r\n")).toEqual([[1], [2]]);
  });

  it("colar 1,5 e 2.5 grava 1,5 e 2,5", () => {
    const r = pasteGrid(grid([[0, 0, 0]]), { row: 0, col: 0 }, parseTsv("1,5\t2.5"));
    expect(r.values).toEqual([[1.5, 2.5, 0]]);
    expect(r.delta.op).toBe("paste");
  });

  it("colagem maior que a tabela é cortada com a contagem de ignoradas", () => {
    const r = pasteGrid(grid([[0, 0], [0, 0]]), { row: 1, col: 1 }, parseTsv("1\t2\n3\t4"));
    expect(r.values).toEqual([[0, 0], [0, 1]]);
    expect(r.outside).toBe(3);
    expect(r.written).toBe(1);
  });

  it("células não numéricas não são gravadas; colagem toda inválida grava 0", () => {
    const r = pasteGrid(grid([[0, 0]]), { row: 0, col: 0 }, parseTsv("x\t7"));
    expect(r.values).toEqual([[0, 7]]);
    expect(r.invalid).toBe(1);
    expect(pasteGrid(grid([[0]]), { row: 0, col: 0 }, parseTsv("abc")).written).toBe(0);
  });

  it("toTsv arredonda a decimals e usa ponto", () => {
    expect(toTsv([[1.25, 2.04999]], R(0, 0, 0, 1), 1)).toBe("1.3\t2");
  });
});

describe("selectionRect (RF-04)", () => {
  it("linhas, colunas e tabela inteira", () => {
    expect(selectionRect({ anchor: { row: 2, col: 1 }, focus: { row: 3, col: 1 }, mode: "rows" }, 16, 16)).toEqual(R(2, 3, 0, 15));
    expect(selectionRect({ anchor: { row: 0, col: 4 }, focus: { row: 15, col: 4 }, mode: "cols" }, 16, 16)).toEqual(R(0, 15, 4, 4));
    expect(selectionRect({ anchor: { row: 5, col: 5 }, focus: { row: 1, col: 2 }, mode: "all" }, 4, 3)).toEqual(R(0, 3, 0, 2));
    expect(selectionRect({ anchor: { row: 5, col: 5 }, focus: { row: 1, col: 2 }, mode: "cells" }, 9, 9)).toEqual(R(1, 5, 2, 5));
  });
});

describe("diffCalibrations (RF-16)", () => {
  const view = (values: number[][], decimals = 1) => ({
    table_id: "ve",
    kind: "ve",
    unit: "%",
    live_tunable: true,
    description: "",
    decimals,
    min: 0,
    max: 150,
    x: { quantity: "rpm", values: [1000, 2000], unit: "rpm" },
    y: { quantity: "map_kpa", values: [50, 100], unit: "kPa" },
    values,
  });
  const cal = (values: number[][], strategies: Record<string, { kind: string } & Record<string, unknown>> = {}) => ({ tables: { ve: view(values) }, strategies, fuel_model: {}, profile_params: {} });

  it("conta só as células diferentes após arredondar a decimals", () => {
    const d = diffCalibrations(cal([[1, 2], [3, 4]]), cal([[1.04, 5], [3, 6]]));
    expect(d.changedCells).toBe(2);
    expect(d.tables).toEqual([
      { tableId: "ve", row: 0, col: 1, a: 2, b: 5 },
      { tableId: "ve", row: 1, col: 1, a: 4, b: 6 },
    ]);
  });

  it("estratégias por caminho e estrutura alterada", () => {
    const a = cal([[1, 1], [1, 1]], { boost_control: { kind: "boost_control", kp_pct_per_kpa: 0.4 } });
    const b = { ...cal([[1, 1], [1, 1]], { boost_control: { kind: "boost_control", kp_pct_per_kpa: 0.5 } }), tables: {} };
    const d = diffCalibrations(a, b);
    expect(d.strategies).toEqual([{ path: "boost_control.kp_pct_per_kpa", a: 0.4, b: 0.5 }]);
    expect(d.structural[0]!.path).toBe("tables.ve");
  });
});
