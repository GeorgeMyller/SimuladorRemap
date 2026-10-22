/**
 * Potência (eixo esquerdo) e torque (eixo direito) vs. RPM, com sobreposição da puxada de
 * comparação (tracejada) e da curva de referência do veículo (pontilhada) (RF-06; D-22).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type uPlot from "uplot";

import { convertPower, formatNumber, POWER_LABEL, type PowerUnit } from "@/lib/units";

import type { CurvePoint, ReferenceCurve } from "./api";
import { alignXY, axisStyle, CHART_COLORS, UPlotChart, type ChartOverlay, type XY } from "./charts/UPlotChart";
import { MSG } from "./messages";
import type { RenderLoop } from "./render/RenderLoop";
import type { TelemetryStore } from "./store";

export interface PowerTorqueSeries {
  rpm: ArrayLike<number>;
  power_kw: ArrayLike<number>;
  torque_nm: ArrayLike<number>;
}

export interface DynoChartProps {
  /** Curva final do `DynoRun` (fonte da verdade); substitui o traço ao vivo. */
  finalCurve?: readonly CurvePoint[] | null;
  comparison?: { label: string; curve: readonly CurvePoint[] } | null;
  reference?: ReferenceCurve | null;
  powerUnit: PowerUnit;
  rpmRange: [number, number];
  /** Picos de referência (kW, N·m) para as escalas padrão (1,2 × pico). */
  peakRef: { power_kw: number; torque_nm: number };
  store?: TelemetryStore;
  loop?: RenderLoop;
  cursorRpm?: number | null;
  width?: number;
  height?: number;
}

export function curveToSeries(curve: readonly CurvePoint[]): PowerTorqueSeries {
  return {
    rpm: curve.map((p) => p.rpm),
    power_kw: curve.map((p) => p.power_wheel_kw),
    torque_nm: curve.map((p) => p.torque_engine_nm),
  };
}

export function referenceToSeries(ref: ReferenceCurve): PowerTorqueSeries {
  return {
    rpm: ref.points.map((p) => p.rpm),
    power_kw: ref.points.map((p) => p.power_wheel_kw ?? Number.NaN),
    torque_nm: ref.points.map((p) => p.torque_crank_nm ?? Number.NaN),
  };
}

function convertSeries(values: ArrayLike<number>, unit: PowerUnit): Float64Array {
  const out = new Float64Array(values.length);
  for (let i = 0; i < values.length; i += 1) out[i] = convertPower(values[i]!, unit);
  return out;
}

/** Dados alinhados: [rpm, P atual, T atual, P comparação, T comparação, P ref, T ref]. */
export function buildDynoData(
  current: PowerTorqueSeries | null,
  comparison: PowerTorqueSeries | null,
  reference: PowerTorqueSeries | null,
  unit: PowerUnit,
): uPlot.AlignedData {
  const xy = (s: PowerTorqueSeries | null, key: "power_kw" | "torque_nm"): XY | null =>
    s ? { x: s.rpm, y: key === "power_kw" ? convertSeries(s.power_kw, unit) : s.torque_nm } : null;
  return alignXY([
    xy(current, "power_kw"),
    xy(current, "torque_nm"),
    xy(comparison, "power_kw"),
    xy(comparison, "torque_nm"),
    xy(reference, "power_kw"),
    xy(reference, "torque_nm"),
  ]);
}

