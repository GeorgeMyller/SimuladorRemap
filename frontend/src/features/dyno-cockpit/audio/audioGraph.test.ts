/** 003 T007 — Grafo de áudio: cadeia do motor, corte dinâmico, turbo sem seno, pops e 1–4 kHz (RF-07 a RF-10; D-05). */
import { describe, expect, it } from "vitest";

import { ARCHETYPE_PRESETS, ENGINE_ARCHETYPES, type EngineArchetype } from "./archetypes";
import { AudioEngine, type AudioInputs, type EngineProfile } from "./AudioEngine";
import { LOWPASS_MAX_HZ, LOWPASS_MIN_HZ, MAX_POPS_PER_BURST, lowpassCutoffHz } from "./EngineSynth";
import { bandEnergyShare, biquadMagnitude, chainGainAt, engineOutputSpectrum } from "./spectrum";
import { GraphAudioContext, asNode, describeNode, downstream, firstPath, graphAudioFactory, paramOf, type GraphNode } from "./test-utils/graphContext";
import { MAX_POP_VOICES } from "./voices";

const PROFILES: Record<EngineArchetype, EngineProfile> = {
  i4_turbo_modern: { nCyl: 4, architecture: "inline", firingOrder: [1, 3, 4, 2], turbo: true, archetype: "i4_turbo_modern" },
  i6_turbo: { nCyl: 6, architecture: "inline", firingOrder: [1, 5, 3, 6, 2, 4], turbo: true, archetype: "i6_turbo" },
  i4_turbo_classic: { nCyl: 4, architecture: "inline", firingOrder: [1, 3, 4, 2], turbo: true, archetype: "i4_turbo_classic" },
  v8_supercharged: { nCyl: 8, architecture: "v", firingOrder: [1, 5, 4, 8, 6, 3, 7, 2], turbo: false, archetype: "v8_supercharged", pulleyRatio: 2.1 },
};

const IDLE: AudioInputs = { rpm: 850, throttlePct: 0, mapKpa: 35, baroKpa: 100, turboRpm: 20_000, nowMs: 0 };
const WOT: AudioInputs = { rpm: 7200, throttlePct: 100, mapKpa: 250, baroKpa: 100, turboRpm: 190_000, nowMs: 0 };

function build(archetype: EngineArchetype = "i4_turbo_modern", factory = graphAudioFactory) {
  GraphAudioContext.instances = [];
  const engine = new AudioEngine(PROFILES[archetype], { createContext: factory });
  return { engine, ctx: GraphAudioContext.instances[0]!, graph: engine.graph! };
}

const lastValue = (node: unknown, key: string) => paramOf(asNode(node), key).value;
const nonZeroSets = (node: unknown, key: string) => paramOf(asNode(node), key).events.filter((e) => e.kind === "set" && Math.abs(e.value) > 1e-3);

