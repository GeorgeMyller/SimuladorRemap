/* eslint-disable @typescript-eslint/require-await -- mocks assíncronos */
/**
 * Fixtures dos testes do editor de ECU: 4 descritores (OEM-Stage, FT-Pro, M1-Race, HT-Elite)
 * no formato de `EcuProfileDescriptor`, calibração com tabelas 3D/2D e trims, sessão, veículo
 * e uma `EcuApi` falsa (mocks de fetch por função).
 */
import { vi, type Mock } from "vitest";

import { ApiProblem } from "@/lib/api";

import type { EcuApi } from "../api";
import type { Calibration, EcuProfileDescriptor, NavSection, Session, TableView, VehicleDetail } from "../types";

export const SESSION_ID = "a1b2c3d4a1b2c3d4a1b2c3d4a1b2c3d4";
export const CAL_ID = "cal-0001";

export const RPM_16 = [800, 1200, 1600, 2000, 2500, 3000, 3500, 4000, 4500, 5000, 5500, 6000, 6500, 7000, 7500, 8000];
export const MAP_16 = [20, 40, 60, 80, 100, 120, 140, 160, 180, 200, 220, 240, 260, 280, 300, 320];

export function table3d(tableId: string, kind: string, unit: string, min: number, max: number, fill: (r: number, c: number) => number, opts: Omit<Partial<TableView>, "x" | "y"> & { x?: number[]; y?: number[] } = {}): TableView {
  const x = opts.x ?? RPM_16;
  const y = opts.y ?? MAP_16;
  const rest: Omit<Partial<TableView>, "x" | "y"> & { x?: number[]; y?: number[] } = { ...opts };
  delete rest.x;
  delete rest.y;
  return {
    table_id: tableId,
    kind,
    unit,
    dims: 3,
    live_tunable: true,
    description: "",
    decimals: 1,
    min,
    max,
    x: { quantity: "rpm", values: x, unit: "rev/min", source_channel: "rpm" },
    y: { quantity: "map_kpa", values: y, unit: "kPa", source_channel: "map_kpa" },
    values: y.map((_, r) => x.map((__, c) => fill(r, c))),
    ...(rest as Partial<TableView>),
  };
}

export function table2d(tableId: string, kind: string, unit: string, min: number, max: number, xq: string, x: number[], values: number[]): TableView {
  return {
    table_id: tableId,
    kind,
    unit,
    dims: 2,
    live_tunable: false,
    description: "",
    decimals: 1,
    min,
    max,
    x: { quantity: xq, values: x, unit: xq === "gear" ? "-" : "°C", source_channel: xq },
    y: null,
    values,
  };
}

export function calibrationFixture(over: Partial<Calibration> = {}): Calibration {
  return {
    calibration_id: CAL_ID,
    vehicle_id: "classic-20t-swap",
    profile_id: "ft-pro",
    version: 6,
    parent_version: 5,
    fuel_model: { mode: "speed_density_ve" },
    tables: {
      ve: table3d("ve", "ve", "%", 0, 150, (r, c) => 60 + r + c),
      lambda_target: table3d("lambda_target", "lambda_target", "λ", 0.65, 1.3, () => 0.85, { decimals: 3 }),
      ignition_base: table3d("ignition_base", "ignition_base", "°BTDC", -20, 60, () => 20),
      boost_target_gear: table2d("boost_target_gear", "boost_target_gear", "kPa", 80, 400, "gear", [1, 2, 3, 4, 5, 6], [150, 170, 190, 200, 200, 200]),
      fuel_trim_cyl_1: table3d("fuel_trim_cyl_1", "fuel_trim_cyl", "%", -25, 25, () => 0, { cylinder: 1, x: [1000, 4000], y: [50, 200] }),
      fuel_trim_cyl_2: table3d("fuel_trim_cyl_2", "fuel_trim_cyl", "%", -25, 25, () => 2, { cylinder: 2, x: [1000, 4000], y: [50, 200] }),
      ignition_trim_cyl_1: table3d("ignition_trim_cyl_1", "ignition_trim_cyl", "°", -15, 15, () => 0, { cylinder: 1, x: [1000, 4000], y: [50, 200] }),
    },
    strategies: {
      rev_limiter: { kind: "rev_limiter", enabled: true, hard_rpm: 7000, cut_mode: "fuel_cut", soft_enabled: true, soft_window_rpm: 200, soft_retard_max_deg: 10, hysteresis_rpm: 100 },
    },
    profile_params: {},
    metadata: { name: "Base FT-Pro", notes: "", source: "wizard", change_summary: "", extra: {} },
    content_hash: "a".repeat(64),
    created_at: "2026-10-18T10:00:00Z",
    versions: [
      { version: 6, parent_version: 5, content_hash: "a".repeat(64), source: "user", author_nickname: "rodrigo", change_summary: "VE +3 % topo", created_at: "2026-10-18T10:00:00Z" },
      { version: 5, parent_version: 4, content_hash: "b".repeat(64), source: "user", author_nickname: null, change_summary: "", created_at: "2026-10-18T09:00:00Z" },
    ],
    ...over,
  };
}

