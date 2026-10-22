/**
 * Efeitos visuais por modo de falha (RF-21; D-12): tipo de fumaça, fagulhas, detritos e brilho
 * térmico de cada `event.failure.mode`.
 */
import type { FAILURE_MODES } from "@/lib/ws";

export type FailureMode = (typeof FAILURE_MODES)[number];

export type ParticleTone =
  | "flame"
  | "flameCore"
  | "spark"
  | "sparkOrange"
  | "smokeGrey"
  | "smokeBlue"
  | "smokeLight"
  | "smokeOil"
  | "smokeWhite"
  | "smokeBlack"
  | "debris"
  | "debrisMetal";

/** Ponto de emissão no carro. */
export type EmitPoint = "engine" | "exhaust" | "turbo";

export interface FailureFx {
  debris: number;
  debrisTone: ParticleTone;
  sparks: number;
  sparkTone: ParticleTone;
  sparkAt: EmitPoint;
  smokeTone: ParticleTone;
  smokeAt: EmitPoint;
  /** Partículas de fumaça por passo da animação. */
  smokePerStep: number;
  smokeSize: number;
  /** Brilho térmico inicial no coletor/turbina (0..1). */
  heat: number;
}

/** Explosão genérica (modo desconhecido): o comportamento da feature 001. */
export const DEFAULT_FAILURE_FX: FailureFx = {
  debris: 40,
  debrisTone: "debris",
  sparks: 0,
  sparkTone: "spark",
  sparkAt: "engine",
  smokeTone: "smokeGrey",
  smokeAt: "engine",
  smokePerStep: 3,
  smokeSize: 8,
  heat: 0,
};

const KNOCK_FX: FailureFx = { ...DEFAULT_FAILURE_FX, debris: 18, sparks: 16, smokeTone: "smokeBlue" };

export const FAILURE_FX: Readonly<Record<FailureMode, FailureFx>> = {
  knock_damage: KNOCK_FX,
  pre_ignition: { ...KNOCK_FX, sparks: 22 },
  egt_overtemp: { ...DEFAULT_FAILURE_FX, debris: 8, sparks: 8, sparkAt: "turbo", smokeTone: "smokeLight", smokeAt: "turbo", heat: 1 },
  rod_failure: { ...DEFAULT_FAILURE_FX, debris: 48, debrisTone: "debrisMetal", sparks: 12, smokeTone: "smokeOil", smokePerStep: 4, smokeSize: 10 },
  piston_failure: { ...DEFAULT_FAILURE_FX, debris: 10, smokeTone: "smokeWhite", smokeAt: "exhaust", smokePerStep: 5, smokeSize: 10 },
  turbo_meltdown: {
    ...DEFAULT_FAILURE_FX,
    debris: 16,
    debrisTone: "debrisMetal",
    sparks: 30,
    sparkTone: "sparkOrange",
    sparkAt: "turbo",
    smokeTone: "smokeBlack",
    smokeAt: "turbo",
    smokePerStep: 4,
    heat: 0.8,
  },
};

export function failureFxFor(mode: string | null | undefined): FailureFx {
  return (mode && FAILURE_FX[mode as FailureMode]) || DEFAULT_FAILURE_FX;
}

/** Cor base e opacidade máxima de cada tom (estilos fixos: nada de strings por frame). */
export const TONE_STYLE: Readonly<Record<ParticleTone, { color: string; alpha: number }>> = {
  flame: { color: "#fb923c", alpha: 0.9 },
  flameCore: { color: "#fef08a", alpha: 1 },
  spark: { color: "#fde047", alpha: 1 },
  sparkOrange: { color: "#f97316", alpha: 1 },
  smokeGrey: { color: "#71717a", alpha: 0.55 },
  smokeBlue: { color: "#7c93b8", alpha: 0.5 },
  smokeLight: { color: "#d4d4d8", alpha: 0.45 },
  smokeOil: { color: "#27272a", alpha: 0.7 },
  smokeWhite: { color: "#f4f4f5", alpha: 0.7 },
  smokeBlack: { color: "#0c0a09", alpha: 0.75 },
  debris: { color: "#d4d4d8", alpha: 1 },
  debrisMetal: { color: "#a8a29e", alpha: 1 },
};
