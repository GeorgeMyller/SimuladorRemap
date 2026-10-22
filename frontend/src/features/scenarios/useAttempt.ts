/**
 * Leitura da tentativa com polling: 2 s enquanto `preparing` ou `evaluating`; 10 s em `in_progress`
 * (puxadas e critérios provisórios mudam a cada puxada feita na bancada ou noutra aba).
 */
import { useCallback, useEffect, useState } from "react";

import { useScenariosApi } from "./api";
import type { AttemptState, AttemptView } from "./types";

export const POLL_MS = 2000;
export const IN_PROGRESS_POLL_MS = 10_000;
const POLLING_STATES: ReadonlySet<AttemptState> = new Set(["preparing", "evaluating"]);
export const TERMINAL_STATES: ReadonlySet<AttemptState> = new Set([
  "passed",
  "failed_final",
  "abandoned",
  "expired",
  "failed_to_start",
]);

export function useAttempt(attemptId: string, pollMs = POLL_MS, slowPollMs = IN_PROGRESS_POLL_MS) {
  const api = useScenariosApi();
  const [attempt, setAttempt] = useState<AttemptView | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let alive = true;
    api
      .getAttempt(attemptId)
      .then((a) => {
        if (!alive) return;
        setAttempt(a);
        setError(null);
      })
      .catch((e: unknown) => {
        if (alive) setError(e);
      });
    return () => {
      alive = false;
    };
  }, [api, attemptId, tick]);

  const state = attempt?.state;
  useEffect(() => {
    if (state === undefined) return;
    const delay = POLLING_STATES.has(state) ? pollMs : state === "in_progress" ? slowPollMs : null;
    if (delay === null) return;
    const timer = setTimeout(() => setTick((t) => t + 1), delay);
    return () => clearTimeout(timer);
  }, [state, pollMs, slowPollMs, attempt]);

  const refresh = useCallback(() => setTick((t) => t + 1), []);
  return { attempt, setAttempt, error, refresh };
}
