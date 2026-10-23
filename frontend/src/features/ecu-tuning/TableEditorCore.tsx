/**
 * Mecanismo comum de `TableEditor2D` e `TableEditor3D` (tuning RF-03 a RF-12, RF-17, RF-20,
 * RF-22): liga a grade à store (seleção, edição, operações, undo/redo), trata os atalhos de
 * teclado da tabela, a cópia/colagem TSV (Clipboard API com fallback para `copy`/`paste`), o
 * cursor de operação e a vista 3D opcional. Abaixo de `lg` a grade e a vista 3D alternam em abas;
 * setas vindas de botões do editor voltam o foco à grade em vez de rolar a página.
 * Feature 002 (RF-08, RF-09): `Q` Quick Tune, `H`/`V` interpolação horizontal/vertical e `B`
 * suavização de bloco; cada operação é 1 passo de desfazer. `overlay` substitui o cursor padrão.
 */
import { useEffect, useMemo, useRef, useState, useSyncExternalStore, type KeyboardEvent, type ReactNode } from "react";

import { formatNumber } from "@/lib/units";
import { LG_PX, useMinWidth } from "@/lib/useMinWidth";

import { MSG } from "./messages";
import { selectionRect, singleCell, type Selection } from "./model";
import { OperationCursor } from "./OperationCursor";
import { isLambdaTable, lambdaToAfr } from "./prefs";
import { LockIcon } from "./ProfileNavigator";
import { Table3DView } from "./Table3DView";
import { TableGrid, type GridGeometry } from "./TableGrid";
import { TableToolbar, type TableToolbarHandle } from "./TableToolbar";
import { warnedCells, type TuningWarning } from "./warnings";
import type { TableOperation, WorkspaceStore } from "./workspaceStore";

const QUICK_OPS: Readonly<Record<string, TableOperation | "quick_tune">> = {
  q: "quick_tune",
  h: { op: "interp_h" },
  v: { op: "interp_v" },
  b: { op: "block_smooth" },
};

const EDIT_KEYS = new Set(["=", "+", "-", "−", "*", "i", "I", "s", "S", ...Object.keys(QUICK_OPS), ...Object.keys(QUICK_OPS).map((k) => k.toUpperCase())]);

function isTextField(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  return el.tagName === "INPUT" || el.tagName === "SELECT" || el.tagName === "TEXTAREA" || el.isContentEditable;
}

export interface TableEditorProps {
  store: WorkspaceStore;
  tableId: string;
  /** Rótulo do item de navegação (terminologia do perfil). */
  title: string;
  warnings?: readonly TuningWarning[];
}

export interface TableEditorCoreProps extends TableEditorProps {
  variant: "2d" | "3d";
  /** Camada sobre a grade (ex.: célula ao vivo da bancada); padrão: cursor de operação do editor. */
  overlay?: (geom: GridGeometry) => ReactNode;
}

