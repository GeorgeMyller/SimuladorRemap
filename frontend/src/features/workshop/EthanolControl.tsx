/** Flex Fuel (002 RF-18, RF-19): liga o combustível misturado e escolhe o teor de etanol (E27 a E100). */
import { ETHANOL_DEFAULT_PCT, ETHANOL_MAX_PCT, ETHANOL_MIN_PCT } from "./types";

export interface EthanolControlProps {
  allowed: boolean;
  /** `null` = Flex desligado. */
  value: number | null;
  disabled: boolean;
  onChange: (ethanolPct: number | null) => void;
}

export function EthanolControl({ allowed, value, disabled, onChange }: EthanolControlProps) {
  if (!allowed) {
    return <p className="mt-4 text-sm text-zinc-300">Flex Fuel indisponível: este carro não permite E27 e E100.</p>;
  }
  const isOn = value !== null;
  return (
    <div className="mt-4 flex flex-col gap-3 rounded border border-zinc-800 p-3 sm:flex-row sm:items-center">
      <label htmlFor="flex-fuel" className="flex cursor-pointer items-center gap-2 text-sm font-semibold">
        <input
          id="flex-fuel"
          type="checkbox"
          checked={isOn}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked ? ETHANOL_DEFAULT_PCT : null)}
          className="accent-amber-400"
        />
        Flex Fuel
      </label>
      {isOn && (
        <div className="flex flex-1 items-center gap-3">
          <label htmlFor="ethanol-pct" className="text-sm">
            Teor de etanol
          </label>
          <input
            id="ethanol-pct"
            type="range"
            min={ETHANOL_MIN_PCT}
            max={ETHANOL_MAX_PCT}
            step={1}
            value={value}
            disabled={disabled}
            aria-valuetext={`E${value}, ${value} % de etanol`}
            onChange={(e) => onChange(Number(e.target.value))}
            className="flex-1 accent-amber-400"
          />
          <output htmlFor="ethanol-pct" className="w-24 text-right font-mono text-sm text-amber-300">
            E{value} ({value} %)
          </output>
        </div>
      )}
    </div>
  );
}
