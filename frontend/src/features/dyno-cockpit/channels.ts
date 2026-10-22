/**
 * Canais por painel e subscrição (dyno-cockpit-ui §8 "Comportamento esperado";
 * contracts/websocket-telemetry.md §4.1 e §5).
 */
import type { TelemetrySubscription } from "@/lib/ws";

import type { PanelId } from "./prefs";

export const PANEL_CHANNELS: Record<PanelId, readonly string[]> = {
  dyno: ["rpm", "power_kw", "torque_nm"],
  "lambda-egt": ["rpm", "lambda", "egt_c"],
  gauges: ["rpm", "map_kpa", "baro_kpa", "lambda", "egt_c", "iat_c", "ect_c", "knock_retard_deg"],
  car: ["rpm", "roller_speed_kmh", "overrun_afterfire", "throttle_pct"],
  spectrogram: ["knock_retard_deg"],
  pressure: ["rpm"],
  events: ["rpm"],
  datalogger: ["rpm"],
};

/** Canais extra do carro no rolo com a Visão Térmica / Raio-X ligada (RF-21). */
export const THERMAL_CHANNELS: readonly string[] = ["egt_c", "egt_pre_turbo_c"];

export const AUDIO_CHANNELS: readonly string[] = ["rpm", "turbo_rpm", "throttle_pct", "map_kpa", "baro_kpa", "overrun_afterfire"];

/** Canais por cilindro do espectrograma: `knock_sensor_v_cyl<k>` e `knock_intensity_cyl<k>`. */
export function perCylinderChannels(base: string, nCyl: number): string[] {
  return Array.from({ length: nCyl }, (_, i) => `${base}_cyl${i + 1}`);
}

export interface SubscriptionInput {
  visiblePanels: readonly PanelId[];
  nCyl: number;
  audioActive: boolean;
  pressureCylinder: number;
  /** Visão térmica ligada: o carro (se visível) pede as EGT. */
  thermalView?: boolean;
  dataloggerChannels?: readonly string[];
  /** Canais pedidos por painéis acoplados (ex.: Live Tuning na tela dividida). */
  extraChannels?: readonly string[];
  /** Resolução abaixo do mínimo: subscrição reduzida (EC-11). */
  reduced?: boolean;
  fps?: number;
}

/** União dos canais dos painéis visíveis mais o áudio (se ativo). Ordem estável, sem repetição. */
export function buildSubscription(input: SubscriptionInput): TelemetrySubscription {
  const channels = new Set<string>();
  if (input.reduced) {
    // Eventos e run.state chegam sem filtro; o mínimo de 1 canal mantém a subscrição válida.
    return { channels: ["rpm"], fps: input.fps ?? 50, spectrum: false, pressure_trace: null };
  }
  for (const panel of input.visiblePanels) {
    for (const ch of PANEL_CHANNELS[panel]) channels.add(ch);
  }
  const spectrum = input.visiblePanels.includes("spectrogram");
  if (spectrum) {
    for (const ch of perCylinderChannels("knock_intensity", input.nCyl)) channels.add(ch);
    for (const ch of perCylinderChannels("knock_sensor_v", input.nCyl)) channels.add(ch);
  }
  if (input.visiblePanels.includes("datalogger")) {
    for (const ch of input.dataloggerChannels ?? []) channels.add(ch);
  }
  if (input.thermalView && input.visiblePanels.includes("car")) for (const ch of THERMAL_CHANNELS) channels.add(ch);
  if (input.audioActive) for (const ch of AUDIO_CHANNELS) channels.add(ch);
  for (const ch of input.extraChannels ?? []) channels.add(ch);
  const pressure = input.visiblePanels.includes("pressure");
  return {
    channels: [...channels].slice(0, 128),
    fps: input.fps ?? 50,
    spectrum,
    pressure_trace: pressure ? { cylinder: input.pressureCylinder } : null,
  };
}

export function subscriptionKey(sub: TelemetrySubscription): string {
  return JSON.stringify([[...sub.channels].sort(), sub.fps, sub.spectrum, sub.pressure_trace]);
}
