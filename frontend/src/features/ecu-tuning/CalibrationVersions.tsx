/**
 * Histórico de versões da calibração (tuning RF-16; Fluxo Alternativo C; D-15; rest-api E-17/E-18).
 * Lista as versões (`include=versions`), compara duas versões célula a célula (`VersionDiff`) e
 * reverte para uma versão anterior criando a versão N+1 (`PUT {base_version, revert_to_version}`).
 */
import { useState } from "react";

import { formatNumber } from "@/lib/units";

import { diffCalibrations, type CalibrationDiff } from "./ops/diffCalibrations";
import type { Calibration, CalibrationVersionInfo } from "./types";

export interface CalibrationVersionsProps {
  versions: CalibrationVersionInfo[];
  currentVersion: number;
  fetchVersion: (version: number) => Promise<Calibration>;
  onRevert: (version: number) => Promise<unknown>;
  onApply?: () => void;
  disabled?: boolean;
  tableLabel?: (tableId: string) => string;
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("pt-BR");
}

export function CalibrationVersions({ versions, currentVersion, fetchVersion, onRevert, onApply, disabled = false, tableLabel = (id) => id }: CalibrationVersionsProps) {
  const sorted = [...versions].sort((a, b) => b.version - a.version);
  const [a, setA] = useState<number | null>(sorted[1]?.version ?? null);
  const [b, setB] = useState<number | null>(sorted[0]?.version ?? null);
  const [diff, setDiff] = useState<{ a: number; b: number; diff: CalibrationDiff } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reverted, setReverted] = useState<number | null>(null);

  const compare = async () => {
    if (a === null || b === null) return;
    setBusy(true);
    setError(null);
    try {
      const [ca, cb] = await Promise.all([fetchVersion(a), fetchVersion(b)]);
      setDiff({ a, b, diff: diffCalibrations(ca, cb) });
    } catch {
      setError("Não foi possível carregar as versões.");
    } finally {
      setBusy(false);
    }
  };

  const revert = async (version: number) => {
    setBusy(true);
    setError(null);
    try {
      await onRevert(version);
      setReverted(version);
    } catch {
      setError("Não foi possível reverter.");
    } finally {
      setBusy(false);
    }
  };

  if (sorted.length === 0) return <p className="p-2 text-sm text-zinc-300">Sem versões anteriores.</p>;

  return (
    <section aria-labelledby="versions-title" className="flex flex-col gap-2 rounded border border-zinc-700 bg-zinc-900 p-3 text-xs">
      <h2 id="versions-title" className="text-base font-semibold text-zinc-100">
        Versões da calibração
      </h2>
      <table className="w-full">
        <caption className="sr-only">Lista de versões</caption>
        <thead className="text-left text-zinc-300">
          <tr>
            <th scope="col">Versão</th>
            <th scope="col">Data</th>
            <th scope="col">Origem</th>
            <th scope="col">Resumo</th>
            <th scope="col">A</th>
            <th scope="col">B</th>
            <th scope="col">
              <span className="sr-only">Ações</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((v) => (
            <tr key={v.version} className="border-t border-zinc-700" aria-current={v.version === currentVersion ? "true" : undefined}>
              <td className="py-1 font-mono">
                {v.version}
                {v.version === currentVersion && <span className="ml-1 text-emerald-300">(atual)</span>}
              </td>
              <td>{fmtDate(v.created_at)}</td>
              <td>
                {v.source}
                {v.author_nickname ? ` · ${v.author_nickname}` : ""}
              </td>
              <td>{v.change_summary || "—"}</td>
              <td>
                <input type="radio" name="version-a" aria-label={`Versão ${v.version} como A`} checked={a === v.version} onChange={() => setA(v.version)} />
              </td>
              <td>
                <input type="radio" name="version-b" aria-label={`Versão ${v.version} como B`} checked={b === v.version} onChange={() => setB(v.version)} />
              </td>
              <td>
                {v.version !== currentVersion && (
                  <button type="button" disabled={disabled || busy} onClick={() => void revert(v.version)} className="rounded border border-zinc-600 px-2 py-0.5 hover:bg-zinc-800 disabled:opacity-50">
                    Reverter para {v.version}
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="flex items-center gap-2">
        <button type="button" disabled={busy || a === null || b === null || a === b} onClick={() => void compare()} className="rounded bg-sky-700 px-3 py-1 font-semibold text-white hover:bg-sky-600 disabled:opacity-50">
          Comparar A × B
        </button>
        {busy && <span role="status">A carregar…</span>}
        {error && (
          <span role="alert" className="text-red-300">
            {error}
          </span>
        )}
      </div>
      {reverted !== null && (
        <p role="status" className="text-emerald-300">
          Revertido para a versão {reverted}: nova versão {currentVersion} criada.{" "}
          {onApply && (
            <button type="button" onClick={onApply} className="ml-1 rounded border border-emerald-500 px-2 py-0.5 text-emerald-200 hover:bg-emerald-900">
              Aplicar à sessão
            </button>
          )}
        </p>
      )}
      {diff && <VersionDiff a={diff.a} b={diff.b} diff={diff.diff} tableLabel={tableLabel} />}
    </section>
  );
}

export function VersionDiff({ a, b, diff, tableLabel = (id) => id }: { a: number; b: number; diff: CalibrationDiff; tableLabel?: (tableId: string) => string }) {
  const byTable = new Map<string, CalibrationDiff["tables"]>();
  for (const c of diff.tables) byTable.set(c.tableId, [...(byTable.get(c.tableId) ?? []), c]);
  return (
    <div aria-label={`Diferenças entre a versão ${a} e a versão ${b}`} role="region" className="rounded border border-zinc-700 p-2">
      <p className="mb-1 font-semibold text-zinc-100" data-testid="diff-summary">
        {diff.changedCells} {diff.changedCells === 1 ? "célula alterada" : "células alteradas"}
        {diff.strategies.length > 0 && ` · ${diff.strategies.length} ${diff.strategies.length === 1 ? "parâmetro alterado" : "parâmetros alterados"}`}
      </p>
      {[...byTable.entries()].map(([tableId, cells]) => (
        <div key={tableId} className="mb-2">
          <h3 className="font-semibold text-zinc-200">{tableLabel(tableId)}</h3>
          <ul className="grid grid-cols-2 gap-x-4 font-mono md:grid-cols-3">
            {cells.map((c) => (
              <li key={`${c.row}-${c.col}`} data-diff-cell={`${tableId}:${c.row},${c.col}`} className="rounded bg-amber-900/40 px-1">
                ({c.row}, {c.col}): {formatNumber(c.a, 2)} → {formatNumber(c.b, 2)}
              </li>
            ))}
          </ul>
        </div>
      ))}
      {diff.strategies.length > 0 && (
        <ul className="font-mono">
          {diff.strategies.map((s) => (
            <li key={s.path} data-diff-path={s.path}>
              {s.path}: {JSON.stringify(s.a)} → {JSON.stringify(s.b)}
            </li>
          ))}
        </ul>
      )}
      {diff.structural.map((s) => (
        <p key={s.path} className="text-amber-300">
          {s.path}: estrutura alterada
        </p>
      ))}
    </div>
  );
}
