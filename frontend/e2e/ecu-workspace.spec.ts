/**
 * Workspace da ECU no navegador (003 T024; RF-14, RF-17; tuning RF-03 a RF-12).
 *
 * Sessão livre OEM-Stage (nasce com a cópia do usuário, editável):
 * 1. "Avanço base" abre a grade; "Vista 3D" mostra a superfície ao lado (1366 px); `F3` alterna-a;
 * 2. bloco selecionado na grade: `H`, `V` e `B` editam e gravam (PATCH da tabela);
 * 3. "Salvar versão" com nome grava nova revisão (PUT);
 * 4. "Aplicar à sessão" com confirmação aplica a revisão (`POST .../calibration`).
 */
import { expect, test } from "@playwright/test";

import { API, Cleanup, createSession, expectJson, watchConsole } from "./helpers";

test.use({ viewport: { width: 1366, height: 768 } });

test("ECU: 2D/3D, H/V/B, salvar versão e aplicar na sessão", async ({ page, request }) => {
  test.setTimeout(120_000);
  const errors = watchConsole(page);
  const cleanup = new Cleanup();
  try {
    const session = await createSession(request, { vehicle_id: "hatch-20t-gdi", profile_id: "oem-stage", seed: 42 }, cleanup);
    const sid = session.session_id;
    await page.goto(`/sessions/${sid}/ecu`);
    await expect(page.getByTestId("workspace-profile")).toHaveText("OEM-Stage", { timeout: 30_000 });
    await expect(page.getByTestId("stock-banner")).toHaveCount(0);

    // 1. Grade + vista 3D; F3 alterna a vista.
    await page.getByRole("button", { name: "Avanço base", exact: true }).click();
    const editor = page.getByRole("main", { name: "Editor" });
    const grid = editor.getByRole("grid");
    await expect(grid).toBeVisible();
    const view3d = editor.getByRole("figure", { name: /Vista 3D de/ });
    await expect(view3d).toHaveCount(0);
    await editor.getByRole("button", { name: "Vista 3D" }).click();
    await expect(view3d).toBeVisible();
    await grid.focus();
    await page.keyboard.press("F3");
    await expect(view3d).toHaveCount(0);
    await page.keyboard.press("F3");
    await expect(view3d).toBeVisible();

    // 2. Bloco 4×4 e operações H, V e B.
    const revision = page.getByTestId("revision");
    const startRevision = Number(await revision.textContent());
    const cells = grid.getByRole("gridcell");
    await cells.nth(2 * 16 + 2).click();
    await cells.nth(5 * 16 + 5).click({ modifiers: ["Shift"] });
    let patches = 0;
    page.on("response", (r) => {
      if (r.request().method() === "PATCH" && r.url().includes("/tables/ignition_base") && r.ok()) patches += 1;
    });
    for (const key of ["h", "v", "b"]) {
      await grid.focus();
      await page.keyboard.press(key);
    }
    await expect.poll(() => patches, { timeout: 15_000 }).toBeGreaterThan(0);
    await expect(page.getByTestId("save-state")).toContainText("gravado", { timeout: 15_000 });
    await expect.poll(async () => Number(await revision.textContent())).toBeGreaterThan(startRevision);

    // 3. Salvar versão com nome.
    const before = Number(await revision.textContent());
    await page.getByLabel("Nome da versão").fill("QF 003 bloco suavizado");
    const put = page.waitForResponse((r) => r.request().method() === "PUT" && /\/calibrations\/[^/]+$/.test(r.url()));
    await page.getByRole("button", { name: "Salvar versão" }).click();
    const saved = await expectJson<{ calibration_id: string; version: number; metadata: { change_summary?: string } }>(await put, 200);
    expect(saved.version).toBeGreaterThan(before);
    await expect(revision).toHaveText(String(saved.version));

    // 4. Aplicar à sessão (confirmação fora da puxada).
    await page.getByRole("button", { name: "Aplicar à sessão" }).click();
    const dialog = page.getByRole("dialog", { name: "Aplicar à sessão" });
    await expect(dialog).toBeVisible();
    const applied = page.waitForResponse((r) => r.request().method() === "POST" && r.url().endsWith(`/sessions/${sid}/calibration`));
    await dialog.getByRole("button", { name: "Confirmar" }).click();
    const body = await expectJson<{ calibration_id: string; version: number }>(await applied, 200);
    expect(body).toMatchObject({ calibration_id: saved.calibration_id, version: saved.version });
    await expect(page.getByTestId("applied")).toHaveText(`revisão ${saved.version} aplicada à sessão`);
    const cal = await expectJson<{ version: number }>(await request.get(`${API}/calibrations/${saved.calibration_id}`), 200);
    expect(cal.version).toBe(saved.version);
    expect(errors, errors.join("\n")).toEqual([]);
  } finally {
    await cleanup.run();
  }
});
