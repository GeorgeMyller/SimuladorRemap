/** API falsa e dados de exemplo para os testes dos cenários. */
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";

import { ApiProblem } from "@/lib/api";

import { ScenariosApiContext, type ScenariosApi } from "../api";
import type { AttemptView, CriterionResult, Evaluation, PlayerProfile, ScenarioSummary, ScenarioView } from "../types";

export const STUDENT: PlayerProfile = {
  profile_id: "11111111-1111-4111-8111-111111111111",
  nickname: "lucas_turbo",
  role: "student",
  created_at: "2026-10-18T10:00:00Z",
};
export const INSTRUCTOR: PlayerProfile = {
  profile_id: "22222222-2222-4222-8222-222222222222",
  nickname: "prof_marcos",
  role: "instructor",
  created_at: "2026-10-18T10:00:00Z",
};

export function problem(status: number, code: string, detail = "erro"): ApiProblem {
  return new ApiProblem({ type: `urn:simremap:problem:${code.toLowerCase()}`, title: code, status, detail, code, request_id: "r" });
}

export const SUMMARIES: ScenarioSummary[] = [
  { scenario_id: "stage1-oem", kind: "base", title: "Stage 1 OEM", vehicle_id: "hatch-20t-gdi", fuel_id: "e27", has_hidden_defect: false, available: true, last_evaluation_passed: true },
  { scenario_id: "stage2-pops-bangs", kind: "base", title: "Stage 2 pops & bangs", vehicle_id: "hatch-20t-gdi", fuel_id: "e27", has_hidden_defect: false, available: true, last_evaluation_passed: null },
  { scenario_id: "standalone-swap", kind: "base", title: "Swap standalone", vehicle_id: "classic-20t-swap", fuel_id: "e100", has_hidden_defect: false, available: true, last_evaluation_passed: null },
  { scenario_id: "challenge-bomba-fraca", kind: "challenge", title: "Bomba fraca", vehicle_id: "hatch-20t-gdi", fuel_id: "e27", has_hidden_defect: true, available: true, last_evaluation_passed: false },
];

export const STAGE1: ScenarioView = {
  scenario_id: "stage1-oem",
  kind: "base",
  title: "Stage 1 OEM",
  briefing: "Ganhe 40 whp com segurança.",
  vehicle_id: "hatch-20t-gdi",
  initial_profile_id: "oem-stage",
  initial_calibration: { source: "vehicle_stock", payload: null, content_hash: "a".repeat(64) },
  fuel_id: "e27",
  ambient: { temperature_c: 25, pressure_kpa: 99, relative_humidity: 0 },
  correction_standard: "sae_j1349",
  seed: null,
  objectives: ["+40 whp sobre a base", "EGT ≤ 950 °C"],
  constraints: {
    allowed_run_types: ["baseline_pull", "sweep_pull", "multi_pull"],
    gear: 4,
    allowed_final_profiles: ["oem-stage"],
    swap_allowed: false,
    locked_table_ids: [],
    max_submissions: 5,
    time_limit_min: null,
    operator_protection: false,
  },
  criteria: {
    criteria: [
      { criterion_id: "delta-whp", kind: "min_delta_whp", comparator: "ge", threshold: 40, weight: 2, mandatory: true },
      { criterion_id: "egt", kind: "max_egt_c", comparator: "le", threshold: 950, weight: 1, mandatory: true },
      { criterion_id: "integrity", kind: "integrity", comparator: "ge", threshold: 100, weight: 1, mandatory: true },
    ],
    required_valid_pulls: 2,
    lambda_window_min_rpm: 3000,
    require_defect_diagnosis: false,
  },
  hidden_defect: null,
  hints: [],
  author_nickname: null,
  scenario_sha256: "b".repeat(64),
  builtin: true,
  origin: "builtin",
  created_at: null,
  has_hidden_defect: false,
};

export const SESSION_ID = "0f5e1d2c3b4a49687766554433221100";

export function result(over: Partial<CriterionResult>): CriterionResult {
  return {
    criterion_id: "egt",
    kind: "max_egt_c",
    comparator: "le",
    measured: 900,
    threshold: 950,
    passed: true,
    score: 100,
    weight: 1,
    mandatory: true,
    evidence: [],
    ...over,
  };
}

