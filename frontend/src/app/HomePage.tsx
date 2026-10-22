/**
 * Tela inicial (cockpit RF-01; T435): escolha de um dos carros do catálogo, do perfil de ECU
 * e de um cenário opcional. Sem cenário cria a sessão por `POST /api/v1/sessions`; com
 * cenário inicia a tentativa (`POST /api/v1/scenarios/{id}/attempts`), que cria a sessão.
 * Depois navega para a cockpit (ou para a ECU, se a cockpit estiver desligada por flag).
 * Cada carro aparece num card com a ilustração em pixel art; com uma sessão ativa, o erro da criação
 * (ex.: `SIM_CAPACITY_EXCEEDED`) oferece retomá-la ou encerrá-la.
 * Sessão livre: o Stage Builder (002 T047) escolhe as peças e o Flex Fuel, enviados como
 * `upgrades` e `ethanol_pct` no `POST /sessions`; os erros 409/422 da oficina têm texto próprio.
 */
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ZodError } from "zod";

import { PixelArtCar } from "@/features/pixel-cars/PixelArtCar";
import { StageBuilder } from "@/features/workshop/StageBuilder";
import { STOCK_SELECTION, stageErrorText, toSessionFields, type StageSelection } from "@/features/workshop/types";
import { isApiProblem } from "@/lib/api";

import { getActiveSessionId, setActiveSessionId } from "./activeSession";
import { readFeatureFlags, type FeatureFlags } from "./flags";
import { homeApi, type EcuProfileSummary, type HomeApi, type ScenarioSummary, type VehicleSummary } from "./homeApi";
import { dynoPath, ecuPath } from "./paths";

type Load =
  | { status: "loading" }
  | { status: "error"; code: string; text: string }
  | { status: "ready"; vehicles: VehicleSummary[]; profiles: EcuProfileSummary[]; scenarios: ScenarioSummary[] };

function describe(error: unknown): { code: string; text: string } {
  if (isApiProblem(error)) return { code: error.code, text: stageErrorText(error.code, error.extra) ?? (error.detail || error.title) };
  if (error instanceof ZodError) return { code: "UNEXPECTED_RESPONSE", text: "Resposta do servidor fora do contrato da API." };
  return { code: "UNEXPECTED_ERROR", text: error instanceof Error ? error.message : String(error) };
}

const INDUCTION_LABEL: Record<string, string> = {
  turbo: "Turbo",
  supercharger: "Compressor",
  natural: "Aspirado",
};

export interface HomePageProps {
  api?: HomeApi;
  flags?: FeatureFlags;
}

