/**
 * Tela Dividida (Live Tuning) da bancada (003 T024; RF-13, RF-14, RF-17; 002 RF-04 a RF-09).
 *
 * Teste 1 — OEM-Stage com a calibração de série (`stock-*`):
 * 1. tecla `L` ⇒ layout dividido com o editor Live Tuning;
 * 2. série: aviso "somente leitura" e `Q` não grava; "Clonar e editar" cria a cópia e aplica-a;
 * 3. Live Cell Tracing numa varredura lenta: a célula do avanço (RPM × carga %) aparece e anda
 *    (a telemetria só corre com puxada ativa); `Q` fora da VE avisa e não grava;
 * 4. `T` alterna a Visão Térmica; `L` fora do editor volta ao layout normal.
 *
 * Teste 2 — FT-Pro (swap e Base Setup por REST): a VE (RPM × MAP) abre
 * primeiro; `Q` com a grade focada durante a puxada grava a VE (PATCH) e aplica-a à sessão.
 *
 * Teste 3 — recarregar a ECU depois de "Clonar e editar".
 *
 * Testes 2 e 3 cobrem a T031: `GET /sessions/{id}` expõe `active_calibration_id` (atualizada por
 * Aplicar, swap e Base Setup); `calibration_id` continua a ser a calibração inicial.
 */
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { API, Cleanup, createSession, expectJson, openCockpit, watchConsole } from "./helpers";

test.use({ viewport: { width: 1366, height: 768 } });

const VEHICLE = "hatch-20t-gdi";
const STOCK = "stock-hatch-20t-gdi-oem-stage";

async function startSlowSweep(page: Page): Promise<string> {
  await page.getByRole("combobox", { name: "Tipo de puxada" }).selectOption("sweep_pull");
  await page.getByRole("spinbutton", { name: "Rampa" }).fill("100");
  const posted = page.waitForResponse((r) => r.request().method() === "POST" && /\/sessions\/[^/]+\/runs$/.test(r.url()));
  await page.getByRole("button", { name: "Iniciar" }).click();
  const runId = (await expectJson<{ run_id: string }>(await posted, 202)).run_id;
  await expect(page.getByTestId("run-status")).toHaveText("puxada em curso", { timeout: 15_000 });
  return runId;
}

async function abortRun(page: Page): Promise<void> {
  const abort = page.getByRole("button", { name: "Abortar" });
  if (await abort.isEnabled()) await abort.click();
  await expect(page.getByTestId("run-status")).not.toHaveText("puxada em curso", { timeout: 20_000 });
}

async function openSplit(page: Page) {
  await page.getByRole("heading", { name: "Bancada de dinamômetro" }).click();
  await page.keyboard.press("l");
  await expect(page.getByTestId("split-layout")).toBeVisible();
  await expect(page.getByRole("button", { name: "Tela Dividida (Live Tuning)" })).toHaveAttribute("aria-pressed", "true");
  const panel = page.locator("[data-live-tuning]");
  await expect(panel.getByRole("heading", { name: "Live Tuning" })).toBeVisible();
  await expect(panel.getByRole("grid")).toBeVisible({ timeout: 20_000 });
  return panel;
}

/** Sessão FT-Pro pronta: swap com snapshot e Base Setup pré-preenchido pela ficha + mapa base. */
async function standaloneSession(request: APIRequestContext, cleanup: Cleanup): Promise<string> {
  const session = await createSession(request, { vehicle_id: "classic-20t-swap", seed: 42 }, cleanup);
  const sid = session.session_id;
  await expectJson(await request.post(`${API}/sessions/${sid}/ecu/swap`, { data: { target_profile_id: "ft-pro", confirm_snapshot: true, prefill_from_hardware_sheet: true } }), 200);
  const setup = await expectJson<{ base_setup_version: number; base_setup: unknown }>(await request.get(`${API}/sessions/${sid}/ecu/base-setup`), 200);
  const saved = await expectJson<{ ecu_state: string }>(
    await request.put(`${API}/sessions/${sid}/ecu/base-setup`, {
      data: { base_version: setup.base_setup_version, base_setup: setup.base_setup, generate_base_map: true, wizard: { max_map_kpa: 290 } },
    }),
    200,
  );
  expect(saved.ecu_state).toBe("standalone_ready");
  return sid;
}

