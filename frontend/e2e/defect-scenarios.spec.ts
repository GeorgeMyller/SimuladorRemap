/**
 * Cenários de treino no navegador (003 T024; RF-15, RF-17; 002 RF-23, RF-24).
 *
 * - Os 7 cenários (3 base + 4 defeitos): lista → briefing → "Iniciar tentativa" ⇒ `/attempts/:id`,
 *   puxada base automática ⇒ "Em curso" com o pico da base e a puxada listada; "Abrir bancada"
 *   ⇒ cockpit com o painel lateral; nos defeitos, o seletor "Defeito diagnosticado" oferece os 5
 *   tipos do backend (inclui o vazamento de pressão).
 * - Critério de aceitação da 003: `defect-lean-injector`, o aluno declara "Injetor entupido"
 *   (cilindro 3 pela EGT individual), corrige a calibração (λ 0,80 em plena carga) e a submissão
 *   pela página da tentativa é aprovada.
 */
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { API, Cleanup, createPlayer, enrichWot, expectJson, freeCapacity, usePlayer, waitEvaluation, type AttemptJson } from "./helpers";

test.use({ viewport: { width: 1366, height: 768 } });

const SCENARIOS = ["stage1-oem", "stage2-pops-bangs", "standalone-swap", "defect-fuel-pump", "defect-boost-leak", "defect-lean-injector", "defect-wastegate-stuck"];
const DEFECT_OPTIONS = ["Bomba de combustível fraca", "Injetor entupido", "Sensor IAT descalibrado", "Wastegate travada", "Vazamento no circuito de pressão"];

async function ensureCapacity(request: APIRequestContext): Promise<void> {
  const probe = await request.post(`${API}/sessions`, { data: { vehicle_id: "hatch-20t-gdi" } });
  if (await freeCapacity(request, probe)) return;
  if (probe.status() === 201) await request.delete(`${API}/sessions/${((await probe.json()) as { session_id: string }).session_id}`);
}

/** Lista → briefing → "Iniciar tentativa"; espera a puxada base e devolve a tentativa. */
async function startFromList(page: Page, request: APIRequestContext, scenarioId: string, headers: Record<string, string>, cleanup: Cleanup): Promise<AttemptJson> {
  const scenario = await expectJson<{ title: string }>(await request.get(`${API}/scenarios/${scenarioId}`, { headers }), 200);
  await page.goto("/scenarios");
  await page.getByRole("link", { name: scenario.title }).click();
  await expect(page).toHaveURL(new RegExp(`/scenarios/${scenarioId}$`));
  const started = page.waitForResponse((r) => r.request().method() === "POST" && r.url().endsWith(`/scenarios/${scenarioId}/attempts`));
  await page.getByRole("button", { name: "Iniciar tentativa" }).click();
  const attempt = await expectJson<AttemptJson>(await started, 201);
  cleanup.attempt(request, attempt.attempt_id, headers);
  if (attempt.session_id) cleanup.session(request, attempt.session_id);
  await expect(page).toHaveURL(new RegExp(`/attempts/${attempt.attempt_id}$`));
  await expect(page.getByRole("status").filter({ hasText: "Estado:" })).toContainText("Em curso", { timeout: 180_000 });
  await expect(page.getByText(/Puxada base: [\d.,]+ whp/)).toBeVisible();
  await expect(page.getByText("baseline_pull").first()).toBeVisible();
  return expectJson<AttemptJson>(await request.get(`${API}/attempts/${attempt.attempt_id}`, { headers }), 200);
}

