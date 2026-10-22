/** RF-05 — formulário de desafio do instrutor: edição de critérios, defeito oculto, dicas e criação. */
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { expectNoAxeViolations } from "@/test/axe";

import { ScenariosApiContext, type ScenariosApi } from "./api";
import { ChallengeForm, DEFAULT_CHALLENGE, defaultComparator } from "./ChallengeForm";
import { makeApi, problem, STAGE1 } from "./test-utils/fixtures";
import type { Scenario } from "./types";

function renderForm(api: ScenariosApi, onCreated = vi.fn()) {
  const utils = render(
    <ScenariosApiContext.Provider value={api}>
      <ChallengeForm onCreated={onCreated} />
    </ScenariosApiContext.Provider>,
  );
  return { ...utils, onCreated };
}

function sentScenario(createScenario: ReturnType<typeof vi.fn<ScenariosApi["createScenario"]>>): Scenario {
  const call = createScenario.mock.calls[0];
  if (!call) throw new Error("createScenario não chamado");
  return call[0].scenario;
}

describe("defaultComparator", () => {
  it("bool para critérios booleanos, le para máximos e ge para o resto", () => {
    expect(defaultComparator("final_profile")).toBe("bool");
    expect(defaultComparator("locked_tables")).toBe("bool");
    expect(defaultComparator("defect_diagnosis")).toBe("bool");
    expect(defaultComparator("max_egt_c")).toBe("le");
    expect(defaultComparator("lambda_wot_max")).toBe("le");
    expect(defaultComparator("min_whp")).toBe("ge");
  });
});

