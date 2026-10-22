/**
 * Formas de onda pré-calculadas (003 RF-07, RF-09; D-05): buffer de pulsos de exaustão por ordem de
 * ignição com jitter ciclo a ciclo, ruído rosa e resposta impulsiva curta do reverb dos pops.
 * Calculadas uma vez por motor; nada aqui roda por frame.
 */
import { mulberry32 } from "../flashGuard";

import type { ExhaustPulse } from "./archetypes";
import { BASE_CYCLE_HZ, firingPulseGains } from "./EngineSynth";

/** Ciclos de 720° no laço: o padrão de jitter só se repete a cada 12 ciclos. */
export const LOOP_CYCLES = 12;
const PEAK = 0.9;

export interface CycleSpec {
  pulse: ExhaustPulse;
  firingOrder: readonly number[];
  sampleRate: number;
  cycles?: number;
  seed?: number;
}

/** Amostras de um ciclo de 720° no ciclo de referência. */
export function samplesPerCycle(sampleRate: number): number {
  return Math.round(sampleRate / BASE_CYCLE_HZ);
}

interface PulseEvent {
  start: number;
  width: number;
  amp: number;
}

/** Soma um pulso beta `u^rise · (1 − u)^fall` (pico 1) com turbulência, de forma circular no laço. */
function addPulse(out: Float32Array, ev: PulseEvent, pulse: ExhaustPulse, rnd: () => number): void {
  const n = Math.max(4, Math.round(ev.width));
  const uPeak = pulse.rise / (pulse.rise + pulse.fall);
  const norm = uPeak ** pulse.rise * (1 - uPeak) ** pulse.fall;
  const len = out.length;
  const base = ((Math.floor(ev.start) % len) + len) % len;
  let turbulence = 0;
  for (let i = 0; i <= n; i += 1) {
    const u = i / n;
    const shape = (u ** pulse.rise * (1 - u) ** pulse.fall) / norm;
    turbulence += 0.35 * (rnd() * 2 - 1 - turbulence);
    const idx = (base + i) % len;
    out[idx] = out[idx]! + ev.amp * shape * (1 + pulse.noiseMix * 2.5 * turbulence);
  }
}

function pulseEvent(cycleStart: number, k: number, interval: number, cylGain: number, bankB: boolean, spec: CycleSpec, rnd: () => number): PulseEvent {
  const { pulse } = spec;
  const jitter = () => rnd() * 2 - 1;
  const bank = bankB ? pulse.bank : null;
  const amp = (1 + (cylGain - 1) * pulse.cylinderSpread) * (1 + pulse.ampJitter * jitter()) * (bank?.gain ?? 1);
  const width = pulse.widthFrac * interval * (bank?.widthMul ?? 1) * (1 + 0.5 * pulse.ampJitter * jitter());
  const start = cycleStart + k * interval + (bank ? bank.delayFrac * interval : 0) + pulse.timeJitter * interval * jitter();
  return { start, width, amp };
}

/** Remove o nível DC (pulsos de pressão são positivos) e normaliza o pico em 0,9. */
function normalize(out: Float32Array): void {
  let mean = 0;
  for (const v of out) mean += v;
  mean /= out.length || 1;
  let peak = 0;
  for (let i = 0; i < out.length; i += 1) {
    out[i] = out[i]! - mean;
    peak = Math.max(peak, Math.abs(out[i]!));
  }
  if (peak <= 0) return;
  for (let i = 0; i < out.length; i += 1) out[i] = (out[i]! / peak) * PEAK;
}

/**
 * Laço de `cycles` ciclos de 720° com um pulso por ignição na ordem `firingOrder`: assinatura por
 * cilindro, bancada atrasada no cross-plane e jitter semeado (determinístico).
 */
export function exhaustCycle(spec: CycleSpec): Float32Array {
  const perCycle = samplesPerCycle(spec.sampleRate);
  const cycles = spec.cycles ?? LOOP_CYCLES;
  const order = spec.firingOrder.length > 0 ? spec.firingOrder : [1];
  const out = new Float32Array(perCycle * cycles);
  const interval = perCycle / order.length;
  const gains = firingPulseGains(order);
  const rnd = mulberry32(spec.seed ?? 0x5eed);
  for (let c = 0; c < cycles; c += 1) {
    order.forEach((cyl, k) => {
      const bankB = spec.pulse.bank !== null && cyl > order.length / 2;
      addPulse(out, pulseEvent(c * perCycle, k, interval, gains[k]!, bankB, spec, rnd), spec.pulse, rnd);
    });
  }
  normalize(out);
  return out;
}

/** Ruído rosa (Paul Kellet) semeado, para spool, wastegate, blow-off, flutter e pops. */
export function pinkNoise(length: number, seed = 12345): Float32Array {
  const out = new Float32Array(length);
  let b0 = 0;
  let b1 = 0;
  let b2 = 0;
  let s = seed;
  for (let i = 0; i < length; i += 1) {
    s = (s * 1103515245 + 12345) & 0x7fffffff;
    const white = (s / 0x7fffffff) * 2 - 1;
    b0 = 0.99765 * b0 + white * 0.099046;
    b1 = 0.963 * b1 + white * 0.2965164;
    b2 = 0.57 * b2 + white * 1.0526913;
    out[i] = (b0 + b1 + b2 + white * 0.1848) * 0.11;
  }
  return out;
}

/** Resposta impulsiva curta (sala/escapamento): ruído com decaimento exponencial que escurece com o tempo. */
export function shortImpulseResponse(sampleRate: number, durationS = 0.32, seed = 4242): Float32Array {
  const length = Math.max(1, Math.round(sampleRate * durationS));
  const out = new Float32Array(length);
  const rnd = mulberry32(seed);
  const fadeIn = Math.max(1, Math.round(sampleRate * 0.002));
  let lp = 0;
  for (let i = 0; i < length; i += 1) {
    const t = i / sampleRate;
    const coeff = 0.6 * Math.exp(-t / 0.12) + 0.08;
    lp += coeff * (rnd() * 2 - 1 - lp);
    out[i] = lp * Math.exp(-t / 0.07) * Math.min(1, i / fadeIn);
  }
  return out;
}
