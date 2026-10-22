/**
 * Jornada do Rodrigo no navegador (T222; req RF-41; ecu-profiles RF-31 e Apêndice F).
 *
 * `classic-20t-swap`, E100 de série, `seed` 42:
 * 1. workspace da ECU em OEM-Stage; "Trocar ECU" → FT-Pro com snapshot (UI) ⇒
 *    `awaiting_base_setup` e o assistente aberto; `POST .../runs` ⇒ 409 `ECU_SETUP_INCOMPLETE`;
 * 2. assistente de configuração base preenchido pela ficha (60-2, 1-3-4-2, bico 2000 cc/min, E100,
 *    MAP 20–400, failsafes 7200/7500 rpm, 300 kPa, 950 °C; mapa base até 290 kPa) e gravado (UI)
 *    ⇒ checklist mínima completa e `standalone_ready`;
 * 3. puxada base na cockpit (UI) sem falha;
 * 4. afinação de plena carga, two-step a 4000 rpm e boost por marcha (mesmas regras de
 *    `backend/tests/integration/test_journey_rodrigo.py`) gravadas e aplicadas por REST — são
 *    centenas de células calculadas a partir do λ medido, sem valor extra se digitadas na grelha;
 * 5. `multi_pull` de 3 puxadas na cockpit (UI) ⇒ dispersão ≤ 2 %, 0 falhas, ≥ 300 whp.
 */
import { expect, test } from "@playwright/test";

import {
  API,
  applyCalibration,
  Cleanup,
  createSession,
  expectJson,
  getCalibration,
  grid,
  interp,
  openCockpit,
  startRunInCockpit,
  waitRun,
  type CalibrationJson,
  type Json,
  type RunJson,
  type TableJson,
} from "./helpers";

const CLASSIC = "classic-20t-swap";
const WOT_MAP_KPA = 290;
const GEAR2_CEILING_KPA = 180;

test.use({ viewport: { width: 1366, height: 768 } });

interface SchedulePoint {
  rpm: number;
  ignition_advance_deg: number;
  map_target_kpa: number;
}

/** Passos 5–6 do Apêndice F (cópia de `tune_wot` do teste de integração). */
function tuneWot(cal: CalibrationJson, stock: CalibrationJson, schedule: SchedulePoint[], curve: { rpm: number; lambda: number }[]): Record<string, TableJson> {
  const tables = structuredClone(cal.tables);
  tables.boost_duty_base = structuredClone(stock.tables.boost_duty_base!);
  const sRpm = schedule.map((p) => p.rpm);
  const sAdv = schedule.map((p) => p.ignition_advance_deg);
  const sMap = schedule.map((p) => p.map_target_kpa);
  const cRpm = curve.map((p) => p.rpm);
  const cLam = curve.map((p) => p.lambda);
  const lamT = grid(tables.lambda_target!);
  for (const name of ["inj_base_ms", "ignition_base"]) {
    const table = tables[name]!;
    const xs = table.x.values;
    const ys = table.y!.values;
    const values = grid(table);
    ys.forEach((mapKpa, j) => {
      if (mapKpa < 150) return;
      xs.forEach((rpm, i) => {
        if (name === "inj_base_ms") {
          if (rpm < cRpm[0]! || rpm > cRpm[cRpm.length - 1]!) return;
          values[j]![i] = values[j]![i]! * (interp(rpm, cRpm, cLam) / lamT[j]![i]!);
        } else {
          const adv = interp(rpm, sRpm, sAdv) - 0.08 * (mapKpa - interp(rpm, sRpm, sMap));
          values[j]![i] = Math.round(Math.min(Math.max(adv, 5), 35) * 100) / 100;
        }
      });
    });
  }
  return tables;
}

