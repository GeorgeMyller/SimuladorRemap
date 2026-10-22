/**
 * Schemas zod das respostas consumidas pelo editor de ECU (contracts/rest-api.md §3.2, §3.3,
 * §3.5 e §3.6). Tolerantes (`looseObject`): o editor só lê os campos que usa e preserva o
 * resto do JSON da calibração para o `PUT` (E-18).
 */
import { z } from "zod";

export const ECU_PROFILE_IDS = ["oem-stage", "ft-pro", "m1-race", "ht-elite"] as const;
export type EcuProfileId = (typeof ECU_PROFILE_IDS)[number];

// ------------------------------------------------------------------ calibração (ecu-core)

export const axisViewSchema = z.looseObject({
  quantity: z.string(),
  values: z.array(z.number()).min(2).max(32),
  unit: z.string().default(""),
  source_channel: z.string().optional(),
});
export type AxisView = z.infer<typeof axisViewSchema>;

export const tableViewSchema = z.looseObject({
  table_id: z.string(),
  kind: z.string(),
  unit: z.string(),
  dims: z.union([z.literal(2), z.literal(3)]).optional(),
  live_tunable: z.boolean().default(false),
  cylinder: z.number().int().nullish(),
  description: z.string().default(""),
  decimals: z.number().int().min(0).max(4).default(1),
  min: z.number(),
  max: z.number(),
  x: axisViewSchema,
  y: axisViewSchema.nullish(),
  values: z.union([z.array(z.array(z.number())), z.array(z.number())]),
});
export type TableView = z.infer<typeof tableViewSchema>;

export const calibrationVersionInfoSchema = z.looseObject({
  version: z.number().int(),
  parent_version: z.number().int().nullable(),
  content_hash: z.string(),
  source: z.string(),
  author_nickname: z.string().nullish(),
  change_summary: z.string().default(""),
  created_at: z.string(),
});
export type CalibrationVersionInfo = z.infer<typeof calibrationVersionInfoSchema>;

export const calibrationMetadataSchema = z.looseObject({
  name: z.string(),
  author_nickname: z.string().nullish(),
  notes: z.string().default(""),
  source: z.string().default("user"),
  change_summary: z.string().default(""),
  extra: z.record(z.string(), z.string()).default({}),
});
export type CalibrationMetadata = z.infer<typeof calibrationMetadataSchema>;

export const calibrationSchema = z.looseObject({
  calibration_id: z.string(),
  vehicle_id: z.string(),
  profile_id: z.string(),
  version: z.number().int().min(1),
  parent_version: z.number().int().nullish(),
  fuel_model: z.record(z.string(), z.unknown()).default({}),
  tables: z.record(z.string(), tableViewSchema),
  strategies: z.record(z.string(), z.looseObject({ kind: z.string() })).default({}),
  profile_params: z.record(z.string(), z.union([z.boolean(), z.number(), z.string()])).default({}),
  metadata: calibrationMetadataSchema,
  content_hash: z.string(),
  created_at: z.string().optional(),
  versions: z.array(calibrationVersionInfoSchema).nullish(),
});
export type Calibration = z.infer<typeof calibrationSchema>;

export const tablePatchResultSchema = z.looseObject({
  version: z.number().int(),
  content_hash: z.string(),
  table: tableViewSchema,
});
export type TablePatchResult = z.infer<typeof tablePatchResultSchema>;

export const applyCalibrationResultSchema = z.looseObject({
  session_id: z.string(),
  calibration_id: z.string(),
  version: z.number().int(),
  content_hash: z.string(),
  mode: z.enum(["full", "live_tables"]),
  changed_tables: z.array(z.string()),
  applied_t_sim_s: z.number(),
});
export type ApplyCalibrationResult = z.infer<typeof applyCalibrationResultSchema>;

export interface CellEdit {
  row: number;
  col: number;
  value: number;
}

export interface TablePatchBody {
  base_version: number;
  op: "set";
  cells: CellEdit[];
  change_summary?: string;
}

// ------------------------------------------------------------------ perfis (ecu-profiles)

export const navItemSchema = z.looseObject({
  id: z.string(),
  label: z.string(),
  kind: z.enum(["table", "strategy", "base_setup", "info"]),
  target_id: z.string(),
  cylinder: z.number().int().nullish(),
  requires_package: z.literal("race").nullish(),
});
export type NavItem = z.infer<typeof navItemSchema>;

