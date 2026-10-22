/** Lista de cenários com filtros de tipo, veículo e combustível (training-scenarios RF-24). */
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { useScenariosApi } from "./api";
import { FUEL_LABELS, VEHICLE_IDS, VEHICLE_LABELS, type ScenarioKind, type ScenarioSummary } from "./types";
import { ErrorBox, PassBadge, SkeletonCards } from "./ui";
import { useActiveProfileId } from "./useActiveProfile";

export function ScenarioList() {
  const api = useScenariosApi();
  const profileId = useActiveProfileId();
  const [kind, setKind] = useState<ScenarioKind | "all">("all");
  const [vehicle, setVehicle] = useState<string>("all");
  const [fuel, setFuel] = useState<string>("all");
  const [tick, setTick] = useState(0);
  const key = `${kind}|${profileId ?? ""}|${tick}`;
  const [loaded, setLoaded] = useState<{ key: string; items: ScenarioSummary[] | null; error: unknown }>({
    key: "",
    items: null,
    error: null,
  });
  const items = loaded.key === key ? loaded.items : null;
  const error = loaded.key === key ? loaded.error : null;

  useEffect(() => {
    let alive = true;
    api
      .listScenarios(kind === "all" ? undefined : kind)
      .then((list) => {
        if (alive) setLoaded({ key, items: list, error: null });
      })
      .catch((e: unknown) => {
        if (alive) setLoaded({ key, items: null, error: e });
      });
    return () => {
      alive = false;
    };
  }, [api, kind, key]);

  const fuels = useMemo(() => [...new Set((items ?? []).map((s) => s.fuel_id))].sort(), [items]);
  const visible = (items ?? []).filter(
    (s) => (vehicle === "all" || s.vehicle_id === vehicle) && (fuel === "all" || s.fuel_id === fuel),
  );

  return (
    <section aria-labelledby="scenario-list-title" className="space-y-3">
      <h1 id="scenario-list-title" className="text-xl font-semibold">
        Cenários de treino
      </h1>
      <div className="flex flex-wrap gap-3 text-sm">
        <label className="flex items-center gap-1">
          Tipo
          <select className="rounded bg-zinc-800 px-2 py-1" value={kind} onChange={(e) => setKind(e.target.value as ScenarioKind | "all")}>
            <option value="all">Todos</option>
            <option value="base">Base</option>
            <option value="challenge">Desafio</option>
          </select>
        </label>
        <label className="flex items-center gap-1">
          Veículo
          <select className="rounded bg-zinc-800 px-2 py-1" value={vehicle} onChange={(e) => setVehicle(e.target.value)}>
            <option value="all">Todos</option>
            {VEHICLE_IDS.map((v) => (
              <option key={v} value={v}>
                {VEHICLE_LABELS[v]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1">
          Combustível
          <select className="rounded bg-zinc-800 px-2 py-1" value={fuel} onChange={(e) => setFuel(e.target.value)}>
            <option value="all">Todos</option>
            {fuels.map((f) => (
              <option key={f} value={f}>
                {FUEL_LABELS[f] ?? f}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error !== null ? (
        <ErrorBox error={error} onRetry={() => setTick((t) => t + 1)} />
      ) : items === null ? (
        <SkeletonCards />
      ) : visible.length === 0 ? (
        <p className="text-zinc-400">Nenhum cenário com estes filtros.</p>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {visible.map((s) => (
            <li key={s.scenario_id} className="rounded border border-zinc-700 bg-zinc-900 p-3">
              <Link to={`/scenarios/${encodeURIComponent(s.scenario_id)}`} className="font-medium text-sky-300 underline">
                {s.title}
              </Link>
              <p className="mt-1 text-sm text-zinc-300">
                {VEHICLE_LABELS[s.vehicle_id] ?? s.vehicle_id} · {FUEL_LABELS[s.fuel_id] ?? s.fuel_id}
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                <span className="rounded bg-zinc-700 px-1.5 py-0.5">{s.kind === "base" ? "Base" : "Desafio"}</span>
                {s.has_hidden_defect && (
                  <span className="rounded bg-purple-800 px-1.5 py-0.5 text-white">
                    <span aria-hidden="true">⚠ </span>Defeito oculto
                  </span>
                )}
                {!s.available && <span className="rounded bg-zinc-600 px-1.5 py-0.5">Indisponível</span>}
                {profileId && s.last_evaluation_passed !== null && <PassBadge passed={s.last_evaluation_passed} size="sm" />}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
