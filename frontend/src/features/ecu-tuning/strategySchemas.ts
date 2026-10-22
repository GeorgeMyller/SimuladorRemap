/**
 * Esquemas zod das 9 estratégias (`StrategyConfig` do ecu-core, `simremap/ecu/contracts.py`)
 * e dos campos de cada formulário (tuning RF-14, EC-13). Espelho dos limites Pydantic
 * (`ge`/`gt`/`le`/`lt`, `Literal`, `extra="forbid"` e os `model_validator`); o teste de paridade
 * `fixtures/strategy-parity.json` corre nos dois lados (vitest e pytest).
 */
import { z } from "zod";

export type StrategyKind =
  | "closed_loop"
  | "knock_control"
  | "boost_control"
  | "rev_limiter"
  | "two_step"
  | "antilag"
  | "powershift"
  | "overrun"
  | "failsafe";

export const STRATEGY_KINDS: readonly StrategyKind[] = [
  "boost_control",
  "rev_limiter",
  "two_step",
  "antilag",
  "powershift",
  "overrun",
  "closed_loop",
  "knock_control",
  "failsafe",
];

export const STRATEGY_LABEL: Record<StrategyKind, string> = {
  closed_loop: "Malha fechada (lambda)",
  knock_control: "Controle de detonação",
  boost_control: "Controle de boost (PID e por marcha)",
  rev_limiter: "Limitador de rotação",
  two_step: "Two-step (largada)",
  antilag: "Antilag",
  powershift: "Powershift (troca sem tirar o pé)",
  overrun: "Overrun / pops & bangs",
  failsafe: "Failsafe (proteções)",
};

interface NumberField {
  type: "number";
  name: string;
  label: string;
  unit?: string;
  ge?: number;
  gt?: number;
  le?: number;
  step?: number;
  default: number;
}
interface BoolField {
  type: "bool";
  name: string;
  label: string;
  default: boolean;
}
interface EnumField {
  type: "enum";
  name: string;
  label: string;
  options: readonly { value: string; label: string }[];
  default: string;
}
export type FieldSpec = NumberField | BoolField | EnumField;

const n = (name: string, label: string, unit: string | undefined, def: number, lim: { ge?: number; gt?: number; le?: number; step?: number }): NumberField => ({ type: "number", name, label, unit, default: def, ...lim });
const b = (name: string, label: string, def: boolean): BoolField => ({ type: "bool", name, label, default: def });
const e = (name: string, label: string, def: string, options: [string, string][]): EnumField => ({ type: "enum", name, label, default: def, options: options.map(([value, l]) => ({ value, label: l })) });

const CUT_MODE: [string, string][] = [
  ["fuel_cut", "Corte de combustível"],
  ["spark_cut", "Corte de ignição"],
  ["rolling_cut", "Corte rotativo"],
];

