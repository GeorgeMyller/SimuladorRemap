/* eslint-disable @typescript-eslint/unbound-method -- asserções sobre vi.fn */
/** T036/T050/T051/T056 — Falhas por modo, Visão Térmica / Raio-X, subscrição e atalhos (RF-20..RF-22). */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { CAR_SPRITES, spriteFor } from "@/features/pixel-cars/sprites";
import { FAILURE_MODES, parseEnvelope } from "@/lib/ws";

import { vehicleFixture } from "./test-utils/harness";
import { engineProfileFor } from "./audio/engineProfile";
import { CarOnRollerView, drawCarScene, thermalGeometry } from "./CarOnRollerView";
import { buildSubscription, THERMAL_CHANNELS } from "./channels";
import { IMMERSION_SHORTCUTS } from "./messages";
import { CarAnimator, MAX_AFTERFIRE_PARTICLES, MAX_PARTICLES } from "./render/CarAnimator";
import { FAILURE_FX, failureFxFor } from "./render/failureFx";
import { RenderLoop } from "./render/RenderLoop";
import { SHORTCUTS } from "./ShortcutsDialog";
import { TelemetryStore } from "./store";
import { frameEnvelope, installCanvasMock, make2dContext, manualRaf } from "./test-utils/mocks";
import { isThermalViewOn, setThermalView } from "./thermalView";

const input = (over: Partial<Parameters<CarAnimator["step"]>[1]> = {}) => ({
  rollerSpeedKmh: 100,
  rpm: 4000,
  maxRpm: 7000,
  throttlePct: 100,
  afterfire: 0,
  afterfireSeq: 0,
  ...over,
});

afterEach(() => setThermalView(false));

describe("CarAnimator: falhas por modo e pops & bangs", () => {
  it("cada modo de falha tem efeito próprio (fumaça, fagulhas, detritos)", () => {
    const signatures = FAILURE_MODES.filter((m) => m !== "pre_ignition").map((m) => {
      const fx = FAILURE_FX[m];
      return `${fx.smokeTone}|${fx.smokeAt}|${fx.sparkTone}|${fx.debrisTone}`;
    });
    expect(new Set(signatures).size).toBe(signatures.length);
    expect(failureFxFor("desconhecido").smokeTone).toBe("smokeGrey");
    expect(failureFxFor(null).debris).toBe(40);
  });

  it.each([
    ["knock_damage", "smokeBlue", "spark"],
    ["pre_ignition", "smokeBlue", "spark"],
    ["egt_overtemp", "smokeLight", "spark"],
    ["rod_failure", "smokeOil", "spark"],
    ["turbo_meltdown", "smokeBlack", "sparkOrange"],
  ] as const)("%s → fumaça %s e fagulhas %s", (mode, smoke, spark) => {
    const a = new CarAnimator();
    a.triggerFailure(11, mode);
    a.step(0.05, input());
    expect(a.failureMode).toBe(mode);
    expect(a.particles.some((p) => p.kind === "smoke" && p.tone === smoke)).toBe(true);
    expect(a.particles.some((p) => p.kind === "spark" && p.tone === spark)).toBe(true);
  });

  it("rod_failure solta detritos metálicos; piston_failure fumaça branca densa pelo escape", () => {
    const rod = new CarAnimator();
    rod.triggerFailure(5, "rod_failure");
    expect(rod.particles.filter((p) => p.tone === "debrisMetal").length).toBe(FAILURE_FX.rod_failure.debris);
    const piston = new CarAnimator();
    piston.configure({ exhaust: { x: 50, y: 160 }, engineBay: { x: 330, y: 120 } });
    piston.triggerFailure(5, "piston_failure");
    piston.step(0.016, input());
    const white = piston.particles.filter((p) => p.tone === "smokeWhite");
    expect(white.length).toBe(FAILURE_FX.piston_failure.smokePerStep);
    for (const p of white) expect(p.x).toBeLessThan(100);
  });

  it("falhas térmicas deixam brilho residual no ponto quente; reset limpa", () => {
    const a = new CarAnimator();
    a.triggerFailure(9, "egt_overtemp");
    expect(a.heatGlow).toBe(1);
    for (let i = 0; i < 100; i += 1) a.step(0.05, input());
    expect(a.heatGlow).toBeCloseTo(0.35);
    a.reset();
    expect(a.heatGlow).toBe(0);
    expect(a.failureMode).toBeNull();
  });

  it("efeitos de falha determinísticos por seed e dentro do teto de partículas", () => {
    const a = new CarAnimator();
    const b = new CarAnimator();
    a.triggerFailure(77, "turbo_meltdown");
    b.triggerFailure(77, "turbo_meltdown");
    expect(a.particles.map((p) => [p.vx, p.vy])).toEqual(b.particles.map((p) => [p.vx, p.vy]));
    for (let i = 0; i < 300; i += 1) a.step(0.01, input());
    expect(a.particles.length).toBeLessThanOrEqual(MAX_PARTICLES);
  });

  it("pops & bangs: labareda maior com núcleo, clarão local no escape e teto por rajada", () => {
    const a = new CarAnimator();
    a.step(0.016, input({ afterfire: 10, afterfireSeq: 3 }));
    expect(a.particles.length).toBeLessThanOrEqual(MAX_AFTERFIRE_PARTICLES);
    expect(a.particles.some((p) => p.tone === "flameCore")).toBe(true);
    expect(Math.max(...a.particles.filter((p) => p.kind === "flame").map((p) => p.size))).toBeGreaterThan(8);
    expect(a.exhaustFlash).toBeGreaterThan(0.8);
    a.step(0.1, input());
    a.step(0.1, input());
    expect(a.exhaustFlash).toBe(0);
  });
});

