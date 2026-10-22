/**
 * Sprites em pixel art dos 4 carros do catálogo (vista lateral, frente à direita). Cada carro é
 * descrito por polígonos numa grelha de baixa resolução e rasterizado em pixels: carroçaria com
 * contorno, vinco iluminado e sombra inferior, vidros com reflexo, detalhes (aerofólio, blower,
 * intercooler, escapes) e rodas rasterizadas à parte para poderem girar. Sem marcas nem logótipos.
 */

export const SPRITE_W = 80;
export const SPRITE_H = 31;

type Pt = readonly [number, number];

export interface Palette {
  body: string;
  shade: string;
  light: string;
  outline: string;
  glass: string;
  glassLight: string;
  trim: string;
  stripe: string;
  lamp: string;
  tail: string;
  grille: string;
  chrome: string;
  tire: string;
  tireWall: string;
  rim: string;
  rimShade: string;
  caliper: string;
}

type ColorKey = keyof Palette;

interface Detail {
  x: number;
  y: number;
  w: number;
  h: number;
  c: ColorKey;
  /** Desenha fora da carroçaria (aerofólio, blower, escape); por omissão só pinta sobre ela. */
  free?: boolean;
}

export interface Wheel {
  x: number;
  y: number;
  r: number;
}

interface RimStyle {
  spokes: number;
  /** Meia-largura do raio em pixels. */
  spokeWidth: number;
  /** Anel interior (jantes tipo colmeia/BBS). */
  ring?: boolean;
}

export interface CarSprite {
  id: string;
  name: string;
  body: readonly Pt[];
  windows: readonly (readonly Pt[])[];
  wheels: readonly [Wheel, Wheel];
  /** Linha do vinco iluminado. */
  beltY: number;
  /** Primeira linha da sombra inferior. */
  shadeFrom: number;
  details: readonly Detail[];
  palette: Palette;
  rim: RimStyle;
  /** Pontos de emissão de partículas (em pixels do sprite). */
  exhaust: Pt;
  engineBay: Pt;
  /** Sobrealimentação desenhada na Visão Térmica / Raio-X (turbina ou compressor mecânico). */
  induction: "turbo" | "supercharger";
}

const BASE: Pick<Palette, "glass" | "glassLight" | "trim" | "lamp" | "tail" | "grille" | "chrome" | "tire" | "tireWall"> = {
  glass: "#1e293b",
  glassLight: "#7dd3fc",
  trim: "#18181b",
  lamp: "#fef9c3",
  tail: "#ef4444",
  grille: "#27272a",
  chrome: "#e4e4e7",
  tire: "#0c0c0e",
  tireWall: "#27272a",
};

const HATCH: CarSprite = {
  id: "hatch-20t-gdi",
  name: "Hatch 2.0 Turbo GDI",
  body: [[9, 25], [8, 19], [9, 13], [11, 7], [14, 5], [38, 5], [48, 11], [66, 13], [71, 15], [72, 20], [71, 25]],
  windows: [
    [[15, 7], [26, 7], [26, 12], [13, 12]],
    [[28, 7], [37, 7], [45, 12], [28, 12]],
  ],
  wheels: [
    { x: 19, y: 23.5, r: 6.5 },
    { x: 60, y: 23.5, r: 6.5 },
  ],
  beltY: 13,
  shadeFrom: 20,
  details: [
    { x: 8, y: 4, w: 9, h: 1, c: "trim", free: true },
    { x: 8, y: 5, w: 3, h: 1, c: "trim", free: true },
    { x: 8, y: 13, w: 2, h: 3, c: "tail" },
    { x: 6, y: 23, w: 3, h: 1, c: "chrome", free: true },
    { x: 69, y: 15, w: 3, h: 2, c: "lamp" },
    { x: 68, y: 19, w: 4, h: 3, c: "grille" },
    { x: 68, y: 20, w: 4, h: 1, c: "chrome" },
    { x: 27, y: 24, w: 26, h: 1, c: "trim" },
    { x: 31, y: 14, w: 2, h: 1, c: "trim" },
    { x: 44, y: 10, w: 2, h: 2, c: "trim", free: true },
    { x: 27, y: 7, w: 1, h: 5, c: "trim" },
  ],
  palette: { ...BASE, body: "#d7262e", shade: "#8f1219", light: "#ff7a6b", outline: "#1a0b0c", stripe: "#18181b", rim: "#a1a1aa", rimShade: "#3f3f46", caliper: "#facc15" },
  rim: { spokes: 5, spokeWidth: 0.6 },
  exhaust: [6, 23],
  engineBay: [60, 15],
  induction: "turbo",
};

