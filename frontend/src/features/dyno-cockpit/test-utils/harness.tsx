/* eslint-disable @typescript-eslint/require-await -- mocks assíncronos */
/** Harness de integração da cockpit: API REST falsa, WebSocket falso, Canvas e Web Audio falsos. */
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, vi } from "vitest";

import { ApiProblem } from "@/lib/api";

import type { CockpitApi, DynoRun, ForensicReport } from "../api";
import { DynoCockpitView } from "../DynoCockpitPage";
import { fakeAudioFactory, FakeWebSocket } from "./mocks";

export const SESSION_ID = "c3f1a2c3f1a2c3f1a2c3f1a2c3f1a2c3";

export const vehicleFixture = {
  vehicle_id: "hatch-20t-gdi",
  display_name: "Hatch 2.0 Turbo GDI",
  induction: "turbo" as const,
  stock_fuel_id: "e27",
  engine: { architecture: "inline" as const, n_cyl: 4, firing_order: [1, 3, 4, 2], bore_mm: 82.5 },
  mechanical_limits: { egt_max_c: 950, max_rpm: 7000, rev_limit_rpm: 6800, turbo_max_rpm: 220000 },
  rated: { peak_power_whp: 220, peak_torque_nm: 350 },
};

export function runFixture(runId: string, state: string, extra: Partial<DynoRun> = {}): DynoRun {
  return {
    run_id: runId,
    session_id: SESSION_ID,
    run_type: "sweep_pull",
    state,
    abort_reason: state === "aborted" ? "user_abort" : null,
    summary: { peak_whp: 220, peak_whp_rpm: 5500, peak_torque_engine_nm: 350, peak_torque_rpm: 3500 },
    curve: [2000, 3000, 4000, 5000, 6000].map((rpm, i) => ({ rpm, t_sim_s: i, power_wheel_kw: 60 + i * 25, torque_engine_nm: 320, lambda: 0.85, egt_c: 800 })),
    ...extra,
  };
}

export const reportFixture: ForensicReport = {
  report_id: "01JAB",
  report_kind: "failure",
  run_id: "r-01J9Z",
  failure_event: { component_id: "piston:3", mode: "piston_failure", cylinder: 3, t_sim_s: 13.118, catastrophic: true },
  primary_mode: "piston_failure",
  damaged_components: [
    { component_id: "piston:3", health: 0, failed: true },
    { component_id: "rod:3", health: 0.7, failed: false },
  ],
  causal_chain: [
    { order: 2, t_sim_s: 12.9, kind: "combustion", cylinder: 3, variable: "knock_intensity_cyl3", value: 0.98, threshold: 0.15, unit: "-", description: "Knock severo persistente no cilindro 3." },
    { order: 1, t_sim_s: 11.2, kind: "calibration", cylinder: null, variable: "ignition_advance_deg", value: 24, threshold: 18, unit: "°", description: "Avanço acima do MBT seguro." },
    { order: 3, t_sim_s: 13.118, kind: "failure", cylinder: 3, variable: "piston_temp_eff_c", value: 371, threshold: 330, unit: "°C", description: "Coroa do pistão fundiu." },
  ],
  recommendations: [{ rule_id: "R-IGN-01", action: "Reduzir o avanço em 4° acima de 4000 rpm", table_id: "ignition_base", cylinders: [3], rationale: "Afasta o knock.", region: "rpm 4000–6500" }],
  texts: { beginner: { title: "O pistão 3 derreteu", summary: "Knock contínuo aqueceu o pistão.", explanation: "..." } },
};

export function makeApi(over: Partial<Record<keyof CockpitApi, unknown>> = {}) {
  const api = {
    getSession: vi.fn(async () => ({ session_id: SESSION_ID, vehicle_id: "hatch-20t-gdi", profile_id: "oem-stage", fuel_id: "e27", state: "ready", active_run_id: null, baseline_run_id: null, engine_locked: false })),
    getVehicle: vi.fn(async () => vehicleFixture),
    getReferenceCurves: vi.fn(async () => ({
      vehicle_id: "hatch-20t-gdi",
      items: [{ curve_id: "stock-e27", fuel_id: "e27", points: [2000, 4000, 6000].map((rpm) => ({ rpm, power_wheel_kw: rpm / 40, torque_crank_nm: 330 })) }],
    })),
    getProfile: vi.fn(async () => ({ profile_id: "oem-stage", name: "OEM-Stage" })),
    getHealth: vi.fn(async () => ({ status: "ok" })),
    startRun: vi.fn(async () => runFixture("r-01J9Z", "arming")),
    abortRun: vi.fn(async () => runFixture("r-01J9Z", "aborted")),
    getRun: vi.fn(async (id: string) => runFixture(id, "completed")),
    getForensicReport: vi.fn(async () => reportFixture),
    restoreEngine: vi.fn(async () => ({ session_id: SESSION_ID, engine_locked: false, components: [] })),
    getLog: vi.fn(),
    compareLogs: vi.fn(),
    importLog: vi.fn(),
    ...over,
  };
  return api as unknown as CockpitApi & Record<keyof CockpitApi, ReturnType<typeof vi.fn>>;
}

export function notFound(code: string, title = "Não encontrado") {
  return ApiProblem.synthetic(404, code, title);
}

export function conflict(code: string) {
  return new ApiProblem({ type: `urn:simremap:problem:${code}`, title: "Conflito", status: 409, detail: "conflito de estado", code, request_id: "x" });
}

export async function renderCockpit(api = makeApi(), storage: Storage | null = null) {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 1920 });
  Object.defineProperty(navigator, "language", { configurable: true, value: "pt-BR" });
  FakeWebSocket.reset();
  const utils = render(
    <MemoryRouter>
      <DynoCockpitView
        sessionId={SESSION_ID}
        deps={{ api, createWebSocket: (url) => new FakeWebSocket(url), createAudioContext: fakeAudioFactory, storage, wsOrigin: "http://localhost" }}
      />
    </MemoryRouter>,
  );
  await screen.findByTestId("vehicle-name");
  // O socket nasce num efeito posterior ao carregamento da sessão; sob carga ele pode
  // chegar depois do nome do veículo, por isso a espera explícita.
  await waitFor(() => expect(FakeWebSocket.instances.length).toBeGreaterThan(0));
  return { ...utils, api };
}

/** Abre o WS falso e devolve-o. */
export function openSocket(): FakeWebSocket {
  const ws = FakeWebSocket.last();
  ws.open();
  return ws;
}
