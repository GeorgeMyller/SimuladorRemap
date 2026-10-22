/** Painel do instrutor: abas "Desafios" (criar e exportar) e "Turma" (importar e avaliar) (RF-05, RF-25). */
import { useEffect, useState, type KeyboardEvent } from "react";

import { downloadText, useScenariosApi } from "./api";
import { ChallengeForm } from "./ChallengeForm";
import { ClassGradeTable } from "./ClassGradeTable";
import { PackageImportQueue } from "./PackageImportQueue";
import type { ScenarioSummary } from "./types";
import { ErrorBox } from "./ui";
import { useProfiles } from "./useActiveProfile";

type Tab = "challenges" | "class";
const TABS: { id: Tab; label: string }[] = [
  { id: "challenges", label: "Desafios" },
  { id: "class", label: "Turma" },
];

function ChallengeExports({ reloadKey }: { reloadKey: number }) {
  const api = useScenariosApi();
  const [items, setItems] = useState<ScenarioSummary[]>([]);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let alive = true;
    api
      .listScenarios("challenge")
      .then((list) => {
        if (alive) setItems(list);
      })
      .catch((e: unknown) => {
        if (alive) setError(e);
      });
    return () => {
      alive = false;
    };
  }, [api, reloadKey]);

  async function exportChallenge(scenarioId: string) {
    setError(null);
    try {
      const file = await api.exportPackage({ kind: "challenge", scenario_id: scenarioId, include_full_logs: false });
      downloadText(file.filename, file.content);
    } catch (e) {
      setError(e);
    }
  }

  return (
    <section aria-labelledby="challenge-exports-title" className="space-y-2">
      <h3 id="challenge-exports-title" className="font-semibold">
        Desafios desta estação
      </h3>
      {error !== null && <ErrorBox error={error} />}
      {items.length === 0 ? (
        <p className="text-sm text-zinc-400">Ainda sem desafios.</p>
      ) : (
        <ul className="space-y-1 text-sm">
          {items.map((s) => (
            <li key={s.scenario_id} className="flex items-center justify-between gap-2">
              <span>
                {s.title} <span className="font-mono text-xs text-zinc-400">{s.scenario_id}</span>
              </span>
              <button type="button" className="rounded bg-sky-700 px-2 py-0.5" onClick={() => void exportChallenge(s.scenario_id)}>
                Exportar desafio {s.scenario_id}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function InstructorPanel({ initialTab = "challenges" }: { initialTab?: Tab }) {
  const { active, loading } = useProfiles();
  const [tab, setTab] = useState<Tab>(initialTab);
  const [challengeKey, setChallengeKey] = useState(0);
  const [classKey, setClassKey] = useState(0);

  function onTabKey(e: KeyboardEvent<HTMLButtonElement>) {
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      setTab((t) => (t === "challenges" ? "class" : "challenges"));
    }
  }

  if (!loading && active?.role !== "instructor") {
    return (
      <p role="alert" className="rounded border border-amber-600 bg-amber-950 p-3 text-sm">
        O painel do instrutor exige um perfil com papel «Instrutor». Troque de perfil em «Perfis».
      </p>
    );
  }

  return (
    <section aria-labelledby="instructor-title" className="space-y-3">
      <h1 id="instructor-title" className="text-xl font-semibold">
        Painel do instrutor
      </h1>
      <div role="tablist" aria-label="Secções do painel" className="flex gap-2">
        {TABS.map((t) => (
          <button
            key={t.id}
            id={`tab-${t.id}`}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            aria-controls={`panel-${t.id}`}
            tabIndex={tab === t.id ? 0 : -1}
            onKeyDown={onTabKey}
            onClick={() => setTab(t.id)}
            className={`rounded px-3 py-1 ${tab === t.id ? "bg-sky-700" : "bg-zinc-800"}`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "challenges" ? (
        <div role="tabpanel" id="panel-challenges" aria-labelledby="tab-challenges" className="space-y-4">
          <ChallengeForm onCreated={() => setChallengeKey((k) => k + 1)} />
          <ChallengeExports reloadKey={challengeKey} />
        </div>
      ) : (
        <div role="tabpanel" id="panel-class" aria-labelledby="tab-class" className="space-y-4">
          <PackageImportQueue onFinished={() => setClassKey((k) => k + 1)} />
          <ClassGradeTable reloadKey={classKey} />
        </div>
      )}
    </section>
  );
}
