/** T185 / 003 T007 — Matemática da síntese e ciclo de vida do AudioEngine (RF-18, RF-19; 003 RF-07 a RF-09; D-23, D-05). */
import { describe, expect, it } from "vitest";

import { FakeAudioContext, fakeAudioFactory } from "../test-utils/mocks";

import { ARCHETYPE_PRESETS } from "./archetypes";
import { AudioEngine, presetFor } from "./AudioEngine";
import {
  BlowoffDetector,
  MAX_POPS_PER_BURST,
  driveFor,
  engineLevel,
  engineLoad,
  envelopeAt,
  estimatedTurboRpm,
  firingFrequencyHz,
  firingPulseGains,
  overrunPopPlan,
  playbackRateFor,
  popPunchHz,
  saturate,
  saturationCurve,
  spoolBandHz,
  spoolGain,
  subLevel,
} from "./EngineSynth";
import { LOOP_CYCLES, exhaustCycle, pinkNoise, samplesPerCycle, shortImpulseResponse } from "./waveforms";

const i4 = { nCyl: 4, architecture: "inline" as const, firingOrder: [1, 3, 4, 2], turbo: true };

function engineWithCtx(profile = i4) {
  FakeAudioContext.instances = [];
  const engine = new AudioEngine(profile, { createContext: fakeAudioFactory });
  const ctx = FakeAudioContext.instances[0]!;
  return { engine, ctx };
}

