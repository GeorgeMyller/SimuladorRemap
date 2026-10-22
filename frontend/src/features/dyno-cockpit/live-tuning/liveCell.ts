/**
 * Live Cell Tracing (feature 002, RF-06; T034): célula [linha MAP × coluna RPM] em operação a
 * partir dos frames WS já guardados no `TelemetryStore` da bancada. O hook só recalcula no
 * `RenderLoop` e só re-renderiza quando a célula muda.
 */
import { useMemo, useSyncExternalStore } from "react";

import type { CellRef, GridTable } from "@/features/ecu-tuning/model";
import { channelFor, nearestCell } from "@/features/ecu-tuning/OperationCursor";

import type { RenderLoop } from "../render/RenderLoop";
import type { TelemetryStore } from "../store";

/** Sem frame há mais que isto, a célula ao vivo some (mesmo limiar do cursor do editor). */
export const LIVE_STALE_MS = 2000;

/**
 * Canais que o Live Tuning lê: eixos das tabelas oferecidas (RPM × MAP nas standalone; RPM ×
 * `load_pct` no avanço do OEM-Stage) e lambda para o Quick Tune.
 */
export const LIVE_TUNING_CHANNELS = ["rpm", "map_kpa", "load_pct", "lambda_measured", "lambda_target"] as const;

export const LIVE_CELL_CLASS = "live-cell-blink";

/** Estilo da classe em `liveCell.css` (folha externa: o CSP `style-src 'self'` bloqueia `<style>` inline). */

function isFresh(telemetry: TelemetryStore, now: number): boolean {
  return telemetry.lastFrameAt >= 0 && now - telemetry.lastFrameAt <= LIVE_STALE_MS;
}

/** Último valor dos canais pedidos (frames frescos), ou `null` sem dados recentes. */
export function liveChannels(telemetry: TelemetryStore, channels: readonly string[] = [...telemetry.latest.keys()], now: number = performance.now()): Record<string, number> | null {
  if (!isFresh(telemetry, now)) return null;
  const out: Record<string, number> = {};
  for (const ch of channels) {
    const v = telemetry.value(ch);
    if (v !== undefined && Number.isFinite(v)) out[ch] = v;
  }
  return out;
}

function axisChannels(table: GridTable): string[] {
  return [table.x, table.y].flatMap((axis) => {
    const ch = axis ? channelFor(axis) : null;
    return ch ? [ch] : [];
  });
}

/** Célula mais próxima do ponto de operação atual, ou `null` sem frames frescos. */
export function liveCellFor(table: GridTable, telemetry: TelemetryStore, now: number = performance.now()): CellRef | null {
  const channels = liveChannels(telemetry, axisChannels(table), now);
  return channels ? nearestCell(table.x, table.y, channels) : null;
}

function sameCell(a: CellRef | null, b: CellRef | null): boolean {
  return a === b || (a !== null && b !== null && a.row === b.row && a.col === b.col);
}

interface LiveCellSource {
  read: () => CellRef | null;
  subscribe: (notify: () => void) => () => void;
}

/** Fonte externa para `useSyncExternalStore`: devolve a mesma referência enquanto a célula não muda. */
export function createLiveCellSource(telemetry: TelemetryStore, loop: RenderLoop, table: GridTable | undefined): LiveCellSource {
  let current: CellRef | null = null;
  const read = (): CellRef | null => {
    const next = table ? liveCellFor(table, telemetry) : null;
    if (!sameCell(current, next)) current = next;
    return current;
  };
  const subscribe = (notify: () => void) =>
    loop.add(() => {
      const prev = current;
      if (read() !== prev) notify();
    });
  return { read, subscribe };
}

export function useLiveCell(telemetry: TelemetryStore, loop: RenderLoop, table: GridTable | undefined): CellRef | null {
  const source = useMemo(() => createLiveCellSource(telemetry, loop, table), [telemetry, loop, table]);
  return useSyncExternalStore(source.subscribe, source.read);
}
