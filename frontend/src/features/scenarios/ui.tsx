/** Peças visuais partilhadas pelas telas dos cenários (estado sempre com texto e ícone). */
import type { ReactNode } from "react";

import { problemMessage } from "./api";

export function PassBadge({ passed, size = "md" }: { passed: boolean | null; size?: "sm" | "md" | "lg" }) {
  const pad = size === "lg" ? "px-3 py-1.5 text-base" : size === "sm" ? "px-1.5 py-0.5 text-xs" : "px-2 py-1 text-sm";
  if (passed === null) {
    return (
      <span className={`inline-flex items-center gap-1 rounded bg-zinc-700 font-medium text-zinc-100 ${pad}`}>
        <span aria-hidden="true">–</span> Sem avaliação
      </span>
    );
  }
  return passed ? (
    <span className={`inline-flex items-center gap-1 rounded bg-emerald-700 font-medium text-white ${pad}`}>
      <span aria-hidden="true">✓</span> Aprovado
    </span>
  ) : (
    <span className={`inline-flex items-center gap-1 rounded bg-red-700 font-medium text-white ${pad}`}>
      <span aria-hidden="true">✗</span> Reprovado
    </span>
  );
}

export function CriterionStatus({ passed }: { passed: boolean }) {
  return passed ? (
    <span className="inline-flex items-center gap-1 text-emerald-300">
      <span aria-hidden="true">✓</span> cumpre
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 text-red-300">
      <span aria-hidden="true">✗</span> não cumpre
    </span>
  );
}

export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { code, text } = problemMessage(error);
  return (
    <div role="alert" className="rounded border border-red-700 bg-red-950 p-3 text-sm text-red-100">
      <p>{text}</p>
      <p className="mt-1 font-mono text-xs">{code}</p>
      {onRetry && (
        <button type="button" className="mt-2 rounded bg-red-800 px-2 py-1" onClick={onRetry}>
          Tentar de novo
        </button>
      )}
    </div>
  );
}

export function SkeletonCards({ count = 3 }: { count?: number }) {
  return (
    <ul aria-busy="true" aria-label="A carregar" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: count }, (_, i) => (
        <li key={i} className="h-28 animate-pulse rounded bg-zinc-800" />
      ))}
    </ul>
  );
}

export function IndeterminateBar({ label }: { label: string }) {
  return (
    <div>
      <div role="progressbar" aria-label={label} className="h-2 w-full overflow-hidden rounded bg-zinc-800">
        <div className="h-2 w-1/3 animate-pulse rounded bg-sky-500" />
      </div>
      <p className="mt-1 text-sm text-zinc-300">{label}</p>
    </div>
  );
}

export function Section({ title, children, id }: { title: string; children: ReactNode; id: string }) {
  return (
    <section aria-labelledby={id} className="rounded border border-zinc-800 p-3">
      <h2 id={id} className="mb-2 text-lg font-semibold">
        {title}
      </h2>
      {children}
    </section>
  );
}

/** Formata número em pt-BR com `digits` casas. */
export function fmt(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return value.toLocaleString("pt-BR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