export function buildDynoOptions(params: {
  powerUnit: PowerUnit;
  rpmRange: [number, number];
  peakRef: { power_kw: number; torque_nm: number };
  comparisonLabel: string | null;
  width: number;
  height: number;
  viewMode?: "all" | "power" | "torque";
}): uPlot.Options {
  const mode = params.viewMode ?? "all";
  const showPower = mode !== "torque";
  const showTorque = mode !== "power";
  const unit = POWER_LABEL[params.powerUnit];
  const powerMax = 1.2 * convertPower(params.peakRef.power_kw, params.powerUnit);
  const torqueMax = 1.2 * params.peakRef.torque_nm;
  const cmp = params.comparisonLabel ?? "comparação";
  return {
    width: params.width,
    height: params.height,
    scales: {
      x: { time: false, range: params.rpmRange },
      power: { range: [0, powerMax] },
      torque: { range: [0, torqueMax] },
    },
    axes: [
      { ...axisStyle(), label: "RPM", scale: "x" },
      { ...axisStyle(), label: `Potência (${unit})`, scale: "power", side: 3, show: showPower },
      { ...axisStyle(), label: "Torque (N·m)", scale: "torque", side: 1, grid: { show: false }, show: showTorque },
    ],
    series: [
      { label: "RPM" },
      { label: `Potência (${unit})`, scale: "power", stroke: CHART_COLORS.power, width: 2, spanGaps: true, show: showPower },
      { label: "Torque (N·m)", scale: "torque", stroke: CHART_COLORS.torque, width: 2, spanGaps: true, show: showTorque },
      { label: `Potência ${cmp}`, scale: "power", stroke: CHART_COLORS.power, width: 1.5, dash: [8, 4], spanGaps: true, show: showPower },
      { label: `Torque ${cmp}`, scale: "torque", stroke: CHART_COLORS.torque, width: 1.5, dash: [8, 4], spanGaps: true, show: showTorque },
      { label: "Potência referência", scale: "power", stroke: CHART_COLORS.reference, width: 1, dash: [2, 4], spanGaps: true, show: showPower },
      { label: "Torque referência", scale: "torque", stroke: CHART_COLORS.reference, width: 1, dash: [2, 4], spanGaps: true, show: showTorque },
    ],
    legend: { show: true },
  };
}

/** Pico de potência de uma série (kW) e o RPM. */
export function peakOf(s: PowerTorqueSeries | null): { power_kw: number; rpm: number } | null {
  if (!s || s.power_kw.length === 0) return null;
  let best = -Infinity;
  let rpm = 0;
  for (let i = 0; i < s.power_kw.length; i += 1) {
    const v = s.power_kw[i]!;
    if (Number.isFinite(v) && v > best) {
      best = v;
      rpm = s.rpm[i]!;
    }
  }
  return Number.isFinite(best) ? { power_kw: best, rpm } : null;
}

/** Pico de torque de uma série (N·m) e o RPM. */
export function peakTorqueOf(s: PowerTorqueSeries | null): { torque_nm: number; rpm: number } | null {
  if (!s || s.torque_nm.length === 0) return null;
  let best = -Infinity;
  let rpm = 0;
  for (let i = 0; i < s.torque_nm.length; i += 1) {
    const v = s.torque_nm[i]!;
    if (Number.isFinite(v) && v > best) {
      best = v;
      rpm = s.rpm[i]!;
    }
  }
  return Number.isFinite(best) ? { torque_nm: best, rpm } : null;
}

function liveSeries(store: TelemetryStore): PowerTorqueSeries {
  return {
    rpm: store.buffer("rpm").toArrays().v,
    power_kw: store.buffer("power_kw").toArrays().v,
    torque_nm: store.buffer("torque_nm").toArrays().v,
  };
}

