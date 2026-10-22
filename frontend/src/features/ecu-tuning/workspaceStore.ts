/**
 * Estado do workspace da ECU (tuning RF-01, RF-04 a RF-09, RF-13, RF-16 a RF-18, EC-01 a EC-15).
 * Store externa (`useSyncExternalStore`): a edição de célula atualiza a grade de forma síncrona
 * (pintura ≤ 100 ms, RNF-01) e entra na `PatchQueue` (debounce de 300 ms, `base_version`).
 * Feature 002: Quick Tune e H/V/B (RF-08, RF-09), aplicação automática à sessão após cada lote
 * gravado (Live Tuning, RF-07) e calibração `stock-*` somente leitura com "Clonar e editar" (RF-04).
 */
import { ZodError } from "zod";

import { isApiProblem, type ApiProblem } from "@/lib/api";
import type { RunState, WebSocketFactory } from "@/lib/ws";

import type { CalibrationPutBody, EcuApi, SwapRequestBody } from "./api";
import { UndoStack } from "./history/UndoStack";
import { MSG } from "./messages";
import {
  applyDelta,
  rectCells,
  roundTo,
  selectionRect,
  singleCell,
  toContractValues,
  toGridTable,
  makeDelta,
  type CellRef,
  type GridTable,
  type Selection,
  type TableDelta,
} from "./model";
import { diffCalibrations, type CalibrationDiff } from "./ops/diffCalibrations";
import { interpolateBlock, interpolateLine, smooth } from "./ops/interpolate";
import { blockSmooth, interpolateH, interpolateV, quickTune, VE_KIND, type QuickTuneRefusal } from "./ops/quickTune";
import { addValue, scalePct, setValue, type OpResult } from "./ops/selectionOps";
import { parseTsv, pasteGrid, toTsv } from "./ops/tsv";
import { channelFor, cursorPosition, nearestCell } from "./OperationCursor";
import { afrToLambda, isLambdaTable, loadDraft, loadPrefs, savePrefs, type TuningPrefs } from "./prefs";
import type {
  ApplyCalibrationResult,
  Calibration,
  CellCorrection,
  CellEdit,
  EcuProfileDescriptor,
  EcuProfileSummary,
  NavItem,
  Session,
  SwapResult,
  BaseSetupResult,
  VehicleDetail,
} from "./types";
import { activeCalibrationId } from "./types";
import { isRunActive, TelemetryFeed } from "./telemetryFeed";
import { PatchQueue, type SaveState } from "./usePatchQueue";
import { BARO_KPA } from "./warnings";

export type LoadState =
  | { kind: "loading" }
  | { kind: "error"; code: string; title: string; detail: string }
  | { kind: "noNavigation"; profileId: string }
  | { kind: "ready" };

export type NoticeTone = "info" | "warn" | "error" | "success";

export interface Notice {
  id: number;
  tone: NoticeTone;
  text: string;
}

export interface ConflictInfo {
  tableId: string;
  latestVersion: number | null;
  server: Calibration | null;
  diff: CalibrationDiff | null;
}

export type TableOperation =
  | { op: "set"; value: number }
  | { op: "add"; value: number }
  | { op: "scale"; value: number }
  | { op: "interp_line" }
  | { op: "interp_row" }
  | { op: "interp_col" }
  | { op: "interp_block" }
  | { op: "smooth"; passes?: number }
  | { op: "interp_h" }
  | { op: "interp_v" }
  | { op: "block_smooth" };

/** Canais de telemetria do ponto de operação (rpm, map_kpa, lambda…), ou `null` sem dados frescos. */
export type LiveChannelSource = () => Readonly<Record<string, number>> | null;

export const STOCK_PREFIX = "stock-";
export const STOCK_IMMUTABLE_CODE = "CALIBRATION_STOCK_IMMUTABLE";

export function isStockCalibration(calibrationId: string): boolean {
  return calibrationId.startsWith(STOCK_PREFIX);
}

const QUICK_TUNE_REFUSAL: Record<QuickTuneRefusal, string> = {
  not_ve: MSG.quickTuneVeOnly,
  invalid_lambda: MSG.quickTuneNoLambda,
  no_cells: MSG.quickTuneNoCells,
};

function measuredLambda(channels: Readonly<Record<string, number>> | null): number | null {
  return channels?.lambda_measured ?? channels?.lambda ?? null;
}

export interface WorkspaceSnapshot {
  load: LoadState;
  session: Session | null;
  vehicle: VehicleDetail | null;
  profile: EcuProfileDescriptor | null;
  profiles: EcuProfileSummary[];
  calibration: Calibration | null;
  tables: Readonly<Record<string, GridTable>>;
  activeItemId: string | null;
  selections: Readonly<Record<string, Selection>>;
  prefs: TuningPrefs;
  notices: Notice[];
  conflict: ConflictInfo | null;
  heldTables: string[];
  canUndo: boolean;
  canRedo: boolean;
  applied: ApplyCalibrationResult | null;
  applying: boolean;
  dirtyTables: string[];
  dirtyOther: boolean;
  runState: RunState | null;
  telemetryFresh: boolean;
  swap: SwapResult | null;
  wizardOpen: boolean;
  readOnly: boolean;
  /** Calibração de série (`stock-*`): só leitura até "Clonar e editar". */
  stock: boolean;
  cloning: boolean;
  aiTuning: boolean;
  aiAggressiveness: "safe" | "balanced" | "race";
}

