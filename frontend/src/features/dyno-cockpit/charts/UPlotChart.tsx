/** Invólucro React do uPlot (Canvas 2D, D-22): cria uma vez, atualiza dados sem re-render. */
import { useEffect, useRef } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";

export interface ChartMarker {
  x: number;
  color: string;
  label?: string;
}

/** Sobreposição dinâmica (cursor, pico, lacunas) desenhada sem recriar o gráfico. */
export interface ChartOverlay {
  markers?: readonly ChartMarker[];
  gaps?: readonly { fromT: number; toT: number | null }[];
}

export interface UPlotChartProps {
  options: uPlot.Options;
  data: uPlot.AlignedData;
  overlay?: ChartOverlay;
  /** Recebe a instância (atualizações ao vivo pelo RenderLoop). */
  onReady?: (chart: uPlot | null) => void;
  className?: string;
  ariaLabel: string;
}

export function UPlotChart({ options, data, overlay, onReady, className, ariaLabel }: UPlotChartProps) {
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<uPlot | null>(null);
  const dataRef = useRef(data);
  const readyRef = useRef(onReady);
  const overlayRef = useRef<ChartOverlay | undefined>(overlay);
  useEffect(() => {
    dataRef.current = data;
    readyRef.current = onReady;
  });
  useEffect(() => {
    overlayRef.current = overlay;
    chart.current?.redraw(false);
  }, [overlay]);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const width = Math.max(320, el.clientWidth || options.width);
    const plugins = [...(options.plugins ?? []), overlayPlugin(() => overlayRef.current)];
    const instance = new uPlot({ ...options, width, plugins }, dataRef.current, el);
    chart.current = instance;
    readyRef.current?.(instance);
    let observer: ResizeObserver | undefined;
    if (typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver((entries) => {
        const w = entries[0]?.contentRect.width;
        if (w && w > 0) instance.setSize({ width: w, height: options.height });
      });
      observer.observe(el);
    }
    return () => {
      observer?.disconnect();
      readyRef.current?.(null);
      instance.destroy();
      chart.current = null;
    };
  }, [options]);

  useEffect(() => {
    chart.current?.setData(data);
  }, [data]);

  return <div ref={host} role="img" aria-label={ariaLabel} className={className} />;
}

export interface XY {
  x: ArrayLike<number>;
  y: ArrayLike<number>;
}

/**
 * Alinha várias séries XY num eixo x comum (união ordenada), com `null` onde a série
 * não tem ponto. NaN vira `null`. Formato `AlignedData` do uPlot.
 */
export function alignXY(series: readonly (XY | null)[]): uPlot.AlignedData {
  const xs = new Set<number>();
  for (const s of series) {
    if (!s) continue;
    for (let i = 0; i < s.x.length; i += 1) {
      const x = s.x[i]!;
      if (Number.isFinite(x)) xs.add(x);
    }
  }
  const x = [...xs].sort((a, b) => a - b);
  const index = new Map<number, number>();
  x.forEach((v, i) => index.set(v, i));
  const ys = series.map((s) => {
    const out: (number | null)[] = new Array<number | null>(x.length).fill(null);
    if (!s) return out;
    for (let i = 0; i < s.x.length; i += 1) {
      const xi = index.get(s.x[i]!);
      const yi = s.y[i]!;
      if (xi !== undefined && Number.isFinite(yi)) out[xi] = yi;
    }
    return out;
  });
  return [x, ...ys] as uPlot.AlignedData;
}

/** Prende `v` à escala; `out` indica o marcador "fora de escala" (EC-13). */
export function clampToScale(v: number, min: number, max: number): { value: number; out: boolean } {
  if (v > max) return { value: max, out: true };
  if (v < min) return { value: min, out: true };
  return { value: v, out: false };
}

/** Plugin uPlot: faixa horizontal de limite numa escala (ex.: EGT máxima). */
export function limitBandPlugin(scale: string, from: number, to: number, color: string, label: string): uPlot.Plugin {
  return {
    hooks: {
      drawClear: (u: uPlot) => {
        const ctx = u.ctx;
        const y0 = u.valToPos(to, scale, true);
        const y1 = u.valToPos(from, scale, true);
        ctx.save();
        ctx.fillStyle = color;
        ctx.fillRect(u.bbox.left, Math.min(y0, y1), u.bbox.width, Math.abs(y1 - y0));
        ctx.restore();
      },
      draw: (u: uPlot) => {
        const ctx = u.ctx;
        const y = u.valToPos(from, scale, true);
        ctx.save();
        ctx.strokeStyle = "#ef4444";
        ctx.lineWidth = 2;
        ctx.setLineDash([6, 3]);
        ctx.beginPath();
        ctx.moveTo(u.bbox.left, y);
        ctx.lineTo(u.bbox.left + u.bbox.width, y);
        ctx.stroke();
        ctx.fillStyle = "#fca5a5";
        ctx.font = "12px sans-serif";
        ctx.fillText(label, u.bbox.left + 6, y - 4);
        ctx.restore();
      },
    },
  };
}

/** Plugin uPlot: lacunas sombreadas (Fluxo D) e linhas verticais (PMS, pico, cursor de evento). */
export function overlayPlugin(getOverlay: () => ChartOverlay | undefined): uPlot.Plugin {
  return {
    hooks: {
      drawClear: (u: uPlot) => {
        const gaps = getOverlay()?.gaps;
        if (!gaps || gaps.length === 0) return;
        const ctx = u.ctx;
        ctx.save();
        ctx.fillStyle = "rgba(161,161,170,0.25)";
        for (const g of gaps) {
          const x0 = u.valToPos(g.fromT, "x", true);
          const x1 = g.toT === null ? u.bbox.left + u.bbox.width : u.valToPos(g.toT, "x", true);
          ctx.fillRect(x0, u.bbox.top, Math.max(1, x1 - x0), u.bbox.height);
        }
        ctx.restore();
      },
      draw: (u: uPlot) => {
        for (const m of getOverlay()?.markers ?? []) {
          if (!Number.isFinite(m.x)) continue;
          const px = u.valToPos(m.x, "x", true);
          const ctx = u.ctx;
          ctx.save();
          ctx.strokeStyle = m.color;
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.moveTo(px, u.bbox.top);
          ctx.lineTo(px, u.bbox.top + u.bbox.height);
          ctx.stroke();
          if (m.label) {
            ctx.fillStyle = m.color;
            ctx.font = "12px sans-serif";
            ctx.fillText(m.label, px + 4, u.bbox.top + 14);
          }
          ctx.restore();
        }
      },
    },
  };
}

export const CHART_COLORS = {
  power: "#f59e0b",
  torque: "#38bdf8",
  lambda: "#a78bfa",
  egt: "#f87171",
  reference: "#a1a1aa",
  pressure: "#34d399",
  axis: "#d4d4d8",
  grid: "rgba(212,212,216,0.12)",
} as const;

export function axisStyle(): Pick<uPlot.Axis, "stroke" | "grid" | "ticks"> {
  return {
    stroke: CHART_COLORS.axis,
    grid: { stroke: CHART_COLORS.grid, width: 1 },
    ticks: { stroke: CHART_COLORS.grid, width: 1 },
  };
}
