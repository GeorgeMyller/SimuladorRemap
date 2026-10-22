/**
 * Chamadas REST do editor de ECU (contracts/rest-api.md E-03, E-04, E-06–E-08, E-16 clone, E-17–E-25).
 * Injetável por `EcuApi` (os testes passam uma implementação falsa).
 */
import { z } from "zod";

import { apiFetch } from "@/lib/api";

import {
  applyCalibrationResultSchema,
  baseSetupResultSchema,
  calibrationSchema,
  ecuProfileDescriptorSchema,
  ecuProfileSummarySchema,
  sessionSchema,
  swapResultSchema,
  tablePatchResultSchema,
  vehicleDetailSchema,
  vehicleListSchema,
  aiTuneResponseSchema,
  type AiTuneRequest,
  type AiTuneResponse,
  type ApplyCalibrationResult,
  type BaseSetupResult,
  type Calibration,
  type EcuProfileDescriptor,
  type EcuProfileSummary,
  type Session,
  type SwapResult,
  type TablePatchBody,
  type TablePatchResult,
  type VehicleDetail,
} from "./types";

const enc = encodeURIComponent;

export interface SwapRequestBody {
  target_profile_id: string;
  confirm_snapshot: boolean;
  feature_package: "base" | "race";
  prefill_from_hardware_sheet: boolean;
  request_id?: string;
}

export interface BaseSetupUpdateBody {
  base_version: number | null;
  base_setup: Record<string, unknown>;
  generate_base_map: boolean;
  wizard: Record<string, unknown> | null;
  apply_limits_to_calibration: boolean;
}

/** Corpo do `PUT` E-18 (substituição completa ou reversão). */
export type CalibrationPutBody =
  | {
      base_version: number;
      fuel_model: Record<string, unknown>;
      tables: Record<string, unknown>;
      strategies: Record<string, unknown>;
      profile_params: Record<string, unknown>;
      metadata: Record<string, unknown>;
    }
  | { base_version: number; revert_to_version: number; change_summary?: string };

/** Corpo do `POST /calibrations` (E-16) no modo clone: cópia editável de outra calibração. */
export interface CalibrationCloneBody {
  vehicle_id: string;
  profile_id: string;
  source: "clone";
  clone_from_id: string;
  clone_from_version?: number;
  metadata: { name: string; source: "clone"; change_summary?: string };
}

export interface EcuApi {
  getSession(sessionId: string): Promise<Session>;
  createSession(body: { vehicle_id: string; profile_id: string }): Promise<Session>;
  deleteSession(sessionId: string): Promise<void>;
  getVehicle(vehicleId: string): Promise<VehicleDetail>;
  listVehicles(): Promise<z.infer<typeof vehicleListSchema>>;
  listProfiles(): Promise<EcuProfileSummary[]>;
  getProfile(profileId: string, vehicleId?: string): Promise<EcuProfileDescriptor>;
  getCalibration(calibrationId: string, opts?: { version?: number; includeVersions?: boolean }): Promise<Calibration>;
  putCalibration(calibrationId: string, body: CalibrationPutBody): Promise<Calibration>;
  cloneCalibration(body: CalibrationCloneBody): Promise<Calibration>;
  patchTable(calibrationId: string, tableId: string, body: TablePatchBody, signal?: AbortSignal): Promise<TablePatchResult>;
  applyToSession(sessionId: string, body: { calibration_id: string; version?: number; profile_options: Record<string, boolean> }): Promise<ApplyCalibrationResult>;
  swap(sessionId: string, body: SwapRequestBody): Promise<SwapResult>;
  getBaseSetup(sessionId: string): Promise<BaseSetupResult>;
  putBaseSetup(sessionId: string, body: BaseSetupUpdateBody): Promise<BaseSetupResult>;
  aiTune(calibrationId: string, body?: AiTuneRequest): Promise<AiTuneResponse>;
}

export const ecuApi: EcuApi = {
  getSession: (id) => apiFetch(`/sessions/${enc(id)}`, { schema: sessionSchema }),
  createSession: (body) => apiFetch("/sessions", { method: "POST", json: body, schema: sessionSchema }),
  deleteSession: async (id) => {
    await apiFetch(`/sessions/${enc(id)}`, { method: "DELETE" });
  },
  getVehicle: (id) => apiFetch(`/vehicles/${enc(id)}`, { schema: vehicleDetailSchema }),
  listVehicles: () => apiFetch("/vehicles?include_drafts=true", { schema: vehicleListSchema }),
  listProfiles: () => apiFetch("/ecu-profiles", { schema: z.array(ecuProfileSummarySchema) }),
  getProfile: (id, vehicleId) =>
    apiFetch(`/ecu-profiles/${enc(id)}${vehicleId ? `?vehicle_id=${enc(vehicleId)}` : ""}`, {
      schema: ecuProfileDescriptorSchema,
    }),
  getCalibration: (id, opts = {}) => {
    const q = new URLSearchParams();
    if (opts.version !== undefined) q.set("version", String(opts.version));
    if (opts.includeVersions) q.set("include", "versions");
    const qs = q.toString();
    return apiFetch(`/calibrations/${enc(id)}${qs ? `?${qs}` : ""}`, { schema: calibrationSchema });
  },
  putCalibration: (id, body) => apiFetch(`/calibrations/${enc(id)}`, { method: "PUT", json: body, schema: calibrationSchema }),
  cloneCalibration: (body) => apiFetch("/calibrations", { method: "POST", json: body, schema: calibrationSchema }),
  patchTable: (id, tableId, body, signal) =>
    apiFetch(`/calibrations/${enc(id)}/tables/${enc(tableId)}`, {
      method: "PATCH",
      json: body,
      schema: tablePatchResultSchema,
      signal: signal ?? null,
    }),
  applyToSession: (sessionId, body) =>
    apiFetch(`/sessions/${enc(sessionId)}/calibration`, { method: "POST", json: body, schema: applyCalibrationResultSchema }),
  swap: (sessionId, body) => apiFetch(`/sessions/${enc(sessionId)}/ecu/swap`, { method: "POST", json: body, schema: swapResultSchema }),
  getBaseSetup: (sessionId) => apiFetch(`/sessions/${enc(sessionId)}/ecu/base-setup`, { schema: baseSetupResultSchema }),
  putBaseSetup: (sessionId, body) =>
    apiFetch(`/sessions/${enc(sessionId)}/ecu/base-setup`, { method: "PUT", json: body, schema: baseSetupResultSchema }),
  aiTune: (calibrationId, body = {}) =>
    apiFetch(`/calibrations/${enc(calibrationId)}/ai-tune`, {
      method: "POST",
      json: body,
      schema: aiTuneResponseSchema,
      timeoutMs: 180_000,
    }),
};
