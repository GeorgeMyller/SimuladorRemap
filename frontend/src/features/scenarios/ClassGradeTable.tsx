/**
 * Tabela de avaliação da turma (tentativas importadas, última submissão) com ordenação,
 * filtros por cenário e aprovado, replay por linha e export do CSV de notas (RF-22, RF-25, RF-26).
 */
import { useEffect, useMemo, useState } from "react";

import { downloadText, useScenariosApi } from "./api";
import { gradesCsv, stationOf, type GradeRow } from "./gradesCsv";
import type { AttemptView, ReplayStatus } from "./types";
import { ErrorBox, fmt, PassBadge, SkeletonCards } from "./ui";

type SortKey = "nickname" | "scenario_id" | "submission" | "passed" | "total_score" | "evaluation_mismatch" | "replay_status" | "imported_at";

const COLUMNS: { key: SortKey; label: string }[] = [
  { key: "nickname", label: "Aluno" },
  { key: "scenario_id", label: "Cenário" },
  { key: "submission", label: "Submissão" },
  { key: "passed", label: "Resultado" },
  { key: "total_score", label: "Pontuação" },
  { key: "evaluation_mismatch", label: "Avaliação divergente" },
  { key: "replay_status", label: "Replay" },
  { key: "imported_at", label: "Importado em" },
];

const REPLAY_TEXT: Record<ReplayStatus, string> = {
  not_run: "não executado",
  running: "em execução",
  verified: "verificado",
  mismatch: "replay divergente",
  incompatible_version: "versão incompatível",
};

export function displayNickname(a: Pick<AttemptView, "nickname" | "producer_install_id">): string {
  const station = stationOf(a.producer_install_id);
  return station ? `${a.nickname} (${station})` : a.nickname;
}

function sortValue(a: AttemptView, key: SortKey): string | number {
  switch (key) {
    case "nickname":
      return displayNickname(a).toLowerCase();
    case "scenario_id":
      return a.scenario_id;
    case "submission":
      return a.last_evaluation?.submission_index ?? a.submissions;
    case "passed":
      return a.last_evaluation?.passed === true ? 1 : a.last_evaluation?.passed === false ? 0 : -1;
    case "total_score":
      return a.last_evaluation?.total_score ?? -1;
    case "evaluation_mismatch":
      return a.evaluation_mismatch ? 1 : 0;
    case "replay_status":
      return a.replay_status;
    case "imported_at":
      return a.imported_at ?? "";
  }
}

export function toGradeRow(a: AttemptView): GradeRow {
  const ev = a.last_evaluation;
  return {
    nickname: a.nickname,
    install_id: a.producer_install_id,
    scenario_id: a.scenario_id,
    scenario_title: a.scenario_title,
    attempt_id: a.attempt_id,
    submission: ev?.submission_index ?? a.submissions,
    passed: ev?.passed ?? null,
    total_score: ev?.total_score ?? null,
    evaluation_mismatch: a.evaluation_mismatch,
    replay_status: a.replay_status,
    package_sha256: a.package_sha256,
    imported_at: a.imported_at,
    scores: Object.fromEntries((ev?.results ?? []).map((r) => [r.criterion_id, r.score])),
  };
}

export async function loadAllImported(api: ReturnType<typeof useScenariosApi>): Promise<AttemptView[]> {
  const all: AttemptView[] = [];
  let cursor: string | undefined;
  for (let guard = 0; guard < 100; guard++) {
    const page = await api.listAttempts({ origin: "imported", limit: 200, ...(cursor ? { cursor } : {}) });
    all.push(...page.items);
    if (!page.next_cursor) break;
    cursor = page.next_cursor;
  }
  return all;
}

