/**
 * Datalogger (RF-17): revisão da puxada concluída com cursor, até 8 canais, export JSON/CSV
 * (`GET /api/v1/runs/{run_id}/log`), import (`POST /api/v1/logs/import`) e comparação de duas
 * puxadas (`POST /api/v1/logs/compare`) com o delta máximo por canal.
 */
import { useEffect, useMemo, useState } from "react";
import type uPlot from "uplot";

import { isApiProblem } from "@/lib/api";
import { convertPower, formatNumber, POWER_LABEL, useUnits } from "@/lib/units";

import { cockpitApi, exportRunLog, type DataLog, type LogComparison } from "./api";
import { axisStyle, CHART_COLORS, UPlotChart, type ChartOverlay } from "./charts/UPlotChart";
import { MSG } from "./messages";

export const MAX_DATALOGGER_CHANNELS = 8;
const PALETTE = ["#f59e0b", "#38bdf8", "#a78bfa", "#f87171", "#34d399", "#fb7185", "#facc15", "#22d3ee"];
const DEFAULT_CHANNELS = ["rpm", "power_kw", "torque_nm", "lambda"];

export interface RunHistoryItem {
  runId: string;
  label: string;
  state: string;
}

export interface DataloggerApi {
  getLog: (runId: string) => Promise<DataLog>;
  compareLogs: (a: string, b: string) => Promise<LogComparison>;
  importLog: (body: string) => Promise<{ log_id: string }>;
  exportLog: (runId: string, format: "json" | "csv") => Promise<string>;
}

const defaultApi: DataloggerApi = {
  getLog: cockpitApi.getLog,
  compareLogs: cockpitApi.compareLogs,
  importLog: cockpitApi.importLog,
  exportLog: (runId, format) => exportRunLog(runId, format),
};

export interface DataloggerPanelProps {
  runs: readonly RunHistoryItem[];
  api?: DataloggerApi;
  /** Cursor partilhado com a linha do tempo (s). */
  cursorT?: number | null;
  onCursorChange?: (t: number) => void;
  gaps?: readonly { fromT: number; toT: number | null }[];
  width?: number;
}

/** Índice da amostra mais próxima de `t` num vetor ordenado. */
export function nearestIndex(ts: readonly number[], t: number): number {
  if (ts.length === 0) return -1;
  let lo = 0;
  let hi = ts.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (ts[mid]! < t) lo = mid + 1;
    else hi = mid;
  }
  if (lo > 0 && Math.abs(ts[lo - 1]! - t) <= Math.abs(ts[lo]! - t)) return lo - 1;
  return lo;
}

/** Alterna um canal respeitando o teto de 8. */
export function toggleChannel(selected: readonly string[], channel: string): string[] {
  if (selected.includes(channel)) return selected.filter((c) => c !== channel);
  if (selected.length >= MAX_DATALOGGER_CHANNELS) return [...selected];
  return [...selected, channel];
}

