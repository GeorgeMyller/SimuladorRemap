/**
 * Chamadas da tela inicial (cockpit RF-01; T435) pelo cliente gerado do orval (D-24):
 * E-01 `GET /vehicles`, E-26 `GET /ecu-profiles`, E-06 `POST /sessions` e, para o
 * cenário opcional, E-32 `GET /scenarios` e E-36 `POST /scenarios/{id}/attempts`; `DELETE
 * /sessions/{id}` encerra a sessão ativa quando a criação esbarra na capacidade.
 * A oficina de upgrades (002 T047) acrescenta `GET /upgrades` e a compatibilidade do veículo
 * (`GET /vehicles/{id}`); `upgrades` e `ethanol_pct` seguem no corpo do `POST /sessions`.
 * As respostas passam pelos schemas zod gerados. Injetável nos testes (`HomeApi`).
 */
import { z } from "zod";

import { createSessionApiV1SessionsPost, deleteSessionApiV1SessionsSessionIdDelete } from "@/lib/api/generated/dyno-bench/dyno-bench";
import { listProfilesApiV1EcuProfilesGet } from "@/lib/api/generated/ecu-profiles/ecu-profiles";
import type {
  EcuProfileSummary,
  SessionCreateRequest,
  SimulationSession,
  VehicleSummary,
} from "@/lib/api/generated/model";
import { listVehiclesApiV1VehiclesGet } from "@/lib/api/generated/vehicle-catalog/vehicle-catalog";
import { CreateSessionApiV1SessionsPostResponse } from "@/lib/api/generated/zod/dyno-bench/dyno-bench";
import { ListProfilesApiV1EcuProfilesGetResponse } from "@/lib/api/generated/zod/ecu-profiles/ecu-profiles";
import { ListVehiclesApiV1VehiclesGetResponse } from "@/lib/api/generated/zod/vehicle-catalog/vehicle-catalog";
import { scenariosApi } from "@/features/scenarios/api";
import { workshopApi, type WorkshopApi } from "@/features/workshop/api";
import type { ScenarioSummary } from "@/features/scenarios/types";

export type { EcuProfileSummary, ScenarioSummary, SimulationSession, VehicleSummary };

/**
 * O servidor sorteia a semente em 63 bits (`SEED_MAX = 2^63 − 1`): acima de 2^53 o JSON.parse
 * perde precisão e o `int()` do zod gerado recusa a resposta. A tela inicial não usa a semente,
 * então basta exigir um número não negativo.
 */
const createdSessionSchema = CreateSessionApiV1SessionsPostResponse.extend({ seed: z.number().nonnegative() });

export interface StartedAttempt {
  attempt_id: string;
  session_id: string | null;
}

export interface HomeApi extends WorkshopApi {
  listVehicles(): Promise<VehicleSummary[]>;
  listEcuProfiles(): Promise<EcuProfileSummary[]>;
  listScenarios(): Promise<ScenarioSummary[]>;
  createSession(body: SessionCreateRequest): Promise<SimulationSession>;
  closeSession(sessionId: string): Promise<void>;
  startAttempt(scenarioId: string): Promise<StartedAttempt>;
}

export const homeApi: HomeApi = {
  async listVehicles() {
    const page = ListVehiclesApiV1VehiclesGetResponse.parse(await listVehiclesApiV1VehiclesGet({ include_drafts: true }));
    return page.items;
  },
  async listEcuProfiles() {
    return ListProfilesApiV1EcuProfilesGetResponse.parse(await listProfilesApiV1EcuProfilesGet());
  },
  // Pelo cliente dos cenários: leva o cabeçalho X-Player-Profile-Id do perfil ativo.
  listScenarios: () => scenariosApi.listScenarios(),
  async createSession(body) {
    return createdSessionSchema.parse(await createSessionApiV1SessionsPost(body));
  },
  closeSession: (sessionId) => deleteSessionApiV1SessionsSessionIdDelete(sessionId),
  async startAttempt(scenarioId) {
    const attempt = await scenariosApi.startAttempt(scenarioId);
    return { attempt_id: attempt.attempt_id, session_id: attempt.session_id ?? null };
  },
  listUpgrades: () => workshopApi.listUpgrades(),
  getVehicleCompat: (vehicleId) => workshopApi.getVehicleCompat(vehicleId),
};
