/**
 * Página `/sessions/:sessionId/upgrades` (aba Upgrades ao lado da ECU): troca as peças da
 * oficina com a sessão viva (`PUT /sessions/{id}/upgrades`), sem criar outra sessão. A
 * calibração ativa continua; o motor volta à marcha lenta e o dano é reposto. Peças fixas
 * em tentativas de cenário e bloqueadas durante uma puxada.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { dynoPath, ecuPath } from "@/app/paths";
import { isApiProblem } from "@/lib/api";

import { sessionUpgradesApi, type SessionUpgradesApi, type SimulationSession } from "./api";
import { CategoryPicker } from "./StageBuilder";
import {
  CATEGORY_LABEL,
  changedCategories,
  partsFromPackage,
  stageErrorText,
  toUpgradePackage,
  type PartSelection,
  type UpgradeCategory,
  type UpgradeCategoryOptions,
} from "./types";
import { useStageBuilderData } from "./useStageBuilderData";

type SessionState = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; session: SimulationSession };

function errorText(error: unknown): string {
  if (isApiProblem(error)) {
    if (error.code === "RUN_IN_PROGRESS") return "Há uma puxada em andamento. Espere o fim da puxada e instale de novo.";
    if (error.code === "UPGRADES_LOCKED") return "As peças desta tentativa de cenário são fixas.";
    if (error.code === "SESSION_CLOSED") return "A sessão está encerrada. Crie uma sessão nova no Início.";
    return stageErrorText(error.code, error.extra) ?? `${error.detail || error.title} (${error.code})`;
  }
  return "Resposta do servidor fora do contrato da API.";
}

function partLabel(categories: UpgradeCategoryOptions[], category: UpgradeCategory, partId: string): string {
  const group = categories.find((g) => g.category === category);
  return group?.options.find((o) => o.part_id === partId)?.label ?? partId;
}

export interface UpgradesViewProps {
  sessionId: string;
  api?: SessionUpgradesApi;
}

export function UpgradesView({ sessionId, api = sessionUpgradesApi }: UpgradesViewProps) {
  const [state, setState] = useState<SessionState>({ status: "loading" });
  const [round, setRound] = useState(0);
  const [chosen, setChosen] = useState<PartSelection | null>(null);
  const [busy, setBusy] = useState(false);
  const [installError, setInstallError] = useState<string | null>(null);
  const [installed, setInstalled] = useState<UpgradeCategory[] | null>(null);

  useEffect(() => {
    let alive = true;
    void api
      .getSession(sessionId)
      .then((session) => {
        if (!alive) return;
        setState({ status: "ready", session });
        setChosen(partsFromPackage(session.upgrades));
      })
      .catch((e: unknown) => alive && setState({ status: "error", message: errorText(e) }));
    return () => {
      alive = false;
    };
  }, [api, sessionId, round]);

  const session = state.status === "ready" ? state.session : null;
  const current = useMemo(() => partsFromPackage(session?.upgrades), [session]);
  const pending = useMemo(() => (chosen ? changedCategories(current, chosen) : []), [current, chosen]);

  const install = useCallback(async () => {
    if (!chosen || pending.length === 0) return;
    setBusy(true);
    setInstallError(null);
    setInstalled(null);
    try {
      const updated = await api.installUpgrades(sessionId, toUpgradePackage(chosen));
      setState({ status: "ready", session: updated });
      setChosen(partsFromPackage(updated.upgrades));
      setInstalled(pending);
    } catch (e: unknown) {
      setInstallError(errorText(e));
    } finally {
      setBusy(false);
    }
  }, [api, chosen, pending, sessionId]);

  return (
    <section aria-labelledby="upgrades-title" className="mx-auto max-w-5xl space-y-4">
      <header>
        <h1 id="upgrades-title" className="text-xl font-semibold">
          Upgrades
        </h1>
        <p className="mt-1 text-sm text-zinc-300">
          Instale peças no carro desta sessão. Depois acerte a calibração na ECU e meça o resultado na bancada.
        </p>
      </header>

      {state.status === "loading" && (
        <p role="status" className="text-sm text-zinc-400">
          A carregar a sessão
        </p>
      )}
      {state.status === "error" && (
        <div role="alert" className="rounded border border-red-500 p-3 text-sm">
          <p>{state.message}</p>
          <button
            type="button"
            onClick={() => {
              setState({ status: "loading" });
              setRound((r) => r + 1);
            }}
            className="mt-2 rounded border border-amber-400 px-3 py-1 text-amber-200 hover:bg-zinc-800">
            Tentar de novo
          </button>
        </div>
      )}
      {session && chosen && (
        <SessionUpgrades
          api={api}
          session={session}
          current={current}
          chosen={chosen}
          pending={pending}
          busy={busy}
          onChange={(next) => {
            setChosen(next);
            setInstalled(null);
          }}
          onInstall={() => void install()}
          onDiscard={() => setChosen(current)}
        />
      )}
      {installError && (
        <p role="alert" className="rounded border border-red-500 p-3 text-sm">
          {installError}
        </p>
      )}
      {installed && session && (
        <div role="status" className="rounded border border-emerald-500 p-3 text-sm">
          <p>
            Peças instaladas: {installed.map((c) => CATEGORY_LABEL[c]).join(", ")}. O motor voltou à marcha lenta com a mesma calibração.
          </p>
          <p className="mt-2 flex flex-wrap gap-3">
            <Link to={ecuPath(session.session_id)} className="text-amber-300 underline hover:text-amber-200">
              Acertar na ECU
            </Link>
            <Link to={dynoPath(session.session_id)} className="text-amber-300 underline hover:text-amber-200">
              Medir na bancada
            </Link>
          </p>
        </div>
      )}
    </section>
  );
}

interface SessionUpgradesProps {
  api: SessionUpgradesApi;
  session: SimulationSession;
  current: PartSelection;
  chosen: PartSelection;
  pending: UpgradeCategory[];
  busy: boolean;
  onChange: (next: PartSelection) => void;
  onInstall: () => void;
  onDiscard: () => void;
}

function SessionUpgrades({ api, session, current, chosen, pending, busy, onChange, onInstall, onDiscard }: SessionUpgradesProps) {
  const { data, retry } = useStageBuilderData(api, session.vehicle_id);
  const closed = session.state === "closed";
  const locked = session.attempt_id != null;
  const running = session.active_run_id != null;
  const lockReason = closed
    ? "A sessão está encerrada. Crie uma sessão nova no Início."
    : locked
      ? "As peças desta tentativa de cenário são fixas."
      : running
        ? "Há uma puxada em andamento. Espere o fim da puxada para trocar peças."
        : null;
  const disabled = busy || lockReason !== null;

  if (data.status === "loading") {
    return (
      <p role="status" className="text-sm text-zinc-400">
        A carregar o catálogo de peças
      </p>
    );
  }
  if (data.status === "error") {
    return (
      <div role="alert" className="rounded border border-red-500 p-3 text-sm">
        <p>Não foi possível carregar o catálogo de peças.</p>
        <p className="mt-1 font-mono text-xs text-zinc-300">{data.message}</p>
        <button type="button" onClick={retry} className="mt-2 rounded border border-amber-400 px-3 py-1 text-amber-200 hover:bg-zinc-800">
          Tentar de novo
        </button>
      </div>
    );
  }

  return (
    <>
      {lockReason && (
        <p role="note" className="rounded border border-amber-500 p-3 text-sm text-amber-100">
          {lockReason}
        </p>
      )}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {data.categories.map((group) => (
          <div key={group.category} className="relative">
            {current[group.category] !== "stock" && (
              <span className="absolute right-2 top-2 z-10 rounded bg-emerald-900 px-1.5 py-0.5 text-xs text-emerald-100">Instalada</span>
            )}
            <CategoryPicker
              group={group}
              compat={data.compat}
              selected={chosen[group.category]}
              disabled={disabled}
              onSelect={(partId) => onChange({ ...chosen, [group.category]: partId })}
            />
          </div>
        ))}
      </div>
      <div className="sticky bottom-0 flex flex-wrap items-center gap-3 rounded border border-zinc-700 bg-zinc-950 p-3">
        {pending.length === 0 ? (
          <p className="text-sm text-zinc-400">Nenhuma alteração pendente.</p>
        ) : (
          <ul aria-label="Alterações pendentes" className="text-sm">
            {pending.map((category) => (
              <li key={category}>
                {CATEGORY_LABEL[category]}: {partLabel(data.categories, category, current[category])} →{" "}
                <span className="text-amber-300">{partLabel(data.categories, category, chosen[category])}</span>
              </li>
            ))}
          </ul>
        )}
        <span className="ml-auto flex gap-2">
          <button
            type="button"
            onClick={onDiscard}
            disabled={disabled || pending.length === 0}
            className="rounded border border-zinc-600 px-3 py-1.5 text-sm hover:bg-zinc-800 disabled:opacity-50"
          >
            Descartar
          </button>
          <button
            type="button"
            onClick={onInstall}
            disabled={disabled || pending.length === 0}
            className="rounded bg-amber-500 px-4 py-1.5 text-sm font-medium text-zinc-950 hover:bg-amber-400 disabled:opacity-50"
          >
            {busy ? "A instalar…" : "Instalar peças"}
          </button>
        </span>
      </div>
      <p className="text-xs text-zinc-400">
        A instalação liga o motor de novo em marcha lenta e repõe o dano. A calibração ativa não muda. Bicos novos: a ECU OEM lê a vazão nova; numa
        ECU standalone, atualize a vazão dos bicos na base setup.
      </p>
    </>
  );
}

export default function UpgradesPage() {
  const { sessionId } = useParams();
  if (!sessionId) return <p role="alert">Sessão não indicada.</p>;
  return <UpgradesView key={sessionId} sessionId={sessionId} />;
}
