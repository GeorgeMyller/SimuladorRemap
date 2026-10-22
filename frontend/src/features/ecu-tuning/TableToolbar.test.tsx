/** RF-05 a RF-09, EC-07 — barra de operações isolada: valor, operação, atalhos, interpolação e toggles. */
import { createRef } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { TableToolbar, type TableToolbarHandle, type TableToolbarProps } from "./TableToolbar";

function setup(over: Partial<TableToolbarProps> = {}) {
  const props: TableToolbarProps = {
    rect: { r0: 0, r1: 1, c0: 0, c1: 1 },
    disabled: false,
    canUndo: true,
    canRedo: true,
    heatmap: false,
    lambdaTable: true,
    lambdaDisplay: "lambda",
    afrAvailable: true,
    is3d: true,
    show3d: false,
    onOperation: vi.fn(),
    onCopy: vi.fn(),
    onPaste: vi.fn(),
    onUndo: vi.fn(),
    onRedo: vi.fn(),
    onToggleHeatmap: vi.fn(),
    onToggleLambda: vi.fn(),
    onToggle3d: vi.fn(),
    onDone: vi.fn(),
    ...over,
  };
  const ref = createRef<TableToolbarHandle>();
  render(<TableToolbar ref={ref} {...props} />);
  return { props, ref, value: screen.getByLabelText(/^Valor/), op: screen.getByLabelText("Operação") };
}

describe("TableToolbar", () => {
  it.each([
    ["set", "2,5", { op: "set", value: 2.5 }],
    ["add", "3", { op: "add", value: 3 }],
    ["sub", "3", { op: "add", value: -3 }],
    ["scale", "10", { op: "scale", value: 10 }],
  ] as const)("operação %s aplica %s", async (kind, text, expected) => {
    const { props, value, op } = setup();
    await userEvent.selectOptions(op, kind);
    if (kind === "scale") expect(screen.getByText("Valor (%)")).toBeInTheDocument();
    fireEvent.change(value, { target: { value: text } });
    await userEvent.click(screen.getByRole("button", { name: "Aplicar" }));
    expect(props.onOperation).toHaveBeenCalledWith(expected);
    expect(props.onDone).toHaveBeenCalled();
  });

  it("valor inválido mostra o erro acessível; Enter aplica e Escape devolve o foco", () => {
    const { props, value } = setup();
    fireEvent.change(value, { target: { value: "abc" } });
    fireEvent.keyDown(value, { key: "Enter" });
    expect(screen.getByRole("alert")).toHaveTextContent("Digite um número");
    expect(value).toHaveAttribute("aria-invalid", "true");
    expect(value).toHaveAttribute("aria-describedby", "toolbar-error");
    expect(props.onOperation).not.toHaveBeenCalled();
    fireEvent.change(value, { target: { value: "1" } });
    fireEvent.keyDown(value, { key: "Enter" });
    expect(props.onOperation).toHaveBeenCalledWith({ op: "add", value: 1 });
    fireEvent.keyDown(value, { key: "Escape" });
    expect(props.onDone).toHaveBeenCalledTimes(2);
    fireEvent.keyDown(value, { key: "a" });
  });

  it("focusValue (atalhos =, +, −, *) escolhe a operação e foca o campo", () => {
    const { ref, value, op } = setup();
    act(() => ref.current!.focusValue("set"));
    expect(op).toHaveValue("set");
    expect(value).toHaveFocus();
  });

  it("interpolações, suavizar, copiar/colar, desfazer/refazer e toggles chamam os callbacks", async () => {
    const { props } = setup();
    for (const name of ["Interpolar linha", "Interpolar coluna", "Interpolar bloco", "Suavizar"]) {
      await userEvent.click(screen.getByRole("button", { name }));
    }
    expect(vi.mocked(props.onOperation).mock.calls.map((c) => c[0].op)).toEqual(["interp_row", "interp_col", "interp_block", "smooth"]);
    await userEvent.click(screen.getByRole("button", { name: "Copiar" }));
    await userEvent.click(screen.getByRole("button", { name: "Colar" }));
    await userEvent.click(screen.getByRole("button", { name: "Desfazer" }));
    await userEvent.click(screen.getByRole("button", { name: "Refazer" }));
    await userEvent.click(screen.getByRole("button", { name: "Heatmap" }));
    await userEvent.click(screen.getByRole("button", { name: "Exibir em AFR" }));
    await userEvent.click(screen.getByRole("button", { name: "Vista 3D" }));
    for (const fn of [props.onCopy, props.onPaste, props.onUndo, props.onRedo, props.onToggleHeatmap, props.onToggleLambda, props.onToggle3d]) {
      expect(fn).toHaveBeenCalledTimes(1);
    }
  });

  it("seleção de 1 célula desativa as interpolações com a dica (EC-07); AFR ativo mostra 'Exibir em λ'", () => {
    setup({ rect: { r0: 0, r1: 0, c0: 0, c1: 0 }, lambdaDisplay: "afr", is3d: false, canUndo: false });
    for (const name of ["Interpolar linha", "Interpolar coluna", "Interpolar bloco"]) {
      const b = screen.getByRole("button", { name });
      expect(b).toBeDisabled();
      expect(b.getAttribute("title")).toMatch(/selecione/i);
    }
    expect(screen.getByRole("button", { name: "Exibir em λ" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("button", { name: "Vista 3D" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Desfazer" })).toBeDisabled();
  });

  it("tabela sem lambda não mostra o botão AFR", () => {
    setup({ lambdaTable: false });
    expect(screen.queryByRole("button", { name: /Exibir em/ })).not.toBeInTheDocument();
  });

  it("quando onAiTune é fornecido, exibe o seletor de modo e dispara callback ao clicar", async () => {
    const onAiTune = vi.fn();
    const onSetAiAggressiveness = vi.fn();
    setup({ onAiTune, onSetAiAggressiveness, aiAggressiveness: "balanced" });
    const btn = screen.getByRole("button", { name: /Tunar com IA/i });
    expect(btn).toBeInTheDocument();
    await userEvent.click(btn);
    expect(onAiTune).toHaveBeenCalledWith("balanced");

    const select = screen.getByLabelText(/Modo de agressividade da IA/i);
    expect(select).toBeInTheDocument();
    await userEvent.selectOptions(select, "race");
    expect(onSetAiAggressiveness).toHaveBeenCalledWith("race");
  });

  it("quando aiTuning é true, desativa o botão e o seletor e exibe estado de carregamento", () => {
    const onAiTune = vi.fn();
    setup({ onAiTune, aiTuning: true });
    const btn = screen.getByRole("button", { name: /Tunando\.\.\./i });
    expect(btn).toBeDisabled();
    const select = screen.getByLabelText(/Modo de agressividade da IA/i);
    expect(select).toBeDisabled();
  });
});