export function HomePage({ api = homeApi, flags }: HomePageProps) {
  const navigate = useNavigate();
  const features = useMemo(() => flags ?? readFeatureFlags(), [flags]);
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [round, setRound] = useState(0);
  const [vehicleId, setVehicleId] = useState("");
  const [profileId, setProfileId] = useState("");
  const [scenarioId, setScenarioId] = useState("");
  const [stage, setStage] = useState<StageSelection>(STOCK_SELECTION);
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState<{ code: string; text: string } | null>(null);
  const [activeSession, setActiveSession] = useState(getActiveSessionId);

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const [vehicles, profiles, scenarios] = await Promise.all([
          api.listVehicles(),
          api.listEcuProfiles(),
          // Cenários são opcionais: com a feature desligada (404) ou indisponível a lista fica vazia.
          api.listScenarios().catch(() => [] as ScenarioSummary[]),
        ]);
        if (!alive) return;
        setLoad({ status: "ready", vehicles, profiles, scenarios });
        const first = vehicles[0];
        if (first) {
          setVehicleId(first.vehicle_id);
          setProfileId(first.stock_profile_id);
        }
      } catch (error) {
        if (alive) setLoad({ status: "error", ...describe(error) });
      }
    })();
    return () => {
      alive = false;
    };
  }, [api, round]);

  const target = features.dynoCockpit ? dynoPath : features.ecuTuning ? ecuPath : null;

  if (load.status === "loading") {
    return (
      <section aria-labelledby="home-title" aria-busy="true" className="mx-auto max-w-6xl py-10">
        <h1 id="home-title" className="text-2xl font-semibold">
          Nova sessão
        </h1>
        <p role="status" className="mt-4 text-zinc-300">
          A carregar o catálogo de veículos…
        </p>
      </section>
    );
  }

  if (load.status === "error") {
    return (
      <section aria-labelledby="home-title" className="mx-auto max-w-6xl py-10">
        <h1 id="home-title" className="text-2xl font-semibold">
          Nova sessão
        </h1>
        <div role="alert" className="mt-4 rounded border border-red-500 p-4">
          <p className="font-semibold">Não foi possível carregar o catálogo.</p>
          <p className="mt-1 text-sm text-zinc-200">{load.text}</p>
          <p className="mt-1 font-mono text-xs text-zinc-400">{load.code}</p>
          <button
            type="button"
            onClick={() => {
              setLoad({ status: "loading" });
              setRound((r) => r + 1);
            }}
            className="mt-3 rounded bg-amber-500 px-3 py-1.5 font-semibold text-zinc-950 hover:bg-amber-400"
          >
            Tentar de novo
          </button>
        </div>
      </section>
    );
  }

  const { vehicles, profiles, scenarios } = load;
  const vehicleScenarios = scenarios.filter((s) => s.vehicle_id === vehicleId && s.available !== false);
  const scenario = vehicleScenarios.find((s) => s.scenario_id === scenarioId) ?? null;

  function chooseVehicle(v: VehicleSummary) {
    setVehicleId(v.vehicle_id);
    setProfileId(v.stock_profile_id);
    setScenarioId("");
    setStage(STOCK_SELECTION);
    setSubmitError(null);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!target || !vehicleId) return;
    setBusy(true);
    setSubmitError(null);
    try {
      let sessionId: string | null;
      if (scenario) {
        const attempt = await api.startAttempt(scenario.scenario_id);
        sessionId = attempt.session_id;
        if (!sessionId) {
          void navigate(`/attempts/${encodeURIComponent(attempt.attempt_id)}`);
          return;
        }
      } else {
        const session = await api.createSession({
          vehicle_id: vehicleId,
          profile_id: profileId as EcuProfileSummary["profile_id"],
          ...toSessionFields(stage),
        });
        sessionId = session.session_id;
      }
      setActiveSessionId(sessionId);
      void navigate(target(sessionId));
    } catch (error) {
      const err = describe(error);
      setSubmitError(err);
      if (err.code === "SIM_CAPACITY_EXCEEDED") {
        const match = /sessão ativa:\s*([0-9a-f]{32})/i.exec(err.text);
        if (match?.[1]) {
          setActiveSessionId(match[1]);
          setActiveSession(match[1]);
        }
      }
      setBusy(false);
    }
  }

  async function closeActiveSession(explicitId?: string) {
    const idToClose = explicitId || activeSession;
    if (!idToClose) return;
    setBusy(true);
    try {
      await api.closeSession(idToClose);
      setActiveSessionId(null);
      setActiveSession(null);
      setSubmitError(null);
    } catch {
      setActiveSessionId(null);
      setActiveSession(null);
      setSubmitError(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="home-title" className="mx-auto max-w-6xl py-6 sm:py-8">
      <h1 id="home-title" className="text-2xl font-semibold">
        Nova sessão
      </h1>
      {activeSession ? (
        <p className="mt-2 text-sm text-zinc-300">
          Sessão ativa <span className="font-mono">{activeSession.slice(0, 8)}</span>:{" "}
          {features.dynoCockpit && (
            <Link to={dynoPath(activeSession)} className="text-amber-300 underline">
              continuar na bancada
            </Link>
          )}
          {features.dynoCockpit && features.ecuTuning && " · "}
          {features.ecuTuning && (
            <Link to={ecuPath(activeSession)} className="text-amber-300 underline">
              abrir a ECU
            </Link>
          )}
        </p>
      ) : (
        <p className="mt-2 text-sm text-zinc-300">Nenhuma sessão ativa. Escolha o carro e crie uma sessão de bancada.</p>
      )}

      {vehicles.length === 0 ? (
        <p role="alert" className="mt-6 rounded border border-amber-400 p-4">
          O catálogo não tem veículos disponíveis.
        </p>
      ) : (
        <form onSubmit={(e) => void submit(e)} className="mt-6 space-y-6">
          <fieldset>
            <legend className="mb-2 font-semibold">Carro</legend>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {vehicles.map((v) => {
                const checked = v.vehicle_id === vehicleId;
                const inputId = `vehicle-${v.vehicle_id}`;
                return (
                  <label
                    key={v.vehicle_id}
                    htmlFor={inputId}
                    className={`group flex cursor-pointer flex-col overflow-hidden rounded border ${checked ? "border-amber-400 bg-zinc-900" : "border-zinc-700 hover:border-zinc-500"}`}
                  >
                    <span className={`block border-b px-3 pb-1 pt-3 ${checked ? "border-amber-400/40 bg-gradient-to-b from-zinc-600 to-zinc-800" : "border-zinc-800 bg-gradient-to-b from-zinc-700 to-zinc-800"}`}>
                      <PixelArtCar
                        vehicleId={v.vehicle_id}
                        className="mx-auto block h-auto w-full max-w-72 transition-transform motion-safe:group-hover:-translate-y-0.5"
                      />
                    </span>
                    <span className="flex gap-3 p-3">
                      <input
                        id={inputId}
                        type="radio"
                        name="vehicle"
                        value={v.vehicle_id}
                        checked={checked}
                        onChange={() => chooseVehicle(v)}
                        className="mt-1 accent-amber-400"
                      />
                      <span>
                        <span className="block font-semibold">
                          {v.display_name}
                          {v.validation_status !== "validated" && (
                            <span className="ml-2 rounded bg-zinc-700 px-1.5 text-xs font-normal text-zinc-100">rascunho</span>
                          )}
                        </span>
                        <span className="block text-sm text-zinc-300">{v.architecture_note}</span>
                        <span className="block text-xs text-zinc-300">
                          {v.n_cyl} cil. · {(v.displacement_cc / 1000).toFixed(1)} L · {INDUCTION_LABEL[v.induction] ?? v.induction} ·{" "}
                          {Math.round(v.rated.peak_power_whp)} whp
                        </span>
                      </span>
                    </span>
                  </label>
                );
              })}
            </div>
          </fieldset>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div className="text-sm">
              <label className="block">
                <span className="font-semibold">Perfil de ECU</span>
                <select
                  value={scenario ? "" : profileId}
                  onChange={(e) => setProfileId(e.target.value)}
                  disabled={scenario !== null}
                  aria-describedby={scenario ? "profile-from-scenario" : undefined}
                  className="mt-1 block w-full rounded border border-zinc-600 bg-zinc-950 px-2 py-1.5 disabled:opacity-60"
                >
                  {scenario && <option value="">Definido pelo cenário</option>}
                  {profiles.map((p) => (
                    <option key={p.profile_id} value={p.profile_id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </label>
              {scenario && (
                <p id="profile-from-scenario" className="mt-1 text-xs text-zinc-300">
                  O cenário define o perfil de ECU, o combustível e a calibração iniciais.
                </p>
              )}
            </div>

            <label className="block text-sm">
              <span className="font-semibold">Cenário (opcional)</span>
              <select
                value={scenario?.scenario_id ?? ""}
                onChange={(e) => setScenarioId(e.target.value)}
                className="mt-1 block w-full rounded border border-zinc-600 bg-zinc-950 px-2 py-1.5"
              >
                <option value="">Nenhum (sessão livre)</option>
                {vehicleScenarios.map((s) => (
                  <option key={s.scenario_id} value={s.scenario_id}>
                    {s.title}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {scenario ? (
            <p className="text-sm text-zinc-300">Com cenário, o carro entra de série: a oficina vale só para sessões livres.</p>
          ) : (
            <StageBuilder api={api} vehicleId={vehicleId} value={stage} onChange={setStage} disabled={busy} />
          )}

          {!target && (
            <p role="alert" className="rounded border border-amber-400 p-3 text-sm">
              A bancada e a ECU estão desativadas nesta instalação (VITE_FEATURE_DYNO_COCKPIT, VITE_FEATURE_ECU_TUNING).
            </p>
          )}
          {submitError && (
            <div role="alert" className="rounded border border-red-500 p-3 text-sm">
              <p>{submitError.text}</p>
              <p className="mt-1 font-mono text-xs text-zinc-300">{submitError.code}</p>
              {activeSession && target && (
                <div className="mt-3 flex flex-wrap gap-2">
                  <Link
                    to={target(activeSession)}
                    onClick={() => setActiveSessionId(activeSession)}
                    className="rounded border border-amber-400 px-3 py-1.5 text-amber-200 hover:bg-zinc-800"
                  >
                    Retomar sessão ativa
                  </Link>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void closeActiveSession(activeSession)}
                    className="rounded border border-red-400 px-3 py-1.5 text-red-200 hover:bg-red-950 disabled:opacity-60"
                  >
                    Encerrar sessão ativa
                  </button>
                </div>
              )}
            </div>
          )}

          <button
            type="submit"
            disabled={busy || !target || !vehicleId}
            className="w-full rounded bg-amber-500 px-4 py-2 font-semibold sm:w-auto text-zinc-950 hover:bg-amber-400 disabled:opacity-60"
          >
            {busy ? "A criar…" : scenario ? "Iniciar tentativa" : "Criar sessão"}
          </button>
        </form>
      )}
    </section>
  );
}
