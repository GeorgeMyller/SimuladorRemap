/**
 * Cursor de operação em tempo real (tuning RF-11, EC-12; §8 "Cursor de operação"): posição
 * fracionária por interpolação bilinear em RPM × carga a partir da telemetria, contorno das 4
 * células vizinhas com espessura proporcional ao peso e trilha dos últimos 2 s (≤ 100 pontos).
 */
import { useSyncExternalStore } from "react";

import type { CellRef, GridAxis } from "./model";
import type { GridGeometry } from "./TableGrid";
import type { TelemetryFeed, TrailPoint } from "./telemetryFeed";

/** Canal de telemetria que alimenta o eixo (`Axis.source_channel` → canal do WS). */
export const AXIS_CHANNEL: Readonly<Record<string, string>> = {
  rpm: "rpm",
  map_kpa: "map_kpa",
  load_pct: "load_pct",
  tps_pct: "throttle_pct",
  throttle_pct: "throttle_pct",
  pedal_pct: "throttle_pct",
  torque_nm: "torque_nm",
  torque_request_nm: "torque_nm",
};

export function channelFor(axis: GridAxis): string | null {
  return AXIS_CHANNEL[axis.sourceChannel] ?? AXIS_CHANNEL[axis.quantity] ?? null;
}

/** Índice fracionário `i + (x − x_i)/(x_(i+1) − x_i)`, preso a `[0, n − 1]`. */
export function fractionalIndex(axis: readonly number[], x: number): number {
  const n = axis.length;
  if (n < 2 || !Number.isFinite(x)) return 0;
  if (x <= axis[0]!) return 0;
  if (x >= axis[n - 1]!) return n - 1;
  let i = 0;
  while (i < n - 2 && axis[i + 1]! <= x) i += 1;
  const a = axis[i]!;
  const b = axis[i + 1]!;
  return b > a ? i + (x - a) / (b - a) : i;
}

/**
 * Célula mais próxima do ponto de operação (breakpoint mais perto em cada eixo) a partir dos
 * canais de telemetria; `null` se faltar o canal de algum eixo.
 */
export function nearestCell(x: GridAxis, y: GridAxis | null, channels: Readonly<Record<string, number>>): CellRef | null {
  const xCh = channelFor(x);
  const xv = xCh ? channels[xCh] : undefined;
  if (xv === undefined || !Number.isFinite(xv)) return null;
  if (!y) return { row: 0, col: Math.round(fractionalIndex(x.values, xv)) };
  const yCh = channelFor(y);
  const yv = yCh ? channels[yCh] : undefined;
  if (yv === undefined || !Number.isFinite(yv)) return null;
  return { row: Math.round(fractionalIndex(y.values, yv)), col: Math.round(fractionalIndex(x.values, xv)) };
}

export interface CursorPosition {
  /** Linha fracionária (eixo Y). */
  u: number;
  /** Coluna fracionária (eixo X). */
  w: number;
  neighbors: { row: number; col: number; weight: number }[];
}

export function cursorPosition(x: GridAxis, y: GridAxis | null, xValue: number, yValue: number | null): CursorPosition {
  const w = fractionalIndex(x.values, xValue);
  const u = y && yValue !== null ? fractionalIndex(y.values, yValue) : 0;
  const rows = y ? y.values.length : 1;
  const cols = x.values.length;
  const i = Math.min(Math.floor(u), Math.max(0, rows - 2));
  const j = Math.min(Math.floor(w), Math.max(0, cols - 2));
  const fy = rows > 1 ? u - i : 0;
  const fx = cols > 1 ? w - j : 0;
  const raw = [
    { row: i, col: j, weight: (1 - fy) * (1 - fx) },
    { row: i, col: j + 1, weight: (1 - fy) * fx },
    { row: i + 1, col: j, weight: fy * (1 - fx) },
    { row: i + 1, col: j + 1, weight: fy * fx },
  ];
  const neighbors = raw.filter((n) => n.row < rows && n.col < cols && n.weight > 1e-6);
  return { u, w, neighbors };
}

function pointFor(p: TrailPoint, xCh: string, yCh: string | null, x: GridAxis, y: GridAxis | null): { u: number; w: number } | null {
  const xv = p.channels[xCh];
  if (xv === undefined) return null;
  const yv = yCh ? p.channels[yCh] : undefined;
  if (y && yv === undefined) return null;
  return { u: y ? fractionalIndex(y.values, yv!) : 0, w: fractionalIndex(x.values, xv) };
}

export interface OperationCursorProps {
  feed: TelemetryFeed;
  x: GridAxis;
  y: GridAxis | null;
  geom: GridGeometry;
}

export function OperationCursor({ feed, x, y, geom }: OperationCursorProps) {
  const snap = useSyncExternalStore(feed.subscribe, () => feed.snapshot);
  const xCh = channelFor(x);
  const yCh = y ? channelFor(y) : null;
  if (!snap.fresh || !xCh || (y && !yCh)) return null;
  const xv = snap.channels[xCh];
  const yv = yCh ? (snap.channels[yCh] ?? null) : null;
  if (xv === undefined || (y && yv === null)) return null;
  const pos = cursorPosition(x, y, xv, yv);
  const px = (w: number) => geom.headerW + (w + 0.5) * geom.colW;
  const py = (u: number) => geom.headerH + (u + 0.5) * geom.rowH;
  const trail = feed
    .visibleTrail(snap.lastFrameAt ?? undefined)
    .map((p) => pointFor(p, xCh, yCh, x, y))
    .filter((p): p is { u: number; w: number } => p !== null);
  return (
    <div aria-hidden="true" data-testid="operation-cursor" data-u={pos.u.toFixed(3)} data-w={pos.w.toFixed(3)} style={{ position: "absolute", inset: 0, pointerEvents: "none", zIndex: 1 }}>
      {pos.neighbors.map((n) => (
        <div
          key={`${n.row}-${n.col}`}
          data-neighbor={`${n.row},${n.col}`}
          style={{
            position: "absolute",
            left: geom.headerW + n.col * geom.colW,
            top: geom.headerH + n.row * geom.rowH,
            width: geom.colW,
            height: geom.rowH,
            boxShadow: `inset 0 0 0 ${Math.max(1, Math.round(n.weight * 4))}px rgba(236, 72, 153, 0.95)`,
          }}
        />
      ))}
      <svg width={geom.headerW + geom.cols * geom.colW} height={geom.headerH + geom.rows * geom.rowH} style={{ position: "absolute", left: 0, top: 0 }}>
        {trail.map((p, k) => (
          <circle key={k} data-trail-point cx={px(p.w)} cy={py(p.u)} r={2} fill="#ec4899" opacity={((k + 1) / trail.length) * 0.8} />
        ))}
        <circle cx={px(pos.w)} cy={py(pos.u)} r={6} fill="none" stroke="#ffffff" strokeWidth={2} />
        <circle cx={px(pos.w)} cy={py(pos.u)} r={3} fill="#ec4899" />
      </svg>
    </div>
  );
}
