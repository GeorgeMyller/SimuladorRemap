/**
 * Benchmark da cockpit (T187; dyno-cockpit-ui RNF-01, RNF-02): com todos os painéis visíveis,
 * 1920×1080 e uma `sweep_pull` com a sessão a 1000 Hz, a renderização fica ≥ 30 FPS no p5
 * (contador de rAF por janela de 1 s) e o separador não passa de 500 MB (RNF-03, se medível).
 */
import { expect, test, type Page } from "@playwright/test";

const VEHICLE_ID = process.env.SIMREMAP_E2E_VEHICLE ?? "hatch-20t-gdi";
const MEASURE_S = Number(process.env.SIMREMAP_E2E_FPS_SECONDS ?? 20);

interface FpsReport {
  samples: number[];
  p5: number;
  p50: number;
}

/** Instala um contador de rAF e devolve o FPS por janela de 1 s após `seconds`. */
async function measureFps(page: Page, seconds: number): Promise<FpsReport> {
  return page.evaluate(async (durationS) => {
    const samples: number[] = [];
    let frames = 0;
    let windowStart = performance.now();
    let running = true;
    const tick = (now: number) => {
      frames += 1;
      if (now - windowStart >= 1000) {
        samples.push((frames * 1000) / (now - windowStart));
        frames = 0;
        windowStart = now;
      }
      if (running) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    await new Promise((resolve) => setTimeout(resolve, durationS * 1000));
    running = false;
    const sorted = [...samples].sort((a, b) => a - b);
    const pick = (q: number) => sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))] ?? 0;
    return { samples, p5: pick(0.05), p50: pick(0.5) };
  }, seconds);
}

test.describe("cockpit: desempenho de renderização", () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  test(`todos os painéis a ≥ 30 FPS p5 durante uma sweep_pull a 1000 Hz (${MEASURE_S} s)`, async ({ page, request, browserName }) => {
    test.skip(browserName !== "chromium", "benchmark de referência em Chromium (RNF-01)");
    test.setTimeout((MEASURE_S + 90) * 1000);

    const created = await request.post("/api/v1/sessions", { data: { vehicle_id: VEHICLE_ID, profile_id: "oem-stage", sim_hz: 1000 } });
    test.skip(created.status() === 404, "rotas de sessão (dyno-bench) ainda não registadas");
    expect(created.status(), await created.text()).toBe(201);
    const session = (await created.json()) as { session_id: string };

    try {
      await page.goto(`/sessions/${session.session_id}/dyno`);
      await expect(page.getByTestId("vehicle-name")).toBeVisible();
      await expect(page.getByTestId("connection-state")).toHaveText("conectado", { timeout: 15_000 });

      // Todos os painéis do topo visíveis e o espectrograma ativo na faixa inferior.
      for (const name of ["Dinamômetro", "Lambda e EGT", "Bancada", "Instrumentos"]) {
        const expand = page.getByRole("button", { name: `Expandir ${name}` });
        if (await expand.count()) await expand.click();
      }
      await page.getByRole("tab", { name: /Espectrograma/ }).click();

      await page.getByRole("combobox", { name: "Tipo de puxada" }).selectOption("sweep_pull");
      await page.getByRole("button", { name: "Iniciar" }).click();
      await expect(page.getByTestId("run-status")).toHaveText("puxada em curso", { timeout: 15_000 });

      const fps = await measureFps(page, MEASURE_S);
      test.info().annotations.push({ type: "fps", description: JSON.stringify({ p5: fps.p5, p50: fps.p50, n: fps.samples.length }) });
      expect(fps.samples.length).toBeGreaterThanOrEqual(Math.floor(MEASURE_S * 0.8));
      expect(fps.p5).toBeGreaterThanOrEqual(30);

      const memory = await page.evaluate(async () => {
        const perf = performance as Performance & { measureUserAgentSpecificMemory?: () => Promise<{ bytes: number }> };
        if (!perf.measureUserAgentSpecificMemory || !crossOriginIsolated) return null;
        return (await perf.measureUserAgentSpecificMemory()).bytes;
      });
      if (memory !== null) expect(memory).toBeLessThanOrEqual(500 * 1024 * 1024);

      // Sem perda de frames sustentada durante a medição.
      await expect(page.getByTestId("frame-loss")).toHaveCount(0);
    } finally {
      const active = page.getByRole("button", { name: "Abortar" });
      if (await active.isEnabled().catch(() => false)) await active.click();
      await request.delete(`/api/v1/sessions/${session.session_id}`);
    }
  });
});