export function TableEditorCore({ store, tableId, title, warnings = [], variant, overlay }: TableEditorCoreProps) {
  const snap = useSyncExternalStore(store.subscribe, store.getSnapshot);
  const toolbarRef = useRef<TableToolbarHandle>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const table = snap.tables[tableId];
  const selection: Selection = snap.selections[tableId] ?? singleCell(0, 0);
  const locked = store.isLocked(tableId);
  const readOnly = locked || snap.readOnly;
  const stoich = store.afrStoich();
  const lambdaTable = table ? isLambdaTable(table.kind) : false;
  const afr = lambdaTable && stoich !== null && snap.prefs.lambdaDisplay === "afr";
  const warned = useMemo(() => warnedCells(warnings, tableId), [warnings, tableId]);

  const wide = useMinWidth(LG_PX);
  const [pane, setPane] = useState<"grid" | "3d">("grid");

  const focusGrid = () => wrapperRef.current?.querySelector<HTMLElement>('[role="grid"]')?.focus();

  // Fallback dos eventos `copy`/`paste` com a grade focada (RNF-07).
  useEffect(() => {
    const inGrid = () => {
      const grid = wrapperRef.current?.querySelector('[role="grid"]');
      return Boolean(grid && document.activeElement && grid.contains(document.activeElement));
    };
    const onCopy = (e: ClipboardEvent) => {
      if (!inGrid() || !e.clipboardData) return;
      e.clipboardData.setData("text/plain", store.copy(tableId));
      e.preventDefault();
    };
    const onPaste = (e: ClipboardEvent) => {
      if (!inGrid() || !e.clipboardData) return;
      const text = e.clipboardData.getData("text/plain");
      e.preventDefault();
      store.paste(tableId, text);
    };
    document.addEventListener("copy", onCopy);
    document.addEventListener("paste", onPaste);
    return () => {
      document.removeEventListener("copy", onCopy);
      document.removeEventListener("paste", onPaste);
    };
  }, [store, tableId]);

  if (!table) return <p className="p-4 text-sm text-zinc-300">{MSG.emptySection}</p>;

  const rect = selectionRect(selection, table.values.length, table.values[0]?.length ?? 0);
  const show3d = variant === "3d" && snap.prefs.show3d !== "off";
  const tabbed = show3d && !wide;

  const copyButton = async () => {
    const text = store.copy(tableId);
    try {
      await navigator.clipboard.writeText(text);
      store.notify("info", "Seleção copiada em TSV.");
    } catch {
      store.notify("warn", "Área de transferência indisponível: use Ctrl/Cmd+C com a grade focada.");
    }
  };

  const pasteButton = async () => {
    try {
      const text = await navigator.clipboard.readText();
      store.paste(tableId, text);
    } catch {
      store.notify("warn", "Área de transferência indisponível: use Ctrl/Cmd+V com a grade focada.");
    }
  };

  const runQuickOp = (op: TableOperation | "quick_tune") => {
    if (op === "quick_tune") store.quickTune(tableId);
    else store.applyOperation(tableId, op);
  };

  const onShortcut = (e: KeyboardEvent<HTMLDivElement>): boolean => {
    if (isTextField(e.target)) return false;
    const mod = e.ctrlKey || e.metaKey;
    const k = e.key;
    if (mod && k.toLowerCase() === "z") {
      e.preventDefault();
      if (e.shiftKey) store.redo();
      else store.undo();
      return true;
    }
    if (mod && k.toLowerCase() === "y") {
      e.preventDefault();
      store.redo();
      return true;
    }
    if (mod) return false; // Ctrl+C/V seguem para os eventos copy/paste; Ctrl+S/Enter sobem ao workspace
    if (k === "F3") {
      e.preventDefault();
      if (variant === "3d") store.setPrefs({ show3d: snap.prefs.show3d === "off" ? "side" : "off" });
      return true;
    }
    if (readOnly && EDIT_KEYS.has(k)) {
      store.notify("warn", locked ? `${title}: ${MSG.lockedDuringRun}` : snap.stock ? MSG.stockReadOnly : MSG.readOnly);
      e.preventDefault();
      return true;
    }
    const valueOp = { "=": "set", "+": "add", "-": "sub", "−": "sub", "*": "scale" } as const;
    if (k in valueOp) {
      e.preventDefault();
      toolbarRef.current?.focusValue(valueOp[k as keyof typeof valueOp]);
      return true;
    }
    if (k === "i" || k === "I") {
      e.preventDefault();
      store.applyOperation(tableId, { op: e.shiftKey || k === "I" ? "interp_block" : "interp_line" });
      return true;
    }
    if (k === "s" || k === "S") {
      e.preventDefault();
      store.applyOperation(tableId, { op: "smooth" });
      return true;
    }
    const quick = e.altKey ? undefined : QUICK_OPS[k.toLowerCase()];
    if (quick) {
      e.preventDefault();
      runQuickOp(quick);
      return true;
    }
    return false;
  };

  const limitText = `${formatNumber(table.min, table.decimals)} a ${formatNumber(table.max, table.decimals)} ${table.unit}`;
  const unitLabel = afr ? "AFR" : table.unit;

  return (
    <section
      ref={wrapperRef}
      aria-labelledby={`tbl-${tableId}-title`}
      onKeyDown={(e) => {
        const el = e.target as HTMLElement;
        if (!e.key.startsWith("Arrow") || el.getAttribute("role") === "grid" || el.getAttribute("role") === "tab") return;
        if (el.tagName === "INPUT" || el.tagName === "SELECT" || el.tagName === "TEXTAREA" || el.isContentEditable) return;
        e.preventDefault();
        if (!tabbed || pane === "grid") focusGrid();
      }}
      className="flex min-w-0 flex-col gap-2"
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id={`tbl-${tableId}-title`} className="text-base font-semibold text-zinc-100">
          {title}
          <span className="ml-2 text-xs font-normal text-zinc-400">
            {table.y ? `${table.values.length}×${table.values[0]?.length ?? 0}` : `1×${table.values[0]?.length ?? 0}`} · {unitLabel} · limites {limitText}
          </span>
        </h2>
        {locked && (
          <p className="flex items-center gap-1 text-xs font-semibold text-amber-300" role="status">
            <LockIcon /> {MSG.lockedDuringRun}
          </p>
        )}
      </header>
      <TableToolbar
        ref={toolbarRef}
        rect={rect}
        disabled={readOnly}
        canUndo={snap.canUndo}
        canRedo={snap.canRedo}
        heatmap={snap.prefs.heatmap === "on"}
        lambdaTable={lambdaTable}
        lambdaDisplay={snap.prefs.lambdaDisplay}
        afrAvailable={stoich !== null}
        is3d={variant === "3d"}
        show3d={show3d}
        onOperation={(op) => store.applyOperation(tableId, op)}
        onQuickTune={() => store.quickTune(tableId)}
        onAiTune={(level) => void store.aiTune(undefined, level)}
        aiTuning={snap.aiTuning}
        aiAggressiveness={snap.aiAggressiveness ?? "balanced"}
        onSetAiAggressiveness={(level) => store.setAiAggressiveness(level)}
        onCopy={() => void copyButton()}
        onPaste={() => void pasteButton()}
        onUndo={() => store.undo()}
        onRedo={() => store.redo()}
        onToggleHeatmap={() => store.setPrefs({ heatmap: snap.prefs.heatmap === "on" ? "off" : "on" })}
        onToggleLambda={() => store.setPrefs({ lambdaDisplay: snap.prefs.lambdaDisplay === "afr" ? "lambda" : "afr" })}
        onToggle3d={() => store.setPrefs({ show3d: show3d ? "off" : "side" })}
        onDone={focusGrid}
      />
      {tabbed && (
        <div role="tablist" aria-label="Vista da tabela" className="flex gap-1">
          {(["grid", "3d"] as const).map((p) => (
            <button
              key={p}
              type="button"
              role="tab"
              id={`tbl-${tableId}-tab-${p}`}
              aria-selected={pane === p}
              aria-controls={`tbl-${tableId}-pane-${p}`}
              tabIndex={pane === p ? 0 : -1}
              onClick={() => setPane(p)}
              onKeyDown={(e) => {
                if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
                  e.preventDefault();
                  const next = p === "grid" ? "3d" : "grid";
                  setPane(next);
                  document.getElementById(`tbl-${tableId}-tab-${next}`)?.focus();
                }
              }}
              className={`rounded px-3 py-1 text-xs focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-400 ${pane === p ? "bg-zinc-700 text-amber-300" : "text-zinc-200 hover:bg-zinc-800"}`}
            >
              {p === "grid" ? "Tabela" : "Vista 3D"}
            </button>
          ))}
        </div>
      )}
      <div className={show3d && !tabbed && snap.prefs.show3d === "side" ? "grid grid-cols-[minmax(0,1fr)_auto] gap-2" : "flex flex-col gap-2"}>
        <div id={`tbl-${tableId}-pane-grid`} role={tabbed ? "tabpanel" : undefined} aria-labelledby={tabbed ? `tbl-${tableId}-tab-grid` : undefined} hidden={tabbed && pane !== "grid"} className="min-w-0">
          <TableGrid
            idPrefix={`g-${tableId}`}
            table={table}
            selection={selection}
            onSelectionChange={(sel) => store.setSelection(tableId, sel)}
            onEditCell={(r, c, v) => store.editCell(tableId, r, c, v)}
            label={`${title} (${unitLabel})`}
            heatmap={snap.prefs.heatmap === "on"}
            readOnly={readOnly}
            display={afr && stoich !== null ? (v) => lambdaToAfr(v, stoich) : undefined}
            displayDecimals={afr ? 1 : table.decimals}
            displayUnit={unitLabel}
            warned={warned}
            onShortcut={onShortcut}
            overlay={overlay ?? (store.feed ? (geom) => <OperationCursor feed={store.feed!} x={table.x} y={table.y} geom={geom} /> : undefined)}
          />
        </div>
        {show3d && (!tabbed || pane === "3d") && (
          <div id={`tbl-${tableId}-pane-3d`} role={tabbed ? "tabpanel" : undefined} aria-labelledby={tabbed ? `tbl-${tableId}-tab-3d` : undefined} className="min-w-0">
            <Table3DView values={table.values} focus={selection.focus} label={title} />
          </div>
        )}
      </div>
    </section>
  );
}
