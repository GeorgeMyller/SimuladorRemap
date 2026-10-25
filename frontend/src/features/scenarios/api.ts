/**
 * Chamadas REST dos cenários de treino (contracts/rest-api.md E-30 a E-45).
 * Todo pedido leva `X-Player-Profile-Id` com o perfil ativo de `localStorage`
 * (`simremap.activeProfileId`). Injetável por `ScenariosApiProvider` (testes usam um falso).
 */
import { createContext, useContext } from "react";

import { apiFetch, apiUrl, ApiProblem, DEFAULT_TIMEOUT_MS } from "@/lib/api";
import { PROBLEM_JSON, problemDetailSchema } from "@/lib/api/problem";

import {
  ACTIVE_PROFILE_KEY,
  type AttemptPage,
  type AttemptView,
  type Evaluation,
  type ExportedFile,
  type HintReveal,
  type PackageExportRequest,
  type PackageImportResult,
  type PlayerProfile,
  type ReplayAccepted,
  type Role,
  type Scenario,
  type ScenarioKind,
  type ScenarioStats,
  type ScenarioSummary,
  type ScenarioView,
  type SubmitAccepted,
  type SubmitRequest,
} from "./types";

const enc = encodeURIComponent;

export interface AttemptQuery {
  scenario_id?: string;
  origin?: "local" | "imported";
  profile_id?: string;
  cursor?: string;
  limit?: number;
}

export interface ScenariosApi {
  listProfiles(): Promise<PlayerProfile[]>;
  createProfile(body: { nickname: string; role: Role }): Promise<PlayerProfile>;
  listScenarios(kind?: ScenarioKind): Promise<ScenarioSummary[]>;
  getScenario(scenarioId: string): Promise<ScenarioView>;
  createScenario(body: { scenario: Scenario; initial_calibration_id?: string }): Promise<ScenarioView>;
  getStats(scenarioId: string): Promise<ScenarioStats>;
  startAttempt(scenarioId: string): Promise<AttemptView>;
  listAttempts(query: AttemptQuery): Promise<AttemptPage>;
  getAttempt(attemptId: string): Promise<AttemptView>;
  revealHint(attemptId: string): Promise<HintReveal>;
  abandon(attemptId: string): Promise<AttemptView>;
  submit(attemptId: string, body: SubmitRequest): Promise<SubmitAccepted>;
  /** Calibração com que a puxada correu (`GET /runs/{id}`): reflete swap, Base Setup e "Aplicar". */
  getRunCalibrationId(runId: string): Promise<string | null>;
  getEvaluation(attemptId: string, submission?: number): Promise<Evaluation>;
  replay(attemptId: string): Promise<ReplayAccepted>;
  exportPackage(body: PackageExportRequest): Promise<ExportedFile>;
  importPackage(raw: string): Promise<PackageImportResult>;
}

/** Perfil ativo guardado no navegador (troca local, sem senha). */
export function getActiveProfileId(): string | null {
  try {
    return localStorage.getItem(ACTIVE_PROFILE_KEY);
  } catch {
    return null;
  }
}

export function setActiveProfileId(profileId: string | null): void {
  try {
    if (profileId) localStorage.setItem(ACTIVE_PROFILE_KEY, profileId);
    else localStorage.removeItem(ACTIVE_PROFILE_KEY);
  } catch {
    /* armazenamento indisponível: o perfil fica só na memória da página */
  }
}

function profileHeaders(): Record<string, string> {
  const id = getActiveProfileId();
  return id ? { "X-Player-Profile-Id": id } : {};
}

function call<T>(path: string, init: { method?: string; json?: unknown; body?: string; contentType?: string } = {}): Promise<T> {
  const headers: Record<string, string> = profileHeaders();
  if (init.contentType) headers["Content-Type"] = init.contentType;
  return apiFetch<T>(path, {
    method: init.method ?? "GET",
    headers,
    ...(init.json !== undefined ? { json: init.json } : {}),
    ...(init.body !== undefined ? { body: init.body } : {}),
  }).catch((err: unknown) => {
    if (err instanceof ApiProblem && err.code === "PLAYER_PROFILE_NOT_FOUND") {
      setActiveProfileId(null);
    }
    throw err;
  });
}

