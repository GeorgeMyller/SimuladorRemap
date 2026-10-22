/**
 * Painel de avisos didáticos W-01 a W-06 (tuning RF-19): não bloqueiam a gravação; cada aviso
 * mostra o ícone âmbar, a explicação curta e o link para a ajuda. Sem `mbt_reference` o W-01 fica
 * inativo com "MBT estimado indisponível".
 */
import { MSG, WARNING_TEXTS } from "./messages";
import type { TuningWarning } from "./warnings";

export interface TuningWarningsProps {
  warnings: readonly TuningWarning[];
  mbtAvailable: boolean;
  tableLabel?: (tableId: string) => string;
  onFocusCell?: (tableId: string, row: number, col: number) => void;
  max?: number;
}

export function WarningIcon() {
  return (
    <svg role="img" aria-label="aviso" viewBox="0 0 16 16" width="14" height="14" className="inline shrink-0 fill-amber-400">
      <path d="M8 1 15 14H1L8 1Zm-.8 5v4h1.6V6H7.2Zm0 5.2v1.6h1.6v-1.6H7.2Z" />
    </svg>
  );
}

export function TuningWarnings({ warnings, mbtAvailable, tableLabel = (id) => id, onFocusCell, max = 40 }: TuningWarningsProps) {
  const shown = warnings.slice(0, max);
  const codes = [...new Set(warnings.map((w) => w.code))].sort();
  return (
    <section aria-labelledby="warnings-title" className="rounded border border-zinc-700 bg-zinc-900 p-2 text-xs">
      <h2 id="warnings-title" className="mb-1 text-xs font-semibold uppercase tracking-wide text-zinc-300">
        Avisos ({warnings.length})
      </h2>
      {!mbtAvailable && <p className="mb-1 text-zinc-400">W-01: {MSG.mbtUnavailable}</p>}
      {warnings.length === 0 ? (
        <p className="text-zinc-400">Nenhum aviso.</p>
      ) : (
        <ul className="flex max-h-64 flex-col gap-1 overflow-auto" aria-live="polite">
          {shown.map((w, i) => (
            <li key={i} data-warning={w.code} className="flex gap-1">
              <WarningIcon />
              <span>
                <strong className="text-amber-300">{w.code}</strong> {WARNING_TEXTS[w.code].title}
                {w.tableId !== undefined && w.row !== undefined && w.col !== undefined && (
                  <>
                    {" "}
                    em{" "}
                    {onFocusCell ? (
                      <button type="button" className="underline hover:text-white" onClick={() => onFocusCell(w.tableId!, w.row!, w.col!)}>
                        {tableLabel(w.tableId)} ({w.row}, {w.col})
                      </button>
                    ) : (
                      `${tableLabel(w.tableId)} (${w.row}, ${w.col})`
                    )}
                  </>
                )}
                {w.field && <span className="text-zinc-400"> ({w.field})</span>}: <span className="text-zinc-300">{w.detail}</span>{" "}
                <a href={WARNING_TEXTS[w.code].helpHref} className="text-sky-300 underline">
                  ajuda
                </a>
              </span>
            </li>
          ))}
          {warnings.length > shown.length && <li className="text-zinc-400">+ {warnings.length - shown.length} avisos</li>}
        </ul>
      )}
      {codes.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer text-zinc-300">Ajuda dos avisos</summary>
          <dl>
            {codes.map((c) => (
              <div key={c} id={WARNING_TEXTS[c].helpHref.slice(1)} className="mt-1">
                <dt className="font-semibold text-amber-300">
                  {c} · {WARNING_TEXTS[c].title}
                </dt>
                <dd className="text-zinc-300">
                  {WARNING_TEXTS[c].message} {WARNING_TEXTS[c].help}
                </dd>
              </div>
            ))}
          </dl>
        </details>
      )}
    </section>
  );
}
