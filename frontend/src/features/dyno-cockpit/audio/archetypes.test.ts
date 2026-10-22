/** T012/T037 / 003 T015 — Arquétipos de timbre (002 RF-20; 003 RF-10; D-11, D-05). */
import { describe, expect, it } from "vitest";

import { FakeAudioContext, fakeAudioFactory } from "../test-utils/mocks";

import { ARCHETYPE_PRESETS, ENGINE_ARCHETYPES, archetypeFor, toneSignature, type EngineArchetype } from "./archetypes";
import { AudioEngine, type EngineProfile } from "./AudioEngine";
import { camLopeAt, spoolBandHz, superchargerWhineHz, wastegateHissGain, whineGain } from "./EngineSynth";

const I4_MODERN: EngineProfile = { nCyl: 4, architecture: "inline", firingOrder: [1, 3, 4, 2], turbo: true, archetype: "i4_turbo_modern" };
const I4_CLASSIC: EngineProfile = { ...I4_MODERN, archetype: "i4_turbo_classic" };

function build(profile: EngineProfile) {
  FakeAudioContext.instances = [];
  const engine = new AudioEngine(profile, { createContext: fakeAudioFactory });
  return { engine, ctx: FakeAudioContext.instances[0]! };
}

describe("archetypeFor", () => {
  it("mapeia os 4 veículos do catálogo", () => {
    expect(archetypeFor("hatch-20t-gdi", { nCyl: 4, architecture: "inline" })).toBe("i4_turbo_modern");
    expect(archetypeFor("coupe-30t-i6", { nCyl: 6, architecture: "inline" })).toBe("i6_turbo");
    expect(archetypeFor("classic-20t-swap", { nCyl: 4, architecture: "inline" })).toBe("i4_turbo_classic");
    expect(archetypeFor("muscle-v8-sc", { nCyl: 8, architecture: "v" })).toBe("v8_supercharged");
  });

  it("fallback pelas características do motor", () => {
    expect(archetypeFor("custom", { nCyl: 8, architecture: "v", induction: "turbo" })).toBe("v8_supercharged");
    expect(archetypeFor(null, { nCyl: 4, architecture: "inline", induction: "supercharger" })).toBe("v8_supercharged");
    expect(archetypeFor("custom-i6", { nCyl: 6, architecture: "inline" })).toBe("i6_turbo");
    expect(archetypeFor("old-swap-build", { nCyl: 4, architecture: "inline" })).toBe("i4_turbo_classic");
    expect(archetypeFor(undefined, { nCyl: 4, architecture: "inline" })).toBe("i4_turbo_modern");
  });
});

