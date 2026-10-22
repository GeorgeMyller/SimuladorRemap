/**
 * Tipos dos cenários de treino (training-scenarios seção 9; contracts/rest-api.md 3.8).
 * Espelham os modelos JSON do backend (snake_case).
 */

export type Role = "student" | "instructor";

export interface PlayerProfile {
  profile_id: string;
  nickname: string;
  role: Role;
  created_at: string;
}

export type ScenarioKind = "base" | "challenge";

export const VEHICLE_IDS = ["hatch-20t-gdi", "coupe-30t-i6", "classic-20t-swap", "muscle-v8-sc"] as const;
export type VehicleId = (typeof VEHICLE_IDS)[number];

export const VEHICLE_LABELS: Record<string, string> = {
  "hatch-20t-gdi": "Hatch 2.0 turbo GDI",
  "coupe-30t-i6": "Coupé 3.0 turbo I6",
  "classic-20t-swap": "Clássico 2.0 turbo (swap)",
  "muscle-v8-sc": "Muscle V8 supercharger",
};

export const FUEL_IDS = ["e27", "e100", "podium", "e0"] as const;
export const FUEL_LABELS: Record<string, string> = {
  e27: "Gasolina comum (E27)",
  e100: "Etanol (E100)",
  podium: "Gasolina premium (Podium)",
  e0: "Gasolina pura (E0)",
};

export interface ScenarioSummary {
  scenario_id: string;
  kind: ScenarioKind;
  title: string;
  vehicle_id: string;
  fuel_id: string;
  has_hidden_defect: boolean;
  available: boolean;
  last_evaluation_passed: boolean | null;
}

/** Mesmo enum do backend (`DefectKind` do OpenAPI); `boost_leak` é do cenário `defect-boost-leak`. */
export type DefectKind = "fuel_pump_weak" | "injector_clogged" | "iat_sensor_bias" | "wastegate_stuck" | "boost_leak";
export const DEFECT_KINDS: DefectKind[] = ["fuel_pump_weak", "injector_clogged", "iat_sensor_bias", "wastegate_stuck", "boost_leak"];
export const DEFECT_LABELS: Record<DefectKind, string> = {
  fuel_pump_weak: "Bomba de combustível fraca",
  injector_clogged: "Injetor entupido",
  iat_sensor_bias: "Sensor IAT descalibrado",
  wastegate_stuck: "Wastegate travada",
  boost_leak: "Vazamento no circuito de pressão",
};

export interface HiddenDefect {
  kind: DefectKind;
  fuel_pump_max_lph?: number | null;
  cylinder?: number | null;
  injector_flow_factor?: number | null;
  sensor_bias_c?: number | null;
  stuck_position_pct?: number | null;
  leak_area_mm2?: number | null;
  start_t_sim_s?: number;
}

export type CriterionKind =
  | "min_whp"
  | "min_delta_whp"
  | "min_torque_nm"
  | "max_knock_retard_deg"
  | "min_knock_margin_deg"
  | "integrity"
  | "max_egt_c"
  | "max_egt_overrun_c"
  | "lambda_wot_max"
  | "lambda_wot_min"
  | "min_pop_events"
  | "valid_pulls"
  | "max_spread_pct"
  | "final_profile"
  | "locked_tables"
  | "defect_diagnosis";

export const CRITERION_KINDS: CriterionKind[] = [
  "min_whp",
  "min_delta_whp",
  "min_torque_nm",
  "max_knock_retard_deg",
  "min_knock_margin_deg",
  "integrity",
  "max_egt_c",
  "max_egt_overrun_c",
  "lambda_wot_max",
  "lambda_wot_min",
  "min_pop_events",
  "valid_pulls",
  "max_spread_pct",
  "final_profile",
  "locked_tables",
  "defect_diagnosis",
];