/** Two-step a 4000 rpm (embraiagem) e boost por marcha com teto na 2.ª (`launch_and_gear_calibration`). */
function launchAndGear(cal: CalibrationJson, tables: Record<string, TableJson>): Json {
  const strategies = structuredClone(cal.strategies);
  strategies.two_step = { ...(strategies.two_step ?? { kind: "two_step" }), enabled: true, target_rpm: 4000, activation: "clutch" };
  strategies.boost_control = { ...strategies.boost_control, by_gear_enabled: true };
  const out = structuredClone(tables);
  out.boost_target_gear = {
    table_id: "boost_target_gear",
    kind: "boost_target_gear",
    unit: "kPa",
    live_tunable: true,
    description: "Teto de boost por marcha",
    decimals: 0,
    dims: 2,
    x: { quantity: "gear", values: [1, 2, 3, 4, 5] },
    values: [150, GEAR2_CEILING_KPA, 400, 400, 400],
  };
  for (const table of Object.values(out)) {
    delete table.min;
    delete table.max;
    for (const axis of ["x", "y"] as const) {
      const a = table[axis];
      if (a) table[axis] = { quantity: a.quantity, values: a.values };
    }
  }
  const metadata = Object.fromEntries(Object.entries(cal.metadata).filter(([k]) => ["name", "author_nickname", "notes", "source", "extra"].includes(k)));
  return {
    base_version: cal.version,
    fuel_model: cal.fuel_model,
    tables: out,
    strategies,
    profile_params: cal.profile_params ?? {},
    metadata: { ...metadata, change_summary: "plena carga, two-step 4000 rpm e boost por marcha" },
  };
}