describe("cadeia do motor (RF-07)", () => {
  it.each(ENGINE_ARCHETYPES)("%s: pulsos → AM → drive → WaveShaper 4× → lowpass → peaking ×2 → highpass → barramento → mix", (archetype) => {
    const { graph } = build(archetype);
    const path = firstPath(asNode(graph.engine.source), asNode(graph.mix));
    expect(path?.map(describeNode)).toEqual([
      "bufferSource",
      "gain",
      "gain",
      "waveShaper",
      "biquad:lowpass",
      "biquad:peaking",
      "biquad:peaking",
      "biquad:highpass",
      "gain",
      "gain",
    ]);
    const shaper = asNode(graph.engine.shaper);
    expect(shaper.oversample).toBe("4x");
    const curve = shaper.curve as Float32Array;
    expect(curve.length).toBeGreaterThan(256);
    expect(curve.at(-1)).toBeCloseTo(1, 5);
    expect(curve[0]).toBeLessThan(-0.5);
    expect(curve[0]).toBeGreaterThan(-1); // assimetria (harmônicos pares)
    curve.slice(1).forEach((v, i) => expect(v).toBeGreaterThanOrEqual(curve[i]!));
    expect(asNode(graph.engine.source).loop).toBe(true);
  });

  it.each(ENGINE_ARCHETYPES)("%s: ressonadores do abafador em 90–140 Hz e 280–450 Hz com ganho positivo", (archetype) => {
    const { graph } = build(archetype);
    const [low, mid] = graph.engine.resonators.map(asNode);
    expect(paramOf(low!, "frequency").value).toBeGreaterThanOrEqual(90);
    expect(paramOf(low!, "frequency").value).toBeLessThanOrEqual(140);
    expect(paramOf(mid!, "frequency").value).toBeGreaterThanOrEqual(280);
    expect(paramOf(mid!, "frequency").value).toBeLessThanOrEqual(450);
    for (const r of [low!, mid!]) expect(paramOf(r, "gain").value).toBeGreaterThan(0);
  });

  it("master: corte de presença (peaking 2,2 kHz, −6 dB) → prateleira aguda → master → compressor → saída", () => {
    const { graph, ctx } = build();
    const path = firstPath(asNode(graph.mix), ctx.destination);
    expect(path?.map(describeNode)).toEqual(["gain", "biquad:peaking", "biquad:highshelf", "gain", "compressor", "destination"]);
    const cut = asNode(graph.presenceCut);
    expect(paramOf(cut, "frequency").value).toBeGreaterThanOrEqual(1000);
    expect(paramOf(cut, "frequency").value).toBeLessThanOrEqual(4000);
    expect(paramOf(cut, "gain").value).toBeLessThan(0);
    expect(paramOf(asNode(graph.highShelf), "gain").value).toBeLessThan(0);
  });

  it("sub-bass: seno no barramento do motor, cheio a 1500 rpm e mudo acima de 120 Hz (sem zumbido)", () => {
    const { engine, graph } = build("i4_turbo_modern");
    expect(asNode(graph.engine.sub).type).toBe("sine");
    expect(asNode(graph.engine.sub).outputs[0]).toBe(asNode(graph.engine.subLevel));
    expect(asNode(graph.engine.subLevel).outputs[0]).toBe(asNode(graph.engine.bus));
    engine.update({ ...IDLE, rpm: 1500, throttlePct: 30, mapKpa: 80 });
    expect(lastValue(graph.engine.sub, "frequency")).toBeCloseTo(50);
    expect(lastValue(graph.engine.subLevel, "gain")).toBeGreaterThan(0.05);
    engine.update({ ...WOT, rpm: 6000 });
    expect(lastValue(graph.engine.subLevel, "gain")).toBe(0);
  });

  it("taxa do laço de pulsos segue o RPM (3000 rpm = 1×, 6000 rpm = 2×) por setTargetAtTime", () => {
    const { engine, graph } = build();
    engine.update({ ...WOT, rpm: 3000 });
    expect(lastValue(graph.engine.source, "playbackRate")).toBeCloseTo(1);
    engine.update({ ...WOT, rpm: 6000 });
    expect(lastValue(graph.engine.source, "playbackRate")).toBeCloseTo(2);
    for (const [node, key] of [
      [graph.engine.source, "playbackRate"],
      [graph.engine.lowpass, "frequency"],
      [graph.engine.bus, "gain"],
      [graph.engine.drive, "gain"],
    ] as const) {
      expect(paramOf(asNode(node), key).events.every((e) => e.kind === "target")).toBe(true);
    }
  });
});

