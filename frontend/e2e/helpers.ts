/**
 * Auxiliares partilhados das jornadas Playwright (T221–T224): chamadas REST para os passos
 * pesados (calibrações completas, limpeza), espera de puxadas e utilitários da cockpit.
 *
 * O backend corre a 1000 Hz em tempo real (steps_per_tick = 1) e só aceita uma sessão ativa
 * (`max_active_sessions = 1`): cada teste regista as sessões/tentativas que cria em `Cleanup`
 * e liberta-as no `finally`.
 */
import { createRequire } from "node:module";

import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const API = "/api/v1";
export const TERMINAL = new Set(["completed", "aborted", "engine_failed"]);

export type Json = Record<string, unknown>;

export interface TableJson {
  table_id: string;
  dims: number;
  x: { quantity: string; values: number[] };
  y?: { quantity: string; values: number[] };
  values: number[] | number[][];
  [key: string]: unknown;
}

export interface CalibrationJson {
  calibration_id: string;
  version: number;
  fuel_model: Json;
  tables: Record<string, TableJson>;
  strategies: Record<string, Json>;
  profile_params: Json;
  metadata: Json;
  content_hash: string;
}

export interface RunJson {
  run_id: string;
  state: string;
  summary: {
    peak_whp: number;
    egt_max_c: number;
    peak_torque_engine_nm: number;
    failure_event_id: string | null;
    knock_events: number;
  } | null;
  curve?: { rpm: number; lambda: number }[];
  pulls?: unknown[];
  repeatability?: { peak_whp_spread_pct: number } | null;
  abort_reason?: string | null;
}

/** Corpo JSON de uma resposta com o estado HTTP esperado (mensagem com o corpo em caso de erro). */
export async function expectJson<T>(response: { status(): number; text(): Promise<string> }, status: number): Promise<T> {
  const text = await response.text();
  expect(response.status(), text.slice(0, 500)).toBe(status);
  return JSON.parse(text) as T;
}

/** Sessões e tentativas criadas pelo teste, libertadas no fim (uma sessão ativa por estação). */
export class Cleanup {
  private readonly sessions: { request: APIRequestContext; id: string }[] = [];
  private readonly attempts: { request: APIRequestContext; id: string; headers: Record<string, string> }[] = [];

  session(request: APIRequestContext, id: string): void {
    this.sessions.push({ request, id });
  }

  attempt(request: APIRequestContext, id: string, headers: Record<string, string>): void {
    this.attempts.push({ request, id, headers });
  }

  async run(): Promise<void> {
    for (const a of this.attempts) {
      await a.request.post(`${API}/attempts/${a.id}/abandon`, { headers: a.headers }).catch(() => undefined);
    }
    for (const s of this.sessions) {
      await s.request.delete(`${API}/sessions/${s.id}`).catch(() => undefined);
    }
  }
}

/**
 * Liberta as sessões ativas deixadas por um teste anterior interrompido (timeout mata o `finally`):
 * a estação de E2E é dedicada, e o 409 `SIM_CAPACITY_EXCEEDED` indica os `active_session_ids`.
 */
export async function freeCapacity(request: APIRequestContext, response: { status(): number; json(): Promise<unknown> }): Promise<boolean> {
  if (response.status() !== 409) return false;
  const problem = (await response.json()) as { code?: string; active_session_ids?: string[] };
  if (problem.code !== "SIM_CAPACITY_EXCEEDED" || !problem.active_session_ids?.length) return false;
  for (const id of problem.active_session_ids) await request.delete(`${API}/sessions/${id}`);
  return true;
}

export async function createSession(request: APIRequestContext, body: Json, cleanup: Cleanup): Promise<Json & { session_id: string }> {
  let response = await request.post(`${API}/sessions`, { data: body });
  if (await freeCapacity(request, response)) response = await request.post(`${API}/sessions`, { data: body });
  const session = await expectJson<Json & { session_id: string }>(response, 201);
  cleanup.session(request, session.session_id);
  return session;
}

export async function getCalibration(request: APIRequestContext, id: string): Promise<CalibrationJson> {
  return expectJson<CalibrationJson>(await request.get(`${API}/calibrations/${id}`), 200);
}

/** Clona a calibração de série e grava `tables` como nova versão (PUT completo, E-16 + E-18). */
export async function cloneWithTables(
  request: APIRequestContext,
  vehicleId: string,
  profileId: string,
  stockId: string,
  name: string,
  edit: (tables: Record<string, TableJson>) => void,
  editStrategies?: (strategies: Record<string, Json>) => void,
): Promise<CalibrationJson> {
  const created = await expectJson<CalibrationJson>(
    await request.post(`${API}/calibrations`, {
      data: { vehicle_id: vehicleId, profile_id: profileId, source: "clone", clone_from_id: stockId, metadata: { name } },
    }),
    201,
  );
  const tables = structuredClone(created.tables);
  edit(tables);
  const strategies = structuredClone(created.strategies);
  editStrategies?.(strategies);
  return expectJson<CalibrationJson>(
    await request.put(`${API}/calibrations/${created.calibration_id}`, {
      data: {
        base_version: created.version,
        fuel_model: created.fuel_model,
        tables,
        strategies,
        profile_params: created.profile_params,
        metadata: { ...created.metadata, name, change_summary: name },
      },
    }),
    200,
  );
}

