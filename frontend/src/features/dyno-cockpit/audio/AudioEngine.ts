/**
 * Síntese Web Audio do motor (001 RF-18, RF-19; 002 RF-20; 003 RF-07 a RF-10; D-05).
 *
 * Cadeia do motor (nós criados uma vez):
 *   laço de pulsos de exaustão (AudioBufferSourceNode, playbackRate = rpm/120 ÷ 25 Hz)
 *   → AM por ignição (lope/jitter) → drive → WaveShaper (tanh assimétrica, 4×)
 *   → passa-baixa dinâmico 180→1400 Hz → ressonador grave → ressonador médio → passa-alta 24 Hz
 *   → barramento do motor (+ sub-bass senoidal por amplitude)
 *   → mix (+ turbo, whine, pops com reverb curto) → corte de presença 2,2 kHz → prateleira 4,5 kHz
 *   → master (mudo/volume) → compressor → saída.
 * Parâmetros contínuos mudam só com `setTargetAtTime` (sem zipper noise). Desligado até o 1.º
 * gesto do usuário (`AudioContext` fica `suspended`).
 */
import { boostBar } from "@/lib/units";

import { mulberry32 } from "../flashGuard";

import { ARCHETYPE_PRESETS, DEFAULT_TURBO, archetypeFor, type ArchetypePreset, type Architecture, type EngineArchetype, type TurboVoice } from "./archetypes";
import {
  BlowoffDetector,
  MASTER_HIGH_SHELF,
  MASTER_PRESENCE_CUT,
  RUMBLE_HIGHPASS_HZ,
  camLopeAt,
  driveFor,
  engineLevel,
  engineLoad,
  firingFrequencyHz,
  lowpassCutoffHz,
  overrunPopPlan,
  playbackRateFor,
  saturationCurve,
  subLevel,
} from "./EngineSynth";
import { bufferFrom, chain, filterNode, gainNode, loopSource, paramOf, shaperNode, shortReverb, smooth, stopAll, type Ctx } from "./graph";
import { PopVoices, TurboSound, WhineSound } from "./voices";
import { exhaustCycle, pinkNoise, shortImpulseResponse } from "./waveforms";

export interface EngineProfile {
  nCyl: number;
  architecture: Architecture;
  firingOrder: readonly number[];
  turbo: boolean;
  crossPlane?: boolean;
  /** Timbre por arquétipo; ausente = arquétipo inferido pela arquitetura. */
  archetype?: EngineArchetype;
  /** Razão da polia do compressor mecânico (whine do V8). */
  pulleyRatio?: number;
}

export interface AudioInputs {
  rpm: number;
  turboRpm?: number | null;
  throttlePct: number;
  mapKpa: number;
  baroKpa: number;
  nowMs: number;
}

export type AudioState = "unavailable" | "suspended" | "running" | "closed";

export type AudioContextFactory = () => AudioContext;

export function defaultAudioContextFactory(): AudioContextFactory | null {
  const Ctor =
    typeof window !== "undefined"
      ? (window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext)
      : undefined;
  return Ctor ? () => new Ctor() : null;
}

const ENGINE_LEVEL = 0.32;
const REVERB_SEND = 0.18;
const PULSE_HORIZON_S = 0.1;
const POP_HORIZON_S = 0.6;
const NOISE_SECONDS = 2;
const COMPRESSOR_SETTINGS = [
  ["threshold", -8],
  ["knee", 6],
  ["ratio", 6],
  ["attack", 0.004],
  ["release", 0.15],
] as const;

/** Preset efetivo: arquétipo declarado ou inferido; cambota plana remove a 2.ª bancada. */
export function presetFor(profile: EngineProfile): ArchetypePreset {
  const base = ARCHETYPE_PRESETS[profile.archetype ?? archetypeFor(null, profile)];
  if (profile.crossPlane !== false || base.pulse.bank === null) return base;
  return { ...base, pulse: { ...base.pulse, bank: null } };
}

interface EngineChain {
  source: AudioBufferSourceNode;
  pulseAm: GainNode;
  drive: GainNode;
  shaper: AudioNode;
  lowpass: BiquadFilterNode;
  resonators: [BiquadFilterNode, BiquadFilterNode];
  bus: GainNode;
  sub: OscillatorNode;
  subLevel: GainNode;
}

