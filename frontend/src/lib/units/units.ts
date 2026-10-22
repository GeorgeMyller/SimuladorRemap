/**
 * Conversões e formatação de unidades (dyno-cockpit-ui RF-20, §9 "Conversões de unidade").
 * Partilhado com ecu-tuning-ui (premissa OQ-05).
 */

export type PowerUnit = "whp" | "cv" | "kW";
export type BoostUnit = "bar" | "psi";

export interface UnitsPrefs {
  power: PowerUnit;
  boost: BoostUnit;
  temperature: "C";
  torque: "Nm";
}

export const DEFAULT_UNITS: UnitsPrefs = { power: "whp", boost: "bar", temperature: "C", torque: "Nm" };

export const POWER_UNITS: readonly PowerUnit[] = ["whp", "cv", "kW"];
export const BOOST_UNITS: readonly BoostUnit[] = ["bar", "psi"];

const KW_PER_HP = 0.7457;
const KW_PER_CV = 0.7355;
const PSI_PER_BAR = 14.5038;

/** Converte potência de roda em kW para a unidade escolhida. */
export function convertPower(powerKw: number, unit: PowerUnit): number {
  switch (unit) {
    case "whp":
      return powerKw / KW_PER_HP;
    case "cv":
      return powerKw / KW_PER_CV;
    case "kW":
      return powerKw;
  }
}

/** Boost relativo em bar: `(map_kpa − baro_kpa) / 100` (negativo = vácuo). */
export function boostBar(mapKpa: number, baroKpa: number): number {
  return (mapKpa - baroKpa) / 100;
}

export function convertBoost(boostInBar: number, unit: BoostUnit): number {
  return unit === "bar" ? boostInBar : boostInBar * PSI_PER_BAR;
}

export const POWER_LABEL: Record<PowerUnit, string> = { whp: "whp", cv: "cv", kW: "kW" };
export const BOOST_LABEL: Record<BoostUnit, string> = { bar: "bar", psi: "psi" };

/** Casas decimais de exibição por grandeza. */
export const DECIMALS = {
  power: 1,
  torque: 1,
  lambda: 2,
  temperature: 0,
  rpm: 0,
  boost: { bar: 2, psi: 1 } as Record<BoostUnit, number>,
} as const;

/** Locale do navegador (fallback pt-BR). */
export function browserLocale(): string {
  if (typeof navigator !== "undefined" && navigator.language) return navigator.language;
  return "pt-BR";
}

const formatters = new Map<string, Intl.NumberFormat>();

/** Formata com casas fixas e a locale indicada (padrão: a do navegador). */
export function formatNumber(value: number, decimals: number, locale: string = browserLocale()): string {
  const key = `${locale}|${decimals}`;
  let fmt = formatters.get(key);
  if (!fmt) {
    fmt = new Intl.NumberFormat(locale, {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
      useGrouping: false,
    });
    formatters.set(key, fmt);
  }
  // Evita "-0" em valores arredondados a zero.
  const rounded = Number(value.toFixed(decimals));
  return fmt.format(Object.is(rounded, -0) ? 0 : rounded);
}

export function formatPower(powerKw: number, unit: PowerUnit, locale?: string): string {
  return `${formatNumber(convertPower(powerKw, unit), DECIMALS.power, locale)} ${POWER_LABEL[unit]}`;
}

export function formatTorque(torqueNm: number, locale?: string): string {
  return `${formatNumber(torqueNm, DECIMALS.torque, locale)} N·m`;
}

export function formatBoost(boostInBar: number, unit: BoostUnit, locale?: string): string {
  return `${formatNumber(convertBoost(boostInBar, unit), DECIMALS.boost[unit], locale)} ${BOOST_LABEL[unit]}`;
}

export function formatTemperature(celsius: number, locale?: string): string {
  return `${formatNumber(celsius, DECIMALS.temperature, locale)} °C`;
}

export function formatLambda(lambda: number, locale?: string): string {
  return formatNumber(lambda, DECIMALS.lambda, locale);
}

export function formatRpm(rpm: number, locale?: string): string {
  return `${formatNumber(rpm, DECIMALS.rpm, locale)} rpm`;
}

export function formatDegrees(deg: number, decimals = 1, locale?: string): string {
  return `${formatNumber(deg, decimals, locale)}°`;
}

export function formatSeconds(s: number, locale?: string): string {
  return `${formatNumber(s, 2, locale)} s`;
}
