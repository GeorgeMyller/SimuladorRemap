/** T193 — TableEditor2D/TableEditor3D: grade até 32×32 virtualizada, seleção, heatmap e teclado (tuning RF-03 a RF-10, RF-17, RF-20; RNF-01, RNF-06). */
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { cellColors, contrastRatio, paletteColor, textColorFor } from "./heatmap";
import { TableEditor3D } from "./TableEditor3D";
import { calibrationFixture, makeApi, table3d } from "./test-utils/fixtures";
import { cellAt, loadedStore, renderTable } from "./test-utils/harness";
import type { WorkspaceStore } from "./workspaceStore";

let store: WorkspaceStore;
beforeEach(() => localStorage.clear());
afterEach(() => store?.stop());

const RPM_32 = Array.from({ length: 32 }, (_, i) => 500 + i * 250);
const MAP_32 = Array.from({ length: 32 }, (_, i) => 20 + i * 10);

async function big() {
  const cal = calibrationFixture();
  cal.tables.ve = table3d("ve", "ve", "%", 0, 150, (r, c) => 40 + r + c, { x: RPM_32, y: MAP_32 });
  store = await loadedStore(makeApi({}, cal));
  return renderTable(store, "ve", "VE");
}

function selected(): string[] {
  return [...document.querySelectorAll('[role="gridcell"][aria-selected="true"]')].map((el) => el.getAttribute("data-cell")!);
}

describe("grade virtualizada (RF-03)", () => {
  it("uma tabela 32×32 monta ≤ 1200 células e só as visíveis", async () => {
    await big();
    const cells = document.querySelectorAll('[role="gridcell"]').length;
    expect(cells).toBeLessThanOrEqual(1200);
    expect(cells).toBeLessThan(32 * 32);
    expect(screen.getByRole("grid")).toHaveAttribute("aria-rowcount", "33");
    expect(screen.getByRole("grid")).toHaveAttribute("aria-colcount", "33");
  });

  it("rolar monta as linhas de baixo", async () => {
    const { grid } = await big();
    expect(document.querySelector('[data-cell="31,0"]')).toBeNull();
    act(() => {
      grid.scrollTop = 31 * 28;
      fireEvent.scroll(grid);
    });
    expect(document.querySelector('[data-cell="31,0"]')).not.toBeNull();
  });

  it("os cabeçalhos mostram os breakpoints e as unidades rpm/kPa", async () => {
    store = await loadedStore();
    renderTable(store, "ve", "VE");
    const headers = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers[0]).toContain("kPa");
    expect(headers[0]).toContain("rev/min");
    expect(headers).toContain("800");
    expect(screen.getAllByRole("rowheader")[0]).toHaveTextContent("20 kPa");
    expect(cellAt(2, 3)).toHaveAttribute("aria-label", expect.stringMatching(/^linha 60 kPa, coluna 2[.,]?000 rev\/min, valor 65[.,]0/));
  });

  it("TableEditor2D: 1×N com uma linha", async () => {
    store = await loadedStore();
    renderTable(store, "boost_target_gear", "Pressão por marcha");
    expect(screen.getAllByRole("gridcell")).toHaveLength(6);
    expect(screen.getAllByRole("rowheader")[0]).toHaveTextContent("kPa");
  });
});

