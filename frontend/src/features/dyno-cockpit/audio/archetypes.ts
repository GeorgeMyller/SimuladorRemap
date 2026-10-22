/**
 * Arquétipos de timbre do motor (002 RF-20 / D-11; 003 RF-10 / D-05). Cada preset descreve o pulso
 * de exaustão, a coloração (saturação, passa-baixa, ressonadores do abafador, sub-bass) e as vozes
 * de indução. Nenhum preset concentra energia entre 1 kHz e 4 kHz (ver `spectrum.ts`).
 */
export const ENGINE_ARCHETYPES = ["i4_turbo_modern", "i6_turbo", "i4_turbo_classic", "v8_supercharged"] as const;
export type EngineArchetype = (typeof ENGINE_ARCHETYPES)[number];

export type Architecture = "inline" | "v";
export type Induction = "turbo" | "supercharger" | "natural";

/** Forma do pulso de exaustão (frações do intervalo entre ignições). */
export interface ExhaustPulse {
  /** Largura do pulso em fração do intervalo entre ignições. */
  widthFrac: number;
  /** Expoentes da forma beta `u^a · (1 − u)^b`: subida rápida (`a`) e cauda longa (`b`). */
  rise: number;
  fall: number;
  /** Turbulência da combustão dentro do pulso (0..1). */
  noiseMix: number;
  /** Escala da assinatura por cilindro (1 = ±8 % de `firingPulseGains`). */
  cylinderSpread: number;
  /** Jitter ciclo a ciclo: amplitude (fração) e instante (fração do intervalo). */
  ampJitter: number;
  timeJitter: number;
  /** Segunda bancada da cambota cross-plane: atraso, ganho e largura relativos. */
  bank: { delayFrac: number; gain: number; widthMul: number } | null;
}

export interface Resonator {
  hz: number;
  q: number;
  gainDb: number;
}

export interface ToneShape {
  /** Curvatura da saturação tanh e assimetria (harmônicos pares, estilo válvula). */
  saturation: number;
  asymmetry: number;
  /** Ganho de entrada da saturação: mínimo (sem carga) e máximo (WOT). */
  driveMin: number;
  driveMax: number;
  /** Q do passa-baixa em dB (convenção Web Audio). */
  lowpassQDb: number;
  /** Expoente sobre a posição rpm/carga (> 1 = timbre mais escuro). */
  cutoffCurve: number;
  /** Ressonadores do abafador: grave (90–140 Hz) e médio (280–450 Hz). */
  resonators: readonly [Resonator, Resonator];
  /** Sub-bass: ordem da ignição e nível relativo. */
  sub: { order: number; level: number };
}

export interface TurboVoice {
  /** Escala da banda do spool (turbinas pequenas soam mais agudas). */
  spoolScale: number;
  level: number;
  /** Harmônico agudo (banda estreita em 2× a do spool), muito discreto. */
  harmonicLevel: number;
  spoolQ: number;
  wastegateLevel: number;
  wastegateHz: number;
  blowoff: { level: number; hz: number; q: number };
  /** Flutter/chirp do compressor ao fechar a borboleta com boost. */
  flutter: { level: number; rateHz: number; cycles: number; hz: number };
}

export interface WhineVoice {
  lobes: number;
  level: number;
  defaultPulleyRatio: number;
  q: number;
}

/** Lope de came na marcha lenta: modulação lenta e irregular de amplitude e frequência. */
export interface CamLope {
  depth: number;
  fmDepth: number;
  rateHz: number;
  fadeRpm: number;
}

export interface ArchetypePreset {
  pulse: ExhaustPulse;
  tone: ToneShape;
  /** Constante de tempo do nível do motor (s): maior = resposta mais macia. */
  responseS: number;
  turbo: TurboVoice | null;
  camLope: CamLope | null;
  whine: WhineVoice | null;
  /** Motor de referência (análise espectral e testes). */
  reference: { nCyl: number; firingOrder: readonly number[] };
}

/** Voz de turbo usada quando o motor tem turbo mas o arquétipo não define uma. */
export const DEFAULT_TURBO: TurboVoice = {
  spoolScale: 1,
  level: 0.9,
  harmonicLevel: 0.06,
  spoolQ: 2.2,
  wastegateLevel: 0,
  wastegateHz: 5000,
  blowoff: { level: 0.35, hz: 1300, q: 0.9 },
  flutter: { level: 0.12, rateHz: 15, cycles: 3, hz: 720 },
};

