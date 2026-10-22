/**
 * Aviso de calibração de série (`stock-*`, feature 002 RF-04): somente leitura, com a ação
 * "Clonar e editar" que cria a cópia do usuário, aplica-a à sessão e recarrega o workspace.
 */
import { useSyncExternalStore } from "react";

import { MSG } from "./messages";
import type { WorkspaceStore } from "./workspaceStore";

export function StockCalibrationBanner({ store, compact = false }: { store: WorkspaceStore; compact?: boolean }) {
  const snap = useSyncExternalStore(store.subscribe, store.getSnapshot);
  if (!snap.stock) return null;
  return (
    <div role="status" data-testid="stock-banner" className={`flex flex-wrap items-center justify-between gap-2 border border-amber-500/70 bg-amber-950/60 text-amber-100 ${compact ? "px-2 py-1 text-xs" : "px-3 py-2 text-sm"}`}>
      <span>{MSG.stockReadOnly}</span>
      <button
        type="button"
        disabled={snap.cloning}
        aria-busy={snap.cloning || undefined}
        onClick={() => void store.cloneAndEdit()}
        className="border border-amber-400 bg-amber-400 px-3 py-1 text-xs font-semibold text-zinc-950 transition-transform hover:bg-amber-300 active:scale-[0.98] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-200 disabled:cursor-wait disabled:opacity-60 motion-reduce:transition-none"
      >
        {snap.cloning ? MSG.cloning : MSG.cloneAndEdit}
      </button>
    </div>
  );
}
