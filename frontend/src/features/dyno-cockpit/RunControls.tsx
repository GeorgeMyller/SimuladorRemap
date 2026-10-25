/**
 * Controles da puxada (RF-12, RF-13; D-14): tipo de puxada, parâmetros, Iniciar/Abortar e
 * borboleta por slider/teclado com `control.throttle` limitado a 20 mensagens/s. Com `arrowKeys`, as
 * setas controlam a borboleta em toda a bancada e nunca rolam a página; segurar Espaço é o
 * acelerador com mola (`useHoldThrottle`, RF-22).
 */
import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import type { DynoRunRequest, RunType } from "./api";
import type { CockpitState } from "./cockpitState";
import { isTypingTarget } from "./keyboardTargets";
import { MSG, RUN_TYPE_LABEL } from "./messages";
import { useHoldThrottle } from "./useHoldThrottle";

/** Envio limitado a `maxPerSecond` (intervalo mínimo), com envio final do último valor. */
export class ThrottleSender {
  private readonly minIntervalMs: number;
  private lastSent = -Infinity;
  private pending: number | null = null;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private readonly send: (pct: number) => void;
  private readonly now: () => number;

  constructor(send: (pct: number) => void, maxPerSecond = 20, now: () => number = () => performance.now()) {
    this.send = send;
    this.minIntervalMs = 1000 / maxPerSecond;
    this.now = now;
  }

  push(pct: number): void {
    const t = this.now();
    if (t - this.lastSent >= this.minIntervalMs) {
      this.lastSent = t;
      this.pending = null;
      this.send(pct);
      return;
    }
    this.pending = pct;
    if (this.timer === undefined) {
      this.timer = setTimeout(() => {
        this.timer = undefined;
        if (this.pending !== null) {
          const v = this.pending;
          this.pending = null;
          this.lastSent = this.now();
          this.send(v);
        }
      }, this.minIntervalMs - (t - this.lastSent));
    }
  }

  dispose(): void {
    if (this.timer !== undefined) clearTimeout(this.timer);
    this.timer = undefined;
  }
}

export function clampThrottle(v: number): number {
  return Math.min(100, Math.max(0, Math.round(v)));
}

/** W / Seta-cima +5 %, S / Seta-baixo −5 %, com Shift ±1 % (presos em 0–100). */
export function throttleStep(current: number, key: string, shift: boolean): number | null {
  const step = shift ? 1 : 5;
  if (key === "w" || key === "W" || key === "ArrowUp" || key === "ArrowRight") return clampThrottle(current + step);
  if (key === "s" || key === "S" || key === "ArrowDown" || key === "ArrowLeft") return clampThrottle(current - step);
  if (key === "Home") return 0;
  if (key === "End") return 100;
  return null;
}

