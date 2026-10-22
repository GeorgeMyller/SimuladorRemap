/**
 * Operações de bloco sobre a seleção (tuning RF-05, §8 "Operações de tabela"):
 * `setValue` (v ← clamp(x)), `addValue` (v ← clamp(v + d)) e `scalePct` (v ← clamp(v·(1 + p/100))).
 * Funções puras: devolvem a grade nova, o `TableDelta` e quantas células foram limitadas.
 * O arredondamento a `decimals` só acontece ao gravar.
 */
import { clamp, makeDelta, type DeltaOp, type GridTable, type Rect, type TableDelta } from "../model";

export interface OpResult {
  values: number[][];
  delta: TableDelta;
  /** Células presas a `min`/`max` (aviso "valor limitado"). */
  clamped: number;
}

export function mapRect(table: GridTable, rect: Rect, op: DeltaOp, fn: (v: number, row: number, col: number) => number): OpResult {
  const values = table.values.map((r) => [...r]);
  let clamped = 0;
  for (let r = rect.r0; r <= rect.r1; r += 1) {
    const row = values[r];
    if (!row) continue;
    for (let c = rect.c0; c <= rect.c1 && c < row.length; c += 1) {
      const raw = fn(row[c]!, r, c);
      if (!Number.isFinite(raw)) continue;
      const v = clamp(raw, table.min, table.max);
      if (v !== raw) clamped += 1;
      row[c] = v;
    }
  }
  return { values, delta: makeDelta(table.tableId, table.values, values, op), clamped };
}

export function setValue(table: GridTable, rect: Rect, x: number): OpResult {
  return mapRect(table, rect, "set", () => x);
}

export function addValue(table: GridTable, rect: Rect, d: number): OpResult {
  return mapRect(table, rect, "add", (v) => v + d);
}

export function scalePct(table: GridTable, rect: Rect, p: number): OpResult {
  return mapRect(table, rect, "scale", (v) => v * (1 + p / 100));
}