describe("passa-baixa dinâmico 180 → 1400 Hz (RF-07)", () => {
  it("é contínuo e monotônico em rpm e em carga, com extremos 180 e 1400 Hz", () => {
    expect(lowpassCutoffHz(700, 0)).toBeCloseTo(LOWPASS_MIN_HZ);
    expect(lowpassCutoffHz(7200, 1)).toBeCloseTo(LOWPASS_MAX_HZ);
    for (let load = 0; load <= 1; load += 0.1) {
      let prev = 0;
      for (let rpm = 500; rpm <= 8000; rpm += 250) {
        const hz = lowpassCutoffHz(rpm, load);
        expect(hz).toBeGreaterThanOrEqual(prev);
        expect(hz - prev).toBeLessThan(prev === 0 ? Infinity : 80); // sem saltos
        prev = hz;
      }
    }
    for (let rpm = 500; rpm <= 8000; rpm += 500) {
      let prev = 0;
      for (let load = 0; load <= 1.0001; load += 0.05) {
        const hz = lowpassCutoffHz(rpm, load, 1.12);
        expect(hz).toBeGreaterThanOrEqual(prev);
        expect(hz).toBeGreaterThanOrEqual(LOWPASS_MIN_HZ - 1e-9);
        expect(hz).toBeLessThanOrEqual(LOWPASS_MAX_HZ + 1e-9);
        prev = hz;
      }
    }
  });

  it.each(ENGINE_ARCHETYPES)("%s: corte no grafo sobe da marcha lenta (≈180 Hz) até WOT (1400 Hz)", (archetype) => {
    const { engine, graph } = build(archetype);
    const cutoffs = [IDLE, { ...IDLE, rpm: 2500, throttlePct: 25, mapKpa: 70 }, { ...WOT, rpm: 4500, throttlePct: 70, mapKpa: 170 }, WOT].map((input) => {
      engine.update(input);
      return lastValue(graph.engine.lowpass, "frequency");
    });
    expect(cutoffs[0]).toBeLessThan(200);
    expect(cutoffs.at(-1)).toBeCloseTo(1400);
    cutoffs.slice(1).forEach((hz, i) => expect(hz).toBeGreaterThan(cutoffs[i]!));
    expect(engine.cutoffHz).toBeCloseTo(1400);
  });
});