const COUPE: CarSprite = {
  id: "coupe-30t-i6",
  name: "Coupé 3.0 Turbo I6",
  body: [[5, 25], [4, 19], [5, 15], [9, 13], [16, 11], [26, 6], [38, 6], [47, 12], [70, 14], [76, 16], [77, 21], [75, 25]],
  windows: [[[19, 12], [27, 7.5], [37, 7.5], [45, 12.5]]],
  wheels: [
    { x: 18, y: 23.5, r: 6.5 },
    { x: 63, y: 23.5, r: 6.5 },
  ],
  beltY: 14,
  shadeFrom: 20,
  details: [
    { x: 6, y: 12, w: 5, h: 1, c: "trim", free: true },
    { x: 33, y: 7, w: 1, h: 6, c: "trim" },
    { x: 4, y: 16, w: 3, h: 2, c: "tail" },
    { x: 4, y: 23, w: 7, h: 2, c: "trim", free: true },
    { x: 2, y: 22, w: 3, h: 1, c: "chrome", free: true },
    { x: 2, y: 24, w: 3, h: 1, c: "chrome", free: true },
    { x: 51, y: 13, w: 10, h: 1, c: "light" },
    { x: 53, y: 17, w: 4, h: 1, c: "trim" },
    { x: 72, y: 15, w: 4, h: 1, c: "lamp" },
    { x: 74, y: 18, w: 3, h: 3, c: "grille" },
    { x: 67, y: 24, w: 11, h: 1, c: "trim", free: true },
    { x: 26, y: 24, w: 29, h: 1, c: "trim" },
    { x: 37, y: 15, w: 2, h: 1, c: "trim" },
    { x: 44, y: 11, w: 2, h: 2, c: "trim", free: true },
  ],
  palette: { ...BASE, body: "#1d5fe0", shade: "#0f3487", light: "#7fb2ff", outline: "#070d1f", stripe: "#18181b", rim: "#d4d4d8", rimShade: "#27272a", caliper: "#ef4444" },
  rim: { spokes: 10, spokeWidth: 0.4 },
  exhaust: [2, 23],
  engineBay: [62, 16],
  induction: "turbo",
};

const CLASSIC: CarSprite = {
  id: "classic-20t-swap",
  name: "Clássico 2.0 Turbo de Swap",
  body: [[7, 25], [6, 14], [9, 13], [14, 6], [40, 6], [48, 13], [73, 14], [74, 15], [74, 24], [72, 25]],
  windows: [
    [[15, 7.5], [26, 7.5], [26, 12], [11.5, 12]],
    [[28, 7.5], [39, 7.5], [45, 12], [28, 12]],
  ],
  wheels: [
    { x: 18, y: 22.5, r: 7.5 },
    { x: 61, y: 23.5, r: 6.5 },
  ],
  beltY: 13,
  shadeFrom: 21,
  details: [
    { x: 4, y: 9, w: 8, h: 1, c: "trim", free: true },
    { x: 8, y: 10, w: 1, h: 3, c: "trim", free: true },
    { x: 6, y: 15, w: 2, h: 3, c: "tail" },
    { x: 5, y: 19, w: 3, h: 2, c: "trim", free: true },
    { x: 72, y: 19, w: 3, h: 2, c: "trim", free: true },
    { x: 71, y: 15, w: 3, h: 2, c: "lamp" },
    { x: 70, y: 21, w: 4, h: 3, c: "grille" },
    { x: 70, y: 22, w: 4, h: 1, c: "chrome" },
    { x: 56, y: 11, w: 5, h: 2, c: "chrome", free: true },
    { x: 55, y: 12, w: 1, h: 1, c: "trim", free: true },
    { x: 61, y: 12, w: 1, h: 1, c: "trim", free: true },
    { x: 9, y: 17, w: 62, h: 1, c: "trim" },
    { x: 41, y: 25, w: 6, h: 1, c: "chrome", free: true },
    { x: 27, y: 7, w: 1, h: 5, c: "trim" },
    { x: 31, y: 15, w: 2, h: 1, c: "trim" },
  ],
  palette: { ...BASE, body: "#b8bec7", shade: "#6b7280", light: "#f1f5f9", outline: "#111318", stripe: "#18181b", rim: "#d4a64a", rimShade: "#5c4413", caliper: "#5c4413" },
  rim: { spokes: 8, spokeWidth: 0.45, ring: true },
  exhaust: [41, 25],
  engineBay: [58, 12],
  induction: "turbo",
};