export async function applyCalibration(request: APIRequestContext, sessionId: string, calibrationId: string): Promise<void> {
  await expectJson(
    await request.post(`${API}/sessions/${sessionId}/calibration`, {
      data: { calibration_id: calibrationId, profile_options: { auto_fix_checksum: true } },
    }),
    200,
  );
}

export async function waitRun(request: APIRequestContext, runId: string, timeoutMs = 240_000): Promise<RunJson> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const run = await expectJson<RunJson>(await request.get(`${API}/runs/${runId}`), 200);
    if (TERMINAL.has(run.state)) return run;
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`a puxada ${runId} não terminou em ${timeoutMs} ms`);
}

/** Abre a cockpit da sessão e espera a telemetria ligada. */
export async function openCockpit(page: Page, sessionId: string): Promise<void> {
  await page.goto(`/sessions/${sessionId}/dyno`);
  await expect(page.getByTestId("vehicle-name")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("connection-state")).toHaveText("conectado", { timeout: 20_000 });
}

/**
 * Configura a puxada nos controlos da cockpit, clica Iniciar e devolve o `run_id` do `POST .../runs`.
 */
export async function startRunInCockpit(
  page: Page,
  runType: "baseline_pull" | "sweep_pull" | "multi_pull",
  opts: { rampRpmS?: number; pullCount?: number } = {},
): Promise<string> {
  await page.getByRole("combobox", { name: "Tipo de puxada" }).selectOption(runType);
  if (opts.rampRpmS !== undefined) await page.getByRole("spinbutton", { name: "Rampa" }).fill(String(opts.rampRpmS));
  if (opts.pullCount !== undefined) await page.getByRole("spinbutton", { name: "Número de puxadas" }).fill(String(opts.pullCount));
  const posted = page.waitForResponse((r) => r.request().method() === "POST" && /\/api\/v1\/sessions\/[^/]+\/runs$/.test(r.url()));
  await page.getByRole("button", { name: "Iniciar" }).click();
  const response = await posted;
  const body = await expectJson<{ run_id: string }>(response, 202);
  return body.run_id;
}

/** Eventos do DataLog da puxada (`header.events`, E-27 em JSON). */
export async function logEvents(request: APIRequestContext, runId: string): Promise<{ type: string; payload: Json }[]> {
  for (let i = 0; i < 40; i++) {
    const res = await request.get(`${API}/runs/${runId}/log`);
    if (res.status() === 200) {
      const body = (await res.json()) as { header: { events: { type: string; payload: Json }[] } };
      return body.header.events;
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`log da puxada ${runId} indisponível`);
}

export const KNOCK_RANK: Record<string, number> = { none: 0, light: 1, moderate: 2, severe: 3 };

export function worstKnock(events: { type: string; payload: Json }[]): string {
  let worst = 0;
  for (const e of events) if (e.type === "event.knock") worst = Math.max(worst, KNOCK_RANK[String(e.payload.knock_class)] ?? 0);
  return Object.keys(KNOCK_RANK).find((k) => KNOCK_RANK[k] === worst) ?? "none";
}

export function interp(x: number, xs: number[], ys: number[]): number {
  if (x <= xs[0]!) return ys[0]!;
  for (let i = 1; i < xs.length; i++) {
    const x0 = xs[i - 1]!;
    const x1 = xs[i]!;
    if (x <= x1) return ys[i - 1]! + ((x - x0) / (x1 - x0)) * (ys[i]! - ys[i - 1]!);
  }
  return ys[ys.length - 1]!;
}

export function grid(table: TableJson): number[][] {
  return table.values as number[][];
}

const require = createRequire(import.meta.url);
const AXE_PATH = require.resolve("axe-core/axe.min.js");
const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

interface AxeViolation {
  id: string;
  impact: string | null;
  help: string;
  nodes: { target: string[]; failureSummary?: string }[];
}

/**
 * Corre o axe-core na página (WCAG 2.0/2.1 A e AA, com `color-contrast`) e devolve as violações
 * em texto. O teste precisa de `bypassCSP: true`: o CSP de produção bloqueia o script injetado.
 */
export async function audit(page: Page, screen: string): Promise<string[]> {
  await page.addScriptTag({ path: AXE_PATH });
  const violations = await page.evaluate(async (tags) => {
    const axe = (window as unknown as { axe: { run: (ctx: Document, opts: unknown) => Promise<{ violations: AxeViolation[] }> } }).axe;
    const result = await axe.run(document, { runOnly: { type: "tag", values: tags }, resultTypes: ["violations"] });
    return result.violations.map((v) => ({ id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.map((n) => ({ target: n.target, failureSummary: n.failureSummary })) }));
  }, AXE_TAGS);
  return violations.flatMap((v) =>
    v.nodes.map((n) => `${screen}: ${v.id} (${v.impact}) ${v.help} — ${n.target.join(" ")} — ${(n.failureSummary ?? "").replace(/\s+/g, " ").slice(0, 200)}`),
  );
}

// ---------------------------------------------------------------- feature 003 (T024)

export const PROFILE_KEY = "simremap.activeProfileId";

/** Perfil de jogador novo (REST) com o cabeçalho pronto para as rotas de cenários. */
export async function createPlayer(
  request: APIRequestContext,
  nickname: string,
  role: "student" | "instructor" = "student",
): Promise<{ id: string; headers: Record<string, string> }> {
  const body = await expectJson<{ profile_id: string }>(await request.post(`${API}/profiles`, { data: { nickname, role } }), 201);
  return { id: body.profile_id, headers: { "X-Player-Profile-Id": body.profile_id } };
}

/** Ativa o perfil de jogador no `localStorage` antes de cada navegação da página. */
export async function usePlayer(page: Page, profileId: string): Promise<void> {
  await page.addInitScript(([key, id]) => localStorage.setItem(key!, id!), [PROFILE_KEY, profileId]);
}

/** Erros de consola e exceções não tratadas da página (ruído de rede esperado filtrado). */
export function watchConsole(page: Page, ignore: RegExp[] = []): string[] {
  const errors: string[] = [];
  const noise = [/Failed to load resource/i, /WebSocket connection to .* failed/i, ...ignore];
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    const text = msg.text();
    if (!noise.some((re) => re.test(text))) errors.push(`console: ${text}`);
  });
  page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
  return errors;
}

