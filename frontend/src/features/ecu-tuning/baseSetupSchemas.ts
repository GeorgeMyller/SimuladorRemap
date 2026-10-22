/**
 * Esquemas zod do `BaseSetup` (ecu-profiles `profiles/contracts.py`: `TriggerSetup`,
 * `InjectorSetup`, `FuelSetup`, `SensorSetup`, `ProtectionLimits`, `WizardInputs`) usados por
 * passo no `BaseSetupWizard` (tuning RF-15). Mensagens com o código estável da spec.
 */
import { z } from "zod";

export const BASE_STEPS = ["trigger", "injectors", "fuel", "sensors", "protection", "review"] as const;
export type BaseStep = (typeof BASE_STEPS)[number];

export const BASE_STEP_LABEL: Record<BaseStep, string> = {
  trigger: "Roda fônica",
  injectors: "Bicos injetores",
  fuel: "Combustível",
  sensors: "Sensores",
  protection: "Failsafe e limites",
  review: "Revisão",
};

export const TRIGGER_WHEELS = ["60-2", "36-1", "36-2", "24-1", "12-1", "4-0"] as const;
export const FUEL_IDS = ["e0", "e27", "e100", "podium"] as const;
export const NTC_CURVES = ["ntc_a", "ntc_b", "ntc_c"] as const;

const isPermutation = (order: number[]) => [...order].sort((a, b) => a - b).every((v, i) => v === i + 1);
const increasing = (xs: number[]) => xs.every((v, i) => i === 0 || v > xs[i - 1]!);

export const triggerSchema = z
  .strictObject({
    wheel: z.enum(TRIGGER_WHEELS),
    tdc_offset_deg: z.number().min(0, { error: "Ângulo do PMS: 0 a 359,9°" }).lt(360, { error: "Ângulo do PMS: 0 a 359,9°" }),
    phase_sensor: z.enum(["none", "cam_hall"]),
    phase_edge_deg: z.number().min(0).lt(720, { error: "Borda de fase: 0 a 719,9°" }),
    injection_mode: z.enum(["sequential", "semi_sequential", "batch"]),
    ignition_mode: z.enum(["sequential", "wasted_spark"]),
    firing_order: z.array(z.number().int()).min(3, { error: "FIRING_ORDER_INVALID" }).max(8, { error: "FIRING_ORDER_INVALID" }),
    timing_lock_deg: z.number().min(-5, { error: "Trava de ponto: −5 a 30°" }).max(30, { error: "Trava de ponto: −5 a 30°" }).nullable(),
  })
  .superRefine((o, ctx) => {
    if (!isPermutation(o.firing_order)) ctx.addIssue({ code: "custom", path: ["firing_order"], message: "FIRING_ORDER_INVALID: a ordem de ignição deve ser uma permutação de 1..n" });
    if ((o.injection_mode === "sequential" || o.ignition_mode === "sequential") && o.phase_sensor === "none") {
      ctx.addIssue({ code: "custom", path: ["phase_sensor"], message: "SEQUENTIAL_REQUIRES_PHASE_SENSOR: o modo sequencial exige sensor de fase" });
    }
  });

export const injectorsSchema = z
  .strictObject({
    flow_cc_min: z.number().gt(0, { error: "Vazão: maior que 0" }).max(5000, { error: "Vazão: máximo 5000 cc/min" }),
    ref_pressure_kpa: z.number().min(200).max(600),
    dead_time_v: z.array(z.number()).min(2).max(16),
    dead_time_ms: z.array(z.number()).min(2).max(16),
    fuel_pressure_mode: z.enum(["fixed_rail", "map_referenced"]),
    rail_pressure_kpa: z.number().min(200, { error: "Pressão da linha: 200 a 800 kPa" }).max(800, { error: "Pressão da linha: 200 a 800 kPa" }),
  })
  .superRefine((o, ctx) => {
    if (o.dead_time_ms.length !== o.dead_time_v.length) ctx.addIssue({ code: "custom", path: ["dead_time_ms"], message: "DEAD_TIME_SHAPE_MISMATCH" });
    if (!increasing(o.dead_time_v)) ctx.addIssue({ code: "custom", path: ["dead_time_v"], message: "TABLE_AXIS_NOT_MONOTONIC" });
    if (o.dead_time_ms.some((v) => v < 0 || v > 5)) ctx.addIssue({ code: "custom", path: ["dead_time_ms"], message: "DEAD_TIME_OUT_OF_RANGE: tempo morto entre 0 e 5 ms" });
  });