export const navSectionSchema = z.looseObject({
  id: z.string(),
  label: z.string(),
  items: z.array(navItemSchema),
});
export type NavSection = z.infer<typeof navSectionSchema>;

export const strategySupportSchema = z.looseObject({
  kind: z.string(),
  level: z.enum(["supported", "package_race", "unsupported"]),
  restricted_options: z.record(z.string(), z.array(z.string())).default({}),
  display_name: z.string(),
});
export type StrategySupport = z.infer<typeof strategySupportSchema>;

export const tableSupportSchema = z.looseObject({
  kind: z.string(),
  required: z.boolean().default(false),
  display_name: z.string(),
  per_cylinder: z.boolean().default(false),
  live_tunable: z.boolean().default(false),
});

export const ecuProfileSummarySchema = z.looseObject({
  profile_id: z.string(),
  name: z.string(),
  family: z.enum(["oem", "standalone"]),
  inspiration: z.string().default(""),
  descriptor_version: z.string().default("1.0.0"),
});
export type EcuProfileSummary = z.infer<typeof ecuProfileSummarySchema>;

/**
 * `EcuProfileDescriptor` (E-22). `navigation` não tem `min(1)` aqui: o vazio é tratado como
 * estado de erro "perfil sem navegação" (EC-09), sem árvore inventada.
 */
