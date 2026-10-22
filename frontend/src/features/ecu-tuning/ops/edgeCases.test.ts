/** Casos de borda das operações de tabela (EC-04, EC-06, EC-07): seleções degeneradas, eixos e TSV. */
import { describe, expect, it } from "vitest";

import type { GridTable, Rect } from "../model";
import type { TableView } from "../types";
import { diffCalibrations, diffTables } from "./diffCalibrations";
import { interpolateBlock, interpolateLine } from "./interpolate";
import { mapRect } from "./selectionOps";
import { parseCellNumber, parseTsv, pasteGrid, toTsv } from "./tsv";

const R = (r0: number, r1: number, c0: number, c1: number): Rect => ({ r0, r1, c0, c1 });

function grid(values: number[][], x: number[], y: number[] | null): GridTable {
  return {
    tableId: "t",
    kind: "ve",
    unit: "%",
    min: 0,
    max: 100,
    decimals: 1,
    liveTunable: true,
    cylinder: null,
    description: "",
    x: { quantity: "rpm", values: x, unit: "rpm", sourceChannel: "rpm" },
    y: y ? { quantity: "map_kpa", values: y, unit: "kPa", sourceChannel: "map_kpa" } : null,
    values,
  };
}

describe("interpolação degenerada (EC-07)", () => {
  const t = grid(
    [
      [10, 20, 30],
      [40, 50, 60],
      [70, 80, 90],
    ],
    [1000, 1000, 3000],
    [20, 20, 60],
  );

  it("linha com breakpoints de X iguais nas pontas devolve null", () => {
    expect(interpolateLine(t, R(0, 0, 0, 1), "row")).toBeNull();
    expect(interpolateLine(t, R(0, 0, 1, 1), "row")).toBeNull();
    expect(interpolateLine(t, R(0, 0, 0, 0))).toBeNull();
  });

  it("coluna com breakpoints de Y iguais ou de uma só linha devolve null; tabela 2D interpola na linha", () => {
    expect(interpolateLine(t, R(0, 1, 0, 0), "col")).toBeNull();
    expect(interpolateLine(t, R(1, 1, 0, 0), "col")).toBeNull();
    const flat = grid([[1, 2, 3]], [1000, 2000, 3000], null);
    expect(interpolateLine(flat, R(0, 0, 0, 2))?.values).toEqual([[1, 2, 3]]);
  });

  it("eixo mais curto que a seleção interrompe a interpolação (frac sem breakpoint)", () => {
    const short = grid(
      [
        [0, 0, 0, 10],
        [0, 0, 0, 10],
      ],
      [1000, 2000, 3000],
      [20, 40],
    );
    expect(interpolateLine(short, R(0, 0, 0, 3), "row")).toBeNull();
    const shortY = grid(
      [
        [0, 0],
        [5, 5],
        [10, 10],
      ],
      [1000, 2000],
      [20, 40],
    );
    expect(interpolateLine(shortY, R(0, 2, 0, 0), "col")).toBeNull();
    expect(interpolateBlock(shortY, R(0, 2, 0, 1))).toBeNull();
    expect(interpolateBlock(short, R(0, 1, 0, 3))).toBeNull();
    expect(interpolateBlock(short, R(0, 0, 0, 3))).toBeNull();
  });
});

describe("TSV (EC-06)", () => {
  it("toTsv preenche com 0 linhas e células ausentes", () => {
    expect(toTsv([[1.25]], R(0, 1, 0, 1), 1)).toBe("1.3\t0\n0\t0");
  });

  it("parseCellNumber rejeita infinitos e vazios; parseTsv vazio devolve []", () => {
    expect(parseCellNumber("1e999")).toBeNull();
    expect(parseCellNumber("\u00a0")).toBeNull();
    expect(parseCellNumber(" 2,5 ")).toBe(2.5);
    expect(parseTsv("\r\n")).toEqual([]);
  });

  it("pasteGrid corta fora da tabela, conta inválidas e limita ao intervalo", () => {
    const t = grid([[1, 2]], [1000, 2000], [20]);
    const res = pasteGrid(t, { row: 0, col: 1 }, [
      [500, 7],
      [null, 3],
    ]);
    expect(res).toMatchObject({ outside: 3, invalid: 0, written: 1, clamped: 1 });
    expect(res.values[0]).toEqual([1, 100]);
    expect(pasteGrid(t, { row: 0, col: 0 }, [[null]])).toMatchObject({ invalid: 1, written: 0 });
  });
});

describe("mapRect", () => {
  it("salta linhas fora da tabela e resultados não finitos", () => {
    const t = grid([[10, 20]], [1000, 2000], [20]);
    const res = mapRect(t, R(0, 2, 0, 5), "set", (v, _r, c) => (c === 0 ? NaN : v * 2));
    expect(res.values).toEqual([[10, 40]]);
    expect(res.clamped).toBe(0);
  });
});

function view(values: number[] | number[][], x: number[], y?: number[], decimals = 1): TableView {
  return {
    table_id: "t",
    kind: "ve",
    unit: "%",
    min: 0,
    max: 100,
    decimals,
    live_tunable: true,
    x: { quantity: "rpm", values: x, unit: "rpm" },
    ...(y ? { y: { quantity: "map_kpa", values: y, unit: "kPa" } } : {}),
    values,
  } as unknown as TableView;
}

describe("diffCalibrations — estrutura e valores", () => {
  it("detecta tabelas só numa versão, eixos diferentes (2D vs 3D) e diferenças de estratégias", () => {
    const a = {
      tables: { ve: view([[1, 2]], [1, 2], [10]), ign: view([5, 6], [1, 2]), only_a: view([1], [1]) },
      strategies: { boost: { kp: 1.0000001, list: [1, 2], flags: [1] }, name: "x" },
      fuel_model: { mode: "sd" },
      profile_params: {},
    };
    const b = {
      tables: { ve: view([[1, 3]], [1, 2], [20]), ign: view([[5, 6]], [1, 2], [10]), only_b: view([1], [1]) },
      strategies: { boost: { kp: 1, list: [1, 2, 3], flags: [2] }, name: "x", extra: true },
      fuel_model: { mode: "alpha_n" },
      profile_params: null,
    };
    const diff = diffCalibrations(a as never, b as never);
    expect(diff.structural.map((s) => s.path)).toEqual(["tables.ign.eixos", "tables.only_a", "tables.only_b", "tables.ve.eixos"]);
    expect(diff.tables).toEqual([{ tableId: "ve", row: 0, col: 1, a: 2, b: 3 }]);
    expect(diff.strategies.map((s) => s.path)).toEqual(["boost.flags[0]", "boost.list", "extra", "fuel_model.mode", "profile_params"]);
  });

  it("diffTables arredonda ao maior nº de casas decimais", () => {
    expect(diffTables("t", view([1.04], [1], undefined, 1), view([1.0], [1], undefined, 1))).toEqual([]);
    expect(diffTables("t", view([1.04], [1], undefined, 2), view([1.0], [1], undefined, 1))).toHaveLength(1);
  });
});
