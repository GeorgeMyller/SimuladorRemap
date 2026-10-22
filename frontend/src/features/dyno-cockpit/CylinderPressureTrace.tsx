/**
 * Pressão no cilindro (bar) vs. ângulo de cambota (−360° a +360°, 1°) do último ciclo,
 * com marcador do pico e do PMS; cilindro selecionável (RF-10).
 */
import { useEffect, useMemo, useState } from "react";
import type uPlot from "uplot";

import type { PressureTrace } from "@/lib/ws";

import { axisStyle, CHART_COLORS, UPlotChart, type ChartOverlay } from "./charts/UPlotChart";
import { MSG } from "./messages";
import type { RenderLoop } from "./render/RenderLoop";
import type { TelemetryStore } from "./store";

export const CRANK_RANGE: [number, number] = [-360, 360];

export function peakOfTrace(trace: Pick<PressureTrace, "crank_deg" | "p_bar">): { deg: number; bar: number } | null {
  if (trace.p_bar.length === 0) return null;
  let best = 0;
  for (let i = 1; i < trace.p_bar.length; i += 1) if (trace.p_bar[i]! > trace.p_bar[best]!) best = i;
  return { deg: trace.crank_deg[best]!, bar: trace.p_bar[best]! };
}

/** "pico 15° ATDC" / "pico 4° BTDC" / "pico no PMS". */
export function peakLabel(deg: number): string {
  if (deg === 0) return "pico no PMS";
  return deg > 0 ? `pico ${deg}° ATDC` : `pico ${-deg}° BTDC`;
}

export function traceToData(trace: PressureTrace | null): uPlot.AlignedData {
  if (!trace) return [[], []];
  const n = Math.min(trace.crank_deg.length, trace.p_bar.length);
  const xs: number[] = [];
  const ys: number[] = [];
  for (let i = 0; i < n; i += 1) {
    const x = trace.crank_deg[i]!;
    if (x < CRANK_RANGE[0] || x > CRANK_RANGE[1]) continue;
    xs.push(x);
    ys.push(trace.p_bar[i]!);
  }
  return [xs, ys];
}

export function buildPressureOptions(params: { width: number; height: number }): uPlot.Options {
  return {
    width: params.width,
    height: params.height,
    scales: { x: { time: false, range: CRANK_RANGE }, y: { range: (_u, _min, max) => [0, Math.max(10, max * 1.1)] } },
    axes: [
      { ...axisStyle(), label: "Ângulo de cambota (° ATDC)", scale: "x" },
      { ...axisStyle(), label: "Pressão (bar abs.)", scale: "y" },
    ],
    series: [{ label: "°" }, { label: "Pressão (bar)", stroke: CHART_COLORS.pressure, width: 2 }],
  };
}

export interface CylinderPressureTraceProps {
  nCyl: number;
  cylinder: number;
  onCylinderChange: (cyl: number) => void;
  /** Traço fixo (testes ou revisão); sem ele lê do store a ≤ 10 Hz. */
  trace?: PressureTrace | null;
  store?: TelemetryStore;
  loop?: RenderLoop;
  width?: number;
  height?: number;
}

export function CylinderPressureTrace({
  nCyl,
  cylinder,
  onCylinderChange,
  trace: fixedTrace,
  store,
  loop,
  width = 720,
  height = 220,
}: CylinderPressureTraceProps) {
  const [liveTrace, setLiveTrace] = useState<PressureTrace | null>(null);
  const trace = fixedTrace !== undefined ? fixedTrace : liveTrace;
  const peak = useMemo(() => (trace ? peakOfTrace(trace) : null), [trace]);
  const overlay = useMemo<ChartOverlay>(
    () => ({
      markers: [{ x: 0, color: "#a1a1aa", label: "PMS" }, ...(peak ? [{ x: peak.deg, color: "#fde047", label: peakLabel(peak.deg) }] : [])],
    }),
    [peak],
  );
  const options = useMemo(() => buildPressureOptions({ width, height }), [width, height]);
  const data = useMemo(() => traceToData(trace), [trace]);

  // Leitura do traço ao vivo a ≤ 10 Hz (RF-21 do datalogger; EC-12).
  useEffect(() => {
    if (fixedTrace !== undefined || !loop || !store) return;
    let lastAt = -Infinity;
    let lastTrace: PressureTrace | null = null;
    return loop.add((now) => {
      if (now - lastAt < 100) return;
      lastAt = now;
      if (store.pressureTrace !== lastTrace) {
        lastTrace = store.pressureTrace;
        setLiveTrace(lastTrace);
      }
    });
  }, [fixedTrace, loop, store]);

  const mismatch = trace && trace.cylinder !== cylinder;

  return (
    <figure aria-labelledby="pressure-title" className="m-0">
      <figcaption id="pressure-title" className="mb-1 flex flex-wrap items-center gap-3 text-sm text-zinc-200">
        <span className="font-semibold">Pressão no cilindro</span>
        <label className="flex items-center gap-1 text-xs">
          Cilindro
          <select
            aria-label="Cilindro do traço de pressão"
            value={cylinder}
            onChange={(e) => onCylinderChange(Number(e.target.value))}
            className="rounded border border-zinc-600 bg-zinc-900 px-1 py-0.5 text-zinc-100"
          >
            {Array.from({ length: nCyl }, (_, i) => (
              <option key={i + 1} value={i + 1}>
                {i + 1}
              </option>
            ))}
          </select>
        </label>
        {peak && (
          <span data-testid="pressure-peak" className="font-mono text-amber-300">
            {peakLabel(peak.deg)} · {peak.bar.toFixed(1)} bar
          </span>
        )}
        {!trace && <span className="text-xs text-zinc-400">{MSG.noData("cyl_pressure_trace")}</span>}
        {mismatch && <span className="text-xs text-zinc-400">a aguardar o cilindro {cylinder}</span>}
      </figcaption>
      <UPlotChart
        options={options}
        data={data}
        overlay={overlay}
        ariaLabel={`Pressão no cilindro ${cylinder} por ângulo de cambota`}
      />
    </figure>
  );
}
