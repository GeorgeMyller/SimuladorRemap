/** Catálogo de peças (uma vez) e compatibilidade do veículo selecionado (a cada troca de carro). */
import { useCallback, useEffect, useState } from "react";

import { isApiProblem } from "@/lib/api";

import type { WorkshopApi } from "./api";
import type { UpgradeCategoryOptions, VehicleCompat } from "./types";

export type StageBuilderData =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; categories: UpgradeCategoryOptions[]; compat: VehicleCompat };

function errorMessage(error: unknown): string {
  if (isApiProblem(error)) return `${error.detail || error.title} (${error.code})`;
  return "Resposta do servidor fora do contrato da API.";
}

export function useStageBuilderData(api: WorkshopApi, vehicleId: string): { data: StageBuilderData; retry: () => void } {
  const [categories, setCategories] = useState<UpgradeCategoryOptions[] | null>(null);
  const [compat, setCompat] = useState<VehicleCompat | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [round, setRound] = useState(0);

  useEffect(() => {
    let alive = true;
    void api
      .listUpgrades()
      .then((list) => alive && setCategories(list))
      .catch((e: unknown) => alive && setError(errorMessage(e)));
    return () => {
      alive = false;
    };
  }, [api, round]);

  useEffect(() => {
    if (!vehicleId) return;
    let alive = true;
    void api
      .getVehicleCompat(vehicleId)
      .then((value) => alive && setCompat(value))
      .catch((e: unknown) => alive && setError(errorMessage(e)));
    return () => {
      alive = false;
    };
  }, [api, vehicleId, round]);

  const retry = useCallback(() => {
    setError(null);
    setRound((r) => r + 1);
  }, []);

  if (error) return { data: { status: "error", message: error }, retry };
  if (!categories || compat?.vehicleId !== vehicleId) return { data: { status: "loading" }, retry };
  return { data: { status: "ready", categories, compat }, retry };
}