describe("EngineSynth", () => {
  it("4 cilindros a 6000 rpm → fundamental de ignição 200 Hz ± 1 Hz; V8 a 6000 rpm → 400 Hz", () => {
    expect(Math.abs(firingFrequencyHz(6000, 4) - 200)).toBeLessThanOrEqual(1);
    expect(firingFrequencyHz(6000, 8)).toBe(400);
    expect(firingFrequencyHz(-5, 4)).toBe(0);
  });

  it("taxa do laço: ciclo de 720° (rpm/120) sobre 25 Hz; nunca zero", () => {
    expect(playbackRateFor(3000)).toBeCloseTo(1);
    expect(playbackRateFor(850)).toBeCloseTo(850 / 3000);
    expect(playbackRateFor(0)).toBeGreaterThan(0);
  });

  it("irregularidade ±8 % por pulso na sequência da ordem de ignição", () => {
    const g = firingPulseGains([1, 3, 4, 2]);
    expect(g).toHaveLength(4);
    for (const v of g) expect(Math.abs(v - 1)).toBeLessThanOrEqual(0.08 + 1e-9);
    expect(new Set(g.map((v) => v.toFixed(4))).size).toBeGreaterThan(1);
    expect(firingPulseGains([1, 2, 3, 4])).not.toEqual(g);
    expect(firingPulseGains([1])).toEqual([1]);
  });

  it("carga combina borboleta e MAP; nível e drive sobem com a carga", () => {
    expect(engineLoad(0, 25, 100)).toBe(0);
    expect(engineLoad(100, 200, 100)).toBeCloseTo(1);
    expect(engineLoad(50, 100, 100)).toBeGreaterThan(engineLoad(20, 100, 100));
    expect(engineLoad(50, 150, 100)).toBeGreaterThan(engineLoad(50, 100, 100));
    expect(engineLevel(0, 1)).toBe(0);
    expect(engineLevel(3000, 1)).toBeGreaterThan(engineLevel(3000, 0.2));
    expect(engineLevel(7200, 1)).toBeCloseTo(1);
    expect(driveFor(0.5, 0.5, 1)).toBeCloseTo(0.75);
    expect(driveFor(2, 0.5, 1)).toBe(1);
  });

  it("sub-bass: janela 22–120 Hz, cheio entre 35 e 60 Hz", () => {
    expect(subLevel(15, 1)).toBe(0);
    expect(subLevel(45, 1)).toBeCloseTo(1);
    expect(subLevel(45, 0)).toBeCloseTo(0.5);
    expect(subLevel(90, 1)).toBeCloseTo(0.5);
    expect(subLevel(130, 1)).toBe(0);
  });

  it("saturação tanh assimétrica: f(0) = 0, f(1) = 1, monotônica, |f(−1)| < 1, entrada presa", () => {
    expect(saturate(0, 2, 0.2)).toBeCloseTo(0);
    expect(saturate(1, 2, 0.2)).toBeCloseTo(1);
    expect(saturate(5, 2, 0.2)).toBeCloseTo(1);
    expect(Math.abs(saturate(-1, 2, 0.2))).toBeLessThan(1);
    expect(saturate(-1, 2, 0)).toBeCloseTo(-1);
    const curve = saturationCurve(2.4, 0.9, 64);
    curve.slice(1).forEach((v, i) => expect(v).toBeGreaterThanOrEqual(curve[i]!));
  });

  it("spool: ganho (map − baro) / 150 e banda turbo_rpm/60 · 0,4 · escala em 350..3200 Hz", () => {
    expect(spoolGain(250, 100)).toBeCloseTo(1);
    expect(spoolGain(175, 100)).toBeCloseTo(0.5);
    expect(spoolGain(80, 100)).toBe(0);
    expect(spoolBandHz(150_000, 1)).toBeCloseTo(1000);
    expect(spoolBandHz(0, 1)).toBe(350);
    expect(spoolBandHz(9e6, 2)).toBe(3200);
    expect(estimatedTurboRpm(250, 100)).toBe(180_000);
    expect(estimatedTurboRpm(90, 100)).toBe(60_000);
  });

  it("detector de fechamento dispara uma vez por fechamento da borboleta com boost > 0,5 bar", () => {
    const d = new BlowoffDetector();
    expect(d.update(0, 100, 1.2)).toBe(false);
    expect(d.update(100, 40, 1.2)).toBe(true);
    expect(d.update(150, 10, 1.2)).toBe(false); // mesmo fechamento
    expect(d.update(1500, 100, 1.2)).toBe(false);
    expect(d.update(1600, 20, 0.3)).toBe(false); // boost baixo
    expect(d.update(3000, 100, 1.2)).toBe(false);
    expect(d.update(3150, 30, 1.2)).toBe(true);
    // queda lenta (> 200 ms) não dispara
    const slow = new BlowoffDetector();
    slow.update(0, 100, 1.2);
    slow.update(150, 80, 1.2);
    slow.update(300, 60, 1.2);
    expect(slow.update(450, 40, 1.2)).toBe(false);
  });

  it("rajada de pops semeada por seq (determinística), limitada, espaçada 45–120 ms, punch em 90–160 Hz", () => {
    const a = overrunPopPlan(1907, 3);
    expect(a).toEqual(overrunPopPlan(1907, 3));
    expect(a).not.toEqual(overrunPopPlan(1908, 3));
    expect(overrunPopPlan(1, 40)).toHaveLength(MAX_POPS_PER_BURST);
    expect(overrunPopPlan(1, -2)).toEqual([]);
    a.slice(1).forEach((p, i) => {
      const gap = p.delayS - a[i]!.delayS;
      expect(gap).toBeGreaterThanOrEqual(0.045);
      expect(gap).toBeLessThanOrEqual(0.12);
    });
    for (const p of a) {
      const { startHz, endHz } = popPunchHz(p.pitchMul);
      expect(startHz).toBeLessThanOrEqual(160);
      expect(endHz).toBeGreaterThanOrEqual(90);
      expect(endHz).toBeLessThan(startHz);
      expect(p.decayS).toBeLessThan(0.05);
    }
    expect(envelopeAt(15, 30, 400)).toBeCloseTo(0.5);
    expect(envelopeAt(230, 30, 400)).toBeCloseTo(0.5);
    expect(envelopeAt(-1, 30, 400)).toBe(0);
  });
});

