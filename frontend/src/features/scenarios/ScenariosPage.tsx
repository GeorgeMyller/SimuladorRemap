/**
 * Página dos cenários de treino (training-scenarios RF-24, RF-25). Montada nas rotas fixas
 * `/scenarios/*` e `/attempts/*`, com sub-rotas internas:
 * `/scenarios` (lista), `/scenarios/profiles`, `/scenarios/instructor`, `/scenarios/:scenarioId`,
 * `/attempts/:attemptId` (progresso) e `/attempts/:attemptId/result`.
 */
import { NavLink, Route, Routes, useLocation, useParams } from "react-router-dom";

import { AttemptProgressPanel } from "./AttemptProgressPanel";
import { EvaluationResult } from "./EvaluationResult";
import { InstructorPanel } from "./InstructorPanel";
import { ProfilePicker, RoleBadge } from "./ProfilePicker";
import { ScenarioBriefing } from "./ScenarioBriefing";
import { ScenarioList } from "./ScenarioList";
import { useProfiles } from "./useActiveProfile";

function BriefingRoute() {
  const { scenarioId = "" } = useParams();
  return <ScenarioBriefing key={scenarioId} scenarioId={scenarioId} />;
}

function AttemptRoute() {
  const { attemptId = "" } = useParams();
  return <AttemptProgressPanel key={attemptId} attemptId={attemptId} />;
}

function ResultRoute() {
  const { attemptId = "" } = useParams();
  const { search } = useLocation();
  const raw = new URLSearchParams(search).get("submission");
  const submission = raw ? Number(raw) : undefined;
  return <EvaluationResult key={`${attemptId}-${raw ?? ""}`} attemptId={attemptId} {...(submission ? { submission } : {})} />;
}

function ScenariosNav() {
  const { active } = useProfiles();
  const link = ({ isActive }: { isActive: boolean }) => `rounded px-2 py-1 ${isActive ? "bg-zinc-700" : "hover:bg-zinc-800"}`;
  return (
    <nav aria-label="Cenários" className="mb-4 flex flex-wrap items-center gap-2 text-sm">
      <NavLink to="/scenarios" end className={link}>
        Cenários
      </NavLink>
      <NavLink to="/scenarios/profiles" className={link}>
        Perfis
      </NavLink>
      {active?.role === "instructor" && (
        <NavLink to="/scenarios/instructor" className={link}>
          Painel do instrutor
        </NavLink>
      )}
      <span className="ml-auto flex items-center gap-2">
        {active ? (
          <>
            Perfil ativo: <strong>{active.nickname}</strong> <RoleBadge role={active.role} />
          </>
        ) : (
          <NavLink to="/scenarios/profiles" className="text-amber-300 underline">
            Escolha um perfil
          </NavLink>
        )}
      </span>
    </nav>
  );
}

export default function ScenariosPage() {
  const { pathname } = useLocation();
  const attempts = pathname.startsWith("/attempts");
  return (
    <div className="p-4">
      <ScenariosNav />
      {attempts ? (
        <Routes>
          <Route path=":attemptId" element={<AttemptRoute />} />
          <Route path=":attemptId/result" element={<ResultRoute />} />
          <Route path="*" element={<p>Tentativa não encontrada.</p>} />
        </Routes>
      ) : (
        <Routes>
          <Route index element={<ScenarioList />} />
          <Route path="profiles" element={<ProfilePicker />} />
          <Route path="instructor" element={<InstructorPanel />} />
          <Route path=":scenarioId" element={<BriefingRoute />} />
        </Routes>
      )}
    </div>
  );
}