test.describe("os 7 cenários iniciam e rodam a puxada base", () => {
  for (const scenarioId of SCENARIOS) {
    test(scenarioId, async ({ page, request, browserName }) => {
      test.skip(browserName !== "chromium", "fluxo de referência em Chromium");
      test.setTimeout(240_000);
      const cleanup = new Cleanup();
      try {
        await ensureCapacity(request);
        const player = await createPlayer(request, `cen_${scenarioId.slice(0, 8)}_${Date.now().toString(36).slice(-4)}`);
        await usePlayer(page, player.id);
        const attempt = await startFromList(page, request, scenarioId, player.headers, cleanup);
        expect(attempt.state).toBe("in_progress");
        expect(attempt.baseline_peak_whp).toBeGreaterThan(50);

        if (scenarioId.startsWith("defect-")) {
          const select = page.getByRole("combobox", { name: "Defeito diagnosticado" });
          await expect(select).toBeVisible();
          for (const label of DEFECT_OPTIONS) await expect(select.getByRole("option", { name: label })).toHaveCount(1);
        }

        await page.getByRole("link", { name: "Abrir bancada" }).click();
        await expect(page.getByTestId("connection-state")).toHaveText("conectado", { timeout: 30_000 });
        await expect(page.getByTestId("attempt-sidebar")).toBeVisible();
      } finally {
        await cleanup.run();
      }
    });
  }
});

test("defect-lean-injector: diagnóstico do injetor entupido e acerto real aprovados", async ({ page, request, browserName }) => {
  test.skip(browserName !== "chromium", "fluxo de referência em Chromium");
  test.setTimeout(600_000);
  const cleanup = new Cleanup();
  try {
    await ensureCapacity(request);
    const player = await createPlayer(request, `diag_${Date.now().toString(36).slice(-6)}`);
    await usePlayer(page, player.id);
    const attempt = await startFromList(page, request, "defect-lean-injector", player.headers, cleanup);

    // Acerto: λ 0,80 em plena carga na calibração aplicada à sessão.
    const session = await expectJson<{ calibration_id: string }>(await request.get(`${API}/sessions/${attempt.session_id}`), 200);
    await enrichWot(request, attempt.session_id!, session.calibration_id);

    await page.getByRole("link", { name: "Abrir bancada" }).click();
    await expect(page.getByTestId("connection-state")).toHaveText("conectado", { timeout: 30_000 });
    await page.getByRole("combobox", { name: "Tipo de puxada" }).selectOption("multi_pull");
    await page.getByRole("spinbutton", { name: "Número de puxadas" }).fill("2");
    const posted = page.waitForResponse((r) => r.request().method() === "POST" && /\/sessions\/[^/]+\/runs$/.test(r.url()));
    await page.getByRole("button", { name: "Iniciar" }).click();
    const multiId = (await expectJson<{ run_id: string }>(await posted, 202)).run_id;
    // A cockpit abre com a puxada base concluída: espera a nova puxada começar e terminar.
    await expect(page.getByTestId("run-status")).toHaveText("puxada em curso", { timeout: 15_000 });
    await expect(page.getByTestId("run-status")).toHaveText("puxada concluída", { timeout: 300_000 });

    // Submissão pela página da tentativa (fora da cockpit).
    await page.goto(`/attempts/${attempt.attempt_id}`);
    await expect(page.getByRole("listitem").filter({ hasText: multiId.slice(-6) }).filter({ hasText: "válida" }).first()).toBeVisible({ timeout: 30_000 });
    await page.getByRole("combobox", { name: "Defeito diagnosticado" }).selectOption("injector_clogged");
    const submitted = page.waitForRequest((r) => r.method() === "POST" && r.url().endsWith(`/attempts/${attempt.attempt_id}/submit`));
    await page.getByRole("button", { name: "Submeter" }).click();
    const body = (await submitted).postDataJSON() as { calibration_id: string; declared_defect: string };
    expect(body).toEqual({ calibration_id: session.calibration_id, declared_defect: "injector_clogged" });

    const evaluation = await waitEvaluation(request, attempt.attempt_id, player.headers);
    expect(evaluation.passed, JSON.stringify(evaluation.results)).toBe(true);
    await page.getByRole("link", { name: "Ver resultado da última submissão" }).click();
    await expect(page.getByRole("heading", { name: /Resultado da submissão 1/ })).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText("Aprovado").first()).toBeVisible();
    await expect(page.getByText(/Defeito oculto revelado: Injetor entupido/)).toBeVisible();
  } finally {
    await cleanup.run();
  }
});
