/** Menu de unidades (tecla `U`): potência whp/cv/kW, boost bar/psi; temperatura em °C (RF-20). */
import { useEffect, useRef } from "react";

import { BOOST_UNITS, POWER_UNITS, useUnits } from "@/lib/units";

export interface UnitsMenuProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function UnitsMenu({ open, onOpenChange }: UnitsMenuProps) {
  const { units, setUnits } = useUnits();
  const firstRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (open) firstRef.current?.focus();
  }, [open]);
  return (
    <div className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-controls="units-menu"
        aria-keyshortcuts="U"
        onClick={() => onOpenChange(!open)}
        className="rounded border border-zinc-500 px-2 py-0.5 text-sm hover:bg-zinc-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-400"
      >
        Unidades: {units.power} · {units.boost} · °C
      </button>
      {open && (
        <div
          id="units-menu"
          className="absolute right-0 z-40 mt-1 w-56 rounded border border-zinc-600 bg-zinc-900 p-3 text-sm shadow-lg"
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.stopPropagation();
              onOpenChange(false);
            }
          }}
        >
          <fieldset className="mb-2">
            <legend className="mb-1 text-zinc-300">Potência</legend>
            {POWER_UNITS.map((u, i) => (
              <label key={u} className="mr-3 inline-flex items-center gap-1">
                <input
                  ref={i === 0 ? firstRef : undefined}
                  type="radio"
                  name="power-unit"
                  value={u}
                  checked={units.power === u}
                  onChange={() => setUnits({ ...units, power: u })}
                />
                {u}
              </label>
            ))}
          </fieldset>
          <fieldset className="mb-2">
            <legend className="mb-1 text-zinc-300">Boost</legend>
            {BOOST_UNITS.map((u) => (
              <label key={u} className="mr-3 inline-flex items-center gap-1">
                <input type="radio" name="boost-unit" value={u} checked={units.boost === u} onChange={() => setUnits({ ...units, boost: u })} />
                {u}
              </label>
            ))}
          </fieldset>
          <p className="text-xs text-zinc-400">Temperatura em °C e torque em N·m.</p>
        </div>
      )}
    </div>
  );
}