describe("turbo por ruído de banda estreita (RF-08)", () => {
  const turboArchetypes = ENGINE_ARCHETYPES.filter((a) => PROFILES[a].turbo);

  it.each(turboArchetypes)("%s: nenhum OscillatorNode alcança o barramento do turbo; o único seno contínuo do motor é o sub", (archetype) => {
    const { ctx, graph } = build(archetype);
    const turboBus = asNode(graph.turbo!.bus);
    const oscillators = ctx.ofKind("oscillator");
    for (const osc of oscillators) expect(downstream(osc).has(turboBus)).toBe(false);
    const continuousSines = oscillators.filter((o) => o.type === "sine" && o.started !== null && o.stopped === null);
    const popPunches = graph.pops.voices.map((v) => asNode(v.punch));
    expect(continuousSines.filter((o) => !popPunches.includes(o))).toEqual([asNode(graph.engine.sub)]);
    const feeders = ctx.nodes.filter((n) => n.outputs.some((o) => downstream(o).has(turboBus) || o === turboBus));
    expect(feeders.some((n) => n.kind === "bufferSource")).toBe(true);
  });

  it("spool: banda (Q moderado) segue turbo_rpm; harmônico agudo em ~2× com Q alto e nível muito discreto", () => {
    const { engine, graph } = build("i4_turbo_modern");
    const turbo = graph.turbo!;
    const q = paramOf(asNode(turbo.spoolFilter), "Q").value;
    expect(q).toBeGreaterThanOrEqual(1.5);
    expect(q).toBeLessThanOrEqual(4);
    engine.update({ ...WOT, turboRpm: 80_000 });
    const low = lastValue(turbo.spoolFilter, "frequency");
    engine.update({ ...WOT, turboRpm: 180_000 });
    const high = lastValue(turbo.spoolFilter, "frequency");
    expect(high).toBeGreaterThan(low);
    expect(lastValue(turbo.harmonicFilter, "frequency")).toBeCloseTo(high * 2.1);
    expect(paramOf(asNode(turbo.harmonicFilter), "Q").value).toBeGreaterThan(q * 3);
    const levels = turboLevels(turbo.harmonicFilter, turbo.spoolFilter);
    expect(levels.harmonic).toBeLessThan(levels.spool * 0.15);
    expect(levels.spool).toBeGreaterThan(0);
  });

  it("sem turbo_rpm estima a rotação pelo boost; turbo_rpm = 0 silencia o spool", () => {
    const { engine, graph } = build("i6_turbo");
    engine.update({ ...WOT, turboRpm: null });
    expect(graph.turbo!.spoolHz).toBeGreaterThan(350);
    expect(turboLevels(graph.turbo!.harmonicFilter, graph.turbo!.spoolFilter).spool).toBeGreaterThan(0);
    engine.update({ ...WOT, turboRpm: 0 });
    expect(turboLevels(graph.turbo!.harmonicFilter, graph.turbo!.spoolFilter).spool).toBe(0);
  });

  it("fechar a borboleta com boost dispara blow-off (banda + envelope) e flutter/chirp com pulsos decrescentes", () => {
    const { engine, graph, ctx } = build("i4_turbo_classic");
    ctx.currentTime = 2;
    engine.update({ ...WOT, nowMs: 0 });
    engine.update({ ...WOT, throttlePct: 5, nowMs: 100 });
    expect(engine.blowoffCount).toBe(1);
    expect(engine.flutterCount).toBe(1);
    expect(asNode(graph.turbo!.flutterFilter).type).toBe("bandpass");
    const flutterGain = asNode(graph.turbo!.flutterFilter).outputs[0]!;
    const peaks = paramOf(flutterGain, "gain").events.filter((e) => e.kind === "target" && e.value > 0).map((e) => e.value);
    expect(peaks.length).toBe(5);
    peaks.slice(1).forEach((p, i) => expect(p).toBeLessThan(peaks[i]!));
    const chirp = paramOf(asNode(graph.turbo!.flutterFilter), "frequency").events.filter((e) => e.kind === "target").map((e) => e.value);
    expect(chirp.at(-1)).toBeLessThan(chirp[0]!);
    expect(nonZeroSets(flutterGain, "gain")).toEqual([]);
    engine.update({ ...WOT, throttlePct: 0, nowMs: 150 });
    expect(engine.blowoffCount).toBe(1);
  });

  it("V8 com compressor: whine por banda estreita (Q alto) em rpm × polia × lóbulos, sem oscilador", () => {
    const { engine, graph } = build("v8_supercharged");
    expect(graph.turbo).toBeNull();
    const whine = graph.whine!;
    expect(asNode(whine.source).kind).toBe("bufferSource");
    expect(paramOf(asNode(whine.filter), "Q").value).toBeGreaterThanOrEqual(6);
    engine.update({ ...IDLE, rpm: 3000, throttlePct: 30, mapKpa: 60 });
    const low = lastValue(whine.filter, "frequency");
    const lowGain = engine.whineLevel;
    engine.update({ ...WOT, rpm: 6000, mapKpa: 190 });
    expect(lastValue(whine.filter, "frequency")).toBeCloseTo(2 * low);
    expect(engine.whineLevel).toBeGreaterThan(lowGain);
    expect(engine.whineLevel).toBeLessThanOrEqual(ARCHETYPE_PRESETS.v8_supercharged.whine!.level);
    engine.update({ ...WOT, throttlePct: 0, nowMs: 100 });
    expect(engine.blowoffCount).toBe(0); // sem turbo, sem blow-off
  });
});