export interface WorkspaceDeps {
  api: EcuApi;
  storage?: Storage | null;
  createSocket?: WebSocketFactory;
  wsOrigin?: string;
  /** Desliga a telemetria (testes de componentes isolados). */
  telemetry?: boolean;
  debounceMs?: number;
  retryDelaysMs?: readonly number[];
  /** Fonte externa do ponto de operação (bancada); padrão: o `TelemetryFeed` do editor. */
  liveSource?: LiveChannelSource;
}

function problemOf(error: unknown): { code: string; title: string; detail: string } {
  if (isApiProblem(error)) return { code: error.code, title: error.title, detail: error.detail };
  if (error instanceof ZodError) return { code: "UNEXPECTED_RESPONSE", title: "Resposta inesperada do servidor", detail: "A resposta não segue o contrato da API v1." };
  return { code: "UNEXPECTED_ERROR", title: "Erro inesperado", detail: error instanceof Error ? error.message : String(error) };
}

function gridTables(cal: Calibration): Record<string, GridTable> {
  const out: Record<string, GridTable> = {};
  for (const [id, t] of Object.entries(cal.tables)) out[id] = toGridTable(t);
  return out;
}

function fmtLimit(v: number): string {
  return v.toLocaleString("pt-BR", { maximumFractionDigits: 3 });
}

export class WorkspaceStore {
  readonly sessionId: string;
  private readonly deps: WorkspaceDeps;
  private listeners = new Set<() => void>();
  private undoStack = new UndoStack();
  private noticeSeq = 0;
  private feedUnsub: (() => void) | null = null;
  private autoApply = false;
  private autoApplyQueued = false;
  /** Incrementa a cada edição: a aplicação só limpa o "sujo" se nada mudou durante o pedido. */
  private editSeq = 0;
  queue: PatchQueue | null = null;
  feed: TelemetryFeed | null = null;
  /** Último erro do `PUT` (erros por campo das estratégias, EC-13). */
  lastPutProblem: ApiProblem | null = null;
  snapshot: WorkspaceSnapshot;

  constructor(sessionId: string, deps: WorkspaceDeps) {
    this.sessionId = sessionId;
    this.deps = deps;
    this.snapshot = {
      load: { kind: "loading" },
      session: null,
      vehicle: null,
      profile: null,
      profiles: [],
      calibration: null,
      tables: {},
      activeItemId: null,
      selections: {},
      prefs: loadPrefs(deps.storage === undefined ? undefined : deps.storage),
      notices: [],
      conflict: null,
      heldTables: [],
      canUndo: false,
      canRedo: false,
      applied: null,
      applying: false,
      dirtyTables: [],
      dirtyOther: false,
      runState: null,
      telemetryFresh: false,
      swap: null,
      wizardOpen: false,
      readOnly: false,
      stock: false,
      cloning: false,
      aiTuning: false,
      aiAggressiveness: "balanced",
    };
  }

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  readonly getSnapshot = (): WorkspaceSnapshot => this.snapshot;

  private set(patch: Partial<WorkspaceSnapshot>): void {
    this.snapshot = { ...this.snapshot, ...patch };
    for (const l of this.listeners) l();
  }

  get api(): EcuApi {
    return this.deps.api;
  }

  // ---------------------------------------------------------------- ciclo de vida

  /** Liga a telemetria (cursor, `run.state`); devolve a função de limpeza. */
  start(): () => void {
    if (this.deps.telemetry !== false && !this.feed) {
      const feed = new TelemetryFeed({ sessionId: this.sessionId, createSocket: this.deps.createSocket, origin: this.deps.wsOrigin });
      this.feed = feed;
      this.feedUnsub = feed.subscribe(() => this.onFeed());
      feed.connect();
    }
    return () => this.stop();
  }

  stop(): void {
    this.feedUnsub?.();
    this.feedUnsub = null;
    this.feed?.close();
    this.feed = null;
    this.queue?.dispose();
  }

  private onFeed(): void {
    const f = this.feed?.snapshot;
    if (!f) return;
    const wasActive = isRunActive(this.snapshot.runState);
    if (f.runState !== this.snapshot.runState || f.fresh !== this.snapshot.telemetryFresh) {
      this.set({ runState: f.runState, telemetryFresh: f.fresh });
    }
    if (wasActive && !isRunActive(f.runState) && this.queue && this.queue.heldTables().length > 0) {
      this.queue.releaseHeld();
      this.set({ heldTables: [] });
    }
  }

  /** Estado de puxada vindo da telemetria (ou injetado em testes). */
  setRunState(state: RunState | null): void {
    const wasActive = isRunActive(this.snapshot.runState);
    this.set({ runState: state });
    if (wasActive && !isRunActive(state) && this.queue && this.queue.heldTables().length > 0) {
      this.queue.releaseHeld();
      this.set({ heldTables: [] });
    }
  }

  async load(): Promise<void> {
    this.set({ load: { kind: "loading" } });
    try {
      const session = await this.api.getSession(this.sessionId);
      const [vehicle, profile, profiles, calibration] = await Promise.all([
        this.api.getVehicle(session.vehicle_id).catch(() => null),
        this.api.getProfile(session.profile_id, session.vehicle_id),
        this.api.listProfiles().catch(() => [] as EcuProfileSummary[]),
        this.api.getCalibration(activeCalibrationId(session), { includeVersions: true }),
      ]);
      if (profile.navigation.length === 0) {
        this.set({ session, vehicle, profile, profiles, load: { kind: "noNavigation", profileId: profile.profile_id } });
        return;
      }
      this.installCalibration(calibration);
      const first = this.firstItem(profile, calibration);
      this.set({
        session,
        vehicle,
        profile,
        profiles,
        activeItemId: this.snapshot.activeItemId ?? first?.id ?? null,
        wizardOpen: session.ecu_state === "awaiting_base_setup" || this.snapshot.wizardOpen,
        load: { kind: "ready" },
      });
      this.restoreDraft(calibration);
    } catch (error) {
      this.set({ load: { kind: "error", ...problemOf(error) } });
    }
  }

