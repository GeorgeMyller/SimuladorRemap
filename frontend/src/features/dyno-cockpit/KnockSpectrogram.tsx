/**
 * Heatmap tempo × frequência do knock (janela 10 s, 0–20 kHz, 256 bins), com marcação das
 * ressonâncias do cilindro (RF-09; D-22). WebGL2 → WebGL1 → Canvas 2D ("modo compatível").
 */
import { useEffect, useRef, useState } from "react";

import { formatNumber } from "@/lib/units";

import { MSG } from "./messages";
import { createSurface, watchContextLoss, type SurfaceKind } from "./render/createSurface";
import type { RenderLoop } from "./render/RenderLoop";
import { createSpectrogramRenderer, type SpectrogramRenderer } from "./render/spectrogramRenderers";
import { SPECTRUM_MAX_HZ, type SpectrogramModel } from "./render/SpectrogramModel";
import type { TelemetryStore } from "./store";

export interface KnockSpectrogramProps {
  store: TelemetryStore;
  loop?: RenderLoop;
  nCyl: number;
  /** Degradação por FPS (EC-12): 25 colunas/s em vez de 50. */
  degraded?: boolean;
  onSurfaceChange?: (kind: SurfaceKind) => void;
  width?: number;
  height?: number;
}

export function KnockSpectrogram({ store, loop, nCyl, degraded = false, onSurfaceChange, width = 720, height = 220 }: KnockSpectrogramProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef<SpectrogramRenderer | null>(null);
  const [force2d, setForce2d] = useState(false);
  const [kind, setKind] = useState<SurfaceKind>("none");
  const [resonances, setResonances] = useState<number[]>([]);
  const [peakHz, setPeakHz] = useState<number | null>(null);
  const [intensities, setIntensities] = useState<number[]>([]);
  const surfaceCb = useRef(onSurfaceChange);
  useEffect(() => {
    surfaceCb.current = onSurfaceChange;
  });

  useEffect(() => {
    store.setSpectrogramDegraded(degraded);
  }, [store, degraded]);

  // Cria a superfície e o renderizador; perda de contexto WebGL remonta o canvas em 2D (EC-08).
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const surface = createSurface(canvas, { force2d });
    const model: SpectrogramModel = store.spectrogram;
    const { renderer, kind: k } = createSpectrogramRenderer(surface, model, () => null);
    if (k === "none" && surface.kind !== "none" && !force2d) {
      // Shader recusado: tenta Canvas 2D num canvas novo.
      queueMicrotask(() => setForce2d(true));
    }
    rendererRef.current = renderer;
    queueMicrotask(() => {
      setKind(k);
      surfaceCb.current?.(k);
    });
    renderer?.redrawAll(model);
    const unwatch = watchContextLoss(
      canvas,
      () => {
        rendererRef.current = null;
        setForce2d(true);
      },
      () => setForce2d(false),
    );
    return () => {
      unwatch();
      renderer?.dispose();
      rendererRef.current = null;
    };
  }, [store, force2d]);

  useEffect(() => {
    if (!loop) return;
    let seenHead = -1;
    let seenFilled = -1;
    let lastUi = -Infinity;
    return loop.add((now) => {
      const m = store.spectrogram;
      if (m.head !== seenHead || m.filled !== seenFilled) {
        seenHead = m.head;
        seenFilled = m.filled;
        rendererRef.current?.update(m);
      }
      // Texto (pico, ressonâncias, intensidades) a 5 Hz para não re-renderizar a cada frame.
      if (now - lastUi >= 200) {
        lastUi = now;
        setPeakHz(m.peakFrequencyHz());
        setResonances((prev) => (prev.join() === m.resonanceHz.join() ? prev : [...m.resonanceHz]));
        setIntensities(Array.from({ length: nCyl }, (_, i) => store.value(`knock_intensity_cyl${i + 1}`) ?? 0));
      }
    });
  }, [loop, store, nCyl]);

  const compat = kind === "2d" || kind === "none";

  return (
    <figure aria-labelledby="spectrogram-title" className="m-0">
      <figcaption id="spectrogram-title" className="mb-1 flex flex-wrap items-center gap-3 text-sm text-zinc-200">
        <span className="font-semibold">Espectrograma de knock (10 s, 0–20 kHz)</span>
        {compat && (
          <span data-testid="compat-badge" className="rounded bg-zinc-700 px-1.5 text-xs text-zinc-100">
            {MSG.compatMode}
          </span>
        )}
        {peakHz !== null && (
          <span data-testid="spectrum-peak" className="font-mono text-amber-300">
            pico {formatNumber(peakHz / 1000, 2)} kHz
          </span>
        )}
        <span className="flex gap-2 font-mono text-xs text-zinc-300" aria-label="Intensidade de knock por cilindro">
          {intensities.map((v, i) => (
            <span key={i}>
              c{i + 1} {formatNumber(v, 2)}
            </span>
          ))}
        </span>
      </figcaption>
      <div className="relative" style={{ width: "100%", maxWidth: width, height }}>
        <canvas
          key={force2d ? "2d" : "gl"}
          ref={canvasRef}
          width={width}
          height={height}
          data-surface={kind}
          role="img"
          aria-label="Espectrograma de knock: tempo no eixo horizontal, frequência no vertical"
          className="h-full w-full bg-black"
        />
        {resonances.map((hz, i) => (
          <div
            key={`${i}-${hz}`}
            data-testid="resonance-marker"
            className="pointer-events-none absolute left-0 right-0 border-t border-dashed border-cyan-300"
            style={{ bottom: `${(hz / SPECTRUM_MAX_HZ) * 100}%` }}
          >
            <span className="absolute right-1 -translate-y-full text-[10px] text-cyan-200">
              {formatNumber(hz / 1000, 2)} kHz{i === 0 ? " (1,0)" : ""}
            </span>
          </div>
        ))}
      </div>
    </figure>
  );
}
