import { describe, expect, it } from "vitest";

import {
  MockAudioContext,
  MockCanvasRenderingContext2D,
  MockWebSocket,
  setCanvasSupport,
} from "./index";

function pickContext(canvas: HTMLCanvasElement): string {
  if (canvas.getContext("webgl2")) return "webgl2";
  if (canvas.getContext("webgl")) return "webgl";
  if (canvas.getContext("2d")) return "2d";
  return "none";
}

describe("mock de canvas", () => {
  it("fornece um contexto 2D que regista chamadas", () => {
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");
    expect(ctx).toBeInstanceOf(MockCanvasRenderingContext2D);
    ctx?.fillRect(0, 0, 10, 10);
    ctx?.setLineDash([2, 2]);
    expect(ctx?.getLineDash()).toEqual([2, 2]);
    expect(ctx?.measureText("960 °C").width).toBeGreaterThan(0);
    expect((ctx as unknown as MockCanvasRenderingContext2D).callsOf("fillRect")).toHaveLength(1);
    expect(canvas.getContext("2d")).toBe(ctx);
    expect(canvas.toDataURL()).toMatch(/^data:image\/png/);
    expect(canvas.getContext("bitmaprenderer")).toBeNull();
  });

  it("simula a cadeia de fallback WebGL2 → WebGL1 → Canvas 2D", () => {
    expect(pickContext(document.createElement("canvas"))).toBe("webgl2");
    setCanvasSupport({ webgl2: false });
    expect(pickContext(document.createElement("canvas"))).toBe("webgl");
    setCanvasSupport({ webgl: false });
    expect(pickContext(document.createElement("canvas"))).toBe("2d");
    setCanvasSupport({ "2d": false });
    expect(pickContext(document.createElement("canvas"))).toBe("none");
  });

  it("aceita chamadas WebGL arbitrárias", () => {
    const gl = document.createElement("canvas").getContext("webgl2");
    expect(gl).not.toBeNull();
    if (!gl) return;
    const shader = gl.createShader(gl.VERTEX_SHADER);
    expect(shader).toBeTruthy();
    gl.shaderSource(shader as WebGLShader, "void main(){}");
    expect(gl.getShaderParameter(shader as WebGLShader, gl.COMPILE_STATUS)).toBe(true);
    expect(typeof gl.ARRAY_BUFFER).toBe("number");
    expect(document.createElement("canvas").getContext("experimental-webgl" as "webgl")).toBeTruthy();
  });
});

describe("mock de Web Audio", () => {
  it("nasce suspenso e retoma com gesto", async () => {
    const ctx = new AudioContext();
    expect(ctx.state).toBe("suspended");
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain).connect(ctx.destination);
    osc.frequency.setValueAtTime(120, ctx.currentTime);
    gain.gain.linearRampToValueAtTime(0, 1);
    osc.start();
    osc.stop(1);
    ctx.createBiquadFilter().frequency.exponentialRampToValueAtTime(800, 1);
    await ctx.resume();
    expect(ctx.state).toBe("running");
    expect(MockAudioContext.instances).toHaveLength(1);
    const mock = MockAudioContext.instances[0];
    mock?.advance(0.5);
    expect(mock?.currentTime).toBe(0.5);
    expect(mock?.createBuffer(1, 48, 48_000).duration).toBe(0.001);
    await ctx.suspend();
    await ctx.close();
    expect(ctx.state).toBe("closed");
  });
});

describe("mock de WebSocket", () => {
  it("permite controlar o servidor e inspecionar envios", () => {
    const ws = new WebSocket("ws://localhost/ws/v1/sessions/s1/telemetry");
    const received: unknown[] = [];
    const closes: number[] = [];
    ws.onmessage = (event: MessageEvent<string>) => received.push(JSON.parse(event.data));
    ws.addEventListener("close", (event) => closes.push(event.code));
    const server = MockWebSocket.last();
    expect(server?.url).toContain("/ws/v1/");
    expect(() => ws.send("cedo")).toThrow();
    server?.open();
    expect(ws.readyState).toBe(WebSocket.OPEN);
    ws.send(JSON.stringify({ v: 1, type: "control.ping", payload: { nonce: "a" } }));
    expect(server?.sentJson()).toEqual([{ v: 1, type: "control.ping", payload: { nonce: "a" } }]);
    server?.receive({ v: 1, type: "run.state", seq: 0 });
    expect(received).toEqual([{ v: 1, type: "run.state", seq: 0 }]);
    server?.serverClose(1011, "erro");
    expect(closes).toEqual([1011]);
    ws.close();
    expect(closes).toEqual([1011]);
  });

  it("simula falha de ligação", () => {
    const ws = new WebSocket("ws://localhost/ws/v1/x");
    let errors = 0;
    ws.onerror = () => {
      errors += 1;
    };
    MockWebSocket.last()?.fail();
    expect(errors).toBe(1);
    expect(ws.readyState).toBe(WebSocket.CLOSED);
    expect(MockWebSocket.instances).toHaveLength(1);
  });
});

describe("polyfills", () => {
  it("expõe requestAnimationFrame, matchMedia e ResizeObserver", async () => {
    const t = await new Promise<number>((resolve) => requestAnimationFrame(resolve));
    expect(t).toBeGreaterThanOrEqual(0);
    cancelAnimationFrame(requestAnimationFrame(() => undefined));
    expect(window.matchMedia("(prefers-reduced-motion: reduce)").matches).toBe(false);
    const observer = new ResizeObserver(() => undefined);
    observer.observe(document.body);
    observer.disconnect();
  });
});
