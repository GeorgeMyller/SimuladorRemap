/**
 * Chamadas REST consumidas pela cockpit (contracts/rest-api.md §3). Schemas zod mínimos
 * e tolerantes (`looseObject`): a cockpit só lê os campos que usa.
 */
import { z } from "zod";

import { apiFetch, ApiProblem } from "@/lib/api";

export const sessionSchema = z.looseObject({
  session_id: z.string(),
  vehicle_id: z.string(),
  profile_id: z.string().default("oem-stage"),
  fuel_id: z.string().nullish(),
  state: z.enum(["ready", "running", "engine_locked", "closed"]),
  active_run_id: z.string().nullish(),
  baseline_run_id: z.string().nullish(),
  engine_locked: z.boolean().default(false),
  seed: z.number().optional(),
  t_sim_s: z.number().optional(),
  attempt_id: z.string().nullish(),
});
export type Session = z.infer<typeof sessionSchema>;

export const mechanicalLimitsSchema = z.looseObject({
  egt_max_c: z.number(),
  max_rpm: z.number(),
  rev_limit_rpm: z.number(),
  turbo_max_rpm: z.number().nullish(),
  max_cylinder_pressure_bar: z.number().optional(),
});
export type MechanicalLimits = z.infer<typeof mechanicalLimitsSchema>;

export const vehicleSchema = z.looseObject({
  vehicle_id: z.string(),
  display_name: z.string(),
  induction: z.enum(["turbo", "supercharger", "natural"]),
  stock_fuel_id: z.string().optional(),
  engine: z.looseObject({
    architecture: z.enum(["inline", "v"]),
    n_cyl: z.number().int().min(1).max(12),
    firing_order: z.array(z.number().int()),
    bore_mm: z.number().optional(),
  }),
  mechanical_limits: mechanicalLimitsSchema,
  rated: z
    .looseObject({ peak_power_whp: z.number(), peak_torque_nm: z.number() })
    .optional(),
  idle_rpm: z.number().optional(),
});
export type Vehicle = z.infer<typeof vehicleSchema>;

export const referenceCurvePointSchema = z.looseObject({
  rpm: z.number(),
  torque_crank_nm: z.number().nullish(),
  power_wheel_kw: z.number().nullish(),
  lambda_value: z.number().nullish(),
  egt_c: z.number().nullish(),
});
export const referenceCurveSchema = z.looseObject({
  curve_id: z.string(),
  fuel_id: z.string().optional(),
  points: z.array(referenceCurvePointSchema),
});
export type ReferenceCurve = z.infer<typeof referenceCurveSchema>;

export const referenceCurveListSchema = z.looseObject({
  vehicle_id: z.string(),
  items: z.array(referenceCurveSchema),
});

export const curvePointSchema = z.looseObject({
  rpm: z.number(),
  t_sim_s: z.number(),
  power_wheel_kw: z.number(),
  power_wheel_kw_corr: z.number().optional(),
  torque_wheel_nm: z.number().optional(),
  torque_engine_nm: z.number(),
  torque_engine_nm_corr: z.number().optional(),
  lambda: z.number(),
  egt_c: z.number(),
  map_kpa: z.number().optional(),
});
export type CurvePoint = z.infer<typeof curvePointSchema>;

export const runSummarySchema = z.looseObject({
  peak_whp: z.number(),
  peak_whp_rpm: z.number(),
  peak_torque_engine_nm: z.number(),
  peak_torque_rpm: z.number(),
  forensic_report_url: z.string().nullish(),
});

export const dynoRunSchema = z.looseObject({
  run_id: z.string(),
  session_id: z.string(),
  run_type: z.string(),
  state: z.string(),
  abort_reason: z.string().nullish(),
  summary: runSummarySchema.nullish(),
  curve: z.array(curvePointSchema).default([]),
  request: z.looseObject({ label: z.string().nullish() }).optional(),
});
export type DynoRun = z.infer<typeof dynoRunSchema>;

