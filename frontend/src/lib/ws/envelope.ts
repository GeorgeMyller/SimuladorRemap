/**
 * Schemas zod do envelope WebSocket v1 (contracts/websocket-telemetry.md §2–§4).
 * O cliente valida `v = 1`, `type` conhecido, `seq` inteiro ≥ 0 e o payload mínimo por tipo.
 */
import { z } from "zod";

export const WS_SERVER_TYPES = [
  "telemetry.frame",
  "run.state",
  "event.knock",
  "event.failure",
  "event.limiter",
  "error",
] as const;

export type WsServerType = (typeof WS_SERVER_TYPES)[number];

export const wsEnvelopeSchema = z.object({
  v: z.literal(1),
  type: z.enum(WS_SERVER_TYPES),
  seq: z.number().int().min(0),
  t_sim_s: z.number().min(0),
  payload: z.record(z.string(), z.unknown()),
});

export type WsEnvelope = z.infer<typeof wsEnvelopeSchema>;

export const knockSpectrumSchema = z.looseObject({
  bins_hz: z.array(z.number()),
  magnitude_db: z.array(z.number()),
  resonance_hz: z.array(z.number()).default([]),
  sensor: z.string().optional(),
});
export type KnockSpectrum = z.infer<typeof knockSpectrumSchema>;

export const pressureTraceSchema = z.looseObject({
  cylinder: z.number().int().min(1),
  crank_deg: z.array(z.number()),
  p_bar: z.array(z.number()),
});
export type PressureTrace = z.infer<typeof pressureTraceSchema>;

export const frameStatsSchema = z.looseObject({
  fps_actual: z.number(),
  dropped_frames: z.number().int().min(0),
  dropped_events: z.number().int().min(0),
  real_time_factor: z.number().nullable(),
  tick: z.number().int(),
});

export const telemetryFramePayloadSchema = z.looseObject({
  session_id: z.string(),
  run_id: z.string().nullable(),
  frame_index: z.number().int().min(0),
  window_ticks: z.number().int().optional(),
  channels: z.record(z.string(), z.number().nullable()),
  knock_spectrum: knockSpectrumSchema.nullish(),
  cyl_pressure_trace: pressureTraceSchema.nullish(),
  stats: frameStatsSchema.optional(),
});
export type TelemetryFramePayload = z.infer<typeof telemetryFramePayloadSchema>;

export const RUN_STATES = [
  "idle",
  "arming",
  "running",
  "coastdown",
  "completed",
  "aborted",
  "engine_failed",
] as const;
export type RunState = (typeof RUN_STATES)[number];

export const runStatePayloadSchema = z.looseObject({
  session_id: z.string().optional(),
  run_id: z.string().nullable(),
  run_type: z.string().nullish(),
  state: z.enum(RUN_STATES),
  previous_state: z.string().nullish(),
  phase: z.string().nullish(),
  pull_index: z.number().nullish(),
  pull_count: z.number().nullish(),
  abort_reason: z.string().nullish(),
  progress_pct: z.number().nullish(),
  rpm: z.number().nullish(),
  realtime_factor: z.number().nullish(),
  forensic_report_url: z.string().nullish(),
});
export type RunStatePayload = z.infer<typeof runStatePayloadSchema>;

export const knockEventPayloadSchema = z.looseObject({
  run_id: z.string().nullish(),
  cylinder: z.number().int().min(1),
  knock_class: z.enum(["light", "moderate", "severe"]),
  intensity: z.number(),
  retard_deg: z.number(),
  rpm: z.number(),
  intensity_raw: z.number().optional(),
  p_max_bar: z.number().optional(),
  threshold: z.number().nullish(),
  simulated_only: z.boolean().optional(),
});
export type KnockEventPayload = z.infer<typeof knockEventPayloadSchema>;

export const FAILURE_MODES = [
  "knock_damage",
  "pre_ignition",
  "egt_overtemp",
  "rod_failure",
  "piston_failure",
  "turbo_meltdown",
] as const;