export const STRATEGY_FIELDS: Record<Exclude<StrategyKind, "failsafe">, FieldSpec[]> = {
  closed_loop: [
    b("enabled", "Ativa", true),
    n("kp", "Ganho proporcional", "-", 0.5, { ge: 0, le: 5, step: 0.05 }),
    n("ki_per_s", "Ganho integral", "1/s", 2, { ge: 0, le: 20, step: 0.1 }),
    n("trim_limit_pct", "Limite de correção", "%", 25, { ge: 0, le: 25 }),
    n("min_ect_c", "Temperatura mínima do motor", "°C", 60, { ge: -40, le: 120 }),
    n("rpm_min", "Rotação mínima", "rpm", 800, { ge: 0 }),
    n("rpm_max", "Rotação máxima", "rpm", 7500, { le: 12000 }),
    n("map_max_kpa", "MAP máximo", "kPa", 400, { le: 500 }),
    n("delay_after_start_s", "Atraso após a partida", "s", 10, { ge: 0, le: 120 }),
    b("ltft_enabled", "Correção de longo prazo", false),
    n("ltft_rate_pct_s", "Taxa da correção longa", "%/s", 0.5, { ge: 0, le: 5, step: 0.1 }),
    n("ltft_limit_pct", "Limite da correção longa", "%", 15, { ge: 0, le: 25 }),
  ],
  knock_control: [
    b("enabled", "Ativa", true),
    n("retard_step_deg", "Passo de atraso", "°", 2, { gt: 0, le: 5, step: 0.5 }),
    n("max_retard_deg", "Atraso máximo", "°", 8, { gt: 0, le: 15, step: 0.5 }),
    n("recovery_hold_s", "Espera antes de recuperar", "s", 0.5, { ge: 0, le: 10, step: 0.1 }),
    n("recovery_deg_per_s", "Taxa de recuperação", "°/s", 1, { gt: 0, le: 10, step: 0.1 }),
    n("rpm_min", "Rotação mínima", "rpm", 1500, { ge: 0 }),
    n("map_min_kpa", "MAP mínimo", "kPa", 80, { ge: 0 }),
    n("boost_reduction_kpa_at_max", "Redução de boost no atraso máximo", "kPa", 20, { ge: 0, le: 100 }),
    n("max_retard_hold_s", "Tempo no atraso máximo", "s", 2, { ge: 0.1, le: 10, step: 0.1 }),
  ],
  boost_control: [
    b("enabled", "Ativa", true),
    e("mode", "Modo", "closed_loop", [
      ["open_loop", "Malha aberta (duty base)"],
      ["closed_loop", "Malha fechada (PID)"],
    ]),
    n("kp_pct_per_kpa", "PID: Kp", "%/kPa", 0.4, { ge: 0, le: 10, step: 0.05 }),
    n("ki_pct_per_kpa_s", "PID: Ki", "%/(kPa·s)", 0.8, { ge: 0, le: 20, step: 0.05 }),
    n("kd_pct_s_per_kpa", "PID: Kd", "%·s/kPa", 0.02, { ge: 0, le: 2, step: 0.01 }),
    n("d_filter_tau_s", "Filtro do termo D", "s", 0.05, { gt: 0, le: 1, step: 0.01 }),
    n("pid_activation_window_kpa", "Janela de ativação do PID", "kPa", 20, { ge: 0, le: 200 }),
    n("integrator_limit_pct", "Limite do integrador", "%", 30, { ge: 0, le: 100 }),
    b("by_gear_enabled", "Alvo por marcha", false),
    n("overboost_kpa", "Sobrepressão (corte)", "kPa abs", 260, { ge: 100, le: 500 }),
    n("overboost_time_s", "Tempo de sobrepressão", "s", 0.1, { ge: 0, le: 2, step: 0.05 }),
    n("overboost_hysteresis_kpa", "Histerese da sobrepressão", "kPa", 10, { ge: 0, le: 50 }),
    e("overboost_cut_mode", "Ação na sobrepressão", "wastegate_open", [
      ["wastegate_open", "Abrir a wastegate"],
      ["fuel_cut", "Corte de combustível"],
      ["spark_cut", "Corte de ignição"],
    ]),
  ],
  rev_limiter: [
    b("enabled", "Ativo", true),
    n("hard_rpm", "Corte (rpm)", "rpm", 7000, { ge: 1000, le: 12000, step: 50 }),
    e("cut_mode", "Tipo de corte", "fuel_cut", CUT_MODE),
    b("soft_enabled", "Limitador suave", true),
    n("soft_window_rpm", "Janela suave", "rpm", 200, { ge: 0, le: 1000, step: 10 }),
    n("soft_retard_max_deg", "Atraso máximo na janela suave", "°", 10, { ge: 0, le: 30 }),
    n("hysteresis_rpm", "Histerese", "rpm", 100, { ge: 10, le: 500 }),
  ],
  two_step: [
    b("enabled", "Ativo", true),
    n("target_rpm", "Rotação de largada", "rpm", 4000, { ge: 1500, le: 9000, step: 50 }),
    e("cut_mode", "Tipo de corte", "spark_cut", CUT_MODE),
    n("ign_advance_deg", "Avanço na largada", "° BTDC", -5, { ge: -20, le: 30 }),
    n("lambda_target", "Lambda alvo", "λ", 0.85, { ge: 0.65, le: 1, step: 0.01 }),
    e("activation", "Ativação", "clutch", [
      ["clutch", "Embreagem"],
      ["launch_switch", "Botão de largada"],
    ]),
    n("max_speed_kmh", "Velocidade máxima", "km/h", 5, { ge: 0, le: 50 }),
    n("min_tps_pct", "Borboleta mínima", "%", 80, { ge: 0, le: 100 }),
    n("max_active_s", "Tempo máximo ativo", "s", 10, { gt: 0, le: 60 }),
    n("release_ramp_s", "Rampa de saída", "s", 0.2, { ge: 0, le: 2, step: 0.05 }),
  ],
  antilag: [
    b("enabled", "Ativo", true),
    e("activation", "Ativação", "switch", [
      ["switch", "Botão"],
      ["rolling", "Rolante (entre rotações)"],
    ]),
    n("rpm_min", "Rotação mínima", "rpm", 3000, { ge: 1000 }),
    n("rpm_max", "Rotação máxima", "rpm", 7000, { le: 12000 }),
    n("max_tps_pct", "Borboleta máxima", "%", 20, { ge: 0, le: 100 }),
    n("ign_advance_deg", "Avanço", "° BTDC", -15, { ge: -20, le: 10 }),
    n("lambda_target", "Lambda alvo", "λ", 0.8, { ge: 0.65, le: 1, step: 0.01 }),
    n("air_valve_pct", "Válvula de ar", "%", 15, { ge: 0, le: 100 }),
    e("cut_mode", "Tipo de corte", "rolling_cut", CUT_MODE),
    n("cut_fraction", "Fração de corte", "-", 0.25, { ge: 0, le: 0.75, step: 0.05 }),
    n("egt_max_c", "EGT máxima", "°C", 1000, { ge: 600, le: 1150 }),
    n("max_active_s", "Tempo máximo ativo", "s", 3, { gt: 0, le: 30 }),
    n("cooldown_s", "Arrefecimento", "s", 5, { ge: 0, le: 120 }),
  ],
  powershift: [
    b("enabled", "Ativo", true),
    e("trigger", "Gatilho", "shift_request", [
      ["shift_request", "Pedido de troca"],
      ["clutch", "Embreagem"],
    ]),
    n("min_tps_pct", "Borboleta mínima", "%", 80, { ge: 0, le: 100 }),
    n("min_rpm", "Rotação mínima", "rpm", 3000, { ge: 0 }),
    e("cut_mode", "Tipo de corte", "spark_cut", [
      ["fuel_cut", "Corte de combustível"],
      ["spark_cut", "Corte de ignição"],
    ]),
    n("cut_time_ms", "Tempo de corte", "ms", 120, { ge: 20, le: 500 }),
    n("resume_retard_deg", "Atraso na retomada", "°", 5, { ge: 0, le: 20 }),
    n("resume_ramp_s", "Rampa de retomada", "s", 0.15, { ge: 0, le: 2, step: 0.05 }),
  ],
  overrun: [
    b("enabled", "Ativo", true),
    b("dfco_enabled", "Corte em desaceleração (DFCO)", true),
    n("dfco_tps_max_pct", "DFCO: borboleta máxima", "%", 2, { ge: 0, le: 10 }),
    n("dfco_rpm_min", "DFCO: rotação mínima", "rpm", 1500, { ge: 500 }),
    n("dfco_resume_rpm", "DFCO: rotação de retomada", "rpm", 1200, { ge: 500 }),
    n("dfco_delay_s", "DFCO: atraso", "s", 0.5, { ge: 0, le: 5, step: 0.1 }),
    b("pops_enabled", "Pops & bangs", false),
    n("pops_rpm_min", "Pops: rotação mínima", "rpm", 2500, { ge: 1000 }),
    n("pops_rpm_max", "Pops: rotação máxima", "rpm", 6500, { le: 12000 }),
    n("pops_tps_max_pct", "Pops: borboleta máxima", "%", 5, { ge: 0, le: 20 }),
    n("fuel_cut_delay_s", "Janela de corte atrasado", "s", 1.5, { ge: 0, le: 5, step: 0.1 }),
    n("ign_advance_deg", "Avanço (negativo = ATDC)", "° BTDC", -15, { ge: -20, le: 10 }),
    n("lambda_target", "Lambda alvo", "λ", 0.9, { ge: 0.7, le: 1.1, step: 0.01 }),
    n("intensity_pct", "Intensidade", "%", 60, { ge: 0, le: 100 }),
    n("max_duration_s", "Duração máxima", "s", 2, { gt: 0, le: 5, step: 0.1 }),
    n("egt_turbine_max_c", "EGT máxima pré-turbina", "°C", 950, { ge: 600, le: 1100 }),
    b("catalyst_present", "Catalisador presente", true),
    n("catalyst_max_intensity_pct", "Intensidade máxima com catalisador", "%", 30, { ge: 0, le: 100 }),
    n("catalyst_max_duration_s", "Duração máxima com catalisador", "s", 0.5, { ge: 0, le: 5, step: 0.1 }),
  ],
};

