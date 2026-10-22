/**
 * Acelerador com mola (RF-22; D-13): segurar Espaço sobe o pedal a 120 %/s até 100 %; soltar volta
 * a 0 % de imediato. O valor sai por `onChange` (o `RunControls` envia pelo `ThrottleSender`).
 */
import { useEffect, useRef, useState } from "react";

import { isPlainShortcut } from "./keyboardTargets";

export const HOLD_RATE_PCT_PER_S = 120;

/** Pedal após `elapsedMs` de Espaço pressionado a partir de `startPct` (inteiro, 0..100). */
export function holdTarget(startPct: number, elapsedMs: number): number {
  const pct = startPct + (HOLD_RATE_PCT_PER_S * Math.max(0, elapsedMs)) / 1000;
  return Math.min(100, Math.max(0, Math.round(pct)));
}

export interface HoldThrottleOptions {
  /** Escuta o teclado global (desligar com diálogos abertos). */
  listen: boolean;
  /** Borboleta controlável agora (falso durante a puxada ou com motor destruído). */
  enabled: boolean;
  /** Valor atual do pedal (início da rampa). */
  value: number;
  onChange: (pct: number) => void;
  raf?: (cb: FrameRequestCallback) => number;
  caf?: (id: number) => void;
  now?: () => number;
}

const isSpace = (e: KeyboardEvent) => e.code === "Space" || e.key === " ";

export function useHoldThrottle(options: HoldThrottleOptions): { holding: boolean } {
  const [holding, setHolding] = useState(false);
  const opts = useRef(options);
  useEffect(() => {
    opts.current = options;
  });

  const ramp = useRef<{ start: number; t0: number; last: number; frame: number | null } | null>(null);
  const stop = useRef<(release: boolean) => void>(() => undefined);

  useEffect(() => {
    if (!options.listen) return;
    const raf = options.raf ?? ((cb: FrameRequestCallback) => requestAnimationFrame(cb));
    const caf = options.caf ?? ((id: number) => cancelAnimationFrame(id));
    const now = options.now ?? (() => performance.now());

    const tick = () => {
      const r = ramp.current;
      if (!r) return;
      r.frame = null;
      const pct = holdTarget(r.start, now() - r.t0);
      if (pct !== r.last) {
        r.last = pct;
        opts.current.onChange(pct);
      }
      if (pct < 100) r.frame = raf(tick);
    };

    stop.current = (release) => {
      const r = ramp.current;
      if (!r) return;
      if (r.frame !== null) caf(r.frame);
      ramp.current = null;
      setHolding(false);
      if (release) opts.current.onChange(0);
    };

    const onDown = (e: KeyboardEvent) => {
      if (!isSpace(e) || !isPlainShortcut(e)) return;
      e.preventDefault();
      if (e.repeat || ramp.current || !opts.current.enabled) return;
      const start = Math.round(opts.current.value);
      ramp.current = { start, t0: now(), last: start, frame: null };
      setHolding(true);
      ramp.current.frame = raf(tick);
    };
    const onUp = (e: KeyboardEvent) => {
      if (!isSpace(e)) return;
      if (ramp.current) {
        e.preventDefault();
        stop.current(true);
      } else if (isPlainShortcut(e)) {
        e.preventDefault();
      }
    };
    const onBlur = () => stop.current(true);

    window.addEventListener("keydown", onDown);
    window.addEventListener("keyup", onUp);
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("keydown", onDown);
      window.removeEventListener("keyup", onUp);
      window.removeEventListener("blur", onBlur);
      stop.current(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- relógio e rAF injetáveis só para testes
  }, [options.listen]);

  useEffect(() => {
    if (!options.enabled) stop.current(false);
  }, [options.enabled]);

  return { holding };
}
