/**
 * Tela inicial: Stage Builder, Flex Fuel e ciclo de vida da sessão livre (003 T024; RF-12, RF-17;
 * 002 RF-13, RF-18, RF-19).
 *
 * 1. `muscle-v8-sc` (compressor): turbinas desabilitadas com o motivo; Flex indisponível (sem E100);
 * 2. `classic-20t-swap` (E100 e E27): 6 categorias; turbina + bicos + Flex E50 pelo teclado; o
 *    `POST /sessions` leva `upgrades` e `ethanol_pct` e a bancada abre com a sessão criada;
 * 3. retomada: a tela inicial mostra a sessão ativa e "continuar na bancada" volta à cockpit;
 * 4. nova sessão com outra ativa ⇒ 409 `SIM_CAPACITY_EXCEEDED` com "Retomar" e "Encerrar";
 *    "Encerrar sessão ativa" fecha-a no servidor (`DELETE`) e a criação seguinte passa.
 */
import { expect, test, type Page } from "@playwright/test";

import { API, Cleanup, expectJson, freeCapacity, watchConsole } from "./helpers";

test.use({ viewport: { width: 1366, height: 768 } });

const CATEGORIES = ["Turbina", "Bicos injetores", "Bomba de combustível", "Intercooler", "Downpipe", "Internos do motor"];

async function chooseCar(page: Page, name: RegExp): Promise<void> {
  await page.getByRole("radio", { name }).check();
  await expect(page.getByRole("status", { name: "A carregar a oficina" })).toHaveCount(0, { timeout: 15_000 });
}

