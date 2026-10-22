/**
 * Motor de simulação com a extensão Rust (`simremap_rs`, 003 T024; RF-01 a RF-06, RF-17).
 *
 * A estação local recebe `SIMREMAP_NATIVE` de `SIMREMAP_E2E_NATIVE` (padrão `auto`, ver
 * playwright.config.ts). Se `/version` ou `/health` expuser o estado da extensão
 * (`native_enabled`, `native.enabled` ou `native_version`), o teste confere-o contra o modo pedido.
 * Em qualquer caso, duas puxadas base com a mesma semente, em sessões novas, terminam pela cockpit
 * sem falha, com potência plausível e resultado determinístico (mesmo pico de potência).
 */
import { expect, test } from "@playwright/test";

import { API, Cleanup, createSession, expectJson, openCockpit, startRunInCockpit, waitRun, watchConsole } from "./helpers";

test.use({ viewport: { width: 1366, height: 768 } });

const MODE = process.env.SIMREMAP_E2E_NATIVE ?? "auto";

type Json = Record<string, unknown>;

/** Estado da extensão nativa anunciado pela API, ou `null` se a API não o expõe. */
function nativeFlag(body: Json): boolean | null {
  if (typeof body.native_enabled === "boolean") return body.native_enabled;
  const native = body.native as Json | undefined;
  if (native && typeof native.enabled === "boolean") return native.enabled;
  if ("native_version" in body) return body.native_version !== null;
  const checks = body.checks as Record<string, Json> | undefined;
  const check = checks?.native ?? checks?.sim_native;
  if (check && typeof check.status === "string") return check.status === "ok";
  return null;
}

test("motor nativo: estado anunciado e puxadas base determinísticas pela cockpit", async ({ page, request, browserName }) => {
  test.skip(browserName !== "chromium", "referência em Chromium");
  test.setTimeout(300_000);
  const errors = watchConsole(page);
  const version = await expectJson<Json>(await request.get(`${API}/version`), 200);
  const health = await expectJson<Json>(await request.get(`${API}/health`), 200);
  const flag = nativeFlag(version) ?? nativeFlag(health);
  test.info().annotations.push({ type: "native", description: JSON.stringify({ mode: MODE, announced: flag }) });
  if (flag !== null && MODE === "on") expect(flag).toBe(true);
  if (flag !== null && MODE === "off") expect(flag).toBe(false);

  const peaks: number[] = [];
  for (let i = 0; i < 2; i++) {
    const cleanup = new Cleanup();
    try {
      const session = await createSession(request, { vehicle_id: "hatch-20t-gdi", profile_id: "oem-stage", seed: 42, sim_hz: 1000 }, cleanup);
      await openCockpit(page, session.session_id);
      const runId = await startRunInCockpit(page, "baseline_pull");
      await expect(page.getByTestId("run-status")).toHaveText("puxada em curso", { timeout: 15_000 });
      await expect(page.getByTestId("run-status")).toHaveText("puxada concluída", { timeout: 150_000 });
      await expect(page.getByRole("status").filter({ hasText: /Puxada concluída: pico/ })).toBeVisible();
      const run = await waitRun(request, runId);
      expect(run.state).toBe("completed");
      expect(run.summary!.failure_event_id).toBeNull();
      expect(run.summary!.peak_whp).toBeGreaterThan(150);
      expect(run.summary!.peak_whp).toBeLessThan(320);
      peaks.push(run.summary!.peak_whp);
    } finally {
      await cleanup.run();
    }
  }
  // Mesma semente e mesma calibração ⇒ mesma física (tolerância de arredondamento).
  expect(Math.abs(peaks[0]! - peaks[1]!)).toBeLessThan(0.5);
  test.info().annotations.push({ type: "peaks", description: JSON.stringify(peaks) });
  expect(errors, errors.join("\n")).toEqual([]);
});