  private firstItem(profile: EcuProfileDescriptor, cal: Calibration): NavItem | null {
    for (const s of profile.navigation) for (const item of s.items) if (this.itemAvailable(item, cal)) return item;
    return profile.navigation[0]?.items[0] ?? null;
  }

  /**
   * `table_id` do item de navegação: o descritor aponta para o `kind` da tabela (e o `cylinder`
   * nos trims); aceita também um `table_id` direto.
   */
  resolveTableId(item: NavItem, cal: Calibration | null = this.snapshot.calibration): string | null {
    if (!cal || item.kind !== "table") return null;
    const direct = cal.tables[item.target_id];
    if (direct && (item.cylinder == null || direct.cylinder === item.cylinder)) return item.target_id;
    const match = Object.values(cal.tables).find((t) => t.kind === item.target_id && (item.cylinder == null || t.cylinder === item.cylinder));
    return match?.table_id ?? null;
  }

  itemAvailable(item: NavItem, cal: Calibration | null = this.snapshot.calibration): boolean {
    if (!cal) return false;
    if (item.kind === "table") return this.resolveTableId(item, cal) !== null;
    if (item.kind === "strategy") {
      if (item.target_id === "cylinder_trims") return true;
      const support = this.snapshot.profile?.strategies.find((s) => s.kind === item.target_id);
      return support?.level !== "unsupported";
    }
    return true;
  }

  private installCalibration(cal: Calibration): void {
    this.queue?.dispose();
    this.undoStack.clear();
    const queue = new PatchQueue({
      calibrationId: cal.calibration_id,
      version: cal.version,
      patch: (id, tableId, body) => this.api.patchTable(id, tableId, body),
      storage: this.deps.storage,
      debounceMs: this.deps.debounceMs,
      retryDelaysMs: this.deps.retryDelaysMs,
      onSaved: (tableId, result) => this.onSaved(tableId, result.version, result.table),
      onConflict: (problem, tableId, latest) => void this.onConflict(problem, tableId, latest),
      onLocked: (_p, tableId) => this.onLocked(tableId),
      onRejected: (problem, tableId) => void this.onRejected(problem, tableId),
    });
    this.queue = queue;
    this.set({
      calibration: cal,
      tables: gridTables(cal),
      selections: {},
      canUndo: false,
      canRedo: false,
      conflict: null,
      heldTables: [],
      readOnly: cal.metadata.extra.read_only === "true" || isStockCalibration(cal.calibration_id),
      stock: isStockCalibration(cal.calibration_id),
    });
  }

  private restoreDraft(cal: Calibration): void {
    const draft = loadDraft(cal.calibration_id, this.deps.storage === undefined ? undefined : this.deps.storage);
    if (draft.kind === "corrupt") {
      this.notify("warn", MSG.draftCorrupt);
      return;
    }
    if (draft.kind !== "ok") return;
    const tables = { ...this.snapshot.tables };
    let restored = 0;
    for (const [tableId, cells] of Object.entries(draft.draft.tables)) {
      const t = tables[tableId];
      if (!t) continue;
      const values = t.values.map((r) => [...r]);
      const valid = cells.filter((c) => values[c.row]?.[c.col] !== undefined && c.value >= t.min && c.value <= t.max);
      for (const c of valid) values[c.row]![c.col] = c.value;
      tables[tableId] = { ...t, values };
      this.queue?.enqueue(tableId, valid);
      restored += valid.length;
    }
    if (restored > 0) {
      this.set({ tables, dirtyTables: [...new Set([...this.snapshot.dirtyTables, ...Object.keys(draft.draft.tables)])] });
      this.notify("info", MSG.draftRestored);
    }
  }

  // ---------------------------------------------------------------- avisos de estado

  notify(tone: NoticeTone, text: string): void {
    this.noticeSeq += 1;
    this.set({ notices: [...this.snapshot.notices.slice(-4), { id: this.noticeSeq, tone, text }] });
  }

  dismissNotice(id: number): void {
    this.set({ notices: this.snapshot.notices.filter((n) => n.id !== id) });
  }

  setPrefs(update: Partial<TuningPrefs>): void {
    const prefs = { ...this.snapshot.prefs, ...update };
    savePrefs(prefs, this.deps.storage === undefined ? undefined : this.deps.storage);
    this.set({ prefs });
  }

  // ---------------------------------------------------------------- navegação e seleção

  selectItem(itemId: string): void {
    this.set({ activeItemId: itemId });
  }

  activeItem(): NavItem | null {
    const id = this.snapshot.activeItemId;
    for (const s of this.snapshot.profile?.navigation ?? []) for (const item of s.items) if (item.id === id) return item;
    return null;
  }

  selection(tableId: string): Selection {
    return this.snapshot.selections[tableId] ?? singleCell(0, 0);
  }

  setSelection(tableId: string, sel: Selection): void {
    this.set({ selections: { ...this.snapshot.selections, [tableId]: sel } });
  }

