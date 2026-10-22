/**
 * Máquina de estados da cockpit (§9 `CockpitState`; RF-12, RF-15, RF-16; D-WS-04):
 * vazio/carregando/erro/pronto/em curso/concluída/abortada/motor destruído.
 */
import type { RunStatePayload } from "@/lib/ws";

export type CockpitState =
  | { kind: "loading" }
  | { kind: "empty" }
  | { kind: "ready" }
  | { kind: "running"; runId: string }
  | { kind: "completed"; runId: string }
  | { kind: "aborted"; runId: string }
  | { kind: "destroyed"; runId: string }
  | { kind: "error"; code: string; title: string; detail?: string };

export type CockpitAction =
  | { type: "loaded"; hasRuns: boolean; engineLocked: boolean; activeRunId: string | null; lastRunId: string | null }
  | { type: "loadFailed"; code: string; title: string; detail?: string }
  | { type: "runStarted"; runId: string }
  | { type: "runState"; payload: RunStatePayload }
  | { type: "failure"; runId: string | null; catastrophic: boolean }
  | { type: "engineDestroyed"; runId: string | null }
  | { type: "restored" };

export const ACTIVE_RUN_STATES = new Set(["arming", "running", "coastdown"]);

export function cockpitReducer(state: CockpitState, action: CockpitAction): CockpitState {
  switch (action.type) {
    case "loaded":
      if (action.engineLocked) return { kind: "destroyed", runId: action.lastRunId ?? "" };
      if (action.activeRunId) return { kind: "running", runId: action.activeRunId };
      return action.hasRuns ? { kind: "ready" } : { kind: "empty" };
    case "loadFailed":
      return { kind: "error", code: action.code, title: action.title, ...(action.detail ? { detail: action.detail } : {}) };
    case "runStarted":
      if (state.kind === "destroyed") return state;
      return { kind: "running", runId: action.runId };
    case "runState": {
      const p = action.payload;
      if (state.kind === "loading" || state.kind === "error") return state;
      const runId = p.run_id ?? ("runId" in state ? state.runId : "");
      if (p.state === "engine_failed") return { kind: "destroyed", runId };
      if (state.kind === "destroyed") return state;
      if (ACTIVE_RUN_STATES.has(p.state) && p.run_id) return { kind: "running", runId: p.run_id };
      if (p.state === "completed" && p.run_id) return { kind: "completed", runId: p.run_id };
      if (p.state === "aborted" && p.run_id) {
        // Abort por falha catastrófica chega depois do engine_failed: mantém "destruído".
        return p.abort_reason === "catastrophic_failure" ? { kind: "destroyed", runId: p.run_id } : { kind: "aborted", runId: p.run_id };
      }
      return state;
    }
    case "failure":
      if (!action.catastrophic) return state;
      return { kind: "destroyed", runId: action.runId ?? ("runId" in state ? state.runId : "") };
    case "engineDestroyed":
      return { kind: "destroyed", runId: action.runId ?? ("runId" in state ? state.runId : "") };
    case "restored":
      return state.kind === "destroyed" ? { kind: "ready" } : state;
  }
}