const nav = (sections: [string, string, [string, string, "table" | "strategy" | "base_setup" | "info", string, number?][]][]): NavSection[] =>
  sections.map(([id, label, items]) => ({ id, label, items: items.map(([iid, ilabel, kind, target, cylinder]) => ({ id: iid, label: ilabel, kind, target_id: target, cylinder: cylinder ?? null })) }));

const STRATS = ["closed_loop", "knock_control", "boost_control", "rev_limiter", "two_step", "antilag", "powershift", "overrun", "failsafe"];

function descriptor(profile_id: string, name: string, family: "oem" | "standalone", navigation: NavSection[], extra: Partial<EcuProfileDescriptor> = {}): EcuProfileDescriptor {
  return {
    profile_id,
    name,
    family,
    inspiration: "texto genérico",
    descriptor_version: "1.0.0",
    tables: [],
    strategies: STRATS.map((kind) => ({ kind, level: "supported" as const, restricted_options: {}, display_name: kind })),
    terminology: {},
    display_units: { mixture: "lambda" },
    requires_base_setup: family === "standalone",
    base_setup_steps: family === "standalone" ? ["trigger", "injectors", "fuel", "sensors", "protection", "review"] : [],
    feature_packages: ["base"],
    navigation,
    live_tunable_table_ids: ["ve", "lambda_target", "ignition_base", "fuel_trim_cyl", "ignition_trim_cyl"],
    load_axis_channel: family === "oem" ? "load_pct" : "map_kpa",
    accent_color: "#7A6F5A",
    ...extra,
  };
}

export const DESCRIPTORS: Record<string, EcuProfileDescriptor> = {
  "oem-stage": descriptor("oem-stage", "OEM-Stage", "oem", nav([
    ["torque", "Caminho de torque", [["tq.ign", "Avanço ótimo", "table", "ignition_base"], ["tq.boost", "Pressão por marcha", "table", "boost_target_gear"]]],
    ["mixture", "Mistura", [["mix.lambda", "Lambda de proteção", "table", "lambda_target"]]],
    ["limits", "Limites", [["lim.rev", "Limitador", "strategy", "rev_limiter"], ["lim.overrun", "Desaceleração", "strategy", "overrun"]]],
  ])),
  "ft-pro": descriptor("ft-pro", "FT-Pro", "standalone", nav([
    ["base-setup", "Configuração base (setup guiado)", [["base-setup.trigger", "Roda fônica", "base_setup", "trigger"]]],
    ["injection", "Injeção principal", [["inj.ve", "Mapa principal (VE)", "table", "ve"], ["inj.lambda_target", "Lambda alvo", "table", "lambda_target"], ["inj.closed_loop", "Malha fechada", "strategy", "closed_loop"]]],
    ["ignition", "Ignição", [["ign.base", "Avanço de ignição", "table", "ignition_base"]]],
    ["drag", "Funções de arrancada", [["drag.two_step", "Two-step", "strategy", "two_step"], ["drag.boost_gear", "Pressão por marcha", "table", "boost_target_gear"]]],
    ["corrections", "Correções", [["corr.fuel_cyl.1", "Combustível cil. 1", "table", "fuel_trim_cyl", 1], ["corr.fuel_cyl.2", "Combustível cil. 2", "table", "fuel_trim_cyl", 2]]],
    ["protection", "Proteções", [["prot.limiter", "Corte de rotação", "strategy", "rev_limiter"], ["prot.failsafe", "Proteções do motor", "strategy", "failsafe"]]],
  ])),
  "m1-race": descriptor("m1-race", "M1-Race", "standalone", nav([
    ["engine", "Motor", [["eng.eff", "Eficiência volumétrica", "table", "ve"], ["eng.ign", "Ignição", "table", "ignition_base"]]],
    ["fuel", "Combustível", [["fuel.lambda", "Lambda alvo", "table", "lambda_target"]]],
    ["race", "Funções de corrida", [["race.antilag", "Antilag", "strategy", "antilag"], ["race.powershift", "Powershift", "strategy", "powershift"]]],
  ]), { feature_packages: ["base", "race"] }),
  "ht-elite": descriptor("ht-elite", "HT-Elite", "standalone", nav([
    ["fuel", "Combustível", [["fuel.ve", "Mapa base de combustível", "table", "ve"]]],
    ["ignition", "Ignição", [["ign.main", "Mapa de ignição", "table", "ignition_base"], ["ign.knock", "Detonação", "strategy", "knock_control"]]],
    ["boost", "Turbo", [["boost.ctrl", "Controle de boost", "strategy", "boost_control"]]],
    ["system", "Sistema", [["sys.limits", "Limitador", "strategy", "rev_limiter"]]],
  ])),
};

