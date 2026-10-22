/**
 * Jornada do Lucas no navegador (T221; req RF-40; knock-and-failure-model G-01).
 *
 * `hatch-20t-gdi`, OEM-Stage, E27, `seed` 42, 1000 Hz:
 * 1. puxada base pela cockpit (UI);
 * 2. calibração exagerada (280 kPa abs nas células com pressão, +8° em `ignition_base`, limites
 *    de torque ×1,5) gravada e aplicada por REST — editar ~600 células à mão no navegador não
 *    acrescenta cobertura (a edição de tabelas tem os seus próprios testes) e levaria minutos;
 * 3. `sweep_pull` a 150 rpm/s pela cockpit ⇒ alarme "Motor destruído", laudo com a cadeia causal
 *    e as recomendações R-KNOCK-01 e R-LAMBDA-01 visíveis no modal; "Restaurar motor" na UI;
 * 4. acerto corrigido do laudo, Stage 2 (RF-40), por REST: λ 0,85 com MAP ≥ 150, −3° nos cilindros
 *    com knock, +1° acima de 5500 rpm, pedido/limites de torque acima da pressão e pressão alvo por
 *    rotação até 292 kPa abs (o mesmo acerto de backend/tests/integration/test_journey_lucas.py);
 * 5. `sweep_pull` final pela cockpit ⇒ "puxada concluída", knock ≤ light, EGT ≤ 950 °C, intacto e
 *    Δwhp ≥ +65 sobre a puxada base.
 */
import { expect, test } from "@playwright/test";

import {
  API,
  applyCalibration,
  audit,
  Cleanup,
  cloneWithTables,
  createSession,
  expectJson,
  grid,
  KNOCK_RANK,
  logEvents,
  openCockpit,
  startRunInCockpit,
  waitRun,
  worstKnock,
  type TableJson,
} from "./helpers";

const VEHICLE = "hatch-20t-gdi";
const STOCK = "stock-hatch-20t-gdi-oem-stage";
const RAMP = 150;

function exaggerate(tables: Record<string, TableJson>): void {
  for (const name of ["torque_request", "torque_limit", "torque_limit_gear"]) {
    const t = tables[name]!;
    t.values = t.dims === 3 ? grid(t).map((row) => row.map((v) => 1.5 * v)) : (t.values as number[]).map((v) => 1.5 * v);
  }
  const p = tables.oem_pressure_target!;
  p.values = grid(p).map((row) => row.map((v) => (v >= 150 ? 280 : v)));
  const ig = tables.ignition_base!;
  ig.values = grid(ig).map((row) => row.map((v) => v + 8));
}

// Stage 2 do acerto corrigido: teto da pressão alvo por rotação (kPa abs) — o torque na biela
// (420 N·m) limita a 4500–6000 rpm e a potência de pico sai a 6000–6300 rpm.
const CORRECTED_BOOST_RPM = [4000, 4500, 5000, 5500, 6000, 6300, 6500];
const CORRECTED_BOOST_KPA = [225, 226, 244, 260, 276, 292, 296];
const CORRECTED_LAMBDA = 0.85;
const CORRECTED_TORQUE_NM = 520;
const CORRECTED_OVERBOOST_KPA = 340;
const MIN_DELTA_WHP = 65;

function interp(x: number, xs: number[], ys: number[]): number {
  if (x <= xs[0]!) return ys[0]!;
  for (let i = 1; i < xs.length; i++) {
    if (x <= xs[i]!) return ys[i - 1]! + ((x - xs[i - 1]!) / (xs[i]! - xs[i - 1]!)) * (ys[i]! - ys[i - 1]!);
  }
  return ys[ys.length - 1]!;
}

