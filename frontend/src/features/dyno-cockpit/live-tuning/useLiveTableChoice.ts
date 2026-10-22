/**
 * Tabelas oferecidas no Live Tuning (feature 002, T033): as live-tunable do perfil entre VE,
 * avanço e lambda alvo (VE primeiro), com o rótulo do item de navegação do perfil.
 */
import { useMemo, useState } from "react";

import type { WorkspaceSnapshot, WorkspaceStore } from "@/features/ecu-tuning/workspaceStore";

/** Ordem de exibição dos tipos de tabela do Live Tuning. */
export const LIVE_TABLE_KINDS = ["ve", "ignition_base", "lambda_target"] as const;

export interface LiveTableOption {
  tableId: string;
  label: string;
}

function navLabels(store: WorkspaceStore, snap: WorkspaceSnapshot): Map<string, string> {
  const labels = new Map<string, string>();
  for (const section of snap.profile?.navigation ?? []) {
    for (const item of section.items) {
      const id = item.kind === "table" ? store.resolveTableId(item, snap.calibration) : null;
      if (id && !labels.has(id)) labels.set(id, item.label);
    }
  }
  return labels;
}

export function liveTableOptions(store: WorkspaceStore, snap: WorkspaceSnapshot): LiveTableOption[] {
  const labels = navLabels(store, snap);
  const rank = (kind: string) => (LIVE_TABLE_KINDS as readonly string[]).indexOf(kind);
  return Object.values(snap.tables)
    .filter((t) => t.cylinder === null && rank(t.kind) >= 0 && store.isLiveTunable(t.tableId))
    .sort((a, b) => rank(a.kind) - rank(b.kind))
    .map((t) => ({ tableId: t.tableId, label: labels.get(t.tableId) ?? t.tableId }));
}

export function useLiveTableChoice(store: WorkspaceStore, snap: WorkspaceSnapshot) {
  const options = useMemo(() => liveTableOptions(store, snap), [store, snap]);
  const [chosen, setTableId] = useState<string | null>(null);
  const tableId = chosen && options.some((o) => o.tableId === chosen) ? chosen : (options[0]?.tableId ?? null);
  return { options, tableId, setTableId };
}