describe("pops & bangs (RF-09)", () => {
  it("cadeia: punch senoidal 90–160 Hz com queda de pitch + corpo grave + estalo em passa-banda → reverb curto", () => {
    const { engine, graph, ctx } = build("i4_turbo_classic");
    ctx.currentTime = 1;
    engine.pops(3, 77);
    expect(engine.popCount).toBe(3);
    const used = graph.pops.voices.filter((v) => paramOf(asNode(v.punch), "frequency").events.length > 0);
    expect(used).toHaveLength(3);
    for (const v of used) {
      const freq = paramOf(asNode(v.punch), "frequency").events.filter((e) => e.kind !== "cancel");
      expect(freq[0]!.kind).toBe("set");
      expect(freq[1]!.kind).toBe("target");
      for (const e of freq) {
        expect(e.value).toBeGreaterThanOrEqual(90);
        expect(e.value).toBeLessThanOrEqual(160);
      }
      expect(freq[1]!.value).toBeLessThan(freq[0]!.value);
      for (const level of [v.punchLevel, v.bodyLevel, v.crackLevel]) {
        expect(nonZeroSets(level, "gain")).toEqual([]); // ataque por constante de tempo: sem cliques
        expect(paramOf(asNode(level), "gain").events.some((e) => e.kind === "target" && e.value > 0)).toBe(true);
      }
      const crackFilter = ctx.nodes.find((n) => n.outputs.includes(asNode(v.crackLevel)))!;
      expect(describeNode(crackFilter)).toBe("biquad:bandpass");
      expect(paramOf(crackFilter, "Q").value).toBeGreaterThanOrEqual(2);
      const bodyFilter = ctx.nodes.find((n) => n.outputs.includes(asNode(v.bodyLevel)))!;
      expect(describeNode(bodyFilter)).toBe("biquad:lowpass");
      expect(paramOf(bodyFilter, "frequency").value).toBeLessThan(1000);
    }
    const reach = downstream(asNode(graph.pops.bus));
    expect(reach.has(asNode(graph.reverb!.input))).toBe(true);
    expect(asNode(graph.reverb!.input).kind).toBe("convolver");
    expect((asNode(graph.reverb!.input).buffer as { length: number }).length).toBeGreaterThan(0);
    expect(reach.has(asNode(graph.mix))).toBe(true);
  });

  it("limita vozes e rajadas: nenhum nó novo, no máximo MAX_POPS_PER_BURST por rajada", () => {
    const { engine, ctx } = build("v8_supercharged");
    const nodes = ctx.nodes.length;
    engine.pops(50, 1);
    expect(engine.popCount).toBeLessThanOrEqual(Math.min(MAX_POPS_PER_BURST, 50));
    for (let i = 0; i < 20; i += 1) engine.pops(6, 100 + i);
    expect(engine.popCount).toBeLessThan(6 * 21);
    expect(ctx.nodes.length).toBe(nodes);
    expect(ctx.ofKind("oscillator").filter((o) => o.type === "sine")).toHaveLength(MAX_POP_VOICES + 1);
  });

  it("sem ConvolverNode usa eco de realimentação baixa; sem WaveShaper usa ganho unitário", () => {
    const limited = () => {
      const ctx = new GraphAudioContext();
      return Object.assign(ctx, { createConvolver: undefined, createWaveShaper: undefined }) as unknown as AudioContext;
    };
    GraphAudioContext.instances = [];
    const engine = new AudioEngine(PROFILES.i4_turbo_modern, { createContext: limited });
    const graph = engine.graph!;
    expect(asNode(graph.engine.shaper).kind).toBe("gain");
    const delay = asNode(graph.reverb!.input);
    expect(delay.kind).toBe("delay");
    expect(downstream(delay).has(delay)).toBe(true); // realimentação
    const feedback = [...downstream(delay)].find((n) => n.kind === "gain" && n.outputs.includes(delay))!;
    expect(paramOf(feedback, "gain").value).toBeLessThan(0.3);
    engine.pops(2, 5);
    expect(engine.popCount).toBe(2);
  });
});

describe("desempenho e estado", () => {
  it("nenhuma alocação de nós por frame e AM por ignição suave (setTargetAtTime)", () => {
    const { engine, ctx, graph } = build("i6_turbo");
    const nodes = ctx.nodes.length;
    for (let i = 0; i < 120; i += 1) {
      ctx.currentTime = i / 60;
      engine.update({ ...WOT, rpm: 2000 + i * 40, nowMs: i * 16 });
    }
    expect(ctx.nodes.length).toBe(nodes);
    const am = paramOf(asNode(graph.engine.pulseAm), "gain").events;
    expect(am.length).toBeGreaterThan(100);
    expect(am.every((e) => e.kind === "target")).toBe(true);
  });

  it("quebra: impacto 60 Hz + metal 3 kHz e silêncio do motor e do turbo; reparo volta a sintetizar", () => {
    const { engine, ctx, graph } = build("i4_turbo_classic");
    engine.update(WOT);
    engine.breakage();
    engine.breakage();
    expect(ctx.ofKind("oscillator").filter((o) => paramOf(o, "frequency").value === 60)).toHaveLength(1);
    expect(ctx.ofKind("biquad").some((f) => f.type === "bandpass" && paramOf(f, "frequency").value === 3000)).toBe(true);
    expect(lastValue(graph.engine.bus, "gain")).toBe(0);
    expect(engine.wastegateLevel).toBe(0);
    engine.update(WOT);
    expect(lastValue(graph.engine.bus, "gain")).toBe(0);
    engine.pops(3, 9);
    engine.triggerBlowoff();
    expect(engine.popCount).toBe(0);
    engine.repair();
    engine.update(WOT);
    expect(lastValue(graph.engine.bus, "gain")).toBeGreaterThan(0);
    engine.dispose();
    expect(ctx.state).toBe("closed");
    expect(asNode(graph.engine.source).stopped).not.toBeNull();
  });
});

