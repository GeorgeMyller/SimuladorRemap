/**
 * Modelo interno do editor (tuning §9 "Estado de front-end"): grade de valores em linhas
 * (`row` indexa o eixo Y, `col` o eixo X; tabela 2D tem 1 linha), seleção, `TableDelta`.
 */
import type { AxisView, TableView } from "./types";

export interface CellRef {
  row: number;
  col: number;
}

export type SelectionMode = "cells" | "rows" | "cols" | "all";

export interface Selection {
  anchor: CellRef;
  focus: CellRef;
  mode: SelectionMode;
}

export type DeltaOp = "set" | "add" | "scale" | "interp_line" | "interp_block" | "smooth" | "quick_tune" | "ai_tune" | "paste" | "revert";

export interface DeltaCell {
  row: number;
  col: number;
  before: number;
  after: number;
}

export interface TableDelta {
  tableId: string;
  cells: DeltaCell[];
  op: DeltaOp;
}

export interface GridAxis {
  quantity: string;
  values: number[];
  unit: string;
  sourceChannel: string;
}

/** Tabela editável normalizada (2D: `y = null`, `values` com 1 linha). */
export interface GridTable {
  tableId: string;
  kind: string;
  unit: string;
  min: number;
  max: number;
  decimals: number;
  liveTunable: boolean;
  cylinder: number | null;
  description: string;
  x: GridAxis;
  y: GridAxis | null;
  values: number[][];
}

export interface Rect {
  r0: number;
  r1: number;
  c0: number;
  c1: number;
}

function toAxis(a: AxisView): GridAxis {
  return { quantity: a.quantity, values: [...a.values], unit: a.unit, sourceChannel: a.source_channel ?? a.quantity };
}

export function toGridTable(t: TableView): GridTable {
  const is3d = Boolean(t.y);
  const raw = t.values;
  const values: number[][] = is3d ? (raw as number[][]).map((r) => [...r]) : [[...(raw as number[])]];
  return {
    tableId: t.table_id,
    kind: t.kind,
    unit: t.unit,
    min: t.min,
    max: t.max,
    decimals: t.decimals,
    liveTunable: t.live_tunable,
    cylinder: t.cylinder ?? null,
    description: t.description,
    x: toAxis(t.x),
    y: t.y ? toAxis(t.y) : null,
    values,
  };
}

export function nRows(t: GridTable): number {
  return t.values.length;
}

export function nCols(t: GridTable): number {
  return t.values[0]?.length ?? 0;
}

export function cell(t: GridTable, row: number, col: number): number {
  return t.values[row]?.[col] ?? Number.NaN;
}

export function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}

export function roundTo(v: number, decimals: number): number {
  const f = 10 ** decimals;
  return Math.round(v * f) / f;
}

/** Retângulo normalizado da seleção na grade `rows × cols`. */
export function selectionRect(sel: Selection, rows: number, cols: number): Rect {
  if (sel.mode === "all") return { r0: 0, r1: rows - 1, c0: 0, c1: cols - 1 };
  const r0 = Math.min(sel.anchor.row, sel.focus.row);
  const r1 = Math.max(sel.anchor.row, sel.focus.row);
  const c0 = Math.min(sel.anchor.col, sel.focus.col);
  const c1 = Math.max(sel.anchor.col, sel.focus.col);
  if (sel.mode === "rows") return { r0, r1, c0: 0, c1: cols - 1 };
  if (sel.mode === "cols") return { r0: 0, r1: rows - 1, c0, c1 };
  return { r0, r1, c0, c1 };
}

export function rectCells(rect: Rect): CellRef[] {
  const out: CellRef[] = [];
  for (let r = rect.r0; r <= rect.r1; r += 1) for (let c = rect.c0; c <= rect.c1; c += 1) out.push({ row: r, col: c });
  return out;
}

export function inRect(rect: Rect, row: number, col: number): boolean {
  return row >= rect.r0 && row <= rect.r1 && col >= rect.c0 && col <= rect.c1;
}

export function singleCell(row: number, col: number): Selection {
  return { anchor: { row, col }, focus: { row, col }, mode: "cells" };
}

/** Aplica um delta (`after`) ou o desfaz (`before`), devolvendo uma grade nova. */
export function applyDelta(values: number[][], delta: TableDelta, direction: "forward" | "backward"): number[][] {
  const next = values.map((r) => [...r]);
  for (const c of delta.cells) {
    const row = next[c.row];
    if (row && c.col < row.length) row[c.col] = direction === "forward" ? c.after : c.before;
  }
  return next;
}

/** Monta o `TableDelta` comparando a grade antiga com a nova (só células alteradas). */
export function makeDelta(tableId: string, before: number[][], after: number[][], op: DeltaOp): TableDelta {
  const cells: DeltaCell[] = [];
  for (let r = 0; r < after.length; r += 1) {
    const a = after[r]!;
    const b = before[r]!;
    for (let c = 0; c < a.length; c += 1) {
      if (!Object.is(a[c], b[c])) cells.push({ row: r, col: c, before: b[c]!, after: a[c]! });
    }
  }
  return { tableId, cells, op };
}

/** Converte a grade de volta ao formato do contrato (2D: lista simples). */
export function toContractValues(t: GridTable): number[] | number[][] {
  return t.y ? t.values.map((r) => [...r]) : [...(t.values[0] ?? [])];
}
