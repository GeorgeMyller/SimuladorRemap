/**
 * Acessibilidade no navegador real (T224; cockpit RNF-06, tuning RNF-06, scenarios RNF-07):
 * axe-core (`axe.min.js` injetado na página) com as regras WCAG 2.0/2.1 A e AA — incluindo
 * `color-contrast`, que no jsdom dos testes unitários fica desligada por não haver layout — e
 * 0 violações em: casca/tela inicial, cockpit, workspace da ECU (OEM e assistente standalone),
 * lista de cenários, briefing, tentativa em curso, resultado, perfis e painel do instrutor
 * (abas Desafios e Turma).
 */
import { expect, test } from "@playwright/test";

import { API, audit, Cleanup, createSession, expectJson, freeCapacity, openCockpit } from "./helpers";

// bypassCSP: o CSP de produção (script-src 'self') bloquearia o script do axe injetado pelo teste.
test.use({ viewport: { width: 1366, height: 768 }, bypassCSP: true });


test("0 violações WCAG A/AA (com contraste) nas telas de cockpit, ECU e cenários", async ({ page, request, browserName }) => {
  test.skip(browserName !== "chromium", "auditoria de referência em Chromium");
  test.setTimeout(300_000);
  const cleanup = new Cleanup();
  const found: string[] = [];
  const suffix = Date.now().toString(36).slice(-6);
  try {
    // Casca e tela inicial.
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Nova sessão" })).toBeVisible();
    await expect(page.getByRole("status")).toHaveCount(0, { timeout: 15_000 }).catch(() => undefined);
    found.push(...(await audit(page, "início")));

    // Cockpit e workspace da ECU (OEM-Stage).
    const session = await createSession(request, { vehicle_id: "hatch-20t-gdi", seed: 42 }, cleanup);
    await openCockpit(page, session.session_id);
    found.push(...(await audit(page, "cockpit")));
    await page.getByRole("tab", { name: /Datalogger/ }).click();
    found.push(...(await audit(page, "cockpit/datalogger")));
    await page.getByRole("tab", { name: /Eventos/ }).click();
    found.push(...(await audit(page, "cockpit/eventos")));
    await page.goto(`/sessions/${session.session_id}/ecu`);
    await expect(page.getByTestId("workspace-profile")).toHaveText("OEM-Stage", { timeout: 30_000 });
    found.push(...(await audit(page, "ecu")));
    await request.delete(`${API}/sessions/${session.session_id}`);

    // Assistente de configuração base (ECU standalone).
    const swapSession = await createSession(request, { vehicle_id: "classic-20t-swap", seed: 42 }, cleanup);
    await expectJson(await request.post(`${API}/sessions/${swapSession.session_id}/ecu/swap`, { data: { target_profile_id: "ft-pro", confirm_snapshot: true } }), 200);
    await page.goto(`/sessions/${swapSession.session_id}/ecu`);
    await expect(page.getByRole("region", { name: /Configuração base/ })).toBeVisible({ timeout: 30_000 });
    found.push(...(await audit(page, "ecu/assistente")));
    await request.delete(`${API}/sessions/${swapSession.session_id}`);

    // Perfis, lista e briefing.
    await page.goto("/scenarios/profiles");
    await page.getByRole("button", { name: "Novo perfil" }).click();
    found.push(...(await audit(page, "perfis/novo")));
    const dialog = page.getByRole("dialog", { name: "Novo perfil" });
    await dialog.getByLabel("Nickname").fill(`a11y_${suffix}`);
    await dialog.getByRole("radio", { name: "Instrutor" }).check();
    await dialog.getByRole("button", { name: "Criar perfil" }).click();
    await expect(page.getByRole("button", { name: new RegExp(`a11y_${suffix}.*\\(ativo\\)`) })).toBeVisible();
    found.push(...(await audit(page, "perfis")));
    const headers = { "X-Player-Profile-Id": (await page.evaluate(() => localStorage.getItem("simremap.activeProfileId")))! };

    await page.goto("/scenarios");
    await expect(page.getByRole("link", { name: /Stage 1/i }).first()).toBeVisible({ timeout: 15_000 });
    found.push(...(await audit(page, "cenários")));
    await page.goto("/scenarios/stage1-oem");
    await expect(page.getByRole("button", { name: "Iniciar tentativa" })).toBeVisible();
    found.push(...(await audit(page, "briefing")));

    // Painel do instrutor (Desafios e Turma).
    await page.goto("/scenarios/instructor");
    await expect(page.getByRole("heading", { name: "Painel do instrutor" })).toBeVisible();
    found.push(...(await audit(page, "instrutor/desafios")));
    await page.getByRole("tab", { name: "Turma" }).click();
    // Estação nova: sem tentativas importadas a tabela dá lugar ao estado vazio.
    await expect(page.getByRole("heading", { name: "Avaliação da turma" }).or(page.getByText("Ainda sem tentativas importadas."))).toBeVisible();
    found.push(...(await audit(page, "instrutor/turma")));

    // Tentativa em curso, bancada com o painel da tentativa e resultado (submissão sem puxadas).
    let started = await request.post(`${API}/scenarios/stage1-oem/attempts`, { headers });
    if (await freeCapacity(request, started)) started = await request.post(`${API}/scenarios/stage1-oem/attempts`, { headers });
    const attempt = await expectJson<{ attempt_id: string; session_id: string | null; calibration_id: string }>(started, 201);
    cleanup.attempt(request, attempt.attempt_id, headers);
    if (attempt.session_id) cleanup.session(request, attempt.session_id);
    await page.goto(`/attempts/${attempt.attempt_id}`);
    await expect(page.getByRole("status").filter({ hasText: "Estado:" })).toContainText("Em curso", { timeout: 180_000 });
    found.push(...(await audit(page, "tentativa")));
    await page.getByRole("link", { name: "Abrir bancada" }).click();
    await expect(page.getByTestId("attempt-sidebar")).toBeVisible({ timeout: 30_000 });
    found.push(...(await audit(page, "cockpit/tentativa")));
    await expectJson(await request.post(`${API}/attempts/${attempt.attempt_id}/submit`, { headers, data: { calibration_id: attempt.calibration_id } }), 202);
    await page.goto(`/attempts/${attempt.attempt_id}/result`);
    await expect(page.getByRole("heading", { name: /Resultado da submissão 1/ })).toBeVisible({ timeout: 60_000 });
    found.push(...(await audit(page, "resultado")));
  } finally {
    await cleanup.run();
  }
  test.info().annotations.push({ type: "axe", description: `${found.length} violações` });
  expect(found, found.join("\n")).toEqual([]);
});
