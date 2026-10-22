/**
 * Linha do tempo de `event.knock`, `event.limiter`, `event.failure` e mudanças de `run.state`
 * com `t_sim_s`, RPM e severidade; clicar posiciona o cursor dos gráficos (RF-14).
 */
import { formatNumber } from "@/lib/units";

import { RUN_STATE_LABEL } from "./messages";
import type { Severity, TimelineEvent } from "./store";

const SEVERITY_LABEL: Record<Severity, string> = { info: "info", warning: "atenção", critical: "crítico" };
const SEVERITY_CLASS: Record<Severity, string> = {
  info: "border-zinc-500 text-zinc-200",
  warning: "border-amber-400 text-amber-200",
  critical: "border-red-500 text-red-200",
};
const KIND_LABEL = { knock: "Knock", limiter: "Limitador", failure: "Falha", run: "Puxada" } as const;

export interface EventTimelineProps {
  events: readonly TimelineEvent[];
  selectedId?: number | null;
  onSelect: (event: TimelineEvent) => void;
  locale?: string;
}

function describe(ev: TimelineEvent, locale?: string): string {
  if (ev.kind === "run" && ev.runState) return `Puxada ${RUN_STATE_LABEL[ev.runState] ?? ev.runState}`;
  if (ev.kind === "knock" && ev.cylinder) return `Knock ${ev.knockClass ?? ""} · cilindro ${ev.cylinder} · ${formatNumber(ev.retardDeg ?? 0, 1, locale)}° retardo`;
  return ev.label;
}

export function EventTimeline({ events, selectedId = null, onSelect, locale }: EventTimelineProps) {
  if (events.length === 0) {
    return <p className="text-sm text-zinc-400">Sem eventos nesta puxada.</p>;
  }
  return (
    <ol aria-label="Linha do tempo de eventos" className="max-h-56 overflow-auto text-sm">
      {events.map((ev) => {
        const selected = ev.id === selectedId;
        return (
          <li key={ev.id}>
            <button
              type="button"
              onClick={() => onSelect(ev)}
              aria-current={selected ? "true" : undefined}
              data-event-kind={ev.kind}
              className={`mb-1 flex w-full items-center gap-3 rounded border-l-4 px-2 py-1 text-left hover:bg-zinc-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-400 ${SEVERITY_CLASS[ev.severity]} ${selected ? "bg-zinc-800 ring-1 ring-yellow-300" : ""}`}
            >
              <span className="w-20 font-mono">{formatNumber(ev.t_sim_s, 2, locale)} s</span>
              <span className="w-20 font-semibold">{KIND_LABEL[ev.kind]}</span>
              <span className="flex-1">{describe(ev, locale)}</span>
              <span className="w-24 text-right font-mono">{ev.rpm !== null ? `${formatNumber(ev.rpm, 0, locale)} rpm` : "–"}</span>
              <span className="w-16 text-right text-xs">{SEVERITY_LABEL[ev.severity]}</span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
