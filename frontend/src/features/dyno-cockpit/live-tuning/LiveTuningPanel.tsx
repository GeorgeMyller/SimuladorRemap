/**
 * Painel Live Tuning da bancada (feature 002, RF-05 a RF-08; D-10, T033): monta a
 * `WorkspaceStore` da sessão sem socket próprio (o ponto de operação vem do `TelemetryStore` da
 * bancada), mostra o editor compacto da tabela live-tunable escolhida com a célula ao vivo a
 * piscar e aplica cada lote gravado à sessão automaticamente (respeitando `canApply`).
 */
import { useEffect, useMemo, useSyncExternalStore } from "react";

import { ecuApi } from "@/features/ecu-tuning/api";
import { MSG as ECU_MSG } from "@/features/ecu-tuning/messages";
import type { CellRef, GridTable } from "@/features/ecu-tuning/model";
import { StockCalibrationBanner } from "@/features/ecu-tuning/StockCalibrationBanner";
import { TableEditorCore } from "@/features/ecu-tuning/TableEditorCore";
import type { GridGeometry } from "@/features/ecu-tuning/TableGrid";
import { usePatchQueue, type SaveState } from "@/features/ecu-tuning/usePatchQueue";
import { useWorkspaceStore } from "@/features/ecu-tuning/useWorkspaceStore";
import type { WorkspaceDeps, WorkspaceStore } from "@/features/ecu-tuning/workspaceStore";

import type { RenderLoop } from "../render/RenderLoop";
import type { TelemetryStore } from "../store";
import { LIVE_CELL_CLASS, liveChannels, useLiveCell } from "./liveCell";
import "./liveCell.css";
import { useLiveTableChoice, type LiveTableOption } from "./useLiveTableChoice";

export interface LiveTuningPanelProps {
  sessionId: string;
  telemetry: TelemetryStore;
  loop: RenderLoop;
  /** Dependências do editor (testes injetam a API falsa). */
  deps?: Partial<WorkspaceDeps>;
}

const SAVE_TEXT: Record<SaveState, string> = {
  idle: "sem alterações",
  pending: ECU_MSG.saving,
  saving: ECU_MSG.saving,
  saved: "gravado",
  failed: ECU_MSG.notSaved,
  error: ECU_MSG.notSaved,
  conflict: ECU_MSG.conflict,
  locked: `${ECU_MSG.notSaved} (${ECU_MSG.lockedDuringRun})`,
};

export function LiveCellOverlay({ cell, geom }: { cell: CellRef | null; geom: GridGeometry }) {
  if (!cell) return null;
  return (
    <div
      aria-hidden="true"
      data-testid="live-cell"
      data-cell={`${cell.row},${cell.col}`}
      className={LIVE_CELL_CLASS}
      style={{ position: "absolute", left: geom.headerW + cell.col * geom.colW, top: geom.headerH + cell.row * geom.rowH, width: geom.colW, height: geom.rowH, pointerEvents: "none", zIndex: 1 }}
    />
  );
}

function useBenchSync(store: WorkspaceStore, telemetry: TelemetryStore): void {
  useEffect(() => {
    store.setAutoApply(true);
    store.setRunState(telemetry.runState?.state ?? null);
    const off = telemetry.onEvent((env) => {
      if (env.type === "run.state") store.setRunState(env.payload.state);
    });
    return () => {
      off();
      store.setAutoApply(false);
    };
  }, [store, telemetry]);
}

function axisText(table: GridTable, cell: CellRef | null): string {
  if (!cell) return ECU_MSG.noBenchData;
  const x = table.x.values[cell.col];
  const y = table.y?.values[cell.row];
  return `${x ?? "–"} ${table.x.unit}${table.y ? ` × ${y ?? "–"} ${table.y.unit}` : ""}`;
}

function TableChoice({ options, value, onChange }: { options: LiveTableOption[]; value: string | null; onChange: (id: string) => void }) {
  return (
    <div role="group" aria-label="Tabela em Live Tuning" className="flex flex-wrap gap-1">
      {options.map((o) => (
        <button
          key={o.tableId}
          type="button"
          aria-pressed={o.tableId === value}
          onClick={() => onChange(o.tableId)}
          className={`border px-2 py-1 text-xs transition-transform active:scale-[0.97] focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-400 motion-reduce:transition-none ${o.tableId === value ? "border-lime-400 bg-lime-400 font-semibold text-zinc-950" : "border-zinc-600 text-zinc-200 hover:border-lime-400"}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function LiveTuningPanel({ sessionId, telemetry, loop, deps }: LiveTuningPanelProps) {
  const store = useWorkspaceStore(sessionId, { api: ecuApi, telemetry: false, liveSource: () => liveChannels(telemetry), ...deps });
  useBenchSync(store, telemetry);
  const snap = useSyncExternalStore(store.subscribe, store.getSnapshot);
  const save = usePatchQueue(store.queue);
  const { options, tableId, setTableId } = useLiveTableChoice(store, snap);
  const table = tableId ? snap.tables[tableId] : undefined;
  const cell = useLiveCell(telemetry, loop, table);
  const overlay = useMemo(() => (geom: GridGeometry) => <LiveCellOverlay cell={cell} geom={geom} />, [cell]);
  const lastNotice = snap.notices[snap.notices.length - 1];

  return (
    <section aria-labelledby="live-tuning-title" data-live-tuning="" className="flex min-w-0 flex-col gap-2 border border-zinc-700 bg-zinc-900/60 p-2">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="live-tuning-title" className="text-sm font-semibold text-lime-300">
          Live Tuning
        </h2>
        <p data-testid="live-status" className="font-mono text-xs text-zinc-300">
          {snap.applying ? "a aplicar…" : snap.applied ? `aplicado rev ${snap.applied.version}` : "não aplicado"} · {SAVE_TEXT[save.state]}
        </p>
      </header>
      {snap.load.kind === "loading" && (
        <p role="status" aria-busy="true" className="text-xs text-zinc-300">
          {ECU_MSG.loading}
        </p>
      )}
      {snap.load.kind === "error" && (
        <div role="alert" className="border border-red-500 p-2 text-xs">
          <p className="font-semibold text-red-200">{snap.load.title}</p>
          <p className="text-red-100">{snap.load.detail}</p>
          <button type="button" onClick={() => void store.load()} className="mt-1 border border-red-300 px-2 py-0.5 hover:bg-red-900">
            Tentar de novo
          </button>
        </div>
      )}
      {snap.load.kind === "noNavigation" && <p className="text-xs text-zinc-300">{ECU_MSG.noNavigation(snap.load.profileId)}</p>}
      {snap.load.kind === "ready" && (
        <>
          <StockCalibrationBanner store={store} compact />
          {options.length === 0 ? (
            <p className="text-xs text-zinc-300">Nenhuma tabela live-tunable neste perfil.</p>
          ) : (
            <div className="flex flex-wrap items-center justify-between gap-2">
              <TableChoice options={options} value={tableId} onChange={setTableId} />
              <p data-testid="live-cell-label" className="font-mono text-xs text-lime-200">
                Célula ao vivo: {table ? axisText(table, cell) : "–"}
              </p>
            </div>
          )}
          {table && tableId && <TableEditorCore store={store} tableId={tableId} title={options.find((o) => o.tableId === tableId)?.label ?? tableId} variant="2d" overlay={overlay} />}
        </>
      )}
      <p aria-live="polite" className="min-h-4 text-xs text-zinc-300">
        {lastNotice?.text ?? ""}
      </p>
    </section>
  );
}