function numberSchema(f: NumberField): z.ZodNumber {
  let s = z.number({ error: `${f.label}: digite um número` });
  if (f.ge !== undefined) s = s.min(f.ge, { error: `${f.label}: mínimo ${f.ge}` });
  if (f.gt !== undefined) s = s.gt(f.gt, { error: `${f.label}: deve ser maior que ${f.gt}` });
  if (f.le !== undefined) s = s.max(f.le, { error: `${f.label}: máximo ${f.le}` });
  return s;
}

function objectFor(kind: Exclude<StrategyKind, "failsafe">) {
  const shape: Record<string, z.ZodType> = { kind: z.literal(kind).default(kind) };
  for (const f of STRATEGY_FIELDS[kind]) {
    if (f.type === "number") shape[f.name] = numberSchema(f).default(f.default);
    else if (f.type === "bool") shape[f.name] = z.boolean().default(f.default);
    else shape[f.name] = z.enum(f.options.map((o) => o.value) as [string, ...string[]], { error: `${f.label}: opção inválida` }).default(f.default);
  }
  return z.strictObject(shape);
}

type Obj = Record<string, unknown>;
const num = (o: Obj, k: string) => o[k] as number;

function rangeCheck(o: Obj, ctx: z.RefinementCtx, lo: string, hi: string, msg: string) {
  if (num(o, hi) <= num(o, lo)) ctx.addIssue({ code: "custom", path: [hi], message: msg });
}

