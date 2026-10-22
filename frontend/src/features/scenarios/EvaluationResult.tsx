/** Resultado da avaliação: selo, pontuação, tabela por critério e evidências (RF-12, RF-13). */
import { useEffect, useState } from "react";

import { downloadText, useScenariosApi } from "./api";
import { EvidenceLink } from "./EvidenceLink";
import { CRITERION_INFO, DEFECT_LABELS, type AttemptView, type Evaluation, type ScenarioView } from "./types";
import { ErrorBox, fmt, IndeterminateBar, PassBadge, SkeletonCards } from "./ui";

export interface EvaluationResultProps {
  attemptId: string;
  submission?: number;
  pollMs?: number;
}

const EVAL_ERROR_TEXT: Record<string, string> = {
  TRACE_UNAVAILABLE: "O log de uma puxada ficou ilegível; submeta de novo (a submissão não conta).",
  PROBE_FAILED: "A sonda de knock falhou; submeta de novo (a submissão não conta).",
  EVALUATION_INTERRUPTED: "A avaliação foi interrompida; submeta de novo.",
  DAMAGE_MODEL_UNAVAILABLE: "O modelo de dano não está disponível.",
};

export function EvaluationResult({ attemptId, submission, pollMs = 2000 }: EvaluationResultProps) {
  const api = useScenariosApi();
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [attempt, setAttempt] = useState<AttemptView | null>(null);
  const [scenario, setScenario] = useState<ScenarioView | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [exportError, setExportError] = useState<unknown>(null);
  const [exporting, setExporting] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let alive = true;
    api
      .getEvaluation(attemptId, submission)
      .then((ev) => {
        if (alive) setEvaluation(ev);
      })
      .catch((e: unknown) => {
        if (alive) setError(e);
      });
    return () => {
      alive = false;
    };
  }, [api, attemptId, submission, tick]);

  useEffect(() => {
    let alive = true;
    api
      .getAttempt(attemptId)
      .then(async (a) => {
        if (!alive) return;
        setAttempt(a);
        const s = await api.getScenario(a.scenario_id);
        if (alive) setScenario(s);
      })
      .catch(() => {
        /* opcional: sem tentativa os links para a bancada ficam escondidos */
      });
    return () => {
      alive = false;
    };
  }, [api, attemptId]);

  const pending = evaluation?.status === "pending";
  useEffect(() => {
    if (!pending) return;
    const timer = setTimeout(() => setTick((t) => t + 1), pollMs);
    return () => clearTimeout(timer);
  }, [pending, pollMs, evaluation]);

  async function exportPackage() {
    setExporting(true);
    setExportError(null);
    try {
      const file = await api.exportPackage({ kind: "attempt", attempt_id: attemptId, include_full_logs: false });
      downloadText(file.filename, file.content);
    } catch (e) {
      setExportError(e);
    } finally {
      setExporting(false);
    }
  }

  if (error !== null) return <ErrorBox error={error} onRetry={() => setTick((t) => t + 1)} />;
  if (evaluation === null) return <SkeletonCards count={1} />;

  const hasProbe = (scenario?.criteria.criteria ?? []).some((c) => c.kind === "min_knock_margin_deg");
  const sessionId = attempt?.session_id ?? null;

  if (evaluation.status === "pending") {
    return (
      <section aria-labelledby="result-title" className="space-y-3">
        <h1 id="result-title" className="text-xl font-semibold">
          Avaliação da submissão {evaluation.submission_index}
        </h1>
        <IndeterminateBar label={hasProbe ? "Sonda de knock em execução" : "Avaliação em curso"} />
      </section>
    );
  }

  return (
    <section aria-labelledby="result-title" className="space-y-4">
      <header className="flex flex-wrap items-center gap-3">
        <h1 id="result-title" className="text-xl font-semibold">
          Resultado da submissão {evaluation.submission_index}
        </h1>
        {evaluation.status === "completed" && <PassBadge passed={evaluation.passed} size="lg" />}
      </header>
      {evaluation.status === "error" && (
        <div role="alert" className="rounded border border-amber-600 bg-amber-950 p-3 text-sm">
          <p>{EVAL_ERROR_TEXT[evaluation.error_code ?? ""] ?? "A avaliação terminou com erro."}</p>
          <p className="font-mono text-xs">{evaluation.error_code}</p>
        </div>
      )}
      {evaluation.status === "completed" && (
        <p className="text-lg">
          Pontuação total: <strong>{fmt(evaluation.total_score, 1)}</strong> / 100
          <span className="block text-xs text-zinc-400">A aprovação depende só dos critérios obrigatórios.</span>
        </p>
      )}
      {evaluation.results.length > 0 && (
        <table className="w-full text-sm">
          <caption className="sr-only">Resultado por critério</caption>
          <thead>
            <tr className="text-left">
              <th scope="col">Critério</th>
              <th scope="col">Medido</th>
              <th scope="col">Limiar</th>
              <th scope="col">Estado</th>
              <th scope="col">Pontuação</th>
              <th scope="col">Evidências</th>
            </tr>
          </thead>
          <tbody>
            {evaluation.results.map((r) => {
              const info = CRITERION_INFO[r.kind];
              const digits = r.kind.startsWith("lambda") ? 3 : 1;
              const cmp = r.comparator === "ge" ? "≥ " : r.comparator === "le" ? "≤ " : "";
              return (
                <tr key={r.criterion_id} data-criterion={r.criterion_id} className="border-t border-zinc-800 align-top">
                  <td>
                    {info.label}
                    {r.mandatory ? "" : " (opcional)"}
                  </td>
                  <td>
                    {fmt(r.measured, digits)} {info.unit}
                  </td>
                  <td>{r.comparator === "bool" ? "sim" : `${cmp}${fmt(r.threshold, digits)} ${info.unit}`}</td>
                  <td>
                    <PassBadge passed={r.passed} size="sm" />
                  </td>
                  <td>
                    {fmt(r.score, 1)} (peso {fmt(r.weight, 1)})
                  </td>
                  <td>
                    {r.evidence.length === 0 ? (
                      <span className="text-zinc-400">—</span>
                    ) : (
                      <ul className="space-y-1">
                        {r.evidence.map((e, i) => (
                          <li key={`${e.run_id}-${i}`}>
                            <EvidenceLink evidence={e} sessionId={sessionId} />
                          </li>
                        ))}
                      </ul>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {evaluation.ignored_runs.length > 0 && (
        <p className="text-sm text-zinc-400">Puxadas ignoradas: {evaluation.ignored_runs.join(", ")}</p>
      )}
      {evaluation.hints_revealed.length > 0 && (
        <p className="text-sm text-zinc-400">Dicas reveladas: {evaluation.hints_revealed.join(", ")}</p>
      )}
      {evaluation.revealed_defect && (
        <p className="rounded border border-purple-700 bg-purple-950 p-2 text-sm">
          Defeito oculto revelado: <strong>{DEFECT_LABELS[evaluation.revealed_defect.kind]}</strong>
        </p>
      )}
      {evaluation.evaluation_sha256 && (
        <p className="break-all font-mono text-xs text-zinc-400">evaluation_sha256 {evaluation.evaluation_sha256}</p>
      )}
      {exportError !== null && <ErrorBox error={exportError} />}
      {evaluation.status === "completed" && (
        <button type="button" disabled={exporting} onClick={() => void exportPackage()} className="rounded bg-sky-700 px-3 py-1 disabled:opacity-50">
          Exportar pacote
        </button>
      )}
    </section>
  );
}