export function DataloggerPanel({ runs, api = defaultApi, cursorT = null, onCursorChange, gaps = [], width = 720 }: DataloggerPanelProps) {
  const { units } = useUnits();
  const [runId, setRunId] = useState<string | null>(runs.at(-1)?.runId ?? null);
  const [compareId, setCompareId] = useState<string>("");
  const [log, setLog] = useState<DataLog | null>(null);
  const [selected, setSelected] = useState<string[]>(DEFAULT_CHANNELS);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [comparison, setComparison] = useState<LogComparison | null>(null);
  const [localCursor, setLocalCursor] = useState<number | null>(null);

  const latestRun = runs.at(-1)?.runId ?? null;
  const [trackedLatest, setTrackedLatest] = useState(latestRun);
  if (latestRun !== trackedLatest) {
    // Nova puxada concluída: passa a revê-la.
    setTrackedLatest(latestRun);
    setRunId(latestRun);
  }

  const run = runs.find((r) => r.runId === runId) ?? null;
  const partial = run ? run.state !== "completed" : false;
  const cursor = cursorT ?? localCursor;

  const overlay = useMemo<ChartOverlay>(() => ({ markers: cursor !== null ? [{ x: cursor, color: "#fde047" }] : [], gaps }), [cursor, gaps]);

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    api.getLog(runId).then(
      (data) => {
        if (cancelled) return;
        setLog(data);
        setError(null);
        const names = data.header.channels.map((c) => c.name);
        setSelected((prev) => {
          const kept = prev.filter((c) => names.includes(c));
          return kept.length > 0 ? kept : names.slice(0, 4);
        });
      },
      (e: unknown) => {
        if (!cancelled) setError(isApiProblem(e) ? `${e.code}: ${e.detail}` : "Falha ao carregar o log.");
      },
    );
    return () => {
      cancelled = true;
    };
  }, [runId, api]);

  const channelNames = useMemo(() => log?.header.channels.map((c) => c.name) ?? [], [log]);
  const unitOf = (name: string) => log?.header.channels.find((c) => c.name === name)?.unit ?? "";

  const options = useMemo<uPlot.Options>(
    () => ({
      width,
      height: 220,
      scales: { x: { time: false } },
      axes: [
        { ...axisStyle(), label: "t (s)" },
        ...selected.slice(0, 2).map((c, i) => ({ ...axisStyle(), scale: c, label: c, side: i === 0 ? 3 : 1, grid: { show: i === 0 } })),
      ],
      series: [{ label: "t" }, ...selected.map((c, i) => ({ label: c, scale: c, stroke: PALETTE[i % PALETTE.length]!, width: 1.5 }))],
    }),
    [selected, width],
  );

  const data = useMemo<uPlot.AlignedData>(() => {
    if (!log) return [[]];
    return [log.t_sim_s, ...selected.map((c) => log.data[c] ?? [])] as uPlot.AlignedData;
  }, [log, selected]);

  const tMin = log?.t_sim_s[0] ?? 0;
  const tMax = log?.t_sim_s.at(-1) ?? 0;
  const idx = log && cursor !== null ? nearestIndex(log.t_sim_s, cursor) : -1;

  const setCursor = (t: number) => {
    setLocalCursor(t);
    onCursorChange?.(t);
  };

  const doExport = async (format: "json" | "csv") => {
    if (!runId) return;
    try {
      const name = await api.exportLog(runId, format);
      setNotice(`Exportado: ${name}`);
    } catch (e) {
      setError(isApiProblem(e) ? `${e.code}: ${e.detail}` : "Falha ao exportar.");
    }
  };

  const doImport = async (file: File) => {
    try {
      const summary = await api.importLog(await file.text());
      setNotice(`Log importado: ${summary.log_id}`);
    } catch (e) {
      setError(isApiProblem(e) ? `${e.code}: ${e.detail}` : "Falha ao importar.");
    }
  };

  const doCompare = async () => {
    if (!runId || !compareId) return;
    try {
      setComparison(await api.compareLogs(compareId, runId));
      setError(null);
    } catch (e) {
      setError(isApiProblem(e) ? `${e.code}: ${e.detail}` : "Falha ao comparar.");
    }
  };

  const compareOptions = useMemo<uPlot.Options>(
    () => ({
      width,
      height: 180,
      scales: { x: { time: false } },
      axes: [{ ...axisStyle(), label: "RPM" }, { ...axisStyle(), label: `Potência (${POWER_LABEL[units.power]})` }],
      series: [
        { label: "RPM" },
        { label: "A", stroke: CHART_COLORS.reference, width: 1.5, dash: [8, 4] },
        { label: "B", stroke: CHART_COLORS.power, width: 2 },
      ],
    }),
    [width, units.power],
  );
  const compareData = useMemo<uPlot.AlignedData>(
    () =>
      comparison
        ? [
            comparison.bins.map((b) => b.rpm_bin),
            comparison.bins.map((b) => convertPower(b.power_kw_a, units.power)),
            comparison.bins.map((b) => convertPower(b.power_kw_b, units.power)),
          ]
        : [[]],
    [comparison, units.power],
  );

  if (runs.length === 0) {
    return <p className="text-sm text-zinc-400">Sem puxadas para rever. Conclua uma puxada para usar o datalogger.</p>;
  }

  return (
    <section aria-label="Datalogger" className="flex flex-col gap-2 text-sm">
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-1">
          Puxada
          <select aria-label="Puxada do datalogger" value={runId ?? ""} onChange={(e) => setRunId(e.target.value)} className="rounded border border-zinc-600 bg-zinc-950 px-1 py-0.5">
            {runs.map((r) => (
              <option key={r.runId} value={r.runId}>
                {r.label}
              </option>
            ))}
          </select>
        </label>
        {partial && (
          <span data-testid="partial-badge" className="rounded bg-amber-500 px-1.5 text-xs font-semibold text-zinc-950">
            {MSG.partial}
          </span>
        )}
        <button type="button" onClick={() => void doExport("csv")} className="rounded border border-zinc-500 px-2 py-0.5 hover:bg-zinc-800">
          Exportar CSV
        </button>
        <button type="button" onClick={() => void doExport("json")} className="rounded border border-zinc-500 px-2 py-0.5 hover:bg-zinc-800">
          Exportar JSON
        </button>
        <label className="cursor-pointer rounded border border-zinc-500 px-2 py-0.5 hover:bg-zinc-800">
          Importar log
          <input
            type="file"
            accept="application/json,.json"
            className="sr-only"
            aria-label="Importar log JSON"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void doImport(f);
            }}
          />
        </label>
        <label className="flex items-center gap-1">
          Comparar com
          <select aria-label="Puxada de comparação" value={compareId} onChange={(e) => setCompareId(e.target.value)} className="rounded border border-zinc-600 bg-zinc-950 px-1 py-0.5">
            <option value="">—</option>
            {runs
              .filter((r) => r.runId !== runId)
              .map((r) => (
                <option key={r.runId} value={r.runId}>
                  {r.label}
                </option>
              ))}
          </select>
        </label>
        <button type="button" disabled={!compareId} onClick={() => void doCompare()} className="rounded border border-zinc-500 px-2 py-0.5 hover:bg-zinc-800 disabled:opacity-50">
          Comparar
        </button>
      </div>
      {error && (
        <p role="alert" className="text-red-300">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="text-emerald-300">
          {notice}
        </p>
      )}
      {log && (
        <>
          <fieldset className="flex flex-wrap gap-x-3 gap-y-1">
            <legend className="mb-1 text-zinc-300">
              Canais ({selected.length}/{MAX_DATALOGGER_CHANNELS})
            </legend>
            {channelNames.map((c) => {
              const checked = selected.includes(c);
              return (
                <label key={c} className="inline-flex items-center gap-1 font-mono text-xs">
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={!checked && selected.length >= MAX_DATALOGGER_CHANNELS}
                    onChange={() => setSelected((prev) => toggleChannel(prev, c))}
                  />
                  {c}
                </label>
              );
            })}
          </fieldset>
          <UPlotChart options={options} data={data} overlay={overlay} ariaLabel="Datalogger: canais selecionados por tempo" />
          <label className="flex items-center gap-2">
            Cursor
            <input
              type="range"
              aria-label="Cursor do datalogger"
              min={tMin}
              max={tMax}
              step={0.001}
              value={cursor ?? tMin}
              onChange={(e) => setCursor(Number(e.target.value))}
              className="flex-1 accent-yellow-300"
            />
            <span data-testid="datalogger-cursor" className="w-20 font-mono">
              {formatNumber(cursor ?? tMin, 2)} s
            </span>
          </label>
          {idx >= 0 && (
            <table className="font-mono text-xs" aria-label="Valores no cursor">
              <tbody>
                {selected.map((c) => (
                  <tr key={c}>
                    <th scope="row" className="pr-3 text-left font-normal text-zinc-300">
                      {c}
                    </th>
                    <td>
                      {log.data[c]?.[idx] ?? "–"} {unitOf(c)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
      {comparison && (
        <div data-testid="comparison">
          <UPlotChart options={compareOptions} data={compareData} ariaLabel="Comparação de potência entre duas puxadas" />
          <p className="font-mono text-xs">
            Pico A {formatNumber(comparison.peak_whp_a, 1)} whp · Pico B {formatNumber(comparison.peak_whp_b, 1)} whp · Δ {formatNumber(comparison.delta_peak_whp_pct, 1)} %
          </p>
          <table aria-label="Delta máximo por canal" className="font-mono text-xs">
            <tbody>
              {Object.entries(comparison.max_abs_delta).map(([k, v]) => (
                <tr key={k}>
                  <th scope="row" className="pr-3 text-left font-normal text-zinc-300">
                    Δ máx. {k}
                  </th>
                  <td>{formatNumber(v, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