  isLiveTunable(tableId: string): boolean {
    const t = this.snapshot.tables[tableId];
    const ids = this.snapshot.profile?.live_tunable_table_ids ?? [];
    return ids.includes(tableId) || (t !== undefined && ids.includes(t.kind));
  }

  /** Tabela só leitura agora (puxada ativa e fora de `live_tunable_table_ids`, RF-17). */
  isLocked(tableId: string): boolean {
    return isRunActive(this.snapshot.runState) && !this.isLiveTunable(tableId);
  }

  afrStoich(): number | null {
    const v = this.snapshot.vehicle;
    if (!v) return null;
    const fuelId = this.snapshot.session?.fuel_id ?? v.stock_fuel_id;
    return v.fuels.find((f) => f.fuel_id === fuelId)?.afr_stoich ?? null;
  }

  /** Converte um valor digitado na unidade exibida (AFR) para a unidade gravada (λ). */
  toStored(tableId: string, value: number): number {
    const t = this.snapshot.tables[tableId];
    const stoich = this.afrStoich();
    if (t && stoich && this.snapshot.prefs.lambdaDisplay === "afr" && isLambdaTable(t.kind)) return afrToLambda(value, stoich);
    return value;
  }

  boostMaxKpa(): number | null {
    const v = this.snapshot.vehicle;
    const pr = v?.induction === "turbo" ? v.turbo?.compressor?.pr_design : undefined;
    return pr ? pr * BARO_KPA : null;
  }

  // ---------------------------------------------------------------- edição

  private guard(tableId: string): GridTable | null {
    const t = this.snapshot.tables[tableId];
    if (!t) return null;
    if (this.snapshot.readOnly) {
      this.notify("warn", this.snapshot.stock ? MSG.stockReadOnly : MSG.readOnly);
      return null;
    }
    if (this.isLocked(tableId)) {
      this.notify("warn", `${tableId}: ${MSG.lockedDuringRun}`);
      return null;
    }
    return t;
  }

  private commit(t: GridTable, result: OpResult, extraNotice?: string): boolean {
    if (result.delta.cells.length === 0) {
      if (extraNotice) this.notify("warn", extraNotice);
      return false;
    }
    this.set({ tables: { ...this.snapshot.tables, [t.tableId]: { ...t, values: result.values } } });
    this.undoStack.push(result.delta);
    this.enqueueDelta(t, result.delta, "forward");
    this.markDirty(t.tableId);
    if (result.clamped > 0) {
      const lim = result.values.flat().some((v) => v === t.max) ? t.max : t.min;
      this.notify("warn", MSG.clamped(result.clamped, fmtLimit(lim)));
    }
    if (extraNotice) this.notify("warn", extraNotice);
    this.set({ canUndo: this.undoStack.canUndo, canRedo: this.undoStack.canRedo });
    return true;
  }

  private enqueueDelta(t: GridTable, delta: TableDelta, direction: "forward" | "backward"): void {
    const cells: CellEdit[] = delta.cells.map((c) => ({ row: c.row, col: c.col, value: roundTo(direction === "forward" ? c.after : c.before, t.decimals) }));
    this.queue?.enqueue(t.tableId, cells);
  }

  private markDirty(tableId: string): void {
    this.editSeq += 1;
    if (!this.snapshot.dirtyTables.includes(tableId)) this.set({ dirtyTables: [...this.snapshot.dirtyTables, tableId] });
  }

  editCell(tableId: string, row: number, col: number, displayed: number): boolean {
    const t = this.guard(tableId);
    if (!t) return false;
    return this.commit(t, setValue(t, { r0: row, r1: row, c0: col, c1: col }, this.toStored(tableId, displayed)));
  }

  applyOperation(tableId: string, operation: TableOperation): boolean {
    const t = this.guard(tableId);
    if (!t) return false;
    const rect = selectionRect(this.selection(tableId), t.values.length, t.values[0]?.length ?? 0);
    let result: OpResult | null;
    switch (operation.op) {
      case "set":
        result = setValue(t, rect, this.toStored(tableId, operation.value));
        break;
      case "add": {
        const stoich = this.afrStoich();
        const d = stoich && this.snapshot.prefs.lambdaDisplay === "afr" && isLambdaTable(t.kind) ? operation.value / stoich : operation.value;
        result = addValue(t, rect, d);
        break;
      }
      case "scale":
        result = scalePct(t, rect, operation.value);
        break;
      case "interp_line":
        result = interpolateLine(t, rect);
        break;
      case "interp_row":
        result = interpolateLine(t, rect, "row");
        break;
      case "interp_col":
        result = interpolateLine(t, rect, "col");
        break;
      case "interp_block":
        result = interpolateBlock(t, rect);
        break;
      case "smooth":
        result = smooth(t, rect, operation.passes ?? 1);
        break;
      case "interp_h":
        result = interpolateH(t, this.selection(tableId));
        break;
      case "interp_v":
        result = interpolateV(t, this.selection(tableId));
        break;
      case "block_smooth":
        result = blockSmooth(t, this.selection(tableId));
        break;
    }
    if (!result) {
      this.notify("warn", MSG.interpHint);
      return false;
    }
    return this.commit(t, result);
  }

  // ---------------------------------------------------------------- Quick Tune (RF-08, RN-04)

