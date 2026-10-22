/** T199 — TuningWarnings: avanço 4° acima do MBT estimado gera W-01 sem bloquear a gravação; W-02 a W-06 (tuning RF-19, T452). */
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { WARNING_TEXTS } from "./messages";
import type { GridTable } from "./model";
import { calibrationFixture, makeApi } from "./test-utils/fixtures";
import { loadedStore, renderWorkspace } from "./test-utils/harness";
import { TuningWarnings } from "./TuningWarnings";
import { computeWarnings, interp2, strategyWarnings, tableWarnings, type WarningContext } from "./warnings";

beforeEach(() => localStorage.clear());

function t(kind: string, values: number[][], y: { quantity: string; values: number[]; unit: string } = { quantity: "map_kpa", values: [100, 200], unit: "kPa" }): GridTable {
  return {
    tableId: kind, kind, unit: "", min: -100, max: 1000, decimals: 1, liveTunable: true, cylinder: null, description: "",
    x: { quantity: "rpm", values: [2000, 4000], unit: "rpm", sourceChannel: "rpm" },
    y: { ...y, sourceChannel: y.quantity },
    values,
  };
}

const ctx = (over: Partial<WarningContext> = {}): WarningContext => ({
  tables: [],
  strategies: {},
  mbtReference: { x_values: [2000, 4000], y_values: [100, 200], z_values: [[30, 30], [20, 20]] },
  maxRpm: 7000,
  boostMaxKpa: 250,
  ...over,
});

describe("regras W-01 a W-06", () => {
  it("W-01: avanço 4° acima do MBT estimado (limiar MBT + 2°)", () => {
    const w = tableWarnings(t("ignition_base", [[34, 31], [22, 21]]), ctx());
    expect(w.filter((x) => x.code === "W-01").map((x) => [x.row, x.col])).toEqual([[0, 0]]);
    expect(w[0]!.detail).toMatch(/\+4[.,]0°/);
  });

  it("W-01 inativo sem mbt_reference", () => {
    expect(tableWarnings(t("ignition_base", [[60, 60], [60, 60]]), ctx({ mbtReference: null })).filter((x) => x.code === "W-01")).toHaveLength(0);
  });

  it("W-02: lambda > 0,90 com MAP ≥ 1,5 × atmosférica ou carga ≥ 80 %", () => {
    expect(tableWarnings(t("lambda_target", [[0.95, 0.95], [0.92, 0.85]]), ctx()).filter((x) => x.code === "W-02").map((x) => [x.row, x.col])).toEqual([[1, 0]]);
    const load = t("lambda_target", [[0.95], [0.95]], { quantity: "load_pct", values: [50, 80], unit: "%" });
    load.x = { ...load.x, values: [2000] };
    expect(tableWarnings(load, ctx()).filter((x) => x.code === "W-02").map((x) => x.row)).toEqual([1]);
  });

  it("W-03: alvo de boost acima do máximo do turbo", () => {
    expect(tableWarnings(t("boost_target", [[200, 260], [240, 250]]), ctx()).filter((x) => x.code === "W-03")).toHaveLength(1);
    expect(strategyWarnings(ctx({ strategies: { boost_control: { overboost_kpa: 300 } } }))[0]!.code).toBe("W-03");
  });

  it("W-04: limitador acima de max_rpm; W-05: pops agressivos", () => {
    expect(strategyWarnings(ctx({ strategies: { rev_limiter: { hard_rpm: 7300, enabled: true } } })).map((w) => w.code)).toEqual(["W-04"]);
    const pops = strategyWarnings(ctx({ strategies: { overrun: { pops_enabled: true, ign_advance_deg: -20.5, fuel_cut_delay_s: 1.6 } } }));
    expect(pops.map((w) => [w.code, w.field])).toEqual([
      ["W-05", "overrun.ign_advance_deg"],
      ["W-05", "overrun.fuel_cut_delay_s"],
    ]);
    expect(strategyWarnings(ctx({ strategies: { overrun: { pops_enabled: false, ign_advance_deg: -20 } } }))).toHaveLength(0);
  });

  it("W-06: degrau > 15 % (VE) ou > 6° (ignição) entre vizinhas", () => {
    expect(tableWarnings(t("ve", [[80, 100], [80, 81]]), ctx()).filter((x) => x.code === "W-06").map((x) => [x.row, x.col])).toEqual([[0, 1], [1, 1]]);
    expect(tableWarnings(t("ignition_base", [[20, 27], [20, 20]]), ctx({ mbtReference: null })).filter((x) => x.code === "W-06")).toHaveLength(2);
  });

  it("interp2 com clamp nas bordas", () => {
    expect(interp2([0, 10], [0, 10], [[0, 10], [10, 20]], 5, 5)).toBe(10);
    expect(interp2([0, 10], [0, 10], [[0, 10], [10, 20]], -5, 50)).toBe(10);
  });

  it("textos pt-BR centralizados com link de ajuda", () => {
    for (const code of ["W-01", "W-02", "W-03", "W-04", "W-05", "W-06"] as const) {
      expect(WARNING_TEXTS[code].message.length).toBeGreaterThan(10);
      expect(WARNING_TEXTS[code].helpHref).toBe(`#ajuda-${code.toLowerCase()}`);
    }
  });
});

describe("painel e workspace (RF-19)", () => {
  it("mostra o ícone âmbar, a explicação e o link de ajuda; sem MBT indica indisponível", () => {
    const warnings = computeWarnings(ctx({ tables: [t("ignition_base", [[34, 30], [20, 20]])] }));
    render(<TuningWarnings warnings={warnings} mbtAvailable={false} />);
    const item = document.querySelector('[data-warning="W-01"]')!;
    expect(item).toHaveTextContent("Avanço acima do MBT estimado");
    expect(item.querySelector('[aria-label="aviso"]')).not.toBeNull();
    expect(screen.getAllByRole("link", { name: "ajuda" })[0]).toHaveAttribute("href", "#ajuda-w-01");
    expect(screen.getByText(/W-01: MBT estimado indisponível/)).toBeInTheDocument();
    expect(document.getElementById("ajuda-w-01")).not.toBeNull();
  });

  it("avanço 4° acima do MBT numa célula gera W-01 e gravar continua permitido", async () => {
    const api = makeApi();
    const store = await loadedStore(api);
    act(() => {
      store.editCell("ignition_base", 0, 0, 34);
    });
    const warnings = computeWarnings({
      tables: Object.values(store.getSnapshot().tables),
      strategies: {},
      mbtReference: { x_values: [800, 8000], y_values: [20, 320], z_values: [[30, 30], [30, 30]] },
      maxRpm: 7200,
      boostMaxKpa: null,
    });
    expect(warnings.some((w) => w.code === "W-01" && w.tableId === "ignition_base" && w.row === 0 && w.col === 0)).toBe(true);
    await act(async () => {
      await store.saveVersion("avanço alto");
    });
    expect(api.putCalibration).toHaveBeenCalled();
    store.stop();
  });

  it("o workspace marca a célula com aviso e lista no painel", async () => {
    const cal = calibrationFixture();
    renderWorkspace(makeApi({}, cal));
    await screen.findByTestId("workspace-profile");
    act(() => {
      document.querySelector<HTMLButtonElement>('[data-nav-item="ign.base"]')!.click();
    });
    expect(screen.getByRole("heading", { name: /Avisos \(\d+\)/ })).toBeInTheDocument();
    expect(document.querySelector('[role="gridcell"] [data-warn="W-01"]')).not.toBeNull();
  });
});
