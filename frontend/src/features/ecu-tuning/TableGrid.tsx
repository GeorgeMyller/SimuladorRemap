/**
 * Grade de valores partilhada por `TableEditor2D` e `TableEditor3D` (tuning RF-03, RF-04,
 * RF-10, RF-20; RNF-02, RNF-06). Virtualiza linhas e colunas (só o visível + margem é montado),
 * mostra os breakpoints e as unidades nos cabeçalhos, pinta o heatmap com o valor sempre visível
 * e expõe `role="grid"` com `aria-rowindex`/`aria-colindex` e foco por `aria-activedescendant`.
 */
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

import { formatNumber } from "@/lib/units";

import { cellColors, valueRange } from "./heatmap";
import { inRect, selectionRect, type CellRef, type GridTable, type Selection } from "./model";
import { parseCellNumber } from "./ops/tsv";
import type { TuningWarning } from "./warnings";

export const COL_W = 64;
export const ROW_H = 28;
export const HEADER_W = 84;
export const HEADER_H = 30;
const OVERSCAN = 2;
const ARROW_KEYS = new Set(["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"]);
const DEFAULT_VIEW = { width: 720, height: 460 };

export interface GridGeometry {
  colW: number;
  rowH: number;
  headerW: number;
  headerH: number;
  rows: number;
  cols: number;
}

export interface TableGridProps {
  table: GridTable;
  selection: Selection;
  onSelectionChange: (sel: Selection) => void;
  /** Grava o valor digitado (na unidade exibida). */
  onEditCell: (row: number, col: number, displayed: number) => boolean;
  label: string;
  heatmap: boolean;
  readOnly?: boolean;
  /** Valor gravado → valor exibido (ex.: λ → AFR). */
  display?: (v: number) => number;
  displayDecimals?: number;
  displayUnit?: string;
  warned?: Map<string, TuningWarning[]>;
  /** Atalhos que não são de navegação (`=`, `+`, `I`, `Ctrl+Z`…); devolve `true` se tratou. */
  onShortcut?: (e: KeyboardEvent<HTMLDivElement>) => boolean;
  overlay?: (geom: GridGeometry) => ReactNode;
  idPrefix: string;
}

function axisLabel(v: number, unit: string): string {
  const decimals = Math.abs(v) >= 100 || Number.isInteger(v) ? 0 : 1;
  return `${formatNumber(v, decimals)}${unit ? ` ${unit}` : ""}`;
}

function clampCell(c: CellRef, rows: number, cols: number): CellRef {
  return { row: Math.min(rows - 1, Math.max(0, c.row)), col: Math.min(cols - 1, Math.max(0, c.col)) };
}

