/**
 * Página `/sessions/:sessionId/ecu` (tuning RF-01; rota lazy fixa de `app/routes.tsx`).
 * Atrás da flag `VITE_FEATURE_ECU_TUNING` (padrão ligada; `"false"`/`"0"` desliga, §13 Rollout).
 */
import { useNavigate, useParams } from "react-router-dom";

import { ecuApi } from "./api";
import { EcuWorkspace } from "./EcuWorkspace";
import type { WorkspaceDeps } from "./workspaceStore";

export function ecuTuningEnabled(flag: string | undefined = import.meta.env.VITE_FEATURE_ECU_TUNING as string | undefined): boolean {
  return !(flag !== undefined && ["false", "0", "off"].includes(flag.trim().toLowerCase()));
}

export function EcuWorkspaceView({ sessionId, deps }: { sessionId: string; deps?: Partial<WorkspaceDeps> }) {
  const navigate = useNavigate();
  return (
    <EcuWorkspace
      key={sessionId}
      sessionId={sessionId}
      deps={{ api: ecuApi, ...deps }}
      onOpenSession={(id) => void navigate(`/sessions/${encodeURIComponent(id)}/ecu`)}
    />
  );
}

export default function EcuWorkspacePage() {
  const { sessionId } = useParams();
  if (!ecuTuningEnabled()) {
    return (
      <p role="status" className="p-4 text-sm text-zinc-300">
        O editor de ECU está desativado nesta instalação (VITE_FEATURE_ECU_TUNING).
      </p>
    );
  }
  if (!sessionId) return <p role="alert">Sessão não indicada.</p>;
  return <EcuWorkspaceView sessionId={sessionId} />;
}