describe("seleção (RF-04)", () => {
  it("Shift+seta-direita 3 vezes a partir de (2,2) seleciona (2,2)–(2,5)", async () => {
    store = await loadedStore();
    const { grid } = renderTable(store, "ve");
    fireEvent.mouseDown(cellAt(2, 2));
    fireEvent.mouseUp(window);
    for (let i = 0; i < 3; i += 1) fireEvent.keyDown(grid, { key: "ArrowRight", shiftKey: true });
    expect(selected().sort()).toEqual(["2,2", "2,3", "2,4", "2,5"]);
  });

  it("clique no cabeçalho da coluna 4 seleciona 16 células numa 16×16", async () => {
    store = await loadedStore();
    renderTable(store, "ve");
    fireEvent.click(document.querySelector('[data-col-header="4"]')!);
    expect(selected()).toHaveLength(16);
    expect(selected().every((c) => c.endsWith(",4"))).toBe(true);
  });

  it("cabeçalho de linha, arrastar e Ctrl/Cmd+A", async () => {
    store = await loadedStore();
    const { grid } = renderTable(store, "ve");
    fireEvent.click(document.querySelector('[data-row-header="1"]')!);
    expect(store.selection("ve").mode).toBe("rows");
    fireEvent.mouseDown(cellAt(0, 0));
    fireEvent.mouseEnter(cellAt(1, 2));
    fireEvent.mouseUp(window);
    expect(selected()).toHaveLength(6);
    fireEvent.keyDown(grid, { key: "a", ctrlKey: true });
    expect(store.selection("ve").mode).toBe("all");
  });

  it("navegação: Tab, Home, End, PageDown e setas atualizam aria-activedescendant", async () => {
    store = await loadedStore();
    const { grid } = renderTable(store, "ve");
    fireEvent.keyDown(grid, { key: "Tab" });
    expect(store.selection("ve").focus).toEqual({ row: 0, col: 1 });
    fireEvent.keyDown(grid, { key: "End" });
    expect(store.selection("ve").focus).toEqual({ row: 0, col: 15 });
    fireEvent.keyDown(grid, { key: "Home" });
    expect(store.selection("ve").focus).toEqual({ row: 0, col: 0 });
    fireEvent.keyDown(grid, { key: "PageDown" });
    expect(store.selection("ve").focus.row).toBeGreaterThan(5);
    fireEvent.keyDown(grid, { key: "End", ctrlKey: true });
    expect(store.selection("ve").focus).toEqual({ row: 15, col: 15 });
    expect(grid.getAttribute("aria-activedescendant")).toContain("-c-15-15");
  });

  it("setas na grade nunca rolam a página; vindas de um botão do editor devolvem o foco à grade", async () => {
    store = await loadedStore();
    const { grid } = renderTable(store, "ve");
    for (const key of ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"]) expect(fireEvent.keyDown(grid, { key })).toBe(false);
    const button = screen.getAllByRole("button")[0]!;
    button.focus();
    expect(fireEvent.keyDown(button, { key: "ArrowDown" })).toBe(false);
    expect(grid).toHaveFocus();
  });
});

describe("edição e operações por teclado (RF-05 a RF-09, RF-20)", () => {
  it("Enter edita a célula e a nova pintura sai em ≤ 100 ms (RNF-01)", async () => {
    store = await loadedStore();
    const { grid } = renderTable(store, "ve");
    fireEvent.keyDown(grid, { key: "Enter" });
    const input = screen.getByRole("textbox", { name: /Editar/ });
    fireEvent.change(input, { target: { value: "92,5" } });
    const t0 = performance.now();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(cellAt(0, 0)).toHaveTextContent(/^92[.,]5$/);
    expect(performance.now() - t0).toBeLessThan(100);
  });

  it("digitar um número abre a edição com esse caractere", async () => {
    store = await loadedStore();
    const { grid } = renderTable(store, "ve");
    fireEvent.keyDown(grid, { key: "7" });
    expect(screen.getByRole("textbox", { name: /Editar/ })).toHaveValue("7");
  });

  it("bloco + '*' 5 % + I + desfazer, só com teclado", async () => {
    store = await loadedStore();
    const { grid } = renderTable(store, "ve");
    for (let i = 0; i < 2; i += 1) fireEvent.keyDown(grid, { key: "ArrowRight", shiftKey: true });
    fireEvent.keyDown(grid, { key: "*" });
    const value = screen.getByLabelText(/Valor/);
    expect(value).toHaveFocus();
    fireEvent.change(value, { target: { value: "5" } });
    fireEvent.keyDown(value, { key: "Enter" });
    expect(store.getSnapshot().tables.ve!.values[0]!.slice(0, 3)).toEqual([63, 64.05, 65.10000000000001]);
    expect(grid).toHaveFocus();
    fireEvent.keyDown(grid, { key: "i" });
    expect(store.getSnapshot().tables.ve!.values[0]![1]).toBeCloseTo(63 + (65.1 - 63) * 0.5, 6);
    fireEvent.keyDown(grid, { key: "z", ctrlKey: true });
    fireEvent.keyDown(grid, { key: "z", ctrlKey: true });
    expect(store.getSnapshot().tables.ve!.values[0]!.slice(0, 3)).toEqual([60, 61, 62]);
    fireEvent.keyDown(grid, { key: "z", ctrlKey: true, shiftKey: true });
    expect(store.getSnapshot().tables.ve!.values[0]![0]).toBe(63);
  });

  it("'=' e '−' focam o campo com a operação; S suaviza; Shift+I interpola bloco", async () => {
    store = await loadedStore();
    const { grid } = renderTable(store, "ve");
    fireEvent.keyDown(grid, { key: "=" });
    expect(screen.getByRole("combobox", { name: /Operação/ })).toHaveValue("set");
    fireEvent.keyDown(grid, { key: "−" });
    expect(screen.getByRole("combobox", { name: /Operação/ })).toHaveValue("sub");
    grid.focus();
    fireEvent.keyDown(grid, { key: "ArrowDown", shiftKey: true });
    fireEvent.keyDown(grid, { key: "ArrowRight", shiftKey: true });
    fireEvent.keyDown(grid, { key: "I", shiftKey: true });
    expect(store.getSnapshot().canUndo).toBe(false); // bloco 2×2 sem interior: sem alteração
    fireEvent.keyDown(grid, { key: "s" });
    expect(store.getSnapshot().canUndo).toBe(true);
  });

  it("valor acima do máximo é preso ao limite com aviso 'valor limitado'", async () => {
    store = await loadedStore();
    renderTable(store, "ve");
    act(() => {
      store.editCell("ve", 0, 0, 999);
    });
    expect(store.getSnapshot().tables.ve!.values[0]![0]).toBe(150);
    expect(store.getSnapshot().notices.at(-1)!.text).toMatch(/valor limitado a 150/);
  });

  it("interpolação degenerada fica desativada com a dica", async () => {
    store = await loadedStore();
    renderTable(store, "ve");
    expect(screen.getByRole("button", { name: "Interpolar bloco" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Interpolar bloco" })).toHaveAttribute("title", "selecione ≥ 2 células numa linha/coluna");
  });

  it("copiar e colar TSV pelos eventos copy/paste com a grade focada (RF-08)", async () => {
    store = await loadedStore();
    const { grid } = renderTable(store, "ve");
    grid.focus();
    fireEvent.keyDown(grid, { key: "ArrowRight", shiftKey: true });
    fireEvent.keyDown(grid, { key: "ArrowRight", shiftKey: true });
    fireEvent.keyDown(grid, { key: "ArrowDown", shiftKey: true });
    const setData = vi.fn();
    fireEvent.copy(grid, { clipboardData: { setData, getData: () => "" } });
    expect(setData).toHaveBeenCalledWith("text/plain", "60\t61\t62\n61\t62\t63");
    fireEvent.keyDown(grid, { key: "Escape" });
    fireEvent.paste(grid, { clipboardData: { getData: () => "1,5\t2.5\tx", setData: vi.fn() } });
    expect(store.getSnapshot().tables.ve!.values[1]!.slice(2, 5)).toEqual([1.5, 2.5, 65]);
    expect(store.getSnapshot().notices.at(-1)!.text).toBe("1 célula ignorada");
  });

  it("botões Copiar/Colar usam a Clipboard API", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    const readText = vi.fn(() => Promise.resolve("7\t8"));
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText, readText } });
    store = await loadedStore();
    renderTable(store, "ve");
    fireEvent.click(screen.getByRole("button", { name: "Copiar" }));
    expect(writeText).toHaveBeenCalledWith("60");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Colar" }));
      await Promise.resolve();
    });
    expect(store.getSnapshot().tables.ve!.values[0]!.slice(0, 2)).toEqual([7, 8]);
  });
});

