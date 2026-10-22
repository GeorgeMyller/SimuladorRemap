/* eslint-disable @typescript-eslint/require-await -- mocks assíncronos */
/** T196 — BaseSetupWizard: 6 passos deixam o motor em marcha lenta com `ft-pro`; voltar preserva os dados (tuning RF-15; Fluxo A; EC-14). */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BaseSetupWizard, validateStep } from "./BaseSetupWizard";
import { SwapSelector } from "./SwapSelector";
import { checklistFixture, DESCRIPTORS, hardwareFixture, makeApi, problem, SESSION_ID, sessionFixture } from "./test-utils/fixtures";
import { renderWorkspace } from "./test-utils/harness";

beforeEach(() => localStorage.clear());
afterEach(() => vi.useRealTimers());

const advance = () => fireEvent.click(screen.getByRole("button", { name: "Avançar" }));

function wizard(over: Partial<Parameters<typeof BaseSetupWizard>[0]> = {}) {
  const api = makeApi();
  const onDone = vi.fn();
  render(<BaseSetupWizard sessionId={SESSION_ID} api={api} profileName="FT-Pro" hardware={hardwareFixture} baseVersion={null} checklist={checklistFixture} onDone={onDone} {...over} />);
  return { api, onDone };
}

describe("BaseSetupWizard (RF-15)", () => {
  it("completar os 6 passos grava a base e deixa o motor pronto (ft-pro)", async () => {
    const { api, onDone } = wizard();
    const steps = ["Roda fônica", "Bicos injetores", "Combustível", "Sensores", "Failsafe e limites"];
    for (const s of steps) {
      expect(screen.getByRole("group", { name: new RegExp(s) })).toBeInTheDocument();
      advance();
    }
    expect(screen.getByRole("group", { name: /Passo 6 de 6: Revisão/ })).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Gravar e gerar mapa base" }));
    });
    expect(api.putBaseSetup).toHaveBeenCalledTimes(1);
    const [sessionId, body] = api.putBaseSetup.mock.calls[0]!;
    expect(sessionId).toBe(SESSION_ID);
    expect(body).toMatchObject({
      base_version: null,
      generate_base_map: true,
      apply_limits_to_calibration: true,
      base_setup: {
        trigger: { wheel: "60-2", tdc_offset_deg: 84, phase_sensor: "cam_hall", injection_mode: "sequential", firing_order: [1, 3, 4, 2], timing_lock_deg: null },
        injectors: { flow_cc_min: 550, dead_time_v: [8, 10, 12, 13.5, 14.5, 16] },
        fuel: { fuel_id: "e27", afr_stoich: 13.2 },
        sensors: { map: { min_kpa: 10, max_kpa: 400 }, wideband: { lambda_at_0v: 0.5, lambda_at_5v: 1.5 } },
        protection: { rev_limit_rpm: 7000, overspeed_rpm: 7500 },
      },
      wizard: { idle_rpm: 900, grid: 16, rev_limit_rpm: 7000 },
    });
    expect(onDone).toHaveBeenCalledWith(expect.objectContaining({ ecu_state: "standalone_ready", profile_id: "ft-pro" }));
  });

  it("valida cada passo com zod antes de avançar e voltar preserva os dados", () => {
    wizard();
    fireEvent.change(screen.getByLabelText("Ordem de ignição"), { target: { value: "1, 3, 3, 2" } });
    advance();
    expect(screen.getByRole("alert")).toHaveTextContent("FIRING_ORDER_INVALID");
    expect(screen.getByRole("group", { name: /Passo 1 de 6/ })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Ordem de ignição"), { target: { value: "1, 2, 4, 3" } });
    advance();
    fireEvent.change(screen.getByLabelText(/Vazão do bico/), { target: { value: "650" } });
    advance();
    fireEvent.click(screen.getByRole("button", { name: "Voltar" }));
    expect(screen.getByLabelText(/Vazão do bico/)).toHaveValue("650");
    fireEvent.click(screen.getByRole("button", { name: "Voltar" }));
    expect(screen.getByLabelText("Ordem de ignição")).toHaveValue("1, 2, 4, 3");
  });

  it("sequencial sem sensor de fase e sobre-rotação abaixo do corte são recusados", () => {
    const v = (over: Record<string, string>) => ({
      "trigger.wheel": "60-2", "trigger.tdc_offset_deg": "84", "trigger.phase_sensor": "none", "trigger.phase_edge_deg": "0",
      "trigger.injection_mode": "sequential", "trigger.ignition_mode": "wasted_spark", "trigger.firing_order": "1, 3, 4, 2", "trigger.timing_lock_deg": "",
      "protection.rev_limit_rpm": "7000", "protection.overspeed_rpm": "6900", "protection.overboost_kpa": "260", "protection.egt_max_c": "950",
      "protection.ect_max_c": "110", "protection.oil_pressure_min_kpa": "100", "protection.lean_delta_lambda": "0.1", ...over,
    });
    const t = validateStep("trigger", v({}));
    expect(t.ok).toBe(false);
    expect(!t.ok && t.errors["trigger.phase_sensor"]).toContain("SEQUENTIAL_REQUIRES_PHASE_SENSOR");
    const p = validateStep("protection", v({}));
    expect(!p.ok && p.errors["protection.overspeed_rpm"]).toContain("OVERSPEED_BELOW_REV_LIMIT");
    expect(validateStep("protection", v({ "protection.overspeed_rpm": "7500" })).ok).toBe(true);
  });

  it("422 BASE_SETUP_INVALID volta ao passo do campo com o erro", async () => {
    const api = makeApi({
      putBaseSetup: vi.fn(async () => {
        throw problem(422, "BASE_SETUP_INVALID", { field: "injectors.flow_cc_min", reason: "INJECTOR_UNDERSIZED" }, "Base inválida", "Bico pequeno para a potência.");
      }),
    });
    render(<BaseSetupWizard sessionId={SESSION_ID} api={api} profileName="FT-Pro" hardware={hardwareFixture} baseVersion={2} initialStep="review" onDone={vi.fn()} />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Gravar e gerar mapa base" }));
    });
    expect(screen.getByRole("group", { name: /Bicos injetores/ })).toBeInTheDocument();
    expect(screen.getAllByRole("alert")[0]).toHaveTextContent("Bico pequeno para a potência. (INJECTOR_UNDERSIZED)");
    expect(api.putBaseSetup.mock.calls[0]![1].base_version).toBe(2);
  });

  it("checklist incompleta após gravar mantém o assistente aberto", async () => {
    const api = makeApi({
      putBaseSetup: vi.fn(async () => ({ ...(await makeApi().putBaseSetup(SESSION_ID, {} as never)), ecu_state: "awaiting_base_setup", checklist: { items: [{ id: "sensors.map", required: true, status: "invalid", code: null, message: "MAP fora da faixa" }], minimum_valid: false } })),
    });
    const onDone = vi.fn();
    render(<BaseSetupWizard sessionId={SESSION_ID} api={api} profileName="FT-Pro" hardware={hardwareFixture} baseVersion={null} initialStep="review" onDone={onDone} />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Gravar e gerar mapa base" }));
    });
    expect(onDone).not.toHaveBeenCalled();
    expect(screen.getByText(/sensors.map: inválido — MAP fora da faixa/)).toBeInTheDocument();
  });
});

