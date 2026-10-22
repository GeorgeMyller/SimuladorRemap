/**
 * Seleção da superfície de desenho (D-22, RNF-08, EC-08): tenta `webgl2`, depois `webgl`,
 * depois `2d`. A perda de contexto WebGL cai para Canvas 2D sem recarregar.
 */
export type SurfaceKind = "webgl2" | "webgl" | "2d" | "none";

export type Surface =
  | { kind: "webgl2"; gl: WebGL2RenderingContext; canvas: HTMLCanvasElement }
  | { kind: "webgl"; gl: WebGLRenderingContext; canvas: HTMLCanvasElement }
  | { kind: "2d"; ctx: CanvasRenderingContext2D; canvas: HTMLCanvasElement }
  | { kind: "none"; canvas: HTMLCanvasElement };

export interface CreateSurfaceOptions {
  /** Força o modo Canvas 2D (ex.: após `webglcontextlost`). */
  force2d?: boolean;
  /** Superfícies a não tentar (testes de fallback). */
  disable?: readonly SurfaceKind[];
}

function tryContext<T>(fn: () => T | null): T | null {
  try {
    return fn();
  } catch {
    return null;
  }
}

export function createSurface(canvas: HTMLCanvasElement, options: CreateSurfaceOptions = {}): Surface {
  const disabled = new Set(options.disable ?? []);
  if (!options.force2d) {
    if (!disabled.has("webgl2")) {
      const gl = tryContext(() => canvas.getContext("webgl2", { antialias: false, preserveDrawingBuffer: false }));
      if (gl) return { kind: "webgl2", gl, canvas };
    }
    if (!disabled.has("webgl")) {
      const gl = tryContext(() => canvas.getContext("webgl", { antialias: false }));
      if (gl) return { kind: "webgl", gl, canvas };
    }
  }
  const ctx = tryContext(() => canvas.getContext("2d"));
  if (ctx) return { kind: "2d", ctx, canvas };
  return { kind: "none", canvas };
}

/** Observa `webglcontextlost`/`webglcontextrestored`; devolve a função de remoção. */
export function watchContextLoss(
  canvas: HTMLCanvasElement,
  onLost: () => void,
  onRestored: () => void,
): () => void {
  const lost = (ev: Event) => {
    ev.preventDefault();
    onLost();
  };
  canvas.addEventListener("webglcontextlost", lost);
  canvas.addEventListener("webglcontextrestored", onRestored);
  return () => {
    canvas.removeEventListener("webglcontextlost", lost);
    canvas.removeEventListener("webglcontextrestored", onRestored);
  };
}

export const SURFACE_LABEL: Record<SurfaceKind, string> = {
  webgl2: "WebGL2",
  webgl: "WebGL1",
  "2d": "Canvas 2D",
  none: "indisponível",
};
