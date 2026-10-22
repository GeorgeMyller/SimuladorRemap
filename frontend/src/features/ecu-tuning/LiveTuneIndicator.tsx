/**
 * Indicador de live-tune e aplicação à sessão (tuning RF-17, RF-18, EC-03, EC-12; D-15).
 * Durante a puxada lista as tabelas editáveis ao vivo (`live_tunable_table_ids`) e as bloqueadas
 * (cadeado e "bloqueada durante a puxada"). `ApplyToSessionButton` aplica a calibração gravada
 * entre puxadas com confirmação; durante a puxada só aceita alterações em tabelas live-tunable.
 */
import { useState } from "react";

import { Dialog } from "../dyno-cockpit/Dialog";
import { MSG } from "./messages";
import { LockIcon } from "./ProfileNavigator";

export interface LiveTableInfo {
  tableId: string;
  label: string;
  live: boolean;
}

export interface LiveTuneIndicatorProps {
  runActive: boolean;
  telemetryFresh: boolean;
  tables: LiveTableInfo[];
  activeTableId: string | null;
}

export function LiveTuneIndicator({ runActive, telemetryFresh, tables, activeTableId }: LiveTuneIndicatorProps) {
  const live = tables.filter((t) => t.live);
  const locked = tables.filter((t) => !t.live);
  const active = tables.find((t) => t.tableId === activeTableId);
  return (
    <section aria-labelledby="live-tune-title" className="rounded border border-zinc-700 bg-zinc-900 p-2 text-xs">
      <h2 id="live-tune-title" className="mb-1 text-xs font-semibold uppercase tracking-wide text-zinc-300">
        Live-tune
      </h2>
      <p role="status" className="mb-1 text-zinc-200">
        {!telemetryFresh ? MSG.noBenchData : runActive ? "Puxada em curso: só tabelas live-tunable aceitam edição." : "Bancada parada: todas as tabelas aceitam edição."}
      </p>
      {active && runActive && !active.live && (
        <p className="mb-1 flex items-center gap-1 font-semibold text-amber-300" data-testid="active-locked">
          <LockIcon />
          {active.label}: {MSG.lockedDuringRun}
        </p>
      )}
      {runActive && (
        <div className="grid grid-cols-2 gap-2">
          <div>
            <h3 className="font-semibold text-emerald-300">Editáveis ao vivo</h3>
            <ul>
              {live.map((t) => (
                <li key={t.tableId}>{t.label}</li>
              ))}
              {live.length === 0 && <li className="text-zinc-400">nenhuma</li>}
            </ul>
          </div>
          <div>
            <h3 className="font-semibold text-amber-300">Bloqueadas</h3>
            <ul>
              {locked.map((t) => (
                <li key={t.tableId} className="flex items-center gap-1">
                  <LockIcon />
                  <span>
                    {t.label} <span className="sr-only">{MSG.lockedDuringRun}</span>
                  </span>
                </li>
              ))}
              {locked.length === 0 && <li className="text-zinc-400">nenhuma</li>}
            </ul>
          </div>
        </div>
      )}
    </section>
  );
}

export interface ApplyToSessionButtonProps {
  version: number | null;
  runActive: boolean;
  /** Só tabelas live-tunable mudaram desde a última aplicação. */
  onlyLiveChanges: boolean;
  disabled: boolean;
  applying: boolean;
  onApply: () => void;
}

export function ApplyToSessionButton({ version, runActive, onlyLiveChanges, disabled, applying, onApply }: ApplyToSessionButtonProps) {
  const [confirm, setConfirm] = useState(false);
  const blockedByRun = runActive && !onlyLiveChanges;
  return (
    <>
      <button
        type="button"
        disabled={disabled || blockedByRun || applying}
        title={blockedByRun ? "Durante a puxada só alterações em tabelas live-tunable podem ser aplicadas." : "Aplicar à sessão (Ctrl/Cmd+Enter)"}
        onClick={() => (runActive ? onApply() : setConfirm(true))}
        data-apply-button
        className="rounded bg-emerald-700 px-3 py-1 text-xs font-semibold text-white hover:bg-emerald-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-400 disabled:cursor-not-allowed disabled:bg-zinc-700 disabled:text-zinc-400"
      >
        {applying ? "A aplicar…" : "Aplicar à sessão"}
      </button>
      {confirm && (
        <Dialog titleId="apply-confirm-title" title="Aplicar à sessão" onClose={() => setConfirm(false)}>
          <p className="mb-3 text-sm">
            Aplicar a revisão {version ?? "atual"} à sessão? A troca acontece entre puxadas, numa fronteira de tick.
          </p>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setConfirm(false)} className="rounded border border-zinc-500 px-3 py-1 text-sm hover:bg-zinc-800">
              Cancelar
            </button>
            <button
              type="button"
              onClick={() => {
                setConfirm(false);
                onApply();
              }}
              className="rounded bg-emerald-700 px-3 py-1 text-sm font-semibold text-white hover:bg-emerald-600"
            >
              Confirmar
            </button>
          </div>
        </Dialog>
      )}
    </>
  );
}
