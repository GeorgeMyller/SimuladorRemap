/* eslint-disable @typescript-eslint/require-await, @typescript-eslint/no-unsafe-assignment -- mocks assíncronos e matchers assimétricos do expect */
/** Workspace da ECU: carga do descritor e da calibração, estados, navegação, atalhos e seletores (tuning RF-01, RF-02, RF-13, RF-14, RF-20; EC-01, EC-02, EC-09). */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useParams } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import EcuWorkspacePage, { ecuTuningEnabled, EcuWorkspaceView } from "./EcuWorkspacePage";
import { ECU_SHORTCUTS } from "./ShortcutsDialog";
import { CAL_ID, DESCRIPTORS, makeApi, problem, SESSION_ID } from "./test-utils/fixtures";
import { renderWorkspace } from "./test-utils/harness";

beforeEach(() => localStorage.clear());
afterEach(() => vi.useRealTimers());

describe("carga do workspace (RF-01)", () => {
  it("com mocks 200 mostra o nome genérico do perfil e a primeira secção em ≤ 1,5 s", async () => {
    const api = makeApi();
    const t0 = performance.now();
    renderWorkspace(api);
    expect(screen.getByRole("status")).toHaveTextContent("A carregar");
    expect(await screen.findByTestId("workspace-profile")).toHaveTextContent("FT-Pro");
    expect(performance.now() - t0).toBeLessThan(1500);
    expect(api.getProfile).toHaveBeenCalledWith("ft-pro", "classic-20t-swap");
    expect(api.getCalibration).toHaveBeenCalledWith(CAL_ID, { includeVersions: true });
    expect(screen.getByRole("heading", { name: "Configuração base (setup guiado)" })).toBeInTheDocument();
    // o primeiro item disponível (base) abre o assistente; a navegação para a VE abre a grade
    fireEvent.click(document.querySelector('[data-nav-item="inj.ve"]')!);
    expect(screen.getByRole("grid", { name: /Mapa principal \(VE\)/ })).toBeInTheDocument();
    expect(screen.getByTestId("revision")).toHaveTextContent("6");
  });

  it("404 mostra o estado de erro com o code", async () => {
    renderWorkspace(makeApi({ getSession: vi.fn(async () => { throw problem(404, "SESSION_NOT_FOUND", {}, "Sessão não encontrada", "A sessão não existe."); }) }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Sessão não encontrada");
    expect(alert).toHaveTextContent("SESSION_NOT_FOUND");
    expect(within(alert).getByRole("button", { name: "Tentar de novo" })).toBeInTheDocument();
  });

  it("perfil sem navegação mostra o erro com o profile_id (EC-09)", async () => {
    renderWorkspace(makeApi({ getProfile: vi.fn(async () => ({ ...DESCRIPTORS["ft-pro"]!, navigation: [] })) }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Perfil sem navegação (ft-pro)");
  });

  it("estratégia: formulário grava com PUT e a versão sobe", async () => {
    const api = makeApi();
    renderWorkspace(api);
    await screen.findByTestId("workspace-profile");
    fireEvent.click(document.querySelector('[data-nav-item="drag.two_step"]')!);
    const form = screen.getByRole("form", { name: "Two-step" });
    fireEvent.change(within(form).getByLabelText(/Rotação de largada/), { target: { value: "4200" } });
    await act(async () => {
      fireEvent.click(within(form).getByRole("button", { name: "Gravar estratégia" }));
    });
    expect(api.putCalibration).toHaveBeenCalledWith(CAL_ID, expect.objectContaining({ base_version: 6, strategies: expect.objectContaining({ two_step: expect.objectContaining({ kind: "two_step", target_rpm: 4200 }) }) }));
    await waitFor(() => expect(screen.getByTestId("revision")).toHaveTextContent("7"));
  });

  it("trims por cilindro gravam com PATCH nas tabelas do cilindro", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const api = makeApi();
    renderWorkspace(api);
    await screen.findByTestId("workspace-profile");
    fireEvent.click(document.querySelector('[data-nav-item="corr.fuel_cyl.2"]')!);
    expect(screen.getByRole("grid", { name: /Combustível cil. 2/ })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Trim de combustível cilindro 1" }), { target: { value: "3" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Gravar correções" }));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });
    const tables = api.patchTable.mock.calls.map((c) => c[1]);
    expect(tables).toContain("fuel_trim_cyl_1");
  });
});