describe("presets por arquétipo", () => {
  const preset = (a: EngineArchetype) => ARCHETYPE_PRESETS[a];

  it("os 4 perfis têm timbres diferentes e ressonadores dependentes do arquétipo", () => {
    expect(new Set(ENGINE_ARCHETYPES.map((a) => toneSignature(preset(a)))).size).toBe(4);
    expect(new Set(ENGINE_ARCHETYPES.map((a) => preset(a).tone.resonators[0].hz)).size).toBe(4);
    for (const a of ENGINE_ARCHETYPES) {
      const [low, mid] = preset(a).tone.resonators;
      expect(low.hz).toBeGreaterThanOrEqual(90);
      expect(low.hz).toBeLessThanOrEqual(140);
      expect(mid.hz).toBeGreaterThanOrEqual(280);
      expect(mid.hz).toBeLessThanOrEqual(450);
      expect(preset(a).reference.firingOrder).toHaveLength(preset(a).reference.nCyl);
    }
  });

  it("I6 3.0 suave: pulsos mais largos, menos jitter, menos saturação e resposta mais macia que o I4 GDI", () => {
    const i6 = preset("i6_turbo");
    const i4 = preset("i4_turbo_modern");
    expect(i6.pulse.widthFrac).toBeGreaterThan(i4.pulse.widthFrac);
    expect(i6.pulse.ampJitter).toBeLessThan(i4.pulse.ampJitter);
    expect(i6.tone.saturation).toBeLessThan(i4.tone.saturation);
    expect(i6.tone.cutoffCurve).toBeGreaterThan(i4.tone.cutoffCurve);
    expect(i6.responseS).toBeGreaterThan(i4.responseS);
  });

  it("AP comando bravo: maior irregularidade, lope de marcha lenta e flutter forte", () => {
    const classic = preset("i4_turbo_classic");
    for (const other of ENGINE_ARCHETYPES.filter((a) => a !== "i4_turbo_classic")) {
      expect(classic.pulse.ampJitter).toBeGreaterThan(preset(other).pulse.ampJitter);
      expect(classic.pulse.cylinderSpread).toBeGreaterThan(preset(other).pulse.cylinderSpread);
    }
    expect(classic.camLope).not.toBeNull();
    expect(classic.turbo!.flutter.level).toBeGreaterThan(preset("i4_turbo_modern").turbo!.flutter.level);
  });

  it("só o V8 cross-plane tem 2.ª bancada (ordens meias) e compressor; nenhum outro tem whine", () => {
    expect(preset("v8_supercharged").pulse.bank).not.toBeNull();
    expect(preset("v8_supercharged").turbo).toBeNull();
    expect(preset("v8_supercharged").whine!.level).toBeLessThan(0.5);
    for (const a of ["i4_turbo_modern", "i6_turbo", "i4_turbo_classic"] as const) {
      expect(preset(a).pulse.bank).toBeNull();
      expect(preset(a).whine).toBeNull();
    }
  });

  it("banda do spool do I4 moderno é mais aguda que a do clássico e a do I6", () => {
    const at = (a: EngineArchetype) => spoolBandHz(180_000, preset(a).turbo!.spoolScale);
    expect(at("i4_turbo_modern")).toBeGreaterThan(at("i4_turbo_classic"));
    expect(at("i4_turbo_classic")).toBeGreaterThan(at("i6_turbo"));
  });

  it("lope de came do clássico: irregular na marcha lenta, nulo em alta", () => {
    const lope = preset("i4_turbo_classic").camLope;
    const idle = Array.from({ length: 40 }, (_, i) => camLopeAt(i * 0.05, 850, lope).amp);
    expect(Math.max(...idle) - Math.min(...idle)).toBeGreaterThan(0.3);
    const steps = idle.slice(1).map((v, i) => Math.abs(v - idle[i]!).toFixed(3));
    expect(new Set(steps).size).toBeGreaterThan(10);
    expect(camLopeAt(1.234, 6000, lope)).toEqual({ amp: 1, freqMul: 1 });
    expect(camLopeAt(1, 850, null)).toEqual({ amp: 1, freqMul: 1 });
    expect(camLopeAt(0.3, 850, lope).freqMul).not.toBe(1);
  });

  it("chiado da wastegate só com boost alto e pedal aberto", () => {
    expect(wastegateHissGain(250, 100, 100)).toBeCloseTo(1);
    expect(wastegateHissGain(150, 100, 100)).toBe(0);
    expect(wastegateHissGain(250, 100, 0)).toBe(0);
  });

  it("whine do compressor proporcional a rpm × polia (máx. 6 kHz) e volume pela carga", () => {
    expect(superchargerWhineHz(3000, 2.1, 6)).toBeCloseTo(630);
    expect(superchargerWhineHz(6000, 2.1, 6)).toBeCloseTo(2 * superchargerWhineHz(3000, 2.1, 6));
    expect(superchargerWhineHz(-10, 2, 6)).toBe(0);
    expect(superchargerWhineHz(20_000, 3, 8)).toBe(6000);
    expect(whineGain(200)).toBe(1);
    expect(whineGain(100)).toBeGreaterThan(whineGain(50));
    expect(whineGain(0)).toBe(0.05);
  });
});

describe("AudioEngine com arquétipo", () => {
  it("clássico: lope de came modula a AM por ignição na marcha lenta e a wastegate chia em boost alto", () => {
    const { engine, ctx } = build(I4_CLASSIC);
    for (let i = 0; i < 10; i += 1) {
      ctx.currentTime = 0.5 + i * 0.1;
      engine.update({ rpm: 850, throttlePct: 0, mapKpa: 40, baroKpa: 100, nowMs: i * 100 });
    }
    const am = ctx.gains.find((g) => g.gain.events.filter((e) => e.kind === "target").length > 20)!;
    const values = am.gain.events.map((e) => e.value);
    expect(Math.max(...values) - Math.min(...values)).toBeGreaterThan(0.1);
    engine.update({ rpm: 5500, throttlePct: 100, mapKpa: 250, baroKpa: 100, turboRpm: 180_000, nowMs: 16 });
    expect(engine.wastegateLevel).toBeGreaterThan(0);
  });

  it("I4 moderno: AM quase constante em alta (só jitter leve), sem wastegate nem compressor", () => {
    const { engine, ctx } = build(I4_MODERN);
    expect(engine.hasWhine).toBe(false);
    ctx.currentTime = 1;
    engine.update({ rpm: 6000, throttlePct: 100, mapKpa: 250, baroKpa: 100, turboRpm: 180_000, nowMs: 0 });
    const am = ctx.gains.find((g) => g.gain.events.filter((e) => e.kind === "target").length > 10)!;
    for (const e of am.gain.events) expect(Math.abs(e.value - 1)).toBeLessThanOrEqual(ARCHETYPE_PRESETS.i4_turbo_modern.pulse.ampJitter * 0.5 + 1e-9);
    expect(engine.wastegateLevel).toBe(0);
    engine.dispose();
  });
});