export const componentHealthSchema = z.looseObject({
  component_id: z.string(),
  health: z.number(),
  failed: z.boolean().default(false),
});
export type ComponentHealth = z.infer<typeof componentHealthSchema>;

export const engineHealthSchema = z.looseObject({
  session_id: z.string(),
  engine_locked: z.boolean(),
  components: z.array(componentHealthSchema).default([]),
  integrity_pct: z.number().optional(),
  restore_count: z.number().optional(),
});
export type EngineHealth = z.infer<typeof engineHealthSchema>;

export const causalLinkSchema = z.looseObject({
  order: z.number().int(),
  t_sim_s: z.number(),
  kind: z.string(),
  cylinder: z.number().int().nullish(),
  variable: z.string(),
  value: z.number(),
  threshold: z.number().nullish(),
  unit: z.string(),
  description: z.string(),
});
export type CausalLink = z.infer<typeof causalLinkSchema>;

export const recommendationSchema = z.looseObject({
  rule_id: z.string(),
  action: z.string(),
  table_id: z.string(),
  cylinders: z.array(z.number()).default([]),
  rationale: z.string(),
  region: z.string().nullish(),
});

export const forensicReportSchema = z.looseObject({
  report_id: z.string(),
  report_kind: z.enum(["failure", "near_miss"]),
  run_id: z.string(),
  vehicle_id: z.string().optional(),
  failure_event: z
    .looseObject({
      component_id: z.string(),
      mode: z.string(),
      cylinder: z.number().int().nullish(),
      t_sim_s: z.number(),
      catastrophic: z.boolean(),
    })
    .nullish(),
  primary_mode: z.string().nullish(),
  damaged_components: z.array(componentHealthSchema).default([]),
  causal_chain: z.array(causalLinkSchema).min(1),
  recommendations: z.array(recommendationSchema).default([]),
  texts: z
    .record(
      z.string(),
      z.looseObject({ title: z.string(), summary: z.string(), explanation: z.string() }),
    )
    .default({}),
});
export type ForensicReport = z.infer<typeof forensicReportSchema>;

export const healthStatusSchema = z.looseObject({
  status: z.enum(["ok", "degraded", "down"]),
});

export const profileSchema = z.looseObject({ profile_id: z.string(), name: z.string() });

export const dataLogSchema = z.looseObject({
  header: z.looseObject({
    run_id: z.string(),
    channels: z.array(z.looseObject({ name: z.string(), unit: z.string().optional() })),
    terminal_state: z.string().optional(),
  }),
  t_sim_s: z.array(z.number()),
  data: z.record(z.string(), z.array(z.number().nullable())),
  sha256: z.string().optional(),
});
export type DataLog = z.infer<typeof dataLogSchema>;

export const logComparisonSchema = z.looseObject({
  bin_rpm: z.number(),
  bins: z.array(
    z.looseObject({
      rpm_bin: z.number(),
      power_kw_a: z.number(),
      power_kw_b: z.number(),
      torque_nm_a: z.number(),
      torque_nm_b: z.number(),
    }),
  ),
  peak_whp_a: z.number(),
  peak_whp_b: z.number(),
  delta_peak_whp_pct: z.number(),
  max_abs_delta: z.record(z.string(), z.number()),
});
export type LogComparison = z.infer<typeof logComparisonSchema>;

export const importSummarySchema = z.looseObject({ log_id: z.string(), run_id: z.string().nullish() });

export type RunType = "baseline_pull" | "sweep_pull" | "steady_state_hold" | "multi_pull";

export interface DynoRunRequest {
  run_type: RunType;
  gear?: number;
  start_rpm?: number;
  end_rpm?: number | null;
  pedal_pct?: number;
  ramp_rate_rpm_s?: number;
  cells?: { rpm: number; pedal_pct: number; hold_s?: number }[];
  pull_count?: number;
  label?: string;
}

const enc = encodeURIComponent;

