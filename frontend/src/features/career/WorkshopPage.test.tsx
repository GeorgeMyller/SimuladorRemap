/** 002 T055 (RF-26): página "Oficina (Carreira)": ordens, aceitar, liquidar e erros. */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getActiveSessionId } from "@/app/activeSession";
import { selectProfile } from "@/features/scenarios/useActiveProfile";
import { ApiProblem } from "@/lib/api";

import type { CareerApi } from "./api";
import { formatBrl, formatBrlDelta, type CareerJob, type CareerProfile, type WorkOrder } from "./types";
import WorkshopPage from "./WorkshopPage";

const PROFILE_ID = "0f1e2d3c4b5a49687766554433221100";
const SESSION_ID = "9a8b7c6d5e4f40312a2b3c4d5e6f7081";
const NOW = "2026-10-18T10:00:00Z";

const PROFILE: CareerProfile = { profile_id: PROFILE_ID, balance_brl: 500_000, reputation: 50, created_at: NOW, updated_at: NOW };

const ORDERS: WorkOrder[] = [
  { order_id: "stage1-diario-seguro", title: "Stage 1 diário seguro", client: "Marina", briefing: "Uso diário.", scenario_id: "stage1-oem", payout_brl: 120_000, engine_cost_brl: 900_000, min_reputation: 0 },
  { order_id: "swap-standalone", title: "Swap standalone", client: "Clássicos do Vale", briefing: "Setup base.", scenario_id: "standalone-swap", payout_brl: 450_000, engine_cost_brl: 1_500_000, min_reputation: 60 },
];

function job(over: Partial<CareerJob> = {}): CareerJob {
  return {
    job_id: "11111111111141118111111111111111",
    profile_id: PROFILE_ID,
    order_id: "stage1-diario-seguro",
    scenario_id: "stage1-oem",
    attempt_id: "22222222222242228222222222222222",
    session_id: SESSION_ID,
    status: "accepted",
    payout_brl: 120_000,
    engine_cost_brl: 900_000,
    accepted_at: NOW,
    ...over,
  };
}

type FakeCareerApi = { [K in keyof CareerApi]: ReturnType<typeof vi.fn<CareerApi[K]>> };

function makeApi(over: Partial<CareerApi> = {}): FakeCareerApi {
  return {
    getProfile: vi.fn<CareerApi["getProfile"]>(() => Promise.resolve(PROFILE)),
    listOrders: vi.fn<CareerApi["listOrders"]>(() => Promise.resolve(ORDERS)),
    listJobs: vi.fn<CareerApi["listJobs"]>(() => Promise.resolve([])),
    acceptOrder: vi.fn<CareerApi["acceptOrder"]>(() => Promise.resolve(job())),
    settleJob: vi.fn<CareerApi["settleJob"]>(() => Promise.resolve(job({ status: "paid", delta_balance_brl: 120_000, delta_reputation: 5, settled_at: NOW }))),
    ...over,
  } as FakeCareerApi;
}

function Where() {
  const { pathname } = useLocation();
  return <p data-testid="where">{pathname}</p>;
}

function renderPage(api: CareerApi) {
  return render(
    <MemoryRouter initialEntries={["/workshop"]}>
      <Routes>
        <Route path="/workshop" element={<WorkshopPage api={api} />} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  );
}

const problem = (status: number, code: string) =>
  new ApiProblem({ type: `urn:simremap:problem:${code}`, title: code, status, detail: "detalhe", code, request_id: "r" });

beforeEach(() => {
  localStorage.clear();
  selectProfile(PROFILE_ID);
});

