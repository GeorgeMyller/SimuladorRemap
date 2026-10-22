/**
 * Operações rápidas do editor (feature 002, RF-08, RF-09, RN-04; D-09).
 * - `quickTune`: `VE_nova = VE × (λ_medido / λ_alvo)`, fator preso a ±25 % por aplicação e valor
 *   preso a `min`/`max` da tabela; recusa com motivo quando a tabela não é VE ou o λ é inválido;
 * - `interpolateH` / `interpolateV`: interpolação por eixo (reusa `interpolateLine`);
 * - `blockSmooth`: núcleo 3×3 `1 2 1 / 2 4 2 / 1 2 1` ÷ 16 só nas células selecionadas (reusa `smooth`).
 */
import { clamp, makeDelta, selectionRect, type CellRef, type GridTable, type Selection } from "../model";
import { interpolateLine, smooth } from "./interpolate";
import type { OpResult } from "./selectionOps";

export const QUICK_TUNE_MAX_STEP = 0.25;
export const VE_KIND = "ve";

export type QuickTuneRefusal = "not_ve" | "invalid_lambda" | "no_cells";

export type QuickTuneOutcome = { ok: true; result: OpResult } | { ok: false; reason: QuickTuneRefusal };

function isValidLambda(v: number | null | undefined): v is number {
  return typeof v === "number" && Number.isFinite(v) && v > 0;
}

/** Fator de correção `λm/λt` limitado a `[1 − 25 %, 1 + 25 %]`. */
export function quickTuneFactor(lambdaMeasured: number, lambdaTarget: number): number {
  return clamp(lambdaMeasured / lambdaTarget, 1 - QUICK_TUNE_MAX_STEP, 1 + QUICK_TUNE_MAX_STEP);
}

export function quickTune(table: GridTable, cells: readonly CellRef[], lambdaMeasured: number | null, lambdaTarget: number | null): QuickTuneOutcome {
  if (table.kind !== VE_KIND) return { ok: false, reason: "not_ve" };
  if (!isValidLambda(lambdaMeasured) || !isValidLambda(lambdaTarget)) return { ok: false, reason: "invalid_lambda" };
  const valid = cells.filter((c) => table.values[c.row]?.[c.col] !== undefined);
  if (valid.length === 0) return { ok: false, reason: "no_cells" };
  const factor = quickTuneFactor(lambdaMeasured, lambdaTarget);
  const values = table.values.map((r) => [...r]);
  let clamped = 0;
  for (const { row, col } of valid) {
    const raw = values[row]![col]! * factor;
    const next = clamp(raw, table.min, table.max);
    if (next !== raw) clamped += 1;
    values[row]![col] = next;
  }
  return { ok: true, result: { values, delta: makeDelta(table.tableId, table.values, values, "quick_tune"), clamped } };
}

function rectOf(table: GridTable, selection: Selection) {
  return selectionRect(selection, table.values.length, table.values[0]?.length ?? 0);
}

/** Cada linha selecionada: linear pelo eixo X entre a primeira e a última coluna. */
export function interpolateH(table: GridTable, selection: Selection): OpResult | null {
  return interpolateLine(table, rectOf(table, selection), "row");
}

/** Cada coluna selecionada: linear pelo eixo Y entre a primeira e a última linha. */
export function interpolateV(table: GridTable, selection: Selection): OpResult | null {
  return interpolateLine(table, rectOf(table, selection), "col");
}

/** Suavização 2D de uma passagem, só nas células selecionadas. */
export function blockSmooth(table: GridTable, selection: Selection): OpResult {
  return smooth(table, rectOf(table, selection), 1);
}