  /** Canais frescos do ponto de operação (fonte externa da bancada ou telemetria própria). */
  liveChannels(): Readonly<Record<string, number>> | null {
    if (this.deps.liveSource) return this.deps.liveSource();
    const f = this.feed?.snapshot;
    return f?.fresh ? f.channels : null;
  }

  /** Célula ativa do Quick Tune: a do cursor de operação (com telemetria) ou a focada. */
  activeCell(tableId: string): CellRef | null {
    const t = this.snapshot.tables[tableId];
    if (!t) return null;
    const channels = this.liveChannels();
    return (channels ? nearestCell(t.x, t.y, channels) : null) ?? this.selection(tableId).focus;
  }

  private quickTuneCells(t: GridTable): CellRef[] {
    const rect = selectionRect(this.selection(t.tableId), t.values.length, t.values[0]?.length ?? 0);
    const multiple = rect.r1 > rect.r0 || rect.c1 > rect.c0;
    if (multiple) return rectCells(rect);
    const active = this.activeCell(t.tableId);
    return active ? [active] : [];
  }

  /** λ alvo: canal `lambda_target`; sem ele, a tabela `lambda_target` no ponto de operação. */
  private lambdaTargetAt(channels: Readonly<Record<string, number>> | null): number | null {
    if (channels?.lambda_target !== undefined) return channels.lambda_target;
    const target = Object.values(this.snapshot.tables).find((t) => t.kind === "lambda_target");
    if (!target || !channels) return null;
    const xv = channels[channelFor(target.x) ?? ""];
    const yv = target.y ? (channels[channelFor(target.y) ?? ""] ?? null) : null;
    if (xv === undefined || (target.y && yv === null)) return null;
    const pos = cursorPosition(target.x, target.y, xv, yv);
    return pos.neighbors.reduce((acc, n) => acc + n.weight * (target.values[n.row]?.[n.col] ?? 0), 0);
  }

  /** `Q`: corrige a VE na seleção (≥ 2 células) ou na célula ativa por `λ medido / λ alvo`. */
  quickTune(tableId: string): boolean {
    const table = this.snapshot.tables[tableId];
    if (!table) return false;
    if (table.kind !== VE_KIND) {
      this.notify("warn", MSG.quickTuneVeOnly);
      return false;
    }
    const t = this.guard(tableId);
    if (!t) return false;
    const channels = this.liveChannels();
    const outcome = quickTune(t, this.quickTuneCells(t), measuredLambda(channels), this.lambdaTargetAt(channels));
    if (!outcome.ok) {
      this.notify("warn", QUICK_TUNE_REFUSAL[outcome.reason]);
      return false;
    }
    return this.commit(t, outcome.result);
  }

  setAiAggressiveness(level: "safe" | "balanced" | "race"): void {
    this.set({ aiAggressiveness: level });
  }

  /**
   * Otimização autônoma assistida por IA (LAYA.ai).
   * Envia as tabelas solicitadas (ou a tabela atual) ao serviço neural local no Mac,
   * recebe as correções com explicações e nível de confiança e as aplica de forma síncrona.
   */
  async aiTune(tableId?: string, level?: "safe" | "balanced" | "race"): Promise<boolean> {
    const cal = this.snapshot.calibration;
    if (!cal) return false;
    if (this.snapshot.readOnly || this.snapshot.stock) {
      this.notify("warn", MSG.stockImmutable);
      return false;
    }
    if (this.snapshot.aiTuning) return false;

    const targetTableIds = tableId ? [tableId] : ["ve", "ignition_base"];
    const aggressiveness = level ?? this.snapshot.aiAggressiveness ?? "balanced";
    this.set({ aiTuning: true });

    try {
      const resp = await this.deps.api.aiTune(cal.calibration_id, {
        target_table_ids: targetTableIds,
        aggressiveness,
      });

      if (!resp.corrections || resp.corrections.length === 0) {
        this.notify("info", "LAYA.ai: As células analisadas já estão otimizadas.");
        return true;
      }

      // Sincroniza a versão mais recente da calibração do servidor para evitar conflito 409
      try {
        const fresh = await this.deps.api.getCalibration(cal.calibration_id);
        this.queue?.setVersion(fresh.version);
        if (this.snapshot.calibration) {
          this.set({ calibration: { ...this.snapshot.calibration, version: fresh.version } });
        }
      } catch {
        /* ignora falha de sync pré-commit */
      }

      // Agrupa correções por table_id
      const byTable: Record<string, CellCorrection[]> = {};
      for (const c of resp.corrections) {
        const list = byTable[c.table_id] ?? [];
        list.push(c);
        byTable[c.table_id] = list;
      }

      let totalApplied = 0;
      for (const [tid, corrs] of Object.entries(byTable)) {
        const guarded = this.guard(tid);
        if (!guarded) continue;

        const newValues = guarded.values.map((row) => [...row]);

        for (const c of corrs) {
          const row = newValues[c.row];
          if (row && row[c.col] !== undefined) {
            row[c.col] = c.new_value;
          }
        }

        const delta = makeDelta(tid, guarded.values, newValues, "ai_tune");
        if (delta.cells.length > 0) {
          const result: OpResult = {
            values: newValues,
            delta,
            clamped: 0,
          };
          if (this.commit(guarded, result)) {
            totalApplied += delta.cells.length;
          }
        }
      }

      const gainMsg = resp.estimated_torque_gain_pct > 0 ? ` (+${resp.estimated_torque_gain_pct}% torque estimado)` : "";
      this.notify(
        resp.safety_risk ? "warn" : "success",
        `🤖 LAYA.ai: ${resp.summary}${gainMsg}`
      );
      return totalApplied > 0;
    } catch (err) {
      const p = problemOf(err);
      this.notify("error", `Falha no ajuste por IA: ${p.detail}`);
      return false;
    } finally {
      this.set({ aiTuning: false });
    }
  }

