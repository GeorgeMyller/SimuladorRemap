/**
 * Fila de gravação das edições de tabela (tuning RF-13, EC-01 a EC-04; D-15; rest-api E-19).
 * - agrupa as células por tabela com debounce de 300 ms (a última edição da célula vence);
 * - envia 1 `PATCH /calibrations/{id}/tables/{table_id}` por tabela com `base_version`;
 *   cada resposta traz a versão nova, usada como `base_version` do lote seguinte (envio em série);
 * - 409 `CALIBRATION_VERSION_CONFLICT`: estado `conflict` e `onConflict` (recarregar ou sobrescrever);
 * - 409 `TABLE_NOT_LIVE_TUNABLE`: as células ficam retidas como rascunho até `releaseHeld()`;
 * - 5xx, timeout ou rede: 3 novas tentativas (1 s, 2 s, 4 s) e depois `failed` com `retry()`;
 * - o pendente fica em `localStorage` (`simremap.ecu-tuning.draft.<calibration_id>`) até gravar.
 */
import { useSyncExternalStore } from "react";

import { isApiProblem, type ApiProblem } from "@/lib/api";

import { clearDraft, saveDraft } from "./prefs";
import type { CellEdit, TablePatchBody, TablePatchResult } from "./types";

export const PATCH_DEBOUNCE_MS = 300;
export const RETRY_DELAYS_MS: readonly number[] = [1000, 2000, 4000];
export const MAX_PATCH_CELLS = 1024;

export type SaveState = "idle" | "pending" | "saving" | "saved" | "failed" | "conflict" | "locked" | "error";

export interface PatchQueueOptions {
  calibrationId: string;
  version: number;
  patch: (calibrationId: string, tableId: string, body: TablePatchBody) => Promise<TablePatchResult>;
  debounceMs?: number;
  retryDelaysMs?: readonly number[];
  storage?: Storage | null;
  onState?: (state: SaveState, version: number) => void;
  onSaved?: (tableId: string, result: TablePatchResult) => void;
  onConflict?: (problem: ApiProblem, tableId: string, latestVersion: number | null) => void;
  onLocked?: (problem: ApiProblem, tableId: string, cells: CellEdit[]) => void;
  onRejected?: (problem: ApiProblem, tableId: string, cells: CellEdit[]) => void;
}

type CellMap = Map<string, CellEdit>;

function key(c: CellEdit): string {
  return `${c.row}:${c.col}`;
}

function mergeInto(target: Map<string, CellMap>, tableId: string, cells: Iterable<CellEdit>): void {
  let map = target.get(tableId);
  if (!map) {
    map = new Map();
    target.set(tableId, map);
  }
  for (const c of cells) map.set(key(c), { row: c.row, col: c.col, value: c.value });
}

function isTransient(e: unknown): boolean {
  if (!isApiProblem(e)) return true;
  return e.status === 0 || e.status >= 500;
}

export class PatchQueue {
  private readonly opts: PatchQueueOptions;
  private pending = new Map<string, CellMap>();
  private held = new Map<string, CellMap>();
  private inflight: { tableId: string; cells: CellEdit[] } | null = null;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private retryTimer: ReturnType<typeof setTimeout> | undefined;
  private attempt = 0;
  private disposed = false;
  private paused = false;
  version: number;
  state: SaveState = "idle";
  lastProblem: ApiProblem | null = null;
  /** Total de pedidos PATCH enviados (diagnóstico e testes). */
  sent = 0;
  snapshot: PatchQueueSnapshot = { state: "idle", version: 0 };
  private listeners = new Set<() => void>();

