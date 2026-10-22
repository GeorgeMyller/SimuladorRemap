/** Harness dos testes: store carregada com a API falsa e render dos editores/workspace. */
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { EcuWorkspaceView } from "../EcuWorkspacePage";
import { TableEditor2D } from "../TableEditor2D";
import { TableEditor3D } from "../TableEditor3D";
import { WorkspaceStore, type WorkspaceDeps } from "../workspaceStore";
import { makeApi, SESSION_ID, type FakeApi } from "./fixtures";

export async function loadedStore(api: FakeApi = makeApi(), deps: Partial<WorkspaceDeps> = {}): Promise<WorkspaceStore> {
  const store = new WorkspaceStore(SESSION_ID, { api, storage: localStorage, telemetry: false, debounceMs: 300, retryDelaysMs: [1000, 2000, 4000], ...deps });
  await store.load();
  return store;
}

export function renderTable(store: WorkspaceStore, tableId: string, title = tableId) {
  const t = store.getSnapshot().tables[tableId]!;
  const Editor = t.y ? TableEditor3D : TableEditor2D;
  const utils = render(<Editor store={store} tableId={tableId} title={title} />);
  return { ...utils, grid: screen.getByRole("grid") };
}

export function renderWorkspace(api: FakeApi = makeApi(), deps: Partial<WorkspaceDeps> = {}) {
  return render(
    <MemoryRouter initialEntries={[`/sessions/${SESSION_ID}/ecu`]}>
      <Routes>
        <Route path="/sessions/:sessionId/ecu" element={<EcuWorkspaceView sessionId={SESSION_ID} deps={{ api, storage: localStorage, telemetry: false, ...deps }} />} />
      </Routes>
    </MemoryRouter>,
  );
}

export function cellAt(row: number, col: number): HTMLElement {
  const el = document.querySelector<HTMLElement>(`[data-cell="${row},${col}"]`);
  if (!el) throw new Error(`célula ${row},${col} não montada`);
  return el;
}