export interface AttemptJson {
  attempt_id: string;
  scenario_id: string;
  state: string;
  session_id: string | null;
  calibration_id: string;
  baseline_peak_whp: number | null;
  submissions: number;
  progress: { criterion_id: string; measured: number | null; passed: boolean | null }[];
}

/** Espera a tentativa sair de `preparing` (puxada base automática). */
export async function waitAttemptReady(request: APIRequestContext, attemptId: string, headers: Record<string, string>, timeoutMs = 180_000): Promise<AttemptJson> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const attempt = await expectJson<AttemptJson>(await request.get(`${API}/attempts/${attemptId}`, { headers }), 200);
    if (attempt.state !== "preparing") return attempt;
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`a tentativa ${attemptId} não saiu de preparing em ${timeoutMs} ms`);
}

/**
 * Acerto real dos cenários de defeito na ECU de série: λ alvo ≤ `lambda` com MAP ≥ 120 kPa
 * (o defeito empobrece a mistura em plena carga). Grava como nova versão da calibração da
 * sessão (PUT completo) e aplica-a.
 */
export async function enrichWot(request: APIRequestContext, sessionId: string, calibrationId: string, lambda = 0.8): Promise<CalibrationJson> {
  const cal = await getCalibration(request, calibrationId);
  const table = cal.tables.lambda_target!;
  const maps = table.y!.values;
  table.values = grid(table).map((row, j) => row.map((v) => (maps[j]! >= 120 ? Math.min(v, lambda) : v)));
  const saved = await expectJson<CalibrationJson>(
    await request.put(`${API}/calibrations/${cal.calibration_id}`, {
      data: {
        base_version: cal.version,
        fuel_model: cal.fuel_model,
        tables: cal.tables,
        strategies: cal.strategies,
        profile_params: cal.profile_params,
        metadata: { ...cal.metadata, change_summary: `λ ${lambda} em plena carga` },
      },
    }),
    200,
  );
  await applyCalibration(request, sessionId, saved.calibration_id);
  return saved;
}

export interface EvaluationJson {
  status: string;
  passed: boolean | null;
  total_score: number | null;
  results: { criterion_id: string; measured: number | null; passed: boolean }[];
}

export async function waitEvaluation(request: APIRequestContext, attemptId: string, headers: Record<string, string>, timeoutMs = 240_000): Promise<EvaluationJson> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const res = await request.get(`${API}/attempts/${attemptId}/evaluation`, { headers });
    if (res.status() === 200) {
      const ev = (await res.json()) as EvaluationJson;
      if (ev.status !== "pending" && ev.status !== "running") return ev;
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
  throw new Error(`a avaliação da tentativa ${attemptId} não terminou em ${timeoutMs} ms`);
}
