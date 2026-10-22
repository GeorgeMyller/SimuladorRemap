/**
 * Laudo forense em modal de tela cheia (RF-15, RF-16; EC-07): diagrama do motor com os componentes
 * danificados destacados por `component_id` (`piston:3`, `rod:2`, `valves:1`, `head_gasket`,
 * `bearings`, `turbo:turbine`), modo de falha, cadeia causal ordenada no tempo e recomendações.
 */
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { isApiProblem } from "@/lib/api";
import { formatNumber } from "@/lib/units";
import type { FailureEventPayload } from "@/lib/ws";

import { fetchForensicReportWithRetry, type ForensicReport } from "./api";
import { Dialog } from "./Dialog";
import { FAILURE_MODE_LABEL, MSG } from "./messages";

export type ComponentState = "failed" | "damaged" | "ok";

/** Estado de cada `component_id` a partir do laudo e/ou do `FailureEvent` bruto. */
export function componentStates(report: ForensicReport | null, failure: FailureEventPayload | null): Map<string, ComponentState> {
  const map = new Map<string, ComponentState>();
  for (const c of report?.damaged_components ?? []) {
    map.set(c.component_id, c.failed || c.health <= 0 ? "failed" : c.health < 1 ? "damaged" : "ok");
  }
  const failedId = report?.failure_event?.component_id ?? failure?.component_id;
  if (failedId) map.set(failedId, "failed");
  return map;
}

const FILL: Record<ComponentState, string> = { failed: "#dc2626", damaged: "#f59e0b", ok: "#52525b" };
const STATE_LABEL: Record<ComponentState, string> = { failed: "destruído", damaged: "danificado", ok: "íntegro" };

const COMPONENT_LABEL = (id: string): string => {
  const [kind, idx] = id.split(":");
  const names: Record<string, string> = {
    piston: "Pistão",
    rod: "Biela",
    valves: "Válvulas",
    head_gasket: "Junta do cabeçote",
    bearings: "Bronzinas",
    turbo: "Turbina",
  };
  const name = names[kind ?? ""] ?? id;
  return idx && kind !== "turbo" ? `${name} ${idx}` : name;
};

export interface EngineDiagramProps {
  nCyl: number;
  turbo: boolean;
  states: Map<string, ComponentState>;
}

export function EngineDiagram({ nCyl, turbo, states }: EngineDiagramProps) {
  const pitch = 70;
  const width = 40 + nCyl * pitch + (turbo ? 110 : 20);
  const st = (id: string): ComponentState => states.get(id) ?? "ok";
  const part = (id: string, el: (fill: string) => ReactNode) => (
    <g key={id} data-component-id={id} data-state={st(id)}>
      <title>{`${COMPONENT_LABEL(id)}: ${STATE_LABEL[st(id)]}`}</title>
      {el(FILL[st(id)])}
    </g>
  );
  return (
    <svg viewBox={`0 0 ${width} 260`} width="100%" role="img" aria-label="Diagrama do motor com componentes danificados" className="max-h-72">
      {part("head_gasket", (fill) => (
        <rect x={20} y={58} width={nCyl * pitch} height={8} fill={fill} />
      ))}
      {Array.from({ length: nCyl }, (_, i) => {
        const k = i + 1;
        const x = 30 + i * pitch;
        return (
          <g key={k}>
            <rect x={x - 4} y={70} width={pitch - 12} height={110} fill="none" stroke="#a1a1aa" strokeWidth={2} />
            {part(`valves:${k}`, (fill) => (
              <>
                <rect x={x + 6} y={30} width={12} height={26} fill={fill} />
                <rect x={x + pitch - 34} y={30} width={12} height={26} fill={fill} />
              </>
            ))}
            {part(`piston:${k}`, (fill) => (
              <rect x={x} y={96} width={pitch - 20} height={32} rx={3} fill={fill} />
            ))}
            {part(`rod:${k}`, (fill) => (
              <line x1={x + (pitch - 20) / 2} y1={128} x2={x + (pitch - 20) / 2} y2={206} stroke={fill} strokeWidth={8} strokeLinecap="round" />
            ))}
            <text x={x + (pitch - 20) / 2} y={90} textAnchor="middle" fontSize={12} fill="#e4e4e7">
              {k}
            </text>
          </g>
        );
      })}
      {part("bearings", (fill) => (
        <rect x={20} y={206} width={nCyl * pitch} height={14} rx={7} fill={fill} />
      ))}
      {turbo &&
        part("turbo:turbine", (fill) => (
          <>
            <circle cx={40 + nCyl * pitch + 45} cy={120} r={34} fill={fill} />
            <text x={40 + nCyl * pitch + 45} y={170} textAnchor="middle" fontSize={12} fill="#e4e4e7">
              turbo
            </text>
          </>
        ))}
    </svg>
  );
}

export interface EngineAutopsyViewProps {
  runId: string;
  nCyl: number;
  turbo: boolean;
  failure: FailureEventPayload | null;
  onClose: () => void;
  onRestore: () => Promise<void>;
  loadReport?: (runId: string) => Promise<ForensicReport>;
  locale?: string;
}

type ReportState = { status: "loading" } | { status: "ok"; report: ForensicReport } | { status: "error"; message: string };