export const fuelSchema = z.strictObject({
  fuel_id: z.enum(FUEL_IDS),
  afr_stoich: z.number().min(8, { error: "AFR estequiométrico: 8 a 15,5" }).max(15.5, { error: "AFR estequiométrico: 8 a 15,5" }),
  density_g_cc: z.number().min(0.68, { error: "Densidade: 0,68 a 0,82 g/cc" }).max(0.82, { error: "Densidade: 0,68 a 0,82 g/cc" }),
});

export const sensorsSchema = z.strictObject({
  map: z.strictObject({
    min_kpa: z.number().min(0, { error: "MAP a 0,5 V: 0 a 50 kPa" }).max(50, { error: "MAP a 0,5 V: 0 a 50 kPa" }),
    max_kpa: z.number().min(100, { error: "MAP a 4,5 V: 100 a 700 kPa" }).max(700, { error: "MAP a 4,5 V: 100 a 700 kPa" }),
  }),
  iat: z.strictObject({ curve: z.enum(NTC_CURVES) }),
  ect: z.strictObject({ curve: z.enum(NTC_CURVES) }),
  wideband: z
    .strictObject({ lambda_at_0v: z.number().min(0.4).max(1), lambda_at_5v: z.number().min(1).max(2.5) })
    .refine((w) => w.lambda_at_5v > w.lambda_at_0v, { path: ["lambda_at_5v"], message: "lambda_at_5v deve ser maior que lambda_at_0v" })
    .nullable(),
});

export const protectionSchema = z
  .strictObject({
    rev_limit_rpm: z.number().min(2000, { error: "Corte: 2000 a 12000 rpm" }).max(12000, { error: "Corte: 2000 a 12000 rpm" }),
    overspeed_rpm: z.number().min(2000).max(13000),
    overboost_kpa: z.number().min(100, { error: "Sobrepressão: 100 a 500 kPa" }).max(500, { error: "Sobrepressão: 100 a 500 kPa" }),
    egt_max_c: z.number().min(600).max(1100),
    ect_max_c: z.number().min(80).max(130),
    oil_pressure_min_kpa: z.number().min(0).max(600),
    lean_delta_lambda: z.number().min(0.03).max(0.3),
  })
  .refine((p) => p.overspeed_rpm > p.rev_limit_rpm, { path: ["overspeed_rpm"], message: "OVERSPEED_BELOW_REV_LIMIT: a sobre-rotação deve ser maior que o corte" });

export const wizardSchema = z.strictObject({
  max_map_kpa: z.number().min(100, { error: "MAP máximo: 100 a 450 kPa" }).max(450, { error: "MAP máximo: 100 a 450 kPa" }),
  rev_limit_rpm: z.number().min(2000).max(12000).nullable(),
  idle_rpm: z.number().min(600, { error: "Marcha lenta: 600 a 1500 rpm" }).max(1500, { error: "Marcha lenta: 600 a 1500 rpm" }),
  grid: z.union([z.literal(12), z.literal(16), z.literal(20)]),
  fuel_model_mode: z.enum(["speed_density_ve", "direct_pulse_ms"]).nullable(),
});

export const STEP_SCHEMAS = {
  trigger: triggerSchema,
  injectors: injectorsSchema,
  fuel: fuelSchema,
  sensors: sensorsSchema,
  protection: protectionSchema,
  review: wizardSchema,
} as const;

/** AFR estequiométrico e densidade padrão por combustível (quando o catálogo não informa). */
export const FUEL_DEFAULTS: Record<(typeof FUEL_IDS)[number], { afr: number; density: number; label: string }> = {
  e0: { afr: 14.7, density: 0.74, label: "Gasolina pura (E0)" },
  e27: { afr: 13.2, density: 0.75, label: "Gasolina comum (E27)" },
  e100: { afr: 9.0, density: 0.79, label: "Etanol (E100)" },
  podium: { afr: 13.2, density: 0.75, label: "Gasolina de alta octanagem" },
};