export function DynoChart({
  finalCurve,
  comparison,
  reference,
  powerUnit,
  rpmRange,
  peakRef,
  store,
  loop,
  cursorRpm = null,
  width = 720,
  height = 300,
}: DynoChartProps) {
  const chartRef = useRef<uPlot | null>(null);
  const [viewMode, setViewMode] = useState<"all" | "power" | "torque">("all");
  const [rMin, rMax] = rpmRange;
  const { power_kw: peakPower, torque_nm: peakTorque } = peakRef;
  const overlay = useMemo<ChartOverlay>(() => ({ markers: cursorRpm !== null ? [{ x: cursorRpm, color: "#fde047" }] : [] }), [cursorRpm]);

  const cmpSeries = useMemo(() => (comparison ? curveToSeries(comparison.curve) : null), [comparison]);
  const refSeries = useMemo(() => (reference ? referenceToSeries(reference) : null), [reference]);
  const finalSeries = useMemo(() => (finalCurve && finalCurve.length > 0 ? curveToSeries(finalCurve) : null), [finalCurve]);

  const options = useMemo(
    () =>
      buildDynoOptions({
        powerUnit,
        rpmRange: [rMin, rMax],
        peakRef: { power_kw: peakPower, torque_nm: peakTorque },
        comparisonLabel: comparison?.label ?? null,
        width,
        height,
        viewMode,
      }),
    [powerUnit, rMin, rMax, peakPower, peakTorque, comparison?.label, width, height, viewMode],
  );

  const staticData = useMemo(
    () => buildDynoData(finalSeries, cmpSeries, refSeries, powerUnit),
    [finalSeries, cmpSeries, refSeries, powerUnit],
  );

  // Traço ao vivo: o RenderLoop redesenha a partir do buffer em anel só quando a versão muda.
  useEffect(() => {
    if (!loop || !store || finalSeries) return;
    let seen = -1;
    return loop.add(() => {
      const u = chartRef.current;
      if (!u || store.version === seen) return;
      seen = store.version;
      u.setData(buildDynoData(liveSeries(store), cmpSeries, refSeries, powerUnit), false);
    });
  }, [loop, store, finalSeries, cmpSeries, refSeries, powerUnit]);

  const currentPeak = peakOf(finalSeries);
  const currentTorque = peakTorqueOf(finalSeries);
  const cmpPeak = peakOf(cmpSeries);
  const cmpTorque = peakTorqueOf(cmpSeries);

  const unit = POWER_LABEL[powerUnit];
  const delta =
    currentPeak && cmpPeak ? convertPower(currentPeak.power_kw, "whp") - convertPower(cmpPeak.power_kw, "whp") : null;
  const deltaPct =
    currentPeak && cmpPeak && cmpPeak.power_kw > 0
      ? ((currentPeak.power_kw - cmpPeak.power_kw) / cmpPeak.power_kw) * 100
      : null;
  const deltaTorque =
    currentTorque && cmpTorque ? currentTorque.torque_nm - cmpTorque.torque_nm : null;
  const deltaTorquePct =
    currentTorque && cmpTorque && cmpTorque.torque_nm > 0
      ? ((currentTorque.torque_nm - cmpTorque.torque_nm) / cmpTorque.torque_nm) * 100
      : null;

  return (
    <figure aria-labelledby="dyno-chart-title" className="m-0 flex flex-col gap-2">
      {/* Scorecard de Comparação de Puxadas */}
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {/* Card 1: Puxada Atual */}
        <div className="relative overflow-hidden rounded border border-amber-500/30 bg-gradient-to-br from-amber-950/20 via-zinc-900/60 to-zinc-900/40 p-2.5 shadow-sm">
          <div className="flex items-center justify-between gap-1 text-xs">
            <span className="flex items-center gap-1.5 font-semibold text-amber-400">
              <span className="inline-block h-2 w-2 rounded-full bg-amber-400 shadow-[0_0_8px_rgba(245,158,11,0.8)]" />
              Puxada Atual
            </span>
            <span className="rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.2 font-mono text-[10px] text-amber-300">
              ━ contínuo
            </span>
          </div>
          <div className="mt-2 grid grid-cols-2 gap-2">
            <div>
              <p className="text-[10px] uppercase tracking-wider text-zinc-400">Potência</p>
              <p className="font-mono text-base font-bold text-amber-300">
                {currentPeak ? `${formatNumber(convertPower(currentPeak.power_kw, powerUnit), 1)} ${unit}` : "—"}
              </p>
              {currentPeak && (
                <p className="font-mono text-[10px] text-zinc-400">@ {formatNumber(currentPeak.rpm, 0)} rpm</p>
              )}
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wider text-zinc-400">Torque</p>
              <p className="font-mono text-base font-bold text-sky-300">
                {currentTorque ? `${formatNumber(currentTorque.torque_nm, 1)} N·m` : "—"}
              </p>
              {currentTorque && (
                <p className="font-mono text-[10px] text-zinc-400">@ {formatNumber(currentTorque.rpm, 0)} rpm</p>
              )}
            </div>
          </div>
        </div>

        {/* Card 2: Puxada de Comparação */}
        <div
          className={`relative overflow-hidden rounded border p-2.5 shadow-sm transition-all ${
            comparison
              ? "border-sky-500/30 bg-gradient-to-br from-sky-950/20 via-zinc-900/60 to-zinc-900/40"
              : "border-dashed border-zinc-700 bg-zinc-900/20"
          }`}
        >
          <div className="flex items-center justify-between gap-1 text-xs">
            <span className="flex items-center gap-1.5 font-semibold text-sky-300">
              <span
                className={`inline-block h-2 w-2 rounded-full ${
                  comparison ? "bg-sky-400 shadow-[0_0_8px_rgba(56,189,248,0.8)]" : "bg-zinc-600"
                }`}
              />
              {comparison ? comparison.label : "Comparação"}
            </span>
            {comparison ? (
              <span className="rounded border border-sky-500/30 bg-sky-500/10 px-1.5 py-0.2 font-mono text-[10px] text-sky-300">
                ╍ tracejado
              </span>
            ) : (
              <span className="text-[10px] text-zinc-400">Sem seleção</span>
            )}
          </div>
          <div className="mt-2 grid grid-cols-2 gap-2">
            <div>
              <p className="text-[10px] uppercase tracking-wider text-zinc-400">Potência</p>
              <p className="font-mono text-base font-bold text-zinc-200">
                {cmpPeak ? `${formatNumber(convertPower(cmpPeak.power_kw, powerUnit), 1)} ${unit}` : "—"}
              </p>
              {cmpPeak && (
                <p className="font-mono text-[10px] text-zinc-400">@ {formatNumber(cmpPeak.rpm, 0)} rpm</p>
              )}
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wider text-zinc-400">Torque</p>
              <p className="font-mono text-base font-bold text-zinc-200">
                {cmpTorque ? `${formatNumber(cmpTorque.torque_nm, 1)} N·m` : "—"}
              </p>
              {cmpTorque && (
                <p className="font-mono text-[10px] text-zinc-400">@ {formatNumber(cmpTorque.rpm, 0)} rpm</p>
              )}
            </div>
          </div>
        </div>

        {/* Card 3: Diferencial de Ganho (Δ Delta) */}
        <div
          className={`relative overflow-hidden rounded border p-2.5 shadow-sm sm:col-span-2 lg:col-span-1 transition-all ${
            comparison && delta !== null
              ? delta >= 0
                ? "border-emerald-500/40 bg-gradient-to-br from-emerald-950/30 via-zinc-900/60 to-zinc-900/40"
                : "border-rose-500/40 bg-gradient-to-br from-rose-950/30 via-zinc-900/60 to-zinc-900/40"
              : "border-dashed border-zinc-700 bg-zinc-900/20"
          }`}
        >
          <div className="flex items-center justify-between gap-1 text-xs">
            <span className="flex items-center gap-1.5 font-semibold text-zinc-200">
              <span className="text-sm">⚡</span>
              Diferencial de Ganho
            </span>
            {comparison && delta !== null && deltaPct !== null && (
              <span
                className={`rounded px-1.5 py-0.2 font-mono text-[10px] font-bold ${
                  delta >= 0 ? "bg-emerald-500/20 text-emerald-300" : "bg-rose-500/20 text-rose-300"
                }`}
              >
                {deltaPct >= 0 ? `+${formatNumber(deltaPct, 1)}%` : `${formatNumber(deltaPct, 1)}%`}
              </span>
            )}
          </div>
          <div className="mt-2 grid grid-cols-2 gap-2">
            <div>
              <p className="text-[10px] uppercase tracking-wider text-zinc-400">Δ Potência</p>
              <p
                className={`font-mono text-base font-bold ${
                  delta === null ? "text-zinc-400" : delta >= 0 ? "text-emerald-400" : "text-rose-400"
                }`}
              >
                {delta !== null ? `${delta >= 0 ? "+" : ""}${formatNumber(delta, 1)} whp` : "—"}
              </p>
              <p className="text-[10px] text-zinc-400">no ponto de pico</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wider text-zinc-400">Δ Torque</p>
              <p
                className={`font-mono text-base font-bold ${
                  deltaTorque === null ? "text-zinc-400" : deltaTorque >= 0 ? "text-emerald-400" : "text-rose-400"
                }`}
              >
                {deltaTorque !== null ? `${deltaTorque >= 0 ? "+" : ""}${formatNumber(deltaTorque, 1)} N·m` : "—"}
              </p>
              <p className="text-[10px] text-zinc-400">
                {deltaTorquePct !== null ? `${deltaTorquePct >= 0 ? "+" : ""}${formatNumber(deltaTorquePct, 1)}%` : "no ponto de pico"}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Barra de Filtro de Séries e Controles Visuais */}
      <div className="flex flex-wrap items-center justify-between gap-2 rounded border border-zinc-800 bg-zinc-950/60 px-2 py-1 text-xs">
        <div className="flex items-center gap-1">
          <span className="mr-1 text-[11px] font-medium text-zinc-400">Exibir:</span>
          <button
            type="button"
            onClick={() => setViewMode("all")}
            className={`rounded px-2 py-0.5 text-xs font-medium transition-colors ${
              viewMode === "all"
                ? "bg-amber-500 text-zinc-950 shadow-sm"
                : "bg-zinc-800 text-zinc-300 hover:bg-zinc-700 hover:text-white"
            }`}
          >
            Todas as Curvas
          </button>
          <button
            type="button"
            onClick={() => setViewMode("power")}
            className={`rounded px-2 py-0.5 text-xs font-medium transition-colors ${
              viewMode === "power"
                ? "bg-amber-500 text-zinc-950 shadow-sm"
                : "bg-zinc-800 text-zinc-300 hover:bg-zinc-700 hover:text-white"
            }`}
          >
            Só Potência ({unit})
          </button>
          <button
            type="button"
            onClick={() => setViewMode("torque")}
            className={`rounded px-2 py-0.5 text-xs font-medium transition-colors ${
              viewMode === "torque"
                ? "bg-sky-500 text-zinc-950 shadow-sm"
                : "bg-zinc-800 text-zinc-300 hover:bg-zinc-700 hover:text-white"
            }`}
          >
            Só Torque (N·m)
          </button>
        </div>
        <div className="flex items-center gap-2">
          {reference && (
            <span className="flex items-center gap-1 text-[11px] text-zinc-400">
              <span className="inline-block h-0.5 w-3 border-t border-dotted border-zinc-400" /> Referência: {reference.curve_id}
            </span>
          )}
        </div>
      </div>

      <figcaption id="dyno-chart-title" className="mb-0.5 flex flex-wrap items-baseline gap-3 text-xs text-zinc-300">
        <span className="font-semibold text-zinc-200">Potência e torque × RPM</span>
        <span>
          <span aria-hidden="true" style={{ color: CHART_COLORS.power }}>━</span> atual ·{" "}
          <span aria-hidden="true">╍</span> {comparison ? comparison.label : "comparação"} ·{" "}
          <span aria-hidden="true">┈</span> referência
        </span>
        {currentPeak && (
          <span data-testid="dyno-peak" className="font-mono text-amber-300">
            pico {formatNumber(convertPower(currentPeak.power_kw, powerUnit), 1)} {unit} @ {formatNumber(currentPeak.rpm, 0)} rpm
          </span>
        )}
        {delta !== null && (
          <span data-testid="dyno-delta" className="font-mono text-emerald-300">
            Δ pico {delta >= 0 ? "+" : ""}
            {formatNumber(delta, 1)} whp
          </span>
        )}
        {!reference && <span className="text-zinc-400">{MSG.noReference}</span>}
      </figcaption>

      <UPlotChart
        options={options}
        data={staticData}
        overlay={overlay}
        onReady={(u) => {
          chartRef.current = u;
        }}
        ariaLabel={`Gráfico de potência em ${unit} e torque em N·m por RPM`}
      />
    </figure>
  );
}
