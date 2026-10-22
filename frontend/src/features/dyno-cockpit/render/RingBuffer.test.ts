/** T173 — RingBuffer (3600 amostras por canal) e RenderLoop desacoplado do onmessage (RF-03; D-22). */
import { describe, expect, it, vi } from "vitest";

import { TelemetryStore } from "../store";
import { FakeWebSocket, frameEnvelope, manualRaf } from "../test-utils/mocks";
import { TelemetrySocket } from "@/lib/ws";

import { RenderLoop } from "./RenderLoop";
import { DEFAULT_CAPACITY, RingBuffer } from "./RingBuffer";

describe("RingBuffer", () => {
  it("capacidade padrão 3600 com Float64Array (t) e Float32Array (v)", () => {
    const b = new RingBuffer();
    expect(b.capacity).toBe(DEFAULT_CAPACITY);
    expect(DEFAULT_CAPACITY).toBe(3600);
    expect(b.t).toBeInstanceOf(Float64Array);
    expect(b.v).toBeInstanceOf(Float32Array);
    expect(b.latest()).toBeUndefined();
  });

  it("inserir 5000 amostras num buffer de 3600 mantém as 3600 mais recentes em ordem", () => {
    const b = new RingBuffer(3600);
    for (let i = 0; i < 5000; i += 1) b.push(i / 60, i);
    expect(b.size).toBe(3600);
    const { t, v } = b.toArrays();
    expect(v[0]).toBe(1400);
    expect(v[3599]).toBe(4999);
    for (let i = 1; i < v.length; i += 1) {
      expect(v[i]! - v[i - 1]!).toBe(1);
      expect(t[i]!).toBeGreaterThan(t[i - 1]!);
    }
    expect(b.latest()).toEqual({ t: 4999 / 60, v: 4999 });
  });

  it("window(from, to) devolve só o intervalo, em ordem; valueAt dá a amostra mais próxima", () => {
    const b = new RingBuffer(10);
    for (let i = 0; i < 15; i += 1) b.push(i, i * 10);
    const w = b.window(7, 9);
    expect([...w.t]).toEqual([7, 8, 9]);
    expect([...w.v]).toEqual([70, 80, 90]);
    expect(b.valueAt(11.4)).toBe(110);
    expect(b.at(0)).toEqual({ t: 5, v: 50 });
    b.clear();
    expect(b.size).toBe(0);
  });

  it("rejeita capacidade inválida", () => {
    expect(() => new RingBuffer(0)).toThrow(RangeError);
  });
});

describe("RenderLoop", () => {
  it("desenha a cada rAF, independente da chegada dos frames", () => {
    const r = manualRaf();
    const loop = new RenderLoop({ raf: r.raf, caf: r.caf, doc: null });
    const draws: number[] = [];
    loop.add((now) => draws.push(now));
    loop.start();
    for (let i = 1; i <= 5; i += 1) r.tick(i * 16.67);
    expect(draws).toHaveLength(5);
    loop.stop();
    expect(r.pending).toBe(0);
  });

  it("o handler onmessage só escreve no store; nenhum desenho dentro dele", () => {
    FakeWebSocket.reset();
    const r = manualRaf();
    const loop = new RenderLoop({ raf: r.raf, caf: r.caf, doc: null });
    const store = new TelemetryStore();
    const draw = vi.fn();
    loop.add(draw);
    loop.start();
    const socket = new TelemetrySocket({ url: "ws://x/ws/v1/sessions/s/telemetry", createSocket: (u) => new FakeWebSocket(u), onEnvelope: (e) => store.ingest(e) });
    socket.connect();
    const ws = FakeWebSocket.last();
    ws.open();
    const durations: number[] = [];
    // 50 FPS de frames (sem rAF): o desenho não corre. Os 20 primeiros aquecem o JIT/zod
    // (sem eles o p95 mede compilação, não o handler) e não entram na medição.
    for (let i = 1; i <= 120; i += 1) {
      const t0 = performance.now();
      ws.receive(frameEnvelope(i, i, { rpm: 2000 + i * 10, power_kw: 100, torque_nm: 300 }));
      if (i > 20) durations.push(performance.now() - t0);
    }
    expect(draw).not.toHaveBeenCalled();
    expect(store.buffer("rpm").size).toBe(120);
    durations.sort((a, b) => a - b);
    expect(durations[Math.floor(durations.length * 0.95)]!).toBeLessThan(4);
    r.tick(16);
    expect(draw).toHaveBeenCalledTimes(1);
    socket.close();
    loop.stop();
  });

  it("pausa com o separador oculto e retoma ao voltar (EC-10)", () => {
    const r = manualRaf();
    const listeners: Record<string, () => void> = {};
    const doc = {
      visibilityState: "visible" as DocumentVisibilityState,
      addEventListener: (k: string, cb: () => void) => {
        listeners[k] = cb;
      },
      removeEventListener: () => undefined,
    };
    const loop = new RenderLoop({ raf: r.raf, caf: r.caf, doc: doc as never });
    loop.start();
    expect(r.pending).toBe(1);
    doc.visibilityState = "hidden";
    listeners.visibilitychange?.();
    expect(r.pending).toBe(0);
    doc.visibilityState = "visible";
    listeners.visibilitychange?.();
    expect(r.pending).toBe(1);
  });

  it("mede FPS e sinaliza degradação após 5 s abaixo de 30 FPS (EC-12)", () => {
    const r = manualRaf();
    const loop = new RenderLoop({ raf: r.raf, caf: r.caf, doc: null });
    const degraded = vi.fn();
    loop.onDegradedChange(degraded);
    loop.start();
    let t = 0;
    for (let i = 0; i < 200; i += 1) {
      t += 50; // 20 FPS
      r.tick(t);
    }
    expect(loop.fps).toBeCloseTo(20, 0);
    expect(degraded).toHaveBeenCalledWith(true);
    expect(loop.degraded).toBe(true);
  });

  it("um painel que lança não derruba os outros", () => {
    const r = manualRaf();
    const loop = new RenderLoop({ raf: r.raf, caf: r.caf, doc: null });
    const ok = vi.fn();
    const err = vi.spyOn(console, "error").mockImplementation(() => undefined);
    loop.add(() => {
      throw new Error("x");
    });
    loop.add(ok);
    loop.start();
    r.tick(16);
    expect(ok).toHaveBeenCalled();
    expect(err).toHaveBeenCalled();
  });
});