/** Rótulo e unidade de cada tipo de critério. */
export const CRITERION_INFO: Record<CriterionKind, { label: string; unit: string }> = {
  min_whp: { label: "Potência na roda mínima", unit: "whp" },
  min_delta_whp: { label: "Ganho sobre a puxada base", unit: "whp" },
  min_torque_nm: { label: "Torque mínimo", unit: "N·m" },
  max_knock_retard_deg: { label: "Retardo de knock máximo", unit: "°" },
  min_knock_margin_deg: { label: "Margem de knock (sonda)", unit: "°" },
  integrity: { label: "Integridade do motor", unit: "%" },
  max_egt_c: { label: "EGT pré-turbina máxima", unit: "°C" },
  max_egt_overrun_c: { label: "EGT máxima no overrun", unit: "°C" },
  lambda_wot_max: { label: "Lambda máximo em plena carga", unit: "λ" },
  lambda_wot_min: { label: "Lambda mínimo em plena carga", unit: "λ" },
  min_pop_events: { label: "Pops & bangs no coastdown", unit: "eventos" },
  valid_pulls: { label: "Puxadas válidas", unit: "puxadas" },
  max_spread_pct: { label: "Dispersão entre puxadas", unit: "%" },
  final_profile: { label: "Perfil de ECU final", unit: "" },
  locked_tables: { label: "Tabelas bloqueadas intactas", unit: "" },
  defect_diagnosis: { label: "Diagnóstico do defeito", unit: "" },
};

export type Comparator = "ge" | "le" | "bool";

export interface Criterion {
  criterion_id: string;
  kind: CriterionKind;
  comparator: Comparator;
  threshold: number | null;
  band?: number | null;
  weight: number;
  mandatory: boolean;
}

export interface ChallengeCriteria {
  criteria: Criterion[];
  required_valid_pulls: number;
  min_end_rpm?: number | null;
  lambda_window_min_rpm: number;
  require_defect_diagnosis: boolean;
}

export interface HintUnlock {
  after_failed_submissions?: number | null;
  after_sim_time_s?: number | null;
  after_event?: "knock_retard" | "engine_failed" | "egt_limit" | "invalid_run" | null;
}

export interface Hint {
  order: number;
  text: string;
  unlock: HintUnlock;
}

export interface ScenarioConstraints {
  allowed_run_types: string[];
  gear: number;
  allowed_final_profiles: string[];
  swap_allowed: boolean;
  locked_table_ids: string[];
  max_submissions: number;
  time_limit_min: number | null;
  operator_protection: boolean;
}

export interface Ambient {
  temperature_c: number;
  pressure_kpa: number;
  relative_humidity: number;
}

export interface InitialCalibration {
  source: "vehicle_stock" | "embedded";
  payload?: Record<string, unknown> | null;
  content_hash: string;
}

export interface Scenario {
  scenario_id: string;
  kind: ScenarioKind;
  title: string;
  briefing: string;
  vehicle_id: string;
  initial_profile_id: string;
  initial_calibration: InitialCalibration;
  fuel_id: string;
  ambient: Ambient;
  correction_standard: string;
  seed: number | null;
  objectives: string[];
  constraints: ScenarioConstraints;
  criteria: ChallengeCriteria;
  hidden_defect: HiddenDefect | null;
  hints: Hint[];
  author_nickname: string | null;
  scenario_sha256?: string | null;
  builtin?: boolean;
  origin?: "builtin" | "local" | "imported";
  created_at?: string | null;
}

export interface ScenarioView extends Scenario {
  has_hidden_defect: boolean;
}

export interface ScenarioStats {
  scenario_id: string;
  started: number;
  passed: number;
  failed_final: number;
  abandoned: number;
  completion_rate_pct: number | null;
  median_submissions_to_pass: number | null;
}

export type AttemptState =
  | "preparing"
  | "in_progress"
  | "evaluating"
  | "passed"
  | "failed_final"
  | "abandoned"
  | "expired"
  | "failed_to_start";

export const ATTEMPT_STATE_LABELS: Record<AttemptState, string> = {
  preparing: "A preparar (puxada base)",
  in_progress: "Em curso",
  evaluating: "Em avaliação",
  passed: "Aprovada",
  failed_final: "Reprovada (sem submissões)",
  abandoned: "Abandonada",
  expired: "Expirada",
  failed_to_start: "Falhou ao iniciar",
};

export type ReplayStatus = "not_run" | "running" | "verified" | "mismatch" | "incompatible_version";

export interface AttemptRun {
  run_id: string;
  run_type: string;
  pull_index: number;
  valid: boolean;
  invalid_reason: string | null;
  calibration_hash: string | null;
  peak_whp: number | null;
}

