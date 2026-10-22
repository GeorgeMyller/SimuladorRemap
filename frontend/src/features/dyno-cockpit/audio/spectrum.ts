/**
 * Análise espectral da cadeia do motor (003 RF-10): espectro do laço de pulsos × resposta dos filtros
 * (passa-baixa dinâmico, ressonadores, passa-alta, corte de presença e prateleira do master).
 * A saturação entra no sinal com o drive máximo (pior caso de harmônicos) antes da DFT.
 */
import { ARCHETYPE_PRESETS, type ArchetypePreset, type EngineArchetype } from "./archetypes";
import { BASE_CYCLE_HZ, MASTER_HIGH_SHELF, MASTER_PRESENCE_CUT, RUMBLE_HIGHPASS_HZ, firingFrequencyHz, lowpassCutoffHz, playbackRateFor, saturate, subLevel } from "./EngineSynth";
import { LOOP_CYCLES, exhaustCycle } from "./waveforms";

export type BiquadKind = "lowpass" | "highpass" | "bandpass" | "peaking" | "highshelf";

export interface BiquadSpec {
  kind: BiquadKind;
  hz: number;
  /** Linear em bandpass/peaking; em dB em lowpass/highpass (convenção Web Audio); ignorado na prateleira. */
  q: number;
  gainDb?: number;
}

const ANALYSIS_RATE = 16_000;
const FILTER_RATE = 48_000;
const BASE_MAX_HZ = 6000;

function coefficients(spec: BiquadSpec, fs: number): { b: [number, number, number]; a: [number, number, number] } {
  const w0 = (2 * Math.PI * Math.min(spec.hz, fs / 2 - 1)) / fs;
  const cos = Math.cos(w0);
  const sin = Math.sin(w0);
  const A = 10 ** ((spec.gainDb ?? 0) / 40);
  const qLin = spec.kind === "lowpass" || spec.kind === "highpass" ? 10 ** (spec.q / 20) : spec.q;
  const alpha = sin / (2 * qLin);
  switch (spec.kind) {
    case "lowpass":
      return { b: [(1 - cos) / 2, 1 - cos, (1 - cos) / 2], a: [1 + alpha, -2 * cos, 1 - alpha] };
    case "highpass":
      return { b: [(1 + cos) / 2, -(1 + cos), (1 + cos) / 2], a: [1 + alpha, -2 * cos, 1 - alpha] };
    case "bandpass":
      return { b: [alpha, 0, -alpha], a: [1 + alpha, -2 * cos, 1 - alpha] };
    case "peaking":
      return { b: [1 + alpha * A, -2 * cos, 1 - alpha * A], a: [1 + alpha / A, -2 * cos, 1 - alpha / A] };
    case "highshelf": {
      const s = 2 * Math.sqrt(A) * (sin / 2) * Math.SQRT2;
      return {
        b: [A * (A + 1 + (A - 1) * cos + s), -2 * A * (A - 1 + (A + 1) * cos), A * (A + 1 + (A - 1) * cos - s)],
        a: [A + 1 - (A - 1) * cos + s, 2 * (A - 1 - (A + 1) * cos), A + 1 - (A - 1) * cos - s],
      };
    }
  }
}

/** |H(f)| de um biquad RBJ (mesmas fórmulas do `BiquadFilterNode`). */
export function biquadMagnitude(spec: BiquadSpec, f: number, fs = FILTER_RATE): number {
  const { b, a } = coefficients(spec, fs);
  const w = (2 * Math.PI * f) / fs;
  const re = (c: readonly number[]) => c[0]! + c[1]! * Math.cos(w) + c[2]! * Math.cos(2 * w);
  const im = (c: readonly number[]) => -(c[1]! * Math.sin(w) + c[2]! * Math.sin(2 * w));
  return Math.hypot(re(b), im(b)) / Math.hypot(re(a), im(a));
}

