/**
 * Mock de Canvas 2D e WebGL/WebGL2 para o vitest (jsdom não implementa `getContext`).
 * Controle de suporte por teste: `setCanvasSupport({ webgl2: false })` força o fallback
 * WebGL2 → WebGL1 → Canvas 2D (cockpit RF-09; D-22). `resetCanvasMocks()` corre no `afterEach`.
 */

export type ContextKind = "2d" | "webgl" | "webgl2";

export interface CanvasSupport {
  "2d": boolean;
  webgl: boolean;
  webgl2: boolean;
}

export interface RecordedCall {
  method: string;
  args: unknown[];
}

const DEFAULT_SUPPORT: CanvasSupport = { "2d": true, webgl: true, webgl2: true };
let support: CanvasSupport = { ...DEFAULT_SUPPORT };
const contexts = new WeakMap<HTMLCanvasElement, Map<ContextKind, object>>();

export function setCanvasSupport(partial: Partial<CanvasSupport>): void {
  support = { ...support, ...partial };
}

export function resetCanvasMocks(): void {
  support = { ...DEFAULT_SUPPORT };
}

const CONTEXT_2D_METHODS = [
  "arc", "arcTo", "beginPath", "bezierCurveTo", "clearRect", "clip", "closePath", "drawImage",
  "ellipse", "fill", "fillRect", "fillText", "lineTo", "moveTo", "putImageData",
  "quadraticCurveTo", "rect", "resetTransform", "restore", "rotate", "roundRect", "save",
  "scale", "setLineDash", "setTransform", "stroke", "strokeRect", "strokeText", "transform",
  "translate",
] as const;

/** Contexto 2D falso que regista as chamadas em `__calls`. */
export class MockCanvasRenderingContext2D {
  readonly canvas: HTMLCanvasElement;
  readonly __calls: RecordedCall[] = [];
  fillStyle: string | CanvasGradient | CanvasPattern = "#000000";
  strokeStyle: string | CanvasGradient | CanvasPattern = "#000000";
  lineWidth = 1;
  lineCap: CanvasLineCap = "butt";
  lineJoin: CanvasLineJoin = "miter";
  font = "10px sans-serif";
  textAlign: CanvasTextAlign = "start";
  textBaseline: CanvasTextBaseline = "alphabetic";
  globalAlpha = 1;
  globalCompositeOperation: GlobalCompositeOperation = "source-over";
  private lineDash: number[] = [];

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    for (const method of CONTEXT_2D_METHODS) {
      Object.defineProperty(this, method, {
        value: (...args: unknown[]) => {
          this.__calls.push({ method, args });
          if (method === "setLineDash") this.lineDash = [...(args[0] as number[])];
        },
        enumerable: false,
      });
    }
  }

  getLineDash(): number[] {
    return [...this.lineDash];
  }

  measureText(text: string): TextMetrics {
    this.__calls.push({ method: "measureText", args: [text] });
    return { width: text.length * 6 } as TextMetrics;
  }

  createLinearGradient(...args: number[]): CanvasGradient {
    this.__calls.push({ method: "createLinearGradient", args });
    return { addColorStop: () => undefined };
  }

  createRadialGradient(...args: number[]): CanvasGradient {
    this.__calls.push({ method: "createRadialGradient", args });
    return { addColorStop: () => undefined };
  }

  createImageData(width: number, height: number): ImageData {
    return { width, height, data: new Uint8ClampedArray(width * height * 4) } as ImageData;
  }

  getImageData(_x: number, _y: number, width: number, height: number): ImageData {
    return this.createImageData(width, height);
  }

  /** Nomes dos métodos chamados, na ordem (ajuda para asserções). */
  callsOf(method: string): RecordedCall[] {
    return this.__calls.filter((call) => call.method === method);
  }
}

let glObjectId = 0;

/** Contexto WebGL/WebGL2 falso: constantes numéricas e métodos sem efeito. */
export function createMockWebGLContext(canvas: HTMLCanvasElement, kind: "webgl" | "webgl2"): object {
  const calls: RecordedCall[] = [];
  const base: Record<string | symbol, unknown> = {
    canvas,
    __kind: kind,
    __calls: calls,
    drawingBufferWidth: canvas.width,
    drawingBufferHeight: canvas.height,
    getExtension: () => null,
    getSupportedExtensions: () => [],
    getParameter: () => 0,
    getShaderParameter: () => true,
    getProgramParameter: () => true,
    getShaderInfoLog: () => "",
    getProgramInfoLog: () => "",
    getUniformLocation: () => ({ id: ++glObjectId }),
    getAttribLocation: () => 0,
    getContextAttributes: () => ({ alpha: true, antialias: true }),
    isContextLost: () => false,
    checkFramebufferStatus: () => 0x8cd5,
  };
  return new Proxy(base, {
    get(target, prop) {
      if (prop in target) return target[prop];
      if (typeof prop !== "string") return undefined;
      if (/^[A-Z][A-Z0-9_]*$/.test(prop)) return 0x1000 + prop.length;
      const fn = (...args: unknown[]) => {
        calls.push({ method: prop, args });
        return prop.startsWith("create") ? { id: ++glObjectId } : undefined;
      };
      target[prop] = fn;
      return fn;
    },
  });
}

function getContextMock(this: HTMLCanvasElement, kind: string): object | null {
  if (kind !== "2d" && kind !== "webgl" && kind !== "webgl2" && kind !== "experimental-webgl") {
    return null;
  }
  const normalized: ContextKind = kind === "experimental-webgl" ? "webgl" : kind;
  if (!support[normalized]) return null;
  let byKind = contexts.get(this);
  if (!byKind) {
    byKind = new Map();
    contexts.set(this, byKind);
  }
  let context = byKind.get(normalized);
  if (!context) {
    context =
      normalized === "2d"
        ? new MockCanvasRenderingContext2D(this)
        : createMockWebGLContext(this, normalized);
    byKind.set(normalized, context);
  }
  return context;
}

export function installCanvasMock(): void {
  Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
    configurable: true,
    writable: true,
    value: getContextMock,
  });
  Object.defineProperty(HTMLCanvasElement.prototype, "toDataURL", {
    configurable: true,
    writable: true,
    value: () => "data:image/png;base64,",
  });
}
