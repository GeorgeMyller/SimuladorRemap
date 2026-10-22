/**
 * Preferências da cockpit em `localStorage` (`simremap.cockpit.prefs.v1`, data-model §4.3).
 * JSON inválido, versão diferente ou campo fora do schema ⇒ padrões.
 */
import { z } from "zod";

import { DEFAULT_UNITS, type UnitsPrefs } from "@/lib/units";

export const PREFS_KEY = "simremap.cockpit.prefs.v1";

export const PANEL_IDS = [
  "dyno",
  "lambda-egt",
  "car",
  "gauges",
  "spectrogram",
  "pressure",
  "events",
  "datalogger",
] as const;
export type PanelId = (typeof PANEL_IDS)[number];

/** Id em `visiblePanels` que indica a faixa inferior expandida (a aba ativa é a visível). */
export const BOTTOM_STRIP = "bottom";
export const TOP_PANELS = ["dyno", "lambda-egt", "car", "gauges"] as const;

/** Painéis efetivamente visíveis para a subscrição: topo expandido + aba inferior ativa. */
export function visibleForSubscription(prefs: Pick<CockpitPrefs, "visiblePanels" | "activeBottomTab">): PanelId[] {
  const out: PanelId[] = TOP_PANELS.filter((p) => prefs.visiblePanels.includes(p));
  if (prefs.visiblePanels.includes(BOTTOM_STRIP)) out.push(prefs.activeBottomTab);
  return out;
}

export const BOTTOM_TABS = ["spectrogram", "pressure", "events", "datalogger"] as const;
export type BottomTab = (typeof BOTTOM_TABS)[number];

export interface AudioPrefs {
  enabled: boolean;
  muted: boolean;
  /** 0..1 */
  volume: number;
}

export interface CockpitPrefs {
  version: 1;
  units: UnitsPrefs;
  audio: AudioPrefs;
  visiblePanels: string[];
  activeBottomTab: BottomTab;
}

export const DEFAULT_PREFS: CockpitPrefs = {
  version: 1,
  units: DEFAULT_UNITS,
  audio: { enabled: false, muted: false, volume: 0.6 },
  visiblePanels: ["dyno", "lambda-egt", "car", "gauges", BOTTOM_STRIP],
  activeBottomTab: "spectrogram",
};

const prefsSchema = z.object({
  version: z.literal(1),
  units: z.object({
    power: z.enum(["whp", "cv", "kW"]),
    boost: z.enum(["bar", "psi"]),
    temperature: z.literal("C"),
    torque: z.literal("Nm"),
  }),
  audio: z.object({
    enabled: z.boolean(),
    muted: z.boolean(),
    volume: z.number().min(0).max(1),
  }),
  visiblePanels: z.array(z.string().max(32)).max(32),
  activeBottomTab: z.enum(BOTTOM_TABS),
});

function safeStorage(storage?: Storage | null): Storage | null {
  if (storage !== undefined) return storage;
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

export function loadPrefs(storage?: Storage | null): CockpitPrefs {
  const store = safeStorage(storage);
  if (!store) return structuredClone(DEFAULT_PREFS);
  let raw: string | null;
  try {
    raw = store.getItem(PREFS_KEY);
  } catch {
    return structuredClone(DEFAULT_PREFS);
  }
  if (!raw) return structuredClone(DEFAULT_PREFS);
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return structuredClone(DEFAULT_PREFS);
  }
  const parsed = prefsSchema.safeParse(data);
  return parsed.success ? parsed.data : structuredClone(DEFAULT_PREFS);
}

export function savePrefs(prefs: CockpitPrefs, storage?: Storage | null): void {
  const store = safeStorage(storage);
  if (!store) return;
  try {
    store.setItem(PREFS_KEY, JSON.stringify(prefs));
  } catch {
    /* quota ou modo privado: preferências só em memória */
  }
}
