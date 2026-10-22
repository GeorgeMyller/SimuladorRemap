/**
 * Geometria da superfície 3D e do contorno 2D (tuning RF-12): funções puras, sem three.js,
 * partilhadas por `Table3DSurface` (WebGL) e pelo fallback de contorno (`Table3DView`).
 */
import { paletteColor } from "./heatmap";

/** Índice do vértice da célula `(row, col)` numa malha `ny × nx` (linha = eixo Y). */
export function vertexIndex(row: number, col: number, nx: number): number {
  return row * nx + col;
}

export interface SurfaceData {
  nx: number;
  ny: number;
  /** x, y (altura), z por vértice, normalizados em [-1, 1] × [0, 1] × [-1, 1]. */
  positions: Float32Array;
  /** RGB 0–1 por vértice (paleta do heatmap). */
  colors: Float32Array;
  /** Índices dos triângulos (2 por quadrado). */
  indices: Uint32Array;
}

export function buildSurface(values: readonly (readonly number[])[]): SurfaceData {
  const ny = values.length;
  const nx = values[0]?.length ?? 0;
  let min = Infinity;
  let max = -Infinity;
  for (const row of values) for (const v of row) {
    if (v < min) min = v;
    if (v > max) max = v;
  }
  const span = max > min ? max - min : 1;
  const positions = new Float32Array(nx * ny * 3);
  const colors = new Float32Array(nx * ny * 3);
  for (let r = 0; r < ny; r += 1) {
    for (let c = 0; c < nx; c += 1) {
      const k = vertexIndex(r, c, nx) * 3;
      const t = (values[r]![c]! - min) / span;
      positions[k] = nx > 1 ? (c / (nx - 1)) * 2 - 1 : 0;
      positions[k + 1] = max > min ? t : 0.5;
      positions[k + 2] = ny > 1 ? (r / (ny - 1)) * 2 - 1 : 0;
      const [cr, cg, cb] = paletteColor(max > min ? t : 0.5);
      colors[k] = cr / 255;
      colors[k + 1] = cg / 255;
      colors[k + 2] = cb / 255;
    }
  }
  const quads = Math.max(0, nx - 1) * Math.max(0, ny - 1);
  const indices = new Uint32Array(quads * 6);
  let q = 0;
  for (let r = 0; r < ny - 1; r += 1) {
    for (let c = 0; c < nx - 1; c += 1) {
      const a = vertexIndex(r, c, nx);
      const b = vertexIndex(r, c + 1, nx);
      const d = vertexIndex(r + 1, c, nx);
      const e = vertexIndex(r + 1, c + 1, nx);
      indices.set([a, d, b, b, d, e], q);
      q += 6;
    }
  }
  return { nx, ny, positions, colors, indices };
}

export interface Segment {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  level: number;
}

/**
 * Linhas de contorno por "marching squares" sobre a grade (coordenadas em índices de célula,
 * centro da célula = inteiro). `levels` níveis igualmente espaçados entre o mín. e o máx.
 */
export function contourSegments(values: readonly (readonly number[])[], levels = 8): Segment[] {
  const ny = values.length;
  const nx = values[0]?.length ?? 0;
  if (nx < 2 || ny < 2) return [];
  let min = Infinity;
  let max = -Infinity;
  for (const row of values) for (const v of row) {
    min = Math.min(min, v);
    max = Math.max(max, v);
  }
  if (!(max > min)) return [];
  const out: Segment[] = [];
  const lerp = (a: number, b: number, lv: number) => (lv - a) / (b - a);
  for (let k = 1; k <= levels; k += 1) {
    const lv = min + ((max - min) * k) / (levels + 1);
    for (let r = 0; r < ny - 1; r += 1) {
      for (let c = 0; c < nx - 1; c += 1) {
        const v00 = values[r]![c]!;
        const v01 = values[r]![c + 1]!;
        const v10 = values[r + 1]![c]!;
        const v11 = values[r + 1]![c + 1]!;
        const pts: [number, number][] = [];
        if (v00 < lv !== v01 < lv) pts.push([c + lerp(v00, v01, lv), r]);
        if (v01 < lv !== v11 < lv) pts.push([c + 1, r + lerp(v01, v11, lv)]);
        if (v10 < lv !== v11 < lv) pts.push([c + lerp(v10, v11, lv), r + 1]);
        if (v00 < lv !== v10 < lv) pts.push([c, r + lerp(v00, v10, lv)]);
        for (let p = 0; p + 1 < pts.length; p += 2) {
          out.push({ x1: pts[p]![0], y1: pts[p]![1], x2: pts[p + 1]![0], y2: pts[p + 1]![1], level: lv });
        }
      }
    }
  }
  return out;
}

/** WebGL disponível neste navegador (EC-11). */
export function webglAvailable(doc: Document = document): boolean {
  try {
    const canvas = doc.createElement("canvas");
    return Boolean(canvas.getContext("webgl2") ?? canvas.getContext("webgl"));
  } catch {
    return false;
  }
}
