/**
 * Controles da bancada no navegador (003 T024; RF-13, RF-17; cockpit RF-12, RF-13, RF-22).
 *
 * 1. `?` abre "Atalhos de teclado" (lista W/S, Espaço, T e L); `Esc` fecha;
 * 2. borboleta: `W` +5 %, `Shift+W` +1 %, `S` −5 %; segurar Espaço sobe o pedal e soltar volta a 0;
 * 3. abas 1–4, `U` (unidades) e `D` (diagnóstico);
 * 4. "Carga estacionária" a 3500 rpm com o pedal escolhido termina sem falha;
 * 5. "Múltiplas puxadas" (2) termina com as duas puxadas no resumo da API.
 */
import { expect, test } from "@playwright/test";

import { Cleanup, createSession, openCockpit, waitRun, watchConsole, expectJson } from "./helpers";

test.use({ viewport: { width: 1366, height: 768 } });

test("bancada: atalhos, borboleta W/S/Espaço, carga estacionária e múltiplas puxadas", async ({ page, request }) => {
  test.setTimeout(300_000);
  const errors = watchConsole(page);
  const cleanup = new Cleanup();
  try {
    const session = await createSession(request, { vehicle_id: "hatch-20t-gdi", profile_id: "oem-stage", seed: 42 }, cleanup);
    await openCockpit(page, session.session_id);
    const title = page.getByRole("heading", { name: "Bancada de dinamômetro" });

    // 1. Atalhos.
    await title.click();
    await page.keyboard.press("?");
    const dialog = page.getByRole("dialog", { name: "Atalhos de teclado" });
    await expect(dialog).toBeVisible();
    for (const key of ["W / S", "Espaço (segurar)", "T", "L", "M", "U", "D"]) await expect(dialog.getByRole("cell", { name: key, exact: true })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);

    // 2. Borboleta pelo teclado (fora de campos de texto).
    const throttle = page.getByRole("slider", { name: "Borboleta" });
    await expect(throttle).toHaveValue("0");
    await title.click();
    await page.keyboard.press("w");
    await page.keyboard.press("w");
    await expect(throttle).toHaveValue("10");
    await page.keyboard.press("Shift+W");
    await expect(throttle).toHaveValue("11");
    await page.keyboard.press("s");
    await expect(throttle).toHaveValue("6");
    await page.keyboard.down("Space");
    await expect.poll(async () => Number(await throttle.inputValue()), { timeout: 5_000 }).toBeGreaterThan(40);
    await expect(throttle).toHaveAttribute("data-holding", "true");
    await page.keyboard.up("Space");
    await expect(throttle).toHaveValue("0");
    await expect(page.locator("main")).toHaveJSProperty("scrollTop", 0);

    // 3. Abas, unidades e diagnóstico.
    await page.keyboard.press("3");
    await expect(page.getByRole("tab", { name: /Eventos/ })).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("1");
    await expect(page.getByRole("tab", { name: /Espectrograma/ })).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("u");
    await expect(page.getByRole("button", { name: /Unidades:/ })).toHaveAttribute("aria-expanded", "true");
    await page.keyboard.press("Escape");
    await title.click();
    await page.keyboard.press("d");
    await expect(page.getByText(/FPS/).first()).toBeVisible();
    await page.keyboard.press("d");

    // 4. Carga estacionária com 60 % de pedal.
    for (let i = 0; i < 12; i++) await page.keyboard.press("w");
    await expect(throttle).toHaveValue("60");
    await page.getByRole("combobox", { name: "Tipo de puxada" }).selectOption("steady_state_hold");
    await page.getByRole("spinbutton", { name: "RPM alvo" }).fill("3500");
    const posted = page.waitForRequest((r) => r.method() === "POST" && /\/sessions\/[^/]+\/runs$/.test(r.url()));
    const accepted = page.waitForResponse((r) => r.request().method() === "POST" && /\/sessions\/[^/]+\/runs$/.test(r.url()));
    await page.getByRole("button", { name: "Iniciar" }).click();
    const body = (await posted).postDataJSON() as { run_type: string; cells: { rpm: number; pedal_pct: number; hold_s: number }[] };
    expect(body.run_type).toBe("steady_state_hold");
    expect(body.cells).toEqual([{ rpm: 3500, pedal_pct: 60, hold_s: 5 }]);
    const holdId = (await expectJson<{ run_id: string }>(await accepted, 202)).run_id;
    await expect(page.getByTestId("run-status")).toHaveText("puxada em curso", { timeout: 15_000 });
    await expect(throttle).toBeDisabled();
    await expect(page.getByTestId("run-status")).not.toHaveText("puxada em curso", { timeout: 120_000 });
    const hold = await waitRun(request, holdId);
    expect(hold.state).toBe("completed");

    // 5. Múltiplas puxadas (2).
    await page.getByRole("combobox", { name: "Tipo de puxada" }).selectOption("multi_pull");
    await page.getByRole("spinbutton", { name: "Número de puxadas" }).fill("2");
    const multiPosted = page.waitForResponse((r) => r.request().method() === "POST" && /\/sessions\/[^/]+\/runs$/.test(r.url()));
    await page.getByRole("button", { name: "Iniciar" }).click();
    const multiId = (await expectJson<{ run_id: string }>(await multiPosted, 202)).run_id;
    await expect(page.getByTestId("run-status")).toHaveText("puxada em curso", { timeout: 15_000 });
    await expect(page.getByTestId("run-status")).toHaveText("puxada concluída", { timeout: 240_000 });
    const multi = await waitRun(request, multiId);
    expect(multi.state).toBe("completed");
    expect(multi.pulls?.length ?? 0).toBe(2);
    expect(errors, errors.join("\n")).toEqual([]);
  } finally {
    await cleanup.run();
  }
});
