/* eslint-disable @typescript-eslint/require-await -- mocks assíncronos */
/**
 * Mocks de teste da cockpit (RNF-09): WebSocket, Canvas 2D/WebGL, Web Audio e uPlot.
 * Ficam na feature para não depender do `src/test/setup.ts` partilhado.
 */
import { vi } from "vitest";

// ---------------------------------------------------------------- WebSocket
export class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  readonly url: string;
  readyState = 0;
  sent: string[] = [];
  onopen: ((ev: Event) => unknown) | null = null;
  onclose: ((ev: CloseEvent) => unknown) | null = null;
  onerror: ((ev: Event) => unknown) | null = null;
  onmessage: ((ev: MessageEvent) => unknown) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  static reset(): void {
    FakeWebSocket.instances = [];
  }

  static last(): FakeWebSocket {
    const ws = FakeWebSocket.instances.at(-1);
    if (!ws) throw new Error("nenhum FakeWebSocket criado");
    return ws;
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(code = 1000, reason = ""): void {
    if (this.readyState === 3) return;
    this.readyState = 3;
    this.onclose?.({ code, reason } as CloseEvent);
  }

  // Lado do servidor.
  open(): void {
    this.readyState = 1;
    this.onopen?.(new Event("open"));
  }

  receive(data: unknown): void {
    this.onmessage?.({ data: typeof data === "string" ? data : JSON.stringify(data) } as MessageEvent);
  }

  drop(code = 1011, reason = ""): void {
    this.readyState = 3;
    this.onclose?.({ code, reason } as CloseEvent);
  }

  sentMessages(): { type: string; payload: Record<string, unknown> }[] {
    return this.sent.map((s) => JSON.parse(s) as { type: string; payload: Record<string, unknown> });
  }
}

export function frameEnvelope(seq: number, frameIndex: number, channels: Record<string, number | null>, extra: Record<string, unknown> = {}) {
  return {
    v: 1,
    type: "telemetry.frame",
    seq,
    t_sim_s: frameIndex / 50,
    payload: {
      session_id: "s1",
      run_id: "r1",
      frame_index: frameIndex,
      window_ticks: 20,
      channels,
      stats: { fps_actual: 50, dropped_frames: 0, dropped_events: 0, real_time_factor: 1, tick: frameIndex * 20 },
      ...extra,
    },
  };
}

// ---------------------------------------------------------------- Canvas
export interface CanvasMockOptions {
  webgl2?: boolean;
  webgl?: boolean;
  ctx2d?: boolean;
}

export function make2dContext(): CanvasRenderingContext2D {
  const handler: ProxyHandler<Record<string, unknown>> = {
    get(target, prop: string) {
      if (prop in target) return target[prop];
      const fn = vi.fn();
      target[prop] = fn;
      return fn;
    },
    set(target, prop: string, value) {
      target[prop] = value;
      return true;
    },
  };
  const base: Record<string, unknown> = {
    createImageData: vi.fn((w: number, h: number) => ({ width: w, height: h, data: new Uint8ClampedArray(w * h * 4) })),
    getImageData: vi.fn((_x: number, _y: number, w: number, h: number) => ({ width: w, height: h, data: new Uint8ClampedArray(w * h * 4) })),
    measureText: vi.fn(() => ({ width: 10 })),
  };
  return new Proxy(base, handler) as unknown as CanvasRenderingContext2D;
}

export function makeWebGLContext(): WebGLRenderingContext {
  const base: Record<string, unknown> = {
    COMPILE_STATUS: 0x8b81,
    LINK_STATUS: 0x8b82,
    VERTEX_SHADER: 0x8b31,
    FRAGMENT_SHADER: 0x8b30,
    drawingBufferWidth: 720,
    drawingBufferHeight: 220,
    createShader: vi.fn(() => ({})),
    createProgram: vi.fn(() => ({})),
    createBuffer: vi.fn(() => ({})),
    createTexture: vi.fn(() => ({})),
    getShaderParameter: vi.fn(() => true),
    getProgramParameter: vi.fn(() => true),
    getAttribLocation: vi.fn(() => 0),
    getUniformLocation: vi.fn(() => ({})),
  };
  return new Proxy(base, {
    get(target, prop: string) {
      if (prop in target) return target[prop];
      const fn = vi.fn();
      target[prop] = fn;
      return fn;
    },
  }) as unknown as WebGLRenderingContext;
}