export function TableGrid(props: TableGridProps) {
  const { table, selection, onSelectionChange, onEditCell, heatmap, readOnly = false, label, idPrefix } = props;
  const display = props.display ?? ((v: number) => v);
  const decimals = props.displayDecimals ?? table.decimals;
  const rows = table.values.length;
  const cols = table.values[0]?.length ?? 0;
  const containerRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef(false);
  const [view, setView] = useState({ top: 0, left: 0, ...DEFAULT_VIEW });
  const [editing, setEditing] = useState<{ row: number; col: number; text: string } | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el || typeof ResizeObserver !== "function") return;
    const ro = new ResizeObserver((entries) => {
      const box = entries[0]?.contentRect;
      if (box && box.width > 0 && box.height > 0) setView((v) => ({ ...v, width: box.width, height: box.height }));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const up = () => {
      draggingRef.current = false;
    };
    window.addEventListener("mouseup", up);
    return () => window.removeEventListener("mouseup", up);
  }, []);

  const rect = selectionRect(selection, rows, cols);
  const focus = clampCell(selection.focus, rows, cols);
  const visibleRows = Math.max(1, Math.floor((view.height - HEADER_H) / ROW_H));
  const r0 = Math.max(0, Math.floor(view.top / ROW_H) - OVERSCAN);
  const r1 = Math.min(rows - 1, Math.ceil((view.top + view.height - HEADER_H) / ROW_H) + OVERSCAN);
  const c0 = Math.max(0, Math.floor(view.left / COL_W) - OVERSCAN);
  const c1 = Math.min(cols - 1, Math.ceil((view.left + view.width - HEADER_W) / COL_W) + OVERSCAN);
  const rowIdx: number[] = [];
  for (let r = r0; r <= r1; r += 1) rowIdx.push(r);
  if (!rowIdx.includes(focus.row)) rowIdx.push(focus.row);
  const colIdx: number[] = [];
  for (let c = c0; c <= c1; c += 1) colIdx.push(c);
  if (!colIdx.includes(focus.col)) colIdx.push(focus.col);
  const range = valueRange(table.values);
  const cellId = (r: number, c: number) => `${idPrefix}-c-${r}-${c}`;
  const xUnit = table.x.unit;
  const yUnit = table.y?.unit ?? "";

  const scrollIntoView = (c: CellRef) => {
    const el = containerRef.current;
    if (!el) return;
    const top = c.row * ROW_H;
    const left = c.col * COL_W;
    const h = el.clientHeight || view.height;
    const w = el.clientWidth || view.width;
    if (top < el.scrollTop) el.scrollTop = top;
    else if (top + ROW_H > el.scrollTop + h - HEADER_H) el.scrollTop = top + ROW_H - (h - HEADER_H);
    if (left < el.scrollLeft) el.scrollLeft = left;
    else if (left + COL_W > el.scrollLeft + w - HEADER_W) el.scrollLeft = left + COL_W - (w - HEADER_W);
    setView((v) => ({ ...v, top: el.scrollTop, left: el.scrollLeft }));
  };

  const moveTo = (c: CellRef, extend: boolean) => {
    const next = clampCell(c, rows, cols);
    onSelectionChange(extend ? { anchor: selection.mode === "cells" ? selection.anchor : { row: rect.r0, col: rect.c0 }, focus: next, mode: "cells" } : { anchor: next, focus: next, mode: "cells" });
    scrollIntoView(next);
  };

  const startEdit = (text?: string) => {
    if (readOnly) return;
    const v = table.values[focus.row]?.[focus.col];
    setEditing({ row: focus.row, col: focus.col, text: text ?? (v === undefined ? "" : String(Number(display(v).toFixed(decimals)))) });
  };

  const commitEdit = (keepFocus = true) => {
    if (!editing) return;
    const n = parseCellNumber(editing.text);
    setEditing(null);
    if (n !== null) onEditCell(editing.row, editing.col, n);
    if (keepFocus) containerRef.current?.focus();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    // Setas dentro da grade nunca rolam a página, mesmo durante a edição de uma célula.
    if (ARROW_KEYS.has(e.key)) e.preventDefault();
    if (editing) return;
    const mod = e.ctrlKey || e.metaKey;
    const { row, col } = focus;
    switch (e.key) {
      case "ArrowUp":
      case "ArrowDown":
      case "ArrowLeft":
      case "ArrowRight": {
        const d = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] }[e.key] as [number, number];
        moveTo({ row: row + d[0], col: col + d[1] }, e.shiftKey);
        return;
      }
      case "Tab": {
        const nextCol = col + (e.shiftKey ? -1 : 1);
        if (nextCol < 0 || nextCol >= cols) return; // deixa o foco sair da grade
        e.preventDefault();
        moveTo({ row, col: nextCol }, false);
        return;
      }
      case "Home":
        e.preventDefault();
        moveTo({ row: mod ? 0 : row, col: 0 }, e.shiftKey);
        return;
      case "End":
        e.preventDefault();
        moveTo({ row: mod ? rows - 1 : row, col: cols - 1 }, e.shiftKey);
        return;
      case "PageUp":
        e.preventDefault();
        moveTo({ row: row - visibleRows, col }, e.shiftKey);
        return;
      case "PageDown":
        e.preventDefault();
        moveTo({ row: row + visibleRows, col }, e.shiftKey);
        return;
      case "Enter":
      case "F2":
        if (mod) break;
        e.preventDefault();
        startEdit();
        return;
      case "Escape":
        onSelectionChange({ anchor: focus, focus, mode: "cells" });
        return;
      default:
        break;
    }
    if (mod && e.key.toLowerCase() === "a") {
      e.preventDefault();
      onSelectionChange({ anchor: { row: 0, col: 0 }, focus: { row: rows - 1, col: cols - 1 }, mode: "all" });
      return;
    }
    if (props.onShortcut?.(e)) return;
    if (!mod && !e.altKey && /^[0-9.,]$/.test(e.key)) {
      e.preventDefault();
      startEdit(e.key);
    }
  };

  const onCellMouseDown = (r: number, c: number, shift: boolean) => {
    containerRef.current?.focus();
    draggingRef.current = true;
    const cellRef = { row: r, col: c };
    onSelectionChange(shift ? { anchor: selection.anchor, focus: cellRef, mode: "cells" } : { anchor: cellRef, focus: cellRef, mode: "cells" });
  };

  const onCellEnter = (r: number, c: number) => {
    if (!draggingRef.current) return;
    onSelectionChange({ anchor: selection.anchor, focus: { row: r, col: c }, mode: "cells" });
  };

  const onColHeader = (c: number, shift: boolean) => {
    containerRef.current?.focus();
    const anchorCol = shift && selection.mode === "cols" ? selection.anchor.col : c;
    onSelectionChange({ anchor: { row: 0, col: anchorCol }, focus: { row: rows - 1, col: c }, mode: "cols" });
  };

  const onRowHeader = (r: number, shift: boolean) => {
    containerRef.current?.focus();
    const anchorRow = shift && selection.mode === "rows" ? selection.anchor.row : r;
    onSelectionChange({ anchor: { row: anchorRow, col: 0 }, focus: { row: r, col: cols - 1 }, mode: "rows" });
  };

  const geom: GridGeometry = { colW: COL_W, rowH: ROW_H, headerW: HEADER_W, headerH: HEADER_H, rows, cols };
  const totalW = HEADER_W + cols * COL_W;
  const totalH = HEADER_H + rows * ROW_H;
  const yLabelFor = (r: number) => (table.y ? axisLabel(table.y.values[r] ?? 0, yUnit) : (props.displayUnit ?? table.unit));
  const cellLabel = (r: number, c: number, v: number) => {
    const rowPart = table.y ? `linha ${axisLabel(table.y.values[r] ?? 0, yUnit)}` : "linha única";
    const warn = props.warned?.get(`${r}:${c}`);
    const warnPart = warn ? `, aviso ${[...new Set(warn.map((w) => w.code))].join(" ")}` : "";
    return `${rowPart}, coluna ${axisLabel(table.x.values[c] ?? 0, xUnit)}, valor ${formatNumber(display(v), decimals)}${warnPart}`;
  };

  return (
    <div
      ref={containerRef}
      role="grid"
      aria-label={label}
      aria-rowcount={rows + 1}
      aria-colcount={cols + 1}
      aria-multiselectable="true"
      aria-readonly={readOnly || undefined}
      aria-activedescendant={cellId(focus.row, focus.col)}
      tabIndex={0}
      onKeyDown={onKeyDown}
      onScroll={(e) => {
        const el = e.currentTarget;
        setView((v) => ({ ...v, top: el.scrollTop, left: el.scrollLeft }));
      }}
      data-testid="table-grid"
      className="relative h-[460px] max-h-[60vh] overflow-auto overscroll-contain rounded border border-zinc-700 bg-zinc-950 font-mono text-xs focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-400"
    >
      <div style={{ width: totalW, height: totalH, position: "relative" }}>
        <div role="row" aria-rowindex={1} style={{ position: "absolute", top: view.top, left: 0, height: HEADER_H, width: totalW, zIndex: 3 }}>
          <div
            role="columnheader"
            aria-colindex={1}
            onClick={() => onSelectionChange({ anchor: { row: 0, col: 0 }, focus: { row: rows - 1, col: cols - 1 }, mode: "all" })}
            title="Selecionar a tabela inteira"
            style={{ position: "absolute", left: view.left, width: HEADER_W, height: HEADER_H, zIndex: 4 }}
            className="flex cursor-pointer items-center justify-center border-b border-r border-zinc-700 bg-zinc-800 text-[10px] text-zinc-300"
          >
            {table.y ? `${yUnit} \\ ${xUnit}` : xUnit}
          </div>
          {colIdx.map((c) => (
            <div
              key={c}
              role="columnheader"
              aria-colindex={c + 2}
              data-col-header={c}
              onClick={(e) => onColHeader(c, e.shiftKey)}
              style={{ position: "absolute", left: HEADER_W + c * COL_W, width: COL_W, height: HEADER_H }}
              className={`flex cursor-pointer items-center justify-center border-b border-r border-zinc-700 bg-zinc-800 text-zinc-200 ${c >= rect.c0 && c <= rect.c1 ? "bg-zinc-700" : ""}`}
            >
              {axisLabel(table.x.values[c] ?? 0, "")}
            </div>
          ))}
        </div>
        {rowIdx.map((r) => (
          <div key={r} role="row" aria-rowindex={r + 2} style={{ position: "absolute", top: HEADER_H + r * ROW_H, left: 0, height: ROW_H, width: totalW }}>
            <div
              role="rowheader"
              aria-colindex={1}
              data-row-header={r}
              onClick={(e) => onRowHeader(r, e.shiftKey)}
              style={{ position: "absolute", left: view.left, width: HEADER_W, height: ROW_H, zIndex: 2 }}
              className={`flex cursor-pointer items-center justify-end border-b border-r border-zinc-700 bg-zinc-800 pr-2 text-zinc-200 ${r >= rect.r0 && r <= rect.r1 ? "bg-zinc-700" : ""}`}
            >
              {yLabelFor(r)}
            </div>
            {colIdx.map((c) => {
              const v = table.values[r]?.[c] ?? 0;
              const selected = inRect(rect, r, c);
              const isFocus = r === focus.row && c === focus.col;
              const colors = heatmap ? cellColors(v, range.min, range.max) : null;
              const warn = props.warned?.get(`${r}:${c}`);
              return (
                <div
                  key={c}
                  id={cellId(r, c)}
                  role="gridcell"
                  aria-colindex={c + 2}
                  aria-selected={selected}
                  aria-label={cellLabel(r, c, v)}
                  data-cell={`${r},${c}`}
                  onClick={() => {
                    if (focus.row === r && focus.col === c && !editing && !readOnly) {
                      startEdit();
                    }
                  }}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    onCellMouseDown(r, c, e.shiftKey);
                  }}
                  onMouseEnter={() => onCellEnter(r, c)}
                  onDoubleClick={() => startEdit()}
                  style={{
                    position: "absolute",
                    left: HEADER_W + c * COL_W,
                    width: COL_W,
                    height: ROW_H,
                    background: colors?.background,
                    color: colors?.color,
                    outline: isFocus ? "2px solid #f59e0b" : undefined,
                    outlineOffset: -2,
                    boxShadow: selected ? "inset 0 0 0 2px rgba(255,255,255,0.85)" : undefined,
                  }}
                  className={`flex select-none items-center justify-end border-b border-r border-zinc-800 pr-1.5 ${colors ? "" : selected ? "bg-zinc-700 text-white" : "text-zinc-100"}`}
                >
                  {warn && (
                    <span aria-hidden="true" data-warn={warn[0]!.code} className="absolute left-0.5 top-0.5 h-1.5 w-1.5 rounded-full bg-amber-400 ring-1 ring-black" />
                  )}
                  {formatNumber(display(v), decimals)}
                </div>
              );
            })}
          </div>
        ))}
        {props.overlay?.(geom)}
        {editing && (
          <input
            aria-label={`Editar ${cellLabel(editing.row, editing.col, table.values[editing.row]?.[editing.col] ?? 0)}`}
            autoFocus
            value={editing.text}
            onChange={(e) => setEditing({ ...editing, text: e.target.value })}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                commitEdit();
              } else if (e.key === "Escape") {
                e.preventDefault();
                setEditing(null);
                containerRef.current?.focus();
              }
              e.stopPropagation();
            }}
            onBlur={() => commitEdit(false)}
            style={{ position: "absolute", top: HEADER_H + editing.row * ROW_H, left: HEADER_W + editing.col * COL_W, width: COL_W, height: ROW_H, zIndex: 5 }}
            className="border-2 border-amber-400 bg-zinc-900 px-1 text-right font-mono text-xs text-white focus:outline-none"
          />
        )}
      </div>
    </div>
  );
}