const MUSCLE: CarSprite = {
  id: "muscle-v8-sc",
  name: "Muscle V8 5.0 Sobrealimentado",
  body: [[4, 25], [3, 17], [5, 13], [16, 12], [24, 7], [38, 7], [46, 13], [74, 14], [78, 16], [78, 22], [76, 25]],
  windows: [[[19, 12], [25, 8.5], [36, 8.5], [43, 12.5]]],
  wheels: [
    { x: 17, y: 22.5, r: 7.5 },
    { x: 64, y: 23.5, r: 6.5 },
  ],
  beltY: 13,
  shadeFrom: 21,
  details: [
    { x: 2, y: 11, w: 6, h: 2, c: "trim", free: true },
    { x: 31, y: 8, w: 1, h: 5, c: "trim" },
    { x: 3, y: 14, w: 2, h: 3, c: "tail" },
    { x: 0, y: 23, w: 4, h: 1, c: "chrome", free: true },
    { x: 0, y: 21, w: 3, h: 1, c: "chrome", free: true },
    { x: 52, y: 8, w: 7, h: 6, c: "chrome", free: true },
    { x: 53, y: 9, w: 5, h: 1, c: "rimShade", free: true },
    { x: 53, y: 11, w: 5, h: 1, c: "rimShade", free: true },
    { x: 51, y: 10, w: 1, h: 3, c: "trim", free: true },
    { x: 51, y: 6, w: 9, h: 2, c: "trim", free: true },
    { x: 53, y: 5, w: 5, h: 1, c: "chrome", free: true },
    { x: 7, y: 15, w: 64, h: 2, c: "stripe" },
    { x: 75, y: 15, w: 3, h: 2, c: "lamp" },
    { x: 76, y: 18, w: 2, h: 3, c: "grille" },
    { x: 70, y: 24, w: 8, h: 1, c: "trim", free: true },
    { x: 27, y: 24, w: 28, h: 1, c: "trim" },
  ],
  palette: { ...BASE, body: "#f5c518", shade: "#a37b06", light: "#fff3a8", outline: "#1c1500", stripe: "#111111", rim: "#71717a", rimShade: "#18181b", caliper: "#dc2626" },
  rim: { spokes: 5, spokeWidth: 0.9 },
  exhaust: [0, 22],
  engineBay: [55, 10],
  induction: "supercharger",
};

export const CAR_SPRITES: readonly CarSprite[] = [HATCH, COUPE, CLASSIC, MUSCLE];

/** Paleta da carroçaria queimada após falha catastrófica. */
export const BURNT: Partial<Palette> = {
  body: "#4a1d18",
  shade: "#2a100d",
  light: "#7f2d22",
  glass: "#18181b",
  glassLight: "#3f3f46",
  lamp: "#3f3f46",
  tail: "#3f1d1d",
};

/** Sprite do veículo; IDs fora do catálogo caem no mais próximo pelo nome (ou no hatch). */
export function spriteFor(vehicleId: string | null | undefined): CarSprite {
  const id = vehicleId ?? "";
  const exact = CAR_SPRITES.find((s) => s.id === id);
  if (exact) return exact;
  if (/muscle|v8/i.test(id)) return MUSCLE;
  if (/coupe|i6/i.test(id)) return COUPE;
  if (/classic|swap/i.test(id)) return CLASSIC;
  return HATCH;
}

/** Retângulo de 1 pixel de altura (corrida horizontal de pixels da mesma cor). */
export interface PixelRun {
  x: number;
  y: number;
  w: number;
  color: string;
}