export const sessionFixture: Session = {
  session_id: SESSION_ID,
  vehicle_id: "classic-20t-swap",
  profile_id: "ft-pro",
  calibration_id: CAL_ID,
  fuel_id: "e27",
  state: "ready",
  ecu_state: "standalone_ready",
  active_run_id: null,
};

export const vehicleFixture: VehicleDetail = {
  vehicle_id: "classic-20t-swap",
  display_name: "Clássico 2.0 turbo (swap)",
  induction: "turbo",
  stock_fuel_id: "e27",
  engine: {
    n_cyl: 4,
    firing_order: [1, 3, 4, 2],
    mbt_reference: { x_name: "rpm", x_values: [1000, 8000], y_name: "map_kpa", y_values: [20, 320], z_values: [[30, 30], [16, 16]] },
  },
  turbo: { compressor: { pr_design: 2.5 } },
  mechanical_limits: { max_rpm: 7200, rev_limit_rpm: 7000 },
  fuels: [
    { fuel_id: "e27", display_name: "E27", afr_stoich: 13.2 },
    { fuel_id: "e100", display_name: "E100", afr_stoich: 9.0 },
  ],
};

export const hardwareFixture = {
  trigger_wheel: "60-2",
  phase_sensor_present: true,
  firing_order: [1, 3, 4, 2],
  injector_label_cc_min: 550,
  tank_fuel_id: "e27",
  map_sensor_label_kpa: [10, 400] as [number, number],
  tdc_offset_nominal_deg: 84,
  n_cyl: 4,
  displacement_cc: 1998,
};

export const checklistFixture = {
  items: [
    { id: "trigger.wheel", required: true, status: "ok" as const, code: null, message: "" },
    { id: "injectors.flow", required: true, status: "ok" as const, code: null, message: "" },
  ],
  minimum_valid: true,
};

export function problem(status: number, code: string, extra: Record<string, unknown> = {}, title = code, detail = `Erro ${code}`): ApiProblem {
  return new ApiProblem({ type: `urn:simremap:problem:${code.toLowerCase()}`, title, status, detail, code, request_id: "rid-1", ...extra });
}

export type FakeApi = { [K in keyof EcuApi]: Mock<EcuApi[K]> };

