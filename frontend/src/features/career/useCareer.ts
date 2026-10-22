/** Perfil da oficina, ordens e serviços do perfil de jogador ativo (carregados em paralelo). */
import { useCallback, useEffect, useState } from "react";

import type { CareerApi } from "./api";
import { careerError, type CareerError, type CareerJob, type CareerProfile, type WorkOrder } from "./types";

export type CareerData =
  | { status: "loading" }
  | { status: "error"; error: CareerError }
  | { status: "ready"; profile: CareerProfile; orders: WorkOrder[]; jobs: CareerJob[] };

export function useCareer(api: CareerApi, profileId: string | null): { data: CareerData; reload: () => void } {
  const [data, setData] = useState<CareerData>({ status: "loading" });
  const [round, setRound] = useState(0);

  useEffect(() => {
    if (!profileId) return;
    let alive = true;
    void Promise.all([api.getProfile(profileId), api.listOrders(), api.listJobs(profileId)])
      .then(([profile, orders, jobs]) => alive && setData({ status: "ready", profile, orders, jobs }))
      .catch((e: unknown) => alive && setData({ status: "error", error: careerError(e) }));
    return () => {
      alive = false;
    };
  }, [api, profileId, round]);

  const reload = useCallback(() => setRound((r) => r + 1), []);
  return { data, reload };
}
