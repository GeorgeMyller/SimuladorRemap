/** T178 — GaugeCluster: EGT 960 °C com limite 950 °C fica vermelho com o texto "960 °C" (RF-08). */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GaugeCluster, gaugeSpecs, gaugeValue, zoneFor, type GaugeLimits } from "./GaugeCluster";

const limits: GaugeLimits = { maxRpm: 7000, revLimitRpm: 6800, egtMaxC: 950, boostMaxBar: 2.0, turbo: true };

describe("GaugeCluster", () => {
  it("egt_c = 960 com limite 950 fica na zona vermelha e mostra '960 °C'", () => {
    render(<GaugeCluster values={{ egt_c: 960, rpm: 3000 }} limits={limits} boostUnit="bar" locale="pt-BR" />);
    const egt = screen.getByRole("meter", { name: "EGT" });
    expect(egt).toHaveAttribute("data-zone", "red");
    expect(screen.getByTestId("gauge-value-egt_c")).toHaveTextContent("960 °C");
    expect(egt).toHaveAttribute("aria-valuetext", "960 °C, zona crítico");
  });

  it("tem os 7 gauges com valor numérico legível além da agulha", () => {
    render(
      <GaugeCluster
        values={{ rpm: 5012, map_kpa: 250, baro_kpa: 100, lambda: 0.82, egt_c: 884, iat_c: 41, ect_c: 92, knock_retard_deg: 3.5 }}
        limits={limits}
        boostUnit="psi"
        locale="pt-BR"
      />,
    );
    expect(screen.getAllByRole("meter")).toHaveLength(7);
    expect(screen.getByTestId("gauge-value-rpm")).toHaveTextContent("5012 rpm");
    expect(screen.getByTestId("gauge-value-boost")).toHaveTextContent("21,8 psi");
    expect(screen.getByTestId("gauge-value-lambda")).toHaveTextContent("λ 0,82");
    expect(screen.getByTestId("gauge-value-knock_retard_deg")).toHaveTextContent("3,5°");
    expect(screen.getByRole("meter", { name: "Knock retard" })).toHaveAttribute("data-zone", "yellow");
    expect(screen.getByRole("meter", { name: "EGT" })).toHaveAttribute("data-zone", "green");
    expect(screen.getByRole("meter", { name: "IAT" })).toHaveAttribute("data-zone", "green");
  });

  it("zonas derivadas dos limites do veículo (RPM pelo corte, EGT pelo egt_max_c)", () => {
    const specs = gaugeSpecs(limits, "bar", "pt-BR");
    const rpm = specs.find((s) => s.id === "rpm")!;
    expect(zoneFor(6000, rpm.bands, rpm.fallback)).toBe("green");
    expect(zoneFor(6500, rpm.bands, rpm.fallback)).toBe("yellow");
    expect(zoneFor(6900, rpm.bands, rpm.fallback)).toBe("red");
    const egt = gaugeSpecs({ ...limits, egtMaxC: 1000 }, "bar").find((s) => s.id === "egt_c")!;
    expect(zoneFor(960, egt.bands, egt.fallback)).toBe("yellow");
    const boost = specs.find((s) => s.id === "boost")!;
    expect(gaugeValue(boost, { map_kpa: 250, baro_kpa: 100 }, "bar")).toBeCloseTo(1.5);
    expect(zoneFor(2.1, boost.bands, boost.fallback)).toBe("red");
  });

  it("sem valor mostra '–'; congelado e canal ausente mostram aviso", () => {
    render(<GaugeCluster values={{}} limits={limits} boostUnit="bar" frozen missingChannels={["egt_c"]} />);
    expect(screen.getByTestId("gauge-value-egt_c")).toHaveTextContent("–");
    expect(screen.getByText("sem dados de egt_c")).toBeInTheDocument();
    expect(screen.getByText(/Gauges congelados/)).toBeInTheDocument();
  });
});
