/* eslint-disable @typescript-eslint/require-await -- mocks assíncronos */
/** T445 — painel lateral da tentativa na cockpit e abertura da puxada da evidência (`?run=&t=`). */
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ScenariosApiContext } from "@/features/scenarios/api";
import { attempt, makeApi as makeScenariosApi } from "@/features/scenarios/test-utils/fixtures";

import { DynoCockpitView, parseRunFocus, type RunFocus } from "./DynoCockpitPage";
import { fakeAudioFactory, FakeWebSocket, installCanvasMock } from "./test-utils/mocks";
import { makeApi, SESSION_ID } from "./test-utils/harness";
import { FakeUPlot } from "./test-utils/uplotMock";

vi.mock("uplot", () => import("./test-utils/uplotMock"));

let canvas: ReturnType<typeof installCanvasMock>;
beforeEach(() => {
  canvas = installCanvasMock({ ctx2d: true });
  FakeUPlot.reset();
  localStorage.clear();
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 1920 });
  Object.defineProperty(navigator, "language", { configurable: true, value: "pt-BR" });
});
afterEach(() => canvas.spy.mockRestore());

const sessionWithAttempt = { session_id: SESSION_ID, vehicle_id: "hatch-20t-gdi", profile_id: "oem-stage", fuel_id: "e27", state: "ready", active_run_id: null, baseline_run_id: null, engine_locked: false, attempt_id: "att-1" };

function renderView(api: ReturnType<typeof makeApi>, focus: RunFocus | null = null) {
  const getAttempt = vi.fn(() => Promise.resolve(attempt({ session_id: SESSION_ID })));
  const scenarios = makeScenariosApi({ getAttempt });
  FakeWebSocket.reset();
  const utils = render(
    <ScenariosApiContext.Provider value={scenarios}>
      <MemoryRouter initialEntries={[`/sessions/${SESSION_ID}/dyno`]}>
        <Routes>
          <Route
            path="*"
            element={
              <DynoCockpitView
                sessionId={SESSION_ID}
                focus={focus}
                deps={{ api, createWebSocket: (url) => new FakeWebSocket(url), createAudioContext: fakeAudioFactory, storage: null, wsOrigin: "http://localhost" }}
              />
            }
          />
        </Routes>
      </MemoryRouter>
    </ScenariosApiContext.Provider>,
  );
  return { ...utils, getAttempt };
}

describe("parseRunFocus", () => {
  it("lê run e t; t inválido ou ausente vira null; sem run devolve null", () => {
    expect(parseRunFocus(new URLSearchParams("run=r1&t=12.5"))).toEqual({ runId: "r1", t: 12.5 });
    expect(parseRunFocus(new URLSearchParams("run=r1&t=abc"))).toEqual({ runId: "r1", t: null });
    expect(parseRunFocus(new URLSearchParams("run=r1"))).toEqual({ runId: "r1", t: null });
    expect(parseRunFocus(new URLSearchParams("t=3"))).toBeNull();
  });
});

describe("AttemptProgressPanel na cockpit (T445)", () => {
  it("sessão com attempt_id mostra o painel lateral da tentativa", async () => {
    const api = makeApi({ getSession: vi.fn(async () => sessionWithAttempt) });
    const { getAttempt } = renderView(api);
    const sidebar = await screen.findByTestId("attempt-sidebar");
    expect(await within(sidebar).findByRole("heading", { name: "Stage 1 OEM" })).toBeInTheDocument();
    expect(getAttempt).toHaveBeenCalledWith("att-1");
    expect(within(sidebar).getByText("Critérios (provisório)")).toBeInTheDocument();
  });

  it("sessão sem attempt_id não mostra o painel", async () => {
    renderView(makeApi());
    await screen.findByTestId("vehicle-name");
    expect(screen.queryByTestId("attempt-sidebar")).not.toBeInTheDocument();
  });

  it("?run=&t= carrega a puxada como comparação, abre o datalogger e posiciona o cursor", async () => {
    const api = makeApi();
    renderView(api, { runId: "01JEVIDENCE00000000EVRN42", t: 7.25 });
    await screen.findByTestId("vehicle-name");
    await waitFor(() => expect(api.getRun).toHaveBeenCalledWith("01JEVIDENCE00000000EVRN42"));
    expect(await screen.findByTestId("chart-cursor")).toHaveTextContent("Cursor: 7,25 s");
    const select = screen.getByRole("combobox", { name: "Puxada de comparação do gráfico" });
    await waitFor(() => expect(select).toHaveValue("01JEVIDENCE00000000EVRN42"));
    expect(within(select).getByRole("option", { name: "Evidência EVRN42" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Datalogger/ })).toHaveAttribute("aria-selected", "true");
  });

  it("puxada da evidência indisponível continua listada (sem t não mexe no cursor)", async () => {
    const api = makeApi({ getRun: vi.fn(async () => Promise.reject(new Error("404"))) });
    renderView(api, { runId: "01JEVIDENCE00000000EVRN43", t: null });
    await screen.findByTestId("vehicle-name");
    const select = screen.getByRole("combobox", { name: "Puxada de comparação do gráfico" });
    await waitFor(() => expect(within(select).getByRole("option", { name: "Evidência EVRN43" })).toBeInTheDocument());
    expect(screen.queryByTestId("chart-cursor")).not.toBeInTheDocument();
  });
});
