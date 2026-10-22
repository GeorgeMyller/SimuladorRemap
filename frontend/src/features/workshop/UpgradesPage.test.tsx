/** Aba Upgrades: peças instaladas com a sessão viva (`PUT /sessions/{id}/upgrades`). */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { sessionFixture, UPGRADE_CATALOG, vehicleCompat } from "@/app/test-fixtures";
import { ApiProblem } from "@/lib/api";

import type { SessionUpgradesApi, SimulationSession } from "./api";
import { UpgradesView } from "./UpgradesPage";

function makeApi(session: SimulationSession, over: Partial<SessionUpgradesApi> = {}) {
  return {
    listUpgrades: vi.fn<SessionUpgradesApi["listUpgrades"]>(() => Promise.resolve(UPGRADE_CATALOG)),
    getVehicleCompat: vi.fn<SessionUpgradesApi["getVehicleCompat"]>((id) => Promise.resolve(vehicleCompat(id))),
    getSession: vi.fn<SessionUpgradesApi["getSession"]>(() => Promise.resolve(session)),
    installUpgrades: vi.fn<SessionUpgradesApi["installUpgrades"]>((_, upgrades) => Promise.resolve({ ...session, upgrades })),
    ...over,
  };
}

function renderView(api: SessionUpgradesApi, sessionId = session.session_id) {
  return render(
    <MemoryRouter>
      <UpgradesView sessionId={sessionId} api={api} />
    </MemoryRouter>,
  );
}

const session = sessionFixture({ upgrades: { injectors: "high_flow" } });

describe("UpgradesView", () => {
  it("mostra as peças instaladas e instala a troca pendente na sessão viva", async () => {
    const api = makeApi(session);
    renderView(api);
    const injectors = await screen.findByRole("group", { name: "Bicos injetores" });
    expect(within(injectors).getByRole("radio", { name: /alta vazão/ })).toBeChecked();
    expect(screen.getByText("Nenhuma alteração pendente.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Instalar peças" })).toBeDisabled();

    await userEvent.click(within(screen.getByRole("group", { name: "Turbina" })).getByRole("radio", { name: /Turbina upgraded/ }));
    expect(within(screen.getByRole("list", { name: "Alterações pendentes" })).getByText(/Turbina: Série →/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Instalar peças" }));

    expect(api.installUpgrades).toHaveBeenCalledWith(session.session_id, {
      turbo: "upgraded",
      injectors: "high_flow",
      fuel_pump: "stock",
      intercooler: "stock",
      downpipe: "stock",
      internals: "stock",
    });
    const done = await screen.findByRole("status");
    expect(done).toHaveTextContent("Peças instaladas: Turbina.");
    expect(within(done).getByRole("link", { name: "Acertar na ECU" })).toHaveAttribute("href", `/sessions/${session.session_id}/ecu`);
    expect(screen.getByText("Nenhuma alteração pendente.")).toBeInTheDocument();
  });

  it("descartar volta às peças instaladas", async () => {
    renderView(makeApi(session));
    await userEvent.click(within(await screen.findByRole("group", { name: "Downpipe" })).getByRole("radio", { name: /alto fluxo/ }));
    await userEvent.click(screen.getByRole("button", { name: "Descartar" }));
    expect(screen.getByText("Nenhuma alteração pendente.")).toBeInTheDocument();
  });

  it("bloqueia a troca numa tentativa de cenário", async () => {
    renderView(makeApi(sessionFixture({ attempt_id: "att-1" })));
    expect(await screen.findByRole("note")).toHaveTextContent("tentativa de cenário");
    expect(within(screen.getByRole("group", { name: "Turbina" })).getByRole("radio", { name: /Turbina upgraded/ })).toBeDisabled();
  });

  it("mostra o erro da instalação com texto claro", async () => {
    const problem = new ApiProblem({ type: "urn:simremap:problem:RUN_IN_PROGRESS", title: "x", status: 409, detail: "x", code: "RUN_IN_PROGRESS", request_id: "r" });
    renderView(makeApi(session, { installUpgrades: vi.fn<SessionUpgradesApi["installUpgrades"]>(() => Promise.reject(problem)) }));
    await userEvent.click(within(await screen.findByRole("group", { name: "Turbina" })).getByRole("radio", { name: /Turbina upgraded/ }));
    await userEvent.click(screen.getByRole("button", { name: "Instalar peças" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("puxada em andamento");
  });
});
