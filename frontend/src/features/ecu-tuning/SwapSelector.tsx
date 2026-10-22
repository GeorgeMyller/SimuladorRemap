/**
 * Seletor de troca de ECU (tuning RF-15, EC-14; rest-api E-23): escolhe o perfil standalone
 * (FT-Pro, M1-Race, HT-Elite, pelos nomes genéricos do registo), confirma o snapshot ao sair do
 * OEM e o pacote `race` do M1-Race. Desativado durante a puxada.
 */
import { useId, useState } from "react";

import { Dialog } from "../dyno-cockpit/Dialog";
import type { SwapRequestBody } from "./api";
import { MSG } from "./messages";
import type { EcuProfileSummary } from "./types";

export interface SwapSelectorProps {
  currentProfileId: string;
  profiles: EcuProfileSummary[];
  runActive: boolean;
  onSwap: (body: SwapRequestBody) => Promise<unknown>;
}

export function SwapSelector({ currentProfileId, profiles, runActive, onSwap }: SwapSelectorProps) {
  const uid = useId();
  const [open, setOpen] = useState(false);
  const targets = profiles.filter((p) => p.family === "standalone" && p.profile_id !== currentProfileId);
  const [target, setTarget] = useState<string>("");
  const [confirm, setConfirm] = useState(false);
  const [pkg, setPkg] = useState<"base" | "race">("base");
  const [busy, setBusy] = useState(false);
  const leavingOem = profiles.find((p) => p.profile_id === currentProfileId)?.family === "oem" || currentProfileId === "oem-stage";
  const chosen = target || targets[0]?.profile_id || "";

  return (
    <>
      <button
        type="button"
        disabled={runActive || targets.length === 0}
        title={runActive ? MSG.swapDuringRun : "Trocar a ECU por um perfil standalone"}
        onClick={() => setOpen(true)}
        className="rounded border border-zinc-500 px-3 py-1 text-xs text-zinc-100 hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-50"
      >
        Trocar ECU
      </button>
      {runActive && <span className="sr-only">{MSG.swapDuringRun}</span>}
      {open && (
        <Dialog titleId={`${uid}-t`} title="Trocar ECU" onClose={() => setOpen(false)}>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setBusy(true);
              void onSwap({
                target_profile_id: chosen,
                confirm_snapshot: confirm,
                feature_package: chosen === "m1-race" ? pkg : "base",
                prefill_from_hardware_sheet: true,
                request_id: `swap-${chosen}-${Date.now()}`,
              }).finally(() => {
                setBusy(false);
                setOpen(false);
              });
            }}
            className="flex flex-col gap-2 text-sm"
          >
            <fieldset>
              <legend className="mb-1 font-semibold">Perfil de destino</legend>
              {targets.map((p) => (
                <label key={p.profile_id} className="flex items-start gap-2 py-0.5">
                  <input type="radio" name={`${uid}-target`} value={p.profile_id} checked={chosen === p.profile_id} onChange={() => setTarget(p.profile_id)} />
                  <span>
                    <strong>{p.name}</strong>
                    <span className="block text-xs text-zinc-400">{p.inspiration}</span>
                  </span>
                </label>
              ))}
            </fieldset>
            {chosen === "m1-race" && (
              <label className="flex items-center gap-2 text-xs">
                Pacote
                <select value={pkg} onChange={(e) => setPkg(e.target.value as "base" | "race")} className="rounded border border-zinc-600 bg-zinc-950 px-1 py-0.5">
                  <option value="base">base</option>
                  <option value="race">race</option>
                </select>
              </label>
            )}
            {leavingOem && (
              <label className="flex items-center gap-2 text-xs">
                <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
                Guardar um snapshot da calibração OEM antes da troca
              </label>
            )}
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setOpen(false)} className="rounded border border-zinc-500 px-3 py-1 hover:bg-zinc-800">
                Cancelar
              </button>
              <button type="submit" disabled={busy || !chosen || (leavingOem && !confirm)} className="rounded bg-sky-700 px-3 py-1 font-semibold text-white hover:bg-sky-600 disabled:opacity-50">
                Trocar e abrir o assistente
              </button>
            </div>
          </form>
        </Dialog>
      )}
    </>
  );
}
