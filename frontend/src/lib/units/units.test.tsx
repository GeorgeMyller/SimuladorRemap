/** T175 — conversão de unidades e formatação pela locale (cockpit RF-20). */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  boostBar,
  convertBoost,
  convertPower,
  formatBoost,
  formatLambda,
  formatNumber,
  formatPower,
  formatTemperature,
  formatTorque,
  UnitsProvider,
  useUnits,
} from "./index";

describe("lib/units", () => {
  it("power_kw = 164,1 mostra 220,1 whp, 223,1 cv e 164,1 kW", () => {
    expect(formatPower(164.1, "whp", "pt-BR")).toBe("220,1 whp");
    expect(formatPower(164.1, "cv", "pt-BR")).toBe("223,1 cv");
    expect(formatPower(164.1, "kW", "pt-BR")).toBe("164,1 kW");
    expect(convertPower(0.7457, "whp")).toBeCloseTo(1, 6);
  });

  it("map 250 kPa com baro 100 kPa mostra 1,50 bar e 21,8 psi", () => {
    const b = boostBar(250, 100);
    expect(b).toBeCloseTo(1.5, 9);
    expect(formatBoost(b, "bar", "pt-BR")).toBe("1,50 bar");
    expect(formatBoost(b, "psi", "pt-BR")).toBe("21,8 psi");
    expect(convertBoost(1, "psi")).toBeCloseTo(14.5038, 4);
  });

  it("vácuo aparece com sinal negativo", () => {
    expect(formatBoost(boostBar(60, 100), "bar", "pt-BR")).toBe("-0,40 bar");
  });

  it("arredonda pela grandeza e respeita a locale", () => {
    expect(formatLambda(0.8234, "pt-BR")).toBe("0,82");
    expect(formatTemperature(959.6, "pt-BR")).toBe("960 °C");
    expect(formatTorque(350.04, "pt-BR")).toBe("350,0 N·m");
    expect(formatNumber(1234.5, 1, "en-US")).toBe("1234.5");
    expect(formatNumber(-0.001, 1, "pt-BR")).toBe("0,0");
  });

  it("UnitsProvider partilha e altera as unidades", () => {
    function Probe() {
      const { units, setUnits } = useUnits();
      return (
        <button type="button" onClick={() => setUnits({ ...units, power: "kW" })}>
          {units.power}
        </button>
      );
    }
    render(
      <UnitsProvider>
        <Probe />
      </UnitsProvider>,
    );
    const btn = screen.getByRole("button");
    expect(btn).toHaveTextContent("whp");
    fireEvent.click(btn);
    expect(screen.getByRole("button")).toHaveTextContent("kW");
  });

  it("useUnits fora de provider devolve os padrões", () => {
    function Probe() {
      return <span>{useUnits().units.boost}</span>;
    }
    render(<Probe />);
    expect(screen.getByText("bar")).toBeInTheDocument();
  });
});