/** Substitui `HTMLCanvasElement.prototype.getContext` com as superfícies pedidas. */
export function installCanvasMock(opts: CanvasMockOptions = { ctx2d: true }) {
  const contexts = new WeakMap<HTMLCanvasElement, unknown>();
  const spy = vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(function (this: HTMLCanvasElement, kind: string) {
    const existing = contexts.get(this);
    if (existing) return (existing as { __kind: string }).__kind === kind ? (existing as never) : null;
    let ctx: unknown = null;
    if (kind === "webgl2" && opts.webgl2) ctx = makeWebGLContext();
    else if (kind === "webgl" && opts.webgl) ctx = makeWebGLContext();
    else if (kind === "2d" && opts.ctx2d) ctx = make2dContext();
    if (ctx) {
      (ctx as { __kind: string }).__kind = kind;
      contexts.set(this, ctx);
    }
    return ctx as never;
  } as typeof HTMLCanvasElement.prototype.getContext);
  return { spy, contextOf: (c: HTMLCanvasElement) => contexts.get(c) };
}

// ---------------------------------------------------------------- Web Audio
class FakeParam {
  value = 0;
  events: { kind: string; value: number; time: number }[] = [];
  setValueAtTime(v: number, t: number) {
    this.value = v;
    this.events.push({ kind: "set", value: v, time: t });
    return this;
  }
  setTargetAtTime(v: number, t: number) {
    this.value = v;
    this.events.push({ kind: "target", value: v, time: t });
    return this;
  }
  linearRampToValueAtTime(v: number, t: number) {
    this.value = v;
    this.events.push({ kind: "ramp", value: v, time: t });
    return this;
  }
}

class FakeNode {
  connections: unknown[] = [];
  connect(n: unknown) {
    this.connections.push(n);
    return n;
  }
  disconnect() {
    this.connections = [];
  }
}

export class FakeOscillator extends FakeNode {
  type = "sine";
  frequency = new FakeParam();
  started = false;
  start = vi.fn(() => {
    this.started = true;
  });
  stop = vi.fn();
}

export class FakeGain extends FakeNode {
  gain = new FakeParam();
}

export class FakeAudioContext {
  static instances: FakeAudioContext[] = [];
  state: AudioContextState = "suspended";
  currentTime = 0;
  sampleRate = 8000;
  destination = new FakeNode();
  oscillators: FakeOscillator[] = [];
  gains: FakeGain[] = [];
  bufferSources: { start: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn> }[] = [];
  filters: { type: string; frequency: FakeParam }[] = [];
  compressor: { threshold: FakeParam } | null = null;

  constructor() {
    FakeAudioContext.instances.push(this);
  }

  resume = vi.fn(async () => {
    this.state = "running";
  });
  suspend = vi.fn(async () => {
    this.state = "suspended";
  });
  close = vi.fn(async () => {
    this.state = "closed";
  });
  createOscillator() {
    const o = new FakeOscillator();
    this.oscillators.push(o);
    return o;
  }
  createGain() {
    const g = new FakeGain();
    this.gains.push(g);
    return g;
  }
  createDynamicsCompressor() {
    const c = Object.assign(new FakeNode(), {
      threshold: new FakeParam(),
      knee: new FakeParam(),
      ratio: new FakeParam(),
      attack: new FakeParam(),
      release: new FakeParam(),
    });
    this.compressor = c;
    return c;
  }
  createBiquadFilter() {
    const f = Object.assign(new FakeNode(), { type: "lowpass", frequency: new FakeParam(), Q: new FakeParam() });
    this.filters.push(f);
    return f;
  }
  createBuffer(_ch: number, length: number) {
    const data = new Float32Array(length);
    return { getChannelData: () => data, length };
  }
  createBufferSource() {
    const s = Object.assign(new FakeNode(), { buffer: null, loop: false, start: vi.fn(), stop: vi.fn() });
    this.bufferSources.push(s);
    return s;
  }
}

export const fakeAudioFactory = () => new FakeAudioContext() as unknown as AudioContext;

// ---------------------------------------------------------------- rAF manual
export function manualRaf() {
  let id = 0;
  const queue = new Map<number, FrameRequestCallback>();
  return {
    raf: (cb: FrameRequestCallback) => {
      id += 1;
      queue.set(id, cb);
      return id;
    },
    caf: (h: number) => {
      queue.delete(h);
    },
    /** Corre os callbacks pendentes no instante `t` (ms). */
    tick(t: number) {
      const cbs = [...queue.values()];
      queue.clear();
      for (const cb of cbs) cb(t);
    },
    get pending() {
      return queue.size;
    },
  };
}
