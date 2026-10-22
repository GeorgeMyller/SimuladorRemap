/**
 * Avisos didáticos não bloqueantes W-01 a W-06 (tuning RF-19, §8 "Avisos didáticos").
 * Funções puras: recebem as tabelas, as estratégias e os dados do veículo e devolvem a lista.
 */
import { WARNING_TEXTS, type WarningCode } from "./messages";
import type { GridTable } from "./model";
import type { Grid2D } from "./types";

export const BARO_KPA = 101.325;

export interface TuningWarning {
  code: WarningCode;
  message: string;
  tableId?: string;
  row?: number;
  col?: number;
  field?: string;
  detail: string;
}

export interface WarningContext {
  tables: GridTable[];
  strategies: Record<string, Record<string, unknown>>;
  mbtReference: Grid2D | null;
  maxRpm: number | null;
  /** Pressão máxima do turbo em kPa abs (`pr_design × atmosférica`) ou `null`. */
  boostMaxKpa: number | null;
  baroKpa?: number;
}

function locate(axis: readonly number[], x: number): [number, number] {
  const last = axis.length - 1;
  if (!(x > axis[0]!)) return [0, 0];
  if (x >= axis[last]!) return [last - 1, 1];
  let i = 0;
  while (i < last - 1 && axis[i + 1]! <= x) i += 1;
  return [i, (x - axis[i]!) / (axis[i + 1]! - axis[i]!)];
}

/** Interpolação bilinear com clamp nas bordas (mesma regra do ecu-core, Apêndice B). */
export function interp2(xs: readonly number[], ys: readonly number[], z: readonly (readonly number[])[], x: number, y: number): number {
  const [j, fx] = locate(xs, x);
  const [i, fy] = locate(ys, y);
  const r0 = z[i]!;
  const r1 = z[Math.min(i + 1, z.length - 1)]!;
  const a = r0[j]! + fx * ((r0[j + 1] ?? r0[j]!) - r0[j]!);
  const b = r1[j]! + fx * ((r1[j + 1] ?? r1[j]!) - r1[j]!);
  return a + fy * (b - a);
}

const IGNITION_KINDS = new Set(["ignition_base", "ignition_optimal"]);
const LAMBDA_KINDS = new Set(["lambda_target"]);
const BOOST_KINDS = new Set(["boost_target", "boost_target_gear", "oem_pressure_target"]);
const VE_KINDS = new Set(["ve"]);

function w(code: WarningCode, detail: string, extra: Partial<TuningWarning> = {}): TuningWarning {
  return { code, message: WARNING_TEXTS[code].message, detail, ...extra };
}

function fmt(v: number, d = 1): string {
  return v.toLocaleString("pt-BR", { maximumFractionDigits: d, minimumFractionDigits: d });
}

function isLoadAxis(q: string | undefined): "map" | "load" | null {
  if (q === "map_kpa") return "map";
  if (q === "load_pct") return "load";
  return null;
}

export function mbtAvailable(ctx: Pick<WarningContext, "mbtReference">): boolean {
  return Boolean(ctx.mbtReference && ctx.mbtReference.x_values.length >= 2 && ctx.mbtReference.y_values.length >= 2);
}