function correct(tables: Record<string, TableJson>, cylinders: number[], knockRpmMax: number): void {
  const req = tables.torque_request!;
  req.values = grid(req).map((row) => row.map((v) => 1.4 * v));
  const lim = tables.torque_limit!;
  const limRpm = lim.x.values;
  lim.values = (lim.values as number[]).map((v, i) =>
    limRpm[i]! >= 4250 ? Math.max(v, interp(limRpm[i]!, [4250, 4750, 5250], [v, 450, CORRECTED_TORQUE_NM])) : v,
  );
  const gear = tables.torque_limit_gear!;
  const gears = gear.x.values;
  gear.values = (gear.values as number[]).map((v, i) => (gears[i]! >= 3 ? Math.max(v, CORRECTED_TORQUE_NM) : v));
  const p = tables.oem_pressure_target!;
  const pRpm = p.x.values;
  p.values = grid(p).map((row) => row.map((v, i) => Math.min(v, interp(pRpm[i]!, CORRECTED_BOOST_RPM, CORRECTED_BOOST_KPA))));
  const lam = tables.lambda_target!;
  const maps = lam.y!.values;
  lam.values = grid(lam).map((row, j) => row.map((v) => (maps[j]! >= 150 ? CORRECTED_LAMBDA : v)));
  const ig = tables.ignition_base!;
  const igRpm = ig.x.values;
  ig.values = grid(ig).map((row) => row.map((v, i) => v + interp(igRpm[i]!, [5000, 5500], [0, 1])));
  const edge = knockRpmMax + 250;
  for (const c of cylinders) {
    tables[`ignition_trim_cyl_${c}`] = {
      table_id: `ignition_trim_cyl_${c}`,
      kind: "ignition_trim_cyl",
      unit: "°",
      live_tunable: true,
      cylinder: c,
      description: "R-KNOCK-01: −3° na região dos ciclos com knock",
      decimals: 1,
      dims: 3,
      x: { quantity: "rpm", values: [500, edge, edge + 500, 8000] },
      y: { quantity: "map_kpa", values: [20, 400] },
      values: [
        [-3, -3, 0, 0],
        [-3, -3, 0, 0],
      ],
    };
  }
}

// O projeto "chromium" herda 1280×720 de devices["Desktop Chrome"] (abaixo do mínimo de 1366×768 da cockpit).
// bypassCSP: auditoria axe do laudo (T224) com o script injetado.
test.use({ viewport: { width: 1366, height: 768 }, bypassCSP: true });

interface Report {
  causal_chain: unknown[];
  recommendations: { rule_id: string; action: string }[];
}