export function ClassGradeTable({ reloadKey = 0 }: { reloadKey?: number }) {
  const api = useScenariosApi();
  const [rows, setRows] = useState<AttemptView[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [scenarioFilter, setScenarioFilter] = useState("all");
  const [passedFilter, setPassedFilter] = useState<"all" | "passed" | "failed">("all");
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "nickname", dir: 1 });
  const [criterionIds, setCriterionIds] = useState<string[]>([]);
  const [rowError, setRowError] = useState<unknown>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let alive = true;
    loadAllImported(api)
      .then((list) => {
        if (alive) setRows(list);
      })
      .catch((e: unknown) => {
        if (alive) setError(e);
      });
    return () => {
      alive = false;
    };
  }, [api, reloadKey, tick]);

  useEffect(() => {
    if (scenarioFilter === "all") return;
    let alive = true;
    api
      .getScenario(scenarioFilter)
      .then((s) => {
        if (alive) setCriterionIds(s.criteria.criteria.map((c) => c.criterion_id));
      })
      .catch(() => {
        if (alive) setCriterionIds([]);
      });
    return () => {
      alive = false;
    };
  }, [api, scenarioFilter]);

  const scenarios = useMemo(() => [...new Set((rows ?? []).map((r) => r.scenario_id))].sort(), [rows]);
  const visible = useMemo(() => {
    const filtered = (rows ?? []).filter((r) => {
      if (scenarioFilter !== "all" && r.scenario_id !== scenarioFilter) return false;
      const passed = r.last_evaluation?.passed;
      if (passedFilter === "passed") return passed === true;
      if (passedFilter === "failed") return passed !== true;
      return true;
    });
    return [...filtered].sort((a, b) => {
      const va = sortValue(a, sort.key);
      const vb = sortValue(b, sort.key);
      return (va < vb ? -1 : va > vb ? 1 : 0) * sort.dir;
    });
  }, [rows, scenarioFilter, passedFilter, sort]);

  function toggleSort(key: SortKey) {
    setSort((s) => ({ key, dir: s.key === key ? (s.dir === 1 ? -1 : 1) : 1 }));
  }

  function exportCsv(dialect: "pt-BR" | "rfc4180") {
    const csv = gradesCsv(visible.map(toGradeRow), {
      dialect,
      criterionIds: scenarioFilter === "all" ? [] : criterionIds,
    });
    const name = scenarioFilter === "all" ? "turma" : scenarioFilter;
    downloadText(`notas-${name}.csv`, csv, "text/csv");
  }

  async function replay(attemptId: string) {
    setRowError(null);
    try {
      await api.replay(attemptId);
      setTick((t) => t + 1);
    } catch (e) {
      setRowError(e);
    }
  }

  if (error !== null)
    return (
      <ErrorBox
        error={error}
        onRetry={() => {
          setError(null);
          setRows(null);
          setTick((t) => t + 1);
        }}
      />
    );
  if (rows === null) return <SkeletonCards count={1} />;
  if (rows.length === 0) return <p className="text-zinc-400">Ainda sem tentativas importadas.</p>;

  return (
    <section aria-labelledby="grades-title" className="space-y-2">
      <h3 id="grades-title" className="font-semibold">
        Avaliação da turma
      </h3>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <label className="flex items-center gap-1">
          Cenário
          <select className="rounded bg-zinc-800 px-2 py-1" value={scenarioFilter} onChange={(e) => setScenarioFilter(e.target.value)}>
            <option value="all">Todos</option>
            {scenarios.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1">
          Resultado
          <select
            className="rounded bg-zinc-800 px-2 py-1"
            value={passedFilter}
            onChange={(e) => setPassedFilter(e.target.value as "all" | "passed" | "failed")}
          >
            <option value="all">Todos</option>
            <option value="passed">Aprovados</option>
            <option value="failed">Reprovados</option>
          </select>
        </label>
        <button type="button" className="rounded bg-sky-700 px-3 py-1" onClick={() => exportCsv("pt-BR")}>
          Exportar CSV
        </button>
        <button type="button" className="rounded bg-zinc-700 px-3 py-1" onClick={() => exportCsv("rfc4180")}>
          Exportar CSV (RFC 4180)
        </button>
        <span className="text-zinc-400">{visible.length} linhas</span>
      </div>
      {rowError !== null && <ErrorBox error={rowError} />}
      <div className="overflow-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">Tentativas importadas, última submissão</caption>
          <thead>
            <tr className="text-left">
              {COLUMNS.map((c) => (
                <th key={c.key} scope="col" aria-sort={sort.key === c.key ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
                  <button type="button" className="underline-offset-2 hover:underline" onClick={() => toggleSort(c.key)}>
                    {c.label}
                    {sort.key === c.key && <span aria-hidden="true">{sort.dir === 1 ? " ▲" : " ▼"}</span>}
                  </button>
                </th>
              ))}
              <th scope="col">Ações</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((a) => {
              const ev = a.last_evaluation;
              return (
                <tr key={a.attempt_id} data-attempt={a.attempt_id} className="border-t border-zinc-800">
                  <td>{displayNickname(a)}</td>
                  <td>{a.scenario_title || a.scenario_id}</td>
                  <td>{ev?.submission_index ?? a.submissions}</td>
                  <td>
                    <PassBadge passed={ev?.passed ?? null} size="sm" />
                  </td>
                  <td>{fmt(ev?.total_score, 1)}</td>
                  <td>{a.evaluation_mismatch ? <span className="text-amber-300">⚠ Sim (recalculada)</span> : "Não"}</td>
                  <td className={a.replay_status === "mismatch" ? "text-red-300" : undefined}>
                    {a.replay_status === "mismatch" && <span aria-hidden="true">⚠ </span>}
                    {REPLAY_TEXT[a.replay_status]}
                  </td>
                  <td>{a.imported_at ? new Date(a.imported_at).toLocaleString("pt-BR") : "—"}</td>
                  <td>
                    <button
                      type="button"
                      disabled={a.replay_status === "running"}
                      className="rounded bg-zinc-700 px-2 py-0.5 disabled:opacity-50"
                      onClick={() => void replay(a.attempt_id)}
                      aria-label={`Replay da tentativa de ${displayNickname(a)}`}
                    >
                      Replay
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
