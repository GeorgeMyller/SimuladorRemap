/** Contrato REST do editor de ECU: caminho, método, corpo e schema de cada chamada (E-03…E-25). */
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiFetch = vi.fn((..._args: unknown[]) => Promise.resolve({}));
vi.mock("@/lib/api", () => ({ apiFetch: (...args: unknown[]) => apiFetch(...args) }));

const { ecuApi } = await import("./api");

type Init = { method?: string; json?: unknown; schema?: unknown; signal?: AbortSignal | null };
const last = (): [string, Init] => apiFetch.mock.calls.at(-1) as [string, Init];

beforeEach(() => apiFetch.mockClear());

describe("ecuApi", () => {
  it.each([
    ["getSession", () => ecuApi.getSession("s 1"), "/sessions/s%201", undefined],
    ["getVehicle", () => ecuApi.getVehicle("hatch-20t-gdi"), "/vehicles/hatch-20t-gdi", undefined],
    ["listVehicles", () => ecuApi.listVehicles(), "/vehicles?include_drafts=true", undefined],
    ["listProfiles", () => ecuApi.listProfiles(), "/ecu-profiles", undefined],
    ["getProfile", () => ecuApi.getProfile("ft-pro"), "/ecu-profiles/ft-pro", undefined],
    ["getProfile com veículo", () => ecuApi.getProfile("ft-pro", "coupe-30t-i6"), "/ecu-profiles/ft-pro?vehicle_id=coupe-30t-i6", undefined],
    ["getCalibration", () => ecuApi.getCalibration("c1"), "/calibrations/c1", undefined],
    ["getCalibration com versão", () => ecuApi.getCalibration("c1", { version: 3, includeVersions: true }), "/calibrations/c1?version=3&include=versions", undefined],
    ["getBaseSetup", () => ecuApi.getBaseSetup("s1"), "/sessions/s1/ecu/base-setup", undefined],
  ])("%s faz GET em %s com schema", async (_name, call, path, method) => {
    await call();
    const [url, init] = last();
    expect(url).toBe(path);
    expect(init.method).toBe(method);
    expect(init.schema).toBeDefined();
  });

  it.each([
    ["createSession", () => ecuApi.createSession({ vehicle_id: "v", profile_id: "oem-stage" }), "/sessions", "POST"],
    ["putCalibration", () => ecuApi.putCalibration("c1", { base_version: 1, revert_to_version: 0 }), "/calibrations/c1", "PUT"],
    ["applyToSession", () => ecuApi.applyToSession("s1", { calibration_id: "c1", profile_options: {} }), "/sessions/s1/calibration", "POST"],
    [
      "swap",
      () => ecuApi.swap("s1", { target_profile_id: "ft-pro", confirm_snapshot: true, feature_package: "base", prefill_from_hardware_sheet: false }),
      "/sessions/s1/ecu/swap",
      "POST",
    ],
    [
      "putBaseSetup",
      () => ecuApi.putBaseSetup("s1", { base_version: null, base_setup: {}, generate_base_map: true, wizard: null, apply_limits_to_calibration: false }),
      "/sessions/s1/ecu/base-setup",
      "PUT",
    ],
  ])("%s envia %s %s com corpo JSON", async (_name, call, path, method) => {
    await call();
    const [url, init] = last();
    expect(url).toBe(path);
    expect(init.method).toBe(method);
    expect(init.json).toBeDefined();
  });

  it("patchTable usa PATCH e repassa o AbortSignal (null sem sinal)", async () => {
    const controller = new AbortController();
    const body = { base_version: 1, cells: [] } as unknown as Parameters<typeof ecuApi.patchTable>[2];
    await ecuApi.patchTable("c1", "ve main", body, controller.signal);
    expect(last()[0]).toBe("/calibrations/c1/tables/ve%20main");
    expect(last()[1]).toMatchObject({ method: "PATCH", json: body, signal: controller.signal });
    await ecuApi.patchTable("c1", "ve", body);
    expect(last()[1].signal).toBeNull();
  });

  it("deleteSession faz DELETE e resolve sem valor", async () => {
    await expect(ecuApi.deleteSession("s1")).resolves.toBeUndefined();
    expect(last()).toEqual(["/sessions/s1", { method: "DELETE" }]);
  });

  it("aiTune faz POST em /calibrations/:id/ai-tune com corpo e schema", async () => {
    const body = { target_table_ids: ["ve"], aggressiveness: "balanced" as const };
    await ecuApi.aiTune("c 1", body);
    const [url, init] = last();
    expect(url).toBe("/calibrations/c%201/ai-tune");
    expect(init.method).toBe("POST");
    expect(init.json).toEqual(body);
    expect(init.schema).toBeDefined();
  });
});
