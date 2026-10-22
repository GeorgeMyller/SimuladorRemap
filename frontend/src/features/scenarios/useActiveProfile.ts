/** Perfil ativo (local, sem senha) partilhado pelas telas dos cenários. */
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";

import { getActiveProfileId, setActiveProfileId, useScenariosApi } from "./api";
import { ACTIVE_PROFILE_KEY, type PlayerProfile } from "./types";

const EVENT = "simremap:active-profile";

function subscribe(onChange: () => void): () => void {
  const onStorage = (e: StorageEvent) => {
    if (e.key === ACTIVE_PROFILE_KEY) onChange();
  };
  window.addEventListener(EVENT, onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(EVENT, onChange);
    window.removeEventListener("storage", onStorage);
  };
}

/** Troca o perfil ativo e avisa as telas abertas. */
export function selectProfile(profileId: string | null): void {
  setActiveProfileId(profileId);
  window.dispatchEvent(new Event(EVENT));
}

export function useActiveProfileId(): string | null {
  return useSyncExternalStore(subscribe, getActiveProfileId, () => null);
}

export interface ActiveProfileState {
  profiles: PlayerProfile[];
  active: PlayerProfile | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export function useProfiles(): ActiveProfileState {
  const api = useScenariosApi();
  const activeId = useActiveProfileId();
  const [profiles, setProfiles] = useState<PlayerProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let alive = true;
    api
      .listProfiles()
      .then((list) => {
        if (!alive) return;
        setProfiles(list);
        setError(null);
      })
      .catch((e: unknown) => {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [api, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  const active = profiles.find((p) => p.profile_id === activeId) ?? null;
  return { profiles, active, loading, error, reload };
}