describe("formas de onda", () => {
  it("laço de pulsos: 12 ciclos, sem DC, pico 0,9, determinístico e com jitter entre ciclos", () => {
    const pulse = ARCHETYPE_PRESETS.i4_turbo_classic.pulse;
    const data = exhaustCycle({ pulse, firingOrder: [1, 3, 4, 2], sampleRate: 8000 });
    const per = samplesPerCycle(8000);
    expect(data.length).toBe(per * LOOP_CYCLES);
    const mean = data.reduce((s, v) => s + v, 0) / data.length;
    expect(Math.abs(mean)).toBeLessThan(1e-6);
    expect(Math.max(...data.map(Math.abs))).toBeCloseTo(0.9, 5);
    expect(exhaustCycle({ pulse, firingOrder: [1, 3, 4, 2], sampleRate: 8000 })).toEqual(data);
    const c0 = data.slice(0, per);
    const c1 = data.slice(per, 2 * per);
    expect(c0).not.toEqual(c1);
    const empty = exhaustCycle({ pulse, firingOrder: [], sampleRate: 8000, cycles: 1 });
    expect(empty.length).toBe(per);
  });

  it("ruído rosa e resposta impulsiva curta (fade-in, decaimento)", () => {
    const noise = pinkNoise(4000);
    expect(Math.max(...noise.map(Math.abs))).toBeLessThan(1);
    const ir = shortImpulseResponse(8000);
    expect(ir.length).toBe(Math.round(8000 * 0.32));
    expect(ir[0]).toBe(0);
    const energy = (from: number, to: number) => ir.slice(from, to).reduce((s, v) => s + v * v, 0);
    expect(energy(0, 400)).toBeGreaterThan(energy(2000, 2400) * 10);
  });
});

