/** T012/T038 — Pedal progressivo: segurar Espaço sobe 120 %/s, soltar fecha (RF-22; D-13). */
import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RunControls } from "./RunControls";
import { manualRaf } from "./test-utils/mocks";
import { HOLD_RATE_PCT_PER_S, holdTarget, useHoldThrottle, type HoldThrottleOptions } from "./useHoldThrottle";

function setup(over: Partial<HoldThrottleOptions> = {}) {
  const r = manualRaf();
  let clock = 0;
  const onChange = vi.fn();
  const opts: HoldThrottleOptions = { listen: true, enabled: true, value: 0, onChange, raf: r.raf, caf: r.caf, now: () => clock, ...over };
  const hook = renderHook((p: HoldThrottleOptions) => useHoldThrottle(p), { initialProps: opts });
  const advance = (ms: number, stepMs = 16) => {
    for (let t = 0; t < ms; t += stepMs) {
      clock += stepMs;
      act(() => r.tick(clock));
    }
  };
  return { ...hook, onChange, advance, raf: r, opts };
}

const space = (type: "keyDown" | "keyUp", init: KeyboardEventInit = {}, target: Window | Element = window) =>
  fireEvent[type](target, { key: " ", code: "Space", ...init });

describe("holdTarget", () => {
  it("sobe a 120 %/s a partir do valor inicial, preso em 100", () => {
    expect(HOLD_RATE_PCT_PER_S).toBe(120);
    expect(holdTarget(0, 500)).toBe(60);
    expect(holdTarget(30, 250)).toBe(60);
    expect(holdTarget(0, 2000)).toBe(100);
    expect(holdTarget(0, -5)).toBe(0);
  });
});

describe("useHoldThrottle", () => {
  it("segurar Espaço 1 s leva o pedal a ≥ 90 %; soltar leva a 0 % de imediato", () => {
    const { onChange, advance, result } = setup();
    space("keyDown");
    expect(result.current.holding).toBe(true);
    advance(1000);
    expect(onChange.mock.calls.at(-1)![0]).toBeGreaterThanOrEqual(90);
    const t0 = performance.now();
    space("keyUp");
    expect(onChange).toHaveBeenLastCalledWith(0);
    expect(performance.now() - t0).toBeLessThanOrEqual(150);
    expect(result.current.holding).toBe(false);
  });

  it("para de pedir frames ao chegar a 100 % e nunca passa de 100", () => {
    const { onChange, advance, raf } = setup();
    space("keyDown");
    advance(1500);
    expect(Math.max(...onChange.mock.calls.map((c) => c[0] as number))).toBe(100);
    expect(raf.pending).toBe(0);
  });

  it("repetição de keydown é ignorada (não reinicia a rampa)", () => {
    const { onChange, advance } = setup();
    space("keyDown");
    advance(400);
    const mid = onChange.mock.calls.at(-1)![0] as number;
    space("keyDown", { repeat: true });
    advance(16);
    expect(onChange.mock.calls.at(-1)![0]).toBeGreaterThanOrEqual(mid);
  });

  it("preventDefault no Espaço (não rola a página nem aciona botões focados)", () => {
    setup();
    const down = new KeyboardEvent("keydown", { key: " ", code: "Space", cancelable: true });
    window.dispatchEvent(down);
    expect(down.defaultPrevented).toBe(true);
    const up = new KeyboardEvent("keyup", { key: " ", code: "Space", cancelable: true });
    window.dispatchEvent(up);
    expect(up.defaultPrevented).toBe(true);
  });

  it("ignora campos de texto e modificadores", () => {
    const { onChange, result } = setup();
    const input = document.createElement("input");
    document.body.appendChild(input);
    space("keyDown", {}, input);
    expect(result.current.holding).toBe(false);
    space("keyDown", { ctrlKey: true });
    expect(result.current.holding).toBe(false);
    expect(onChange).not.toHaveBeenCalled();
    input.remove();
  });

  it("respeita enabled (puxada em curso) e listen (diálogo aberto)", () => {
    const { onChange, result, rerender, opts } = setup({ enabled: false });
    space("keyDown");
    expect(result.current.holding).toBe(false);
    rerender({ ...opts, enabled: true, listen: false });
    const ev = new KeyboardEvent("keydown", { key: " ", code: "Space", cancelable: true });
    window.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(false);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("desativar durante a rampa interrompe; perder o foco da janela solta o pedal", () => {
    const { onChange, advance, result, rerender, opts } = setup();
    space("keyDown");
    advance(200);
    rerender({ ...opts, enabled: false });
    expect(result.current.holding).toBe(false);
    rerender({ ...opts, enabled: true });
    space("keyDown");
    advance(100);
    fireEvent.blur(window);
    expect(onChange).toHaveBeenLastCalledWith(0);
    expect(result.current.holding).toBe(false);
  });
});

describe("RunControls com acelerador de mola", () => {
  it("Espaço sobe a borboleta e soltar envia 0 pelo ThrottleSender; W/S continuam ±5 %", () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "requestAnimationFrame", "cancelAnimationFrame", "performance"] });
    const onThrottle = vi.fn();
    render(<RunControls state={{ kind: "ready" }} defaultEndRpm={6600} onStart={vi.fn()} onAbort={vi.fn()} onThrottle={onThrottle} arrowKeys />);
    space("keyDown");
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(Number(screen.getByRole("slider", { name: "Borboleta" }).getAttribute("value"))).toBeGreaterThanOrEqual(90);
    space("keyUp");
    act(() => {
      vi.advanceTimersByTime(150);
    });
    expect(onThrottle).toHaveBeenLastCalledWith(0);
    expect(screen.getByRole("slider", { name: "Borboleta" })).toHaveValue("0");
    fireEvent.keyDown(window, { key: "w" });
    expect(screen.getByRole("slider", { name: "Borboleta" })).toHaveValue("5");
    vi.useRealTimers();
  });
});