  constructor(opts: PatchQueueOptions) {
    this.opts = opts;
    this.version = opts.version;
    this.snapshot = { state: "idle", version: opts.version };
  }

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  /** Acrescenta células ao lote da tabela e reinicia o debounce. */
  enqueue(tableId: string, cells: CellEdit[]): void {
    if (this.disposed || cells.length === 0) return;
    mergeInto(this.pending, tableId, cells);
    this.persist();
    if (this.state !== "conflict" && this.state !== "failed") this.setState("pending");
    if (this.paused) return;
    if (this.timer !== undefined) clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      this.timer = undefined;
      void this.flush();
    }, this.opts.debounceMs ?? PATCH_DEBOUNCE_MS);
  }

  hasPending(): boolean {
    return this.pending.size > 0 || this.inflight !== null;
  }

  pendingCells(tableId: string): CellEdit[] {
    return [...(this.pending.get(tableId)?.values() ?? [])];
  }

  heldTables(): string[] {
    return [...this.held.keys()];
  }

  /** Envia já o que estiver pendente (ex.: antes de "Salvar versão"). */
  async flush(): Promise<void> {
    if (this.timer !== undefined) {
      clearTimeout(this.timer);
      this.timer = undefined;
    }
    while (!this.disposed && !this.paused && !this.inflight && this.pending.size > 0) {
      const [tableId, map] = this.pending.entries().next().value as [string, CellMap];
      const all = [...map.values()];
      const cells = all.slice(0, MAX_PATCH_CELLS);
      if (all.length > MAX_PATCH_CELLS) {
        for (const c of cells) map.delete(key(c));
      } else {
        this.pending.delete(tableId);
      }
      const ok = await this.send(tableId, cells);
      if (!ok) return;
    }
  }

  private async send(tableId: string, cells: CellEdit[]): Promise<boolean> {
    this.inflight = { tableId, cells };
    this.setState("saving");
    this.sent += 1;
    try {
      const result = await this.opts.patch(this.opts.calibrationId, tableId, {
        base_version: this.version,
        op: "set",
        cells,
        change_summary: `${tableId}: ${cells.length} ${cells.length === 1 ? "célula" : "células"}`,
      });
      if (this.disposed) return false;
      this.inflight = null;
      this.attempt = 0;
      this.version = result.version;
      this.lastProblem = null;
      this.opts.onSaved?.(tableId, result);
      this.persist();
      this.setState(this.pending.size > 0 ? "pending" : "saved");
      return true;
    } catch (error) {
      if (this.disposed) return false;
      this.inflight = null;
      // As células voltam para o início do lote, sem sobrepor edições mais novas.
      const newer = this.pending.get(tableId);
      const restored = new Map<string, CellMap>([[tableId, new Map(cells.map((c) => [key(c), c]))]]);
      if (newer) for (const [k, c] of newer) restored.get(tableId)!.set(k, c);
      for (const [t, m] of this.pending) if (t !== tableId) restored.set(t, m);
      this.pending = restored;
      this.handleError(error, tableId, cells);
      return false;
    }
  }

  private handleError(error: unknown, tableId: string, cells: CellEdit[]): void {
    const problem = isApiProblem(error) ? error : null;
    this.lastProblem = problem;
    if (problem?.code === "CALIBRATION_VERSION_CONFLICT" || problem?.code === "CALIBRATION_REVISION_CONFLICT") {
      this.paused = true;
      this.setState("conflict");
      const latest = problem.extra.latest_version;
      this.opts.onConflict?.(problem, tableId, typeof latest === "number" ? latest : null);
      return;
    }
    if (problem?.code === "TABLE_NOT_LIVE_TUNABLE" || problem?.code === "TABLE_LOCKED_DURING_RUN") {
      const map = this.pending.get(tableId);
      if (map) {
        mergeInto(this.held, tableId, map.values());
        this.pending.delete(tableId);
      }
      this.persist();
      this.setState("locked");
      this.opts.onLocked?.(problem, tableId, cells);
      if (this.pending.size > 0) void this.flush();
      return;
    }
    if (isTransient(error)) {
      const delays = this.opts.retryDelaysMs ?? RETRY_DELAYS_MS;
      if (this.attempt < delays.length) {
        const delay = delays[this.attempt]!;
        this.attempt += 1;
        this.setState("saving");
        this.retryTimer = setTimeout(() => {
          this.retryTimer = undefined;
          void this.flush();
        }, delay);
        return;
      }
      this.attempt = 0;
      this.paused = true;
      this.setState("failed");
      return;
    }
    // 422 e afins: o lote é recusado e descartado; o chamador recarrega a tabela.
    this.pending.delete(tableId);
    this.persist();
    this.setState("error");
    if (problem) this.opts.onRejected?.(problem, tableId, cells);
    if (this.pending.size > 0) void this.flush();
  }

  /** Botão "Tentar de novo" após `failed`. */
  retry(): void {
    this.paused = false;
    this.attempt = 0;
    void this.flush();
  }

  /** Resolve o conflito: `reload` descarta o pendente; `overwrite` regrava sobre `latestVersion`. */
  resolveConflict(choice: "reload" | "overwrite", latestVersion: number): void {
    this.paused = false;
    this.version = latestVersion;
    if (choice === "reload") {
      this.pending.clear();
      this.persist();
      this.setState("saved");
      return;
    }
    void this.flush();
  }

  /** Libera as células retidas por `TABLE_NOT_LIVE_TUNABLE` (fim da puxada). */
  releaseHeld(): void {
    if (this.held.size === 0) return;
    for (const [t, m] of this.held) mergeInto(this.pending, t, m.values());
    this.held.clear();
    void this.flush();
  }

  /** Atualiza a versão base depois de uma gravação feita fora da fila (PUT, revert). */
  setVersion(version: number): void {
    this.version = version;
    this.persist();
    this.setState(this.state);
  }

  dispose(): void {
    this.disposed = true;
    if (this.timer !== undefined) clearTimeout(this.timer);
    if (this.retryTimer !== undefined) clearTimeout(this.retryTimer);
  }

  private persist(): void {
    const tables: Record<string, CellEdit[]> = {};
    const add = (src: Map<string, CellMap>) => {
      for (const [t, m] of src) tables[t] = [...(tables[t] ?? []), ...m.values()];
    };
    add(this.pending);
    add(this.held);
    if (this.inflight) tables[this.inflight.tableId] = [...(tables[this.inflight.tableId] ?? []), ...this.inflight.cells];
    if (Object.keys(tables).length === 0) clearDraft(this.opts.calibrationId, this.opts.storage);
    else saveDraft({ version: 1, calibration_id: this.opts.calibrationId, base_version: this.version, tables }, this.opts.storage);
  }

  private setState(state: SaveState): void {
    this.state = state;
    this.snapshot = { state, version: this.version };
    this.opts.onState?.(state, this.version);
    for (const l of this.listeners) l();
  }
}

export interface PatchQueueSnapshot {
  state: SaveState;
  version: number;
}

const IDLE_SNAPSHOT: PatchQueueSnapshot = { state: "idle", version: 0 };
const noopSubscribe = () => () => undefined;

/** Estado de gravação da fila (`useSyncExternalStore`); `null` = sem calibração carregada. */
export function usePatchQueue(queue: PatchQueue | null): PatchQueueSnapshot {
  return useSyncExternalStore(
    queue ? queue.subscribe : noopSubscribe,
    () => (queue ? queue.snapshot : IDLE_SNAPSHOT),
  );
}