describe("AudioEngine", () => {
  it("sem gesto o AudioContext fica suspended; enable() (clique 'Ativar som') passa a running", async () => {
    const { engine, ctx } = engineWithCtx();
    expect(engine.state).toBe("suspended");
    expect(ctx.resume).not.toHaveBeenCalled();
    await engine.enable();
    expect(engine.state).toBe("running");
    await engine.suspend();
    expect(engine.state).toBe("suspended");
    await ctx.close();
    expect(engine.state).toBe("closed");
  });

  it("funciona com o mock mínimo (sem WaveShaper, Convolver, Delay nem playbackRate)", () => {
    const { engine, ctx } = engineWithCtx();
    expect(() => {
      engine.update({ rpm: 6000, throttlePct: 100, mapKpa: 200, baroKpa: 100, turboRpm: 180_000, nowMs: 0 });
      engine.update({ rpm: 6000, throttlePct: 0, mapKpa: 200, baroKpa: 100, turboRpm: 180_000, nowMs: 100 });
      engine.pops(2, 77);
    }).not.toThrow();
    expect(Math.abs(engine.fundamentalHz - 200)).toBeLessThanOrEqual(1);
    expect(engine.blowoffCount).toBe(1);
    expect(engine.popCount).toBe(2);
    expect(engine.graph?.reverb).toBeNull();
    expect(ctx.filters.some((f) => f.type === "lowpass" && Math.abs(f.frequency.value - engine.cutoffHz) < 1e-6)).toBe(true);
    expect(ctx.oscillators.every((o) => o.type === "sine")).toBe(true);
  });

  it("compressor suave, volume padrão 60 % e mudo por rampa", () => {
    const { engine, ctx } = engineWithCtx();
    expect(ctx.compressor?.threshold.value).toBe(-8);
    expect(engine.currentVolume).toBe(0.6);
    const master = engine.graph!.master as unknown as FakeAudioContext["gains"][number];
    expect(master.gain.value).toBe(0.6);
    engine.setMuted(true);
    expect(engine.isMuted).toBe(true);
    expect(master.gain.value).toBe(0);
    expect(master.gain.events.at(-1)?.kind).toBe("target");
    engine.setMuted(false);
    engine.setVolume(1.4);
    expect(master.gain.value).toBe(1);
    engine.setVolume(-1);
    expect(engine.currentVolume).toBe(0);
  });

  it("estado inicial mudo e volume pelas opções", () => {
    FakeAudioContext.instances = [];
    const engine = new AudioEngine(i4, { createContext: fakeAudioFactory, muted: true, volume: 0.3 });
    expect((engine.graph!.master as unknown as FakeAudioContext["gains"][number]).gain.value).toBe(0);
    expect(engine.currentVolume).toBe(0.3);
  });

  it("sem Web Audio fica 'unavailable' e não lança; contagens seguem", async () => {
    const engine = new AudioEngine(i4, { createContext: null });
    expect(engine.state).toBe("unavailable");
    expect(engine.graph).toBeNull();
    expect(await engine.enable()).toBe("unavailable");
    await engine.suspend();
    engine.setVolume(0.2);
    expect(() => engine.update({ rpm: 3000, throttlePct: 50, mapKpa: 100, baroKpa: 100, nowMs: 0 })).not.toThrow();
    expect(engine.fundamentalHz).toBe(100);
    engine.pops(2, 3);
    expect(engine.popCount).toBe(2);
    engine.triggerBlowoff();
    expect(engine.blowoffCount).toBe(1);
    expect(engine.wastegateLevel).toBe(0);
    expect(engine.whineLevel).toBe(0);
    engine.breakage();
    engine.dispose();
  });

  it("mock global (compressor sem parâmetros) e grafo que falha não lançam", async () => {
    const { MockAudioContext } = await import("@/test/mocks");
    const engine = new AudioEngine(i4, { createContext: () => new MockAudioContext() as unknown as AudioContext });
    expect(engine.graph).not.toBeNull();
    expect(() => engine.update({ rpm: 4000, throttlePct: 80, mapKpa: 180, baroKpa: 100, turboRpm: 150_000, nowMs: 0 })).not.toThrow();
    engine.pops(3, 4);
    expect(engine.popCount).toBe(3);
    const broken = new AudioEngine(i4, {
      createContext: () =>
        Object.assign(new MockAudioContext(), {
          createBiquadFilter: () => {
            throw new Error("sem biquad");
          },
        }) as unknown as AudioContext,
    });
    expect(broken.state).toBe("suspended");
    expect(broken.graph).toBeNull();
    expect(() => broken.update({ rpm: 4000, throttlePct: 80, mapKpa: 180, baroKpa: 100, nowMs: 0 })).not.toThrow();
    broken.setMuted(true);
    broken.dispose();
  });

  it("fábrica que lança vira 'unavailable'", () => {
    const engine = new AudioEngine(i4, {
      createContext: () => {
        throw new Error("bloqueado");
      },
    });
    expect(engine.state).toBe("unavailable");
  });

  it("preset: arquétipo inferido pela arquitetura; cambota plana remove a 2.ª bancada", () => {
    expect(presetFor(i4)).toBe(ARCHETYPE_PRESETS.i4_turbo_modern);
    const flat = presetFor({ nCyl: 8, architecture: "v", firingOrder: [1, 8, 4, 3, 6, 5, 7, 2], turbo: true, crossPlane: false });
    expect(flat.pulse.bank).toBeNull();
    expect(flat.tone).toBe(ARCHETYPE_PRESETS.v8_supercharged.tone);
    expect(presetFor({ nCyl: 6, architecture: "inline", firingOrder: [1, 5, 3, 6, 2, 4], turbo: true, crossPlane: false })).toBe(ARCHETYPE_PRESETS.i6_turbo);
    FakeAudioContext.instances = [];
    const v8turbo = new AudioEngine({ nCyl: 8, architecture: "v", firingOrder: [1, 5, 4, 8, 6, 3, 7, 2], turbo: true }, { createContext: fakeAudioFactory });
    expect(v8turbo.graph?.turbo).not.toBeNull(); // voz de turbo padrão
    expect(v8turbo.hasWhine).toBe(true);
  });
});