describe("drawCarScene com Visão Térmica / Raio-X", () => {
  it("carroçaria translúcida e camada térmica (turbo e compressor)", () => {
    for (const sprite of CAR_SPRITES) {
      const a = new CarAnimator();
      a.triggerFailure(2, "turbo_meltdown");
      a.step(0.016, input({ afterfire: 1, afterfireSeq: 4 }));
      const ctx = make2dContext();
      drawCarScene(ctx, a, 480, 240, sprite, { egtC: 900, egtPreTurboC: 990 });
      expect(ctx.stroke).toHaveBeenCalled();
      expect(ctx.globalAlpha).toBe(1);
    }
  });

  it("geometria térmica sai dos pontos engineBay/exhaust do sprite; V8 usa compressor mecânico", () => {
    const g = thermalGeometry(spriteFor("hatch-20t-gdi"));
    expect(g).toMatchObject({ engine: { x: 340, y: 123 }, exhaust: { x: 70, y: 163 }, scale: 5, induction: "turbo" });
    expect(thermalGeometry(spriteFor("muscle-v8-sc")).induction).toBe("supercharger");
  });
});

describe("CarOnRollerView: toggle e atalho T", () => {
  function mount() {
    const mock = installCanvasMock({ ctx2d: true });
    const r = manualRaf();
    const loop = new RenderLoop({ raf: r.raf, caf: r.caf, doc: null });
    loop.start();
    const store = new TelemetryStore();
    const anim = new CarAnimator();
    const utils = render(<CarOnRollerView store={store} loop={loop} maxRpm={7000} animator={anim} vehicleId="coupe-30t-i6" />);
    return { ...utils, mock, r, store, anim };
  }

  it("botão com aria-pressed liga/desliga a camada e lê egt_c/egt_pre_turbo_c", () => {
    const { mock, r, store } = mount();
    const button = screen.getByRole("button", { name: "Visão Térmica / Raio-X" });
    expect(button).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("img")).toHaveAttribute("data-thermal", "on");
    expect(screen.getByRole("img", { name: /visão térmica ligada/i })).toBeInTheDocument();
    store.ingest(parseEnvelope(frameEnvelope(1, 1, { rpm: 5000, roller_speed_kmh: 90, egt_c: 880, egt_pre_turbo_c: 960 }))!);
    act(() => r.tick(16));
    act(() => r.tick(32));
    fireEvent.click(button);
    expect(isThermalViewOn()).toBe(false);
    mock.spy.mockRestore();
  });

  it("tecla T alterna; ignorada em campos de texto, com modificador ou com diálogo aberto", () => {
    const { mock } = mount();
    fireEvent.keyDown(window, { key: "t" });
    expect(isThermalViewOn()).toBe(true);
    fireEvent.keyDown(window, { key: "T" });
    expect(isThermalViewOn()).toBe(false);
    const input = document.createElement("input");
    document.body.appendChild(input);
    fireEvent.keyDown(input, { key: "t" });
    fireEvent.keyDown(window, { key: "t", ctrlKey: true });
    expect(isThermalViewOn()).toBe(false);
    const dialog = document.createElement("div");
    dialog.setAttribute("role", "dialog");
    document.body.appendChild(dialog);
    fireEvent.keyDown(window, { key: "t" });
    expect(isThermalViewOn()).toBe(false);
    dialog.remove();
    input.remove();
    mock.spy.mockRestore();
  });

  it("a falha usa o modo da última event.failure do store", () => {
    const { mock, store, anim, rerender } = mount();
    store.events.push({ kind: "failure", t: 1, failure: { mode: "rod_failure" } } as never);
    rerender(<CarOnRollerView store={store} maxRpm={7000} animator={anim} vehicleId="coupe-30t-i6" failureSeq={9} />);
    expect(anim.failureMode).toBe("rod_failure");
    mock.spy.mockRestore();
  });
});

