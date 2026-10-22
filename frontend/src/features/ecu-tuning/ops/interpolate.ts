/**
 * Interpolação pelos valores dos eixos e suavização 3×3 (tuning RF-06, RF-07).
 * - `interpolateLine`: linha (eixo X) ou coluna (eixo Y) entre as extremidades da seleção;
 * - `interpolateBlock`: bilinear a partir dos 4 cantos com os breakpoints dos dois eixos;
 * - `smooth`: núcleo `1 2 1 / 2 4 2 / 1 2 1` ÷ 16, bordas replicadas, só células selecionadas.
 * Seleção degenerada (1 célula ou breakpoints iguais) devolve `null` (EC-07), sem dividir por zero.
 */
import { makeDelta, type GridTable, type Rect } from "../model";
import type { OpResult } from "./selectionOps";

function frac(axis: readonly number[], i: number, i0: number, i1: number): number | null {
  const a = axis[i0];
  const b = axis[i1];
  const x = axis[i];
  if (a === undefined || b === undefined || x === undefined || b === a) return null;
  return (x - a) / (b - a);
}

function yAxis(table: GridTable): number[] {
  return table.y ? table.y.values : [0];
}

/** Direção possível de interpolação de linha para o retângulo (ou `null`). */
export function lineDirection(rect: Rect): "row" | "col" | null {
  if (rect.c1 > rect.c0) return "row";
  if (rect.r1 > rect.r0) return "col";
  return null;
}

export function canInterpolateBlock(rect: Rect): boolean {
  return rect.r1 > rect.r0 && rect.c1 > rect.c0;
}

/**
 * Interpola cada linha do retângulo entre as colunas `c0` e `c1` (direção `row`), ou cada coluna
 * entre as linhas `r0` e `r1` (direção `col`). Sem direção informada, usa `row` se houver ≥ 2 colunas.
 */
export function interpolateLine(table: GridTable, rect: Rect, direction: "row" | "col" | null = lineDirection(rect)): OpResult | null {
  if (!direction) return null;
  const values = table.values.map((r) => [...r]);
  if (direction === "row") {
    if (rect.c1 <= rect.c0 || table.x.values[rect.c1] === table.x.values[rect.c0]) return null;
    for (let r = rect.r0; r <= rect.r1; r += 1) {
      const row = values[r]!;
      const v0 = row[rect.c0]!;
      const v1 = row[rect.c1]!;
      for (let c = rect.c0 + 1; c < rect.c1; c += 1) {
        const f = frac(table.x.values, c, rect.c0, rect.c1);
        if (f === null) return null;
        row[c] = v0 + (v1 - v0) * f;
      }
    }
  } else {
    const ys = yAxis(table);
    if (rect.r1 <= rect.r0 || ys[rect.r1] === ys[rect.r0]) return null;
    for (let c = rect.c0; c <= rect.c1; c += 1) {
      const v0 = values[rect.r0]![c]!;
      const v1 = values[rect.r1]![c]!;
      for (let r = rect.r0 + 1; r < rect.r1; r += 1) {
        const f = frac(ys, r, rect.r0, rect.r1);
        if (f === null) return null;
        values[r]![c] = v0 + (v1 - v0) * f;
      }
    }
  }
  return { values, delta: makeDelta(table.tableId, table.values, values, "interp_line"), clamped: 0 };
}

/** Bilinear pelos 4 cantos `(r0,c0)`, `(r0,c1)`, `(r1,c0)`, `(r1,c1)`. */
export function interpolateBlock(table: GridTable, rect: Rect): OpResult | null {
  if (!canInterpolateBlock(rect)) return null;
  const ys = yAxis(table);
  const src = table.values;
  const q00 = src[rect.r0]![rect.c0]!;
  const q01 = src[rect.r0]![rect.c1]!;
  const q10 = src[rect.r1]![rect.c0]!;
  const q11 = src[rect.r1]![rect.c1]!;
  const values = src.map((r) => [...r]);
  for (let r = rect.r0; r <= rect.r1; r += 1) {
    const fy = frac(ys, r, rect.r0, rect.r1);
    if (fy === null) return null;
    for (let c = rect.c0; c <= rect.c1; c += 1) {
      const fx = frac(table.x.values, c, rect.c0, rect.c1);
      if (fx === null) return null;
      const top = q00 + (q01 - q00) * fx;
      const bottom = q10 + (q11 - q10) * fx;
      values[r]![c] = top + (bottom - top) * fy;
    }
  }
  return { values, delta: makeDelta(table.tableId, table.values, values, "interp_block"), clamped: 0 };
}

const KERNEL = [
  [1, 2, 1],
  [2, 4, 2],
  [1, 2, 1],
] as const;

/** Suavização 3×3 normalizada por 16, bordas replicadas; cada passagem lê a grade anterior. */
export function smooth(table: GridTable, rect: Rect, passes = 1): OpResult {
  const rows = table.values.length;
  const cols = table.values[0]?.length ?? 0;
  let current = table.values.map((r) => [...r]);
  for (let p = 0; p < Math.max(1, passes); p += 1) {
    const src = current;
    const next = src.map((r) => [...r]);
    for (let r = rect.r0; r <= rect.r1; r += 1) {
      for (let c = rect.c0; c <= rect.c1; c += 1) {
        let acc = 0;
        for (let dr = -1; dr <= 1; dr += 1) {
          const rr = Math.min(rows - 1, Math.max(0, r + dr));
          for (let dc = -1; dc <= 1; dc += 1) {
            const cc = Math.min(cols - 1, Math.max(0, c + dc));
            acc += KERNEL[dr + 1]![dc + 1]! * src[rr]![cc]!;
          }
        }
        next[r]![c] = acc / 16;
      }
    }
    current = next;
  }
  return { values: current, delta: makeDelta(table.tableId, table.values, current, "smooth"), clamped: 0 };
}
