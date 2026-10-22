/** Table3DView: superfície em chunk lazy sincronizada com a seleção e fallback 2D sem WebGL (tuning RF-12, EC-11; D-22). */
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setCanvasSupport } from "@/test/mocks";

import { buildSurface, contourSegments, vertexIndex, webglAvailable } from "./Table3DGeometry";
import { Table3DView } from "./Table3DView";
import { loadedStore, renderTable } from "./test-utils/harness";
import type { WorkspaceStore } from "./workspaceStore";

vi.mock("./Table3DSurface", () => ({
  default: (props: { focus: { row: number; col: number }; onFallback: () => void }) => (
    <div data-testid="table3d-surface" data-highlight={`${props.focus.row},${props.focus.col}`}>
      <button type="button" onClick={props.onFallback}>
        perder contexto
      </button>
    </div>
  ),
}));

const values = Array.from({ length: 8 }, (_, r) => Array.from({ length: 10 }, (_, c) => r * 10 + c));

let store: WorkspaceStore | null = null;
beforeEach(() => localStorage.clear());
afterEach(() => {
  store?.stop();
  store = null;
});

describe("geometria (RF-12)", () => {
  it("vértice da célula (5,7) e malha ny × nx", () => {
    const s = buildSurface(values);
    expect(s.nx).toBe(10);
    expect(s.ny).toBe(8);
    expect(vertexIndex(5, 7, 10)).toBe(57);
    expect(s.positions[57 * 3 + 1]).toBeCloseTo((57 - 0) / 79, 5);
    expect(s.indices.length).toBe(9 * 7 * 6);
    expect(s.colors.every((v) => v >= 0 && v <= 1)).toBe(true);
  });

  it("contorno gera segmentos dentro da grade", () => {
    const segs = contourSegments(values, 4);
    expect(segs.length).toBeGreaterThan(0);
    for (const s of segs) {
      expect(s.x1).toBeGreaterThanOrEqual(0);
      expect(s.x2).toBeLessThanOrEqual(9);
      expect(s.y2).toBeLessThanOrEqual(7);
    }
    expect(contourSegments([[1, 1], [1, 1]])).toEqual([]);
  });
});

describe("Table3DView", () => {
  it("selecionar a célula (5,7) destaca o vértice correspondente", async () => {
    const { rerender } = render(<Table3DView values={values} focus={{ row: 0, col: 0 }} label="VE" />);
    expect(await screen.findByTestId("table3d-surface")).toHaveAttribute("data-highlight", "0,0");
    rerender(<Table3DView values={values} focus={{ row: 5, col: 7 }} label="VE" />);
    expect(screen.getByTestId("table3d-surface")).toHaveAttribute("data-highlight", "5,7");
  });

  it("sem WebGL aparece o contorno 2D e o selo 'modo compatível'", () => {
    setCanvasSupport({ webgl: false, webgl2: false });
    expect(webglAvailable()).toBe(false);
    render(<Table3DView values={values} focus={{ row: 5, col: 7 }} label="VE" />);
    expect(screen.getByTestId("compat-badge")).toHaveTextContent("modo compatível");
    expect(screen.getByTestId("contour-view")).toHaveAttribute("data-highlight", "5,7");
    expect(screen.queryByTestId("table3d-surface")).not.toBeInTheDocument();
  });

  it("contexto perdido cai no contorno", async () => {
    render(<Table3DView values={values} focus={{ row: 1, col: 1 }} label="VE" />);
    fireEvent.click(await screen.findByRole("button", { name: "perder contexto" }));
    expect(screen.getByTestId("compat-badge")).toBeInTheDocument();
  });

  it("F3 alterna a vista 3D no editor e acompanha a seleção da grade", async () => {
    store = await loadedStore();
    const { grid } = renderTable(store, "ve", "VE");
    expect(screen.queryByRole("figure")).not.toBeInTheDocument();
    fireEvent.keyDown(grid, { key: "F3" });
    expect(await screen.findByTestId("table3d-surface")).toBeInTheDocument();
    fireEvent.keyDown(grid, { key: "ArrowDown" });
    fireEvent.keyDown(grid, { key: "ArrowRight" });
    expect(screen.getByTestId("table3d-surface")).toHaveAttribute("data-highlight", "1,1");
    fireEvent.click(screen.getByRole("button", { name: "Vista 3D" }));
    expect(screen.queryByTestId("table3d-surface")).not.toBeInTheDocument();
  });
});