export const cockpitApi = {
  getSession: (id: string) => apiFetch(`/sessions/${enc(id)}`, { schema: sessionSchema }),
  getVehicle: (id: string) => apiFetch(`/vehicles/${enc(id)}`, { schema: vehicleSchema }),
  getReferenceCurves: (id: string) =>
    apiFetch(`/vehicles/${enc(id)}/reference-curves`, { schema: referenceCurveListSchema }),
  getProfile: (id: string) => apiFetch(`/ecu-profiles/${enc(id)}`, { schema: profileSchema }),
  getHealth: () => apiFetch("/health", { schema: healthStatusSchema }),
  startRun: (sessionId: string, req: DynoRunRequest) =>
    apiFetch(`/sessions/${enc(sessionId)}/runs`, { method: "POST", json: req, schema: dynoRunSchema }),
  abortRun: (sessionId: string, runId: string) =>
    apiFetch(`/sessions/${enc(sessionId)}/runs/${enc(runId)}/abort`, { method: "POST", schema: dynoRunSchema }),
  getRun: (runId: string) => apiFetch(`/runs/${enc(runId)}`, { schema: dynoRunSchema }),
  getForensicReport: (runId: string) =>
    apiFetch(`/runs/${enc(runId)}/forensic-report`, { schema: forensicReportSchema }),
  restoreEngine: (sessionId: string) =>
    apiFetch(`/sessions/${enc(sessionId)}/engine/restore`, { method: "POST", json: {}, schema: engineHealthSchema }),
  getLog: (runId: string) => apiFetch(`/runs/${enc(runId)}/log?format=json`, { schema: dataLogSchema }),
  compareLogs: (a: string, b: string) =>
    apiFetch("/logs/compare", {
      method: "POST",
      json: { a: { run_id: a }, b: { run_id: b } },
      schema: logComparisonSchema,
    }),
  importLog: (body: string) =>
    apiFetch("/logs/import", {
      method: "POST",
      body,
      headers: { "Content-Type": "application/json" },
      schema: importSummarySchema,
    }),
};

export type CockpitApi = typeof cockpitApi;

/** Descarrega um ficheiro de texto/blob no navegador com o nome indicado. */
export function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

/** Export do log (`GET /api/v1/runs/{run_id}/log`) como download `run-<run_id>.<fmt>` (RF-17). */
export async function exportRunLog(runId: string, format: "json" | "csv", fetchImpl: typeof fetch = fetch): Promise<string> {
  const response = await fetchImpl(`/api/v1/runs/${enc(runId)}/log?format=${format}`, {
    headers: { Accept: format === "csv" ? "text/csv" : "application/json" },
  });
  if (!response.ok) {
    throw ApiProblem.synthetic(response.status, response.status === 409 ? "LOG_NOT_READY" : "LOG_NOT_FOUND", `Falha ao exportar o log (HTTP ${response.status}).`);
  }
  const blob = await response.blob();
  const filename = `run-${runId}.${format}`;
  triggerDownload(blob, filename);
  return filename;
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Busca o laudo com 3 retries automáticos (1 s, 2 s, 4 s) em 404/5xx/timeout;
 * 409 `FORENSIC_REPORT_PENDING` também espera e repete (EC-07).
 */
export async function fetchForensicReportWithRetry(
  runId: string,
  api: Pick<CockpitApi, "getForensicReport"> = cockpitApi,
  delays: readonly number[] = [1000, 2000, 4000],
): Promise<ForensicReport> {
  let lastError: unknown;
  for (let attempt = 0; attempt <= delays.length; attempt += 1) {
    try {
      return await api.getForensicReport(runId);
    } catch (error) {
      lastError = error;
      if (error instanceof ApiProblem && error.status >= 400 && error.status < 500 && error.status !== 404 && error.status !== 409) {
        throw error;
      }
      const delay = delays[attempt];
      if (delay === undefined) break;
      await sleep(delay);
    }
  }
  throw lastError;
}