export const ecuProfileDescriptorSchema = ecuProfileSummarySchema.extend({
  tables: z.array(tableSupportSchema).default([]),
  strategies: z.array(strategySupportSchema).default([]),
  terminology: z.record(z.string(), z.string()).default({}),
  display_units: z.looseObject({ mixture: z.enum(["lambda", "afr"]).default("lambda") }).default({ mixture: "lambda" }),
  requires_base_setup: z.boolean().default(false),
  base_setup_steps: z.array(z.string()).default([]),
  feature_packages: z.array(z.enum(["base", "race"])).default(["base"]),
  navigation: z.array(navSectionSchema).default([]),
  live_tunable_table_ids: z.array(z.string()).default([]),
  load_axis_channel: z.enum(["map_kpa", "load_pct", "torque_request_nm", "throttle_pct"]).default("map_kpa"),
  accent_color: z.string().regex(/^#[0-9a-fA-F]{6}$/).default("#64748b"),
});
export type EcuProfileDescriptor = z.infer<typeof ecuProfileDescriptorSchema>;

export const checklistItemSchema = z.looseObject({
  id: z.string(),
  required: z.boolean(),
  status: z.enum(["ok", "missing", "invalid", "warning"]),
  code: z.string().nullish(),
  message: z.string().default(""),
});
export const checklistSchema = z.looseObject({
  items: z.array(checklistItemSchema),
  minimum_valid: z.boolean(),
});
export type SetupChecklist = z.infer<typeof checklistSchema>;

export const hardwareSheetSchema = z.looseObject({
  trigger_wheel: z.string(),
  phase_sensor_present: z.boolean(),
  firing_order: z.array(z.number().int()),
  injector_label_cc_min: z.number(),
  tank_fuel_id: z.string(),
  map_sensor_label_kpa: z.tuple([z.number(), z.number()]),
  tdc_offset_nominal_deg: z.number(),
  n_cyl: z.number().int(),
  displacement_cc: z.number(),
});
export type HardwareSheet = z.infer<typeof hardwareSheetSchema>;

export const swapResultSchema = z.looseObject({
  session_id: z.string(),
  previous_profile_id: z.string(),
  profile_id: z.string(),
  ecu_state: z.enum(["oem", "awaiting_base_setup", "standalone_ready"]),
  base_setup_version: z.number().int().nullish(),
  calibration_id: z.string().nullish(),
  checklist: checklistSchema,
  hardware_sheet: hardwareSheetSchema,
});
export type SwapResult = z.infer<typeof swapResultSchema>;

export const baseSetupResultSchema = z.looseObject({
  session_id: z.string(),
  profile_id: z.string(),
  editable: z.boolean(),
  ecu_state: z.enum(["oem", "awaiting_base_setup", "standalone_ready"]),
  base_setup_version: z.number().int().nullish(),
  base_setup: z.record(z.string(), z.unknown()).nullish(),
  setup_hash: z.string().nullish(),
  checklist: checklistSchema,
  hardware_sheet: hardwareSheetSchema,
  calibration_id: z.string().nullish(),
  calibration_version: z.number().int().nullish(),
  estimated_peak_duty_pct: z.number().nullish(),
  warnings: z.array(z.string()).default([]),
});
export type BaseSetupResult = z.infer<typeof baseSetupResultSchema>;

// ------------------------------------------------------------------ sessão e veículo

export const sessionSchema = z.looseObject({
  session_id: z.string(),
  vehicle_id: z.string(),
  profile_id: z.string().default("oem-stage"),
  calibration_id: z.string(),
  /** Calibração em uso pelo worker (muda com Aplicar, swap e Base Setup); ausente em sessões antigas. */
  active_calibration_id: z.string().nullish(),
  active_calibration_version: z.number().int().nullish(),
  fuel_id: z.string().nullish(),
  state: z.string(),
  ecu_state: z.enum(["oem", "awaiting_base_setup", "standalone_ready"]).default("oem"),
  active_run_id: z.string().nullish(),
});
export type Session = z.infer<typeof sessionSchema>;

/** Calibração que o workspace deve abrir: a ativa da sessão, ou a inicial em sessões antigas. */
export function activeCalibrationId(session: Pick<Session, "calibration_id" | "active_calibration_id">): string {
  return session.active_calibration_id ?? session.calibration_id;
}

export const grid2dSchema = z.looseObject({
  x_name: z.string().optional(),
  x_values: z.array(z.number()),
  y_name: z.string().optional(),
  y_values: z.array(z.number()),
  z_values: z.array(z.array(z.number())),
});
export type Grid2D = z.infer<typeof grid2dSchema>;

export const vehicleDetailSchema = z.looseObject({
  vehicle_id: z.string(),
  display_name: z.string(),
  induction: z.enum(["turbo", "supercharger", "natural"]),
  stock_fuel_id: z.string().optional(),
  engine: z.looseObject({
    n_cyl: z.number().int(),
    firing_order: z.array(z.number().int()).optional(),
    mbt_reference: grid2dSchema.nullish(),
  }),
  turbo: z
    .looseObject({ compressor: z.looseObject({ pr_design: z.number() }).optional() })
    .nullish(),
  mechanical_limits: z.looseObject({ max_rpm: z.number(), rev_limit_rpm: z.number().optional() }),
  fuels: z.array(z.looseObject({ fuel_id: z.string(), display_name: z.string().optional(), afr_stoich: z.number() })).default([]),
});
export type VehicleDetail = z.infer<typeof vehicleDetailSchema>;

export const vehicleSummarySchema = z.looseObject({
  vehicle_id: z.string(),
  display_name: z.string(),
  induction: z.string().optional(),
  n_cyl: z.number().int().optional(),
  stock_profile_id: z.string().optional(),
  stock_fuel_id: z.string().optional(),
  validation_status: z.enum(["draft", "validated"]).default("validated"),
});
export type VehicleSummary = z.infer<typeof vehicleSummarySchema>;

export const vehicleListSchema = z.looseObject({
  catalog_version: z.string().optional(),
  items: z.array(vehicleSummarySchema),
});

// ------------------------------------------------------------------ otimização por IA (LAYA.ai)

export const cellCorrectionSchema = z.looseObject({
  table_id: z.string(),
  row: z.number().int(),
  col: z.number().int(),
  old_value: z.number(),
  new_value: z.number(),
  action: z.string(),
  confidence: z.number(),
  explanation: z.string(),
});
export type CellCorrection = z.infer<typeof cellCorrectionSchema>;

export const aiTuneResponseSchema = z.looseObject({
  corrections: z.array(cellCorrectionSchema),
  total_cells_modified: z.number().int(),
  summary: z.string(),
  safety_risk: z.boolean(),
  risk_confidence: z.number(),
  estimated_torque_gain_pct: z.number(),
});
export type AiTuneResponse = z.infer<typeof aiTuneResponseSchema>;

export interface AiTuneRequest {
  target_table_ids?: string[];
  aggressiveness?: "safe" | "balanced" | "race";
  max_fuel_step_pct?: number;
  max_ign_advance_step_deg?: number;
}

