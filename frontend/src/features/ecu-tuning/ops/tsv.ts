/**
 * Cópia e colagem em TSV compatível com planilhas (tuning RF-08, EC-06).
 * `toTsv` usa ponto decimal sem separador de milhar; `parseTsv` aceita vírgula ou ponto,
 * trata só números (sem fórmulas nem HTML) e marca células inválidas como `null`.
 */
import { clamp, makeDelta, type GridTable, type Rect } from "../model";
import type { OpResult } from "./selectionOps";

function formatTsvNumber(v: number, decimals?: number): string {
  if (decimals === undefined) return String(v);
  return String(Number(v.toFixed(decimals)));
}

export function toTsv(values: number[][], rect: Rect, decimals?: number): string {
  const lines: string[] = [];
  for (let r = rect.r0; r <= rect.r1; r += 1) {
    const row = values[r] ?? [];
    const cells: string[] = [];
    for (let c = rect.c0; c <= rect.c1; c += 1) cells.push(formatTsvNumber(row[c] ?? 0, decimals));
    lines.push(cells.join("\t"));
  }
  return lines.join("\n");
}

const NUMBER_RE = /^[-+]?(\d+([.,]\d*)?|[.,]\d+)([eE][-+]?\d+)?$/;

/** Converte um texto de célula em número (vírgula ou ponto decimal) ou `null`. */
export function parseCellNumber(text: string): number | null {
  const t = text.trim().replace(/\u00a0/g, "");
  if (!t || !NUMBER_RE.test(t)) return null;
  const n = Number(t.replace(",", "."));
  return Number.isFinite(n) ? n : null;
}

/** Grade de células (`null` = inválida) a partir do TSV colado. */
export function parseTsv(text: string): (number | null)[][] {
  const normalized = text.replace(/\r\n?/g, "\n").replace(/\n+$/, "");
  if (!normalized) return [];
  return normalized.split("\n").map((line) => line.split("\t").map(parseCellNumber));
}

export interface PasteResult extends OpResult {
  /** Células fora da tabela (cortadas). */
  outside: number;
  /** Células não numéricas ou vazias. */
  invalid: number;
  written: number;
}

/** Cola a grade a partir de `(row, col)`; células inválidas e fora da tabela não são gravadas. */
export function pasteGrid(table: GridTable, origin: { row: number; col: number }, grid: (number | null)[][]): PasteResult {
  const values = table.values.map((r) => [...r]);
  let outside = 0;
  let invalid = 0;
  let clamped = 0;
  let written = 0;
  grid.forEach((line, i) => {
    line.forEach((v, j) => {
      const r = origin.row + i;
      const c = origin.col + j;
      const row = values[r];
      if (!row || c >= row.length) {
        outside += 1;
        return;
      }
      if (v === null) {
        invalid += 1;
        return;
      }
      const cv = clamp(v, table.min, table.max);
      if (cv !== v) clamped += 1;
      row[c] = cv;
      written += 1;
    });
  });
  return { values, delta: makeDelta(table.tableId, table.values, values, "paste"), clamped, outside, invalid, written };
}