function query(params: Record<string, string | number | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
}

/** Nome do ficheiro em `Content-Disposition: attachment; filename="..."`. */
export function filenameFromDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback;
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(header);
  return match?.[1] ? decodeURIComponent(match[1]) : fallback;
}

async function exportPackage(body: PackageExportRequest): Promise<ExportedFile> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), DEFAULT_TIMEOUT_MS * 6);
  let response: Response;
  try {
    response = await fetch(apiUrl("/packages/export"), {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json", ...profileHeaders() },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } catch {
    throw ApiProblem.synthetic(0, "NETWORK_ERROR", "Não foi possível contactar o servidor.");
  } finally {
    clearTimeout(timer);
  }
  if (!response.ok) {
    const type = response.headers.get("Content-Type") ?? "";
    if (type.startsWith(PROBLEM_JSON)) {
      const parsed = problemDetailSchema.safeParse(await response.json().catch(() => null));
      if (parsed.success) throw new ApiProblem(parsed.data);
    }
    throw ApiProblem.synthetic(response.status, "UNEXPECTED_RESPONSE", `Resposta inesperada (HTTP ${response.status}).`);
  }
  const id = body.kind === "challenge" ? body.scenario_id : body.attempt_id;
  const filename = filenameFromDisposition(
    response.headers.get("Content-Disposition"),
    `simremap-${body.kind}-${id ?? "pacote"}.simremap.json`,
  );
  return { filename, content: await response.text() };
}

export const scenariosApi: ScenariosApi = {
  listProfiles: () => call("/profiles"),
  createProfile: (body) => call("/profiles", { method: "POST", json: body }),
  listScenarios: (kind) =>
    call<ScenarioSummary[]>(`/scenarios${query({ kind })}`).catch((err: unknown) => {
      if (err instanceof ApiProblem && err.code === "PLAYER_PROFILE_NOT_FOUND") {
        setActiveProfileId(null);
        return call<ScenarioSummary[]>(`/scenarios${query({ kind })}`);
      }
      throw err;
    }),
  getScenario: (id) => call(`/scenarios/${enc(id)}`),
  createScenario: (body) => call("/scenarios", { method: "POST", json: body }),
  getStats: (id) => call(`/scenarios/${enc(id)}/stats`),
  startAttempt: (id) => call(`/scenarios/${enc(id)}/attempts`, { method: "POST" }),
  listAttempts: (q) => call(`/attempts${query({ ...q })}`),
  getAttempt: (id) => call(`/attempts/${enc(id)}`),
  revealHint: (id) => call(`/attempts/${enc(id)}/hints`, { method: "POST" }),
  abandon: (id) => call(`/attempts/${enc(id)}/abandon`, { method: "POST" }),
  submit: (id, body) => call(`/attempts/${enc(id)}/submit`, { method: "POST", json: body }),
  getRunCalibrationId: async (runId) => {
    const run = await call<{ calibration_id?: string | null }>(`/runs/${enc(runId)}`);
    return run.calibration_id ?? null;
  },
  getEvaluation: (id, submission) => call(`/attempts/${enc(id)}/evaluation${query({ submission })}`),
  replay: (id) => call(`/attempts/${enc(id)}/replay`, { method: "POST" }),
  exportPackage,
  // O ficheiro vai tal como foi lido: o servidor recalcula o hash sobre o JSON recebido.
  importPackage: (raw) => call("/packages/import", { method: "POST", body: raw, contentType: "application/json" }),
};

export const ScenariosApiContext = createContext<ScenariosApi>(scenariosApi);

export function useScenariosApi(): ScenariosApi {
  return useContext(ScenariosApiContext);
}

/** Mensagem curta de erro para a UI (`title`, `detail` e `code`). */
export function problemMessage(error: unknown): { code: string; text: string } {
  if (error instanceof ApiProblem) return { code: error.code, text: `${error.title}: ${error.detail}` };
  return { code: "INTERNAL_ERROR", text: error instanceof Error ? error.message : String(error) };
}

/** Descarrega um ficheiro de texto pelo navegador (Blob + link temporário). */
export function downloadText(filename: string, content: string, mime = "application/json"): void {
  const blob = new Blob([content], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
