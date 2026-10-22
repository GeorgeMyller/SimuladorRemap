/** Briefing do cenário: objetivos, critérios, restrições e início da tentativa (RF-07, RF-24). */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useScenariosApi } from "./api";
import { CRITERION_INFO, DEFECT_LABELS, FUEL_LABELS, VEHICLE_LABELS, type Criterion, type ScenarioView } from "./types";
import { ErrorBox, fmt, SkeletonCards } from "./ui";
import { useActiveProfileId } from "./useActiveProfile";

const COMPARATOR_TEXT = { ge: "≥", le: "≤", bool: "" } as const;

export function criterionThreshold(c: Criterion): string {
  if (c.comparator === "bool") return "sim";
  const unit = CRITERION_INFO[c.kind].unit;
  const digits = c.kind.startsWith("lambda") ? 2 : c.threshold !== null && Number.isInteger(c.threshold) ? 0 : 1;
  return `${COMPARATOR_TEXT[c.comparator]} ${fmt(c.threshold, digits)}${unit ? ` ${unit}` : ""}`;
}

export function ScenarioBriefing({ scenarioId }: { scenarioId: string }) {
  const api = useScenariosApi();
  const navigate = useNavigate();
  const profileId = useActiveProfileId();
  const [scenario, setScenario] = useState<ScenarioView | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [startError, setStartError] = useState<unknown>(null);
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    let alive = true;
    api
      .getScenario(scenarioId)
      .then((s) => {
        if (alive) setScenario(s);
      })
      .catch((e: unknown) => {
        if (alive) setError(e);
      });
    return () => {
      alive = false;
    };
  }, [api, scenarioId, profileId]);

  async function start() {
    setStarting(true);
    setStartError(null);
    try {
      const attempt = await api.startAttempt(scenarioId);
      void navigate(`/attempts/${encodeURIComponent(attempt.attempt_id)}`);
    } catch (e) {
      setStartError(e);
      setStarting(false);
    }
  }

  if (error !== null) return <ErrorBox error={error} />;
  if (scenario === null) return <SkeletonCards count={2} />;
  const c = scenario.constraints;

  return (
    <article aria-labelledby="briefing-title" className="space-y-4">
      <header>
        <h1 id="briefing-title" className="text-xl font-semibold">
          {scenario.title}
        </h1>
        <p className="text-sm text-zinc-300">
          {VEHICLE_LABELS[scenario.vehicle_id] ?? scenario.vehicle_id} · perfil inicial {scenario.initial_profile_id} ·{" "}
          {FUEL_LABELS[scenario.fuel_id] ?? scenario.fuel_id}
        </p>
        {scenario.has_hidden_defect && (
          <p className="mt-1 text-sm text-purple-300">
            <span aria-hidden="true">⚠ </span>Este cenário tem um defeito oculto.
            {scenario.hidden_defect && ` (Instrutor: ${DEFECT_LABELS[scenario.hidden_defect.kind]})`}
          </p>
        )}
      </header>
      {scenario.briefing && <p className="whitespace-pre-line">{scenario.briefing}</p>}
      <section aria-labelledby="objectives-title">
        <h2 id="objectives-title" className="font-semibold">
          Objetivos
        </h2>
        <ul className="list-disc pl-6">
          {scenario.objectives.map((o) => (
            <li key={o}>{o}</li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="criteria-title">
        <h2 id="criteria-title" className="font-semibold">
          Critérios de aprovação
        </h2>
        <table className="mt-1 w-full text-sm">
          <caption className="sr-only">Critérios, limiares e unidades</caption>
          <thead>
            <tr className="text-left">
              <th scope="col">Critério</th>
              <th scope="col">Limiar</th>
              <th scope="col">Peso</th>
              <th scope="col">Obrigatório</th>
            </tr>
          </thead>
          <tbody>
            {scenario.criteria.criteria.map((cr) => (
              <tr key={cr.criterion_id} className="border-t border-zinc-800">
                <td>{CRITERION_INFO[cr.kind].label}</td>
                <td>{criterionThreshold(cr)}</td>
                <td>{fmt(cr.weight, 1)}</td>
                <td>{cr.mandatory ? "Sim" : "Não"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-1 text-xs text-zinc-400">
          Puxadas válidas exigidas: {scenario.criteria.required_valid_pulls}. Lambda avaliado a partir de{" "}
          {fmt(scenario.criteria.lambda_window_min_rpm, 0)} rpm.
        </p>
      </section>
      <section aria-labelledby="constraints-title">
        <h2 id="constraints-title" className="font-semibold">
          Restrições e condições
        </h2>
        <ul className="list-disc pl-6 text-sm">
          <li>Marcha: {c.gear}ª · puxadas permitidas: {c.allowed_run_types.join(", ")}</li>
          <li>Submissões máximas: {c.max_submissions}</li>
          {c.allowed_final_profiles.length > 0 && <li>Perfil final permitido: {c.allowed_final_profiles.join(", ")}</li>}
          {c.swap_allowed && <li>Troca para ECU standalone permitida</li>}
          {c.locked_table_ids.length > 0 && <li>Tabelas bloqueadas: {c.locked_table_ids.join(", ")}</li>}
          {c.time_limit_min !== null && <li>Tempo limite: {c.time_limit_min} min</li>}
          <li>
            Ambiente: {fmt(scenario.ambient.temperature_c, 1)} °C, {fmt(scenario.ambient.pressure_kpa, 1)} kPa, umidade{" "}
            {fmt(scenario.ambient.relative_humidity * 100, 0)} % · correção {scenario.correction_standard}
          </li>
        </ul>
      </section>
      {startError !== null && <ErrorBox error={startError} />}
      {!profileId && <p className="text-sm text-amber-300">Escolha um perfil antes de iniciar a tentativa.</p>}
      <button
        type="button"
        disabled={starting || !profileId}
        onClick={() => void start()}
        className="rounded bg-emerald-700 px-4 py-2 font-medium disabled:opacity-50"
      >
        {starting ? "A iniciar…" : "Iniciar tentativa"}
      </button>
    </article>
  );
}