export const failureEventPayloadSchema = z.looseObject({
  failure_event_id: z.string(),
  session_id: z.string().optional(),
  run_id: z.string().nullable(),
  tick: z.number().int().optional(),
  t_sim_s: z.number(),
  cylinder: z.number().int().nullable(),
  component_id: z.string(),
  mode: z.enum(FAILURE_MODES),
  mechanism: z.string().optional(),
  catastrophic: z.boolean(),
  simulated_only: z.boolean().optional(),
  health_after: z.number().optional(),
  causal_variables: z.record(z.string(), z.number()).default({}),
});
export type FailureEventPayload = z.infer<typeof failureEventPayloadSchema>;

export const limiterEventPayloadSchema = z.looseObject({
  run_id: z.string().nullish(),
  kind: z.enum(["rev_limiter", "two_step", "overboost_cut", "antilag_protect", "overrun_protect"]),
  phase: z.enum(["soft", "hard"]).nullable().optional(),
  active: z.boolean(),
  rpm: z.number(),
});
export type LimiterEventPayload = z.infer<typeof limiterEventPayloadSchema>;

export const wsErrorPayloadSchema = z.looseObject({
  code: z.string().regex(/^[A-Z][0-9A-Z_]{2,63}$/),
  title: z.string(),
  detail: z.string().default(""),
  fatal: z.boolean().default(false),
  oldest_available_seq: z.number().int().nullish(),
});
export type WsErrorPayload = z.infer<typeof wsErrorPayloadSchema>;

/** Envelope já validado e com payload tipado. */
export type TypedEnvelope =
  | { type: "telemetry.frame"; seq: number; t_sim_s: number; payload: TelemetryFramePayload }
  | { type: "run.state"; seq: number; t_sim_s: number; payload: RunStatePayload }
  | { type: "event.knock"; seq: number; t_sim_s: number; payload: KnockEventPayload }
  | { type: "event.failure"; seq: number; t_sim_s: number; payload: FailureEventPayload }
  | { type: "event.limiter"; seq: number; t_sim_s: number; payload: LimiterEventPayload }
  | { type: "error"; seq: number; t_sim_s: number; payload: WsErrorPayload };

const payloadSchemas = {
  "telemetry.frame": telemetryFramePayloadSchema,
  "run.state": runStatePayloadSchema,
  "event.knock": knockEventPayloadSchema,
  "event.failure": failureEventPayloadSchema,
  "event.limiter": limiterEventPayloadSchema,
  error: wsErrorPayloadSchema,
} as const;

/**
 * Decodifica uma mensagem de texto. Devolve `null` para JSON malformado,
 * `v` ≠ 1, `type` desconhecido ou payload fora do contrato (EC-04). Nunca lança.
 */
export function parseEnvelope(raw: unknown): TypedEnvelope | null {
  let data: unknown;
  if (typeof raw === "string") {
    try {
      data = JSON.parse(raw);
    } catch {
      return null;
    }
  } else {
    data = raw;
  }
  const env = wsEnvelopeSchema.safeParse(data);
  if (!env.success) return null;
  const payload = payloadSchemas[env.data.type].safeParse(env.data.payload);
  if (!payload.success) return null;
  return { type: env.data.type, seq: env.data.seq, t_sim_s: env.data.t_sim_s, payload: payload.data } as TypedEnvelope;
}

/** Payload de `control.subscribe` (§4.1). */
export interface TelemetrySubscription {
  channels: string[];
  fps?: number;
  spectrum?: boolean;
  pressure_trace?: { cylinder: number } | null;
}

export type WsClientMessage =
  | { v: 1; type: "control.subscribe"; payload: TelemetrySubscription }
  | { v: 1; type: "control.throttle"; payload: { throttle_pct: number } }
  | { v: 1; type: "control.ping"; payload: { nonce: string } };
