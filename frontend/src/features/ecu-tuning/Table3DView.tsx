/**
 * Vista 3D da tabela (tuning RF-12, EC-11; D-22): superfície WebGL num chunk lazy
 * (`Table3DSurface`, three.js) sincronizada com a seleção da grade. Sem WebGL, ou com o contexto
 * perdido, mostra o mapa de contorno 2D em Canvas e o selo "modo compatível".
 */
import { lazy, Suspense, useEffect, useRef, useState } from "react";

import { paletteColor, rgbCss } from "./heatmap";
import { MSG } from "./messages";
import { contourSegments, webglAvailable } from "./Table3DGeometry";

const Table3DSurface = lazy(() => import("./Table3DSurface"));

export interface Table3DViewProps {
  values: number[][];
  focus: { row: number; col: number };
  label: string;
  width?: number;
  height?: number;
}

export function Table3DView({ values, focus, label, width = 480, height = 320 }: Table3DViewProps) {
  const [fallback, setFallback] = useState(() => !webglAvailable());
  return (
    <figure aria-label={`Vista 3D de ${label}`} className="relative rounded border border-zinc-700 bg-zinc-950 p-1">
      {fallback ? (
        <>
          <span className="absolute right-2 top-2 z-10 rounded bg-amber-500 px-1.5 py-0.5 text-[10px] font-semibold text-black" data-testid="compat-badge">
            {MSG.compatMode}
          </span>
          <ContourView values={values} focus={focus} width={width} height={height} />
        </>
      ) : (
        <Suspense fallback={<p className="p-4 text-xs text-zinc-300">A carregar a vista 3D…</p>}>
          <Table3DSurface values={values} focus={focus} width={width} height={height} onFallback={() => setFallback(true)} />
        </Suspense>
      )}
      <figcaption className="px-1 pt-1 text-[11px] text-zinc-400">
        {fallback ? "Mapa de contorno (WebGL indisponível)." : "Arraste para orbitar, roda para zoom, duplo clique para repor."}
      </figcaption>
    </figure>
  );
}

/** Contorno 2D em Canvas: células coloridas, isolinhas e a célula ativa destacada. */
export function ContourView({ values, focus, width, height }: { values: number[][]; focus: { row: number; col: number }; width: number; height: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const ctx = ref.current?.getContext("2d");
    if (!ctx) return;
    const ny = values.length;
    const nx = values[0]?.length ?? 0;
    if (!nx || !ny) return;
    let min = Infinity;
    let max = -Infinity;
    for (const row of values) for (const v of row) {
      min = Math.min(min, v);
      max = Math.max(max, v);
    }
    const cw = width / nx;
    const ch = height / ny;
    ctx.clearRect(0, 0, width, height);
    values.forEach((row, r) =>
      row.forEach((v, c) => {
        ctx.fillStyle = rgbCss(paletteColor(max > min ? (v - min) / (max - min) : 0.5));
        ctx.fillRect(c * cw, r * ch, cw + 0.5, ch + 0.5);
      }),
    );
    ctx.strokeStyle = "rgba(0,0,0,0.65)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (const s of contourSegments(values)) {
      ctx.moveTo((s.x1 + 0.5) * cw, (s.y1 + 0.5) * ch);
      ctx.lineTo((s.x2 + 0.5) * cw, (s.y2 + 0.5) * ch);
    }
    ctx.stroke();
    ctx.strokeStyle = "#f59e0b";
    ctx.lineWidth = 2;
    ctx.strokeRect(focus.col * cw + 1, focus.row * ch + 1, cw - 2, ch - 2);
  }, [values, focus.row, focus.col, width, height]);
  return <canvas ref={ref} width={width} height={height} data-testid="contour-view" data-highlight={`${focus.row},${focus.col}`} aria-hidden="true" />;
}
