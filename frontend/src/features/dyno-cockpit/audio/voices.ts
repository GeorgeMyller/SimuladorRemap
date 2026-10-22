/**
 * Vozes de indução e transientes (003 RF-08, RF-09; D-05). Todos os nós nascem uma vez; os eventos só
 * agendam envelopes com `setTargetAtTime` (sem degraus, sem cliques).
 * - Turbo: spool por ruído de banda estreita seguindo `turbo_rpm`, harmônico agudo discreto, chiado
 *   da wastegate, blow-off e flutter/chirp do compressor. Nenhum oscilador.
 * - Compressor mecânico: whine por ruído de banda estreita (Q alto) em `rpm · polia · lóbulos`.
 * - Pops de overrun: punch senoidal com queda de pitch + corpo grave + estalo metálico filtrado,
 *   com reverb curto, em `MAX_POP_VOICES` vozes reaproveitadas.
 */
import type { TurboVoice, WhineVoice } from "./archetypes";
import { estimatedTurboRpm, popPunchHz, spoolBandHz, spoolGain, superchargerWhineHz, wastegateHissGain, whineGain, type PopPlan } from "./EngineSynth";
import { cancelFrom, chain, filterNode, gainNode, loopSource, smooth, type Ctx } from "./graph";

export const MAX_POP_VOICES = 4;

export interface InductionInputs {
  rpm: number;
  turboRpm?: number | null;
  throttlePct: number;
  mapKpa: number;
  baroKpa: number;
}

/** Envelope ataque/decaimento por constantes de tempo, a partir do valor corrente. */
function pulseEnvelope(param: AudioParam, t: number, peak: number, attackS: number, holdS: number, decayS: number): void {
  cancelFrom(param, t);
  param.setTargetAtTime(peak, t, attackS);
  param.setTargetAtTime(0, t + holdS, decayS);
}

export class TurboSound {
  readonly bus: GainNode;
  readonly spoolFilter: BiquadFilterNode;
  readonly harmonicFilter: BiquadFilterNode;
  private readonly spoolLevel: GainNode;
  private readonly harmonicLevel: GainNode;
  private readonly wastegateLevel: GainNode | null;
  private readonly blowoffFilter: BiquadFilterNode;
  private readonly blowoffLevel: GainNode;
  readonly flutterFilter: BiquadFilterNode;
  private readonly flutterLevel: GainNode;
  readonly sources: AudioBufferSourceNode[];
  spoolHz = 0;
  wastegate = 0;

  constructor(
    ctx: Ctx,
    private readonly voice: TurboVoice,
    noise: AudioBuffer,
    out: AudioNode,
  ) {
    this.bus = gainNode(ctx, 1);
    this.bus.connect(out);
    const spoolNoise = loopSource(ctx, noise, 0.37);
    const ventNoise = loopSource(ctx, noise, 1.13);
    this.sources = [spoolNoise, ventNoise];
    this.spoolFilter = filterNode(ctx, "bandpass", 400, voice.spoolQ);
    this.spoolLevel = gainNode(ctx, 0);
    chain(spoolNoise, this.spoolFilter, this.spoolLevel, this.bus);
    this.harmonicFilter = filterNode(ctx, "bandpass", 800, voice.spoolQ * 6);
    this.harmonicLevel = gainNode(ctx, 0);
    chain(spoolNoise, this.harmonicFilter, this.harmonicLevel, this.bus);
    this.wastegateLevel = voice.wastegateLevel > 0 ? gainNode(ctx, 0) : null;
    if (this.wastegateLevel) chain(ventNoise, filterNode(ctx, "bandpass", voice.wastegateHz, 0.8), this.wastegateLevel, this.bus);
    this.blowoffFilter = filterNode(ctx, "bandpass", voice.blowoff.hz, voice.blowoff.q);
    this.blowoffLevel = gainNode(ctx, 0);
    chain(ventNoise, this.blowoffFilter, this.blowoffLevel, this.bus);
    this.flutterFilter = filterNode(ctx, "bandpass", voice.flutter.hz, 1.8);
    this.flutterLevel = gainNode(ctx, 0);
    chain(ventNoise, this.flutterFilter, this.flutterLevel, this.bus);
  }

  update(t: number, input: InductionInputs): void {
    const turboRpm = input.turboRpm ?? estimatedTurboRpm(input.mapKpa, input.baroKpa);
    this.spoolHz = spoolBandHz(turboRpm, this.voice.spoolScale);
    smooth(this.spoolFilter.frequency, this.spoolHz, t, 0.06);
    smooth(this.harmonicFilter.frequency, Math.min(9000, this.spoolHz * 2.1), t, 0.06);
    const throttle = Math.min(1, Math.max(0, input.throttlePct / 100));
    const level = turboRpm > 0 ? this.voice.level * spoolGain(input.mapKpa, input.baroKpa) * (0.35 + 0.65 * throttle) : 0;
    smooth(this.spoolLevel.gain, level, t, 0.08);
    smooth(this.harmonicLevel.gain, level * this.voice.harmonicLevel, t, 0.08);
    if (!this.wastegateLevel) return;
    this.wastegate = this.voice.wastegateLevel * wastegateHissGain(input.mapKpa, input.baroKpa, input.throttlePct);
    smooth(this.wastegateLevel.gain, this.wastegate, t, 0.08);
  }

  /** Blow-off: ruído em banda média com envelope 30 ms / ~400 ms e leve queda de frequência. */
  blowoff(t: number): void {
    const { hz, level } = this.voice.blowoff;
    cancelFrom(this.blowoffFilter.frequency, t);
    this.blowoffFilter.frequency.setTargetAtTime(hz * 1.25, t, 0.005);
    this.blowoffFilter.frequency.setTargetAtTime(hz * 0.8, t + 0.03, 0.2);
    pulseEnvelope(this.blowoffLevel.gain, t, level, 0.012, 0.035, 0.13);
  }

