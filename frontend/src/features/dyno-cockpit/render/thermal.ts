/**
 * Visão Térmica / Raio-X do carro no rolo (RF-21; D-12): cor do metal pela EGT (vermelho escuro a
 * 650 °C, laranja a ~815 °C, amarelo claro a 980 °C) e camada com coletor, turbina (ou compressor
 * mecânico) e escape desenhados a partir dos pontos `engineBay`/`exhaust` do sprite.
 */

export const THERMAL_COLD_C = 650;
export const THERMAL_MID_C = 815;
export const THERMAL_HOT_C = 980;
/** Abaixo disto o metal fica cinza escuro (sem brilho). */
const THERMAL_FLOOR_C = 400;

export interface ThermalColor {
  r: number;
  g: number;
  b: number;
  /** Intensidade do brilho (0..1): 0 até 650 °C, 1 a partir de 980 °C. */
  glow: number;
}

type Rgb = readonly [number, number, number];

const STOPS: readonly { t: number; c: Rgb }[] = [
  { t: THERMAL_FLOOR_C, c: [63, 63, 70] },
  { t: THERMAL_COLD_C, c: [127, 29, 29] },
  { t: THERMAL_MID_C, c: [249, 115, 22] },
  { t: THERMAL_HOT_C, c: [254, 249, 195] },
];

const clamp01 = (v: number) => Math.min(1, Math.max(0, v));

/** Cor contínua do metal à temperatura `egtC` (°C). Entrada ausente/inválida = cinza escuro. */
export function thermalColor(egtC: number | null | undefined): ThermalColor {
  const t = egtC === null || egtC === undefined || !Number.isFinite(egtC) ? 0 : egtC;
  const glow = clamp01((t - THERMAL_COLD_C) / (THERMAL_HOT_C - THERMAL_COLD_C));
  let i = 0;
  while (i < STOPS.length - 2 && t > STOPS[i + 1]!.t) i += 1;
  const a = STOPS[i]!;
  const b = STOPS[i + 1]!;
  const k = clamp01((t - a.t) / (b.t - a.t));
  const mix = (j: 0 | 1 | 2) => Math.round(a.c[j] + (b.c[j] - a.c[j]) * k);
  return { r: mix(0), g: mix(1), b: mix(2), glow };
}

/** Passo do cache de cor (°C): estilos prontos, sem montar strings a cada frame. */
const CSS_STEP_C = 5;
const CSS_MAX_C = 1100;
const cssCache: string[] = [];

export function thermalCss(egtC: number | null | undefined): string {
  const t = egtC === null || egtC === undefined || !Number.isFinite(egtC) ? 0 : egtC;
  const bucket = Math.round(Math.min(CSS_MAX_C, Math.max(0, t)) / CSS_STEP_C);
  let css = cssCache[bucket];
  if (css === undefined) {
    const c = thermalColor(bucket * CSS_STEP_C);
    css = `rgb(${c.r},${c.g},${c.b})`;
    cssCache[bucket] = css;
  }
  return css;
}

export interface ThermalGeometry {
  /** Centro do motor (`engineBay`) no referencial da cena. */
  engine: { x: number; y: number };
  /** Saída do escape no referencial da cena. */
  exhaust: { x: number; y: number };
  /** Pixels da cena por pixel do sprite. */
  scale: number;
  induction: "turbo" | "supercharger";
}

export interface ThermalTemps {
  /** EGT pós-turbina (`egt_c`). */
  egtC: number | null;
  /** EGT no coletor, antes da turbina (`egt_pre_turbo_c`); cai em `egt_c` se ausente. */
  egtPreTurboC: number | null;
}

/** Arrefecimento do tubo do escape até a ponteira (°C). */
const TAILPIPE_DROP_C = 150;
const BLOCK_FILL = "#18181b";
const BLOCK_EDGE = "#a1a1aa";
const BLOWER_FILL = "#52525b";

function strokePath(ctx: CanvasRenderingContext2D, color: string, width: number, pts: readonly number[]): void {
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.beginPath();
  ctx.moveTo(pts[0]!, pts[1]!);
  for (let i = 2; i < pts.length; i += 2) ctx.lineTo(pts[i]!, pts[i + 1]!);
  ctx.stroke();
}

function drawGlow(ctx: CanvasRenderingContext2D, x: number, y: number, radius: number, egtC: number | null): void {
  const { glow } = thermalColor(egtC);
  if (glow <= 0) return;
  ctx.globalAlpha = 0.18 + 0.27 * glow;
  ctx.fillStyle = thermalCss(egtC);
  ctx.beginPath();
  ctx.arc(x, y, radius * (1.4 + 0.8 * glow), 0, Math.PI * 2);
  ctx.fill();
  ctx.globalAlpha = 1;
}