export const closedLoopSchema = objectFor("closed_loop").superRefine((o, ctx) => rangeCheck(o, ctx, "rpm_min", "rpm_max", "closed_loop rpm: o máximo deve ser maior que o mínimo"));
export const knockControlSchema = objectFor("knock_control").superRefine((o, ctx) => {
  if (num(o, "retard_step_deg") > num(o, "max_retard_deg")) ctx.addIssue({ code: "custom", path: ["retard_step_deg"], message: "retard_step_deg não pode exceder max_retard_deg" });
});
export const boostControlSchema = objectFor("boost_control");
export const revLimiterSchema = objectFor("rev_limiter").superRefine((o, ctx) => {
  if (o.soft_enabled === true && num(o, "soft_window_rpm") >= num(o, "hard_rpm")) ctx.addIssue({ code: "custom", path: ["soft_window_rpm"], message: "soft_window_rpm deve ser menor que hard_rpm" });
});
export const twoStepSchema = objectFor("two_step");
export const antilagSchema = objectFor("antilag").superRefine((o, ctx) => rangeCheck(o, ctx, "rpm_min", "rpm_max", "antilag rpm: o máximo deve ser maior que o mínimo"));
export const powershiftSchema = objectFor("powershift");
export const overrunSchema = objectFor("overrun").superRefine((o, ctx) => {
  if (num(o, "dfco_resume_rpm") >= num(o, "dfco_rpm_min")) ctx.addIssue({ code: "custom", path: ["dfco_resume_rpm"], message: "dfco_resume_rpm deve ser menor que dfco_rpm_min" });
  rangeCheck(o, ctx, "pops_rpm_min", "pops_rpm_max", "pops rpm: o máximo deve ser maior que o mínimo");
});

export const FAILSAFE_RULE_IDS = ["egt_high", "egt_critical", "lean_under_load", "ect_high", "oil_pressure_low", "overspeed", "sensor_fault"] as const;
export const FAILSAFE_ACTIONS = ["boost_reduce", "boost_cut", "rev_limit_reduce", "enrich", "ignition_retard", "fuel_cut"] as const;