test("Rodrigo: swap para FT-Pro, configuração base no assistente e multi_pull repetível", async ({ page, request, browserName }) => {
  test.skip(browserName !== "chromium", "jornada de referência em Chromium");
  test.setTimeout(480_000);
  const cleanup = new Cleanup();
  try {
    const session = await createSession(request, { vehicle_id: CLASSIC, seed: 42, sim_hz: 1000 }, cleanup);
    const sid = session.session_id;
    expect(session.ecu_state).toBe("oem");

    // 1. Swap na UI da ECU.
    await page.goto(`/sessions/${sid}/ecu`);
    await expect(page.getByTestId("workspace-profile")).toHaveText("OEM-Stage", { timeout: 30_000 });
    await page.getByRole("button", { name: "Trocar ECU" }).click();
    const swapDialog = page.getByRole("dialog");
    await swapDialog.getByRole("radio", { name: /FT-Pro/ }).check();
    await swapDialog.getByRole("checkbox", { name: /snapshot da calibração OEM/ }).check();
    const swapped = page.waitForResponse((r) => r.request().method() === "POST" && r.url().endsWith(`/sessions/${sid}/ecu/swap`));
    await swapDialog.getByRole("button", { name: "Trocar e abrir o assistente" }).click();
    expect((await swapped).status()).toBe(200);
    const wizard = page.getByRole("region", { name: /Configuração base — FT-Pro/ });
    await expect(wizard).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("workspace-profile")).toHaveText("FT-Pro");
    const awaiting = await expectJson<Json>(await request.get(`${API}/sessions/${sid}`), 200);
    expect(awaiting.ecu_state).toBe("awaiting_base_setup");
    const blocked = await request.post(`${API}/sessions/${sid}/runs`, { data: { run_type: "baseline_pull" } });
    expect(blocked.status()).toBe(409);
    expect(((await blocked.json()) as { code: string }).code).toBe("ECU_SETUP_INCOMPLETE");

    // 2. Assistente: ficha do carro + failsafes do Rodrigo.
    const fill = async (label: RegExp, value: string) => {
      const field = wizard.getByLabel(label);
      if ((await field.evaluate((el) => el.tagName)) === "SELECT") await field.selectOption(value);
      else await field.fill(value);
    };
    const next = () => wizard.getByRole("button", { name: "Avançar" }).click();
    await expect(wizard.getByRole("group", { name: /Passo 1 de 6/ })).toBeVisible();
    await fill(/^Roda fônica/, "60-2");
    await fill(/^Ângulo da falha/, "90");
    await fill(/^Ordem de ignição/, "1, 3, 4, 2");
    await next();
    await fill(/^Vazão do bico/, "2000");
    await fill(/^Tensões do tempo morto/, "8, 10, 12, 14, 16");
    await fill(/^Tempo morto/, "1.6, 1.2, 0.95, 0.8, 0.7");
    await next();
    await fill(/^Combustível/, "e100");
    await fill(/^AFR estequiométrico/, "9");
    await fill(/^Densidade/, "0.789");
    await next();
    await fill(/^MAP a 0,5 V/, "20");
    await fill(/^MAP a 4,5 V/, "400");
    await next();
    await fill(/^Corte de rotação/, "7200");
    await fill(/^Sobre-rotação/, "7500");
    await fill(/^Sobrepressão/, "300");
    await fill(/^EGT máxima/, "950");
    await next();
    await expect(wizard.getByRole("group", { name: /Passo 6 de 6/ })).toBeVisible();
    await fill(/^MAP máximo do mapa base/, String(WOT_MAP_KPA));
    const saved = page.waitForResponse((r) => r.request().method() === "PUT" && r.url().endsWith(`/sessions/${sid}/ecu/base-setup`));
    await wizard.getByRole("button", { name: "Gravar e gerar mapa base" }).click();
    const setup = await expectJson<{ ecu_state: string; calibration_id: string }>(await saved, 200);
    expect(setup.ecu_state).toBe("standalone_ready");
    await expect(wizard).toHaveCount(0, { timeout: 15_000 });
    const ready = await expectJson<Json>(await request.get(`${API}/sessions/${sid}`), 200);
    expect(ready.profile_id).toBe("ft-pro");
    expect(ready.ecu_state).toBe("standalone_ready");

    // 3. Puxada base no mapa do assistente (cockpit).
    await openCockpit(page, sid);
    await expect(page.getByTestId("profile-name")).toHaveText("FT-Pro");
    const baseId = await startRunInCockpit(page, "baseline_pull");
    await expect(page.getByTestId("run-status")).toHaveText("puxada concluída", { timeout: 150_000 });
    const base = await waitRun(request, baseId);
    expect(base.state).toBe("completed");
    expect(base.summary!.failure_event_id).toBeNull();

    // 4. Afinação (REST) aplicada à sessão.
    const cal = await getCalibration(request, setup.calibration_id);
    const stock = await getCalibration(request, `stock-${CLASSIC}-oem-stage`);
    const vehicle = await expectJson<{ reference_command_schedule: { points: SchedulePoint[] } }>(await request.get(`${API}/vehicles/${CLASSIC}`), 200);
    const baseRun = await expectJson<RunJson>(await request.get(`${API}/runs/${baseId}`), 200);
    const tables = tuneWot(cal, stock, vehicle.reference_command_schedule.points, baseRun.curve!);
    await expectJson(await request.put(`${API}/calibrations/${cal.calibration_id}`, { data: launchAndGear(cal, tables) }), 200);
    await applyCalibration(request, sid, cal.calibration_id);

    // 5. multi_pull de 3 puxadas (cockpit).
    const multiId = await startRunInCockpit(page, "multi_pull", { pullCount: 3 });
    await expect(page.getByTestId("run-status")).toHaveText("puxada concluída", { timeout: 300_000 });
    await expect(page.getByRole("status").filter({ hasText: /Puxada concluída: pico/ })).toBeVisible();
    const multi = await waitRun(request, multiId);
    expect(multi.state, multi.abort_reason ?? "").toBe("completed");
    expect(multi.pulls).toHaveLength(3);
    expect(multi.repeatability!.peak_whp_spread_pct).toBeLessThanOrEqual(2);
    expect(multi.summary!.failure_event_id).toBeNull();
    expect(multi.summary!.peak_whp).toBeGreaterThanOrEqual(300);
    const health = await expectJson<{ engine_locked: boolean; failures: unknown[] }>(await request.get(`${API}/sessions/${sid}/engine/health`), 200);
    expect(health.engine_locked).toBe(false);
    expect(health.failures).toHaveLength(0);
    test.info().annotations.push({
      type: "rodrigo",
      description: JSON.stringify({
        base_whp: base.summary!.peak_whp,
        multi_whp: multi.summary!.peak_whp,
        spread_pct: multi.repeatability!.peak_whp_spread_pct,
      }),
    });
  } finally {
    await cleanup.run();
  }
});
