/** Mock do uPlot para jsdom (sem Canvas): regista opções, dados e chamadas. */
import type uPlot from "uplot";

export class FakeUPlot {
  static instances: FakeUPlot[] = [];
  opts: uPlot.Options;
  data: uPlot.AlignedData;
  setDataCalls = 0;
  redraws = 0;
  destroyed = false;
  bbox = { left: 0, top: 0, width: 600, height: 200 };
  ctx = {
    save() {},
    restore() {},
    fillRect() {},
    beginPath() {},
    moveTo() {},
    lineTo() {},
    stroke() {},
    fillText() {},
    setLineDash() {},
  } as unknown as CanvasRenderingContext2D;

  constructor(opts: uPlot.Options, data: uPlot.AlignedData) {
    this.opts = opts;
    this.data = data;
    FakeUPlot.instances.push(this);
  }

  static reset(): void {
    FakeUPlot.instances = [];
  }

  setData(data: uPlot.AlignedData): void {
    this.data = data;
    this.setDataCalls += 1;
  }

  redraw(): void {
    this.redraws += 1;
  }

  setSize(): void {}

  valToPos(v: number): number {
    return v;
  }

  destroy(): void {
    this.destroyed = true;
  }

  /** Corre os hooks `drawClear`/`draw` dos plugins (verifica que não lançam). */
  runDrawHooks(): void {
    for (const p of this.opts.plugins ?? []) {
      const hooks = p.hooks as Record<string, ((u: unknown) => void) | undefined>;
      hooks.drawClear?.(this);
      hooks.draw?.(this);
    }
  }
}

export default FakeUPlot;