describe("subscrição, perfil de áudio e atalhos", () => {
  it("egt_c e egt_pre_turbo_c só com a visão térmica ligada e o carro visível", () => {
    const base = { nCyl: 4, audioActive: false, pressureCylinder: 1 };
    expect(THERMAL_CHANNELS).toEqual(["egt_c", "egt_pre_turbo_c"]);
    expect(buildSubscription({ ...base, visiblePanels: ["car"] }).channels).not.toContain("egt_pre_turbo_c");
    expect(buildSubscription({ ...base, visiblePanels: ["car"], thermalView: true }).channels).toEqual(expect.arrayContaining(["egt_c", "egt_pre_turbo_c"]));
    expect(buildSubscription({ ...base, visiblePanels: ["dyno"], thermalView: true }).channels).not.toContain("egt_pre_turbo_c");
  });

  it("perfil de áudio por veículo: arquétipo e polia do compressor", () => {
    expect(engineProfileFor(vehicleFixture)).toMatchObject({ nCyl: 4, turbo: true, archetype: "i4_turbo_modern" });
    const v8 = {
      ...vehicleFixture,
      vehicle_id: "muscle-v8-sc",
      induction: "supercharger" as const,
      engine: { architecture: "v" as const, n_cyl: 8, firing_order: [1, 5, 4, 8, 6, 3, 7, 2] },
      supercharger: { pulley_ratio: 2.3 },
    };
    expect(engineProfileFor(v8)).toMatchObject({ archetype: "v8_supercharged", turbo: false, pulleyRatio: 2.3 });
  });

  it("diálogo de atalhos lista Espaço (acelerador com mola) e T (visão térmica) sem conflito", () => {
    const keys = SHORTCUTS.map((s) => s.keys);
    expect(keys).toEqual(expect.arrayContaining(IMMERSION_SHORTCUTS.map((s) => s.keys)));
    expect(keys.some((k) => k.startsWith("Espaço"))).toBe(true);
    expect(keys.filter((k) => k === "T")).toHaveLength(1);
    for (const reserved of ["M", "U", "D", "L", "?"]) expect(keys).not.toContain(`${reserved} `);
  });
});
