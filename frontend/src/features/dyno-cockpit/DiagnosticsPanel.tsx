/** Painel de diagnóstico (tecla `D`): FPS, superfície ativa, perda de frames e `StreamStats` locais. */
import type { StreamStats } from "@/lib/ws";

import { SURFACE_LABEL, type SurfaceKind } from "./render/createSurface";

export interface DiagnosticsPanelProps {
  fps: number;
  surface: SurfaceKind;
  stats: StreamStats;
  degraded: boolean;
}

export function DiagnosticsPanel({ fps, surface, stats, degraded }: DiagnosticsPanelProps) {
  return (
    <aside aria-label="Diagnóstico" className="rounded border border-zinc-700 bg-zinc-900 p-2 font-mono text-xs text-zinc-200">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-0.5">
        <dt>FPS</dt>
        <dd data-testid="diag-fps">{fps.toFixed(0)}</dd>
        <dt>Superfície</dt>
        <dd data-testid="diag-surface">{SURFACE_LABEL[surface]}</dd>
        <dt>Perda (5 s)</dt>
        <dd>{(stats.lossRate5s * 100).toFixed(1)} %</dd>
        <dt>Frames recebidos / perdidos</dt>
        <dd>
          {stats.received} / {stats.lost}
        </dd>
        <dt>Último seq / frame_index</dt>
        <dd>
          {stats.lastSeq} / {stats.lastFrameIndex}
        </dd>
        <dt>Envelopes inválidos</dt>
        <dd>{stats.invalidEnvelopes}</dd>
        <dt>Reconexão</dt>
        <dd>
          {stats.reconnectAttempt}/{stats.maxAttempts}
        </dd>
      </dl>
      {degraded && <p className="mt-1 text-amber-300">FPS &lt; 30 por 5 s: modo degradado (espectrograma 25 col/s, 100 partículas).</p>}
    </aside>
  );
}