export function makeApi(over: Partial<Record<keyof EcuApi, unknown>> = {}, cal: Calibration = calibrationFixture()): FakeApi {
  let current = cal;
  const api = {
    getSession: vi.fn(async () => sessionFixture),
    createSession: vi.fn(async (body: { vehicle_id: string; profile_id: string }) => ({ ...sessionFixture, session_id: "b".repeat(32), vehicle_id: body.vehicle_id, profile_id: body.profile_id })),
    deleteSession: vi.fn(async () => undefined),
    getVehicle: vi.fn(async () => vehicleFixture),
    listVehicles: vi.fn(async () => ({
      catalog_version: "1",
      items: [
        { vehicle_id: "hatch-20t-gdi", display_name: "Hatch 2.0 turbo", stock_profile_id: "oem-stage", validation_status: "validated" as const },
        { vehicle_id: "coupe-30t-i6", display_name: "Cupê 3.0 turbo I6", stock_profile_id: "oem-stage", validation_status: "validated" as const },
        { vehicle_id: "muscle-v8-sc", display_name: "Muscle V8 compressor", stock_profile_id: "oem-stage", validation_status: "draft" as const },
        { vehicle_id: "classic-20t-swap", display_name: "Clássico 2.0 turbo (swap)", stock_profile_id: "ft-pro", validation_status: "validated" as const },
      ],
    })),
    listProfiles: vi.fn(async () => Object.values(DESCRIPTORS).map(({ profile_id, name, family, inspiration, descriptor_version }) => ({ profile_id, name, family, inspiration, descriptor_version }))),
    getProfile: vi.fn(async (id: string) => {
      const d = DESCRIPTORS[id];
      if (!d) throw problem(404, "ECU_PROFILE_NOT_FOUND", {}, "Perfil não encontrado");
      return d;
    }),
    getCalibration: vi.fn(async (_id: string, opts?: { version?: number }) => (opts?.version ? { ...current, version: opts.version } : current)),
    putCalibration: vi.fn(async (_id: string, body: Record<string, unknown>) => {
      current = { ...current, version: current.version + 1, strategies: (body.strategies as Calibration["strategies"]) ?? current.strategies };
      return current;
    }),
    cloneCalibration: vi.fn(async (body: { clone_from_id: string; metadata: { name: string } }) => ({
      ...current,
      calibration_id: `user-${body.clone_from_id}`,
      version: 1,
      parent_version: null,
      metadata: { ...current.metadata, name: body.metadata.name, source: "clone", extra: {} },
    })),
    patchTable: vi.fn(async (_id: string, tableId: string, body: { base_version: number }) => {
      current = { ...current, version: body.base_version + 1 };
      return { version: body.base_version + 1, content_hash: "c".repeat(64), table: current.tables[tableId]! };
    }),
    applyToSession: vi.fn(async (_s: string, body: { calibration_id: string; version?: number }) => ({
      session_id: SESSION_ID,
      calibration_id: body.calibration_id,
      version: body.version ?? current.version,
      content_hash: "d".repeat(64),
      mode: "full" as const,
      changed_tables: [],
      applied_t_sim_s: 1.5,
    })),
    swap: vi.fn(async (_s: string, body: { target_profile_id: string }) => ({
      session_id: SESSION_ID,
      previous_profile_id: "oem-stage",
      profile_id: body.target_profile_id,
      ecu_state: "awaiting_base_setup" as const,
      base_setup_version: null,
      calibration_id: null,
      checklist: { ...checklistFixture, minimum_valid: false },
      hardware_sheet: hardwareFixture,
    })),
    getBaseSetup: vi.fn(async () => ({
      session_id: SESSION_ID,
      profile_id: "ft-pro",
      editable: true,
      ecu_state: "awaiting_base_setup" as const,
      base_setup_version: null,
      base_setup: null,
      setup_hash: null,
      checklist: checklistFixture,
      hardware_sheet: hardwareFixture,
      warnings: [],
    })),
    putBaseSetup: vi.fn(async () => ({
      session_id: SESSION_ID,
      profile_id: "ft-pro",
      editable: true,
      ecu_state: "standalone_ready" as const,
      base_setup_version: 1,
      base_setup: {},
      setup_hash: "e".repeat(64),
      checklist: checklistFixture,
      hardware_sheet: hardwareFixture,
      calibration_id: CAL_ID,
      calibration_version: 1,
      warnings: [],
    })),
    aiTune: vi.fn(async () => ({
      corrections: [
        {
          table_id: "ve",
          row: 0,
          col: 0,
          old_value: 60,
          new_value: 65,
          action: "enrich_light",
          confidence: 0.9,
          explanation: "Enriquecimento fino",
        },
      ],
      total_cells_modified: 1,
      summary: "1 célula ajustada",
      safety_risk: false,
      risk_confidence: 0.95,
      estimated_torque_gain_pct: 3.5,
    })),
    ...over,
  };
  return api as unknown as FakeApi;
}