const THROTTLE_GLOBAL_KEYS = new Set(["w", "W", "s", "S", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"]);
const THROTTLE_STEP_KEYS = new Set(["w", "W", "s", "S", "ArrowUp", "ArrowDown"]);

export const RUN_TYPES: readonly RunType[] = ["baseline_pull", "sweep_pull", "steady_state_hold", "multi_pull"];

export function stateLabel(state: CockpitState): string {
  switch (state.kind) {
    case "loading":
      return "a carregar";
    case "empty":
    case "ready":
      return MSG.ready;
    case "running":
      return "puxada em curso";
    case "completed":
      return "puxada concluída";
    case "aborted":
      return MSG.aborted;
    case "destroyed":
      return MSG.engineDestroyed.toLowerCase();
    case "error":
      return "erro";
  }
}

export interface RunControlsProps {
  state: CockpitState;
  /** Motivo extra para desativar "Iniciar" (backend indisponível, WS a conectar). */
  disabledReason?: string | null;
  defaultEndRpm: number;
  onStart: (req: DynoRunRequest) => void;
  onAbort: () => void;
  onThrottle: (pct: number) => void;
  error?: string | null;
  /**
   * Setas globais (fora de campos de texto): ↑/↓ mexem na borboleta quando ativa; todas as setas
   * têm `preventDefault` para a página não rolar. Desligar com diálogos abertos.
   */
  arrowKeys?: boolean;
}

export function RunControls({ state, disabledReason = null, defaultEndRpm, onStart, onAbort, onThrottle, error = null, arrowKeys = false }: RunControlsProps) {
  const [runType, setRunType] = useState<RunType>("sweep_pull");
  const [startRpm, setStartRpm] = useState(2000);
  const [endRpm, setEndRpm] = useState(Math.round(defaultEndRpm));
  const [gear, setGear] = useState(4);
  const [rampRate, setRampRate] = useState(300);
  const [pullCount, setPullCount] = useState(3);
  const [holdRpm, setHoldRpm] = useState(3500);
  const [throttle, setThrottle] = useState(0);
  const senderRef = useRef<ThrottleSender | null>(null);
  const throttleCb = useRef(onThrottle);
  useEffect(() => {
    throttleCb.current = onThrottle;
  });
  useEffect(() => {
    const sender = new ThrottleSender((pct) => throttleCb.current(pct));
    senderRef.current = sender;
    return () => sender.dispose();
  }, []);

  const running = state.kind === "running";
  const blocked = state.kind === "loading" || state.kind === "destroyed" || state.kind === "error" || disabledReason !== null;
  const canStart = !running && !blocked;
  const throttleEnabled = !running && state.kind !== "destroyed" && state.kind !== "loading" && state.kind !== "error";

  const setAndSend = (v: number) => {
    const pct = clampThrottle(v);
    setThrottle(pct);
    senderRef.current?.push(pct);
  };

  const arrowState = useRef({ throttle, throttleEnabled });
  useEffect(() => {
    arrowState.current = { throttle, throttleEnabled };
  });
  useEffect(() => {
    if (!arrowKeys) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return;
      if (!THROTTLE_GLOBAL_KEYS.has(e.key) || isTypingTarget(e.target)) return;
      e.preventDefault();
      const { throttle: current, throttleEnabled: enabled } = arrowState.current;
      if (!enabled || !THROTTLE_STEP_KEYS.has(e.key)) return;
      const pct = throttleStep(current, e.key, e.shiftKey)!;
      arrowState.current = { throttle: pct, throttleEnabled: enabled };
      setThrottle(pct);
      senderRef.current?.push(pct);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [arrowKeys]);

  const { holding } = useHoldThrottle({
    listen: arrowKeys,
    enabled: throttleEnabled,
    value: throttle,
    onChange: (pct) => {
      arrowState.current = { throttle: pct, throttleEnabled: arrowState.current.throttleEnabled };
      setThrottle(pct);
      senderRef.current?.push(pct);
    },
  });

  const buildRequest = (): DynoRunRequest => {
    const base: DynoRunRequest = { run_type: runType, gear, start_rpm: startRpm, end_rpm: endRpm, ramp_rate_rpm_s: rampRate };
    if (runType === "multi_pull") return { ...base, pull_count: pullCount };
    if (runType === "steady_state_hold") {
      return { run_type: runType, gear, start_rpm: Math.min(startRpm, holdRpm), cells: [{ rpm: holdRpm, pedal_pct: Math.max(1, throttle), hold_s: 5 }] };
    }
    return base;
  };

  const start = () => {
    if (canStart) onStart(buildRequest());
  };

  const onKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    const target = e.target as HTMLElement;
    if (e.key === "Enter" && target.tagName !== "BUTTON" && target.tagName !== "SELECT") {
      e.preventDefault();
      start();
    }
  };

  const field = "w-20 min-w-0 rounded border border-zinc-600 bg-zinc-950 px-1 py-0.5 font-mono text-zinc-100 disabled:opacity-50";

  return (
    <section aria-labelledby="run-controls-title" onKeyDown={onKeyDown} className="flex flex-col gap-2 rounded border border-zinc-700 bg-zinc-900 p-3 text-sm">
      <div className="flex items-center justify-between">
        <h2 id="run-controls-title" className="font-semibold">
          Puxada
        </h2>
        <span data-testid="run-status" role="status" className={`font-semibold ${state.kind === "aborted" ? "text-amber-300" : state.kind === "destroyed" ? "text-red-300" : "text-zinc-200"}`}>
          {stateLabel(state)}
        </span>
      </div>
      <label className="flex items-center justify-between gap-2">
        Tipo
        <select
          aria-label="Tipo de puxada"
          value={runType}
          disabled={running}
          onChange={(e) => setRunType(e.target.value as RunType)}
          className="rounded border border-zinc-600 bg-zinc-950 px-1 py-0.5 text-zinc-100"
        >
          {RUN_TYPES.map((t) => (
            <option key={t} value={t}>
              {RUN_TYPE_LABEL[t]}
            </option>
          ))}
        </select>
      </label>
      <div className="grid grid-cols-1 gap-x-3 gap-y-1 min-[360px]:grid-cols-2">
        <label className="flex items-center justify-between gap-1">
          Marcha
          <input aria-label="Marcha" className={field} type="number" min={1} max={10} value={gear} disabled={running} onChange={(e) => setGear(Number(e.target.value))} />
        </label>
        {runType === "steady_state_hold" ? (
          <label className="flex items-center justify-between gap-1">
            RPM alvo
            <input aria-label="RPM alvo" className={field} type="number" min={500} max={12000} step={100} value={holdRpm} disabled={running} onChange={(e) => setHoldRpm(Number(e.target.value))} />
          </label>
        ) : (
          <>
            <label className="flex items-center justify-between gap-1">
              RPM inicial
              <input aria-label="RPM inicial" className={field} type="number" min={1000} max={10000} step={100} value={startRpm} disabled={running} onChange={(e) => setStartRpm(Number(e.target.value))} />
            </label>
            <label className="flex items-center justify-between gap-1">
              RPM final
              <input aria-label="RPM final" className={field} type="number" min={1500} max={12000} step={100} value={endRpm} disabled={running} onChange={(e) => setEndRpm(Number(e.target.value))} />
            </label>
            <label className="flex items-center justify-between gap-1">
              Rampa (rpm/s)
              <input aria-label="Rampa" className={field} type="number" min={50} max={1000} step={50} value={rampRate} disabled={running} onChange={(e) => setRampRate(Number(e.target.value))} />
            </label>
          </>
        )}
        {runType === "multi_pull" && (
          <label className="flex items-center justify-between gap-1">
            Puxadas
            <input aria-label="Número de puxadas" className={field} type="number" min={2} max={10} value={pullCount} disabled={running} onChange={(e) => setPullCount(Number(e.target.value))} />
          </label>
        )}
      </div>
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between">
          <span className="font-medium text-xs sm:text-sm">
            Borboleta: <span className="font-mono text-amber-400 font-bold">{throttle} %</span>
          </span>
          <span className="hidden sm:inline font-mono text-xs text-zinc-400">{MSG.throttleHint}</span>
        </div>
        <input
          type="range"
          min={0}
          max={100}
          step={1}
          value={throttle}
          disabled={!throttleEnabled}
          aria-label="Borboleta"
          aria-keyshortcuts="w s ArrowUp ArrowDown Space"
          data-holding={holding || undefined}
          aria-valuetext={`${throttle} %`}
          onChange={(e) => setAndSend(Number(e.target.value))}
          onKeyDown={(e) => {
            const next = throttleStep(throttle, e.key, e.shiftKey);
            if (next !== null) {
              e.preventDefault();
              setAndSend(next);
            }
          }}
          className="h-2 w-full cursor-pointer accent-amber-400 disabled:opacity-40"
        />
        <div className="flex items-center gap-1.5 pt-0.5">
          {[0, 25, 50, 75, 100].map((pct) => (
            <button
              key={pct}
              type="button"
              disabled={!throttleEnabled}
              onClick={() => setAndSend(pct)}
              className={`flex-1 rounded py-1 text-xs font-semibold transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
                throttle === pct
                  ? "bg-amber-500 text-zinc-950 shadow-sm"
                  : "bg-zinc-800 text-zinc-300 hover:bg-zinc-700 active:bg-zinc-600"
              }`}
            >
              {pct === 100 ? "100% WOT" : `${pct}%`}
            </button>
          ))}
        </div>
      </div>
      <div className="flex gap-2 pt-1">
        <button
          type="button"
          onClick={start}
          disabled={!canStart}
          aria-keyshortcuts="Enter"
          className="flex-1 rounded-lg bg-emerald-500 py-3 sm:py-2 text-base sm:text-sm font-bold text-zinc-950 hover:bg-emerald-400 active:scale-[0.98] transition-transform disabled:cursor-not-allowed disabled:bg-zinc-700 disabled:text-zinc-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-white"
        >
          {MSG.start}
        </button>
        <button
          type="button"
          onClick={onAbort}
          disabled={!running}
          aria-keyshortcuts="Escape"
          className="flex-1 rounded-lg bg-red-600 py-3 sm:py-2 text-base sm:text-sm font-bold text-white hover:bg-red-500 active:scale-[0.98] transition-transform disabled:cursor-not-allowed disabled:bg-zinc-700 disabled:text-zinc-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-white"
        >
          {MSG.abort}
        </button>
      </div>
      {disabledReason && <p className="text-xs text-zinc-300">{disabledReason}</p>}
      {error && (
        <p role="alert" className="text-xs font-semibold text-red-300">
          {error}
        </p>
      )}
    </section>
  );
}
