import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AttemptProgressPanel } from "./AttemptProgressPanel";
import ScenariosPage from "./ScenariosPage";
import { attempt, makeApi, problem, renderWithApi, SESSION_ID, STAGE1, STUDENT, SUMMARIES } from "./test-utils/fixtures";
import { ACTIVE_PROFILE_KEY } from "./types";

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem(ACTIVE_PROFILE_KEY, STUDENT.profile_id);
});

describe("ScenarioList", () => {
  it("lista os cenários, filtra por tipo e veículo e mostra o selo de defeito oculto sem revelar qual", async () => {
    const listScenarios = vi.fn(() => Promise.resolve(SUMMARIES));
    renderWithApi(<ScenariosPage />, makeApi({ listScenarios }), "/scenarios", "/scenarios/*");
    expect(await screen.findByRole("link", { name: "Stage 1 OEM" })).toBeInTheDocument();
    expect(screen.getAllByRole("listitem").length).toBeGreaterThanOrEqual(4);
    const challenge = screen.getByRole("link", { name: "Bomba fraca" }).closest("li");
    expect(challenge).not.toBeNull();
    expect(within(challenge!).getByText("Defeito oculto")).toBeInTheDocument();
    expect(within(challenge!).getByText("Reprovado")).toBeInTheDocument();
    expect(screen.queryByText(/bomba de combustível/i)).toBeNull();

    await userEvent.selectOptions(screen.getByLabelText("Veículo"), "classic-20t-swap");
    expect(screen.getByRole("link", { name: "Swap standalone" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Stage 1 OEM" })).toBeNull();

    await userEvent.selectOptions(screen.getByLabelText("Tipo"), "challenge");
    await waitFor(() => expect(listScenarios).toHaveBeenLastCalledWith("challenge"));
  });

  it("mostra erro com code e permite tentar de novo", async () => {
    const listScenarios = vi.fn().mockRejectedValueOnce(problem(503, "DATABASE_UNAVAILABLE")).mockResolvedValue(SUMMARIES);
    renderWithApi(<ScenariosPage />, makeApi({ listScenarios }), "/scenarios", "/scenarios/*");
    expect(await screen.findByText("DATABASE_UNAVAILABLE")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByRole("link", { name: "Stage 1 OEM" })).toBeInTheDocument();
  });
});

describe("ScenarioBriefing", () => {
  it("mostra objetivos, critérios com limiar e unidade e inicia a tentativa", async () => {
    const startAttempt = vi.fn(() => Promise.resolve(attempt({ state: "preparing" })));
    renderWithApi(<ScenariosPage />, makeApi({ startAttempt }), "/scenarios/stage1-oem", "/scenarios/*");
    expect(await screen.findByRole("heading", { name: "Stage 1 OEM" })).toBeInTheDocument();
    expect(screen.getByText("+40 whp sobre a base")).toBeInTheDocument();
    expect(screen.getByText("≥ 40 whp")).toBeInTheDocument();
    expect(screen.getByText("≤ 950 °C")).toBeInTheDocument();
    expect(screen.getByText(/Perfil final permitido: oem-stage/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Iniciar tentativa" }));
    expect(startAttempt).toHaveBeenCalledWith("stage1-oem");
  });

  it("sem perfil ativo o botão fica desativado", async () => {
    localStorage.clear();
    renderWithApi(<ScenariosPage />, makeApi(), "/scenarios/stage1-oem", "/scenarios/*");
    expect(await screen.findByRole("button", { name: "Iniciar tentativa" })).toBeDisabled();
  });
});

describe("AttemptProgressPanel", () => {
  it("mostra estado, links da bancada e da ECU, critérios provisórios e puxadas classificadas", async () => {
    renderWithApi(<AttemptProgressPanel attemptId="att-1" sidebar />, makeApi());
    expect(await screen.findByText("Em curso")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Abrir bancada" })).toHaveAttribute("href", `/sessions/${SESSION_ID}/dyno`);
    expect(screen.getByRole("link", { name: "Abrir ECU" })).toHaveAttribute("href", `/sessions/${SESSION_ID}/ecu`);
    expect(screen.getByText(/Ganho sobre a puxada base: 43,2/)).toBeInTheDocument();
    expect(screen.getByText(/inválida: Calibração alterada durante a puxada/)).toBeInTheDocument();
    expect(screen.getByText("Submissões: 0/5 · restaurações do motor: 0")).toBeInTheDocument();
    expect(screen.getByRole("complementary")).toHaveClass("w-[320px]");
  });

  it("dicas progressivas: HINT_LOCKED, revelação e HINTS_EXHAUSTED", async () => {
    const revealHint = vi
      .fn()
      .mockRejectedValueOnce(problem(409, "HINT_LOCKED"))
      .mockResolvedValueOnce({ order: 1, text: "Enriqueça o lambda alvo acima de 5000 rpm", remaining: 2 })
      .mockRejectedValueOnce(problem(409, "HINTS_EXHAUSTED"));
    renderWithApi(<AttemptProgressPanel attemptId="att-1" />, makeApi({ revealHint }));
    const button = await screen.findByRole("button", { name: "Revelar próxima dica" });
    await userEvent.click(button);
    expect(await screen.findByText("A próxima dica ainda está bloqueada.")).toBeInTheDocument();
    await userEvent.click(button);
    expect(await screen.findByText("Enriqueça o lambda alvo acima de 5000 rpm")).toBeInTheDocument();
    await userEvent.click(button);
    expect(await screen.findByText("Não há mais dicas.")).toBeInTheDocument();
  });

  it("submete com a calibração da tentativa e o defeito declarado, e faz polling em evaluating", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const getAttempt = vi
        .fn()
        .mockResolvedValueOnce(attempt())
        .mockResolvedValueOnce(attempt({ state: "evaluating", submissions: 1 }))
        .mockResolvedValue(attempt({ state: "passed", submissions: 1 }));
      const submit = vi.fn(() => Promise.resolve({ attempt_id: "att-1", submission_index: 1, evaluation_status: "pending" as const }));
      const getScenario = vi.fn(() => Promise.resolve({ ...STAGE1, has_hidden_defect: true }));
      renderWithApi(<AttemptProgressPanel attemptId="att-1" pollMs={50} />, makeApi({ getAttempt, submit, getScenario }));
      await userEvent.selectOptions(await screen.findByLabelText("Defeito diagnosticado"), "fuel_pump_weak");
      await userEvent.click(screen.getByRole("button", { name: "Submeter" }));
      expect(submit).toHaveBeenCalledWith("att-1", { calibration_id: "cal-1", declared_defect: "fuel_pump_weak" });
      expect(await screen.findByText("Em avaliação")).toBeInTheDocument();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(100);
      });
      expect(await screen.findByText("Aprovada")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Ver resultado da última submissão" })).toHaveAttribute("href", "/attempts/att-1/result");
    } finally {
      vi.useRealTimers();
    }
  });

  it("abandona a tentativa", async () => {
    const abandon = vi.fn(() => Promise.resolve(attempt({ state: "abandoned" })));
    renderWithApi(<AttemptProgressPanel attemptId="att-1" />, makeApi({ abandon }));
    await userEvent.click(await screen.findByRole("button", { name: "Abandonar" }));
    expect(await screen.findByText("Abandonada")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Abrir bancada" })).toBeNull();
  });

  it("puxada base em curso mostra barra de progresso", async () => {
    renderWithApi(<ScenariosPage />, makeApi({ getAttempt: vi.fn(() => Promise.resolve(attempt({ state: "preparing", runs: [], progress: [] }))) }), "/attempts/att-1", "/attempts/*");
    expect(await screen.findByRole("progressbar", { name: "Puxada base em execução" })).toBeInTheDocument();
    expect(screen.getByText("Ainda sem puxadas.")).toBeInTheDocument();
  });
});
