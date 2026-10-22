/**
 * Painel de progresso da tentativa (320 px): estado, links para a bancada e a ECU,
 * checklist por critério com valor provisório, puxadas classificadas, dicas e submissão
 * (training-scenarios RF-09, RF-10, RF-15, RF-24, RF-27).
 */
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { dynoPath, ecuPath } from "@/app/routes";

import { useScenariosApi } from "./api";
import { HintPanel } from "./HintPanel";
import { criterionThreshold } from "./ScenarioBriefing";
import {
  ATTEMPT_STATE_LABELS,
  CRITERION_INFO,
  DEFECT_KINDS,
  DEFECT_LABELS,
  invalidReasonLabel,
  type DefectKind,
  type ScenarioView,
} from "./types";
import { CriterionStatus, ErrorBox, fmt, IndeterminateBar, SkeletonCards } from "./ui";
import { TERMINAL_STATES, useAttempt } from "./useAttempt";

export interface AttemptProgressPanelProps {
  attemptId: string;
  /** Painel lateral sobre a cockpit/ECU (largura fixa de 320 px). */
  sidebar?: boolean;
  pollMs?: number;
  /** Muda quando uma puxada termina na bancada: recarrega a tentativa (puxadas e critérios). */
  refreshKey?: string | null;
}