export const ARCHETYPE_PRESETS: Readonly<Record<EngineArchetype, ArchetypePreset>> = {
  /** 2.0 GDI turbo: pulso médio, ronco firme a 125 Hz, spool mais agudo e BOV recirculante. */
  i4_turbo_modern: {
    pulse: { widthFrac: 0.42, rise: 2, fall: 3.2, noiseMix: 0.22, cylinderSpread: 0.6, ampJitter: 0.05, timeJitter: 0.012, bank: null },
    tone: {
      saturation: 1.8,
      asymmetry: 0.18,
      driveMin: 0.55,
      driveMax: 0.95,
      lowpassQDb: -1,
      cutoffCurve: 1,
      resonators: [
        { hz: 125, q: 1.4, gainDb: 4 },
        { hz: 400, q: 2, gainDb: 2.5 },
      ],
      sub: { order: 1, level: 0.14 },
    },
    responseS: 0.03,
    turbo: { ...DEFAULT_TURBO, spoolScale: 1.25, level: 1, harmonicLevel: 0.08, spoolQ: 2.4, blowoff: { level: 0.4, hz: 1300, q: 0.9 }, flutter: { level: 0.15, rateHz: 16, cycles: 4, hz: 750 } },
    camLope: null,
    whine: null,
    reference: { nCyl: 4, firingOrder: [1, 3, 4, 2] },
  },
  /** 3.0 I6 turbo: pulsos largos e sobrepostos (quase senoidal), timbre escuro e liso. */
  i6_turbo: {
    pulse: { widthFrac: 0.6, rise: 2.2, fall: 2.8, noiseMix: 0.12, cylinderSpread: 0.3, ampJitter: 0.025, timeJitter: 0.006, bank: null },
    tone: {
      saturation: 1.4,
      asymmetry: 0.08,
      driveMin: 0.5,
      driveMax: 0.85,
      lowpassQDb: -3,
      cutoffCurve: 1.12,
      resonators: [
        { hz: 110, q: 1.2, gainDb: 3.5 },
        { hz: 330, q: 1.6, gainDb: 2 },
      ],
      sub: { order: 1, level: 0.1 },
    },
    responseS: 0.06,
    turbo: { ...DEFAULT_TURBO, spoolScale: 0.9, level: 0.85, harmonicLevel: 0.05, spoolQ: 2, blowoff: { level: 0.3, hz: 1150, q: 0.8 }, flutter: { level: 0.1, rateHz: 14, cycles: 3, hz: 680 } },
    camLope: null,
    whine: null,
    reference: { nCyl: 6, firingOrder: [1, 5, 3, 6, 2, 4] },
  },
  /** AP turbo com comando bravo: pulsos estreitos e irregulares, lope de marcha lenta, flutter forte. */
  i4_turbo_classic: {
    pulse: { widthFrac: 0.34, rise: 1.8, fall: 3.6, noiseMix: 0.3, cylinderSpread: 1.4, ampJitter: 0.12, timeJitter: 0.025, bank: null },
    tone: {
      saturation: 2.4,
      asymmetry: 0.28,
      driveMin: 0.6,
      driveMax: 1,
      lowpassQDb: 0,
      cutoffCurve: 0.95,
      resonators: [
        { hz: 95, q: 1.6, gainDb: 5 },
        { hz: 300, q: 1.8, gainDb: 3 },
      ],
      sub: { order: 1, level: 0.18 },
    },
    responseS: 0.045,
    turbo: {
      ...DEFAULT_TURBO,
      spoolScale: 1,
      level: 1.1,
      harmonicLevel: 0.1,
      spoolQ: 2.6,
      wastegateLevel: 0.15,
      wastegateHz: 4800,
      blowoff: { level: 0.55, hz: 1600, q: 0.9 },
      flutter: { level: 0.5, rateHz: 18, cycles: 5, hz: 820 },
    },
    camLope: { depth: 0.45, fmDepth: 0.045, rateHz: 1.35, fadeRpm: 2400 },
    whine: null,
    reference: { nCyl: 4, firingOrder: [1, 3, 4, 2] },
  },
  /** V8 cross-plane com compressor: bancadas desiguais (ordens meias), ronco a 92 Hz e whine suave. */
  v8_supercharged: {
    pulse: { widthFrac: 0.5, rise: 2, fall: 3.4, noiseMix: 0.2, cylinderSpread: 0.8, ampJitter: 0.06, timeJitter: 0.012, bank: { delayFrac: 0.07, gain: 0.8, widthMul: 1.15 } },
    tone: {
      saturation: 2,
      asymmetry: 0.22,
      driveMin: 0.55,
      driveMax: 0.95,
      lowpassQDb: -1,
      cutoffCurve: 1.05,
      resonators: [
        { hz: 92, q: 1.3, gainDb: 5 },
        { hz: 290, q: 1.5, gainDb: 3 },
      ],
      sub: { order: 0.5, level: 0.2 },
    },
    responseS: 0.04,
    turbo: null,
    camLope: null,
    whine: { lobes: 6, level: 0.45, defaultPulleyRatio: 2.1, q: 9 },
    reference: { nCyl: 8, firingOrder: [1, 5, 4, 8, 6, 3, 7, 2] },
  },
};

const ARCHETYPE_BY_VEHICLE: Readonly<Record<string, EngineArchetype>> = {
  "hatch-20t-gdi": "i4_turbo_modern",
  "coupe-30t-i6": "i6_turbo",
  "classic-20t-swap": "i4_turbo_classic",
  "muscle-v8-sc": "v8_supercharged",
};

/** Arquétipo pelo `vehicle_id` do catálogo; fora dele, pelas características do motor. */
export function archetypeFor(vehicleId: string | null | undefined, engine: { nCyl: number; architecture: Architecture; induction?: Induction }): EngineArchetype {
  const known = ARCHETYPE_BY_VEHICLE[vehicleId ?? ""];
  if (known) return known;
  if (engine.induction === "supercharger" || engine.architecture === "v" || engine.nCyl >= 8) return "v8_supercharged";
  if (engine.nCyl >= 5) return "i6_turbo";
  if (/classic|swap/i.test(vehicleId ?? "")) return "i4_turbo_classic";
  return "i4_turbo_modern";
}

/** Assinatura comparável do timbre (testes e diagnóstico). */
export function toneSignature(preset: ArchetypePreset): string {
  const [low, mid] = preset.tone.resonators;
  return `${preset.pulse.widthFrac}:${low.hz}/${mid.hz}:${preset.tone.saturation}:${preset.tone.sub.order}`;
}