describe("ChallengeForm", () => {
  it("pré-preenche o exemplo 400 whp e não tem violações axe", async () => {
    const { container } = renderForm(makeApi());
    expect(screen.getByLabelText("Título")).toHaveValue(DEFAULT_CHALLENGE.title);
    expect(screen.getByLabelText("Veículo")).toHaveValue("coupe-30t-i6");
    expect(screen.getAllByRole("button", { name: "Remover" })).toHaveLength(DEFAULT_CHALLENGE.criteria.criteria.length);
    await expectNoAxeViolations(container);
  });

  it("edita campos, critérios, defeito oculto e dicas e envia o cenário montado", async () => {
    const createScenario = vi.fn<ScenariosApi["createScenario"]>(() => Promise.resolve(STAGE1));
    const api = makeApi({ createScenario });
    const { onCreated } = renderForm(api);

    fireEvent.change(screen.getByLabelText("Identificador (slug)"), { target: { value: "desafio-teste" } });
    fireEvent.change(screen.getByLabelText("Título"), { target: { value: "Desafio de teste" } });
    await userEvent.selectOptions(screen.getByLabelText("Veículo"), "hatch-20t-gdi");
    await userEvent.selectOptions(screen.getByLabelText("Combustível"), "e100");
    fireEvent.change(screen.getByLabelText("Briefing"), { target: { value: "Faça o melhor possível." } });
    fireEvent.change(screen.getByLabelText("Objetivos (um por linha)"), { target: { value: "Objetivo A\n\n  Objetivo B  " } });
    fireEvent.change(screen.getByLabelText("Puxadas válidas exigidas"), { target: { value: "" } });

    // Critério 1: troca para booleano (limiar some), depois comparador, peso e obrigatoriedade.
    await userEvent.selectOptions(screen.getByLabelText("Tipo do critério 1"), "final_profile");
    expect(screen.getByLabelText(/Limiar do critério 1/)).toBeDisabled();
    await userEvent.selectOptions(screen.getByLabelText("Comparador do critério 1"), "ge");
    fireEvent.change(screen.getByLabelText(/Limiar do critério 1/), { target: { value: "12,5" } });
    fireEvent.change(screen.getByLabelText("Peso do critério 1"), { target: { value: "0" } });
    await userEvent.click(screen.getByLabelText("Critério 1 obrigatório"));
    // Critério 2: limiar vazio e inválido viram null.
    fireEvent.change(screen.getByLabelText(/Limiar do critério 2/), { target: { value: "abc" } });
    // Remove o último critério e acrescenta um novo.
    const removes = screen.getAllByRole("button", { name: "Remover" });
    await userEvent.click(removes[removes.length - 1]!);
    await userEvent.click(screen.getByRole("button", { name: "Adicionar critério" }));

    // Defeito oculto com parâmetros e diagnóstico obrigatório; troca e volta.
    await userEvent.selectOptions(screen.getByLabelText("Tipo de defeito oculto"), "injector_clogged");
    fireEvent.change(screen.getByLabelText("Cilindro"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Fator de vazão"), { target: { value: "0.7" } });
    await userEvent.click(screen.getByLabelText("Exigir diagnóstico do defeito"));

    // Dicas: acrescenta duas, edita, define desbloqueio e remove a primeira.
    await userEvent.click(screen.getByRole("button", { name: "Adicionar dica" }));
    await userEvent.click(screen.getByRole("button", { name: "Adicionar dica" }));
    fireEvent.change(screen.getByLabelText("Texto da dica 1"), { target: { value: "dica 1" } });
    fireEvent.change(screen.getByLabelText("Texto da dica 2"), { target: { value: "dica 2" } });
    const unlocks = screen.getAllByLabelText("Após reprovações");
    fireEvent.change(unlocks[1]!, { target: { value: "2" } });
    fireEvent.change(unlocks[0]!, { target: { value: "" } });
    expect(screen.getByText("Dicas (2/5)")).toBeInTheDocument();
    const hintRow = screen.getByLabelText("Texto da dica 1").closest("div")!;
    await userEvent.click(within(hintRow).getByRole("button", { name: "Remover" }));

    await userEvent.click(screen.getByRole("button", { name: "Criar desafio" }));
    expect(await screen.findByRole("status")).toHaveTextContent(`Desafio ${STAGE1.scenario_id} criado.`);
    expect(onCreated).toHaveBeenCalledWith(STAGE1);

    const sent = sentScenario(createScenario);
    expect(sent.scenario_id).toBe("desafio-teste");
    expect(sent.vehicle_id).toBe("hatch-20t-gdi");
    expect(sent.fuel_id).toBe("e100");
    expect(sent.objectives).toEqual(["Objetivo A", "Objetivo B"]);
    expect(sent.criteria.required_valid_pulls).toBe(1);
    expect(sent.criteria.require_defect_diagnosis).toBe(true);
    const [first, second] = sent.criteria.criteria;
    expect(first).toMatchObject({ kind: "final_profile", comparator: "ge", threshold: 12.5, weight: 1, mandatory: false });
    expect(second!.threshold).toBeNull();
    expect(sent.criteria.criteria.at(-1)).toMatchObject({ kind: "min_torque_nm", threshold: 400 });
    expect(sent.hidden_defect).toMatchObject({ kind: "injector_clogged", cylinder: 3, injector_flow_factor: 0.7 });
    expect(sent.hints).toEqual([{ order: 1, text: "dica 2", unlock: { after_failed_submissions: 2 } }]);
  });

  it("sem defeito volta a null e o slug inválido bloqueia o envio", async () => {
    const createScenario = vi.fn<ScenariosApi["createScenario"]>();
    renderForm(makeApi({ createScenario }));
    await userEvent.selectOptions(screen.getByLabelText("Tipo de defeito oculto"), "wastegate_stuck");
    expect(screen.getByLabelText("Posição travada (%)")).toHaveValue(0);
    await userEvent.selectOptions(screen.getByLabelText("Tipo de defeito oculto"), "");
    expect(screen.queryByLabelText("Posição travada (%)")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Identificador (slug)"), { target: { value: "Slug Inválido" } });
    expect(screen.getByLabelText("Identificador (slug)")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("button", { name: "Criar desafio" })).toBeDisabled();
    fireEvent.submit(screen.getByRole("form", { name: "Novo desafio" }));
    expect(createScenario).not.toHaveBeenCalled();
  });

  it("mostra o erro do servidor ao criar", async () => {
    renderForm(makeApi({ createScenario: vi.fn(() => Promise.reject(problem(409, "SCENARIO_ID_TAKEN", "Já existe."))) }));
    await userEvent.click(screen.getByRole("button", { name: "Criar desafio" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("SCENARIO_ID_TAKEN");
  });

  it("limita a 5 dicas", async () => {
    renderForm(makeApi());
    const add = screen.getByRole("button", { name: "Adicionar dica" });
    for (let i = 0; i < 5; i += 1) await userEvent.click(add);
    expect(add).toBeDisabled();
  });
});
