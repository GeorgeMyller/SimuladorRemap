/**
 * Lambda (eixo esquerdo, 0,60–1,30) e EGT (eixo direito, 0–1100 °C) vs. RPM, com a faixa de
 * EGT máxima de `MechanicalLimits` e marcador "fora de escala" (RF-07, EC-13).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type uPlot from "uplot";

import { formatLambda, formatTemperature } from "@/lib/units";

import type { CurvePoint, ReferenceCurve } from "./api";
import { alignXY, axisStyle, CHART_COLORS, clampToScale, limitBandPlugin, UPlotChart, type ChartOverlay } from "./charts/UPlotChart";
import { MSG } from "./messages";
import type { RenderLoop } from "./render/RenderLoop";
import type { TelemetryStore } from "./store";

export const LAMBDA_SCALE: [number, number] = [0.6, 1.3];
export const EGT_SCALE: [number, number] = [0, 1100];

export interface LambdaEgtSeries {
  rpm: ArrayLike<number>;
  lambda: ArrayLike<number>;
  egt_c: ArrayLike<number>;
}

export interface LambdaEgtChartProps {
  finalCurve?: readonly CurvePoint[] | null;
  comparison?: { label: string; curve: readonly CurvePoint[] } | null;
  reference?: ReferenceCurve | null;
  egtLimitC: number;
  rpmRange: [number, number];
  store?: TelemetryStore;
  loop?: RenderLoop;
  cursorRpm?: number | null;
  width?: number;
  height?: number;
}

function clampArray(values: ArrayLike<number>, [min, max]: [number, number]): { y: Float64Array; out: boolean } {
  const y = new Float64Array(values.length);
  let out = false;
  for (let i = 0; i < values.length; i += 1) {
    const v = values[i]!;
    if (!Number.isFinite(v)) {
      y[i] = Number.NaN;
      continue;
    }
    const c = clampToScale(v, min, max);
    y[i] = c.value;
    out ||= c.out;
  }
  return { y, out };
}

/** Dados alinhados com valores presos às escalas; `outOfScale` acende o marcador. */
export function buildLambdaEgtData(
  current: LambdaEgtSeries | null,
  comparison: LambdaEgtSeries | null,
  reference: LambdaEgtSeries | null,
): { data: uPlot.AlignedData; outOfScale: boolean } {
  let outOfScale = false;
  const pair = (s: LambdaEgtSeries | null) => {
    if (!s) return [null, null] as const;
    const l = clampArray(s.lambda, LAMBDA_SCALE);
    const e = clampArray(s.egt_c, EGT_SCALE);
    if (s === current) outOfScale ||= l.out || e.out;
    return [
      { x: s.rpm, y: l.y },
      { x: s.rpm, y: e.y },
    ] as const;
  };
  const data = alignXY([...pair(current), ...pair(comparison), ...pair(reference)]);
  return { data, outOfScale };
}

export function buildLambdaEgtOptions(params: {
  egtLimitC: number;
  rpmRange: [number, number];
  width: number;
  height: number;
}): uPlot.Options {
  return {
    width: params.width,
    height: params.height,
    scales: {
      x: { time: false, range: params.rpmRange },
      lambda: { range: LAMBDA_SCALE },
      egt: { range: EGT_SCALE },
    },
    axes: [
      { ...axisStyle(), label: "RPM", scale: "x" },
      { ...axisStyle(), label: "Lambda (λ)", scale: "lambda", side: 3 },
      { ...axisStyle(), label: "EGT (°C)", scale: "egt", side: 1, grid: { show: false } },
    ],
    series: [
      { label: "RPM" },
      { label: "Lambda", scale: "lambda", stroke: CHART_COLORS.lambda, width: 2, spanGaps: true },
      { label: "EGT (°C)", scale: "egt", stroke: CHART_COLORS.egt, width: 2, spanGaps: true },
      { label: "Lambda comparação", scale: "lambda", stroke: CHART_COLORS.lambda, width: 1.5, dash: [8, 4], spanGaps: true },
      { label: "EGT comparação", scale: "egt", stroke: CHART_COLORS.egt, width: 1.5, dash: [8, 4], spanGaps: true },
      { label: "Lambda referência", scale: "lambda", stroke: CHART_COLORS.reference, width: 1, dash: [2, 4], spanGaps: true },
      { label: "EGT referência", scale: "egt", stroke: CHART_COLORS.reference, width: 1, dash: [2, 4], spanGaps: true },
    ],
    plugins: [
      limitBandPlugin("egt", params.egtLimitC, EGT_SCALE[1], "rgba(239,68,68,0.15)", `EGT máx. ${Math.round(params.egtLimitC)} °C`),
    ],
  };
}

