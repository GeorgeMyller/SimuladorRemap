/**
 * Chamadas da oficina de upgrades pelo cliente orval: `GET /upgrades` (catálogo de peças) e
 * `GET /vehicles/{id}` (só o que decide a compatibilidade: turbo, intercooler e combustíveis).
 * A aba Upgrades da sessão acrescenta `GET /sessions/{id}` e `PUT /sessions/{id}/upgrades`
 * (peças instaladas com a sessão viva).
 */
import { z } from "zod";

import {
  getSessionApiV1SessionsSessionIdGet,
  installUpgradesApiV1SessionsSessionIdUpgradesPut,
} from "@/lib/api/generated/dyno-bench/dyno-bench";
import type { SimulationSession, UpgradePackage } from "@/lib/api/generated/model";
import { getVehicleApiV1VehiclesVehicleIdGet, listUpgradesApiV1UpgradesGet } from "@/lib/api/generated/vehicle-catalog/vehicle-catalog";
import {
  GetSessionApiV1SessionsSessionIdGetResponse,
  InstallUpgradesApiV1SessionsSessionIdUpgradesPutResponse,
} from "@/lib/api/generated/zod/dyno-bench/dyno-bench";
import { ListUpgradesApiV1UpgradesGetResponse } from "@/lib/api/generated/zod/vehicle-catalog/vehicle-catalog";

import type { UpgradeCategoryOptions, VehicleCompat } from "./types";

export type { SimulationSession, UpgradePackage };

export interface WorkshopApi {
  listUpgrades(): Promise<UpgradeCategoryOptions[]>;
  getVehicleCompat(vehicleId: string): Promise<VehicleCompat>;
}

const vehicleCompatSchema = z.object({
  vehicle_id: z.string(),
  turbo: z.object({}).nullish(),
  engine: z.object({ intercooler: z.object({}).nullish() }),
  allowed_fuel_ids: z.array(z.string()),
});

export function compatFromVehicle(raw: unknown): VehicleCompat {
  const vehicle = vehicleCompatSchema.parse(raw);
  const fuels = new Set(vehicle.allowed_fuel_ids);
  return {
    vehicleId: vehicle.vehicle_id,
    hasTurbo: vehicle.turbo != null,
    hasIntercooler: vehicle.engine.intercooler != null,
    flexAllowed: fuels.has("e27") && fuels.has("e100"),
  };
}

export interface SessionUpgradesApi extends WorkshopApi {
  getSession(sessionId: string): Promise<SimulationSession>;
  installUpgrades(sessionId: string, upgrades: UpgradePackage): Promise<SimulationSession>;
}

/** A semente vai até 2^63 − 1: acima de 2^53 o `int()` do zod gerado recusa a resposta. */
const sessionSchema = GetSessionApiV1SessionsSessionIdGetResponse.extend({ seed: z.number().nonnegative() });
const installedSchema = InstallUpgradesApiV1SessionsSessionIdUpgradesPutResponse.extend({ seed: z.number().nonnegative() });

export const workshopApi: WorkshopApi = {
  async listUpgrades() {
    return ListUpgradesApiV1UpgradesGetResponse.parse(await listUpgradesApiV1UpgradesGet()).categories;
  },
  async getVehicleCompat(vehicleId) {
    return compatFromVehicle(await getVehicleApiV1VehiclesVehicleIdGet(vehicleId));
  },
};

export const sessionUpgradesApi: SessionUpgradesApi = {
  ...workshopApi,
  async getSession(sessionId) {
    return sessionSchema.parse(await getSessionApiV1SessionsSessionIdGet(sessionId));
  },
  async installUpgrades(sessionId, upgrades) {
    return installedSchema.parse(await installUpgradesApiV1SessionsSessionIdUpgradesPut(sessionId, upgrades));
  },
};