describe("energia em 1–4 kHz por arquétipo (RF-10)", () => {
  const POINTS: [number, number][] = [
    [850, 0.05],
    [2500, 0.3],
    [4500, 0.7],
    [7000, 1],
    [7000, 0.05],
  ];
  const MAX_SHARE = 0.05;

  it.each(ENGINE_ARCHETYPES)("%s: soma em 1–4 kHz < 5 % da energia em todos os pontos de operação", (archetype) => {
    for (const [rpm, load] of POINTS) expect(bandEnergyShare(archetype, rpm, load)).toBeLessThan(MAX_SHARE);
  });

  it.each(ENGINE_ARCHETYPES)("%s: ganho da cadeia em 2 kHz ≥ 12 dB abaixo do ressonador grave, mesmo em WOT", (archetype) => {
    const low = chainGainAt(archetype, 110, 7000, 1);
    const presence = chainGainAt(archetype, 2000, 7000, 1);
    expect(20 * Math.log10(presence / low)).toBeLessThan(-12);
    expect(chainGainAt(archetype, 1000, 850, 0)).toBeLessThan(0.05); // marcha lenta escura
  });

  it("energia de saída concentrada abaixo de 1 kHz e o V8 cross-plane tem mais ordem meia que o I6", () => {
    const halfOrderShare = (archetype: EngineArchetype, rpm: number) => {
      const nCyl = PROFILES[archetype].nCyl;
      const half = ((rpm / 60) * (nCyl / 2)) / 2;
      const lines = engineOutputSpectrum(archetype, rpm, 0.6);
      const total = lines.reduce((s, l) => s + l.power, 0);
      return lines.filter((l) => Math.abs(l.hz - half) < 2).reduce((s, l) => s + l.power, 0) / total;
    };
    expect(halfOrderShare("v8_supercharged", 3000)).toBeGreaterThan(halfOrderShare("i6_turbo", 3000) * 3);
    expect(bandEnergyShare("i6_turbo", 7000, 1, 0, 1000)).toBeGreaterThan(0.9);
  });

  it("biquad RBJ: passa-baixa −3 dB no corte (Q −3 dB) e peaking com o ganho pedido no centro", () => {
    expect(20 * Math.log10(biquadMagnitude({ kind: "lowpass", hz: 1000, q: -3.0103 }, 1000))).toBeCloseTo(-3.01, 1);
    expect(20 * Math.log10(biquadMagnitude({ kind: "peaking", hz: 120, q: 1.4, gainDb: 4 }, 120))).toBeCloseTo(4, 3);
    expect(20 * Math.log10(biquadMagnitude({ kind: "highshelf", hz: 4500, q: 0, gainDb: -6 }, 20_000))).toBeCloseTo(-6, 0);
    expect(biquadMagnitude({ kind: "bandpass", hz: 800, q: 2 }, 800)).toBeCloseTo(1, 3);
    expect(biquadMagnitude({ kind: "highpass", hz: 24, q: -3 }, 5)).toBeLessThan(0.1);
  });
});

/** Níveis-alvo atuais (ganho a jusante do filtro) do spool e do harmônico agudo. */
function turboLevels(harmonicFilter: unknown, spoolFilter: unknown) {
  const levelOf = (filter: unknown) => paramOf(asNode(filter).outputs[0] as GraphNode, "gain").value;
  return { harmonic: levelOf(harmonicFilter), spool: levelOf(spoolFilter) };
}