function drawEngineBlock(ctx: CanvasRenderingContext2D, g: ThermalGeometry): void {
  const s = g.scale;
  ctx.fillStyle = BLOCK_FILL;
  ctx.fillRect(g.engine.x - 5 * s, g.engine.y - 3 * s, 10 * s, 7 * s);
  ctx.strokeStyle = BLOCK_EDGE;
  ctx.lineWidth = 1;
  ctx.strokeRect(g.engine.x - 5 * s, g.engine.y - 3 * s, 10 * s, 7 * s);
}

/**
 * Ponto quente da camada: centro da turbina (turbo) ou coletor dos headers (compressor mecânico).
 * Também é onde nascem a fumaça e as fagulhas das falhas do turbo/escape.
 */
export function hotSpot(g: ThermalGeometry): { x: number; y: number } {
  const s = g.scale;
  return g.induction === "turbo" ? { x: g.engine.x - 7.5 * s, y: g.engine.y + 1.5 * s } : { x: g.engine.x - 6.5 * s, y: g.engine.y + 5 * s };
}

function drawTurboSide(ctx: CanvasRenderingContext2D, g: ThermalGeometry, t: ThermalTemps): void {
  const s = g.scale;
  const pre = t.egtPreTurboC ?? t.egtC;
  const hot = thermalCss(pre);
  const { x: tx, y: ty } = hotSpot(g);
  for (let i = 0; i < 3; i += 1) {
    const ry = g.engine.y - 2 * s + i * 1.6 * s;
    strokePath(ctx, hot, 3, [g.engine.x - 5 * s, ry, g.engine.x - 6.3 * s, ry, tx, ty]);
  }
  drawGlow(ctx, tx, ty, 2.2 * s, pre);
  ctx.fillStyle = hot;
  ctx.beginPath();
  ctx.arc(tx, ty, 2.2 * s, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = BLOCK_FILL;
  ctx.fillRect(tx - 0.5 * s, ty - 0.5 * s, s, s);
  drawExhaustRun(ctx, g, t.egtC, tx, ty);
}

function drawSuperchargerSide(ctx: CanvasRenderingContext2D, g: ThermalGeometry, t: ThermalTemps): void {
  const s = g.scale;
  ctx.fillStyle = BLOWER_FILL;
  ctx.fillRect(g.engine.x - 4 * s, g.engine.y - 6 * s, 8 * s, 3 * s);
  ctx.strokeStyle = BLOCK_EDGE;
  ctx.lineWidth = 1;
  ctx.strokeRect(g.engine.x - 4 * s, g.engine.y - 6 * s, 8 * s, 3 * s);
  ctx.beginPath();
  ctx.arc(g.engine.x + 5 * s, g.engine.y - 4.5 * s, 1.2 * s, 0, Math.PI * 2);
  ctx.stroke();
  const pre = t.egtPreTurboC ?? t.egtC;
  const hot = thermalCss(pre);
  const { x: cx, y: cy } = hotSpot(g);
  for (let i = 0; i < 4; i += 1) {
    const rx = g.engine.x - 4 * s + i * 2 * s;
    strokePath(ctx, hot, 3, [rx, g.engine.y + 4 * s, rx, cy, cx, cy]);
  }
  drawGlow(ctx, cx, cy, 1.5 * s, pre);
  drawExhaustRun(ctx, g, t.egtC, cx, cy);
}

/** Tubo do escape: da turbina/coletor ao assoalho e daí à ponteira (arrefece pelo caminho). */
function drawExhaustRun(ctx: CanvasRenderingContext2D, g: ThermalGeometry, egtC: number | null, fromX: number, fromY: number): void {
  const s = g.scale;
  const downX = Math.max(g.exhaust.x, fromX - 1.5 * s);
  strokePath(ctx, thermalCss(egtC), 3, [fromX, fromY, downX, g.exhaust.y]);
  const tail = egtC === null ? null : egtC - TAILPIPE_DROP_C;
  strokePath(ctx, thermalCss(tail), 2, [downX, g.exhaust.y, g.exhaust.x, g.exhaust.y]);
}

/** Desenha a camada térmica (bloco, coletor, turbina ou compressor e escape). */
export function drawThermalLayer(ctx: CanvasRenderingContext2D, geometry: ThermalGeometry, temps: ThermalTemps): void {
  drawEngineBlock(ctx, geometry);
  if (geometry.induction === "turbo") drawTurboSide(ctx, geometry, temps);
  else drawSuperchargerSide(ctx, geometry, temps);
  ctx.globalAlpha = 1;
}
