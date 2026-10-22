/**
 * Preferências do editor e rascunho não gravado (tuning RF-22, EC-15; data-model 4.3).
 * - `simremap.ecu-tuning.prefs.v1`: `heatmap`, `lambdaDisplay` (λ ou AFR), `show3d`;
 * - `simremap.ecu-tuning.draft.<calibration_id>`: células pendentes por tabela com `base_version`.
 * JSON inválido no `localStorage` é descartado (o chamador mostra o aviso).
 */
import { z } from "zod";

import type { CellEdit } from "./types";

export const PREFS_KEY = "simremap.ecu-tuning.prefs.v1";
export const DRAFT_PREFIX = "simremap.ecu-tuning.draft.";

export interface TuningPrefs {
  version: 1;
  heatmap: "on" | "off";
  lambdaDisplay: "lambda" | "afr";
  show3d: "side" | "below" | "off";
}

export const DEFAULT_PREFS: TuningPrefs = { version: 1, heatmap: "on", lambdaDisplay: "lambda", show3d: "off" };

const prefsSchema = z.object({
  version: z.literal(1),
  heatmap: z.enum(["on", "off"]).catch("on"),
  lambdaDisplay: z.enum(["lambda", "afr"]).catch("lambda"),
  show3d: z.enum(["side", "below", "off"]).catch("off"),
});

function defaultStorage(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

export function loadPrefs(storage: Storage | null = defaultStorage()): TuningPrefs {
  const raw = storage?.getItem(PREFS_KEY);
  if (!raw) return { ...DEFAULT_PREFS };
  try {
    const parsed = prefsSchema.safeParse(JSON.parse(raw));
    return parsed.success ? parsed.data : { ...DEFAULT_PREFS };
  } catch {
    return { ...DEFAULT_PREFS };
  }
}

export function savePrefs(prefs: TuningPrefs, storage: Storage | null = defaultStorage()): void {
  try {
    storage?.setItem(PREFS_KEY, JSON.stringify(prefs));
  } catch {
    /* cota cheia ou storage indisponível: preferência só na memória */
  }
}

// ------------------------------------------------------------------ rascunho

export interface Draft {
  version: 1;
  calibration_id: string;
  base_version: number;
  tables: Record<string, CellEdit[]>;
}

const draftSchema = z.object({
  version: z.literal(1),
  calibration_id: z.string(),
  base_version: z.number().int().min(1),
  tables: z.record(
    z.string(),
    z.array(z.object({ row: z.number().int().min(0), col: z.number().int().min(0), value: z.number() })),
  ),
});

export type DraftLoad = { kind: "none" } | { kind: "ok"; draft: Draft } | { kind: "corrupt" };

export function draftKey(calibrationId: string): string {
  return `${DRAFT_PREFIX}${calibrationId}`;
}

export function loadDraft(calibrationId: string, storage: Storage | null = defaultStorage()): DraftLoad {
  const raw = storage?.getItem(draftKey(calibrationId));
  if (!raw) return { kind: "none" };
  try {
    const parsed = draftSchema.safeParse(JSON.parse(raw));
    if (parsed.success && parsed.data.calibration_id === calibrationId) return { kind: "ok", draft: parsed.data };
  } catch {
    /* JSON inválido: cai no descarte */
  }
  storage?.removeItem(draftKey(calibrationId));
  return { kind: "corrupt" };
}

export function saveDraft(draft: Draft, storage: Storage | null = defaultStorage()): void {
  const hasCells = Object.values(draft.tables).some((cells) => cells.length > 0);
  try {
    if (!hasCells) storage?.removeItem(draftKey(draft.calibration_id));
    else storage?.setItem(draftKey(draft.calibration_id), JSON.stringify(draft));
  } catch {
    /* storage indisponível */
  }
}

export function clearDraft(calibrationId: string, storage: Storage | null = defaultStorage()): void {
  try {
    storage?.removeItem(draftKey(calibrationId));
  } catch {
    /* ignora */
  }
}

// ------------------------------------------------------------------ λ ↔ AFR (RF-22)

/** Tabelas cujo valor é lambda (exibíveis em AFR). */
export const LAMBDA_KINDS: ReadonlySet<string> = new Set(["lambda_target", "lambda_component_protection"]);

export function isLambdaTable(kind: string): boolean {
  return LAMBDA_KINDS.has(kind);
}

export function lambdaToAfr(lambda: number, afrStoich: number): number {
  return lambda * afrStoich;
}

export function afrToLambda(afr: number, afrStoich: number): number {
  return afr / afrStoich;
}
