/**
 * Correções por cilindro (tuning RF-21): trim de combustível ±25 % e de ignição ±10° para cada
 * cilindro do motor ativo. Grava o valor uniforme nas tabelas `fuel_trim_cyl`/`ignition_trim_cyl`
 * de cada cilindro (a edição célula a célula continua no editor da tabela).
 */
import { useId, useState, type FormEvent } from "react";
import { z } from "zod";

import { formatNumber } from "@/lib/units";

import { parseCellNumber } from "./ops/tsv";

export const FUEL_TRIM_LIMIT_PCT = 25;
export const IGN_TRIM_LIMIT_DEG = 10;

export const fuelTrimSchema = z
  .number({ error: "Digite um número" })
  .min(-FUEL_TRIM_LIMIT_PCT, { error: `Limite do trim de combustível: ±${FUEL_TRIM_LIMIT_PCT} %` })
  .max(FUEL_TRIM_LIMIT_PCT, { error: `Limite do trim de combustível: ±${FUEL_TRIM_LIMIT_PCT} %` });
export const ignTrimSchema = z
  .number({ error: "Digite um número" })
  .min(-IGN_TRIM_LIMIT_DEG, { error: `Limite do trim de ignição: ±${IGN_TRIM_LIMIT_DEG}°` })
  .max(IGN_TRIM_LIMIT_DEG, { error: `Limite do trim de ignição: ±${IGN_TRIM_LIMIT_DEG}°` });

export type TrimKind = "fuel_trim_cyl" | "ignition_trim_cyl";

export interface CylinderTrimsProps {
  nCyl: number;
  /** Valor atual (média da tabela do cilindro) ou `null` sem tabela. */
  fuel: Record<number, number | null>;
  ignition: Record<number, number | null>;
  disabled?: boolean;
  onSave: (kind: TrimKind, byCylinder: Record<number, number>) => Promise<void>;
}

type Row = Record<number, string>;

function initRow(values: Record<number, number | null>, n: number): Row {
  const out: Row = {};
  for (let c = 1; c <= n; c += 1) out[c] = values[c] === null || values[c] === undefined ? "" : String(Number(values[c]!.toFixed(2)));
  return out;
}

export function CylinderTrims({ nCyl, fuel, ignition, disabled = false, onSave }: CylinderTrimsProps) {
  const id = useId();
  const [fuelRow, setFuelRow] = useState<Row>(() => initRow(fuel, nCyl));
  const [ignRow, setIgnRow] = useState<Row>(() => initRow(ignition, nCyl));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [status, setStatus] = useState("");
  const cylinders = Array.from({ length: nCyl }, (_, i) => i + 1);

  const collect = (row: Row, values: Record<number, number | null>, schema: z.ZodNumber, prefix: string, errs: Record<string, string>) => {
    const out: Record<number, number> = {};
    for (const c of cylinders) {
      if (values[c] === null || values[c] === undefined) continue;
      const n = parseCellNumber(row[c] ?? "");
      const parsed = schema.safeParse(n ?? Number.NaN);
      if (!parsed.success) errs[`${prefix}${c}`] = parsed.error.issues[0]?.message ?? "Valor inválido";
      else out[c] = parsed.data;
    }
    return out;
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const errs: Record<string, string> = {};
    const f = collect(fuelRow, fuel, fuelTrimSchema, "f", errs);
    const g = collect(ignRow, ignition, ignTrimSchema, "i", errs);
    setErrors(errs);
    if (Object.keys(errs).length > 0) {
      setStatus("Corrija os valores fora do limite.");
      return;
    }
    setStatus("A gravar…");
    if (Object.keys(f).length > 0) await onSave("fuel_trim_cyl", f);
    if (Object.keys(g).length > 0) await onSave("ignition_trim_cyl", g);
    setStatus("Correções gravadas.");
  };

  const cellInput = (prefix: "f" | "i", c: number, row: Row, set: (r: Row) => void, available: boolean, label: string) => {
    const key = `${prefix}${c}`;
    const err = errors[key];
    return (
      <td key={c} className="px-1 py-1 align-top">
        <input
          aria-label={`${label} cilindro ${c}`}
          inputMode="decimal"
          value={row[c] ?? ""}
          disabled={disabled || !available}
          placeholder={available ? "" : "—"}
          aria-invalid={err ? true : undefined}
          aria-describedby={err ? `${id}-${key}` : undefined}
          onChange={(e) => set({ ...row, [c]: e.target.value })}
          className="w-16 rounded border border-zinc-600 bg-zinc-950 px-1 py-0.5 text-right font-mono text-xs text-zinc-100 aria-[invalid=true]:border-red-400"
        />
        {err && (
          <p id={`${id}-${key}`} role="alert" className="mt-0.5 max-w-[8rem] text-[11px] text-red-300">
            {err}
          </p>
        )}
      </td>
    );
  };

  return (
    <form onSubmit={(e) => void submit(e)} aria-label="Correções por cilindro" className="rounded border border-zinc-700 bg-zinc-900 p-3" noValidate>
      <h2 className="mb-2 text-base font-semibold text-zinc-100">Correções por cilindro</h2>
      <table className="text-xs">
        <caption className="sr-only">Trims por cilindro</caption>
        <thead>
          <tr>
            <th scope="col" className="px-1 text-left text-zinc-300">
              Correção
            </th>
            {cylinders.map((c) => (
              <th key={c} scope="col" className="px-1 text-zinc-300" data-cylinder-col={c}>
                Cil. {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row" className="px-1 text-left font-normal text-zinc-200">
              Combustível (±{formatNumber(FUEL_TRIM_LIMIT_PCT, 0)} %)
            </th>
            {cylinders.map((c) => cellInput("f", c, fuelRow, setFuelRow, fuel[c] !== null && fuel[c] !== undefined, "Trim de combustível"))}
          </tr>
          <tr>
            <th scope="row" className="px-1 text-left font-normal text-zinc-200">
              Ignição (±{formatNumber(IGN_TRIM_LIMIT_DEG, 0)}°)
            </th>
            {cylinders.map((c) => cellInput("i", c, ignRow, setIgnRow, ignition[c] !== null && ignition[c] !== undefined, "Trim de ignição"))}
          </tr>
        </tbody>
      </table>
      <div className="mt-2 flex items-center gap-2">
        <button type="submit" disabled={disabled} className="rounded bg-sky-700 px-3 py-1 text-xs font-semibold text-white hover:bg-sky-600 disabled:opacity-50">
          Gravar correções
        </button>
        <span role="status" className="text-xs text-zinc-300">
          {status}
        </span>
      </div>
    </form>
  );
}