  copy(tableId: string): string {
    const t = this.snapshot.tables[tableId];
    if (!t) return "";
    const rect = selectionRect(this.selection(tableId), t.values.length, t.values[0]?.length ?? 0);
    return toTsv(t.values, rect, t.decimals);
  }

  paste(tableId: string, text: string): boolean {
    const t = this.guard(tableId);
    if (!t) return false;
    const grid = parseTsv(text);
    const sel = this.selection(tableId);
    const rect = selectionRect(sel, t.values.length, t.values[0]?.length ?? 0);
    const result = pasteGrid(t, { row: rect.r0, col: rect.c0 }, grid);
    if (result.written === 0) {
      this.notify("warn", MSG.pasteNothing);
      return false;
    }
    const ignored = result.outside + result.invalid;
    return this.commit(t, result, ignored > 0 ? MSG.pasteIgnored(ignored) : undefined);
  }

  undo(): void {
    const d = this.undoStack.undo();
    if (d) this.replay(d, "backward");
  }

  redo(): void {
    const d = this.undoStack.redo();
    if (d) this.replay(d, "forward");
  }

  private replay(delta: TableDelta, direction: "forward" | "backward"): void {
    const t = this.snapshot.tables[delta.tableId];
    if (!t || this.isLocked(delta.tableId)) {
      // Não aplicável agora: devolve o passo à pilha original.
      if (direction === "backward") this.undoStack.redo();
      else this.undoStack.undo();
      if (t) this.notify("warn", `${delta.tableId}: ${MSG.lockedDuringRun}`);
      return;
    }
    this.set({
      tables: { ...this.snapshot.tables, [t.tableId]: { ...t, values: applyDelta(t.values, delta, direction) } },
      canUndo: this.undoStack.canUndo,
      canRedo: this.undoStack.canRedo,
    });
    this.enqueueDelta(t, delta, direction);
    this.markDirty(t.tableId);
  }

  // ---------------------------------------------------------------- respostas da fila

  private onSaved(tableId: string, version: number, table: Calibration["tables"][string]): void {
    const cal = this.snapshot.calibration;
    if (!cal) return;
    this.set({ calibration: { ...cal, version, tables: { ...cal.tables, [tableId]: table } } });
    if (this.autoApply && !this.queue?.hasPending()) this.requestAutoApply();
  }

  /** Live Tuning (RF-07): após cada lote gravado sem pendências, aplica à sessão (se `canApply`). */
  setAutoApply(enabled: boolean): void {
    this.autoApply = enabled;
  }

  private requestAutoApply(): void {
    if (this.snapshot.applying) {
      this.autoApplyQueued = true;
      return;
    }
    if (this.canApply()) void this.applyToSession();
  }

  private markStock(): void {
    this.set({ readOnly: true, stock: true });
    this.notify("error", MSG.stockImmutable);
  }

  private onLocked(tableId: string): void {
    // EC-03: reverte a pintura local para o valor do servidor e mantém o rascunho.
    const server = this.snapshot.calibration?.tables[tableId];
    if (server) this.set({ tables: { ...this.snapshot.tables, [tableId]: toGridTable(server) } });
    this.set({ heldTables: this.queue?.heldTables() ?? [] });
    this.notify("warn", `${tableId}: ${MSG.lockedDuringRun}`);
  }

  private async onRejected(problem: ApiProblem, tableId: string): Promise<void> {
    if (problem.code === STOCK_IMMUTABLE_CODE) this.markStock();
    else this.notify("error", `${MSG.notSaved}: ${problem.detail} (${problem.code})`);
    await this.reloadTable(tableId);
  }

  private async reloadTable(tableId: string): Promise<void> {
    const cal = this.snapshot.calibration;
    if (!cal) return;
    try {
      const fresh = await this.api.getCalibration(cal.calibration_id);
      const t = fresh.tables[tableId];
      if (t) this.set({ tables: { ...this.snapshot.tables, [tableId]: toGridTable(t) }, calibration: { ...cal, version: fresh.version, tables: { ...cal.tables, [tableId]: t } } });
      this.queue?.setVersion(fresh.version);
    } catch {
      /* mantém o estado local; a barra mostra o erro */
    }
  }

  private async onConflict(_problem: ApiProblem, tableId: string, latest: number | null): Promise<void> {
    const cal = this.snapshot.calibration;
    this.set({ conflict: { tableId, latestVersion: latest, server: null, diff: null } });
    if (!cal) return;
    try {
      const server = await this.api.getCalibration(cal.calibration_id);
      const local = { ...cal, tables: { ...cal.tables } };
      for (const [id, t] of Object.entries(this.snapshot.tables)) {
        const view = local.tables[id];
        if (view) local.tables[id] = { ...view, values: toContractValues(t) };
      }
      this.set({ conflict: { tableId, latestVersion: latest ?? server.version, server, diff: diffCalibrations(server, local) } });
    } catch {
      /* diálogo continua com as duas opções */
    }
  }