export function AttemptProgressPanel({ attemptId, sidebar = false, pollMs, refreshKey = null }: AttemptProgressPanelProps) {
  const api = useScenariosApi();
  const { attempt, setAttempt, error, refresh } = useAttempt(attemptId, pollMs);
  const seenKey = useRef(refreshKey);
  useEffect(() => {
    if (refreshKey === seenKey.current) return;
    seenKey.current = refreshKey;
    refresh();
  }, [refreshKey, refresh]);
  const [scenario, setScenario] = useState<ScenarioView | null>(null);
  const [declared, setDeclared] = useState<DefectKind | "none" | "">("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<unknown>(null);
  const [submitted, setSubmitted] = useState<number | null>(null);
  const scenarioId = attempt?.scenario_id;

  useEffect(() => {
    if (!scenarioId) return;
    let alive = true;
    api
      .getScenario(scenarioId)
      .then((s) => {
        if (alive) setScenario(s);
      })
      .catch(() => {
        /* o painel funciona sem o briefing (só perde rótulos e o seletor de defeito) */
      });
    return () => {
      alive = false;
    };
  }, [api, scenarioId]);

  async function submit() {
    if (!attempt) return;
    setBusy(true);
    setActionError(null);
    try {
      // Submete a calibração da última puxada válida (a que o aluno testou: muda com swap, Base Setup
      // ou "Aplicar"); a `calibration_id` da tentativa é só o clone inicial.
      const lastValid = attempt.runs.findLast((r) => r.valid);
      const current = lastValid ? await api.getRunCalibrationId(lastValid.run_id).catch(() => null) : null;
      const accepted = await api.submit(attempt.attempt_id, {
        calibration_id: current ?? attempt.calibration_id,
        ...(declared ? { declared_defect: declared } : {}),
      });
      setSubmitted(accepted.submission_index);
      refresh();
    } catch (e) {
      setActionError(e);
    } finally {
      setBusy(false);
    }
  }

  async function abandon() {
    if (!attempt) return;
    setBusy(true);
    setActionError(null);
    try {
      setAttempt(await api.abandon(attempt.attempt_id));
    } catch (e) {
      setActionError(e);
    } finally {
      setBusy(false);
    }
  }

  const width = sidebar ? "w-[320px] shrink-0" : "max-w-xl";
  if (error !== null && attempt === null) return <ErrorBox error={error} onRetry={refresh} />;
  if (attempt === null) return <SkeletonCards count={1} />;

  const inProgress = attempt.state === "in_progress";
  const terminal = TERMINAL_STATES.has(attempt.state);
  const thresholds = new Map((scenario?.criteria.criteria ?? []).map((c) => [c.criterion_id, criterionThreshold(c)]));
  const hasResult = attempt.submissions > 0 && attempt.state !== "evaluating";

  return (
    <aside aria-labelledby={`attempt-${attempt.attempt_id}`} className={`${width} space-y-3 rounded border border-zinc-700 bg-zinc-900 p-3`}>
      <header>
        <h2 id={`attempt-${attempt.attempt_id}`} className="font-semibold">
          {attempt.scenario_title || attempt.scenario_id}
        </h2>
        <p className="text-sm" role="status">
          Estado: <strong>{ATTEMPT_STATE_LABELS[attempt.state]}</strong>
        </p>
        {attempt.failure_code && <p className="font-mono text-xs text-red-300">{attempt.failure_code}</p>}
        <p className="text-xs text-zinc-400">
          Submissões: {attempt.submissions}/{attempt.max_submissions} · restaurações do motor: {attempt.engine_restores}
        </p>
      </header>

      {attempt.state === "preparing" && <IndeterminateBar label="Puxada base em execução" />}
      {attempt.state === "evaluating" && <IndeterminateBar label="Avaliação em curso" />}

      {attempt.session_id && !terminal && (
        <nav aria-label="Ferramentas da tentativa" className="flex gap-2 text-sm">
          <Link className="rounded bg-sky-800 px-2 py-1" to={dynoPath(attempt.session_id)}>
            Abrir bancada
          </Link>
          <Link className="rounded bg-sky-800 px-2 py-1" to={ecuPath(attempt.session_id)}>
            Abrir ECU
          </Link>
        </nav>
      )}

      {attempt.baseline_peak_whp !== null && (
        <p className="text-sm">Puxada base: {fmt(attempt.baseline_peak_whp, 1)} whp</p>
      )}

      <section aria-labelledby={`progress-${attempt.attempt_id}`}>
        <h3 id={`progress-${attempt.attempt_id}`} className="font-semibold">
          Critérios (provisório)
        </h3>
        {attempt.progress.length === 0 ? (
          <p className="text-sm text-zinc-400">Sem puxadas válidas ainda.</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {attempt.progress.map((r) => (
              <li key={r.criterion_id} className="flex justify-between gap-2">
                <span>
                  {CRITERION_INFO[r.kind].label}: {fmt(r.measured, r.kind.startsWith("lambda") ? 3 : 1)}
                  {thresholds.has(r.criterion_id) && <span className="text-zinc-400"> ({thresholds.get(r.criterion_id)})</span>}
                </span>
                <CriterionStatus passed={r.passed} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby={`runs-${attempt.attempt_id}`}>
        <h3 id={`runs-${attempt.attempt_id}`} className="font-semibold">
          Puxadas
        </h3>
        {attempt.runs.length === 0 ? (
          <p className="text-sm text-zinc-400">Ainda sem puxadas.</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {attempt.runs.map((r) => (
              <li key={`${r.run_id}-${r.pull_index}`}>
                <span className="font-mono text-xs">{r.run_id.slice(-6)}</span> {r.run_type}
                {r.pull_index > 0 && ` #${r.pull_index}`} · {fmt(r.peak_whp, 1)} whp ·{" "}
                {r.valid ? (
                  <span className="text-emerald-300">
                    <span aria-hidden="true">✓ </span>válida
                  </span>
                ) : (
                  <span className="text-red-300">
                    <span aria-hidden="true">✗ </span>inválida: {invalidReasonLabel(r.invalid_reason)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <HintPanel attemptId={attempt.attempt_id} revealed={attempt.hints_revealed} total={attempt.hints_total} disabled={terminal} />

      {actionError !== null && <ErrorBox error={actionError} />}
      {submitted !== null && attempt.state === "evaluating" && (
        <p role="status" className="text-sm">
          Submissão {submitted} recebida; a avaliar…
        </p>
      )}

      {inProgress && (
        <div className="space-y-2">
          {scenario?.has_hidden_defect && (
            <label className="block text-sm">
              Defeito diagnosticado
              <select
                className="mt-1 w-full rounded bg-zinc-800 px-2 py-1"
                value={declared}
                onChange={(e) => setDeclared(e.target.value as DefectKind | "none" | "")}
              >
                <option value="">Não declarar</option>
                <option value="none">Nenhum defeito</option>
                {DEFECT_KINDS.map((k) => (
                  <option key={k} value={k}>
                    {DEFECT_LABELS[k]}
                  </option>
                ))}
              </select>
            </label>
          )}
          <div className="flex gap-2">
            <button
              type="button"
              disabled={busy || attempt.submissions >= attempt.max_submissions}
              onClick={() => void submit()}
              className="rounded bg-emerald-700 px-3 py-1 disabled:opacity-50"
            >
              Submeter
            </button>
            <button type="button" disabled={busy} onClick={() => void abandon()} className="rounded bg-zinc-700 px-3 py-1">
              Abandonar
            </button>
          </div>
        </div>
      )}

      {hasResult && (
        <Link className="inline-block text-sm text-sky-300 underline" to={`/attempts/${encodeURIComponent(attempt.attempt_id)}/result`}>
          Ver resultado da última submissão
        </Link>
      )}
    </aside>
  );
}
