/**
 * Laço `requestAnimationFrame` desacoplado da chegada dos frames (RF-03; D-22).
 * Pausa com o separador oculto (EC-10), mede FPS e sinaliza degradação após 5 s < 30 FPS (EC-12).
 */
export type DrawCallback = (nowMs: number, dtMs: number) => void;

export interface RenderLoopOptions {
  raf?: (cb: FrameRequestCallback) => number;
  caf?: (id: number) => void;
  doc?: Pick<Document, "visibilityState" | "addEventListener" | "removeEventListener"> | null;
  minFps?: number;
  degradeAfterMs?: number;
}

export class RenderLoop {
  private readonly callbacks = new Set<DrawCallback>();
  private readonly raf: (cb: FrameRequestCallback) => number;
  private readonly caf: (id: number) => void;
  private readonly doc: RenderLoopOptions["doc"];
  private readonly minFps: number;
  private readonly degradeAfterMs: number;
  private handle: number | null = null;
  private running = false;
  private last = -1;
  private fpsWindow: number[] = [];
  private belowSince: number | null = null;
  private degradedListeners = new Set<(degraded: boolean) => void>();
  fps = 0;
  degraded = false;
  frames = 0;

  constructor(options: RenderLoopOptions = {}) {
    this.raf = options.raf ?? ((cb) => requestAnimationFrame(cb));
    this.caf = options.caf ?? ((id) => cancelAnimationFrame(id));
    this.doc = options.doc === undefined ? (typeof document !== "undefined" ? document : null) : options.doc;
    this.minFps = options.minFps ?? 30;
    this.degradeAfterMs = options.degradeAfterMs ?? 5000;
  }

  add(cb: DrawCallback): () => void {
    this.callbacks.add(cb);
    return () => this.callbacks.delete(cb);
  }

  onDegradedChange(cb: (degraded: boolean) => void): () => void {
    this.degradedListeners.add(cb);
    return () => this.degradedListeners.delete(cb);
  }

  get isRunning(): boolean {
    return this.running;
  }

  start(): void {
    if (this.running) return;
    this.running = true;
    this.doc?.addEventListener("visibilitychange", this.onVisibility);
    if (this.doc?.visibilityState !== "hidden") this.schedule();
  }

  stop(): void {
    this.running = false;
    this.doc?.removeEventListener("visibilitychange", this.onVisibility);
    if (this.handle !== null) this.caf(this.handle);
    this.handle = null;
    this.last = -1;
  }

  private readonly onVisibility = () => {
    if (!this.running) return;
    if (this.doc?.visibilityState === "hidden") {
      if (this.handle !== null) this.caf(this.handle);
      this.handle = null;
      this.last = -1;
    } else if (this.handle === null) {
      this.schedule();
    }
  };

  private schedule(): void {
    this.handle = this.raf(this.tick);
  }

  private readonly tick = (now: number) => {
    this.handle = null;
    if (!this.running) return;
    const dt = this.last < 0 ? 0 : now - this.last;
    this.last = now;
    this.frames += 1;
    this.measure(now);
    for (const cb of this.callbacks) {
      try {
        cb(now, dt);
      } catch (error) {
        console.error("[RenderLoop] painel falhou ao desenhar", error);
      }
    }
    this.schedule();
  };

  private measure(now: number): void {
    this.fpsWindow.push(now);
    while (this.fpsWindow.length > 0 && now - this.fpsWindow[0]! > 1000) this.fpsWindow.shift();
    const span = now - this.fpsWindow[0]!;
    if (span < 500) return;
    this.fps = ((this.fpsWindow.length - 1) * 1000) / span;
    if (this.fps < this.minFps) {
      this.belowSince ??= now;
      if (!this.degraded && now - this.belowSince >= this.degradeAfterMs) this.setDegraded(true);
    } else {
      this.belowSince = null;
    }
  }

  private setDegraded(value: boolean): void {
    this.degraded = value;
    for (const cb of this.degradedListeners) cb(value);
  }
}
