/** Seletor dos 4 carros do workspace: troca de sessão, capacidade cheia (409) e falhas. */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiProblem } from "@/lib/api";

import { sessionFixture } from "./test-utils/fixtures";
import { VehicleSelector, type VehicleSelectorProps } from "./VehicleSelector";

const items = [
  { vehicle_id: "hatch-20t-gdi", display_name: "Hatch", stock_profile_id: "oem-stage", validation_status: "draft" },
  { vehicle_id: "coupe-30t-i6", display_name: "Coupé", stock_profile_id: "ft-pro", validation_status: "validated" },
];

const capacity = new ApiProblem({ type: "urn:x", title: "Capacidade", status: 409, detail: "cheia", code: "SIM_CAPACITY_EXCEEDED", request_id: "r" });

function setup(over: Partial<VehicleSelectorProps> = {}) {
  const props: VehicleSelectorProps = {
    api: { listVehicles: vi.fn(() => Promise.resolve({ items } as never)) },
    currentVehicleId: "hatch-20t-gdi",
    onSwitch: vi.fn(() => Promise.resolve(sessionFixture)),
    onSwitched: vi.fn(),
    ...over,
  };
  render(<VehicleSelector {...props} />);
  return props;
}

describe("VehicleSelector", () => {
  it("lista os carros (rascunho marcado) e troca para o carro escolhido com o perfil de série", async () => {
    const props = setup();
    const select = screen.getByLabelText("Carro");
    expect(select).toBeDisabled();
    await screen.findByRole("option", { name: "Hatch (rascunho)" });
    await userEvent.selectOptions(select, "coupe-30t-i6");
    expect(props.onSwitch).toHaveBeenCalledWith("coupe-30t-i6", "ft-pro", false);
    await waitFor(() => expect(props.onSwitched).toHaveBeenCalledWith(sessionFixture));
  });

  it("capacidade cheia oferece fechar a sessão atual e repete com closeCurrent", async () => {
    const onSwitch = vi.fn<VehicleSelectorProps["onSwitch"]>().mockRejectedValueOnce(capacity).mockResolvedValue(sessionFixture);
    const props = setup({ onSwitch });
    await screen.findByRole("option", { name: "Coupé" });
    await userEvent.selectOptions(screen.getByLabelText("Carro"), "coupe-30t-i6");
    await userEvent.click(await screen.findByRole("button", { name: "Fechar a sessão atual e abrir Coupé" }));
    expect(onSwitch).toHaveBeenLastCalledWith("coupe-30t-i6", "ft-pro", true);
    await waitFor(() => expect(props.onSwitched).toHaveBeenCalled());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("outros erros mostram título e detalhe; erro desconhecido mostra mensagem genérica", async () => {
    const onSwitch = vi
      .fn<VehicleSelectorProps["onSwitch"]>()
      .mockRejectedValueOnce(new ApiProblem({ type: "urn:x", title: "Veículo", status: 409, detail: "não validado", code: "VEHICLE_NOT_VALIDATED", request_id: "r" }))
      .mockRejectedValueOnce(new Error("x"));
    setup({ onSwitch, currentVehicleId: "coupe-30t-i6" });
    await screen.findByRole("option", { name: "Coupé" });
    await userEvent.selectOptions(screen.getByLabelText("Carro"), "hatch-20t-gdi");
    expect(await screen.findByRole("alert")).toHaveTextContent("Veículo: não validado");
    await userEvent.selectOptions(screen.getByLabelText("Carro"), "hatch-20t-gdi");
    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível trocar de carro.");
  });

  it("catálogo indisponível mantém o carro atual e mostra o aviso", async () => {
    setup({ api: { listVehicles: vi.fn(() => Promise.reject(new Error("down"))) } });
    expect(await screen.findByRole("alert")).toHaveTextContent("Catálogo de carros indisponível.");
    expect(screen.getByRole("option", { name: "hatch-20t-gdi" })).toBeInTheDocument();
  });
});