  /** EC-02: "Recarregar" (versão do servidor) ou "Sobrescrever com as minhas alterações". */
  async resolveConflict(choice: "reload" | "overwrite"): Promise<void> {
    const conflict = this.snapshot.conflict;
    const cal = this.snapshot.calibration;
    if (!conflict || !cal || !this.queue) return;
    let server = conflict.server;
    if (!server) {
      try {
        server = await this.api.getCalibration(cal.calibration_id);
      } catch (error) {
        this.notify("error", problemOf(error).detail);
        return;
      }
    }
    const latest = conflict.latestVersion ?? server.version;
    if (choice === "reload") {
      this.queue.resolveConflict("reload", server.version);
      this.undoStack.clear();
      this.set({ calibration: server, tables: gridTables(server), conflict: null, canUndo: false, canRedo: false });
      return;
    }
    this.set({ conflict: null, calibration: { ...cal, version: latest } });
    this.queue.resolveConflict("overwrite", latest);
  }

  retrySave(): void {
    this.queue?.retry();
  }

  saveState(): SaveState {
    return this.queue?.state ?? "idle";
  }

  // ---------------------------------------------------------------- versões e estratégias

  private contentBody(cal: Calibration, patch: { strategies?: Record<string, unknown>; changeSummary?: string; name?: string }): CalibrationPutBody {
    const tables: Record<string, unknown> = {};
    for (const [id, view] of Object.entries(cal.tables)) {
      const local = this.snapshot.tables[id];
      tables[id] = local ? { ...view, values: toContractValues({ ...local, values: local.values.map((r) => r.map((v) => roundTo(v, local.decimals))) }) } : view;
    }
    return {
      base_version: this.queue?.version ?? cal.version,
      fuel_model: cal.fuel_model,
      tables,
      strategies: patch.strategies ?? cal.strategies,
      profile_params: cal.profile_params,
      metadata: {
        ...cal.metadata,
        name: patch.name ?? cal.metadata.name,
        change_summary: (patch.changeSummary ?? cal.metadata.change_summary).slice(0, 200),
      },
    };
  }

  private async put(body: CalibrationPutBody): Promise<Calibration | null> {
    const cal = this.snapshot.calibration;
    if (!cal) return null;
    this.lastPutProblem = null;
    try {
      const next = await this.api.putCalibration(cal.calibration_id, body);
      const withVersions = await this.api.getCalibration(cal.calibration_id, { includeVersions: true }).catch(() => next);
      const merged = { ...next, versions: withVersions.versions ?? next.versions ?? cal.versions };
      this.queue?.setVersion(next.version);
      this.set({ calibration: merged, tables: gridTables(merged) });
      return merged;
    } catch (error) {
      const p = problemOf(error);
      this.lastPutProblem = isApiProblem(error) ? error : null;
      if (p.code === STOCK_IMMUTABLE_CODE) {
        this.markStock();
        return null;
      }
      if (p.code === "CALIBRATION_VERSION_CONFLICT") {
        this.set({ conflict: { tableId: "", latestVersion: isApiProblem(error) && typeof error.extra.latest_version === "number" ? error.extra.latest_version : null, server: null, diff: null } });
      }
      this.notify("error", `${MSG.notSaved}: ${p.detail} (${p.code})`);
      return null;
    }
  }

  /** "Salvar versão" (Ctrl/Cmd+S): grava o pendente e cria uma versão com nome. */
  async saveVersion(label: string): Promise<Calibration | null> {
    const cal = this.snapshot.calibration;
    if (!cal) return null;
    await this.queue?.flush();
    const current = this.snapshot.calibration ?? cal;
    const next = await this.put(this.contentBody(current, { changeSummary: label || "versão salva" }));
    if (next) this.notify("success", MSG.saved(next.version));
    return next;
  }

  async saveStrategy(kind: string, config: Record<string, unknown>): Promise<Calibration | null> {
    const cal = this.snapshot.calibration;
    if (!cal) return null;
    await this.queue?.flush();
    const current = this.snapshot.calibration ?? cal;
    const strategies = { ...current.strategies, [kind]: { ...config, kind } };
    const next = await this.put(this.contentBody(current, { strategies, changeSummary: `estratégia ${kind}` }));
    if (next) {
      this.set({ dirtyOther: true });
      this.notify("success", MSG.saved(next.version));
    }
    return next;
  }

  /** Correções por cilindro (RF-21): grava o valor uniforme em cada tabela de trim. */
  async saveCylinderTrims(kind: "fuel_trim_cyl" | "ignition_trim_cyl", byCylinder: Record<number, number>): Promise<number> {
    let written = 0;
    for (const t of Object.values(this.snapshot.tables)) {
      if (t.kind !== kind || t.cylinder === null) continue;
      const value = byCylinder[t.cylinder];
      if (value === undefined) continue;
      const rect = { r0: 0, r1: t.values.length - 1, c0: 0, c1: (t.values[0]?.length ?? 1) - 1 };
      const guarded = this.guard(t.tableId);
      if (!guarded) continue;
      if (this.commit(guarded, setValue(guarded, rect, value))) written += 1;
    }
    await this.queue?.flush();
    return written;
  }

  async revertTo(version: number): Promise<Calibration | null> {
    const cal = this.snapshot.calibration;
    if (!cal) return null;
    await this.queue?.flush();
    const next = await this.put({ base_version: this.queue?.version ?? cal.version, revert_to_version: version, change_summary: `reverter para a versão ${version}` });
    if (next) {
      this.undoStack.clear();
      this.set({ canUndo: false, canRedo: false, dirtyOther: true });
      this.notify("success", MSG.saved(next.version));
    }
    return next;
  }

