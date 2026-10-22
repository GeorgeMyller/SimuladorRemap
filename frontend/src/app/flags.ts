/**
 * Flags de funcionalidade do frontend (Vite, `import.meta.env`). Padrão ligada;
 * `"false"`, `"0"` ou `"off"` desligam (rollout das features dyno-cockpit e ecu-tuning).
 */
export interface FeatureFlags {
  dynoCockpit: boolean;
  ecuTuning: boolean;
}

export function flagEnabled(raw: unknown): boolean {
  if (typeof raw !== "string") return raw !== false;
  return !["false", "0", "off"].includes(raw.trim().toLowerCase());
}

/** Lê as flags no momento da chamada (os testes usam `vi.stubEnv`). */
export function readFeatureFlags(env: Record<string, unknown> = import.meta.env): FeatureFlags {
  return {
    dynoCockpit: flagEnabled(env.VITE_FEATURE_DYNO_COCKPIT),
    ecuTuning: flagEnabled(env.VITE_FEATURE_ECU_TUNING),
  };
}
