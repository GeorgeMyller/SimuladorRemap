/** T435 — tela inicial: escolha do carro, do perfil de ECU e do cenário opcional; criação da sessão. */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { ZodError } from "zod";

import { ApiProblem } from "@/lib/api";

import { ACTIVE_SESSION_KEY, getActiveSessionId } from "./activeSession";
import type { FeatureFlags } from "./flags";
import { HomePage } from "./HomePage";
import type { HomeApi } from "./homeApi";
import { makeHomeApi, NEW_SESSION_ID, VEHICLES } from "./test-fixtures";

const ALL_ON: FeatureFlags = { dynoCockpit: true, ecuTuning: true };

function Where() {
  const { pathname } = useLocation();
  return <p data-testid="where">{pathname}</p>;
}

function renderHome(api: HomeApi, flags: FeatureFlags = ALL_ON) {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<HomePage api={api} flags={flags} />} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  );
}

const problem = (status: number, code: string, detail: string) =>
  new ApiProblem({ type: `urn:simremap:problem:${code}`, title: code, status, detail, code, request_id: "r" });

beforeEach(() => localStorage.clear());

describe("HomePage (T435)", () => {
  it("lista os 4 carros, seleciona o primeiro com o perfil de série e marca rascunhos", async () => {
    renderHome(makeHomeApi());
    const group = await screen.findByRole("group", { name: "Carro" });
    const radios = within(group).getAllByRole("radio");
    expect(radios).toHaveLength(4);
    expect(within(group).getByRole("radio", { name: /Hatch 2.0 Turbo GDI/ })).toBeChecked();
    expect(within(group).getByText("rascunho")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Perfil de ECU" })).toHaveValue("oem-stage");
    expect(screen.getByText("Nenhuma sessão ativa. Escolha o carro e crie uma sessão de bancada.")).toBeInTheDocument();
    expect(screen.getByText(/8 cil\. · 6\.2 L · Compressor · 520 whp/)).toBeInTheDocument();
  });

  it("cria a sessão com vehicle_id e profile_id e navega para a cockpit", async () => {
    const api = makeHomeApi();
    renderHome(api);
    await userEvent.click(await screen.findByRole("radio", { name: /Coupé 3.0 Turbo I6/ }));
    const profile = screen.getByRole("combobox", { name: "Perfil de ECU" });
    expect(profile).toHaveValue("ft-pro");
    await userEvent.selectOptions(profile, "m1-race");
    await userEvent.click(screen.getByRole("button", { name: "Criar sessão" }));
    expect(api.createSession).toHaveBeenCalledWith({ vehicle_id: "coupe-30t-i6", profile_id: "m1-race" });
    expect(await screen.findByTestId("where")).toHaveTextContent(`/sessions/${NEW_SESSION_ID}/dyno`);
    expect(getActiveSessionId()).toBe(NEW_SESSION_ID);
  });

  it("com cenário inicia a tentativa (perfil definido pelo cenário) e abre a sessão criada", async () => {
    const api = makeHomeApi();
    renderHome(api);
    const scenario = await screen.findByRole("combobox", { name: "Cenário (opcional)" });
    const options = within(scenario).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["Nenhum (sessão livre)", "Stage 1 na ECU de série"]);
    await userEvent.selectOptions(scenario, "stage1-oem");
    expect(screen.getByRole("combobox", { name: "Perfil de ECU" })).toBeDisabled();
    expect(screen.getByText(/O cenário define o perfil de ECU/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Iniciar tentativa" }));
    expect(api.startAttempt).toHaveBeenCalledWith("stage1-oem");
    expect(api.createSession).not.toHaveBeenCalled();
    expect(await screen.findByTestId("where")).toHaveTextContent(`/sessions/${NEW_SESSION_ID}/dyno`);
  });

  it("trocar de carro limpa o cenário e filtra a lista pelo veículo", async () => {
    renderHome(makeHomeApi());
    const scenario = await screen.findByRole("combobox", { name: "Cenário (opcional)" });
    await userEvent.selectOptions(scenario, "stage1-oem");
    await userEvent.click(screen.getByRole("radio", { name: /Muscle V8/ }));
    expect(scenario).toHaveValue("");
    expect(within(scenario).getByRole("option", { name: "V8 no etanol" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Perfil de ECU" })).toHaveValue("ht-elite");
  });

  it("tentativa sem session_id abre o painel da tentativa", async () => {
    const api = makeHomeApi({ startAttempt: () => Promise.resolve({ attempt_id: "att-9", session_id: null }) });
    renderHome(api);
    await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Cenário (opcional)" }), "stage1-oem");
    await userEvent.click(screen.getByRole("button", { name: "Iniciar tentativa" }));
    expect(await screen.findByTestId("where")).toHaveTextContent("/attempts/att-9");
  });

  it("mostra o erro do servidor (ex.: SIM_CAPACITY_EXCEEDED) e permite nova tentativa", async () => {
    const api = makeHomeApi({ createSession: () => Promise.reject(problem(409, "SIM_CAPACITY_EXCEEDED", "Já existe uma sessão ativa.")) });
    renderHome(api);
    await userEvent.click(await screen.findByRole("button", { name: "Criar sessão" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Já existe uma sessão ativa.");
    expect(alert).toHaveTextContent("SIM_CAPACITY_EXCEEDED");
    expect(screen.getByRole("button", { name: "Criar sessão" })).toBeEnabled();
  });

  it("com sessão ativa, o erro de capacidade oferece retomar ou encerrar a sessão", async () => {
    localStorage.setItem(ACTIVE_SESSION_KEY, "abcdef0123456789");
    const api = makeHomeApi({ createSession: () => Promise.reject(problem(409, "SIM_CAPACITY_EXCEEDED", "Capacidade esgotada.")) });
    renderHome(api);
    await userEvent.click(await screen.findByRole("button", { name: "Criar sessão" }));
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByRole("link", { name: "Retomar sessão ativa" })).toHaveAttribute("href", "/sessions/abcdef0123456789/dyno");
    await userEvent.click(within(alert).getByRole("button", { name: "Encerrar sessão ativa" }));
    expect(api.closeSession).toHaveBeenCalledWith("abcdef0123456789");
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(getActiveSessionId()).toBeNull();
  });

  it("cada card de carro mostra a ilustração em pixel art", async () => {
    renderHome(makeHomeApi());
    const group = await screen.findByRole("group", { name: "Carro" });
    const sprites = [...group.querySelectorAll("svg[data-sprite]")].map((el) => el.getAttribute("data-sprite"));
    expect(sprites).toHaveLength(4);
    expect(new Set(sprites).size).toBe(4);
  });

  it("erro inesperado (não ApiProblem) aparece com UNEXPECTED_ERROR", async () => {
    renderHome(makeHomeApi({ createSession: () => Promise.reject(new Error("falhou")) }));
    await userEvent.click(await screen.findByRole("button", { name: "Criar sessão" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("UNEXPECTED_ERROR");
  });

  it("falha ao carregar o catálogo mostra o erro e 'Tentar de novo' recarrega", async () => {
    let fail = true;
    const api = makeHomeApi({
      listVehicles: () => (fail ? Promise.reject(problem(503, "CATALOG_UNAVAILABLE", "Catálogo indisponível.")) : Promise.resolve(VEHICLES)),
    });
    renderHome(api);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Catálogo indisponível.");
    expect(alert).toHaveTextContent("CATALOG_UNAVAILABLE");
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByRole("group", { name: "Carro" })).toBeInTheDocument();
  });

  it("sem cenários (feature desligada) mantém só a sessão livre", async () => {
    renderHome(makeHomeApi({ listScenarios: () => Promise.reject(problem(404, "NOT_FOUND", "x")) }));
    const scenario = await screen.findByRole("combobox", { name: "Cenário (opcional)" });
    expect(within(scenario).getAllByRole("option")).toHaveLength(1);
  });

  it("catálogo vazio mostra o aviso", async () => {
    renderHome(makeHomeApi({ listVehicles: () => Promise.resolve([]) }));
    expect(await screen.findByRole("alert")).toHaveTextContent("O catálogo não tem veículos disponíveis.");
  });

  it("com a cockpit desligada (VITE_FEATURE_DYNO_COCKPIT) navega para a ECU", async () => {
    renderHome(makeHomeApi(), { dynoCockpit: false, ecuTuning: true });
    await userEvent.click(await screen.findByRole("button", { name: "Criar sessão" }));
    expect(await screen.findByTestId("where")).toHaveTextContent(`/sessions/${NEW_SESSION_ID}/ecu`);
  });

  it("com bancada e ECU desligadas não permite criar sessão", async () => {
    renderHome(makeHomeApi(), { dynoCockpit: false, ecuTuning: false });
    expect(await screen.findByRole("alert")).toHaveTextContent("VITE_FEATURE_DYNO_COCKPIT");
    expect(screen.getByRole("button", { name: "Criar sessão" })).toBeDisabled();
  });

  it("com sessão ativa guardada oferece continuar na bancada ou abrir a ECU", async () => {
    localStorage.setItem(ACTIVE_SESSION_KEY, "abcdef0123456789abcdef0123456789");
    renderHome(makeHomeApi());
    expect(await screen.findByRole("link", { name: "continuar na bancada" })).toHaveAttribute("href", "/sessions/abcdef0123456789abcdef0123456789/dyno");
    expect(screen.getByRole("link", { name: "abrir a ECU" })).toHaveAttribute("href", "/sessions/abcdef0123456789abcdef0123456789/ecu");
    await waitFor(() => expect(screen.getByText("abcdef01")).toBeInTheDocument());
  });
});

describe("HomePage — resposta fora do contrato", () => {
  it("erro de validação zod vira UNEXPECTED_RESPONSE", async () => {
    renderHome(makeHomeApi({ listVehicles: () => Promise.reject(new ZodError([])) }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("UNEXPECTED_RESPONSE");
    expect(alert).toHaveTextContent("Resposta do servidor fora do contrato da API.");
  });
});
