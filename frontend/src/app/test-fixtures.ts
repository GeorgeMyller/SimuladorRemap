/** Fixtures da casca e da tela inicial (catálogo de 4 carros, perfis de ECU, cenários). */
import { vi } from "vitest";

import type { UpgradeCategoryOptions, VehicleCompat } from "@/features/workshop/types";

import type { EcuProfileSummary, HomeApi, ScenarioSummary, SimulationSession, VehicleSummary } from "./homeApi";

function vehicle(
  vehicle_id: string,
  display_name: string,
  induction: string,
  n_cyl: number,
  displacement_cc: number,
  stock_profile_id: VehicleSummary["stock_profile_id"],
  whp: number,
  validation_status: VehicleSummary["validation_status"] = "validated",
): VehicleSummary {
  return {
    vehicle_id,
    display_name,
    architecture_note: `Arquitetura de ${display_name}`,
    body: "hatch",
    induction,
    n_cyl,
    displacement_cc,
    stock_fuel_id: "e27",
    stock_profile_id,
    rated: { peak_power_whp: whp, peak_power_rpm: 5500, peak_torque_nm: 350, peak_torque_rpm_from: 2500, peak_torque_rpm_to: 4500 },
    validation_status,
    data_version: 1,
  };
}

export const VEHICLES: VehicleSummary[] = [
  vehicle("hatch-20t-gdi", "Hatch 2.0 Turbo GDI", "turbo", 4, 1998, "oem-stage", 220, "draft"),
  vehicle("coupe-30t-i6", "Coupé 3.0 Turbo I6", "turbo", 6, 2998, "ft-pro", 330),
  vehicle("classic-20t-swap", "Clássico 2.0 Turbo (swap)", "turbo", 4, 1998, "m1-race", 280),
  vehicle("muscle-v8-sc", "Muscle V8 Compressor", "supercharger", 8, 6200, "ht-elite", 520),
];

export const ECU_PROFILES: EcuProfileSummary[] = [
  { profile_id: "oem-stage", name: "OEM-Stage", family: "oem", inspiration: "ECU de série", descriptor_version: "1.0.0" },
  { profile_id: "ft-pro", name: "FT-Pro", family: "standalone", inspiration: "Standalone", descriptor_version: "1.0.0" },
  { profile_id: "m1-race", name: "M1-Race", family: "standalone", inspiration: "Competição", descriptor_version: "1.0.0" },
  { profile_id: "ht-elite", name: "HT-Elite", family: "standalone", inspiration: "Elite", descriptor_version: "1.0.0" },
] as EcuProfileSummary[];

export const HOME_SCENARIOS: ScenarioSummary[] = [
  { scenario_id: "stage1-oem", kind: "base", title: "Stage 1 na ECU de série", vehicle_id: "hatch-20t-gdi", fuel_id: "e27", has_hidden_defect: false, available: true, last_evaluation_passed: null },
  { scenario_id: "indisponivel", kind: "base", title: "Cenário indisponível", vehicle_id: "hatch-20t-gdi", fuel_id: "e27", has_hidden_defect: false, available: false, last_evaluation_passed: null },
  { scenario_id: "v8-e100", kind: "base", title: "V8 no etanol", vehicle_id: "muscle-v8-sc", fuel_id: "e100", has_hidden_defect: true, available: true, last_evaluation_passed: null },
];

export const NEW_SESSION_ID = "9a8b7c6d5e4f40312a2b3c4d5e6f7081";

export function sessionFixture(over: Partial<SimulationSession> = {}): SimulationSession {
  return {
    session_id: NEW_SESSION_ID,
    vehicle_id: "hatch-20t-gdi",
    calibration_id: "cal-1",
    profile_id: "oem-stage",
    seed: 1,
    fuel_id: "e27",
    state: "ready",
    created_at: "2026-10-18T10:00:00Z",
    ...over,
  };
}

/** Catálogo de peças no formato do `GET /api/v1/upgrades`. */
export const UPGRADE_CATALOG: UpgradeCategoryOptions[] = [
  { category: "turbo", options: [{ part_id: "stock", label: "Série" }, { part_id: "upgraded", label: "Turbina upgraded", effects: { turbine_area_eff_scale: 1.25, rotor_inertia_scale: 1.45 } }] },
  { category: "injectors", options: [{ part_id: "stock", label: "Série" }, { part_id: "high_flow", label: "Bicos de alta vazão", effects: { injector_flow_scale: 1.5 } }] },
  { category: "fuel_pump", options: [{ part_id: "stock", label: "Série" }, { part_id: "high_flow", label: "Bomba de combustível de alta vazão", effects: { fuel_pump_capacity_scale: 1.8 } }] },
  { category: "intercooler", options: [{ part_id: "stock", label: "Série" }, { part_id: "sport", label: "Intercooler esportivo", effects: { intercooler_effectiveness_add: 0.08 } }] },
  { category: "downpipe", options: [{ part_id: "stock", label: "Série" }, { part_id: "high_flow", label: "Downpipe de alto fluxo", effects: { exhaust_backpressure_scale: 0.6 } }] },
  { category: "internals", options: [{ part_id: "stock", label: "Série" }, { part_id: "forged", label: "Internos forjados", effects: { max_piston_temp_add_c: 40 } }] },
];

/** Compatibilidade por veículo: o V8 com compressor não tem turbo nem intercooler e não aceita Flex. */
export function vehicleCompat(vehicleId: string): VehicleCompat {
  const isSupercharged = vehicleId === "muscle-v8-sc";
  return { vehicleId, hasTurbo: !isSupercharged, hasIntercooler: !isSupercharged, flexAllowed: !isSupercharged };
}

export type FakeHomeApi = { [K in keyof HomeApi]: ReturnType<typeof vi.fn<HomeApi[K]>> };

export function makeHomeApi(over: Partial<HomeApi> = {}): FakeHomeApi {
  return {
    listVehicles: vi.fn<HomeApi["listVehicles"]>(() => Promise.resolve(VEHICLES)),
    listEcuProfiles: vi.fn<HomeApi["listEcuProfiles"]>(() => Promise.resolve(ECU_PROFILES)),
    listScenarios: vi.fn<HomeApi["listScenarios"]>(() => Promise.resolve(HOME_SCENARIOS)),
    createSession: vi.fn<HomeApi["createSession"]>((body) => Promise.resolve(sessionFixture({ vehicle_id: body.vehicle_id }))),
    closeSession: vi.fn<HomeApi["closeSession"]>(() => Promise.resolve()),
    startAttempt: vi.fn<HomeApi["startAttempt"]>(() => Promise.resolve({ attempt_id: "att-1", session_id: NEW_SESSION_ID })),
    listUpgrades: vi.fn<HomeApi["listUpgrades"]>(() => Promise.resolve(UPGRADE_CATALOG)),
    getVehicleCompat: vi.fn<HomeApi["getVehicleCompat"]>((vehicleId) => Promise.resolve(vehicleCompat(vehicleId))),
    ...over,
  } as FakeHomeApi;
}