test("Live Tuning no OEM-Stage: L, série somente leitura, Clonar e editar e célula ao vivo", async ({ page, request }) => {
  test.setTimeout(180_000);
  const errors = watchConsole(page);
  const cleanup = new Cleanup();
  try {
    const session = await createSession(request, { vehicle_id: VEHICLE, profile_id: "oem-stage", calibration_id: STOCK, seed: 42 }, cleanup);
    const sid = session.session_id;
    await openCockpit(page, sid);
    const panel = await openSplit(page);

    // 2. Série: somente leitura; Q não grava; "Clonar e editar".
    const banner = panel.getByTestId("stock-banner");
    await expect(banner).toBeVisible();
    let patched = false;
    page.on("request", (r) => {
      if (r.method() === "PATCH" && r.url().includes("/tables/")) patched = true;
    });
    await panel.getByRole("grid").focus();
    await page.keyboard.press("q");
    await expect(panel.getByText(/somente leitura/).last()).toBeVisible();
    const cloned = page.waitForResponse((r) => r.request().method() === "POST" && r.url().endsWith(`${API}/calibrations`));
    const applied = page.waitForResponse((r) => r.request().method() === "POST" && r.url().endsWith(`/sessions/${sid}/calibration`));
    await banner.getByRole("button", { name: "Clonar e editar" }).click();
    const copy = await expectJson<{ calibration_id: string }>(await cloned, 201);
    expect(copy.calibration_id).not.toMatch(/^stock-/);
    expect((await applied).ok()).toBeTruthy();
    await expect(panel.getByTestId("stock-banner")).toHaveCount(0, { timeout: 20_000 });

    // 3. Célula ao vivo durante uma varredura lenta; Q fora da VE avisa.
    const label = panel.getByTestId("live-cell-label");
    await expect(label).toHaveText("Célula ao vivo: sem dados da bancada");
    await startSlowSweep(page);
    const live = panel.getByTestId("live-cell");
    await expect(live).toBeVisible({ timeout: 20_000 });
    await expect(live).toHaveAttribute("data-cell", /^\d+,\d+$/);
    await expect(label).toHaveText(/Célula ao vivo: [\d.,]+ \S+ × [\d.,]+ %/);
    const firstCell = await live.getAttribute("data-cell");
    await expect.poll(() => live.getAttribute("data-cell"), { timeout: 30_000 }).not.toBe(firstCell);
    await panel.getByRole("grid").focus();
    await page.keyboard.press("q");
    await expect(panel.getByText("Quick Tune só atua na tabela VE").last()).toBeVisible();
    expect(patched).toBe(false);
    await abortRun(page);

    // 4. T (Visão Térmica) e L fora do editor.
    await page.getByRole("heading", { name: "Bancada de dinamômetro" }).click();
    const thermal = page.getByRole("button", { name: /Visão Térmica/ });
    await expect(thermal).toHaveAttribute("aria-pressed", "false");
    await page.keyboard.press("t");
    await expect(thermal).toHaveAttribute("aria-pressed", "true");
    await page.keyboard.press("t");
    await expect(thermal).toHaveAttribute("aria-pressed", "false");
    await page.keyboard.press("l");
    await expect(page.getByTestId("split-layout")).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Dinamômetro", exact: true })).toBeVisible();
    expect(errors, errors.join("\n")).toEqual([]);
  } finally {
    await cleanup.run();
  }
});