const curveSeries = (c: readonly CurvePoint[]): LambdaEgtSeries => ({
  rpm: c.map((p) => p.rpm),
  lambda: c.map((p) => p.lambda),
  egt_c: c.map((p) => p.egt_c),
});

export function LambdaEgtChart({
  finalCurve,
  comparison,
  reference,
  egtLimitC,
  rpmRange,
  store,
  loop,
  cursorRpm = null,
  width = 720,
  height = 240,
}: LambdaEgtChartProps) {
  const chartRef = useRef<uPlot | null>(null);
  const [liveOut, setLiveOut] = useState(false);
  const [rMin, rMax] = rpmRange;
  const overlay = useMemo<ChartOverlay>(() => ({ markers: cursorRpm !== null ? [{ x: cursorRpm, color: "#fde047" }] : [] }), [cursorRpm]);

  const finalS = useMemo(() => (finalCurve && finalCurve.length ? curveSeries(finalCurve) : null), [finalCurve]);
  const cmpS = useMemo(() => (comparison ? curveSeries(comparison.curve) : null), [comparison]);
  const refS = useMemo(
    () =>
      reference
        ? {
            rpm: reference.points.map((p) => p.rpm),
            lambda: reference.points.map((p) => p.lambda_value ?? Number.NaN),
            egt_c: reference.points.map((p) => p.egt_c ?? Number.NaN),
          }
        : null,
    [reference],
  );
  const options = useMemo(
    () => buildLambdaEgtOptions({ egtLimitC, rpmRange: [rMin, rMax], width, height }),
    [egtLimitC, rMin, rMax, width, height],
  );
  const built = useMemo(() => buildLambdaEgtData(finalS, cmpS, refS), [finalS, cmpS, refS]);

  useEffect(() => {
    if (!loop || !store || finalS) return;
    let seen = -1;
    let lastOut = false;
    return loop.add(() => {
      const u = chartRef.current;
      if (!u || store.version === seen) return;
      seen = store.version;
      const live = {
        rpm: store.buffer("rpm").toArrays().v,
        lambda: store.buffer("lambda").toArrays().v,
        egt_c: store.buffer("egt_c").toArrays().v,
      };
      const res = buildLambdaEgtData(live, cmpS, refS);
      u.setData(res.data, false);
      if (res.outOfScale !== lastOut) {
        lastOut = res.outOfScale;
        setLiveOut(res.outOfScale);
      }
    });
  }, [loop, store, finalS, cmpS, refS]);

  const outOfScale = finalS ? built.outOfScale : liveOut;
  const latestEgt = store?.value("egt_c");
  const latestLambda = store?.value("lambda");

  return (
    <figure aria-labelledby="lambda-egt-title" className="m-0">
      <figcaption id="lambda-egt-title" className="mb-1 flex flex-wrap items-baseline gap-3 text-sm text-zinc-200">
        <span className="font-semibold">Lambda e EGT × RPM</span>
        <span data-testid="egt-limit" className="text-xs text-red-300">
          Limite EGT {formatTemperature(egtLimitC)}
        </span>
        {outOfScale && (
          <span
            data-testid="out-of-scale"
            className="rounded bg-amber-500 px-1.5 text-xs font-semibold text-zinc-950"
            title={`Valor real: λ ${latestLambda !== undefined ? formatLambda(latestLambda) : "–"}, EGT ${latestEgt !== undefined ? formatTemperature(latestEgt) : "–"}`}
          >
            {MSG.outOfScale}
          </span>
        )}
      </figcaption>
      <UPlotChart
        options={options}
        data={built.data}
        overlay={overlay}
        onReady={(u) => {
          chartRef.current = u;
        }}
        ariaLabel="Gráfico de lambda e temperatura de escape por RPM"
      />
    </figure>
  );
}