/** Nós principais expostos para diagnóstico e testes do grafo. */
export interface GraphTaps {
  master: GainNode;
  mix: GainNode;
  presenceCut: BiquadFilterNode;
  highShelf: BiquadFilterNode;
  engine: EngineChain;
  turbo: TurboSound | null;
  whine: WhineSound | null;
  pops: PopVoices;
  reverb: { input: AudioNode; output: AudioNode } | null;
}

export class AudioEngine {
  readonly ctx: AudioContext | null;
  private readonly profile: EngineProfile;
  private readonly preset: ArchetypePreset;
  private readonly turboVoice: TurboVoice | null;
  private taps: GraphTaps | null = null;
  private noise: AudioBuffer | null = null;
  private readonly blowoff = new BlowoffDetector();
  private readonly jitter = mulberry32(0xa11ce);
  private nextPulseAt = 0;
  private popClock = 0;
  private lastRpm = 0;
  private muted: boolean;
  private volume: number;
  private broken = false;
  /** Diagnóstico: frequência de ignição (Hz), carga 0..1 e corte atual do passa-baixa (Hz). */
  fundamentalHz = 0;
  load = 0;
  cutoffHz = 0;
  blowoffCount = 0;
  flutterCount = 0;
  popCount = 0;

  constructor(profile: EngineProfile, options: { createContext?: AudioContextFactory | null; muted?: boolean; volume?: number } = {}) {
    this.profile = profile;
    this.preset = presetFor(profile);
    this.turboVoice = profile.turbo ? (this.preset.turbo ?? DEFAULT_TURBO) : null;
    this.muted = options.muted ?? false;
    this.volume = options.volume ?? 0.6;
    const factory = options.createContext === undefined ? defaultAudioContextFactory() : options.createContext;
    let ctx: AudioContext | null;
    try {
      ctx = factory ? factory() : null;
    } catch {
      ctx = null;
    }
    this.ctx = ctx;
    if (ctx) this.taps = this.tryBuild(ctx);
  }

  get state(): AudioState {
    if (!this.ctx) return "unavailable";
    return this.ctx.state === "running" ? "running" : this.ctx.state === "closed" ? "closed" : "suspended";
  }

  get isMuted(): boolean {
    return this.muted;
  }

  get currentVolume(): number {
    return this.volume;
  }

  get hasWhine(): boolean {
    return this.preset.whine !== null;
  }

  get graph(): GraphTaps | null {
    return this.taps;
  }

  get wastegateLevel(): number {
    return this.taps?.turbo?.wastegate ?? 0;
  }

  get whineLevel(): number {
    return this.taps?.whine?.gain ?? 0;
  }

  /** Chamado num gesto do usuário ("Ativar som"). */
  async enable(): Promise<AudioState> {
    if (!this.ctx) return "unavailable";
    if (this.ctx.state !== "running") await this.ctx.resume();
    return this.state;
  }

  async suspend(): Promise<void> {
    if (this.ctx && this.ctx.state === "running") await this.ctx.suspend();
  }

  setMuted(muted: boolean): void {
    this.muted = muted;
    this.applyMaster();
  }

  setVolume(volume: number): void {
    this.volume = Math.min(1, Math.max(0, volume));
    this.applyMaster();
  }

  private applyMaster(): void {
    if (!this.ctx || !this.taps) return;
    smooth(this.taps.master.gain, this.muted ? 0 : this.volume, this.ctx.currentTime, 0.02);
  }

  /** Falha na montagem do grafo (navegador limitado) deixa o motor mudo, sem quebrar a cockpit. */
  private tryBuild(ctx: Ctx): GraphTaps | null {
    try {
      return this.build(ctx);
    } catch {
      return null;
    }
  }