// T031: depois do swap e do Base Setup, o Live Tuning abre `active_calibration_id` (o mapa base do
// FT-Pro), não a calibração OEM da criação (antes: 422 `CALIBRATION_PROFILE_MISMATCH`).
test("Live Tuning no FT-Pro: Quick Tune (Q) na VE durante a puxada grava e aplica", async ({ page, request }) => {
  test.setTimeout(180_000);
  const errors = watchConsole(page);
  const cleanup = new Cleanup();
  try {
    const sid = await standaloneSession(request, cleanup);
    await openCockpit(page, sid);
    await expect(page.getByTestId("profile-name")).toHaveText("FT-Pro");
    const panel = await openSplit(page);
    await expect(panel.getByTestId("stock-banner")).toHaveCount(0);
    const firstTable = panel.getByRole("group", { name: "Tabela em Live Tuning" }).getByRole("button").first();
    await expect(firstTable).toHaveAttribute("aria-pressed", "true");

    await startSlowSweep(page);
    await expect(panel.getByTestId("live-cell")).toBeVisible({ timeout: 20_000 });
    await expect(panel.getByTestId("live-cell-label")).toHaveText(/Célula ao vivo: [\d.,]+ \S+ × [\d.,]+ kPa/);

    const patch = page.waitForResponse((r) => r.request().method() === "PATCH" && r.url().includes("/tables/ve"), { timeout: 20_000 });
    const reapplied = page.waitForResponse((r) => r.request().method() === "POST" && r.url().endsWith(`/sessions/${sid}/calibration`), { timeout: 20_000 });
    await panel.getByRole("grid").focus();
    await page.keyboard.press("q");
    const patched = await patch;
    expect(patched.ok(), await patched.text()).toBeTruthy();
    const applyResponse = await reapplied;
    expect(applyResponse.ok(), await applyResponse.text()).toBeTruthy();
    await expect(panel.getByTestId("live-status")).toContainText(/aplicado rev \d+/, { timeout: 20_000 });
    const calibrationId = /\/calibrations\/([^/]+)\/tables\//.exec(patched.url())![1]!;
    const cal = await expectJson<{ version: number }>(await request.get(`${API}/calibrations/${calibrationId}`), 200);
    expect(cal.version).toBeGreaterThanOrEqual(2);
    await abortRun(page);
    expect(errors, errors.join("\n")).toEqual([]);
  } finally {
    await cleanup.run();
  }
});

// T031 (relatado na 003 T024): `POST /sessions/{id}/calibration` atualiza `active_calibration_id`;
// o workspace da ECU carrega por esse campo, e recarregar a página mantém a cópia editável.
test("ECU: depois de Clonar e editar, recarregar a página mantém a cópia aplicada", async ({ page, request }) => {
  const cleanup = new Cleanup();
  try {
    const session = await createSession(request, { vehicle_id: VEHICLE, profile_id: "oem-stage", calibration_id: STOCK, seed: 42 }, cleanup);
    await page.goto(`/sessions/${session.session_id}/ecu`);
    await expect(page.getByTestId("stock-banner")).toBeVisible({ timeout: 30_000 });
    const cloned = page.waitForResponse((r) => r.request().method() === "POST" && r.url().endsWith(`${API}/calibrations`));
    await page.getByTestId("stock-banner").getByRole("button", { name: "Clonar e editar" }).click();
    const copy = await expectJson<{ calibration_id: string }>(await cloned, 201);
    await expect(page.getByTestId("stock-banner")).toHaveCount(0, { timeout: 20_000 });
    const view = await expectJson<{ calibration_id: string; active_calibration_id: string }>(await request.get(`${API}/sessions/${session.session_id}`), 200);
    expect(view.calibration_id).toBe(STOCK);
    expect(view.active_calibration_id).toBe(copy.calibration_id);
    await page.reload();
    await expect(page.getByTestId("workspace-profile")).toHaveText("OEM-Stage", { timeout: 30_000 });
    await expect(page.getByTestId("stock-banner")).toHaveCount(0);
  } finally {
    await cleanup.run();
  }
});