describe("WorkshopPage (002 T048)", () => {
  it("sem perfil de jogador pede para escolher um", () => {
    selectProfile(null);
    const api = makeApi();
    renderPage(api);
    expect(screen.getByRole("link", { name: "Escolher perfil" })).toHaveAttribute("href", "/scenarios/profiles");
    expect(api.getProfile).not.toHaveBeenCalled();
  });

  it("mostra saldo em R$, reputação e lista as ordens com bloqueio por reputação", async () => {
    const api = makeApi();
    renderPage(api);
    expect(formatBrl(500_000)).toMatch(/^R\$\s5\.000,00$/);
    expect(await screen.findByText(/^R\$\s5\.000,00$/)).toBeInTheDocument();
    expect(api.getProfile).toHaveBeenCalledWith(PROFILE_ID);
    expect(screen.getByRole("heading", { name: "Stage 1 diário seguro" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Aceitar a ordem Stage 1 diário seguro" })).toBeEnabled();
    const locked = screen.getByRole("button", { name: "Aceitar a ordem Swap standalone" });
    expect(locked).toBeDisabled();
    expect(locked).toHaveAccessibleDescription("Requer reputação 60 (a oficina tem 50).");
    expect(screen.getByText("Nenhum serviço em andamento. Aceite uma ordem abaixo.")).toBeInTheDocument();
    expect(screen.getByText("Ainda não há serviços liquidados.")).toBeInTheDocument();
    expect(screen.queryByText(PROFILE_ID)).not.toBeInTheDocument();
  });

  it("aceitar cria a tentativa e abre a bancada da sessão", async () => {
    const api = makeApi();
    renderPage(api);
    await userEvent.click(await screen.findByRole("button", { name: "Aceitar a ordem Stage 1 diário seguro" }));
    expect(api.acceptOrder).toHaveBeenCalledWith(PROFILE_ID, "stage1-diario-seguro");
    expect(await screen.findByTestId("where")).toHaveTextContent(`/sessions/${SESSION_ID}/dyno`);
    expect(getActiveSessionId()).toBe(SESSION_ID);
  });

  it("erro ao aceitar aparece com texto claro", async () => {
    const api = makeApi({ acceptOrder: vi.fn().mockRejectedValue(problem(409, "CAREER_REPUTATION_TOO_LOW")) });
    renderPage(api);
    await userEvent.click(await screen.findByRole("button", { name: "Aceitar a ordem Stage 1 diário seguro" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/reputação da oficina ainda não chega/);
  });

  it("liquidar mostra o delta de saldo e de reputação e recarrega", async () => {
    const paid = job({ status: "paid", delta_balance_brl: 120_000, delta_reputation: 5, settled_at: NOW });
    const api = makeApi({ listJobs: vi.fn().mockResolvedValueOnce([job()]).mockResolvedValue([paid]) });
    renderPage(api);
    const open = await screen.findByRole("button", { name: "Liquidar o serviço Stage 1 diário seguro" });
    expect(screen.getByRole("link", { name: "Abrir bancada" })).toHaveAttribute("href", `/sessions/${SESSION_ID}/dyno`);
    expect(screen.getByRole("button", { name: "Aceitar a ordem Stage 1 diário seguro" })).toBeDisabled();
    await userEvent.click(open);
    expect(api.settleJob).toHaveBeenCalledWith(paid.job_id);
    const banner = await screen.findByRole("status");
    expect(banner).toHaveTextContent(/Saldo \+R\$\s1\.200,00, reputação \+5/);
    const row = (await screen.findByRole("cell", { name: "Pago" })).closest("tr");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText(/^\+R\$\s1\.200,00$/)).toBeInTheDocument();
    expect(api.listJobs).toHaveBeenCalledTimes(2);
  });

  it("com um serviço em andamento todas as ordens ficam bloqueadas (um serviço aberto por perfil)", async () => {
    const third: WorkOrder = { ...ORDERS[0]!, order_id: "diagnostico-bomba-combustivel", title: "Diagnóstico bomba", scenario_id: "defect-fuel-pump", min_reputation: 20 };
    const api = makeApi({ listOrders: vi.fn().mockResolvedValue([...ORDERS, third]), listJobs: vi.fn().mockResolvedValue([job()]) });
    renderPage(api);
    const other = await screen.findByRole("button", { name: "Aceitar a ordem Diagnóstico bomba" });
    expect(other).toBeDisabled();
    expect(other).toHaveAccessibleDescription("Há um serviço em andamento: liquide-o antes de aceitar outra ordem.");
    expect(screen.getByRole("button", { name: "Aceitar a ordem Stage 1 diário seguro" })).toHaveAccessibleDescription(
      "Serviço em andamento: liquide-o antes de aceitar de novo.",
    );
  });

  it("409 CAREER_JOB_ALREADY_OPEN explica que o serviço aberto é da oficina", async () => {
    const api = makeApi({ acceptOrder: vi.fn().mockRejectedValue(problem(409, "CAREER_JOB_ALREADY_OPEN")) });
    renderPage(api);
    await userEvent.click(await screen.findByRole("button", { name: "Aceitar a ordem Stage 1 diário seguro" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Já há um serviço em andamento nesta oficina/);
  });

  it("liquidar com tentativa em andamento (409) explica o que falta", async () => {
    const api = makeApi({
      listJobs: vi.fn().mockResolvedValue([job()]),
      settleJob: vi.fn().mockRejectedValue(problem(409, "CAREER_ATTEMPT_NOT_FINISHED")),
    });
    renderPage(api);
    await userEvent.click(await screen.findByRole("button", { name: "Liquidar o serviço Stage 1 diário seguro" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/ainda não terminou/);
    expect(alert).toHaveTextContent("CAREER_ATTEMPT_NOT_FINISHED");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("quebra do motor aparece no histórico com débito", async () => {
    const broken = job({ status: "engine_broken", delta_balance_brl: -900_000, delta_reputation: -10, settled_at: NOW });
    renderPage(makeApi({ listJobs: vi.fn().mockResolvedValue([broken]) }));
    expect(await screen.findByText("Motor quebrado")).toBeInTheDocument();
    expect(formatBrlDelta(-900_000)).toMatch(/^-R\$\s9\.000,00$/);
    expect(screen.getByText(/^-R\$\s9\.000,00$/)).toBeInTheDocument();
    expect(screen.getByText("-10")).toBeInTheDocument();
  });

  it("perfil inexistente (404) volta à escolha de perfil; outro erro permite tentar de novo", async () => {
    const lost = makeApi({ getProfile: vi.fn().mockRejectedValue(problem(404, "PLAYER_PROFILE_NOT_FOUND")) });
    const { unmount } = renderPage(lost);
    expect(await screen.findByRole("link", { name: "Escolher perfil" })).toBeInTheDocument();
    unmount();

    const api = makeApi({ listOrders: vi.fn().mockRejectedValueOnce(problem(503, "DATABASE_UNAVAILABLE")).mockResolvedValue(ORDERS) });
    renderPage(api);
    expect(await screen.findByRole("alert")).toHaveTextContent("DATABASE_UNAVAILABLE");
    await userEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByRole("heading", { name: "Swap standalone" })).toBeInTheDocument();
  });
});
