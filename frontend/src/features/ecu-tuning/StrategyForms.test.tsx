/** T195 — StrategyForms (1 formulário por subtipo, zod espelho do Pydantic) e CylinderTrims ±25 % / ±10° (tuning RF-14, RF-19, RF-21; EC-13). */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CylinderTrims } from "./CylinderTrims";
import parity from "./fixtures/strategy-parity.json";
import { problemToFieldErrors, StrategyForm } from "./StrategyForms";
import { STRATEGY_FIELDS, STRATEGY_KINDS, strategyDefaults, validateStrategy } from "./strategySchemas";
import { problem } from "./test-utils/fixtures";

describe("paridade zod × Pydantic (RF-14)", () => {
  it("o conjunto de 40 payloads (20 válidos, 20 inválidos) dá o veredito esperado", () => {
    expect(parity.cases).toHaveLength(40);
    expect(parity.cases.filter((c) => c.valid)).toHaveLength(20);
    for (const c of parity.cases) expect({ name: c.name, valid: validateStrategy(c.payload).ok }).toEqual({ name: c.name, valid: c.valid });
  });

  it("os padrões de cada subtipo são válidos", () => {
    for (const kind of STRATEGY_KINDS) expect(validateStrategy(strategyDefaults(kind)).ok).toBe(true);
  });
});

describe("formulários por subtipo", () => {
  it.each(STRATEGY_KINDS.filter((k) => k !== "failsafe"))("%s renderiza todos os campos", (kind) => {
    render(<StrategyForm kind={kind} value={strategyDefaults(kind)} onSave={vi.fn((_config: Record<string, unknown>) => Promise.resolve(null))} />);
    const form = screen.getByRole("form");
    const fields = STRATEGY_FIELDS[kind];
    const esc = (t: string) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    for (const f of fields) expect(within(form).getByLabelText(new RegExp(`^${esc(f.label)}( \\(.*\\))?$`))).toBeInTheDocument();
  });

  it("valor inválido mostra o erro junto ao campo e não grava", async () => {
    const onSave = vi.fn((_config: Record<string, unknown>) => Promise.resolve(null));
    render(<StrategyForm kind="rev_limiter" value={strategyDefaults("rev_limiter")} onSave={onSave} />);
    const input = screen.getByLabelText(/Corte \(rpm\)/);
    fireEvent.change(input, { target: { value: "13000" } });
    fireEvent.click(screen.getByRole("button", { name: "Gravar estratégia" }));
    await waitFor(() => expect(input).toHaveAttribute("aria-invalid", "true"));
    expect(screen.getByRole("alert")).toHaveTextContent("Corte (rpm): máximo 12000");
    expect(input.getAttribute("aria-describedby")).toBe(screen.getByRole("alert").id);
    expect(onSave).not.toHaveBeenCalled();
  });

  it("regra entre campos (two_step/overrun) e vírgula decimal", async () => {
    const onSave = vi.fn((_config: Record<string, unknown>) => Promise.resolve(null));
    render(<StrategyForm kind="overrun" value={strategyDefaults("overrun")} onSave={onSave} />);
    fireEvent.change(screen.getByLabelText(/DFCO: rotação de retomada/), { target: { value: "1600" } });
    fireEvent.change(screen.getByLabelText(/Lambda alvo/), { target: { value: "0,95" } });
    fireEvent.click(screen.getByRole("button", { name: "Gravar estratégia" }));
    expect(await screen.findByText("dfco_resume_rpm deve ser menor que dfco_rpm_min")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/DFCO: rotação de retomada/), { target: { value: "1200" } });
    fireEvent.click(screen.getByRole("button", { name: "Gravar estratégia" }));
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0]![0]).toMatchObject({ kind: "overrun", lambda_target: 0.95, dfco_resume_rpm: 1200 });
    expect(await screen.findByText("Estratégia gravada.")).toBeInTheDocument();
  });

  it("opções restritas pelo perfil ficam desativadas (antilag só por botão)", () => {
    render(
      <StrategyForm
        kind="antilag"
        value={strategyDefaults("antilag")}
        support={{ kind: "antilag", level: "supported", restricted_options: { activation: ["switch"] }, display_name: "Antilag por botão" }}
        onSave={vi.fn((_config: Record<string, unknown>) => Promise.resolve(null))}
      />,
    );
    expect(screen.getByRole("heading", { name: "Antilag por botão" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Rolante/ })).toBeDisabled();
  });

  it("estratégia não suportada mostra a indicação", () => {
    render(<StrategyForm kind="antilag" value={{}} support={{ kind: "antilag", level: "unsupported", restricted_options: {}, display_name: "Antilag" }} onSave={vi.fn()} />);
    expect(screen.getByText("Estratégia não suportada neste perfil.")).toBeInTheDocument();
  });

  it("erros 422 do servidor aparecem por campo (EC-13)", async () => {
    const p = problem(422, "VALIDATION_FAILED", {}, "Validação", "inválido");
    const errs = problemToFieldErrors({ detail: p.detail, errors: [{ loc: ["body", "strategies", "two_step", "target_rpm"], msg: "valor recusado" }], extra: {} }, "two_step");
    expect(errs).toEqual({ target_rpm: "valor recusado" });
    render(<StrategyForm kind="two_step" value={strategyDefaults("two_step")} onSave={() => Promise.resolve(errs)} />);
    fireEvent.click(screen.getByRole("button", { name: "Gravar estratégia" }));
    expect(await screen.findByText("valor recusado")).toBeInTheDocument();
    expect(problemToFieldErrors({ detail: "two_step ≥ corte", errors: [], extra: { fields: ["strategies.two_step.target_rpm"] } }, "two_step")).toEqual({ target_rpm: "two_step ≥ corte" });
    expect(problemToFieldErrors(null, "x")).toEqual({ "": "Não foi possível gravar a estratégia." });
  });

  it("aviso W-04 junto ao campo não bloqueia a gravação", async () => {
    const onSave = vi.fn((_config: Record<string, unknown>) => Promise.resolve(null));
    render(<StrategyForm kind="rev_limiter" value={strategyDefaults("rev_limiter")} warnings={[{ code: "W-04", message: "Limitador acima da rotação máxima segura do motor.", detail: "", field: "rev_limiter.hard_rpm" }]} onSave={onSave} />);
    expect(document.querySelector('[data-warning="W-04"]')).toHaveTextContent("Limitador acima");
    fireEvent.click(screen.getByRole("button", { name: "Gravar estratégia" }));
    await waitFor(() => expect(onSave).toHaveBeenCalled());
  });

  it("failsafe: editar, acrescentar e validar regras", async () => {
    const onSave = vi.fn((_config: Record<string, unknown>) => Promise.resolve(null));
    render(<StrategyForm kind="failsafe" value={{ kind: "failsafe", rules: [{ rule_id: "egt_high", threshold: 950, confirm_s: 0.5, actions: ["boost_reduce"], action_value: 30, release_s: 2 }] }} onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "Acrescentar regra" }));
    fireEvent.change(screen.getByLabelText("Regra 2"), { target: { value: "egt_high" } });
    fireEvent.click(screen.getByRole("button", { name: "Gravar estratégia" }));
    expect(await screen.findByText("rules com rule_id duplicado")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Regra 2"), { target: { value: "overspeed" } });
    fireEvent.change(screen.getByLabelText("Limiar da regra 2"), { target: { value: "7600" } });
    fireEvent.click(screen.getByRole("button", { name: "Gravar estratégia" }));
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0]![0]).toMatchObject({ kind: "failsafe", rules: [{ rule_id: "egt_high" }, { rule_id: "overspeed", threshold: 7600, actions: ["boost_cut"] }] });
  });
});

