/**
 * Cliente WebSocket base (`/ws/v1`). O cliente de telemetria completo
 * (envelope v1, `seq`, resume) é do componente telemetry-datalogger / dyno-cockpit-ui.
 */

/** Prefixo único do WebSocket (D-33). */
export const WS_PREFIX = "/ws/v1";

/** Versão do envelope WebSocket (`v = 1`, RF-21). */
export const WS_ENVELOPE_VERSION = 1;

/** URL absoluta `ws(s)://<host>/ws/v1/<path>` a partir da origem da página. */
export function wsUrl(path: string, origin: string = window.location.origin): string {
  const base = origin.replace(/^http/, "ws");
  const suffix = path.startsWith(`${WS_PREFIX}/`) ? path : `${WS_PREFIX}${path.startsWith("/") ? path : `/${path}`}`;
  return `${base}${suffix}`;
}

/** URL do WebSocket de telemetria de uma sessão (contracts/websocket-telemetry.md §1). */
export function telemetryUrl(sessionId: string, origin?: string): string {
  return wsUrl(`/sessions/${encodeURIComponent(sessionId)}/telemetry`, origin);
}

export * from "./envelope";
export * from "./TelemetrySocket";
