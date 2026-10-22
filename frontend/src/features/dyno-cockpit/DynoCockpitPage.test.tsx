/* eslint-disable @typescript-eslint/require-await -- mocks assíncronos */
/** T360 — DynoCockpitPage: carregamento, estados, subscrição por painel, perda, reconexão e áudio (RF-01, RF-02, RF-04, RF-05, RF-19, EC-11, EC-15). */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import DynoCockpitPage from "./DynoCockpitPage";
import { FakeAudioContext, FakeWebSocket, frameEnvelope, installCanvasMock } from "./test-utils/mocks";
import { makeApi, notFound, openSocket, renderCockpit, runFixture, SESSION_ID } from "./test-utils/harness";
import { FakeUPlot } from "./test-utils/uplotMock";

vi.mock("uplot", () => import("./test-utils/uplotMock"));

let canvas: ReturnType<typeof installCanvasMock>;
beforeEach(() => {
  canvas = installCanvasMock({ ctx2d: true });
  FakeUPlot.reset();
  localStorage.clear();
});
afterEach(() => canvas.spy.mockRestore());

const subscribes = (ws: FakeWebSocket) => ws.sentMessages().filter((m) => m.type === "control.subscribe");

describe("DynoCockpitPage", () => {
  it("com mocks 200 mostra veículo, perfil ECU ativo e o estado vazio em ≤ 1 s", async () => {
    const t0 = performance.now();
    const { api } = await renderCockpit();
    expect(performance.now() - t0).toBeLessThan(1000);
    expect(screen.getByTestId("vehicle-name")).toHaveTextContent("Hatch 2.0 Turbo GDI");
    expect(screen.getByTestId("profile-name")).toHaveTextContent("OEM-Stage");
    expect(screen.getByText("Nenhuma puxada ainda. Escolha um tipo e clique Iniciar.")).toBeInTheDocument();
    expect(api.getSession).toHaveBeenCalledWith(SESSION_ID);
    expect(api.getReferenceCurves).toHaveBeenCalledWith("hatch-20t-gdi");
    expect(FakeWebSocket.last().url).toBe(`ws://localhost/ws/v1/sessions/${SESSION_ID}/telemetry`);
  });

  it("estado de carregamento: 'Conectando à bancada' e controles indisponíveis", () => {
    const api = makeApi({ getSession: vi.fn(() => new Promise(() => undefined)) });
    render(
      <MemoryRouter>
        <DynoCockpitPageHarness api={api} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Conectando à bancada");
    expect(screen.queryByRole("button", { name: "Iniciar" })).toBeNull();
  });

  it("404 SESSION_NOT_FOUND mostra o estado de erro com o botão 'Voltar'", async () => {
    const api = makeApi({ getSession: vi.fn(async () => Promise.reject(notFound("SESSION_NOT_FOUND", "Sessão não encontrada"))) });
    render(
      <MemoryRouter>
        <DynoCockpitPageHarness api={api} />
      </MemoryRouter>,
    );
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("SESSION_NOT_FOUND");
    expect(screen.getByRole("link", { name: "Voltar" })).toHaveAttribute("href", "/");
  });

  it("rota real /sessions/:sessionId/dyno monta a página (export default)", () => {
    render(
      <MemoryRouter initialEntries={["/sessions/abc/dyno"]}>
        <Routes>
          <Route path="/sessions/:sessionId/dyno" element={<DynoCockpitPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { name: "Bancada de dinamômetro" })).toBeInTheDocument();
  });

  it("envia control.subscribe com os canais visíveis; ao recolher o espectrograma a próxima subscrição não tem espectro", async () => {
    await renderCockpit();
    const ws = openSocket();
    const first = subscribes(ws)[0]!;
    expect(first.payload.spectrum).toBe(true);
    expect(first.payload.channels).toEqual(expect.arrayContaining(["rpm", "power_kw", "torque_nm", "egt_c", "knock_sensor_v_cyl1", "knock_intensity_cyl4"]));
    fireEvent.click(screen.getByRole("button", { name: /Recolher painel inferior/ }));
    await waitFor(() => expect(subscribes(ws)).toHaveLength(2), { timeout: 1500 });
    const next = subscribes(ws)[1]!;
    expect(next.payload.spectrum).toBe(false);
    expect((next.payload.channels as string[]).some((c) => c.startsWith("knock_sensor_v") || c.startsWith("knock_intensity"))).toBe(false);
  });

  it("acende 'perda de frames' com perda > 2 % em 5 s", async () => {
    await renderCockpit();
    const ws = openSocket();
    act(() => {
      let fi = 0;
      for (let i = 1; i <= 50; i += 1) {
        fi += i % 10 === 0 ? 2 : 1;
        ws.receive(frameEnvelope(i, fi, { rpm: 3000 }));
      }
    });
    expect(await screen.findByTestId("frame-loss")).toHaveTextContent("perda de frames");
  });

  it("queda do WS mostra 'reconectando (1/10)'; fecho 4404 mostra 'telemetria indisponível' e 'Tentar de novo'", async () => {
    await renderCockpit();
    const ws = openSocket();
    act(() => ws.drop(1011));
    expect(await screen.findByText("reconectando (1/10)")).toBeInTheDocument();
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(2), { timeout: 1500 });
    const ws2 = FakeWebSocket.last();
    act(() => ws2.drop(4404, "SESSION_NOT_FOUND"));
    expect((await screen.findAllByText("telemetria indisponível")).length).toBeGreaterThan(0);
    fireEvent.click(screen.getAllByRole("button", { name: "Tentar de novo" })[0]!);
    expect(FakeWebSocket.instances.length).toBe(3);
  });

  it("envelope inválido é descartado e contado no diagnóstico", async () => {
    await renderCockpit();
    const ws = openSocket();
    act(() => {
      ws.receive({ ...frameEnvelope(1, 1, {}), v: 2 });
      ws.receive("{x");
    });
    fireEvent.keyDown(document.body, { key: "d" });
    await waitFor(() => expect(screen.getByRole("complementary", { name: "Diagnóstico" })).toHaveTextContent(/Envelopes inválidos\s*2/));
  });

  it("puxada concluída: busca o DynoRun e substitui a curva ao vivo; a puxada fica disponível para comparação", async () => {
    const api = makeApi();
    await renderCockpit(api);
    const ws = openSocket();
    await waitFor(() => expect(screen.getByRole("button", { name: "Iniciar" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Iniciar" }));
    await waitFor(() => expect(api.startRun).toHaveBeenCalledWith(SESSION_ID, expect.objectContaining({ run_type: "sweep_pull" })));
    act(() => ws.receive({ v: 1, type: "run.state", seq: 50, t_sim_s: 20, payload: { run_id: "r-01J9Z", state: "completed", previous_state: "coastdown" } }));
    await waitFor(() => expect(api.getRun).toHaveBeenCalledWith("r-01J9Z"));
    expect(await screen.findByText(/Puxada concluída: pico 220,0 whp/)).toBeInTheDocument();
    expect(screen.getByTestId("run-status")).toHaveTextContent("puxada concluída");
    expect(screen.getByRole("option", { name: /#1/ })).toBeInTheDocument();
  });

  it("run.state completed antes do DynoRun finalizado no REST: repete a leitura até ter o resumo (E2E T221)", async () => {
    let calls = 0;
    const api = makeApi({
      getRun: vi.fn(async (id: string) => {
        calls += 1;
        return calls === 1 ? runFixture(id, "coastdown", { summary: null, curve: [] }) : runFixture(id, "completed");
      }),
    });
    await renderCockpit(api);
    const ws = openSocket();
    await waitFor(() => expect(screen.getByRole("button", { name: "Iniciar" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Iniciar" }));
    await waitFor(() => expect(api.startRun).toHaveBeenCalled());
    act(() => ws.receive({ v: 1, type: "run.state", seq: 50, t_sim_s: 20, payload: { run_id: "r-01J9Z", state: "completed", previous_state: "coastdown" } }));
    expect(await screen.findByText(/Puxada concluída: pico 220,0 whp/)).toBeInTheDocument();
    expect(api.getRun).toHaveBeenCalledTimes(2);
  });

  it("sessão com motor bloqueado abre em 'motor destruído' e 409 ENGINE_DESTROYED não repete o POST", async () => {
    const api = makeApi({
      getSession: vi.fn(async () => ({ session_id: SESSION_ID, vehicle_id: "hatch-20t-gdi", profile_id: "oem-stage", state: "engine_locked", engine_locked: true, baseline_run_id: "r-base" })),
      getRun: vi.fn(async (id: string) => runFixture(id, "completed")),
    });
    await renderCockpit(api);
    expect(screen.getByTestId("run-status")).toHaveTextContent("motor destruído");
    expect(screen.getByRole("button", { name: "Restaurar motor" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Iniciar" })).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Puxada de comparação do gráfico" })).toHaveValue("r-base");
  });

  it("backend indisponível: banner e controles da puxada desativados (EC-15)", async () => {
    const api = makeApi({ getHealth: vi.fn(async () => Promise.reject(new Error("down"))) });
    await renderCockpit(api);
    openSocket();
    expect(await screen.findByText(/backend indisponível — nova tentativa/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Iniciar" })).toBeDisabled();
  });

  it("ecrã estreito (layout responsivo) mantém os gráficos montados e a subscrição completa", async () => {
    await renderCockpit();
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 390 });
    act(() => {
      window.dispatchEvent(new Event("resize"));
    });
    expect(screen.getByRole("figure", { name: /Potência e torque/ })).toBeInTheDocument();
    const ws = openSocket();
    await waitFor(() => expect((subscribes(ws).at(-1)?.payload.channels as string[] | undefined)?.length ?? 0).toBeGreaterThan(1), { timeout: 1500 });
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 1024 });
  });

  it("setas fora de campos não rolam a página na bancada", async () => {
    await renderCockpit();
    openSocket();
    await screen.findByRole("button", { name: "Iniciar" });
    expect(fireEvent.keyDown(document.body, { key: "ArrowDown" })).toBe(false);
    expect(fireEvent.keyDown(document.body, { key: "ArrowUp" })).toBe(false);
  });

  it("áudio: 'Ativar som' passa o AudioContext a running e o volume ajusta 0–100 %", async () => {
    FakeAudioContext.instances = [];
    await renderCockpit(makeApi(), localStorage);
    const btn = await screen.findByRole("button", { name: "Ativar som" });
    const ctx = FakeAudioContext.instances.at(-1)!;
    expect(ctx.state).toBe("suspended");
    fireEvent.click(btn);
    await waitFor(() => expect(ctx.state).toBe("running"));
    expect(await screen.findByRole("button", { name: "Som ligado" })).toHaveAttribute("aria-pressed", "false");
    fireEvent.change(screen.getByRole("slider", { name: "Volume" }), { target: { value: "25" } });
    await waitFor(() => expect((JSON.parse(localStorage.getItem("simremap.cockpit.prefs.v1")!) as CockpitPrefs).audio.volume).toBe(0.25));
  });
});

import { DynoCockpitView } from "./DynoCockpitPage";
import type { CockpitApi } from "./api";
import type { CockpitPrefs } from "./prefs";

function DynoCockpitPageHarness({ api }: { api: CockpitApi }) {
  return <DynoCockpitView sessionId={SESSION_ID} deps={{ api, createWebSocket: (u) => new FakeWebSocket(u), createAudioContext: null, storage: null, wsOrigin: "http://localhost" }} />;
}