  private build(ctx: Ctx): GraphTaps {
    const master = gainNode(ctx, this.muted ? 0 : this.volume);
    const compressor = ctx.createDynamicsCompressor();
    for (const [key, value] of COMPRESSOR_SETTINGS) {
      const param = paramOf(compressor, key);
      if (param) param.value = value;
    }
    const mix = gainNode(ctx, 1);
    const presenceCut = filterNode(ctx, "peaking", MASTER_PRESENCE_CUT.hz, MASTER_PRESENCE_CUT.q, MASTER_PRESENCE_CUT.gainDb);
    const highShelf = filterNode(ctx, "highshelf", MASTER_HIGH_SHELF.hz, 0, MASTER_HIGH_SHELF.gainDb);
    chain(mix, presenceCut, highShelf, master, compressor, ctx.destination);
    const noise = bufferFrom(ctx, pinkNoise(ctx.sampleRate * NOISE_SECONDS));
    this.noise = noise;
    const engine = this.buildEngine(ctx, mix);
    const turbo = this.turboVoice ? new TurboSound(ctx, this.turboVoice, noise, mix) : null;
    const whine = this.preset.whine ? new WhineSound(ctx, this.preset.whine, this.profile.pulleyRatio ?? this.preset.whine.defaultPulleyRatio, noise, mix) : null;
    const pops = new PopVoices(ctx, noise, mix);
    const reverb = shortReverb(ctx, shortImpulseResponse(ctx.sampleRate));
    if (reverb) {
      const send = gainNode(ctx, REVERB_SEND);
      chain(pops.bus, send, reverb.input);
      reverb.output.connect(mix);
    }
    return { master, mix, presenceCut, highShelf, engine, turbo, whine, pops, reverb };
  }

  private buildEngine(ctx: Ctx, out: AudioNode): EngineChain {
    const { pulse, tone } = this.preset;
    const cycle = exhaustCycle({ pulse, firingOrder: this.profile.firingOrder, sampleRate: ctx.sampleRate });
    const source = loopSource(ctx, bufferFrom(ctx, cycle));
    const pulseAm = gainNode(ctx, 1);
    const drive = gainNode(ctx, tone.driveMin);
    const shaper = shaperNode(ctx, saturationCurve(tone.saturation, tone.asymmetry));
    const lowpass = filterNode(ctx, "lowpass", lowpassCutoffHz(0, 0, tone.cutoffCurve), tone.lowpassQDb);
    const [low, mid] = tone.resonators;
    const resonators: [BiquadFilterNode, BiquadFilterNode] = [filterNode(ctx, "peaking", low.hz, low.q, low.gainDb), filterNode(ctx, "peaking", mid.hz, mid.q, mid.gainDb)];
    const rumble = filterNode(ctx, "highpass", RUMBLE_HIGHPASS_HZ, -3);
    const bus = gainNode(ctx, 0);
    chain(source, pulseAm, drive, shaper, lowpass, resonators[0], resonators[1], rumble, bus, out);
    const sub = ctx.createOscillator();
    sub.type = "sine";
    sub.frequency.value = 30;
    const subGain = gainNode(ctx, 0);
    chain(sub, subGain, bus);
    sub.start();
    return { source, pulseAm, drive, shaper, lowpass, resonators, bus, sub, subLevel: subGain };
  }

  /** Atualiza a síntese a partir dos canais mais recentes (chamado pelo RenderLoop a cada frame). */
  update(input: AudioInputs): void {
    const f = firingFrequencyHz(input.rpm, this.profile.nCyl);
    this.fundamentalHz = f;
    this.load = engineLoad(input.throttlePct, input.mapKpa, input.baroKpa);
    this.cutoffHz = lowpassCutoffHz(input.rpm, this.load, this.preset.tone.cutoffCurve);
    if (this.turboVoice && this.blowoff.update(input.nowMs, input.throttlePct, boostBar(input.mapKpa, input.baroKpa))) this.triggerBlowoff();
    this.lastRpm = input.rpm;
    const ctx = this.ctx;
    if (!ctx || !this.taps || this.broken) return;
    const t = ctx.currentTime;
    this.updateEngine(t, input.rpm, f);
    this.schedulePulses(t, f);
    this.taps.turbo?.update(t, input);
    this.taps.whine?.update(t, input);
  }

  private updateEngine(t: number, rpm: number, f: number): void {
    const engine = this.taps!.engine;
    const { tone, responseS, camLope } = this.preset;
    const lope = camLopeAt(t, rpm, camLope);
    smooth(paramOf(engine.source, "playbackRate"), playbackRateFor(rpm) * lope.freqMul, t, 0.015);
    smooth(engine.lowpass.frequency, this.cutoffHz, t, 0.04);
    smooth(engine.drive.gain, driveFor(this.load, tone.driveMin, tone.driveMax), t, 0.05);
    smooth(engine.bus.gain, ENGINE_LEVEL * engineLevel(rpm, this.load), t, responseS);
    const subHz = Math.max(1, f * tone.sub.order);
    smooth(engine.sub.frequency, subHz, t, 0.015);
    smooth(engine.subLevel.gain, rpm > 50 ? tone.sub.level * subLevel(subHz, this.load) : 0, t, responseS * 2);
  }

