/**
 * Gauges de RPM, boost, lambda, EGT, IAT, ECT e knock retard com zonas verde/amarela/vermelha
 * derivadas dos limites do veículo e valor numérico legível além da agulha (RF-08).
 */
import { useEffect, useRef, useState } from "react";

import {
  boostBar,
  convertBoost,
  formatBoost,
  formatDegrees,
  formatLambda,
  formatNumber,
  formatTemperature,
  type BoostUnit,
} from "@/lib/units";

import { MSG } from "./messages";

export type Zone = "green" | "yellow" | "red";

/** Faixas ordenadas: valor < `upTo` cai na zona; o resto na última. */
export interface ZoneBand {
  upTo: number;
  zone: Zone;
}

export function zoneFor(value: number, bands: readonly ZoneBand[], fallback: Zone = "red"): Zone {
  for (const band of bands) if (value < band.upTo) return band.zone;
  return fallback;
}

export interface GaugeLimits {
  maxRpm: number;
  revLimitRpm: number;
  egtMaxC: number;
  /** Boost máximo tolerado (bar rel.). Sem dado do veículo usa 1,0 bar acima do alvo típico. */
  boostMaxBar: number;
  turbo: boolean;
}

export interface GaugeValues {
  rpm?: number;
  map_kpa?: number;
  baro_kpa?: number;
  lambda?: number;
  egt_c?: number;
  iat_c?: number;
  ect_c?: number;
  knock_retard_deg?: number;
}

export interface GaugeSpec {
  id: keyof GaugeValues | "boost";
  label: string;
  min: number;
  max: number;
  bands: ZoneBand[];
  fallback: Zone;
  format: (v: number) => string;
}

/** Especificação dos 7 gauges a partir dos limites e da unidade de boost. */
export function gaugeSpecs(limits: GaugeLimits, boostUnit: BoostUnit, locale?: string): GaugeSpec[] {
  const bMax = limits.boostMaxBar;
  return [
    {
      id: "rpm",
      label: "RPM",
      min: 0,
      max: limits.maxRpm,
      bands: [
        { upTo: limits.revLimitRpm - 500, zone: "green" },
        { upTo: limits.revLimitRpm, zone: "yellow" },
      ],
      fallback: "red",
      format: (v) => `${formatNumber(v, 0, locale)} rpm`,
    },
    {
      id: "boost",
      label: "Boost",
      min: convertBoost(-1, boostUnit),
      max: convertBoost(Math.max(1, bMax * 1.2), boostUnit),
      bands: [
        { upTo: convertBoost(bMax * 0.9, boostUnit), zone: "green" },
        { upTo: convertBoost(bMax, boostUnit), zone: "yellow" },
      ],
      fallback: "red",
      format: (v) => formatBoost(boostUnit === "bar" ? v : v / 14.5038, boostUnit, locale),
    },
    {
      id: "lambda",
      label: "Lambda",
      min: 0.6,
      max: 1.3,
      bands: [
        { upTo: 0.7, zone: "red" },
        { upTo: 0.75, zone: "yellow" },
        { upTo: 1.02, zone: "green" },
        { upTo: 1.1, zone: "yellow" },
      ],
      fallback: "red",
      format: (v) => `λ ${formatLambda(v, locale)}`,
    },
    {
      id: "egt_c",
      label: "EGT",
      min: 0,
      max: 1100,
      bands: [
        { upTo: limits.egtMaxC - 50, zone: "green" },
        { upTo: limits.egtMaxC, zone: "yellow" },
      ],
      fallback: "red",
      format: (v) => formatTemperature(v, locale),
    },
    {
      id: "iat_c",
      label: "IAT",
      min: -20,
      max: 100,
      bands: [
        { upTo: 50, zone: "green" },
        { upTo: 65, zone: "yellow" },
      ],
      fallback: "red",
      format: (v) => formatTemperature(v, locale),
    },
    {
      id: "ect_c",
      label: "ECT",
      min: 0,
      max: 130,
      bands: [
        { upTo: 105, zone: "green" },
        { upTo: 112, zone: "yellow" },
      ],
      fallback: "red",
      format: (v) => formatTemperature(v, locale),
    },
    {
      id: "knock_retard_deg",
      label: "Knock retard",
      min: 0,
      max: 15,
      bands: [
        { upTo: 2, zone: "green" },
        { upTo: 5, zone: "yellow" },
      ],
      fallback: "red",
      format: (v) => formatDegrees(v, 1, locale),
    },
  ];
}

/** Valor do gauge na unidade de exibição (boost convertido). */
export function gaugeValue(spec: GaugeSpec, values: GaugeValues, boostUnit: BoostUnit): number | undefined {
  if (spec.id === "boost") {
    if (values.map_kpa === undefined) return undefined;
    return convertBoost(boostBar(values.map_kpa, values.baro_kpa ?? 101.3), boostUnit);
  }
  return values[spec.id];
}

const ZONE_COLOR: Record<Zone, string> = { green: "#22c55e", yellow: "#eab308", red: "#ef4444" };
const ZONE_TEXT: Record<Zone, string> = { green: "normal", yellow: "atenção", red: "crítico" };

/**
 * Suavização exponencial só das agulhas (τ = 80 ms), animada por rAF; o texto mostra o valor bruto.
 */
