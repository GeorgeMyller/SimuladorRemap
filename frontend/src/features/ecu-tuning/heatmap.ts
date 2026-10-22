/**
 * Heatmap das células (tuning RF-10): escala contínua min→max da tabela com a paleta "cividis"
 * (segura para daltonismo) e texto escuro ou claro escolhido por luminância (contraste ≥ 4,5:1).
 */

/** Paradas da cividis (sRGB 0–255), de 0 a 1 em passos iguais. */
const CIVIDIS: readonly (readonly [number, number, number])[] = [
  [0, 32, 77],
  [0, 42, 102],
  [28, 56, 110],
  [61, 72, 110],
  [87, 88, 111],
  [111, 105, 113],
  [134, 122, 116],
  [158, 139, 114],
  [184, 158, 106],
  [210, 177, 93],
  [237, 198, 72],
  [255, 234, 70],
];

export type Rgb = readonly [number, number, number];

export function paletteColor(t: number): Rgb {
  const x = Math.min(1, Math.max(0, Number.isFinite(t) ? t : 0)) * (CIVIDIS.length - 1);
  const i = Math.min(CIVIDIS.length - 2, Math.floor(x));
  const f = x - i;
  const a = CIVIDIS[i]!;
  const b = CIVIDIS[i + 1]!;
  return [Math.round(a[0] + (b[0] - a[0]) * f), Math.round(a[1] + (b[1] - a[1]) * f), Math.round(a[2] + (b[2] - a[2]) * f)];
}

function channel(c: number): number {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

/** Luminância relativa WCAG 2.1. */
export function luminance([r, g, b]: Rgb): number {
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function contrastRatio(a: Rgb, b: Rgb): number {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

export const TEXT_DARK: Rgb = [0, 0, 0];
export const TEXT_LIGHT: Rgb = [255, 255, 255];

export function textColorFor(bg: Rgb): Rgb {
  return contrastRatio(bg, TEXT_DARK) >= contrastRatio(bg, TEXT_LIGHT) ? TEXT_DARK : TEXT_LIGHT;
}

export function rgbCss([r, g, b]: Rgb): string {
  return `rgb(${r}, ${g}, ${b})`;
}

export interface CellColors {
  background: string;
  color: string;
}

/** Cores da célula para `value` na escala `[min, max]` dos valores da tabela. */
export function cellColors(value: number, min: number, max: number): CellColors {
  const t = max > min ? (value - min) / (max - min) : 0.5;
  const bg = paletteColor(t);
  return { background: rgbCss(bg), color: rgbCss(textColorFor(bg)) };
}

export function valueRange(values: number[][]): { min: number; max: number } {
  let min = Infinity;
  let max = -Infinity;
  for (const row of values) for (const v of row) {
    if (v < min) min = v;
    if (v > max) max = v;
  }
  return Number.isFinite(min) ? { min, max } : { min: 0, max: 0 };
}