test("Stage Builder: incompatibilidades, Flex E50 e criação da sessão com peças", async ({ page, request }) => {
  test.setTimeout(120_000);
  const errors = watchConsole(page);
  const cleanup = new Cleanup();
  try {
    // Estação dedicada: liberta uma sessão ativa deixada por outro spec.
    const probe = await request.post(`${API}/sessions`, { data: { vehicle_id: "hatch-20t-gdi" } });
    if (!(await freeCapacity(request, probe)) && probe.status() === 201) {
      await request.delete(`${API}/sessions/${((await probe.json()) as { session_id: string }).session_id}`);
    }

    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Nova sessão" })).toBeVisible();
    const builder = page.getByRole("region", { name: "Oficina: peças e combustível" });

    // 1. Compressor: turbinas fora; Flex indisponível.
    await chooseCar(page, /Muscle V8/);
    for (const category of CATEGORIES) await expect(builder.getByRole("group", { name: category })).toBeVisible();
    const turbo = builder.getByRole("group", { name: "Turbina" });
    await expect(turbo.locator('input[value="stock"]')).toBeEnabled();
    const turboUpgrades = turbo.locator('input[type="radio"]:not([value="stock"])');
    expect(await turboUpgrades.count()).toBeGreaterThan(0);
    for (const radio of await turboUpgrades.all()) await expect(radio).toBeDisabled();
    await expect(turbo.getByText("Só para motor turbo.").first()).toBeVisible();
    // As outras categorias continuam livres no V8.
    await expect(builder.getByRole("group", { name: "Internos do motor" }).locator('input[value="forged"]')).toBeEnabled();
    await expect(builder.getByText(/Flex Fuel indisponível/)).toBeVisible();

    // 2. Clássico com swap: Flex disponível.
    await chooseCar(page, /Clássico 2\.0 turbo/);
    const flex = builder.getByRole("checkbox", { name: "Flex Fuel" });
    await expect(flex).toBeVisible();
    await flex.check();
    const slider = builder.getByRole("slider", { name: "Teor de etanol" });
    await expect(slider).toHaveValue("85");
    await slider.focus();
    for (let i = 0; i < 35; i++) await page.keyboard.press("ArrowLeft");
    await expect(slider).toHaveValue("50");
    await expect(builder.getByText("E50 (50 %)")).toBeVisible();

    const turboGroup = builder.getByRole("group", { name: "Turbina" });
    const turboPart = turboGroup.locator('input[type="radio"]:not([value="stock"])').first();
    await turboPart.check();
    const turboId = await turboPart.getAttribute("value");
    const injPart = builder.getByRole("group", { name: "Bicos injetores" }).locator('input[type="radio"]:not([value="stock"])').first();
    await injPart.check();
    const injId = await injPart.getAttribute("value");

    const posted = page.waitForRequest((r) => r.method() === "POST" && r.url().endsWith(`${API}/sessions`));
    const created = page.waitForResponse((r) => r.request().method() === "POST" && r.url().endsWith(`${API}/sessions`));
    await page.getByRole("button", { name: "Criar sessão" }).click();
    const body = (await posted).postDataJSON() as { vehicle_id: string; upgrades?: Record<string, string>; ethanol_pct?: number };
    expect(body.vehicle_id).toBe("classic-20t-swap");
    expect(body.ethanol_pct).toBe(50);
    expect(body.upgrades).toEqual({ turbo: turboId, injectors: injId });
    const session = await expectJson<{ session_id: string; upgrades?: Record<string, string>; ethanol_pct?: number | null; fuel_id: string }>(await created, 201);
    cleanup.session(request, session.session_id);
    expect(session.ethanol_pct).toBe(50);

    await expect(page).toHaveURL(new RegExp(`/sessions/${session.session_id}/dyno$`));
    await expect(page.getByTestId("vehicle-name")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("connection-state")).toHaveText("conectado", { timeout: 20_000 });

    // 3. Retomada pela tela inicial.
    await page.goto("/");
    await expect(page.getByText(`Sessão ativa ${session.session_id.slice(0, 8)}`)).toBeVisible();
    await page.getByRole("link", { name: "continuar na bancada" }).click();
    await expect(page).toHaveURL(new RegExp(`/sessions/${session.session_id}/dyno$`));
    await expect(page.getByTestId("vehicle-name")).toBeVisible({ timeout: 30_000 });

    // 4. Segunda sessão ⇒ 409; "Encerrar sessão ativa" e nova criação.
    await page.goto("/");
    await chooseCar(page, /Hatch 2\.0 turbo/);
    const conflict = page.waitForResponse((r) => r.request().method() === "POST" && r.url().endsWith(`${API}/sessions`));
    await page.getByRole("button", { name: "Criar sessão" }).click();
    expect((await conflict).status()).toBe(409);
    const alert = page.getByRole("alert").filter({ hasText: "SIM_CAPACITY_EXCEEDED" });
    await expect(alert).toBeVisible();
    await expect(alert.getByRole("link", { name: "Retomar sessão ativa" })).toHaveAttribute("href", `/sessions/${session.session_id}/dyno`);
    const closed = page.waitForResponse((r) => r.request().method() === "DELETE" && r.url().endsWith(`/sessions/${session.session_id}`));
    await alert.getByRole("button", { name: "Encerrar sessão ativa" }).click();
    expect((await closed).ok()).toBeTruthy();
    await expect(alert).toHaveCount(0);
    await expect(page.getByText("Nenhuma sessão ativa.")).toBeVisible();

    const again = page.waitForResponse((r) => r.request().method() === "POST" && r.url().endsWith(`${API}/sessions`));
    await page.getByRole("button", { name: "Criar sessão" }).click();
    const second = await expectJson<{ session_id: string }>(await again, 201);
    cleanup.session(request, second.session_id);
    await expect(page).toHaveURL(new RegExp(`/sessions/${second.session_id}/dyno$`));
    await expect(page.getByTestId("vehicle-name")).toBeVisible({ timeout: 30_000 });
    expect(errors, errors.join("\n")).toEqual([]);
  } finally {
    await cleanup.run();
  }
});

test("sessão guardada que já não existe: a bancada mostra o erro e volta ao início sem a sessão", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("simremap.activeSessionId", "0123456789abcdef0123456789abcdef"));
  await page.goto("/");
  await expect(page.getByText("Sessão ativa 01234567")).toBeVisible();
  await page.getByRole("link", { name: "continuar na bancada" }).click();
  const alert = page.getByRole("alert").filter({ hasText: /SESSION_NOT_FOUND/ });
  await expect(alert).toBeVisible({ timeout: 20_000 });
  await alert.getByRole("link").first().click();
  await expect(page.getByText("Nenhuma sessão ativa.")).toBeVisible();
});
