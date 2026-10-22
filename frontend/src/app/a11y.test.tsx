/* eslint-disable @typescript-eslint/require-await -- mocks assíncronos */
/**
 * Auditoria axe-core por tela principal (cockpit RNF-06, tuning G-05, scenarios RF-24):
 * 0 violações WCAG 2.x A/AA na casca + tela inicial, na bancada (com o painel da tentativa),
 * no workspace da ECU, na lista de cenários, no briefing, no progresso da tentativa,
 * nos perfis e no painel do instrutor.
 */
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, it, vi } from "vitest";

import { DynoCockpitView } from "@/features/dyno-cockpit/DynoCockpitPage";
import { fakeAudioFactory, FakeWebSocket, installCanvasMock } from "@/features/dyno-cockpit/test-utils/mocks";
import { makeApi as makeCockpitApi, SESSION_ID } from "@/features/dyno-cockpit/test-utils/harness";
import { makeApi as makeEcuApi } from "@/features/ecu-tuning/test-utils/fixtures";
import { renderWorkspace } from "@/features/ecu-tuning/test-utils/harness";
import { ScenariosApiContext, setActiveProfileId } from "@/features/scenarios/api";
import ScenariosPage from "@/features/scenarios/ScenariosPage";
import { attempt, INSTRUCTOR, makeApi as makeScenariosApi } from "@/features/scenarios/test-utils/fixtures";
import { expectNoAxeViolations } from "@/test/axe";

import { App } from "./App";
import { HomePage } from "./HomePage";
import { ECU_PROFILES, makeHomeApi, VEHICLES } from "./test-fixtures";

vi.mock("uplot", () => import("@/features/dyno-cockpit/test-utils/uplotMock"));

let canvas: ReturnType<typeof installCanvasMock>;
beforeEach(() => {
  canvas = installCanvasMock({ ctx2d: true });
  localStorage.clear();
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 1920 });
  Object.defineProperty(navigator, "language", { configurable: true, value: "pt-BR" });
});
afterEach(() => {
  canvas.spy.mockRestore();
  vi.unstubAllGlobals();
});

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function renderScenarios(path: string, api = makeScenariosApi()) {
  return render(
    <ScenariosApiContext.Provider value={api}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/scenarios/*" element={<ScenariosPage />} />
          <Route path="/attempts/*" element={<ScenariosPage />} />
        </Routes>
      </MemoryRouter>
    </ScenariosApiContext.Provider>,
  );
}

describe("acessibilidade axe (0 violações A/AA)", () => {
  it("casca da aplicação com a tela inicial", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>((input) => {
        const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
        if (url.includes("/vehicles")) return Promise.resolve(json({ catalog_version: "1", catalog_sha256: "b".repeat(64), items: VEHICLES }));
        if (url.includes("/ecu-profiles")) return Promise.resolve(json(ECU_PROFILES));
        if (url.includes("/scenarios")) return Promise.resolve(json([]));
        return Promise.resolve(
          json({
            app_version: "0.1.0",
            api_version: "v1",
            ws_envelope_version: 1,
            package_format_version: 1,
            datalog_format_version: 1,
            alembic_head: "0007_scenarios_base",
            error_catalog_sha256: "a".repeat(64),
            python_version: "3.12.10",
          }),
        );
      }),
    );
    localStorage.setItem("simremap.activeSessionId", SESSION_ID);
    const { container } = render(
      <MemoryRouter initialEntries={["/"]}>
        <App versionRetryMs={0} />
      </MemoryRouter>,
    );
    await screen.findByRole("radio", { name: /Hatch 2.0 Turbo GDI/ });
    await expectNoAxeViolations(container);
  });

  it("tela inicial com cenário selecionado e erro de criação", async () => {
    const { container } = render(
      <MemoryRouter>
        <HomePage api={makeHomeApi()} flags={{ dynoCockpit: false, ecuTuning: false }} />
      </MemoryRouter>,
    );
    await screen.findByRole("group", { name: "Carro" });
    await expectNoAxeViolations(container);
  });

  it("bancada (DynoCockpitPage) com o painel lateral da tentativa", async () => {
    const api = makeCockpitApi({
      getSession: vi.fn(async () => ({ session_id: SESSION_ID, vehicle_id: "hatch-20t-gdi", profile_id: "oem-stage", fuel_id: "e27", state: "ready", engine_locked: false, attempt_id: "att-1" })),
    });
    const scenarios = makeScenariosApi({ getAttempt: vi.fn(() => Promise.resolve(attempt({ session_id: SESSION_ID }))) });
    FakeWebSocket.reset();
    const { container } = render(
      <ScenariosApiContext.Provider value={scenarios}>
        <MemoryRouter>
          <DynoCockpitView
            sessionId={SESSION_ID}
            deps={{ api, createWebSocket: (url) => new FakeWebSocket(url), createAudioContext: fakeAudioFactory, storage: null, wsOrigin: "http://localhost" }}
          />
        </MemoryRouter>
      </ScenariosApiContext.Provider>,
    );
    await screen.findByTestId("vehicle-name");
    await screen.findByRole("heading", { name: "Stage 1 OEM" });
    await expectNoAxeViolations(container);
  });

  it("workspace da ECU (EcuWorkspacePage)", async () => {
    const { container } = renderWorkspace(makeEcuApi());
    await screen.findByTestId("workspace-profile");
    await expectNoAxeViolations(container);
  });

  it("lista de cenários", async () => {
    const { container } = renderScenarios("/scenarios");
    await screen.findByRole("link", { name: "Stage 1 OEM" });
    await expectNoAxeViolations(container);
  });

  it("briefing do cenário", async () => {
    const { container } = renderScenarios("/scenarios/stage1-oem");
    await screen.findByRole("button", { name: /Iniciar/ });
    await expectNoAxeViolations(container);
  });

  it("progresso da tentativa", async () => {
    const { container } = renderScenarios("/attempts/att-1");
    await screen.findByText("Critérios (provisório)");
    await expectNoAxeViolations(container);
  });

  it("perfis da estação", async () => {
    const { container } = renderScenarios("/scenarios/profiles");
    await screen.findByRole("heading", { name: "Perfis desta estação" });
    await screen.findByText("lucas_turbo");
    await expectNoAxeViolations(container);
  });

  it("painel do instrutor", async () => {
    setActiveProfileId(INSTRUCTOR.profile_id);
    const { container } = renderScenarios("/scenarios/instructor");
    await screen.findByRole("heading", { name: "Painel do instrutor" });
    await expectNoAxeViolations(container);
  });
});
