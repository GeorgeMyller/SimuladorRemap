/**
 * Rotas fixas do SPA. Cada feature mantém o caminho e o export default da sua página:
 * - `/` → HomePage (criação de sessão, T435)
 * - `/sessions/:sessionId/dyno` → features/dyno-cockpit/DynoCockpitPage (flag VITE_FEATURE_DYNO_COCKPIT)
 * - `/sessions/:sessionId/ecu`  → features/ecu-tuning/EcuWorkspacePage (flag VITE_FEATURE_ECU_TUNING, T437)
 * - `/sessions/:sessionId/upgrades` → features/workshop/UpgradesPage (peças com a sessão viva)
 * - `/scenarios/*` e `/attempts/*` → features/scenarios/ScenariosPage (sub-rotas internas: lista,
 *   briefing, perfis, painel do instrutor, tentativa e resultado; T444)
 * - `/workshop` → features/career/WorkshopPage ("Oficina (Carreira)", 002 T049)
 * - `/profiles` e `/instructor` → atalhos para `/scenarios/profiles` e `/scenarios/instructor`
 * Flag desligada: a rota cai na NotFoundPage. Todas as páginas são lazy (002 T053, RF-27): o
 * chunk inicial leva só a casca e a NotFoundPage.
 */
import { lazy } from "react";
import { Navigate, type RouteObject } from "react-router-dom";

import { readFeatureFlags, type FeatureFlags } from "./flags";
import { NotFoundPage } from "./NotFoundPage";
import { ROUTE_PATHS } from "./paths";

export { dynoPath, ecuPath, ROUTE_PATHS, upgradesPath } from "./paths";

const HomePage = lazy(() => import("./HomePage").then((m) => ({ default: m.HomePage })));
const DynoCockpitPage = lazy(() => import("../features/dyno-cockpit/DynoCockpitPage"));
const EcuWorkspacePage = lazy(() => import("../features/ecu-tuning/EcuWorkspacePage"));
const UpgradesPage = lazy(() => import("../features/workshop/UpgradesPage"));
const ScenariosPage = lazy(() => import("../features/scenarios/ScenariosPage"));
const WorkshopPage = lazy(() => import("../features/career/WorkshopPage"));

export function buildRoutes(flags: FeatureFlags = readFeatureFlags()): RouteObject[] {
  return [
    { path: ROUTE_PATHS.home, element: <HomePage flags={flags} /> },
    { path: ROUTE_PATHS.dyno, element: flags.dynoCockpit ? <DynoCockpitPage /> : <NotFoundPage /> },
    { path: ROUTE_PATHS.ecu, element: flags.ecuTuning ? <EcuWorkspacePage /> : <NotFoundPage /> },
    { path: ROUTE_PATHS.upgrades, element: <UpgradesPage /> },
    { path: ROUTE_PATHS.scenarios, element: <ScenariosPage /> },
    { path: ROUTE_PATHS.attempts, element: <ScenariosPage /> },
    { path: ROUTE_PATHS.workshop, element: <WorkshopPage /> },
    { path: ROUTE_PATHS.profiles, element: <Navigate to="/scenarios/profiles" replace /> },
    { path: ROUTE_PATHS.instructor, element: <Navigate to="/scenarios/instructor" replace /> },
    { path: "*", element: <NotFoundPage /> },
  ];
}