  /** AM suave por ignição: lope de came (marcha lenta) + jitter vivo leve, até 100 ms à frente. */
  private schedulePulses(now: number, f: number): void {
    const am = this.taps!.engine.pulseAm.gain;
    if (f <= 1) return;
    const period = 1 / f;
    if (this.nextPulseAt < now) this.nextPulseAt = now;
    const live = this.preset.pulse.ampJitter * 0.5;
    for (let n = 0; this.nextPulseAt < now + PULSE_HORIZON_S && n < 64; n += 1) {
      const lope = camLopeAt(this.nextPulseAt, this.lastRpm, this.preset.camLope).amp;
      am.setTargetAtTime(lope * (1 + live * (this.jitter() * 2 - 1)), this.nextPulseAt, period / 3);
      this.nextPulseAt += period;
    }
  }

  /** Fechamento da borboleta com boost: blow-off + flutter/chirp do compressor. */
  triggerBlowoff(): void {
    this.blowoffCount += 1;
    const turbo = this.taps?.turbo;
    if (!this.ctx || !turbo || this.broken) return;
    const t = this.ctx.currentTime + 0.005;
    turbo.blowoff(t);
    if (turbo.flutter(t + 0.04)) this.flutterCount += 1;
  }

  /** Pops de overrun: rajada semeada por `seq`, limitada por vozes e por horizonte de agenda. */
  pops(count: number, seq: number): void {
    if (count <= 0 || this.broken) return;
    const plan = overrunPopPlan(seq, count);
    const ctx = this.ctx;
    if (!ctx || !this.taps) {
      this.popCount += plan.length;
      return;
    }
    const now = ctx.currentTime;
    const start = Math.max(now + 0.005, this.popClock);
    for (const p of plan) {
      const at = start + p.delayS;
      if (at > now + POP_HORIZON_S) break;
      if (!this.taps.pops.trigger(at, p)) continue;
      this.popCount += 1;
      this.popClock = at + 0.04;
    }
  }

  /** Quebra: impacto de 60 Hz (300 ms) + ruído metálico (passa-banda 3 kHz, 1,2 s); depois silêncio do motor. */
  breakage(): void {
    if (this.broken) return;
    this.broken = true;
    const ctx = this.ctx;
    const taps = this.taps;
    if (!ctx || !taps || !this.noise) return;
    const t = ctx.currentTime;
    const thump = ctx.createOscillator();
    thump.type = "sine";
    thump.frequency.value = 60;
    const thumpLevel = gainNode(ctx, 0);
    thumpLevel.gain.setTargetAtTime(0.9, t, 0.003);
    thumpLevel.gain.setTargetAtTime(0, t + 0.02, 0.08);
    chain(thump, thumpLevel, taps.mix);
    thump.start(t);
    thump.stop(t + 0.6);
    const metal = ctx.createBufferSource();
    metal.buffer = this.noise;
    const metalLevel = gainNode(ctx, 0);
    metalLevel.gain.setTargetAtTime(0.6, t, 0.004);
    metalLevel.gain.setTargetAtTime(0, t + 0.05, 0.35);
    chain(metal, filterNode(ctx, "bandpass", 3000, 1.2), metalLevel, taps.mix);
    metal.start(t);
    metal.stop(t + 1.8);
    smooth(taps.engine.bus.gain, 0, t, 0.05);
    smooth(taps.engine.subLevel.gain, 0, t, 0.05);
    taps.turbo?.silence(t);
    taps.whine?.silence(t);
  }

  /** Motor restaurado: volta a sintetizar. */
  repair(): void {
    this.broken = false;
  }

  dispose(): void {
    const taps = this.taps;
    if (taps) {
      stopAll([taps.engine.source, taps.engine.sub, ...(taps.turbo?.sources ?? []), ...(taps.whine ? [taps.whine.source] : []), ...taps.pops.sources]);
    }
    void this.ctx?.close().catch(() => undefined);
  }
}