function inPolygon(px: number, py: number, poly: readonly Pt[]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i, i += 1) {
    const [xi, yi] = poly[i]!;
    const [xj, yj] = poly[j]!;
    if (yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function toRuns(grid: (string | null)[], w: number, h: number): PixelRun[] {
  const runs: PixelRun[] = [];
  for (let y = 0; y < h; y += 1) {
    let x = 0;
    while (x < w) {
      const color = grid[y * w + x];
      if (!color) {
        x += 1;
        continue;
      }
      let end = x + 1;
      while (end < w && grid[y * w + end] === color) end += 1;
      runs.push({ x, y, w: end - x, color });
      x = end;
    }
  }
  return runs;
}

type Cell = "body" | "glass" | "detail" | null;

/** Carroçaria sem rodas (estática), já com contorno, sombras e detalhes. */
export function rasterizeBody(sprite: CarSprite, override: Partial<Palette> = {}): PixelRun[] {
  const pal = { ...sprite.palette, ...override };
  const W = SPRITE_W;
  const H = SPRITE_H;
  const kind: Cell[] = new Array<Cell>(W * H).fill(null);
  const color: (string | null)[] = new Array<string | null>(W * H).fill(null);
  const at = (x: number, y: number) => (x < 0 || y < 0 || x >= W || y >= H ? null : kind[y * W + x]);

  for (let y = 0; y < H; y += 1) {
    for (let x = 0; x < W; x += 1) {
      const cx = x + 0.5;
      const cy = y + 0.5;
      if (!inPolygon(cx, cy, sprite.body)) continue;
      const inArch = sprite.wheels.some((wh) => cy < wh.y + wh.r && Math.hypot(cx - wh.x, cy - wh.y) < wh.r + 1.5);
      if (inArch) continue;
      kind[y * W + x] = "body";
    }
  }
  const isBody = (x: number, y: number) => at(x, y) !== null;

  for (let y = 0; y < H; y += 1) {
    for (let x = 0; x < W; x += 1) {
      if (!isBody(x, y)) continue;
      const i = y * W + x;
      if (sprite.windows.some((w) => inPolygon(x + 0.5, y + 0.5, w))) {
        kind[i] = "glass";
        color[i] = (x + y) % 9 < 2 ? pal.glassLight : pal.glass;
        continue;
      }
      const edge = !isBody(x - 1, y) || !isBody(x + 1, y) || !isBody(x, y - 1) || !isBody(x, y + 1);
      if (edge) color[i] = pal.outline;
      else if (!isBody(x, y - 2) || y === sprite.beltY) color[i] = pal.light;
      else if (y >= sprite.shadeFrom || y === sprite.beltY + 1) color[i] = pal.shade;
      else color[i] = pal.body;
    }
  }

  for (const d of sprite.details) {
    for (let y = d.y; y < d.y + d.h; y += 1) {
      for (let x = d.x; x < d.x + d.w; x += 1) {
        if (x < 0 || y < 0 || x >= W || y >= H) continue;
        const i = y * W + x;
        if (!d.free && kind[i] !== "body" && kind[i] !== "glass") continue;
        kind[i] = "detail";
        color[i] = pal[d.c];
      }
    }
  }

  // Sombra no chão entre as rodas.
  const [rear, front] = sprite.wheels;
  for (let x = rear.x - rear.r - 2; x <= front.x + front.r + 2; x += 1) {
    if (x >= 0 && x < W) color[(H - 1) * W + x] = "#00000066";
  }
  return toRuns(color, W, H);
}

/** Pixels de uma roda no ângulo dado (raios giram, a pinça de travão fica parada). */
export function rasterizeWheel(sprite: CarSprite, wheel: Wheel, angle: number, override: Partial<Palette> = {}): PixelRun[] {
  const pal = { ...sprite.palette, ...override };
  const { r } = wheel;
  const rr = r - 1.6;
  const size = Math.ceil(r) * 2 + 1;
  const ox = Math.floor(wheel.x - r);
  const oy = Math.floor(wheel.y - r);
  const grid: (string | null)[] = new Array<string | null>(size * size).fill(null);
  const n = sprite.rim.spokes;
  for (let j = 0; j < size; j += 1) {
    for (let i = 0; i < size; i += 1) {
      const dx = ox + i + 0.5 - wheel.x;
      const dy = oy + j + 0.5 - wheel.y;
      const d = Math.hypot(dx, dy);
      if (d > r) continue;
      let c: string;
      if (d > r - 1) c = pal.tire;
      else if (d > rr) c = pal.tireWall;
      else if (d > rr - 0.9) c = pal.rim;
      else if (d < 1.2) c = pal.trim;
      else {
        const a = Math.atan2(dy, dx) - angle;
        const sector = (2 * Math.PI) / n;
        const rel = ((a % sector) + sector) % sector;
        const off = Math.min(rel, sector - rel);
        const spoke = Math.sin(off) * d < sprite.rim.spokeWidth;
        const ring = sprite.rim.ring === true && Math.abs(d - rr * 0.55) < 0.5;
        if (spoke || ring) c = pal.rim;
        else {
          const ang = Math.atan2(dy, dx);
          c = ang > -1.2 && ang < -0.2 && d > rr * 0.4 ? pal.caliper : pal.rimShade;
        }
      }
      grid[j * size + i] = c;
    }
  }
  return toRuns(grid, size, size).map((run) => ({ ...run, x: run.x + ox, y: run.y + oy }));
}

const bodyCache = new Map<string, PixelRun[]>();

export function bodyRuns(sprite: CarSprite, burnt = false): PixelRun[] {
  const key = `${sprite.id}|${burnt ? 1 : 0}`;
  let runs = bodyCache.get(key);
  if (!runs) {
    runs = rasterizeBody(sprite, burnt ? BURNT : {});
    bodyCache.set(key, runs);
  }
  return runs;
}

/** Pinta corridas de pixels num canvas 2D com escala inteira (sem suavização). */
export function paintRuns(ctx: CanvasRenderingContext2D, runs: readonly PixelRun[], ox: number, oy: number, scale: number): void {
  let last = "";
  for (const run of runs) {
    if (run.color !== last) {
      ctx.fillStyle = run.color;
      last = run.color;
    }
    ctx.fillRect(ox + run.x * scale, oy + run.y * scale, run.w * scale, scale);
  }
}