test("Lucas: knock severo destrói o motor e o acerto do laudo termina a puxada intacto", async ({ page, request, browserName }) => {
  test.skip(browserName !== "chromium", "jornada de referência em Chromium");
  test.setTimeout(420_000);
  const cleanup = new Cleanup();
  try {
    const session = await createSession(request, { vehicle_id: VEHICLE, profile_id: "oem-stage", seed: 42, fuel_id: "e27", sim_hz: 1000 }, cleanup);
    const sid = session.session_id;
    await openCockpit(page, sid);
    await expect(page.getByTestId("profile-name")).toContainText(/OEM/i);

    // 1. Puxada base.
    const baseId = await startRunInCockpit(page, "baseline_pull");
    await expect(page.getByTestId("run-status")).toHaveText("puxada concluída", { timeout: 120_000 });
    const base = await waitRun(request, baseId);
    expect(base.state).toBe("completed");
    expect(base.summary!.failure_event_id).toBeNull();
    expect(worstKnock(await logEvents(request, baseId))).toMatch(/none|light/);

    // 2. Calibração exagerada (REST) aplicada à sessão.
    const exaggerated = await cloneWithTables(request, VEHICLE, "oem-stage", STOCK, "Lucas exagerada", exaggerate);
    await applyCalibration(request, sid, exaggerated.calibration_id);

    // 3. sweep_pull ⇒ falha catastrófica e laudo.
    const failedId = await startRunInCockpit(page, "sweep_pull", { rampRpmS: RAMP });
    await expect(page.getByTestId("run-status")).toHaveText("motor destruído", { timeout: 120_000 });
    await expect(page.getByRole("alert").filter({ hasText: /Motor destruído/ })).toBeVisible();
    const failed = await waitRun(request, failedId);
    expect(failed.state).toBe("engine_failed");
    const failedEvents = await logEvents(request, failedId);
    expect(worstKnock(failedEvents)).toBe("severe");

    const report = await expectJson<Report>(await request.get(`${API}/runs/${failedId}/forensic-report`), 200);
    const rules = report.recommendations.map((r) => r.rule_id);
    expect(rules).toEqual(expect.arrayContaining(["R-KNOCK-01", "R-LAMBDA-01"]));

    // A cockpit abre o laudo sozinha após a falha; "Ver laudo" reabre-o se tiver sido fechado.
    const dialog = page.getByRole("dialog");
    await expect(dialog.or(page.getByRole("button", { name: "Ver laudo" })).first()).toBeVisible();
    if (!(await dialog.isVisible())) await page.getByRole("button", { name: "Ver laudo" }).click();
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("heading", { name: /Laudo forense/ })).toBeVisible();
    const chain = dialog.getByRole("list", { name: "Cadeia causal" }).getByRole("listitem");
    await expect(chain.first()).toBeVisible({ timeout: 15_000 });
    expect(await chain.count()).toBeGreaterThanOrEqual(3);
    for (const id of ["R-KNOCK-01", "R-LAMBDA-01"]) {
      const action = report.recommendations.find((r) => r.rule_id === id)!.action;
      await expect(dialog.getByText(action, { exact: false }).first()).toBeVisible();
    }
    await expect(dialog.getByRole("list", { name: "Componentes danificados" }).getByRole("listitem").filter({ hasText: /destruído/ })).not.toHaveCount(0);

    // Acessibilidade do laudo e da cockpit em "motor destruído" (T224).
    const autopsyViolations = await audit(page, "laudo");
    expect(autopsyViolations, autopsyViolations.join("\n")).toEqual([]);

    // Restaurar o motor pela UI.
    const restored = page.waitForResponse((r) => r.request().method() === "POST" && r.url().endsWith(`/sessions/${sid}/engine/restore`));
    await dialog.getByRole("button", { name: "Restaurar motor" }).click();
    expect((await restored).ok()).toBeTruthy();
    if (await dialog.isVisible()) await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.getByTestId("run-status")).not.toHaveText("motor destruído", { timeout: 15_000 });
    const healthAfterRestore = await expectJson<{ engine_locked: boolean }>(await request.get(`${API}/sessions/${sid}/engine/health`), 200);
    expect(healthAfterRestore.engine_locked).toBe(false);

    // 4. Acerto corrigido pelo laudo (cilindros e faixa de rotação dos ciclos com knock ≥ moderate).
    const knocks = failedEvents.filter((e) => e.type === "event.knock" && (KNOCK_RANK[String(e.payload.knock_class)] ?? 0) >= 2);
    const cylinders = [...new Set(knocks.map((k) => Number(k.payload.cylinder)))].sort();
    const rpmMax = knocks.length ? Math.max(...knocks.map((k) => Number(k.payload.rpm))) : 4000;
    const corrected = await cloneWithTables(
      request,
      VEHICLE,
      "oem-stage",
      STOCK,
      "Lucas corrigida",
      (t) => correct(t, cylinders.length ? cylinders : [1, 2, 3, 4], rpmMax),
      (s) => {
        // Overboost da ECU acima do novo alvo de pressão (de série 265 kPa).
        (s.boost_control as Record<string, unknown>).overboost_kpa = CORRECTED_OVERBOOST_KPA;
      },
    );
    await applyCalibration(request, sid, corrected.calibration_id);

    // 5. Puxada final segura.
    const finalId = await startRunInCockpit(page, "sweep_pull", { rampRpmS: RAMP });
    await expect(page.getByTestId("run-status")).toHaveText("puxada concluída", { timeout: 120_000 });
    await expect(page.getByRole("status").filter({ hasText: /Puxada concluída: pico/ })).toBeVisible();
    const final = await waitRun(request, finalId);
    expect(final.state).toBe("completed");
    expect(final.summary!.failure_event_id).toBeNull();
    expect(final.summary!.egt_max_c).toBeLessThanOrEqual(950);
    expect(KNOCK_RANK[worstKnock(await logEvents(request, finalId))]).toBeLessThanOrEqual(KNOCK_RANK.light!);
    // `failures` guarda o histórico da sessão (a falha da puxada exagerada fica registada).
    const health = await expectJson<{ engine_locked: boolean; failures: { run_id: string }[]; components?: { component_id: string; health: number }[] }>(
      await request.get(`${API}/sessions/${sid}/engine/health`),
      200,
    );
    expect(health.engine_locked).toBe(false);
    expect(health.failures.filter((f) => f.run_id === finalId)).toHaveLength(0);
    for (const c of health.components ?? []) expect(c.health, c.component_id).toBeGreaterThanOrEqual(0.999);
    // RF-40: ganho estável de +65 whp sobre a puxada base.
    expect(final.summary!.peak_whp - base.summary!.peak_whp).toBeGreaterThanOrEqual(MIN_DELTA_WHP);
    test.info().annotations.push({
      type: "lucas",
      description: JSON.stringify({
        base_whp: base.summary!.peak_whp,
        failed_whp: failed.summary!.peak_whp,
        final_whp: final.summary!.peak_whp,
        delta_whp: final.summary!.peak_whp - base.summary!.peak_whp,
        final_egt_c: final.summary!.egt_max_c,
        knock_cylinders: cylinders,
        rules,
      }),
    });
  } finally {
    await cleanup.run();
  }
});