export function tableWarnings(t: GridTable, ctx: WarningContext): TuningWarning[] {
  const out: TuningWarning[] = [];
  const baro = ctx.baroKpa ?? BARO_KPA;
  const xs = t.x.values;
  const ys = t.y?.values ?? [0];
  const loadKind = isLoadAxis(t.y?.quantity);
  t.values.forEach((row, r) => {
    row.forEach((v, c) => {
      const x = xs[c]!;
      const y = ys[r]!;
      const at = { tableId: t.tableId, row: r, col: c };
      if (IGNITION_KINDS.has(t.kind) && ctx.mbtReference && mbtAvailable(ctx) && t.x.quantity === "rpm" && t.y) {
        const m = ctx.mbtReference;
        const mbt = interp2(m.x_values, m.y_values, m.z_values, x, y);
        if (v > mbt + 2) out.push(w("W-01", `${fmt(v)}° com MBT estimado ${fmt(mbt)}° (+${fmt(v - mbt)}°).`, at));
      }
      if (LAMBDA_KINDS.has(t.kind) && v > 0.9) {
        const high = loadKind === "load" ? y >= 80 : loadKind === "map" ? y >= 1.5 * baro : false;
        if (high) out.push(w("W-02", `λ ${fmt(v, 3)} com carga ${fmt(y, 0)} ${t.y?.unit ?? ""}.`, at));
      }
      if (BOOST_KINDS.has(t.kind) && ctx.boostMaxKpa !== null && v > ctx.boostMaxKpa) {
        out.push(w("W-03", `${fmt(v, 0)} kPa acima do máximo ${fmt(ctx.boostMaxKpa, 0)} kPa.`, at));
      }
      const right = row[c + 1];
      const down = t.values[r + 1]?.[c];
      for (const [nb, nr, nc] of [
        [right, r, c + 1],
        [down, r + 1, c],
      ] as const) {
        if (nb === undefined) continue;
        if (VE_KINDS.has(t.kind)) {
          const ref = Math.max(Math.abs(v), Math.abs(nb));
          if (ref > 0 && Math.abs(nb - v) / ref > 0.15) out.push(w("W-06", `Variação de ${fmt((Math.abs(nb - v) / ref) * 100, 0)} % entre células vizinhas.`, { tableId: t.tableId, row: nr, col: nc }));
        } else if (IGNITION_KINDS.has(t.kind) && Math.abs(nb - v) > 6) {
          out.push(w("W-06", `Degrau de ${fmt(Math.abs(nb - v))}° entre células vizinhas.`, { tableId: t.tableId, row: nr, col: nc }));
        }
      }
    });
  });
  return out;
}

function num(o: Record<string, unknown> | undefined, k: string): number | null {
  const v = o?.[k];
  return typeof v === "number" ? v : null;
}

export function strategyWarnings(ctx: WarningContext): TuningWarning[] {
  const out: TuningWarning[] = [];
  const lim = ctx.strategies.rev_limiter;
  const hard = num(lim, "hard_rpm");
  if (ctx.maxRpm !== null && hard !== null && lim?.enabled !== false && hard > ctx.maxRpm) {
    out.push(w("W-04", `Corte em ${fmt(hard, 0)} rpm; máximo seguro ${fmt(ctx.maxRpm, 0)} rpm.`, { field: "rev_limiter.hard_rpm" }));
  }
  const ov = ctx.strategies.overrun;
  if (ov && ov.enabled !== false && ov.pops_enabled === true) {
    const adv = num(ov, "ign_advance_deg");
    const delay = num(ov, "fuel_cut_delay_s");
    if (adv !== null && adv < -20) out.push(w("W-05", `Atraso de ${fmt(-adv)}° ATDC (limite didático 20°).`, { field: "overrun.ign_advance_deg" }));
    if (delay !== null && delay > 1.5) out.push(w("W-05", `Janela de corte atrasado de ${fmt(delay)} s (limite didático 1,5 s).`, { field: "overrun.fuel_cut_delay_s" }));
  }
  const boost = ctx.strategies.boost_control;
  const ob = num(boost, "overboost_kpa");
  if (ctx.boostMaxKpa !== null && ob !== null && ob > ctx.boostMaxKpa) {
    out.push(w("W-03", `Corte de sobrepressão em ${fmt(ob, 0)} kPa acima do máximo ${fmt(ctx.boostMaxKpa, 0)} kPa.`, { field: "boost_control.overboost_kpa" }));
  }
  return out;
}

export function computeWarnings(ctx: WarningContext): TuningWarning[] {
  return [...ctx.tables.flatMap((t) => tableWarnings(t, ctx)), ...strategyWarnings(ctx)];
}

/** Chave `row:col` das células com aviso numa tabela (marcador âmbar na grade). */
export function warnedCells(list: readonly TuningWarning[], tableId: string): Map<string, TuningWarning[]> {
  const map = new Map<string, TuningWarning[]>();
  for (const item of list) {
    if (item.tableId !== tableId || item.row === undefined || item.col === undefined) continue;
    const key = `${item.row}:${item.col}`;
    map.set(key, [...(map.get(key) ?? []), item]);
  }
  return map;
}
