import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

import { DEFAULT_UNITS, type UnitsPrefs } from "./units";

export interface UnitsContextValue {
  units: UnitsPrefs;
  setUnits: (next: UnitsPrefs) => void;
}

const UnitsContext = createContext<UnitsContextValue | null>(null);

export interface UnitsProviderProps {
  /** Valor controlado (ex.: preferências da cockpit). Sem ele o provider guarda estado próprio. */
  value?: UnitsPrefs;
  onChange?: (next: UnitsPrefs) => void;
  initial?: UnitsPrefs;
  children: ReactNode;
}

/** Fornece as unidades de exibição a gráficos, gauges, eventos e exportações de tela. */
export function UnitsProvider({ value, onChange, initial = DEFAULT_UNITS, children }: UnitsProviderProps) {
  const [inner, setInner] = useState<UnitsPrefs>(initial);
  const units = value ?? inner;
  const ctx = useMemo<UnitsContextValue>(
    () => ({
      units,
      setUnits: (next) => {
        if (value === undefined) setInner(next);
        onChange?.(next);
      },
    }),
    [units, value, onChange],
  );
  return <UnitsContext.Provider value={ctx}>{children}</UnitsContext.Provider>;
}

/** Unidades atuais; fora de um provider devolve os padrões (whp, bar, °C, N·m). */
export function useUnits(): UnitsContextValue {
  const ctx = useContext(UnitsContext);
  return ctx ?? { units: DEFAULT_UNITS, setUnits: () => undefined };
}
