/**
 * Matemática pura da síntese do motor (001 RF-18; 003 RF-07 a RF-10; D-05).
 * Sem Web Audio aqui: o `AudioEngine` aplica estes valores aos nós.
 */
import { mulberry32 } from "../flashGuard";

import type { CamLope } from "./archetypes";

/** Ciclo de referência do buffer de pulsos (Hz de ciclo de 720°): 25 Hz = 3000 rpm. */
export const BASE_CYCLE_HZ = 25;
export const LOWPASS_MIN_HZ = 180;
export const LOWPASS_MAX_HZ = 1400;
/** Corte de presença no master (1–4 kHz) e prateleira aguda. */
export const MASTER_PRESENCE_CUT = { hz: 2200, q: 0.7, gainDb: -6 } as const;
export const MASTER_HIGH_SHELF = { hz: 4500, gainDb: -6 } as const;
/** Passa-alta de limpeza (DC e ronco subsônico) no fim da cadeia do motor. */
export const RUMBLE_HIGHPASS_HZ = 24;
export const MAX_POPS_PER_BURST = 6;

const clamp01 = (v: number) => Math.min(1, Math.max(0, v));

/** Frequência de ignição de um 4 tempos: `f_fire = (rpm / 60) · (n_cyl / 2)` (Hz). */
export function firingFrequencyHz(rpm: number, nCyl: number): number {
  return (Math.max(0, rpm) / 60) * (nCyl / 2);
}

/** Taxa de reprodução do buffer de pulsos: ciclo de 720° (`rpm / 120`) sobre o ciclo de referência. */
export function playbackRateFor(rpm: number): number {
  return Math.max(0.02, Math.max(0, rpm) / 120 / BASE_CYCLE_HZ);
}

/** Posição normalizada da rotação (700 → 0, 7200 → 1). */
export function rpmNorm(rpm: number): number {
  return clamp01((rpm - 700) / 6500);
}

/** Carga 0..1 combinando borboleta (55 %) e pressão do coletor (45 %; 200 kPa = cheia). */
export function engineLoad(throttlePct: number, mapKpa: number, baroKpa: number): number {
  const fullMap = Math.max(150, baroKpa + 100);
  return clamp01(0.55 * clamp01(throttlePct / 100) + 0.45 * clamp01((mapKpa - 25) / (fullMap - 25)));
}

/**
 * Corte do passa-baixa dinâmico: interpolação exponencial 180 → 1400 Hz, monotônica em rpm e carga.
 * `curve > 1` escurece o meio da faixa sem mudar os extremos.
 */
export function lowpassCutoffHz(rpm: number, load: number, curve = 1): number {
  const x = clamp01(0.55 * rpmNorm(rpm) + 0.45 * clamp01(load)) ** curve;
  return LOWPASS_MIN_HZ * (LOWPASS_MAX_HZ / LOWPASS_MIN_HZ) ** x;
}

/** Nível relativo do motor (0 abaixo de 50 rpm; 0,32..1 por carga e rotação). */
export function engineLevel(rpm: number, load: number): number {
  if (rpm <= 50) return 0;
  return (0.4 + 0.6 * clamp01(load)) * (0.8 + 0.2 * rpmNorm(rpm));
}

/** Ganho de entrada da saturação: mais carga = mais harmônicos quentes. */
export function driveFor(load: number, min: number, max: number): number {
  return min + (max - min) * clamp01(load);
}

/** Sub-bass só como corpo: cheio entre 35 e 60 Hz, some abaixo de 22 Hz e acima de 120 Hz. */
export function subLevel(subHz: number, load: number): number {
  const window = Math.min(clamp01((subHz - 22) / 13), clamp01((120 - subHz) / 60));
  return window * (0.5 + 0.5 * clamp01(load));
}

/** Saturação estilo válvula: `tanh(k · (x + a·x²)) / tanh(k · (1 + a))`, suave, monotônica, entrada presa em ±1. */
export function saturate(x: number, k: number, asymmetry: number): number {
  const a = Math.min(0.5, Math.max(0, asymmetry));
  const v = Math.min(1, Math.max(-1, x));
  return Math.tanh(k * (v + a * v * v)) / Math.tanh(k * (1 + a));
}

/** Curva do `WaveShaperNode` amostrada de `saturate` em −1..1. */
export function saturationCurve(k: number, asymmetry: number, samples = 1024): Float32Array {
  const curve = new Float32Array(samples);
  for (let i = 0; i < samples; i += 1) curve[i] = saturate((i / (samples - 1)) * 2 - 1, k, asymmetry);
  return curve;
}

/** Ganho do spool proporcional a `(map_kpa − baro_kpa) / 150`, preso em 0..1. */
export function spoolGain(mapKpa: number, baroKpa: number): number {
  return clamp01((mapKpa - baroKpa) / 150);
}

/** Centro da banda do spool (ruído filtrado): `turbo_rpm / 60 · 0,4 · escala`, preso em 350..3200 Hz. */
export function spoolBandHz(turboRpm: number, scale: number): number {
  return Math.min(3200, Math.max(350, (Math.max(0, turboRpm) / 60) * 0.4 * scale));
}

/** Rotação estimada da turbina quando o canal `turbo_rpm` falta: 60k + 120k · spool. */
export function estimatedTurboRpm(mapKpa: number, baroKpa: number): number {
  return 60_000 + 120_000 * spoolGain(mapKpa, baroKpa);
}