export function evaluation(over: Partial<Evaluation> = {}): Evaluation {
  return {
    evaluation_id: "e1",
    attempt_id: "att-1",
    submission_index: 1,
    status: "completed",
    error_code: null,
    evaluator_version: "1.0.0",
    passed: true,
    total_score: 100,
    results: [],
    evidence_run_ids: [],
    ignored_runs: [],
    calibration_content_hash: "c".repeat(64),
    probe_run_sha256: null,
    hints_revealed: [],
    revealed_defect: null,
    evaluation_sha256: "d".repeat(64),
    created_at: "2026-10-18T10:00:00Z",
    ...over,
  };
}

export function attempt(over: Partial<AttemptView> = {}): AttemptView {
  return {
    attempt_id: "att-1",
    scenario_id: "stage1-oem",
    scenario_sha256: "b".repeat(64),
    profile_id: STUDENT.profile_id,
    nickname: STUDENT.nickname,
    origin: "local",
    state: "in_progress",
    session_id: SESSION_ID,
    calibration_id: "cal-1",
    seed: 42,
    baseline_run_id: "01JABCDEFGHJKMNPQRSTVWXYZ0",
    baseline_peak_whp: 220.4,
    runs: [
      { run_id: "01JABCDEFGHJKMNPQRSTVWXYZ0", run_type: "baseline_pull", pull_index: 0, valid: true, invalid_reason: null, calibration_hash: "a".repeat(64), peak_whp: 220.4 },
      { run_id: "01JABCDEFGHJKMNPQRSTVWXYZ1", run_type: "sweep_pull", pull_index: 0, valid: false, invalid_reason: "calibration_changed_during_run", calibration_hash: null, peak_whp: 255.1 },
    ],
    submissions: 0,
    hints_revealed: [],
    engine_restores: 0,
    replay_status: "not_run",
    started_at: "2026-10-18T10:00:00Z",
    max_submissions: 5,
    hints_total: 3,
    failure_code: null,
    progress: [result({ criterion_id: "delta-whp", kind: "min_delta_whp", comparator: "ge", measured: 43.2, threshold: 40 })],
    last_evaluation: null,
    evaluation_mismatch: false,
    producer_install_id: null,
    package_sha256: null,
    imported_at: null,
    replay_mismatch_run_ids: [],
    scenario_title: "Stage 1 OEM",
    ...over,
  };
}

const never = () => Promise.reject(new Error("não esperado no teste"));

export function makeApi(over: Partial<ScenariosApi> = {}): ScenariosApi {
  return {
    listProfiles: vi.fn(() => Promise.resolve([STUDENT, INSTRUCTOR])),
    createProfile: vi.fn(never),
    listScenarios: vi.fn(() => Promise.resolve(SUMMARIES)),
    getScenario: vi.fn(() => Promise.resolve(STAGE1)),
    createScenario: vi.fn(never),
    getStats: vi.fn(never),
    startAttempt: vi.fn(never),
    listAttempts: vi.fn(() => Promise.resolve({ items: [], next_cursor: null })),
    getAttempt: vi.fn(() => Promise.resolve(attempt())),
    revealHint: vi.fn(never),
    abandon: vi.fn(never),
    submit: vi.fn(never),
    getRunCalibrationId: vi.fn(() => Promise.resolve("cal-1")),
    getEvaluation: vi.fn(() => Promise.resolve(evaluation())),
    replay: vi.fn(never),
    exportPackage: vi.fn(never),
    importPackage: vi.fn(never),
    ...over,
  };
}

/** Renderiza `ui` com a API falsa num router em memória (rotas fixas da app). */
export function renderWithApi(ui: ReactElement, api: ScenariosApi, path = "/", routePath = "*") {
  return render(
    <ScenariosApiContext.Provider value={api}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path={routePath} element={ui} />
          <Route path="/sessions/:sessionId/dyno" element={<p>cockpit</p>} />
        </Routes>
      </MemoryRouter>
    </ScenariosApiContext.Provider>,
  );
}
