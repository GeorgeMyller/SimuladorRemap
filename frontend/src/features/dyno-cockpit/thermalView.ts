/**
 * Estado da Visão Térmica / Raio-X (RF-21; T050), partilhado entre o `CarOnRollerView` (toggle e
 * desenho) e o `useCockpit` (subscrição de `egt_c`/`egt_pre_turbo_c` só quando ligada).
 */
import { useSyncExternalStore } from "react";

let enabled = false;
const listeners = new Set<() => void>();

export function isThermalViewOn(): boolean {
  return enabled;
}

export function setThermalView(on: boolean): void {
  if (on === enabled) return;
  enabled = on;
  for (const l of listeners) l();
}

export function toggleThermalView(): void {
  setThermalView(!enabled);
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useThermalView(): boolean {
  return useSyncExternalStore(subscribe, isThermalViewOn, isThermalViewOn);
}