export interface Evidence {
  run_id: string;
  log_id: string | null;
  channel: string;
  t_sim_s: number | null;
  rpm: number | null;
  cylinder: number | null;
  value: number | null;
  url: string;
}

export interface CriterionResult {
  criterion_id: string;
  kind: CriterionKind;
  comparator: Comparator;
  measured: number | null;
  threshold: number | null;
  passed: boolean;
  score: number;
  weight: number;
  mandatory: boolean;
  evidence: Evidence[];
}

export interface Evaluation {
  evaluation_id: string;
  attempt_id: string;
  submission_index: number;
  status: "pending" | "completed" | "error";
  error_code: string | null;
  evaluator_version: string;
  passed: boolean | null;
  total_score: number | null;
  results: CriterionResult[];
  evidence_run_ids: string[];
  ignored_runs: string[];
  calibration_content_hash: string | null;
  probe_run_sha256: string | null;
  hints_revealed: number[];
  revealed_defect: HiddenDefect | null;
  evaluation_sha256: string | null;
  created_at: string | null;
}

export interface AttemptView {
  attempt_id: string;
  scenario_id: string;
  scenario_sha256: string;
  profile_id: string | null;
  nickname: string;
  origin: "local" | "imported";
  state: AttemptState;
  session_id: string | null;
  calibration_id: string;
  seed: number;
  baseline_run_id: string | null;
  baseline_peak_whp: number | null;
  runs: AttemptRun[];
  submissions: number;
  hints_revealed: number[];
  engine_restores: number;
  replay_status: ReplayStatus;
  started_at: string;
  max_submissions: number;
  hints_total: number;
  failure_code: string | null;
  progress: CriterionResult[];
  last_evaluation: Evaluation | null;
  evaluation_mismatch: boolean;
  producer_install_id: string | null;
  package_sha256: string | null;
  imported_at: string | null;
  replay_mismatch_run_ids: string[];
  scenario_title: string;
}

export interface AttemptPage {
  items: AttemptView[];
  next_cursor: string | null;
}

export interface HintReveal {
  order: number;
  text: string;
  remaining: number;
}

export interface SubmitRequest {
  calibration_id: string;
  run_ids?: string[];
  declared_defect?: DefectKind | "none";
}

export interface SubmitAccepted {
  attempt_id: string;
  submission_index: number;
  evaluation_status: "pending";
}

export interface ReplayAccepted {
  attempt_id: string;
  replay_status: "running";
  runs_to_replay: number;
}

export interface PackageExportRequest {
  kind: "challenge" | "attempt";
  scenario_id?: string;
  attempt_id?: string;
  include_full_logs: boolean;
}

export interface PackageImportResult {
  package_sha256: string;
  kind: "challenge" | "attempt";
  scenario_id: string;
  attempt_id: string | null;
  already_imported: boolean;
  evaluation_mismatch: boolean;
  recomputed_evaluation: Evaluation | null;
}

export interface ExportedFile {
  filename: string;
  content: string;
}

export const INVALID_REASON_LABELS: Record<string, string> = {
  run_not_completed: "Puxada não concluída",
  engine_failed: "Motor quebrou",
  run_type_not_allowed: "Tipo de puxada não permitido",
  calibration_changed_during_run: "Calibração alterada durante a puxada",
  calibration_not_submitted: "Calibração diferente da submetida",
  session_mismatch: "Condições da sessão diferentes do cenário",
  damage_disabled: "Dano desligado",
  faults_mismatch: "Falhas físicas diferentes do cenário",
  end_rpm_too_low: "Rotação final abaixo do mínimo",
  gear_mismatch: "Marcha diferente da exigida",
  profile_not_allowed: "Perfil de ECU não permitido",
  trace_unavailable: "Log indisponível",
};

export function invalidReasonLabel(reason: string | null): string {
  if (!reason) return "";
  return INVALID_REASON_LABELS[reason] ?? reason;
}

export const NICKNAME_RE = /^[-_0-9A-Za-z]{3,24}$/;
export const SLUG_RE = /^[0-9a-z][-0-9a-z]{2,63}$/;
export const ACTIVE_PROFILE_KEY = "simremap.activeProfileId";