describe("CylinderTrims (RF-21)", () => {
  const six = Object.fromEntries([1, 2, 3, 4, 5, 6].map((c) => [c, 0]));

  it("num motor de 6 cilindros aparecem 6 colunas", () => {
    render(<CylinderTrims nCyl={6} fuel={six} ignition={six} onSave={vi.fn(() => Promise.resolve())} />);
    expect(document.querySelectorAll("[data-cylinder-col]")).toHaveLength(6);
    expect(screen.getAllByRole("textbox", { name: /Trim de ignição cilindro/ })).toHaveLength(6);
  });

  it("valor −11° é rejeitado com a mensagem de limite", async () => {
    const onSave = vi.fn(() => Promise.resolve());
    render(<CylinderTrims nCyl={6} fuel={six} ignition={six} onSave={onSave} />);
    fireEvent.change(screen.getByRole("textbox", { name: "Trim de ignição cilindro 3" }), { target: { value: "-11" } });
    fireEvent.click(screen.getByRole("button", { name: "Gravar correções" }));
    expect(await screen.findByText("Limite do trim de ignição: ±10°")).toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
  });

  it("combustível ±25 %: 26 rejeitado, −25 e 4,5 aceites", async () => {
    const onSave = vi.fn(() => Promise.resolve());
    render(<CylinderTrims nCyl={6} fuel={six} ignition={six} onSave={onSave} />);
    fireEvent.change(screen.getByRole("textbox", { name: "Trim de combustível cilindro 1" }), { target: { value: "26" } });
    fireEvent.click(screen.getByRole("button", { name: "Gravar correções" }));
    expect(await screen.findByText("Limite do trim de combustível: ±25 %")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Trim de combustível cilindro 1" }), { target: { value: "-25" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Trim de combustível cilindro 2" }), { target: { value: "4,5" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Gravar correções" }));
      await Promise.resolve();
    });
    expect(onSave).toHaveBeenCalledWith("fuel_trim_cyl", { 1: -25, 2: 4.5, 3: 0, 4: 0, 5: 0, 6: 0 });
    expect(onSave).toHaveBeenCalledWith("ignition_trim_cyl", six);
  });

  it("cilindro sem tabela fica desativado", () => {
    render(<CylinderTrims nCyl={4} fuel={{ 1: 0, 2: null, 3: null, 4: null }} ignition={{ 1: 0, 2: 0, 3: 0, 4: 0 }} onSave={vi.fn()} />);
    expect(screen.getByRole("textbox", { name: "Trim de combustível cilindro 2" })).toBeDisabled();
  });
});
