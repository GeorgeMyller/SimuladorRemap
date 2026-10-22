import { Suspense, useMemo } from "react";
import { NavLink, useRoutes } from "react-router-dom";

import { useActiveSessionId } from "./activeSession";
import { readFeatureFlags, type FeatureFlags } from "./flags";
import { dynoPath, ecuPath, ROUTE_PATHS, upgradesPath } from "./paths";
import { buildRoutes } from "./routes";
import { useAppVersion } from "./useAppVersion";

const navClass = ({ isActive }: { isActive: boolean }) =>
  `rounded px-3 py-1.5 text-sm ${isActive ? "bg-zinc-800 text-amber-400" : "text-zinc-300 hover:text-white"}`;

export interface AppProps {
  /** Intervalo entre tentativas de `/api/v1/version` (testes usam 0). */
  versionRetryMs?: number;
  /** Flags de funcionalidade (padrão: `import.meta.env`). */
  flags?: FeatureFlags;
}

/** Casca da aplicação: navegação, estados de arranque e rodapé com a versão. */
export function App({ versionRetryMs, flags }: AppProps) {
  const { state, retry } = useAppVersion(versionRetryMs);
  const features = useMemo(() => flags ?? readFeatureFlags(), [flags]);
  const routes = useMemo(() => buildRoutes(features), [features]);
  const element = useRoutes(routes);
  const sessionId = useActiveSessionId();

  return (
    <div className="flex min-h-screen flex-col bg-zinc-950 text-zinc-100">
      <header className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-zinc-800 px-4 py-3 sm:px-6">
        <span className="font-semibold tracking-wide">SimuladorRemap</span>
        <nav aria-label="Navegação principal" className="flex flex-wrap gap-2">
          <NavLink to="/" end className={navClass}>
            Início
          </NavLink>
          {sessionId && features.dynoCockpit && (
            <NavLink to={dynoPath(sessionId)} className={navClass}>
              Bancada
            </NavLink>
          )}
          {sessionId && features.ecuTuning && (
            <NavLink to={ecuPath(sessionId)} className={navClass}>
              ECU
            </NavLink>
          )}
          {sessionId && (
            <NavLink to={upgradesPath(sessionId)} className={navClass}>
              Upgrades
            </NavLink>
          )}
          <NavLink to="/scenarios" className={navClass}>
            Cenários
          </NavLink>
          <NavLink to={ROUTE_PATHS.workshop} className={navClass}>
            Oficina (Carreira)
          </NavLink>
        </nav>
        {sessionId && (
          <span className="ml-auto text-xs text-zinc-400">
            Sessão <span className="font-mono text-zinc-200">{sessionId.slice(0, 8)}</span>
          </span>
        )}
      </header>

      <main className="min-w-0 flex-1 px-4 py-4 sm:px-6">
        {state.status === "loading" && (
          <div role="status" className="py-16 text-center text-zinc-400">
            A iniciar o simulador
          </div>
        )}
        {state.status === "error" && (
          <div role="alert" className="py-16 text-center">
            <p className="text-lg font-semibold">Servidor indisponível</p>
            <p className="mt-2 font-mono text-sm text-zinc-400">{state.code}</p>
            <button
              type="button"
              onClick={retry}
              className="mt-4 rounded bg-amber-500 px-4 py-2 font-medium text-zinc-950 hover:bg-amber-400"
            >
              Tentar de novo
            </button>
          </div>
        )}
        {state.status === "ready" && (
          <Suspense fallback={<div role="status">A carregar…</div>}>{element}</Suspense>
        )}
      </main>

      <footer className="border-t border-zinc-800 px-6 py-2 text-xs text-zinc-400">
        {state.status === "ready" ? `v${state.version.app_version}` : "SimuladorRemap"}
      </footer>
    </div>
  );
}