  async fetchVersion(version: number): Promise<Calibration> {
    const cal = this.snapshot.calibration;
    if (!cal) throw new Error("sem calibração");
    return this.api.getCalibration(cal.calibration_id, { version });
  }

  // ---------------------------------------------------------------- sessão

  /** Só alterações em tabelas live-tunable desde a última aplicação (RF-18). */
  onlyLiveChanges(): boolean {
    return !this.snapshot.dirtyOther && this.snapshot.dirtyTables.every((id) => this.isLiveTunable(id));
  }

  canApply(): boolean {
    if (!this.snapshot.calibration || this.snapshot.applying) return false;
    if (isRunActive(this.snapshot.runState)) return this.onlyLiveChanges() && (this.snapshot.dirtyTables.length > 0);
    return true;
  }

  async applyToSession(): Promise<ApplyCalibrationResult | null> {
    const cal = this.snapshot.calibration;
    if (!cal || !this.canApply()) return null;
    this.set({ applying: true });
    const seq = this.editSeq;
    try {
      await this.queue?.flush();
      const isOem = this.snapshot.profile?.profile_id === "oem-stage" || this.snapshot.profile?.family === "oem";
      const profile_options: Record<string, boolean> = isOem ? { auto_fix_checksum: true } : {};
      const result = await this.api.applyToSession(this.sessionId, {
        calibration_id: cal.calibration_id,
        version: this.queue?.version ?? cal.version,
        profile_options,
      });
      const untouched = seq === this.editSeq;
      this.set({ applied: result, applying: false, ...(untouched ? { dirtyTables: [], dirtyOther: false } : {}) });
      this.notify("success", MSG.applied(result.version));
      return result;
    } catch (error) {
      const p = problemOf(error);
      const items = isApiProblem(error) && Array.isArray(error.extra.items) ? ` (${(error.extra.items as unknown[]).join(", ")})` : "";
      this.set({ applying: false });
      this.notify("error", `${p.title}: ${p.detail}${items}`);
      return null;
    } finally {
      this.drainAutoApply();
    }
  }

  private drainAutoApply(): void {
    if (!this.autoApplyQueued) return;
    this.autoApplyQueued = false;
    if (this.autoApply && !this.queue?.hasPending()) this.requestAutoApply();
  }

  /**
   * "Clonar e editar" (RF-04): cria a cópia do usuário da calibração de série, aplica-a à sessão
   * e recarrega o workspace com a cópia editável.
   */
  async cloneAndEdit(): Promise<Calibration | null> {
    const cal = this.snapshot.calibration;
    if (!cal || this.snapshot.cloning) return null;
    this.set({ cloning: true });
    try {
      const name = `${cal.metadata.name} (cópia)`.slice(0, 80);
      const clone = await this.api.cloneCalibration({
        vehicle_id: cal.vehicle_id,
        profile_id: cal.profile_id,
        source: "clone",
        clone_from_id: cal.calibration_id,
        clone_from_version: cal.version,
        metadata: { name, source: "clone", change_summary: `cópia de ${cal.calibration_id}` },
      });
      const isOem = this.snapshot.profile?.profile_id === "oem-stage" || this.snapshot.profile?.family === "oem";
      const profile_options: Record<string, boolean> = isOem ? { auto_fix_checksum: true } : {};
      await this.api.applyToSession(this.sessionId, { calibration_id: clone.calibration_id, version: clone.version, profile_options });
      await this.load();
      if (this.snapshot.calibration?.calibration_id !== clone.calibration_id) {
        this.installCalibration(await this.api.getCalibration(clone.calibration_id, { includeVersions: true }));
      }
      this.notify("success", MSG.cloned(clone.metadata.name));
      return clone;
    } catch (error) {
      const p = problemOf(error);
      this.notify("error", `${p.title}: ${p.detail} (${p.code})`);
      return null;
    } finally {
      this.set({ cloning: false });
    }
  }

  // ---------------------------------------------------------------- swap e base

  async swap(body: SwapRequestBody): Promise<SwapResult | null> {
    try {
      const result = await this.api.swap(this.sessionId, body);
      const session = this.snapshot.session;
      const profile = await this.api.getProfile(result.profile_id, session?.vehicle_id).catch(() => this.snapshot.profile);
      this.set({
        swap: result,
        wizardOpen: true,
        profile,
        session: session ? { ...session, profile_id: result.profile_id, ecu_state: result.ecu_state } : session,
      });
      return result;
    } catch (error) {
      const p = problemOf(error);
      this.notify("error", `${p.title}: ${p.detail} (${p.code})`);
      return null;
    }
  }

  openWizard(open: boolean): void {
    this.set({ wizardOpen: open });
  }

  /** Base gravada pelo assistente: recarrega sessão, perfil e a calibração base gerada. */
  async onBaseSetupDone(result: BaseSetupResult): Promise<void> {
    this.set({ wizardOpen: false, swap: null, activeItemId: null });
    await this.load();
    if (result.ecu_state === "standalone_ready") this.notify("success", "Configuração base gravada: o motor pode arrancar e ficar em marcha lenta.");
  }

  /** Troca de carro (seletor dos 4 carros): cria sessão nova com o perfil de série. */
  async switchVehicle(vehicleId: string, profileId: string, closeCurrent = false): Promise<Session> {
    if (closeCurrent) await this.api.deleteSession(this.sessionId);
    return this.api.createSession({ vehicle_id: vehicleId, profile_id: profileId });
  }
}