  /** Flutter/chirp do compressor (surge): pulsos que aceleram e decaem, com a banda descendo. */
  flutter(t: number): boolean {
    const { level, rateHz, cycles, hz } = this.voice.flutter;
    if (level <= 0 || cycles <= 0) return false;
    const g = this.flutterLevel.gain;
    cancelFrom(g, t);
    cancelFrom(this.flutterFilter.frequency, t);
    this.flutterFilter.frequency.setTargetAtTime(hz * 1.2, t, 0.005);
    this.flutterFilter.frequency.setTargetAtTime(hz * 0.65, t + 0.01, 0.15);
    let at = t;
    for (let i = 0; i < cycles; i += 1) {
      const period = (1 / rateHz) * (1 - 0.06 * i);
      g.setTargetAtTime(level * 0.72 ** i, at, 0.004);
      g.setTargetAtTime(0, at + 0.012, period * 0.22);
      at += period;
    }
    return true;
  }

  silence(t: number): void {
    for (const g of [this.spoolLevel, this.harmonicLevel, this.wastegateLevel, this.blowoffLevel, this.flutterLevel]) if (g) smooth(g.gain, 0, t, 0.05);
    this.wastegate = 0;
  }
}

export class WhineSound {
  readonly filter: BiquadFilterNode;
  private readonly level: GainNode;
  readonly source: AudioBufferSourceNode;
  hz = 0;
  gain = 0;

  constructor(ctx: Ctx, private readonly voice: WhineVoice, private readonly pulleyRatio: number, noise: AudioBuffer, out: AudioNode) {
    this.source = loopSource(ctx, noise, 0.71);
    this.filter = filterNode(ctx, "bandpass", 300, voice.q);
    this.level = gainNode(ctx, 0);
    chain(this.source, this.filter, this.level, out);
  }

  update(t: number, input: InductionInputs): void {
    this.hz = Math.max(40, superchargerWhineHz(input.rpm, this.pulleyRatio, this.voice.lobes));
    smooth(this.filter.frequency, this.hz, t, 0.02);
    this.gain = input.rpm > 50 ? this.voice.level * whineGain(input.mapKpa) : 0;
    smooth(this.level.gain, this.gain, t, 0.05);
  }

  silence(t: number): void {
    this.gain = 0;
    smooth(this.level.gain, 0, t, 0.05);
  }
}

interface PopVoice {
  punch: OscillatorNode;
  punchLevel: GainNode;
  bodyLevel: GainNode;
  crackLevel: GainNode;
  busyUntil: number;
}

/** Pops & bangs: vozes fixas; uma rajada usa as vozes livres e descarta o excedente. */
export class PopVoices {
  readonly bus: GainNode;
  readonly voices: PopVoice[] = [];
  readonly sources: AudioScheduledSourceNode[] = [];
  private next = 0;

  constructor(ctx: Ctx, noise: AudioBuffer, out: AudioNode) {
    this.bus = gainNode(ctx, 1);
    const tame = filterNode(ctx, "lowpass", 5000, -3);
    chain(this.bus, tame, out);
    for (let i = 0; i < MAX_POP_VOICES; i += 1) this.voices.push(this.buildVoice(ctx, noise, i));
  }

  private buildVoice(ctx: Ctx, noise: AudioBuffer, i: number): PopVoice {
    const punch = ctx.createOscillator();
    punch.type = "sine";
    punch.frequency.value = 120;
    punch.start();
    const punchLevel = gainNode(ctx, 0);
    chain(punch, punchLevel, this.bus);
    const src = loopSource(ctx, noise, 0.21 + i * 0.29);
    const bodyLevel = gainNode(ctx, 0);
    chain(src, filterNode(ctx, "lowpass", 650, 0), bodyLevel, this.bus);
    const crackLevel = gainNode(ctx, 0);
    chain(src, filterNode(ctx, "bandpass", 2100 + 260 * i, 3.5), crackLevel, this.bus);
    this.sources.push(punch, src);
    return { punch, punchLevel, bodyLevel, crackLevel, busyUntil: -Infinity };
  }

  /** Agenda um pop numa voz livre; devolve `false` se todas estão ocupadas (limite de vozes). */
  trigger(t: number, plan: PopPlan): boolean {
    const voice = this.freeVoice(t);
    if (!voice) return false;
    const { startHz, endHz } = popPunchHz(plan.pitchMul);
    cancelFrom(voice.punch.frequency, t);
    voice.punch.frequency.setValueAtTime(startHz, t);
    voice.punch.frequency.setTargetAtTime(endHz, t + 0.002, 0.012);
    pulseEnvelope(voice.punchLevel.gain, t, 0.4 * plan.gain, 0.0015, 0.006, plan.decayS * 1.4);
    pulseEnvelope(voice.bodyLevel.gain, t, 0.35 * plan.gain, 0.002, 0.004, plan.decayS);
    pulseEnvelope(voice.crackLevel.gain, t, 0.6 * plan.gain * plan.crackMix, 0.001, 0.003, plan.decayS * 0.5);
    voice.busyUntil = t + plan.decayS * 5;
    return true;
  }

  private freeVoice(t: number): PopVoice | null {
    for (let i = 0; i < this.voices.length; i += 1) {
      const voice = this.voices[(this.next + i) % this.voices.length]!;
      if (voice.busyUntil > t) continue;
      this.next = (this.next + i + 1) % this.voices.length;
      return voice;
    }
    return null;
  }
}