/** Filtros da cadeia do motor no ponto de operação (mesma ordem do grafo do `AudioEngine`). */
export function engineChainFilters(preset: ArchetypePreset, rpm: number, load: number): BiquadSpec[] {
  const { tone } = preset;
  return [
    { kind: "lowpass", hz: lowpassCutoffHz(rpm, load, tone.cutoffCurve), q: tone.lowpassQDb },
    ...tone.resonators.map((r): BiquadSpec => ({ kind: "peaking", hz: r.hz, q: r.q, gainDb: r.gainDb })),
    { kind: "highpass", hz: RUMBLE_HIGHPASS_HZ, q: -3 },
    { kind: "peaking", hz: MASTER_PRESENCE_CUT.hz, q: MASTER_PRESENCE_CUT.q, gainDb: MASTER_PRESENCE_CUT.gainDb },
    { kind: "highshelf", hz: MASTER_HIGH_SHELF.hz, q: 0, gainDb: MASTER_HIGH_SHELF.gainDb },
  ];
}

/** Ganho espectral |H(f)| da cadeia do motor do arquétipo. */
export function chainGainAt(archetype: EngineArchetype, f: number, rpm: number, load: number): number {
  return engineChainFilters(ARCHETYPE_PRESETS[archetype], rpm, load).reduce((g, spec) => g * biquadMagnitude(spec, f), 1);
}

const baseSpectra = new Map<EngineArchetype, Float64Array>();

/** Potência por bin do laço de pulsos saturado no ciclo de referência (DFT; resolução 25/12 Hz), em cache. */
export function pulseSpectrum(archetype: EngineArchetype): Float64Array {
  const cached = baseSpectra.get(archetype);
  if (cached) return cached;
  const preset = ARCHETYPE_PRESETS[archetype];
  const { tone } = preset;
  const signal = exhaustCycle({ pulse: preset.pulse, firingOrder: preset.reference.firingOrder, sampleRate: ANALYSIS_RATE }).map((x) =>
    saturate(x * tone.driveMax, tone.saturation, tone.asymmetry),
  );
  const n = signal.length;
  const binHz = BASE_CYCLE_HZ / LOOP_CYCLES;
  const bins = Math.floor(BASE_MAX_HZ / binHz);
  const cos = new Float64Array(n);
  const sin = new Float64Array(n);
  for (let i = 0; i < n; i += 1) {
    cos[i] = Math.cos((2 * Math.PI * i) / n);
    sin[i] = Math.sin((2 * Math.PI * i) / n);
  }
  const power = new Float64Array(bins + 1);
  for (let k = 1; k <= bins; k += 1) {
    let re = 0;
    let im = 0;
    for (let i = 0, idx = 0; i < n; i += 1, idx = (idx + k) % n) {
      re += signal[i]! * cos[idx]!;
      im -= signal[i]! * sin[idx]!;
    }
    power[k] = (re * re + im * im) / (n * n);
  }
  baseSpectra.set(archetype, power);
  return power;
}

export interface SpectrumLine {
  hz: number;
  power: number;
}

/** Linhas espectrais na saída (pulsos filtrados + sub-bass) no ponto de operação. */
export function engineOutputSpectrum(archetype: EngineArchetype, rpm: number, load: number): SpectrumLine[] {
  const preset = ARCHETYPE_PRESETS[archetype];
  const filters = engineChainFilters(preset, rpm, load);
  const binHz = (BASE_CYCLE_HZ / LOOP_CYCLES) * playbackRateFor(rpm);
  const lines: SpectrumLine[] = [];
  pulseSpectrum(archetype).forEach((p, k) => {
    const hz = k * binHz;
    if (k === 0 || hz >= FILTER_RATE / 2) return;
    const g = filters.reduce((acc, spec) => acc * biquadMagnitude(spec, hz), 1);
    lines.push({ hz, power: p * g * g });
  });
  const subHz = firingFrequencyHz(rpm, preset.reference.nCyl) * preset.tone.sub.order;
  const subAmp = preset.tone.sub.level * subLevel(subHz, load);
  if (subAmp > 0) lines.push({ hz: subHz, power: (subAmp * subAmp) / 2 });
  return lines;
}

/** Fração da energia de saída entre `lo` e `hi` Hz (padrão 1–4 kHz). */
export function bandEnergyShare(archetype: EngineArchetype, rpm: number, load: number, lo = 1000, hi = 4000): number {
  let band = 0;
  let total = 0;
  for (const { hz, power } of engineOutputSpectrum(archetype, rpm, load)) {
    total += power;
    if (hz >= lo && hz <= hi) band += power;
  }
  return total > 0 ? band / total : 0;
}