describe("gravação e conflito (RF-13, EC-01, EC-02)", () => {
  it("falha de gravação mostra 'não gravado' com 'Tentar de novo'", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const api = makeApi({ patchTable: vi.fn(async () => { throw problem(503, "DATABASE_UNAVAILABLE"); }) });
    renderWorkspace(api, { retryDelaysMs: [10, 10, 10] });
    await screen.findByTestId("workspace-profile");
    fireEvent.click(document.querySelector('[data-nav-item="inj.ve"]')!);
    const grid = screen.getByRole("grid");
    fireEvent.keyDown(grid, { key: "Enter" });
    const input = screen.getByRole("textbox", { name: /Editar/ });
    fireEvent.change(input, { target: { value: "70" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByTestId("save-state")).toHaveTextContent("a gravar");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });
    expect(screen.getByTestId("save-state")).toHaveTextContent("não gravado");
    expect(api.patchTable).toHaveBeenCalledTimes(4);
    api.patchTable.mockImplementation(async (_c: string, tableId: string, body: { base_version: number }) => ({ version: body.base_version + 1, content_hash: "c", table: (await makeApi().getCalibration("x")).tables[tableId]! }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(screen.getByTestId("save-state")).toHaveTextContent("gravado (revisão 7)");
  });

  it("409 abre o diálogo 'Recarregar' ou 'Sobrescrever'", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const api = makeApi({ patchTable: vi.fn(async () => { throw problem(409, "CALIBRATION_VERSION_CONFLICT", { latest_version: 8 }); }) });
    renderWorkspace(api);
    await screen.findByTestId("workspace-profile");
    fireEvent.click(document.querySelector('[data-nav-item="inj.ve"]')!);
    fireEvent.keyDown(screen.getByRole("grid"), { key: "5" });
    fireEvent.keyDown(screen.getByRole("textbox", { name: /Editar/ }), { key: "Enter" });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });
    const dialog = await screen.findByRole("dialog", { name: "Conflito de versão" });
    expect(dialog).toHaveTextContent("versão 8");
    expect(within(dialog).getByRole("button", { name: "Recarregar" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Sobrescrever com as minhas alterações" })).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "Recarregar" }));
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("atalhos globais (RF-20)", () => {
  it("'?' abre o diálogo com todos os atalhos documentados", async () => {
    renderWorkspace();
    await screen.findByTestId("workspace-profile");
    fireEvent.keyDown(screen.getByTestId("workspace-profile"), { key: "?" });
    const dialog = screen.getByRole("dialog", { name: "Atalhos do editor de ECU" });
    for (const s of ECU_SHORTCUTS) expect(within(dialog).getByText(s.keys)).toBeInTheDocument();
    for (const k of ["Ctrl/Cmd + S", "Ctrl/Cmd + Enter", "F3", "I / Shift + I", "PageUp / PageDown"]) expect(dialog.textContent).toContain(k);
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("Ctrl/Cmd+S salva versão com o nome; Ctrl/Cmd+Enter aplica à sessão", async () => {
    const api = makeApi();
    renderWorkspace(api);
    await screen.findByTestId("workspace-profile");
    fireEvent.change(screen.getByLabelText("Nome da versão"), { target: { value: "VE +3 % topo" } });
    fireEvent.click(document.querySelector('[data-nav-item="inj.ve"]')!);
    const grid = screen.getByRole("grid");
    await act(async () => {
      fireEvent.keyDown(grid, { key: "s", ctrlKey: true });
    });
    expect(api.putCalibration).toHaveBeenCalledWith(CAL_ID, expect.objectContaining({ metadata: expect.objectContaining({ change_summary: "VE +3 % topo" }) }));
    await act(async () => {
      fireEvent.keyDown(grid, { key: "Enter", metaKey: true });
    });
    expect(api.applyToSession).toHaveBeenCalledWith(SESSION_ID, expect.objectContaining({ calibration_id: CAL_ID, version: 7 }));
  });
});

describe("seletor dos 4 carros (GET /vehicles?include_drafts=true)", () => {
  function Probe() {
    const { sessionId } = useParams();
    return <p data-testid="opened">{sessionId}</p>;
  }

  it("lista os 4 carros e trocar cria a sessão nova e navega", async () => {
    const api = makeApi();
    render(
      <MemoryRouter initialEntries={[`/sessions/${SESSION_ID}/ecu`]}>
        <Routes>
          <Route path={`/sessions/${SESSION_ID}/ecu`} element={<EcuWorkspaceView sessionId={SESSION_ID} deps={{ api, storage: localStorage, telemetry: false }} />} />
          <Route path="/sessions/:sessionId/ecu" element={<Probe />} />
        </Routes>
      </MemoryRouter>,
    );
    await screen.findByTestId("workspace-profile");
    const select = await screen.findByRole("combobox", { name: "Carro" });
    await waitFor(() => expect(within(select).getAllByRole("option")).toHaveLength(4));
    expect(within(select).getByRole("option", { name: /Muscle V8 compressor \(rascunho\)/ })).toBeInTheDocument();
    await act(async () => {
      fireEvent.change(select, { target: { value: "hatch-20t-gdi" } });
    });
    expect(api.createSession).toHaveBeenCalledWith({ vehicle_id: "hatch-20t-gdi", profile_id: "oem-stage" });
    expect(await screen.findByTestId("opened")).toHaveTextContent("b".repeat(32));
  });

  it("capacidade cheia oferece fechar a sessão atual", async () => {
    const createSession = vi.fn().mockRejectedValueOnce(problem(409, "SIM_CAPACITY_EXCEEDED")).mockResolvedValue({ session_id: "c".repeat(32) });
    const api = makeApi({ createSession });
    renderWorkspace(api);
    await screen.findByTestId("workspace-profile");
    const select = screen.getByRole("combobox", { name: "Carro" });
    await waitFor(() => expect(within(select).getAllByRole("option")).toHaveLength(4));
    await act(async () => {
      fireEvent.change(select, { target: { value: "coupe-30t-i6" } });
    });
    await act(async () => {
      fireEvent.click(await screen.findByRole("button", { name: /Fechar a sessão atual/ }));
    });
    expect(api.deleteSession).toHaveBeenCalledWith(SESSION_ID);
    expect(createSession).toHaveBeenCalledTimes(2);
  });
});

describe("página e flag VITE_FEATURE_ECU_TUNING", () => {
  it("flag ligada por padrão; 'false' desliga", () => {
    expect(ecuTuningEnabled(undefined)).toBe(true);
    expect(ecuTuningEnabled("true")).toBe(true);
    expect(ecuTuningEnabled("false")).toBe(false);
    expect(ecuTuningEnabled("0")).toBe(false);
  });

  it("export default lê o :sessionId da rota", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({ type: "x", title: "Sessão não encontrada", status: 404, detail: "não existe", code: "SESSION_NOT_FOUND", request_id: "r" }), { status: 404, headers: { "Content-Type": "application/problem+json" } }))));
    render(
      <MemoryRouter initialEntries={[`/sessions/${SESSION_ID}/ecu`]}>
        <Routes>
          <Route path="/sessions/:sessionId/ecu" element={<EcuWorkspacePage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText("SESSION_NOT_FOUND")).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls[0]![0]).toBe(`/api/v1/sessions/${SESSION_ID}`);
    vi.unstubAllGlobals();
  });
});
