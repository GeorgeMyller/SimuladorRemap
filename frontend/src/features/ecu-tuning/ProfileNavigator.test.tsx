/** T192 — ProfileNavigator: o mesmo componente gera 4 árvores a partir dos 4 descritores (tuning RF-02, EC-09, EC-10). */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ProfileNavigator } from "./ProfileNavigator";
import { DESCRIPTORS } from "./test-utils/fixtures";
import type { EcuProfileDescriptor } from "./types";

function tree(d: EcuProfileDescriptor) {
  const { unmount, container } = render(<ProfileNavigator descriptor={d} activeItemId={null} onSelect={() => undefined} />);
  const nav = screen.getByRole("navigation");
  const shape = d.navigation.map((s) => [s.label, ...s.items.map((i) => i.label)]);
  const rendered = [...container.querySelectorAll("h3")].map((h) => {
    const list = h.nextElementSibling!;
    return [h.textContent, ...[...list.querySelectorAll("[data-nav-item]")].map((b) => b.firstElementChild?.firstChild?.textContent)];
  });
  const name = within(nav).getByTestId("profile-name").textContent;
  unmount();
  return { shape, rendered, name };
}

describe("ProfileNavigator (RF-02)", () => {
  it("os 4 descritores produzem 4 árvores diferentes, na ordem do descritor", () => {
    const trees = ["oem-stage", "ft-pro", "m1-race", "ht-elite"].map((id) => tree(DESCRIPTORS[id]!));
    for (const t of trees) expect(t.rendered).toEqual(t.shape);
    expect(trees.map((t) => t.name)).toEqual(["OEM-Stage", "FT-Pro", "M1-Race", "HT-Elite"]);
    const serialized = new Set(trees.map((t) => JSON.stringify(t.rendered)));
    expect(serialized.size).toBe(4);
  });

  it("um item novo no descritor aparece sem mudança de código", () => {
    const d = structuredClone(DESCRIPTORS["ht-elite"]!);
    d.navigation[0]!.items.push({ id: "fuel.new", label: "Tabela nova do perfil", kind: "table", target_id: "fuel_corr_ect", cylinder: null });
    render(<ProfileNavigator descriptor={d} activeItemId={null} onSelect={() => undefined} />);
    expect(screen.getByRole("button", { name: /Tabela nova do perfil/ })).toBeInTheDocument();
  });

  it("seleciona o item e marca o ativo com aria-current", () => {
    const onSelect = vi.fn();
    const { rerender } = render(<ProfileNavigator descriptor={DESCRIPTORS["ft-pro"]!} activeItemId={null} onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("button", { name: /Avanço de ignição/ }));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: "ign.base", target_id: "ignition_base" }));
    rerender(<ProfileNavigator descriptor={DESCRIPTORS["ft-pro"]!} activeItemId="ign.base" onSelect={onSelect} />);
    expect(screen.getByRole("button", { name: /Avanço de ignição/ })).toHaveAttribute("aria-current", "page");
  });

  it("pesquisa por nome de tabela (sem acento)", () => {
    render(<ProfileNavigator descriptor={DESCRIPTORS["ft-pro"]!} activeItemId={null} onSelect={() => undefined} />);
    fireEvent.change(screen.getByLabelText("Pesquisar tabela"), { target: { value: "avanco" } });
    expect(screen.getByRole("button", { name: /Avanço de ignição/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Lambda alvo/ })).not.toBeInTheDocument();
  });

  it("item órfão aparece desativado com 'não disponível nesta calibração' (EC-10)", () => {
    render(<ProfileNavigator descriptor={DESCRIPTORS["m1-race"]!} activeItemId={null} onSelect={() => undefined} isAvailable={(i) => i.id !== "eng.ign"} />);
    const btn = screen.getByRole("button", { name: /Ignição/ });
    expect(btn).toBeDisabled();
    expect(btn).toHaveTextContent("não disponível nesta calibração");
  });

  it("tabela bloqueada mostra o cadeado", () => {
    render(<ProfileNavigator descriptor={DESCRIPTORS["ft-pro"]!} activeItemId={null} onSelect={() => undefined} isLocked={(i) => i.id === "drag.boost_gear"} />);
    expect(within(screen.getByRole("button", { name: /Pressão por marcha/ })).getByRole("img", { name: "cadeado" })).toBeInTheDocument();
  });

  it("descritor sem navegação mostra o erro com o profile_id (EC-09)", () => {
    render(<ProfileNavigator descriptor={{ ...DESCRIPTORS["ft-pro"]!, navigation: [] }} activeItemId={null} onSelect={() => undefined} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Perfil sem navegação (ft-pro)");
  });

  it("o acento de cor vem do descritor", () => {
    render(<ProfileNavigator descriptor={{ ...DESCRIPTORS["ft-pro"]!, accent_color: "#123456" }} activeItemId={null} onSelect={() => undefined} />);
    expect(screen.getByRole("navigation").getAttribute("style")).toContain("rgb(18, 52, 86)");
  });
});