export const FAILSAFE_RULE_LABEL: Record<(typeof FAILSAFE_RULE_IDS)[number], string> = {
  egt_high: "EGT alta",
  egt_critical: "EGT crítica",
  lean_under_load: "Pobre em carga",
  ect_high: "Motor quente",
  oil_pressure_low: "Pressão de óleo baixa",
  overspeed: "Sobre-rotação",
  sensor_fault: "Falha de sensor",
};

export const FAILSAFE_ACTION_LABEL: Record<(typeof FAILSAFE_ACTIONS)[number], string> = {
  boost_reduce: "Reduzir boost",
  boost_cut: "Cortar boost",
  rev_limit_reduce: "Baixar limitador",
  enrich: "Enriquecer",
  ignition_retard: "Atrasar ignição",
  fuel_cut: "Cortar combustível",
};

export const failsafeRuleSchema = z
  .strictObject({
    rule_id: z.enum(FAILSAFE_RULE_IDS),
    enabled: z.boolean().default(true),
    threshold: z.number({ error: "Limiar: digite um número" }),
    confirm_s: z.number().min(0, { error: "Confirmação: mínimo 0" }).max(5, { error: "Confirmação: máximo 5" }),
    actions: z.array(z.enum(FAILSAFE_ACTIONS)).min(1, { error: "Escolha pelo menos uma ação" }),
    action_value: z.number().default(0),
    release_s: z.number().min(0).max(60).default(2),
    latch_until_stop: z.boolean().default(false),
  })
  .superRefine((o, ctx) => {
    if (new Set(o.actions).size !== o.actions.length) ctx.addIssue({ code: "custom", path: ["actions"], message: "actions com duplicados" });
  });

export const failsafeSchema = z
  .strictObject({
    kind: z.literal("failsafe").default("failsafe"),
    enabled: z.boolean().default(true),
    rules: z.array(failsafeRuleSchema),
    overspeed_rpm: z.number().min(1000, { error: "Sobre-rotação: mínimo 1000" }).max(13000, { error: "Sobre-rotação: máximo 13000" }).default(7500),
  })
  .superRefine((o, ctx) => {
    const ids = o.rules.map((r) => r.rule_id);
    if (new Set(ids).size !== ids.length) ctx.addIssue({ code: "custom", path: ["rules"], message: "rules com rule_id duplicado" });
  });

export const STRATEGY_SCHEMAS: Record<StrategyKind, z.ZodType<Record<string, unknown>>> = {
  closed_loop: closedLoopSchema,
  knock_control: knockControlSchema,
  boost_control: boostControlSchema,
  rev_limiter: revLimiterSchema,
  two_step: twoStepSchema,
  antilag: antilagSchema,
  powershift: powershiftSchema,
  overrun: overrunSchema,
  failsafe: failsafeSchema,
};

/** União discriminada por `kind` (mesmo veredito do `StrategyConfig` Pydantic). */
export function validateStrategy(payload: unknown): { ok: true; data: Record<string, unknown> } | { ok: false; errors: { path: string; message: string }[] } {
  const kind = typeof payload === "object" && payload !== null ? (payload as Obj).kind : undefined;
  const schema = typeof kind === "string" && kind in STRATEGY_SCHEMAS ? STRATEGY_SCHEMAS[kind as StrategyKind] : null;
  if (!schema) return { ok: false, errors: [{ path: "kind", message: "kind desconhecido" }] };
  const parsed = schema.safeParse(payload);
  if (parsed.success) return { ok: true, data: parsed.data };
  return { ok: false, errors: parsed.error.issues.map((i) => ({ path: i.path.join("."), message: i.message })) };
}

export function isStrategyKind(v: string): v is StrategyKind {
  return v in STRATEGY_SCHEMAS;
}

/** Valores padrão do subtipo (formulário de estratégia ausente na calibração). */
export function strategyDefaults(kind: StrategyKind): Record<string, unknown> {
  if (kind === "failsafe") return { kind, enabled: true, rules: [], overspeed_rpm: 7500 };
  const out: Record<string, unknown> = { kind };
  for (const f of STRATEGY_FIELDS[kind]) out[f.name] = f.default;
  return out;
}
