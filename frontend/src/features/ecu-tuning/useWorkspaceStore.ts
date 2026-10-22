/**
 * Cria a `WorkspaceStore` da sessão uma vez, liga a telemetria e carrega a calibração.
 * Partilhada pelo workspace da ECU e pelo painel Live Tuning da bancada (feature 002, D-10).
 */
import { useEffect, useState } from "react";

import { WorkspaceStore, type WorkspaceDeps } from "./workspaceStore";

export function useWorkspaceStore(sessionId: string, deps: WorkspaceDeps): WorkspaceStore {
  const [store] = useState(() => new WorkspaceStore(sessionId, deps));
  useEffect(() => {
    const stop = store.start();
    void store.load();
    return stop;
  }, [store]);
  return store;
}