/** Chiado da wastegate: entra com boost alto (spool > 0,55) e pedal aberto; 0..1. */
export function wastegateHissGain(mapKpa: number, baroKpa: number, throttlePct: number): number {
  return clamp01((spoolGain(mapKpa, baroKpa) - 0.55) / 0.45) * clamp01(throttlePct / 100);
}

/** Assobio do compressor: rotação do rotor (`rpm · polia`) × lóbulos, em Hz (máx. 6 kHz). */
export function superchargerWhineHz(rpm: number, pulleyRatio: number, lobes: number): number {
  return Math.min(6000, ((Math.max(0, rpm) * pulleyRatio) / 60) * lobes);
}

/** Volume do assobio do compressor pela carga (`map_kpa`), 0,05..1. */
export function whineGain(mapKpa: number): number {
  return Math.min(1, Math.max(0.05, (mapKpa - 30) / 170));
}

/**
 * Irregularidade da ordem de ignição: fator de amplitude ±8 % por pulso, determinístico pela
 * posição de cada cilindro na `firing_order`.
 */
export function firingPulseGains(firingOrder: readonly number[]): number[] {
  const n = firingOrder.length;
  return firingOrder.map((cyl, i) => {
    const phase = ((cyl - 1) * 2.399963 + i * 0.7) % (2 * Math.PI); // ângulo de ouro: padrão sem período curto
    return 1 + 0.08 * Math.sin(phase) * (n > 1 ? 1 : 0);
  });
}

/**
 * Lope de came em `tS`: duas senoides de razão irracional (padrão irregular, mas determinístico),
 * pleno abaixo de `fadeRpm / 2` e nulo a partir de `fadeRpm`.
 */
export function camLopeAt(tS: number, rpm: number, lope: CamLope | null): { amp: number; freqMul: number } {
  if (!lope || rpm <= 0) return { amp: 1, freqMul: 1 };
  const fade = clamp01((lope.fadeRpm - rpm) / (lope.fadeRpm / 2));
  if (fade === 0) return { amp: 1, freqMul: 1 };
  const w = 2 * Math.PI * lope.rateHz * tS;
  const am = 0.6 * Math.sin(w) + 0.4 * Math.sin(w * 1.618 + 1.3);
  const fm = Math.sin(w * 0.73 + 0.4);
  return { amp: 1 + lope.depth * fade * am, freqMul: 1 + lope.fmDepth * fade * fm };
}

export interface PopPlan {
  /** Atraso desde o início da rajada (s). */
  delayS: number;
  gain: number;
  /** Multiplicador do punch grave (90–160 Hz). */
  pitchMul: number;
  /** Proporção do estalo metálico filtrado. */
  crackMix: number;
  /** Constante de tempo do decaimento (s). */
  decayS: number;
}

/** Rajada de pops semeada por `seq` (determinística), no máximo `MAX_POPS_PER_BURST`, espaçamento 45–120 ms. */
export function overrunPopPlan(seq: number, count: number): PopPlan[] {
  const rnd = mulberry32(seq);
  const n = Math.min(MAX_POPS_PER_BURST, Math.max(0, Math.floor(count)));
  let delayS = 0;
  return Array.from({ length: n }, (_, i) => {
    delayS += i === 0 ? 0.02 * rnd() : 0.045 + 0.075 * rnd();
    return { delayS, gain: 0.45 + 0.55 * rnd(), pitchMul: 0.92 + 0.14 * rnd(), crackMix: 0.3 + 0.5 * rnd(), decayS: 0.018 + 0.022 * rnd() };
  });
}

/** Punch grave: começa em 150 · m Hz e cai para 96 · m Hz, sempre dentro de 90–160 Hz. */
export function popPunchHz(pitchMul: number): { startHz: number; endHz: number } {
  return { startHz: Math.min(160, 150 * pitchMul), endHz: Math.max(90, 96 * pitchMul) };
}

/**
 * Detector de fechamento da borboleta com boost (blow-off e flutter): queda ≥ 50 pontos em ≤ 200 ms
 * com boost > 0,5 bar; no máximo 1 disparo por 1 s.
 */
export class BlowoffDetector {
  private readonly times: number[] = [];
  private readonly throttles: number[] = [];
  private lastFire = -Infinity;
  private armed = true;

  /** `tMs` = relógio (ms); devolve `true` quando dispara. */
  update(tMs: number, throttlePct: number, boostInBar: number): boolean {
    this.times.push(tMs);
    this.throttles.push(throttlePct);
    while (this.times.length > 0 && tMs - this.times[0]! > 200) {
      this.times.shift();
      this.throttles.shift();
    }
    let maxRecent = throttlePct;
    for (const v of this.throttles) if (v > maxRecent) maxRecent = v;
    if (maxRecent - throttlePct < 50) {
      // Rearma quando a borboleta volta a abrir (1 disparo por fechamento).
      if (throttlePct > 50) this.armed = true;
      return false;
    }
    if (this.armed && boostInBar > 0.5 && tMs - this.lastFire >= 1000) {
      this.lastFire = tMs;
      this.armed = false;
      return true;
    }
    return false;
  }
}

/** Envelope ataque/decaimento linear: amplitude em `tMs` desde o início. */
export function envelopeAt(tMs: number, attackMs: number, decayMs: number): number {
  if (tMs < 0) return 0;
  if (tMs < attackMs) return tMs / attackMs;
  return Math.max(0, 1 - (tMs - attackMs) / decayMs);
}