describe("heatmap acessível (RF-10)", () => {
  it("contraste do texto ≥ 4,5:1 em toda a paleta", () => {
    for (let i = 0; i <= 200; i += 1) {
      const bg = paletteColor(i / 200);
      expect(contrastRatio(bg, textColorFor(bg))).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("células coloridas mostram sempre o valor; modo 'sem cores' disponível", async () => {
    store = await loadedStore();
    renderTable(store, "ve");
    const c = cellAt(0, 0);
    expect(c.style.background).toBe(cellColors(60, 60, 90).background);
    expect(c).toHaveTextContent(/^60[.,]0$/);
    fireEvent.click(screen.getByRole("button", { name: "Heatmap" }));
    expect(cellAt(0, 0).style.background).toBe("");
    expect(cellAt(0, 0)).toHaveTextContent(/^60[.,]0$/);
  });
});

describe("bloqueio durante a puxada (RF-17)", () => {
  it("tabela fora de live_tunable_table_ids fica só leitura com cadeado", async () => {
    store = await loadedStore();
    store.setRunState("running");
    renderTable(store, "boost_target_gear", "Pressão por marcha");
    expect(screen.getByRole("status")).toHaveTextContent("bloqueada durante a puxada");
    expect(screen.getByRole("grid")).toHaveAttribute("aria-readonly", "true");
    expect(store.editCell("boost_target_gear", 0, 0, 160)).toBe(false);
    fireEvent.keyDown(screen.getByRole("grid"), { key: "+" });
    expect(store.getSnapshot().notices.at(-1)!.text).toContain("bloqueada durante a puxada");
  });

  it("tabela live-tunable aceita edição durante a puxada", async () => {
    store = await loadedStore();
    store.setRunState("running");
    render(<TableEditor3D store={store} tableId="ve" title="VE" />);
    expect(within(screen.getByRole("grid")).getAllByRole("gridcell").length).toBeGreaterThan(0);
    act(() => {
      expect(store.editCell("ve", 0, 0, 70)).toBe(true);
    });
  });
});