function useSmoothedNeedles(targets: readonly (number | undefined)[], frozen: boolean): (number | undefined)[] {
  const key = targets.map((t) => (t === undefined ? "u" : String(t))).join("|");
  const [needles, setNeedles] = useState<(number | undefined)[]>(() => [...targets]);
  const current = useRef<(number | undefined)[]>([...targets]);
  useEffect(() => {
    const goal = key.split("|").map((s) => (s === "u" ? undefined : Number(s)));
    if (typeof requestAnimationFrame !== "function") return;
    let handle = 0;
    let last = -1;
    let elapsed = 0;
    const step = (now: number) => {
      const dt = last < 0 ? 16 : now - last;
      last = now;
      elapsed += dt;
      const alpha = frozen ? 1 : 1 - Math.exp(-dt / 80);
      let done = true;
      current.current = goal.map((g, i) => {
        const c = current.current[i];
        if (g === undefined || c === undefined) return g;
        const v = c + (g - c) * alpha;
        if (Math.abs(g - v) > Math.abs(g) * 1e-3 + 1e-6) done = false;
        return v;
      });
      setNeedles([...current.current]);
      if (!done && elapsed < 1000) handle = requestAnimationFrame(step);
    };
    handle = requestAnimationFrame(step);
    return () => cancelAnimationFrame(handle);
  }, [key, frozen]);
  return needles;
}

function arcPath(cx: number, cy: number, r: number, a0: number, a1: number): string {
  const x0 = cx + r * Math.cos(a0);
  const y0 = cy + r * Math.sin(a0);
  const x1 = cx + r * Math.cos(a1);
  const y1 = cy + r * Math.sin(a1);
  const large = a1 - a0 > Math.PI ? 1 : 0;
  return `M ${x0} ${y0} A ${r} ${r} 0 ${large} 1 ${x1} ${y1}`;
}

const START = Math.PI * 0.75;
const SWEEP = Math.PI * 1.5;

function Gauge({ spec, value, needle, frozen, missing }: { spec: GaugeSpec; value: number | undefined; needle: number | undefined; frozen: boolean; missing: boolean }) {
  const zone = value === undefined ? null : zoneFor(value, spec.bands, spec.fallback);
  const frac = (v: number) => Math.min(1, Math.max(0, (v - spec.min) / (spec.max - spec.min)));
  const segments: { from: number; to: number; zone: Zone }[] = [];
  let from = spec.min;
  for (const b of spec.bands) {
    const to = Math.min(spec.max, Math.max(spec.min, b.upTo));
    if (to > from) segments.push({ from, to, zone: b.zone });
    from = Math.max(from, to);
  }
  if (from < spec.max) segments.push({ from, to: spec.max, zone: spec.fallback });
  const needleAngle = needle === undefined ? null : START + SWEEP * frac(needle);
  const text = value === undefined ? "–" : spec.format(value);
  return (
    <div
      role="meter"
      aria-label={spec.label}
      aria-valuemin={spec.min}
      aria-valuemax={spec.max}
      aria-valuenow={value ?? spec.min}
      aria-valuetext={value === undefined ? `${spec.label} sem dados` : `${text}, zona ${ZONE_TEXT[zone!]}`}
      data-gauge={spec.id}
      data-zone={zone ?? "none"}
      className={`flex flex-col items-center rounded border p-1 ${zone === "red" ? "border-red-500" : "border-zinc-700"} ${frozen ? "opacity-70" : ""}`}
    >
      <svg viewBox="0 0 100 80" width="100%" height="72" aria-hidden="true">
        {segments.map((s) => (
          <path
            key={`${s.zone}-${s.from}`}
            d={arcPath(50, 50, 38, START + SWEEP * frac(s.from), START + SWEEP * frac(s.to))}
            stroke={ZONE_COLOR[s.zone]}
            strokeWidth="7"
            fill="none"
          />
        ))}
        {needleAngle !== null && (
          <line
            x1="50"
            y1="50"
            x2={50 + 32 * Math.cos(needleAngle)}
            y2={50 + 32 * Math.sin(needleAngle)}
            stroke="#fafafa"
            strokeWidth="3"
            strokeLinecap="round"
          />
        )}
        <circle cx="50" cy="50" r="4" fill="#fafafa" />
      </svg>
      <span className="text-xs text-zinc-300">{spec.label}</span>
      <span
        data-testid={`gauge-value-${spec.id}`}
        className={`font-mono text-base font-semibold ${zone === "red" ? "text-red-300" : zone === "yellow" ? "text-yellow-200" : "text-zinc-50"}`}
      >
        {text}
      </span>
      {missing && <span className="text-[10px] text-zinc-400">{MSG.noData(spec.id === "boost" ? "map_kpa" : spec.id)}</span>}
    </div>
  );
}

export interface GaugeClusterProps {
  values: GaugeValues;
  limits: GaugeLimits;
  boostUnit: BoostUnit;
  /** Motor destruído: gauges congelados. */
  frozen?: boolean;
  missingChannels?: readonly string[];
  locale?: string;
}

export function GaugeCluster({ values, limits, boostUnit, frozen = false, missingChannels = [], locale }: GaugeClusterProps) {
  const specs = gaugeSpecs(limits, boostUnit, locale);
  const targets = specs.map((s) => gaugeValue(s, values, boostUnit));
  const needles = useSmoothedNeedles(targets, frozen);
  return (
    <section aria-label="Gauges" aria-describedby={frozen ? "gauges-frozen" : undefined}>
      {frozen && (
        <p id="gauges-frozen" className="mb-1 text-xs font-semibold text-red-200">
          Gauges congelados (motor destruído)
        </p>
      )}
      <div className="grid grid-cols-2 min-[460px]:grid-cols-3 sm:grid-cols-4 gap-2 sm:gap-2.5">
        {specs.map((spec, i) => (
          <Gauge
            key={spec.id}
            spec={spec}
            value={gaugeValue(spec, values, boostUnit)}
            needle={needles[i]}
            frozen={frozen}
            missing={missingChannels.includes(spec.id === "boost" ? "map_kpa" : spec.id)}
          />
        ))}
      </div>
    </section>
  );
}
