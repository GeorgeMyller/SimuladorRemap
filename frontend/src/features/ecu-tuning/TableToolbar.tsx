/**
 * Barra de operações da tabela (tuning RF-05 a RF-09, RF-20, RF-22): definir (`=`), somar (`+`),
 * subtrair (`−`), ajuste percentual (`*`), interpolar linha/coluna/bloco, suavizar, copiar/colar
 * TSV, desfazer/refazer, heatmap, λ↔AFR e vista 3D. As operações degeneradas ficam desativadas
 * com a dica "selecione ≥ 2 células numa linha/coluna" (EC-07).
 * Feature 002: grupo rápido Quick Tune (`Q`), interpolar H (`H`) / V (`V`) e suavizar bloco (`B`).
 */
import { forwardRef, useImperativeHandle, useRef, useState } from "react";

import { MSG } from "./messages";
import type { Rect } from "./model";
import { canInterpolateBlock } from "./ops/interpolate";
import { parseCellNumber } from "./ops/tsv";
import type { TableOperation } from "./workspaceStore";

export type ValueOp = "set" | "add" | "sub" | "scale";

const OP_LABEL: Record<ValueOp, string> = {
  set: "= Definir",
  add: "+ Somar",
  sub: "− Subtrair",
  scale: "% Ajustar",
};

export interface TableToolbarHandle {
  /** Foca o campo de valor com a operação escolhida (atalhos `=`, `+`, `−`, `*`). */
  focusValue: (op: ValueOp) => void;
}

export interface TableToolbarProps {
  rect: Rect;
  disabled: boolean;
  canUndo: boolean;
  canRedo: boolean;
  heatmap: boolean;
  lambdaTable: boolean;
  lambdaDisplay: "lambda" | "afr";
  afrAvailable: boolean;
  is3d: boolean;
  show3d: boolean;
  onOperation: (op: TableOperation) => void;
  /** Quick Tune (`Q`): a store recusa com aviso fora da tabela VE. */
  onQuickTune?: () => void;
  /** Otimização assistida por IA (LAYA.ai). */
  onAiTune?: (level?: "safe" | "balanced" | "race") => void;
  aiTuning?: boolean;
  aiAggressiveness?: "safe" | "balanced" | "race";
  onSetAiAggressiveness?: (level: "safe" | "balanced" | "race") => void;
  onCopy: () => void;
  onPaste: () => void;
  onUndo: () => void;
  onRedo: () => void;
  onToggleHeatmap: () => void;
  onToggleLambda: () => void;
  onToggle3d: () => void;
  /** Devolve o foco à grade depois de aplicar. */
  onDone?: () => void;
}

const btn =
  "rounded border border-zinc-600 px-2 py-1 text-xs text-zinc-100 hover:bg-zinc-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-400 disabled:cursor-not-allowed disabled:opacity-50";

