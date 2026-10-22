/**
 * Jornada do Prof. Marcos no navegador (T223; req RF-42; training-scenarios RF-05, RF-18 a RF-26;
 * telemetry-datalogger RF-17, RF-19).
 *
 * Duas estações: a do instrutor (`baseURL`) e a do aluno (`SIMREMAP_E2E_STUDENT_URL`, outro
 * servidor com banco próprio; `scripts/e2e_local.sh` sobe as duas). Sem a variável o teste salta:
 * importar a tentativa na própria estação que a gerou não representa a jornada.
 * 1. Instrutor (UI): perfil «Instrutor», cria `challenge-400whp-e27` no painel e exporta o pacote
 *    (download do `.simremap.json`).
 * 2. Estação do aluno: o pacote do desafio é importado por REST (a UI do aluno não tem ecrã de
 *    importação; a fila de importação fica no painel do instrutor e exige papel «Instrutor»).
 * 3. Aluno (UI): perfil «Aluno», briefing → "Iniciar tentativa" (puxada base automática) → bancada
 *    com o painel da tentativa → `multi_pull` de 3 → "Submeter" → resultado → "Exportar pacote".
 * 4. Instrutor (UI): aba Turma → importa o pacote da tentativa pela fila → a avaliação recalculada
 *    tem o mesmo `evaluation_sha256` → "Exportar CSV" (pt-BR, `;`) com a linha do aluno.
 * 5. Logs antes/depois (REST): o log da puxada base e o da `multi_pull` exportados da estação do
 *    aluno, importados na do instrutor (E-28) e comparados por bins de RPM (E-29).
 */
import { readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";

import { expect, request as playwrightRequest, test, type APIRequestContext, type Download, type Page } from "@playwright/test";

import { API, Cleanup, expectJson, freeCapacity, type Json } from "./helpers";

const CHALLENGE = "challenge-400whp-e27";
const STUDENT_URL = process.env.SIMREMAP_E2E_STUDENT_URL ?? null;
const VIEWPORT = { width: 1366, height: 768 };

test.use({ viewport: VIEWPORT });

async function text(download: Download): Promise<string> {
  const path = await download.path();
  return readFileSync(path, "utf8");
}

interface Evaluation {
  status: string;
  passed: boolean | null;
  evaluation_sha256: string | null;
  results: { criterion_id: string; passed: boolean; mandatory: boolean; measured: number | null }[];
}

interface Attempt {
  attempt_id: string;
  session_id: string | null;
  state: string;
  baseline_run_id: string | null;
  runs: { run_id: string; valid: boolean; run_type: string }[];
}

async function profileId(page: Page): Promise<string> {
  const id = await page.evaluate(() => localStorage.getItem("simremap.activeProfileId"));
  expect(id).toBeTruthy();
  return id!;
}

test("Prof. Marcos: desafio exportado, tentativa do aluno importada e avaliação objetiva da turma", async ({ page, request, browser, browserName }) => {
  test.skip(browserName !== "chromium", "jornada de referência em Chromium");
  test.skip(!STUDENT_URL, "defina SIMREMAP_E2E_STUDENT_URL (estação do aluno com banco próprio)");
  test.setTimeout(600_000);
  const suffix = Date.now().toString(36).slice(-6);
  const cleanup = new Cleanup();
  const studentRequest: APIRequestContext = await playwrightRequest.newContext({ baseURL: STUDENT_URL! });
  const studentContext = await browser.newContext({ baseURL: STUDENT_URL!, viewport: VIEWPORT, locale: "pt-BR", acceptDownloads: true });
  const student = await studentContext.newPage();
  try {
    // 1. Instrutor: perfil, desafio e export.
    await page.goto("/scenarios/profiles");
    await page.getByRole("button", { name: "Novo perfil" }).click();
    const dialog = page.getByRole("dialog", { name: "Novo perfil" });
    await dialog.getByLabel("Nickname").fill(`prof_marcos_${suffix}`);
    await dialog.getByRole("radio", { name: "Instrutor" }).check();
    await dialog.getByRole("button", { name: "Criar perfil" }).click();
    await expect(page.getByRole("button", { name: new RegExp(`prof_marcos_${suffix}.*Instrutor.*\\(ativo\\)`) })).toBeVisible();
    const instructorHeaders = { "X-Player-Profile-Id": await profileId(page) };

    await page.goto("/scenarios/instructor");
    await expect(page.getByRole("heading", { name: "Painel do instrutor" })).toBeVisible();
    const exists = (await request.get(`${API}/scenarios/${CHALLENGE}`)).status() === 200;
    const form = page.getByRole("form", { name: "Novo desafio" });
    await expect(form.getByLabel("Identificador (slug)")).toHaveValue(CHALLENGE);
    if (!exists) {
      await form.getByRole("button", { name: "Criar desafio" }).click();
      await expect(form.getByRole("status")).toContainText(`Desafio ${CHALLENGE} criado.`);
    }
    const challenge = await expectJson<Json & { criteria: { criteria: { criterion_id: string }[] } }>(await request.get(`${API}/scenarios/${CHALLENGE}`), 200);
    expect(challenge.vehicle_id).toBe("coupe-30t-i6");
    const exportBtn = page.getByRole("button", { name: `Exportar desafio ${CHALLENGE}` });
    const challengeDownload = page.waitForEvent("download");
    await exportBtn.click();
    const challengeFile = await challengeDownload;
    expect(challengeFile.suggestedFilename()).toMatch(/\.simremap\.json$/);
    const challengePackage = await text(challengeFile);
    expect((JSON.parse(challengePackage) as { kind: string }).kind).toBe("challenge");

    // 3a. Aluno: perfil na estação do aluno.
    await student.goto("/scenarios/profiles");
    await student.getByRole("button", { name: "Novo perfil" }).click();
    const sDialog = student.getByRole("dialog", { name: "Novo perfil" });
    await sDialog.getByLabel("Nickname").fill(`aluno_${suffix}`);
    await sDialog.getByRole("button", { name: "Criar perfil" }).click();
    await expect(student.getByRole("button", { name: new RegExp(`aluno_${suffix}.*Aluno.*\\(ativo\\)`) })).toBeVisible();
    const studentHeaders = { "X-Player-Profile-Id": await profileId(student) };

    // 2. Pacote do desafio importado na estação do aluno (REST).
    const imported = await studentRequest.post(`${API}/packages/import`, {
      headers: { ...studentHeaders, "Content-Type": "application/json" },
      data: challengePackage,
    });
    expect([200, 201], await imported.text()).toContain(imported.status());

    // 3b. Briefing e início da tentativa (UI).
    await student.goto("/scenarios");
    await student.getByRole("link", { name: String(challenge.title) }).click();
    await expect(student.getByText("Critérios, limiares e unidades")).toBeVisible();
    const started = student.waitForResponse((r) => r.request().method() === "POST" && r.url().endsWith(`/scenarios/${CHALLENGE}/attempts`));
    await student.getByRole("button", { name: "Iniciar tentativa" }).click();
    let startResponse = await started;
    if (await freeCapacity(studentRequest, startResponse)) {
      const retry = student.waitForResponse((r) => r.request().method() === "POST" && r.url().endsWith(`/scenarios/${CHALLENGE}/attempts`));
      await student.getByRole("button", { name: "Iniciar tentativa" }).click();
      startResponse = await retry;
    }
    const attempt0 = await expectJson<Attempt>(startResponse, 201);
    cleanup.attempt(studentRequest, attempt0.attempt_id, studentHeaders);
    if (attempt0.session_id) cleanup.session(studentRequest, attempt0.session_id);
    await expect(student).toHaveURL(new RegExp(`/attempts/${attempt0.attempt_id}$`));
    await expect(student.getByRole("status").filter({ hasText: "Estado:" })).toContainText("Em curso", { timeout: 180_000 });
    const attempt1 = await expectJson<Attempt>(await studentRequest.get(`${API}/attempts/${attempt0.attempt_id}`, { headers: studentHeaders }), 200);
    if (attempt1.session_id) cleanup.session(studentRequest, attempt1.session_id);

    // 3c. Bancada com o painel da tentativa e multi_pull de 3.
    await student.getByRole("link", { name: "Abrir bancada" }).click();
    await expect(student.getByTestId("connection-state")).toHaveText("conectado", { timeout: 30_000 });
    await expect(student.getByTestId("attempt-sidebar")).toBeVisible();
    await student.getByRole("combobox", { name: "Tipo de puxada" }).selectOption("multi_pull");
    await student.getByRole("spinbutton", { name: "Número de puxadas" }).fill("3");
    const posted = student.waitForResponse((r) => r.request().method() === "POST" && /\/sessions\/[^/]+\/runs$/.test(r.url()));
    await student.getByRole("button", { name: "Iniciar" }).click();
    const multiId = (await expectJson<{ run_id: string }>(await posted, 202)).run_id;
    await expect(student.getByTestId("run-status")).toHaveText("puxada concluída", { timeout: 300_000 });
    const sidebar = student.getByTestId("attempt-sidebar");
    await expect(sidebar.getByText("válida").first()).toBeVisible({ timeout: 20_000 });

    // Submissão e resultado.
    await sidebar.getByRole("button", { name: "Submeter" }).click();
    const resultLink = sidebar.getByRole("link", { name: "Ver resultado da última submissão" });
    await expect(resultLink).toBeVisible({ timeout: 120_000 });
    await resultLink.click();
    await expect(student.getByRole("heading", { name: /Resultado da submissão 1/ })).toBeVisible({ timeout: 60_000 });
    const evaluation = await expectJson<Evaluation>(
      await studentRequest.get(`${API}/attempts/${attempt0.attempt_id}/evaluation`, { headers: studentHeaders }),
      200,
    );
    expect(evaluation.status).toBe("completed");
    expect(evaluation.evaluation_sha256).toMatch(/^[0-9a-f]{64}$/);
    // Aprova só se todos os critérios obrigatórios aprovam (a pontuação não decide).
    expect(evaluation.passed).toBe(evaluation.results.filter((r) => r.mandatory).every((r) => r.passed));
    await expect(student.getByText(/Pontuação total:/)).toBeVisible();
    const attemptDownload = student.waitForEvent("download");
    await student.getByRole("button", { name: "Exportar pacote" }).click();
    const attemptFile = await attemptDownload;
    const attemptPackage = await text(attemptFile);
    expect((JSON.parse(attemptPackage) as { kind: string }).kind).toBe("attempt");

    // 4. Instrutor: importa a tentativa pela fila e exporta o CSV de notas.
    await page.goto("/scenarios/instructor");
    await page.getByRole("tab", { name: "Turma" }).click();
    const importedResponse = page.waitForResponse((r) => r.request().method() === "POST" && r.url().endsWith("/packages/import"));
    await page.getByLabel("Ficheiros de pacote").setInputFiles({
      name: attemptFile.suggestedFilename(),
      mimeType: "application/json",
      buffer: Buffer.from(attemptPackage, "utf8"),
    });
    const importResult = await expectJson<{ evaluation_mismatch: boolean; recomputed_evaluation: Evaluation | null; attempt_id: string }>(
      await importedResponse,
      201,
    );
    const queue = page.getByRole("list", { name: "Estado por ficheiro" });
    await expect(queue.getByRole("listitem").first()).toContainText("Importado");
    await expect(queue.getByText("avaliação recalculada")).toHaveCount(0);
    expect(importResult.evaluation_mismatch).toBe(false);
    expect(importResult.recomputed_evaluation!.evaluation_sha256).toBe(evaluation.evaluation_sha256);
    const listed = await expectJson<{ items: { attempt_id: string; last_evaluation?: { evaluation_sha256: string } | null }[] }>(
      await request.get(`${API}/attempts?origin=imported`, { headers: instructorHeaders }),
      200,
    );
    expect(listed.items.map((a) => a.attempt_id)).toContain(attempt0.attempt_id);

    const grades = page.getByRole("table");
    await expect(grades.getByRole("row").filter({ hasText: `aluno_${suffix}` })).toBeVisible({ timeout: 20_000 });
    await page.getByRole("combobox", { name: /^Cenário/ }).selectOption(CHALLENGE);
    const csvDownload = page.waitForEvent("download");
    await page.getByRole("button", { name: "Exportar CSV", exact: true }).click();
    const csvFile = await csvDownload;
    expect(csvFile.suggestedFilename()).toBe(`notas-${CHALLENGE}.csv`);
    const csv = (await text(csvFile)).split(/\r?\n/).filter(Boolean);
    const header = csv[0]!.split(";");
    expect(header.slice(0, 3)).toEqual(["nickname", "station", "scenario_id"]);
    for (const c of challenge.criteria.criteria) expect(header.join(";")).toContain(c.criterion_id);
    const row = csv.find((l) => l.startsWith(`aluno_${suffix};`));
    expect(row, csv.join("\n")).toBeTruthy();
    const cells = row!.split(";");
    expect(cells[header.indexOf("scenario_id")]).toBe(CHALLENGE);
    expect(cells[header.indexOf("attempt_id")]).toBe(attempt0.attempt_id);
    const score = cells[header.indexOf("total_score")]!;
    expect(score).not.toContain("."); // vírgula decimal no dialeto pt-BR

    // 5. Logs antes/depois: export (E-27) da estação do aluno, comparação por bins de RPM (E-29)
    // e import (E-28) na estação do instructor. O E-28 aceita até 64 MiB descomprimidos: o log
    // JSON de uma multi_pull de 3 a 1 kHz passa disso, e então só a comparação local é possível.
    const baselineRun = attempt1.baseline_run_id!;
    const logSizes: Record<string, number> = {};
    const logIds: string[] = [];
    for (const runId of [baselineRun, multiId]) {
      const exported = await studentRequest.get(`${API}/runs/${runId}/log`);
      expect(exported.status()).toBe(200);
      const body = await exported.body();
      logSizes[runId] = body.length;
      const imported = await request.post(`${API}/logs/import`, {
        headers: { "Content-Type": "application/json", "Content-Encoding": "gzip" },
        data: gzipSync(body),
      });
      if (imported.status() === 409) logIds.push(((await imported.json()) as { log_id: string }).log_id);
      else if (imported.status() === 201) {
        const summary = (await imported.json()) as { log_id: string; sha256: string };
        expect(summary.sha256).toBe(exported.headers()["x-log-sha256"]);
        logIds.push(summary.log_id);
      } else expect(((await imported.json()) as { code: string }).code).toBe("PAYLOAD_TOO_LARGE");
    }
    const local = await expectJson<{ bins: unknown[] }>(
      await studentRequest.post(`${API}/logs/compare`, { data: { a: { run_id: baselineRun }, b: { run_id: multiId } } }),
      200,
    );
    expect(local.bins.length).toBeGreaterThan(0);
    let remoteBins: number | null = null;
    if (logIds.length === 2) {
      const remote = await expectJson<{ bins: unknown[] }>(
        await request.post(`${API}/logs/compare`, { data: { a: { log_id: logIds[0] }, b: { log_id: logIds[1] } } }),
        200,
      );
      expect(remote.bins).toEqual(local.bins);
      remoteBins = remote.bins.length;
    }
    const comparison = local;
    test.info().annotations.push({
      type: "marcos",
      description: JSON.stringify({
        passed: evaluation.passed,
        evaluation_sha256: evaluation.evaluation_sha256,
        results: evaluation.results.map((r) => [r.criterion_id, r.measured, r.passed]),
        compare_bins: comparison.bins.length,
        instructor_compare_bins: remoteBins,
        imported_logs: logIds.length,
        log_bytes: logSizes,
      }),
    });
  } finally {
    await cleanup.run();
    await studentContext.close();
    await studentRequest.dispose();
  }
});
