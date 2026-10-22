/** 002 T055 (RF-19): Stage Builder na criação de sessão: peças, Flex Fuel e erros da oficina. */
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { HomePage } from "@/app/HomePage";
import type { HomeApi } from "@/app/homeApi";
import { makeHomeApi, UPGRADE_CATALOG, vehicleCompat } from "@/app/test-fixtures";
import { ApiProblem } from "@/lib/api";

import { compatFromVehicle } from "./api";
import { StageBuilder } from "./StageBuilder";
import { describeEffect, STOCK_SELECTION, toSessionFields } from "./types";

function renderHome(api: HomeApi) {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<HomePage api={api} flags={{ dynoCockpit: true, ecuTuning: true }} />} />
        <Route path="*" element={<p>outra página</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

const problem = (status: number, code: string, detail: string, extra: Record<string, unknown> = {}) =>
  new ApiProblem({ type: `urn:simremap:problem:${code}`, title: code, status, detail, code, request_id: "r", ...extra });

beforeEach(() => localStorage.clear());

describe("StageBuilder (002 T047)", () => {
  it("mostra as 6 categorias com as peças e os efeitos", async () => {
    render(<StageBuilder api={makeHomeApi()} vehicleId="hatch-20t-gdi" value={STOCK_SELECTION} onChange={vi.fn()} />);
    for (const legend of ["Turbina", "Bicos injetores", "Bomba de combustível", "Intercooler", "Downpipe", "Internos do motor"]) {
      expect(await screen.findByRole("group", { name: legend })).toBeInTheDocument();
    }
    expect(screen.getByText("Área efetiva da turbina ×1,25")).toBeInTheDocument();
    expect(screen.getByText("Temperatura máxima do pistão +40 °C")).toBeInTheDocument();
  });

  it("bloqueia turbo e intercooler num veículo sem eles e esconde o Flex", async () => {
    const onChange = vi.fn();
    render(<StageBuilder api={makeHomeApi()} vehicleId="muscle-v8-sc" value={STOCK_SELECTION} onChange={onChange} />);
    const turbo = await screen.findByRole("group", { name: "Turbina" });
    const upgraded = within(turbo).getByRole("radio", { name: /Turbina upgraded/ });
    expect(upgraded).toBeDisabled();
    expect(upgraded).toHaveAccessibleDescription("Só para motor turbo.");
    expect(within(screen.getByRole("group", { name: "Intercooler" })).getByRole("radio", { name: /esportivo/ })).toBeDisabled();
    expect(within(screen.getByRole("group", { name: "Internos do motor" })).getByRole("radio", { name: /forjados/ })).toBeEnabled();
    await userEvent.click(upgraded);
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.queryByRole("checkbox", { name: "Flex Fuel" })).not.toBeInTheDocument();
    expect(screen.getByText(/Flex Fuel indisponível/)).toBeInTheDocument();
  });

  it("falha do catálogo mostra o erro e tenta de novo", async () => {
    const api = makeHomeApi({ listUpgrades: vi.fn().mockRejectedValueOnce(problem(503, "DATABASE_UNAVAILABLE", "fora")).mockResolvedValue(UPGRADE_CATALOG) });
    render(<StageBuilder api={api} vehicleId="hatch-20t-gdi" value={STOCK_SELECTION} onChange={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/carro de série/);
    await userEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByRole("group", { name: "Turbina" })).toBeInTheDocument();
  });
});

describe("HomePage com a oficina (002 RF-19)", () => {
  it("escolher peças e E85 envia upgrades e ethanol_pct no POST da sessão", async () => {
    const api = makeHomeApi();
    renderHome(api);
    await userEvent.click(within(await screen.findByRole("group", { name: "Turbina" })).getByRole("radio", { name: /Turbina upgraded/ }));
    await userEvent.click(within(screen.getByRole("group", { name: "Internos do motor" })).getByRole("radio", { name: /forjados/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Flex Fuel" }));
    const slider = screen.getByRole("slider", { name: "Teor de etanol" });
    fireEvent.change(slider, { target: { value: "60" } });
    fireEvent.change(slider, { target: { value: "85" } });
    expect(screen.getByText("E85 (85 %)")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Criar sessão" }));
    expect(api.createSession).toHaveBeenCalledWith({
      vehicle_id: "hatch-20t-gdi",
      profile_id: "oem-stage",
      upgrades: { turbo: "upgraded", internals: "forged" },
      ethanol_pct: 85,
    });
    expect(await screen.findByText("outra página")).toBeInTheDocument();
  });

  it("trocar de carro volta o pacote para série", async () => {
    const api = makeHomeApi();
    renderHome(api);
    await userEvent.click(within(await screen.findByRole("group", { name: "Downpipe" })).getByRole("radio", { name: /alto fluxo/ }));
    await userEvent.click(screen.getByRole("radio", { name: /Coupé 3.0 Turbo I6/ }));
    await screen.findByRole("group", { name: "Downpipe" });
    await userEvent.click(screen.getByRole("button", { name: "Criar sessão" }));
    expect(api.createSession).toHaveBeenCalledWith({ vehicle_id: "coupe-30t-i6", profile_id: "ft-pro" });
  });

  it.each([
    [409, "FUEL_NOT_ALLOWED", {}, /não aceita Flex Fuel/],
    [422, "UPGRADE_NOT_COMPATIBLE", { category: "turbo", part_id: "upgraded" }, /A peça de turbina não serve neste carro/],
  ])("erro %i %s tem mensagem clara", async (status, code, extra, text) => {
    const api = makeHomeApi({ createSession: vi.fn().mockRejectedValue(problem(status, code, "detalhe técnico", extra)) });
    renderHome(api);
    await userEvent.click(await screen.findByRole("checkbox", { name: "Flex Fuel" }));
    await userEvent.click(screen.getByRole("button", { name: "Criar sessão" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(text);
    expect(alert).toHaveTextContent(code);
  });

  it("com cenário a oficina fica de fora", async () => {
    renderHome(makeHomeApi());
    await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Cenário (opcional)" }), "stage1-oem");
    expect(screen.queryByRole("group", { name: "Turbina" })).not.toBeInTheDocument();
    expect(screen.getByText(/a oficina vale só para sessões livres/)).toBeInTheDocument();
  });
});

describe("regras puras da oficina", () => {
  it("toSessionFields omite o pacote de série e o Flex desligado", () => {
    expect(toSessionFields(STOCK_SELECTION)).toEqual({});
    expect(toSessionFields({ parts: { ...STOCK_SELECTION.parts, downpipe: "high_flow" }, ethanolPct: 27 })).toEqual({
      upgrades: { downpipe: "high_flow" },
      ethanol_pct: 27,
    });
  });

  it("describeEffect formata fator e soma em pt-BR", () => {
    expect(describeEffect("intercooler_effectiveness_add", 0.08)).toBe("Efetividade do intercooler +0,08");
    expect(describeEffect("x_scale", 1.5)).toBe("x_scale ×1,5");
  });

  it("compatFromVehicle lê turbo, intercooler e E27/E100 do detalhe do veículo", () => {
    expect(
      compatFromVehicle({ vehicle_id: "hatch-20t-gdi", turbo: { a: 1 }, engine: { intercooler: { effectiveness: 0.7 } }, allowed_fuel_ids: ["e27", "e100"] }),
    ).toEqual(vehicleCompat("hatch-20t-gdi"));
    expect(compatFromVehicle({ vehicle_id: "muscle-v8-sc", turbo: null, engine: {}, allowed_fuel_ids: ["e27", "podium"] })).toEqual(
      vehicleCompat("muscle-v8-sc"),
    );
  });
});
