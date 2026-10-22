/**
 * Seletor dos 4 carros (rest-api E-03 `GET /vehicles?include_drafts=true`): trocar de carro cria
 * uma sessão nova com o perfil de série e abre o workspace dela. Com a capacidade cheia
 * (409 `SIM_CAPACITY_EXCEEDED`) oferece fechar a sessão atual antes.
 */
import { useEffect, useId, useState } from "react";

import { isApiProblem } from "@/lib/api";

import type { EcuApi } from "./api";
import type { Session, VehicleSummary } from "./types";

export interface VehicleSelectorProps {
  api: Pick<EcuApi, "listVehicles">;
  currentVehicleId: string;
  disabled?: boolean;
  onSwitch: (vehicleId: string, profileId: string, closeCurrent: boolean) => Promise<Session>;
  onSwitched: (session: Session) => void;
}

export function VehicleSelector({ api, currentVehicleId, disabled = false, onSwitch, onSwitched }: VehicleSelectorProps) {
  const id = useId();
  const [items, setItems] = useState<VehicleSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [capacity, setCapacity] = useState<VehicleSummary | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .listVehicles()
      .then((r) => {
        if (!cancelled) setItems(r.items);
      })
      .catch(() => {
        if (!cancelled) setError("Catálogo de carros indisponível.");
      });
    return () => {
      cancelled = true;
    };
  }, [api]);

  const go = async (v: VehicleSummary, closeCurrent: boolean) => {
    setError(null);
    try {
      const session = await onSwitch(v.vehicle_id, v.stock_profile_id ?? "oem-stage", closeCurrent);
      setCapacity(null);
      onSwitched(session);
    } catch (e) {
      if (isApiProblem(e) && e.code === "SIM_CAPACITY_EXCEEDED" && !closeCurrent) setCapacity(v);
      else setError(isApiProblem(e) ? `${e.title}: ${e.detail}` : "Não foi possível trocar de carro.");
    }
  };

  return (
    <div className="flex items-center gap-2 text-xs">
      <label htmlFor={id} className="text-zinc-300">
        Carro
      </label>
      <select
        id={id}
        value={currentVehicleId}
        disabled={disabled || !items}
        onChange={(e) => {
          const v = items?.find((i) => i.vehicle_id === e.target.value);
          if (v && v.vehicle_id !== currentVehicleId) void go(v, false);
        }}
        className="rounded border border-zinc-600 bg-zinc-950 px-1 py-1 text-zinc-100"
      >
        {!items && <option value={currentVehicleId}>{currentVehicleId}</option>}
        {items?.map((v) => (
          <option key={v.vehicle_id} value={v.vehicle_id}>
            {v.display_name}
            {v.validation_status === "draft" ? " (rascunho)" : ""}
          </option>
        ))}
      </select>
      {capacity && (
        <span role="alert" className="text-amber-300">
          Limite de sessões atingido.{" "}
          <button type="button" onClick={() => void go(capacity, true)} className="underline">
            Fechar a sessão atual e abrir {capacity.display_name}
          </button>
        </span>
      )}
      {error && (
        <span role="alert" className="text-red-300">
          {error}
        </span>
      )}
    </div>
  );
}
