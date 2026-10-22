/**
 * Diff célula a célula entre duas versões (tuning RF-16, §9 "Versões"): tabelas com igualdade
 * numérica após arredondamento a `decimals`; estratégias, `fuel_model` e `profile_params` por
 * caminho (ex.: `boost_control.kp_pct_per_kpa`). Mudança de forma/eixos aparece em `axes`.
 */
import { roundTo } from "../model";
import type { Calibration, TableView } from "../types";

export interface CellDiff {
  tableId: string;
  row: number;
  col: number;
  a: number;
  b: number;
}

export interface ValueDiff {
  path: string;
  a: unknown;
  b: unknown;
}

export interface CalibrationDiff {
  tables: CellDiff[];
  strategies: ValueDiff[];
  /** Tabelas só numa versão ou com eixos/forma diferentes. */
  structural: ValueDiff[];
  changedCells: number;
}

function rows(t: TableView): number[][] {
  return t.y ? (t.values as number[][]) : [t.values as number[]];
}

function sameAxis(a: TableView, b: TableView): boolean {
  const eq = (x: number[] | undefined, y: number[] | undefined) =>
    (x ?? []).length === (y ?? []).length && (x ?? []).every((v, i) => v === (y ?? [])[i]);
  return eq(a.x.values, b.x.values) && eq(a.y?.values, b.y?.values) && Boolean(a.y) === Boolean(b.y);
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function walk(path: string, a: unknown, b: unknown, out: ValueDiff[]): void {
  if (isPlainObject(a) && isPlainObject(b)) {
    for (const key of [...new Set([...Object.keys(a), ...Object.keys(b)])].sort()) {
      walk(path ? `${path}.${key}` : key, a[key], b[key], out);
    }
    return;
  }
  if (Array.isArray(a) && Array.isArray(b) && a.length === b.length) {
    a.forEach((item, i) => walk(`${path}[${i}]`, item, b[i], out));
    return;
  }
  if (typeof a === "number" && typeof b === "number" ? roundTo(a, 6) === roundTo(b, 6) : JSON.stringify(a) === JSON.stringify(b)) return;
  out.push({ path, a, b });
}

export function diffTables(tableId: string, a: TableView, b: TableView): CellDiff[] {
  const decimals = Math.max(a.decimals, b.decimals);
  const ra = rows(a);
  const rb = rows(b);
  const out: CellDiff[] = [];
  for (let r = 0; r < Math.min(ra.length, rb.length); r += 1) {
    const la = ra[r]!;
    const lb = rb[r]!;
    for (let c = 0; c < Math.min(la.length, lb.length); c += 1) {
      if (roundTo(la[c]!, decimals) !== roundTo(lb[c]!, decimals)) out.push({ tableId, row: r, col: c, a: la[c]!, b: lb[c]! });
    }
  }
  return out;
}

export function diffCalibrations(a: Pick<Calibration, "tables" | "strategies" | "fuel_model" | "profile_params">, b: Pick<Calibration, "tables" | "strategies" | "fuel_model" | "profile_params">): CalibrationDiff {
  const tables: CellDiff[] = [];
  const structural: ValueDiff[] = [];
  for (const id of [...new Set([...Object.keys(a.tables), ...Object.keys(b.tables)])].sort()) {
    const ta = a.tables[id];
    const tb = b.tables[id];
    if (!ta || !tb) {
      structural.push({ path: `tables.${id}`, a: ta ? "presente" : "ausente", b: tb ? "presente" : "ausente" });
      continue;
    }
    if (!sameAxis(ta, tb)) structural.push({ path: `tables.${id}.eixos`, a: [ta.x.values, ta.y?.values ?? null], b: [tb.x.values, tb.y?.values ?? null] });
    tables.push(...diffTables(id, ta, tb));
  }
  const strategies: ValueDiff[] = [];
  walk("", a.strategies, b.strategies, strategies);
  walk("fuel_model", a.fuel_model, b.fuel_model, strategies);
  walk("profile_params", a.profile_params, b.profile_params, strategies);
  return { tables, strategies, structural, changedCells: tables.length };
}
