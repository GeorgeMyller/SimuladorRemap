/* eslint-disable @typescript-eslint/unbound-method -- asserções sobre vi.fn */
/** T180 — CarOnRollerView: rotação proporcional ao rolo e vibração proporcional ao RPM (RF-11). */
import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { parseEnvelope } from "@/lib/ws";

import { CarOnRollerView, drawCarScene } from "./CarOnRollerView";
import { CarAnimator, MAX_PARTICLES, STOP_AFTER_FAILURE_S } from "./render/CarAnimator";
import { RenderLoop } from "./render/RenderLoop";
import { TelemetryStore } from "./store";
import { frameEnvelope, installCanvasMock, make2dContext, manualRaf } from "./test-utils/mocks";

const input = (over: Partial<Parameters<CarAnimator["step"]>[1]> = {}) => ({
  rollerSpeedKmh: 100,
  rpm: 4000,
  maxRpm: 7000,
  throttlePct: 100,
  afterfire: 0,
  afterfireSeq: 0,
  ...over,
});

describe("CarAnimator", () => {
  it("rotação das rodas proporcional à velocidade do rolo", () => {
    const a = new CarAnimator();
    a.step(0.05, input({ rollerSpeedKmh: 50 }));
    const slow = a.wheelAngle;
    const b = new CarAnimator();
    b.step(0.05, input({ rollerSpeedKmh: 100 }));
    expect(b.wheelAngle).toBeCloseTo(2 * slow, 9);
    expect(CarAnimator.wheelOmega(36)).toBeCloseTo(10 / 0.31, 6);
  });

  it("amplitude de vibração com rpm = 6000 maior que com rpm = 2000", () => {
    const a = new CarAnimator();
    a.step(0.016, input({ rpm: 2000 }));
    const low = a.vibrationAmp;
    a.step(0.016, input({ rpm: 6000 }));
    expect(a.vibrationAmp).toBeGreaterThan(low);
  });

  it("falha catastrófica: fumaça em ≤ 100 ms e rodas paradas em ≤ 2 s", () => {
    const a = new CarAnimator();
    a.step(0.016, input());
    a.triggerFailure(1907);
    expect(a.smoking).toBe(true);
    a.step(0.05, input());
    expect(a.particles.some((p) => p.kind === "smoke")).toBe(true);
    expect(a.explosionFlash).toBeGreaterThan(0);
    let t = 0.05;
    while (t < STOP_AFTER_FAILURE_S + 0.1) {
      a.step(0.05, input());
      t += 0.05;
    }
    expect(t).toBeLessThanOrEqual(2);
    const before = a.wheelAngle;
    a.step(0.05, input());
    expect(a.wheelAngle).toBe(before);
    a.reset();
    expect(a.smoking).toBe(false);
    expect(a.spinFactor).toBe(1);
  });

  it("chama/faísca no escape por overrun_afterfire, determinística por seq, teto de partículas", () => {
    const a = new CarAnimator();
    const b = new CarAnimator();
    a.step(0.016, input({ afterfire: 2, afterfireSeq: 77 }));
    b.step(0.016, input({ afterfire: 2, afterfireSeq: 77 }));
    expect(a.particles.filter((p) => p.kind === "flame" || p.kind === "spark").length).toBeGreaterThan(0);
    expect(a.particles.map((p) => p.vx)).toEqual(b.particles.map((p) => p.vx));
    a.triggerFailure(1);
    for (let i = 0; i < 400; i += 1) a.step(0.001, input({ afterfire: 0 }));
    expect(a.particles.length).toBeLessThanOrEqual(MAX_PARTICLES);
    a.configure({ maxParticles: 100 });
    expect(a.particles.length).toBeLessThanOrEqual(100);
  });

  it("drawCarScene desenha sem erro", () => {
    const a = new CarAnimator();
    a.triggerFailure(3);
    a.step(0.016, input({ afterfire: 1, afterfireSeq: 2 }));
    const ctx = make2dContext();
    drawCarScene(ctx, a);
    expect(ctx.arc).toHaveBeenCalled();
  });
});

describe("CarOnRollerView", () => {
  it("anima pelo RenderLoop com os canais do store e reage a event.failure", () => {
    const mock = installCanvasMock({ ctx2d: true });
    const r = manualRaf();
    const loop = new RenderLoop({ raf: r.raf, caf: r.caf, doc: null });
    loop.start();
    const store = new TelemetryStore();
    const anim = new CarAnimator();
    const { rerender } = render(<CarOnRollerView store={store} loop={loop} maxRpm={7000} animator={anim} />);
    store.ingest(parseEnvelope(frameEnvelope(1, 1, { rpm: 6000, roller_speed_kmh: 120, overrun_afterfire: 1 }))!);
    act(() => r.tick(16));
    act(() => r.tick(300));
    expect(anim.wheelAngle).toBeGreaterThan(0);
    expect(anim.vibrationAmp).toBeCloseTo(CarAnimator.vibrationFor(6000, 7000));
    expect(screen.getByTestId("roller-speed")).toHaveTextContent("120");
    rerender(<CarOnRollerView store={store} loop={loop} maxRpm={7000} animator={anim} failureSeq={42} />);
    expect(anim.smoking).toBe(true);
    expect(screen.getByRole("img", { name: /fumaça/ })).toBeInTheDocument();
    rerender(<CarOnRollerView store={store} loop={loop} maxRpm={7000} animator={anim} failureSeq={null} />);
    expect(anim.smoking).toBe(false);
    mock.spy.mockRestore();
  });
});
