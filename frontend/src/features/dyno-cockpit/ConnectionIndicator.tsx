/**
 * Estado do WebSocket ("reconectando (n/10)", "telemetria indisponível", "perda de frames") e
 * alarmes textuais em região `aria-live` + banner, sem piscar (RF-04, RF-05, RF-21).
 */
import type { StreamStats } from "@/lib/ws";

import { MSG } from "./messages";

export const LOSS_THRESHOLD = 0.02;

export function connectionLabel(stats: Pick<StreamStats, "state" | "reconnectAttempt" | "maxAttempts">): string {
  switch (stats.state) {
    case "connecting":
      return MSG.connecting;
    case "open":
      return MSG.connected;
    case "reconnecting":
      return MSG.reconnecting(stats.reconnectAttempt, stats.maxAttempts);
    case "failed":
      return MSG.telemetryUnavailable;
    case "closed":
      return MSG.closed;
  }
}

export interface ConnectionIndicatorProps {
  stats: StreamStats;
  onRetry: () => void;
}

export function ConnectionIndicator({ stats, onRetry }: ConnectionIndicatorProps) {
  const lossy = stats.state === "open" && stats.lossRate5s > LOSS_THRESHOLD;
  const dot =
    stats.state === "open" ? "bg-emerald-400" : stats.state === "failed" ? "bg-red-500" : "bg-amber-400";
  return (
    <div className="flex items-center gap-2 text-sm" role="status" aria-label="Estado da telemetria">
      <span aria-hidden="true" className={`inline-block h-2.5 w-2.5 rounded-full ${dot}`} />
      <span data-testid="connection-state">{connectionLabel(stats)}</span>
      {lossy && (
        <span data-testid="frame-loss" className="rounded bg-amber-500 px-1.5 text-xs font-semibold text-zinc-950">
          {MSG.frameLoss} ({(stats.lossRate5s * 100).toFixed(1)} %)
        </span>
      )}
      {stats.state === "failed" && (
        <button
          type="button"
          onClick={onRetry}
          className="rounded bg-amber-500 px-2 py-0.5 text-xs font-semibold text-zinc-950 hover:bg-amber-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-white"
        >
          {MSG.retry}
        </button>
      )}
    </div>
  );
}

export interface Alarm {
  id: number;
  text: string;
  severity: "warning" | "critical";
}

/**
 * Região `aria-live="assertive"` com o último alarme e banner visual estático (sem animação de
 * piscar; atualização do banner limitada pelo chamador a ≤ 3 por segundo).
 */
export function AlarmRegion({ alarms }: { alarms: readonly Alarm[] }) {
  const latest = alarms.at(-1);
  return (
    <>
      <div aria-live="assertive" aria-atomic="true" className="sr-only" data-testid="alarm-live">
        {latest?.text ?? ""}
      </div>
      {latest && (
        <div
          data-testid="alarm-banner"
          aria-hidden="true"
          className={`rounded px-3 py-1 text-sm font-semibold ${latest.severity === "critical" ? "bg-red-800 text-white" : "bg-amber-400 text-zinc-950"}`}
        >
          {latest.text}
        </div>
      )}
    </>
  );
}