export const TableToolbar = forwardRef<TableToolbarHandle, TableToolbarProps>(function TableToolbar(props, ref) {
  const [op, setOp] = useState<ValueOp>("add");
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useImperativeHandle(ref, () => ({
    focusValue: (next: ValueOp) => {
      setOp(next);
      setError(null);
      inputRef.current?.focus();
      inputRef.current?.select();
    },
  }));

  const apply = (which: ValueOp = op) => {
    const n = parseCellNumber(text);
    if (n === null) {
      setError("Digite um número (vírgula ou ponto decimal).");
      inputRef.current?.focus();
      return;
    }
    setError(null);
    if (which === "set") props.onOperation({ op: "set", value: n });
    else if (which === "add") props.onOperation({ op: "add", value: n });
    else if (which === "sub") props.onOperation({ op: "add", value: -n });
    else props.onOperation({ op: "scale", value: n });
    props.onDone?.();
  };

  const { rect } = props;
  const hasRow = rect.c1 > rect.c0;
  const hasCol = rect.r1 > rect.r0;
  const blockOk = canInterpolateBlock(rect);

  const nudgeStep = props.lambdaTable ? (props.lambdaDisplay === "afr" ? 0.1 : 0.01) : 1;

  return (
    <div role="toolbar" aria-label="Operações da tabela" className="flex flex-col gap-1.5 rounded border border-zinc-700 bg-zinc-900 p-2">
      {/* Linha 1: Operações principais e atalhos rápidos de toque */}
      <div className="flex flex-wrap items-center gap-1.5 sm:gap-2">
        <label className="flex items-center gap-1 text-xs text-zinc-300">
          <span>Operação</span>
          <select
            value={op}
            onChange={(e) => setOp(e.target.value as ValueOp)}
            disabled={props.disabled}
            className="rounded border border-zinc-600 bg-zinc-950 px-1 py-1 text-xs text-zinc-100"
          >
            {(Object.keys(OP_LABEL) as ValueOp[]).map((k) => (
              <option key={k} value={k}>
                {OP_LABEL[k]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1 text-xs text-zinc-300">
          <span>Valor{op === "scale" ? " (%)" : ""}</span>
          <input
            ref={inputRef}
            value={text}
            inputMode="decimal"
            disabled={props.disabled}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? "toolbar-error" : undefined}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                apply();
              } else if (e.key === "Escape") {
                e.preventDefault();
                props.onDone?.();
              }
              e.stopPropagation();
            }}
            className="w-16 sm:w-20 rounded border border-zinc-600 bg-zinc-950 px-1 py-1 text-right font-mono text-xs text-zinc-100"
          />
        </label>
        <button type="button" className={`${btn} font-semibold bg-amber-500/20 border-amber-500/40 text-amber-200 hover:bg-amber-500/30`} disabled={props.disabled} onClick={() => apply()}>
          Aplicar
        </button>
        {/* Nudge rápido para toque/mobile */}
        <div className="flex items-center gap-1">
          <button
            type="button"
            className={`${btn} font-mono font-bold text-amber-400 bg-zinc-800 hover:bg-zinc-700`}
            disabled={props.disabled}
            title={`Ajuste rápido: -${nudgeStep}`}
            aria-label={`Subtrair ${nudgeStep}`}
            onClick={() => {
              props.onOperation({ op: "add", value: -nudgeStep });
              props.onDone?.();
            }}
          >
            -{nudgeStep}
          </button>
          <button
            type="button"
            className={`${btn} font-mono font-bold text-emerald-400 bg-zinc-800 hover:bg-zinc-700`}
            disabled={props.disabled}
            title={`Ajuste rápido: +${nudgeStep}`}
            aria-label={`Somar ${nudgeStep}`}
            onClick={() => {
              props.onOperation({ op: "add", value: nudgeStep });
              props.onDone?.();
            }}
          >
            +{nudgeStep}
          </button>
        </div>
        <div className="ml-auto flex items-center gap-1">
          <button type="button" className={btn} disabled={!props.canUndo} onClick={props.onUndo} title="Desfazer (Ctrl/Cmd+Z)">
            Desfazer
          </button>
          <button type="button" className={btn} disabled={!props.canRedo} onClick={props.onRedo} title="Refazer (Ctrl/Cmd+Shift+Z)">
            Refazer
          </button>
        </div>
      </div>

      {/* Linha 2: Ferramentas avançadas em barra rolável horizontal para telas mobile */}
      <div className="flex items-center gap-1.5 overflow-x-auto pb-1 text-xs no-scrollbar">
        <button type="button" className={`${btn} shrink-0`} disabled={props.disabled || !hasRow} title={hasRow ? "Interpolar linha (I)" : MSG.interpHint} onClick={() => props.onOperation({ op: "interp_row" })}>
          Interpolar linha
        </button>
        <button type="button" className={`${btn} shrink-0`} disabled={props.disabled || !hasCol} title={hasCol ? "Interpolar coluna (I)" : MSG.interpHint} onClick={() => props.onOperation({ op: "interp_col" })}>
          Interpolar coluna
        </button>
        <button type="button" className={`${btn} shrink-0`} disabled={props.disabled || !blockOk} title={blockOk ? "Interpolar bloco (Shift+I)" : MSG.interpHint} onClick={() => props.onOperation({ op: "interp_block" })}>
          Interpolar bloco
        </button>
        <button type="button" className={`${btn} shrink-0`} disabled={props.disabled} title="Suavizar (S)" onClick={() => props.onOperation({ op: "smooth" })}>
          Suavizar
        </button>
        <button type="button" className={`${btn} shrink-0`} disabled={props.disabled || !hasRow} aria-keyshortcuts="H" title={hasRow ? "Interpolar horizontal pelo eixo X (H)" : MSG.interpHint} onClick={() => props.onOperation({ op: "interp_h" })}>
          Interpolar H
        </button>
        <button type="button" className={`${btn} shrink-0`} disabled={props.disabled || !hasCol} aria-keyshortcuts="V" title={hasCol ? "Interpolar vertical pelo eixo Y (V)" : MSG.interpHint} onClick={() => props.onOperation({ op: "interp_v" })}>
          Interpolar V
        </button>
        <button type="button" className={`${btn} shrink-0`} disabled={props.disabled} aria-keyshortcuts="B" title="Suavizar bloco 3×3 (B)" onClick={() => props.onOperation({ op: "block_smooth" })}>
          Suavizar bloco
        </button>
        <span className="mx-1 h-5 w-px shrink-0 bg-zinc-700" aria-hidden="true" />
        {props.onQuickTune && (
          <button type="button" className={`${btn} shrink-0`} disabled={props.disabled} aria-keyshortcuts="Q" title="Quick Tune: VE × λ medido / λ alvo, ±25 % (Q)" onClick={props.onQuickTune}>
            Quick Tune
          </button>
        )}
        {props.onAiTune && (
          <div className="flex shrink-0 items-center gap-1 rounded border border-purple-500/40 bg-purple-950/20 px-1 py-0.5">
            <label className="flex items-center gap-1 text-[11px] font-medium text-purple-300">
              <span>Modo:</span>
              <select
                aria-label="Modo de agressividade da IA"
                value={props.aiAggressiveness ?? "balanced"}
                disabled={props.disabled || props.aiTuning}
                onChange={(e) => props.onSetAiAggressiveness?.(e.target.value as "safe" | "balanced" | "race")}
                className="rounded border border-purple-500/50 bg-zinc-950 px-1 py-0.5 text-xs text-purple-200 hover:border-purple-400 focus-visible:outline-purple-400"
              >
                <option value="safe">🛡️ Safe</option>
                <option value="balanced">⚖️ Balanced</option>
                <option value="race">⚡ Race</option>
              </select>
            </label>
            <button
              type="button"
              className={`${btn} border-purple-500/60 bg-purple-950/40 font-semibold text-purple-200 hover:bg-purple-900/60 focus-visible:outline-purple-400`}
              disabled={props.disabled || props.aiTuning}
              title={`Tunar com IA (${props.aiAggressiveness ?? "balanced"}): otimiza tabela com inferência neural local no Mac`}
              onClick={() => props.onAiTune?.(props.aiAggressiveness ?? "balanced")}
            >
              {props.aiTuning ? "Tunando..." : "🤖 Tunar com IA"}
            </button>
          </div>
        )}
        <span className="mx-1 h-5 w-px shrink-0 bg-zinc-700" aria-hidden="true" />
        <button type="button" className={`${btn} shrink-0`} onClick={props.onCopy} title="Copiar TSV (Ctrl/Cmd+C)">
          Copiar
        </button>
        <button type="button" className={`${btn} shrink-0`} disabled={props.disabled} onClick={props.onPaste} title="Colar TSV (Ctrl/Cmd+V)">
          Colar
        </button>
        <span className="mx-1 h-5 w-px shrink-0 bg-zinc-700" aria-hidden="true" />
        <button type="button" className={`${btn} shrink-0`} aria-pressed={props.heatmap} onClick={props.onToggleHeatmap}>
          Heatmap
        </button>
        {props.lambdaTable && (
          <button type="button" className={`${btn} shrink-0`} aria-pressed={props.lambdaDisplay === "afr"} disabled={!props.afrAvailable} onClick={props.onToggleLambda} title="Exibir lambda em AFR do combustível ativo">
            {props.lambdaDisplay === "afr" ? "Exibir em λ" : "Exibir em AFR"}
          </button>
        )}
        {props.is3d && (
          <button type="button" className={`${btn} shrink-0`} aria-pressed={props.show3d} onClick={props.onToggle3d} title="Vista 3D (F3)">
            Vista 3D
          </button>
        )}
      </div>
      {error && (
        <p id="toolbar-error" role="alert" className="w-full text-xs text-red-300">
          {error}
        </p>
      )}
    </div>
  );
});
