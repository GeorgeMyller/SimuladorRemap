/** Fumo do SPA servido pelo container (platform-foundation RF-15, 6.2 passos 7–8). */
import { expect, test } from "@playwright/test";

test("a casca carrega com a versão da API e cabeçalhos de segurança", async ({ page, request }) => {
  const version = await request.get("/api/v1/version");
  expect(version.ok()).toBeTruthy();
  const body = (await version.json()) as { api_version: string; app_version: string };
  expect(body.api_version).toBe("v1");

  const response = await page.goto("/");
  expect(response?.headers()["x-frame-options"]).toBe("DENY");
  await expect(page.getByText("SimuladorRemap").first()).toBeVisible();
  await expect(page.getByText(`v${body.app_version}`)).toBeVisible();
  await expect(page.getByText("Servidor indisponível")).toHaveCount(0);
});

test("rota do SPA cai no index.html e API inexistente responde problem+json", async ({
  page,
  request,
}) => {
  const spa = await page.goto("/sessions/qualquer/dyno");
  expect(spa?.status()).toBe(200);
  const missing = await request.get("/api/v1/inexistente");
  expect(missing.status()).toBe(404);
  expect(missing.headers()["content-type"]).toContain("application/problem+json");
  const problem = (await missing.json()) as { code: string };
  expect(problem.code).toBe("ROUTE_NOT_FOUND");
});