describe("swap OEM → standalone (Fluxo A)", () => {
  const profiles = Object.values(DESCRIPTORS);

  it("seletor lista os perfis standalone, exige o snapshot e o pacote do M1-Race", async () => {
    const onSwap = vi.fn(() => Promise.resolve());
    render(<SwapSelector currentProfileId="oem-stage" profiles={profiles} runActive={false} onSwap={onSwap} />);
    fireEvent.click(screen.getByRole("button", { name: "Trocar ECU" }));
    expect(screen.getAllByRole("radio").map((r) => (r as HTMLInputElement).value)).toEqual(["ft-pro", "m1-race", "ht-elite"]);
    const submit = screen.getByRole("button", { name: "Trocar e abrir o assistente" });
    expect(submit).toBeDisabled();
    fireEvent.click(screen.getByRole("radio", { name: /M1-Race/ }));
    fireEvent.change(screen.getByRole("combobox", { name: /Pacote/ }), { target: { value: "race" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /snapshot/ }));
    await act(async () => {
      fireEvent.click(submit);
    });
    expect(onSwap).toHaveBeenCalledWith(expect.objectContaining({ target_profile_id: "m1-race", confirm_snapshot: true, feature_package: "race" }));
  });

  it("durante a puxada o botão fica desativado com a dica (EC-14)", () => {
    render(<SwapSelector currentProfileId="oem-stage" profiles={profiles} runActive onSwap={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Trocar ECU" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Trocar ECU" })).toHaveAttribute("title", "aborte ou aguarde o fim da puxada");
  });

  it("no workspace: Trocar ECU → assistente → base gravada recarrega o perfil ft-pro", async () => {
    const api = makeApi({ getSession: vi.fn(async () => ({ ...sessionFixture, profile_id: "oem-stage", ecu_state: "oem" })) });
    renderWorkspace(api);
    await screen.findByTestId("workspace-profile");
    expect(screen.getByTestId("workspace-profile")).toHaveTextContent("OEM-Stage");
    fireEvent.click(screen.getByRole("button", { name: "Trocar ECU" }));
    fireEvent.click(screen.getByRole("radio", { name: /HT-Elite/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /snapshot/ }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Trocar e abrir o assistente" }));
    });
    expect(api.swap).toHaveBeenCalledWith(SESSION_ID, expect.objectContaining({ target_profile_id: "ht-elite", confirm_snapshot: true }));
    expect(await screen.findByRole("heading", { name: /Configuração base — HT-Elite/ })).toBeInTheDocument();
    api.getSession.mockImplementation(async () => ({ ...sessionFixture, profile_id: "ft-pro", ecu_state: "standalone_ready" }));
    const go = async () => {
      for (let i = 0; i < 5; i += 1) advance();
      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: "Gravar e gerar mapa base" }));
      });
    };
    await go();
    await waitFor(() => expect(screen.getByTestId("workspace-profile")).toHaveTextContent("FT-Pro"));
    expect(api.putBaseSetup).toHaveBeenCalled();
    expect(await screen.findByText(/marcha lenta/)).toBeInTheDocument();
  });
});
