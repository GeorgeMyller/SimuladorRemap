/* eslint-disable @typescript-eslint/unbound-method -- asserções sobre vi.fn */
/** T012/T035 — Cor térmica pela EGT e camada Visão Térmica / Raio-X (RF-21; D-12). */
import { describe, expect, it } from "vitest";

import { make2dContext } from "../test-utils/mocks";

import { drawThermalLayer, THERMAL_COLD_C, THERMAL_HOT_C, THERMAL_MID_C, thermalColor, thermalCss, type ThermalGeometry } from "./thermal";

const geo = (induction: ThermalGeometry["induction"]): ThermalGeometry => ({ engine: { x: 340, y: 123 }, exhaust: { x: 70, y: 163 }, scale: 5, induction });

describe("thermalColor", () => {
  it("650 °C → vermelho escuro, sem brilho", () => {
    const c = thermalColor(THERMAL_COLD_C);
    expect(c).toMatchObject({ r: 127, g: 29, b: 29, glow: 0 });
  });

  it("~815 °C → laranja com brilho intermediário", () => {
    const c = thermalColor(THERMAL_MID_C);
    expect(c.r).toBeGreaterThan(240);
    expect(c.g).toBeGreaterThan(90);
    expect(c.g).toBeLessThan(140);
    expect(c.b).toBeLessThan(40);
    expect(c.glow).toBeCloseTo(0.5, 1);
  });

  it("980 °C ou mais → amarelo claro brilhante (brilho máximo)", () => {
    const c = thermalColor(THERMAL_HOT_C);
    expect(c.r).toBeGreaterThan(250);
    expect(c.g).toBeGreaterThan(240);
    expect(c.b).toBeGreaterThan(150);
    expect(c.glow).toBe(1);
    expect(thermalColor(1200)).toEqual(c);
  });

  it("abaixo de 650 °C não brilha e tende ao cinza escuro; entrada inválida é cinza", () => {
    expect(thermalColor(500).glow).toBe(0);
    const cold = thermalColor(200);
    expect(Math.abs(cold.r - cold.g)).toBeLessThan(10);
    expect(thermalColor(null)).toEqual(thermalColor(Number.NaN));
    expect(thermalColor(undefined).glow).toBe(0);
  });

  it("interpolação contínua: brilho monotônico e sem saltos de cor", () => {
    let prev = thermalColor(600);
    for (let t = 601; t <= 1000; t += 1) {
      const c = thermalColor(t);
      expect(c.glow).toBeGreaterThanOrEqual(prev.glow);
      expect(Math.abs(c.r - prev.r) + Math.abs(c.g - prev.g) + Math.abs(c.b - prev.b)).toBeLessThan(8);
      prev = c;
    }
  });

  it("thermalCss devolve rgb() estável e em cache (sem alocar por frame)", () => {
    expect(thermalCss(650)).toBe("rgb(127,29,29)");
    expect(thermalCss(813)).toBe(thermalCss(816));
    expect(thermalCss(5000)).toBe(thermalCss(1100));
    expect(thermalCss(null)).toBe(thermalCss(0));
  });
});

describe("drawThermalLayer", () => {
  it("turbo: desenha coletor, turbina com brilho e escape", () => {
    const ctx = make2dContext();
    drawThermalLayer(ctx, geo("turbo"), { egtC: 900, egtPreTurboC: 980 });
    expect(ctx.stroke).toHaveBeenCalled();
    expect(ctx.arc).toHaveBeenCalled();
    // turbina + halo de brilho
    expect((ctx.arc as unknown as { mock: { calls: unknown[] } }).mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it("compressor mecânico (V8): bloco do compressor em cima do motor, sem turbina", () => {
    const ctx = make2dContext();
    drawThermalLayer(ctx, geo("supercharger"), { egtC: 600, egtPreTurboC: null });
    expect(ctx.fillRect).toHaveBeenCalled();
    expect(ctx.stroke).toHaveBeenCalled();
    expect(ctx.globalAlpha).toBe(1);
  });
});