export function EngineAutopsyView({ runId, nCyl, turbo, failure, onClose, onRestore, loadReport = fetchForensicReportWithRetry, locale }: EngineAutopsyViewProps) {
  const [state, setState] = useState<ReportState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [restoring, setRestoring] = useState(false);
  const [restoreError, setRestoreError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    loadReport(runId).then(
      (report) => {
        if (!cancelled) setState({ status: "ok", report });
      },
      (error: unknown) => {
        if (!cancelled) setState({ status: "error", message: isApiProblem(error) ? `${error.code}: ${error.detail}` : MSG.reportUnavailable });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [runId, attempt, loadReport]);

  const retry = useCallback(() => {
    setState({ status: "loading" });
    setAttempt((a) => a + 1);
  }, []);

  const restore = async () => {
    setRestoring(true);
    setRestoreError(null);
    try {
      await onRestore();
    } catch (error) {
      setRestoreError(isApiProblem(error) ? `${error.title}: ${error.detail}` : "Falha ao restaurar o motor.");
    } finally {
      setRestoring(false);
    }
  };

  const report = state.status === "ok" ? state.report : null;
  const states = componentStates(report, failure);
  const mode = report?.primary_mode ?? report?.failure_event?.mode ?? failure?.mode ?? null;
  const chain = report ? [...report.causal_chain].sort((a, b) => a.t_sim_s - b.t_sim_s || a.order - b.order) : [];
  const text = report?.texts.beginner ?? report?.texts.intermediate ?? Object.values(report?.texts ?? {})[0];
  const damaged = [...states.entries()].filter(([, s]) => s !== "ok");

  return (
    <Dialog titleId="autopsy-title" title={`Laudo forense${mode ? `: ${FAILURE_MODE_LABEL[mode] ?? mode}` : ""}`} onClose={onClose} fullScreen>
      <div className="grid gap-4 lg:grid-cols-2">
        <section aria-labelledby="autopsy-diagram">
          <h3 id="autopsy-diagram" className="mb-2 font-semibold">
            Diagrama do motor
          </h3>
          <EngineDiagram nCyl={nCyl} turbo={turbo} states={states} />
          <ul aria-label="Componentes danificados" className="mt-2 text-sm">
            {damaged.map(([id, s]) => (
              <li key={id} data-damaged-id={id} className={s === "failed" ? "text-red-300" : "text-amber-200"}>
                {COMPONENT_LABEL(id)} — {STATE_LABEL[s]}
              </li>
            ))}
          </ul>
          <div className="mt-4 flex gap-2">
            <button
              type="button"
              onClick={() => void restore()}
              disabled={restoring}
              className="rounded bg-emerald-500 px-3 py-1.5 font-semibold text-zinc-950 hover:bg-emerald-400 disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-white"
            >
              {restoring ? "A restaurar…" : MSG.restoreEngine}
            </button>
          </div>
          {restoreError && (
            <p role="alert" className="mt-2 text-sm text-red-300">
              {restoreError}
            </p>
          )}
        </section>
        <section aria-labelledby="autopsy-chain" aria-busy={state.status === "loading"}>
          {state.status === "loading" && <p role="status">A carregar o laudo…</p>}
          {state.status === "error" && (
            <div role="alert" className="mb-3 rounded border border-red-500 p-2 text-sm">
              <p className="font-semibold">{MSG.reportUnavailable}</p>
              <p className="font-mono text-xs text-zinc-300">{state.message}</p>
              {failure && (
                <pre data-testid="raw-failure" className="mt-2 overflow-auto whitespace-pre-wrap text-xs text-zinc-200">
                  {JSON.stringify(failure, null, 2)}
                </pre>
              )}
              <button type="button" onClick={retry} className="mt-2 rounded bg-amber-500 px-2 py-1 text-xs font-semibold text-zinc-950">
                {MSG.retry}
              </button>
            </div>
          )}
          {text && (
            <div className="mb-3">
              <p className="font-semibold">{text.title}</p>
              <p className="text-sm text-zinc-200">{text.summary}</p>
            </div>
          )}
          <h3 id="autopsy-chain" className="mb-1 font-semibold">
            Cadeia causal
          </h3>
          {report && (
            <ol aria-label="Cadeia causal" className="mb-3 list-decimal pl-5 text-sm">
              {chain.map((link) => (
                <li key={`${link.order}-${link.t_sim_s}`} data-causal-order={link.order} className="mb-1">
                  <span className="font-mono text-amber-300">{formatNumber(link.t_sim_s, 2, locale)} s</span>{" "}
                  <span className="font-mono">
                    {link.variable} = {formatNumber(link.value, 2, locale)} {link.unit}
                    {link.threshold !== null && link.threshold !== undefined ? ` (limiar ${formatNumber(link.threshold, 2, locale)} ${link.unit})` : ""}
                  </span>
                  {link.cylinder ? ` · cil. ${link.cylinder}` : ""}
                  <br />
                  <span className="text-zinc-300">{link.description}</span>
                </li>
              ))}
            </ol>
          )}
          {report && report.recommendations.length > 0 && (
            <>
              <h3 className="mb-1 font-semibold">Recomendações</h3>
              <ul className="list-disc pl-5 text-sm">
                {report.recommendations.map((r) => (
                  <li key={r.rule_id} className="mb-1">
                    <span className="font-semibold">{r.action}</span>
                    {r.region ? <span className="text-zinc-300"> ({r.region})</span> : null}
                    <br />
                    <span className="text-zinc-300">{r.rationale}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      </div>
    </Dialog>
  );
}
