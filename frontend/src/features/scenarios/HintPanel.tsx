/** Dicas progressivas da tentativa (training-scenarios RF-15). */
import { useState } from "react";

import { ApiProblem } from "@/lib/api";

import { useScenariosApi } from "./api";
import type { HintReveal } from "./types";
import { ErrorBox } from "./ui";

export interface HintPanelProps {
  attemptId: string;
  revealed: number[];
  total: number;
  /** Textos já revelados nesta página (o servidor só devolve o texto ao revelar). */
  initialTexts?: HintReveal[];
  disabled?: boolean;
  onRevealed?: (hint: HintReveal) => void;
}

export function HintPanel({ attemptId, revealed, total, initialTexts = [], disabled, onRevealed }: HintPanelProps) {
  const api = useScenariosApi();
  const [texts, setTexts] = useState<HintReveal[]>(initialTexts);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const remaining = Math.max(0, total - revealed.length);

  async function reveal() {
    setBusy(true);
    setNotice(null);
    setError(null);
    try {
      const hint = await api.revealHint(attemptId);
      setTexts((prev) => [...prev.filter((h) => h.order !== hint.order), hint]);
      onRevealed?.(hint);
    } catch (e) {
      if (e instanceof ApiProblem && e.code === "HINT_LOCKED") setNotice("A próxima dica ainda está bloqueada.");
      else if (e instanceof ApiProblem && e.code === "HINTS_EXHAUSTED") setNotice("Não há mais dicas.");
      else setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby={`hints-${attemptId}`} className="space-y-2">
      <h3 id={`hints-${attemptId}`} className="font-semibold">
        Dicas ({revealed.length}/{total})
      </h3>
      {texts.length > 0 && (
        <ol className="list-decimal space-y-1 pl-5 text-sm">
          {[...texts]
            .sort((a, b) => a.order - b.order)
            .map((h) => (
              <li key={h.order} value={h.order}>
                {h.text}
              </li>
            ))}
        </ol>
      )}
      {revealed.length > texts.length && (
        <p className="text-xs text-zinc-400">Dicas já reveladas: {revealed.join(", ")}.</p>
      )}
      {notice && (
        <p role="status" className="text-sm text-amber-300">
          {notice}
        </p>
      )}
      {error !== null && <ErrorBox error={error} />}
      {total > 0 && (
        <button
          type="button"
          disabled={busy || disabled || remaining === 0}
          onClick={() => void reveal()}
          className="rounded bg-zinc-700 px-2 py-1 text-sm disabled:opacity-50"
        >
          Revelar próxima dica
        </button>
      )}
    </section>
  );
}
