/**
 * Controlador da cockpit (RF-01..RF-21): carrega sessão/veículo/curvas, liga o WebSocket,
 * alimenta o store (só escrita no `onmessage`, RNF-04), gere a máquina de estados, os alarmes,
 * o áudio, a subscrição por painel (debounce 250 ms) e as ações REST (puxada, abort, restore).
 */
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import { isApiProblem } from "@/lib/api";
import type { UnitsPrefs } from "@/lib/units";
import { telemetryUrl, TelemetrySocket, type FailureEventPayload, type StreamStats, type TypedEnvelope, type WebSocketFactory } from "@/lib/ws";

import { cockpitApi, fetchForensicReportWithRetry, type CockpitApi, type DynoRun, type DynoRunRequest, type ReferenceCurve, type Session, type Vehicle } from "./api";
import { AudioEngine, type AudioContextFactory, type AudioState } from "./audio/AudioEngine";
import { engineProfileFor } from "./audio/engineProfile";
import { buildSubscription, subscriptionKey } from "./channels";
import { ACTIVE_RUN_STATES, cockpitReducer, type CockpitState } from "./cockpitState";
import type { Alarm } from "./ConnectionIndicator";
import type { RunHistoryItem } from "./DataloggerPanel";
import { FlashLimiter } from "./flashGuard";
import type { GaugeValues } from "./GaugeCluster";
import { egtAlarmText, failureAlarmText, knockAlarmText, limiterAlarmText, MSG, RUN_TYPE_LABEL } from "./messages";
import { loadPrefs, savePrefs, visibleForSubscription, type BottomTab, type CockpitPrefs } from "./prefs";
import { RenderLoop } from "./render/RenderLoop";
import type { SurfaceKind } from "./render/createSurface";
import { TelemetryStore, type TimelineEvent } from "./store";
import { useThermalView } from "./thermalView";

const HEALTH_RETRY_MS = 5000;
const FINISH_RUN_RETRIES = 20;
const FINISH_RUN_RETRY_MS = 150;

export interface CockpitDeps {
  api?: CockpitApi;
  /** Fábrica do WebSocket bruto (testes); padrão: `new WebSocket(url)`. */
  createWebSocket?: WebSocketFactory;
  createAudioContext?: AudioContextFactory | null;
  storage?: Storage | null;
  wsOrigin?: string;
}

export interface LoadedData {
  session: Session;
  vehicle: Vehicle;
  reference: ReferenceCurve | null;
  profileName: string;
}

export interface HistoryEntry extends RunHistoryItem {
  run: DynoRun | null;
}

const INITIAL_STATS: StreamStats = {
  lastSeq: -1,
  lastFrameIndex: -1,
  received: 0,
  lost: 0,
  lossRate5s: 0,
  invalidEnvelopes: 0,
  duplicates: 0,
  reconnectAttempt: 0,
  maxAttempts: 10,
  state: "connecting",
  closeCode: null,
  closeReason: null,
};

function problemMessage(error: unknown): { code: string; title: string; detail: string } {
  if (isApiProblem(error)) return { code: error.code, title: error.title, detail: error.detail };
  return { code: "UNEXPECTED_ERROR", title: "Erro inesperado", detail: error instanceof Error ? error.message : String(error) };
}

export interface CockpitOptions {
  /** Canais extra na subscrição (ex.: Live Tuning). */
  extraChannels?: readonly string[];
}

export function useCockpit(sessionId: string, deps: CockpitDeps = {}, options: CockpitOptions = {}) {
  const api = deps.api ?? cockpitApi;
  const [prefs, setPrefsState] = useState<CockpitPrefs>(() => loadPrefs(deps.storage));
  const setPrefs = useCallback(
    (update: (p: CockpitPrefs) => CockpitPrefs) => {
      setPrefsState((prev) => {
        const next = update(prev);
        savePrefs(next, deps.storage);
        return next;
      });
    },
    [deps.storage],
  );

  const [state, dispatch] = useReducer(cockpitReducer, { kind: "loading" } as CockpitState);
  const [loaded, setLoaded] = useState<LoadedData | null>(null);
  const [stats, setStats] = useState<StreamStats>(INITIAL_STATS);
  const [store] = useState(() => new TelemetryStore());
  const [loop] = useState(() => new RenderLoop());
  const [gauges, setGauges] = useState<GaugeValues>({});
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [alarms, setAlarms] = useState<Alarm[]>([]);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [finalRun, setFinalRun] = useState<DynoRun | null>(null);
  const [comparisonId, setComparisonId] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [backendDown, setBackendDown] = useState(false);
  const [failure, setFailure] = useState<FailureEventPayload | null>(null);
  const [failureSeq, setFailureSeq] = useState<number | null>(null);
  const [autopsyRunId, setAutopsyRunId] = useState<string | null>(null);
  const [audioState, setAudioState] = useState<AudioState>("unavailable");
  const [fps, setFps] = useState(0);
  const [degraded, setDegraded] = useState(false);
  const [surface, setSurface] = useState<SurfaceKind>("none");
  const [cursorT, setCursorT] = useState<number | null>(null);
  const [selectedEventId, setSelectedEventId] = useState<number | null>(null);
  const [pressureCylinder, setPressureCylinder] = useState(1);
  const [missing, setMissing] = useState<string[]>([]);
  const [loadAttempt, setLoadAttempt] = useState(0);

  const socketRef = useRef<TelemetrySocket | null>(null);
  const audioRef = useRef<AudioEngine | null>(null);
  const stateRef = useRef(state);
  const loadedRef = useRef(loaded);
  const prefsRef = useRef(prefs);
  useEffect(() => {
    stateRef.current = state;
    loadedRef.current = loaded;
    prefsRef.current = prefs;
  });

  // ---- Alarmes (RF-21): região aria-live + banner, ≤ 3 atualizações/s (sem flash > 3 Hz).
  const alarmLimiter = useRef(new FlashLimiter(3));
  const pendingAlarm = useRef<Alarm | null>(null);
  const alarmSeq = useRef(0);
  const pushAlarm = useCallback((text: string, severity: Alarm["severity"]) => {
    alarmSeq.current += 1;
    const alarm: Alarm = { id: alarmSeq.current, text, severity };
    if (alarmLimiter.current.tryFlash(performance.now())) {
      setAlarms((prev) => [...prev.slice(-19), alarm]);
    } else {
      pendingAlarm.current = alarm;
    }
  }, []);

  // ---- Carregamento da sessão, do veículo, das curvas e do perfil (RF-01).
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const session = await api.getSession(sessionId);
        const vehicle = await api.getVehicle(session.vehicle_id);
        const [refs, profile, baseline] = await Promise.all([
          api.getReferenceCurves(session.vehicle_id).catch(() => null),
          api.getProfile(session.profile_id).catch(() => null),
          session.baseline_run_id ? api.getRun(session.baseline_run_id).catch(() => null) : Promise.resolve(null),
        ]);
        if (cancelled) return;
        const fuel = session.fuel_id ?? vehicle.stock_fuel_id;
        const reference = refs?.items.find((c) => c.fuel_id === fuel) ?? refs?.items[0] ?? null;
        setLoaded({ session, vehicle, reference, profileName: profile?.name ?? session.profile_id });
        if (baseline) {
          setHistory([{ runId: baseline.run_id, label: "Puxada base", state: baseline.state, run: baseline }]);
          setComparisonId(baseline.run_id);
        }
        dispatch({
          type: "loaded",
          hasRuns: Boolean(baseline),
          engineLocked: session.engine_locked || session.state === "engine_locked",
          activeRunId: session.active_run_id ?? null,
          lastRunId: session.active_run_id ?? session.baseline_run_id ?? null,
        });
      } catch (error) {
        if (cancelled) return;
        const p = problemMessage(error);
        dispatch({ type: "loadFailed", code: p.code, title: p.title, detail: p.detail });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [api, sessionId, loadAttempt]);

  // ---- Health (EC-15): banner e retry a cada 5 s.
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const check = async () => {
      let ok: boolean;
      try {
        const h = await api.getHealth();
        ok = h.status !== "down";
      } catch {
        ok = false;
      }
      if (cancelled) return;
      setBackendDown(!ok);
      if (!ok) timer = setTimeout(() => void check(), HEALTH_RETRY_MS);
    };
    void check();
    return () => {
      cancelled = true;
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [api]);

  // ---- Puxada concluída/abortada: curva final do DynoRun (fonte da verdade) e histórico.
  const finishRun = useCallback(
    async (runId: string, terminal: string) => {
      let run: DynoRun | null = null;
      // O `run.state` terminal do WS chega antes de o DynoRun do REST ser finalizado (o resultado
      // da puxada é processado logo a seguir): enquanto o REST ainda devolver uma fase ativa,
      // sem resumo nem curva, repete a leitura (E2E T221: a curva final e o resumo nunca apareciam).
      for (let attempt = 0; attempt < FINISH_RUN_RETRIES; attempt++) {
        try {
          run = await api.getRun(runId);
        } catch {
          run = null;
        }
        if (!run || !ACTIVE_RUN_STATES.has(run.state)) break;
        await new Promise((resolve) => setTimeout(resolve, FINISH_RUN_RETRY_MS));
      }
      if (terminal === "completed" && run) setFinalRun(run);
      setHistory((prev) => {
        if (prev.some((h) => h.runId === runId)) return prev.map((h) => (h.runId === runId ? { ...h, state: run?.state ?? terminal, run } : h));
        const n = prev.length + 1;
        const label = `#${n} ${RUN_TYPE_LABEL[(run?.run_type ?? "sweep_pull") as keyof typeof RUN_TYPE_LABEL] ?? run?.run_type ?? ""}${terminal !== "completed" ? ` (${terminal === "aborted" ? MSG.partial : terminal})` : ""}`;
        return [...prev, { runId, label, state: run?.state ?? terminal, run }];
      });
    },
    [api],
  );

  // ---- Evidência de cenário (`?run=<run_id>&t=<t_sim_s>`, training-scenarios RF-12/RF-24):
  // carrega a puxada no histórico, seleciona-a como comparação e posiciona o cursor do log.
  const focusRun = useCallback(
    async (runId: string, t: number | null) => {
      let run: DynoRun | null = null;
      try {
        run = await api.getRun(runId);
      } catch {
        run = null;
      }
      setHistory((prev) =>
        prev.some((h) => h.runId === runId)
          ? prev
          : [...prev, { runId, label: `${MSG.evidenceRun} ${runId.slice(-6)}`, state: run?.state ?? "unknown", run }],
      );
      setComparisonId(runId);
      if (t !== null) setCursorT(t);
    },
    [api],
  );

  const openAutopsy = useCallback((runId: string | null) => {
    if (runId) setAutopsyRunId(runId);
  }, []);

  // ---- Envelopes não-frame (eventos raros): estado, alarmes, áudio, animação.
  const handleEnvelope = useCallback(
    (env: TypedEnvelope) => {
      switch (env.type) {
        case "run.state": {
          dispatch({ type: "runState", payload: env.payload });
          const p = env.payload;
          if (p.run_id && (p.state === "completed" || p.state === "aborted")) void finishRun(p.run_id, p.state);
          if (p.state === "engine_failed") {
            openAutopsy(p.run_id);
            if (p.run_id) void finishRun(p.run_id, "engine_failed");
          }
          break;
        }
        case "event.knock":
          if (env.payload.knock_class === "severe") {
            pushAlarm(knockAlarmText("severe", env.payload.cylinder, env.payload.retard_deg), "critical");
          }
          break;
        case "event.limiter":
          if (env.payload.active) pushAlarm(limiterAlarmText(env.payload.kind, true, env.payload.rpm), "warning");
          break;
        case "event.failure": {
          const p = env.payload;
          if (p.catastrophic) {
            setFailure(p);
            setFailureSeq(env.seq);
            dispatch({ type: "failure", runId: p.run_id, catastrophic: true });
            audioRef.current?.breakage();
            pushAlarm(failureAlarmText(p.mode), "critical");
            openAutopsy(p.run_id ?? (stateRef.current.kind === "running" ? stateRef.current.runId : null));
          } else {
            pushAlarm(`Dano: ${p.mode} em ${p.component_id}`, "warning");
          }
          break;
        }
        case "error":
          if (env.payload.code === "THROTTLE_LOCKED_BY_RUN" || env.payload.fatal) setRunError(`${env.payload.title} (${env.payload.code})`);
          break;
        case "telemetry.frame":
          break;
      }
    },
    [finishRun, openAutopsy, pushAlarm],
  );

  // ---- WebSocket (RF-02, RF-05).
  const sessionLoaded = loaded !== null;
  useEffect(() => {
    if (!sessionLoaded) return;
    let lastState: StreamStats["state"] | null = null;
    let lastEmit = -Infinity;
    let lastLossy = false;
    let pendingStats: StreamStats | null = null;
    let flushTimer: ReturnType<typeof setTimeout> | undefined;
    const options = {
      url: telemetryUrl(sessionId, deps.wsOrigin),
      debug: import.meta.env.DEV,
      onEnvelope: (env: TypedEnvelope) => {
        store.ingest(env);
        if (env.type !== "telemetry.frame") handleEnvelope(env);
      },
      onStats: (s: StreamStats) => {
        // Re-render no máximo a 4 Hz, exceto em mudança de estado ou do indicador de perda.
        const now = performance.now();
        const lossy = s.lossRate5s > 0.02;
        if (s.state !== lastState && s.state === "reconnecting") store.markGapStart();
        if (s.state !== lastState || lossy !== lastLossy || now - lastEmit > 250) {
          lastState = s.state;
          lastLossy = lossy;
          lastEmit = now;
          if (flushTimer !== undefined) clearTimeout(flushTimer);
          flushTimer = undefined;
          setStats(s);
        } else {
          pendingStats = s;
          flushTimer ??= setTimeout(() => {
            flushTimer = undefined;
            lastEmit = performance.now();
            if (pendingStats) setStats(pendingStats);
            pendingStats = null;
          }, 250);
        }
      },
      onReconnected: () => {
        store.markGapEnd();
        const st = stateRef.current;
        if (st.kind === "running") {
          void api.getRun(st.runId).then(
            (run) => {
              if (run.state === "completed" || run.state === "aborted") void finishRun(run.run_id, run.state);
              dispatch({ type: "runState", payload: { run_id: run.run_id, state: run.state as never, abort_reason: run.abort_reason ?? null } });
            },
            () => undefined,
          );
        }
      },
    };
    const socket = new TelemetrySocket(deps.createWebSocket ? { ...options, createSocket: deps.createWebSocket } : options);
    socketRef.current = socket;
    socket.connect();
    return () => {
      if (flushTimer !== undefined) clearTimeout(flushTimer);
      socket.close();
      socketRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- o socket vive enquanto a sessão estiver carregada
  }, [sessionLoaded, sessionId]);

  // ---- Subscrição por painel visível com debounce de 250 ms (RF-02).
  const nCyl = loaded?.vehicle.engine.n_cyl ?? 4;
  const audioActive = audioState === "running" && !prefs.audio.muted;
  const thermalView = useThermalView();
  const extraKey = (options.extraChannels ?? []).join(",");
  // eslint-disable-next-line react-hooks/exhaustive-deps -- estabiliza pela chave, não pela identidade do array
  const extraChannels = useMemo(() => options.extraChannels ?? [], [extraKey]);
  const subscription = useMemo(
    () =>
      buildSubscription({
        visiblePanels: visibleForSubscription(prefs),
        nCyl,
        audioActive,
        pressureCylinder,
        thermalView,
        extraChannels,
      }),
    [prefs, nCyl, audioActive, pressureCylinder, thermalView, extraChannels],
  );
  const subKey = subscriptionKey(subscription);
  const subRef = useRef(subscription);
  useEffect(() => {
    subRef.current = subscription;
  });
  const firstSub = useRef(true);
  useEffect(() => {
    const socket = socketRef.current;
    if (!socket) return;
    if (firstSub.current) {
      firstSub.current = false;
      socket.subscribe(subRef.current);
      return;
    }
    const timer = setTimeout(() => socketRef.current?.subscribe(subRef.current), 250);
    return () => clearTimeout(timer);
  }, [subKey, sessionLoaded]);

  // ---- Áudio (RF-18, RF-19).
  useEffect(() => {
    if (!loaded) return;
    const engine = new AudioEngine(engineProfileFor(loaded.vehicle), {
      createContext: deps.createAudioContext,
      muted: prefsRef.current.audio.muted,
      volume: prefsRef.current.audio.volume,
    });
    audioRef.current = engine;
    queueMicrotask(() => setAudioState(engine.state));
    return () => {
      engine.dispose();
      audioRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- recria só ao trocar de veículo
  }, [loaded?.vehicle.vehicle_id]);

  useEffect(() => {
    audioRef.current?.setMuted(prefs.audio.muted);
    audioRef.current?.setVolume(prefs.audio.volume);
  }, [prefs.audio.muted, prefs.audio.volume]);

  const enableAudio = useCallback(async () => {
    const engine = audioRef.current;
    if (!engine) return;
    const st = await engine.enable();
    setAudioState(st);
    setPrefs((p) => ({ ...p, audio: { ...p.audio, enabled: true } }));
  }, [setPrefs]);

  // EC-10: separador oculto suspende o áudio; ao voltar, retoma sem repetir eventos perdidos.
  useEffect(() => {
    const onVis = () => {
      const engine = audioRef.current;
      if (!engine) return;
      if (document.visibilityState === "hidden") void engine.suspend().then(() => setAudioState(engine.state));
      else if (prefsRef.current.audio.enabled && engine.state === "suspended") void engine.enable().then(setAudioState);
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  // ---- RenderLoop: amostras para gauges/eventos/diagnóstico e síntese de áudio.
  useEffect(() => {
    loop.start();
    const offDegraded = loop.onDegradedChange(setDegraded);
    let lastUi = -Infinity;
    let lastSlow = -Infinity;
    let seenVersion = -1;
    let popCursor = store.afterfireTotal;
    let egtAlarmOn = false;
    const off = loop.add((now) => {
      const audio = audioRef.current;
      if (audio && audio.state === "running") {
        audio.update({
          rpm: store.value("rpm") ?? 0,
          turboRpm: store.value("turbo_rpm") ?? null,
          throttlePct: store.value("throttle_pct") ?? 0,
          mapKpa: store.value("map_kpa") ?? 100,
          baroKpa: store.value("baro_kpa") ?? 100,
          nowMs: now,
        });
        const pops = store.afterfireSince(popCursor);
        if (pops.count > 0) audio.pops(pops.count, pops.seq);
        popCursor = pops.total;
      } else {
        popCursor = store.afterfireTotal;
      }
      if (now - lastUi >= 50 && store.version !== seenVersion && stateRef.current.kind !== "destroyed") {
        lastUi = now;
        seenVersion = store.version;
        setGauges({
          rpm: store.value("rpm"),
          map_kpa: store.value("map_kpa"),
          baro_kpa: store.value("baro_kpa"),
          lambda: store.value("lambda"),
          egt_c: store.value("egt_c"),
          iat_c: store.value("iat_c"),
          ect_c: store.value("ect_c"),
          knock_retard_deg: store.value("knock_retard_deg"),
        });
        const egt = store.value("egt_c");
        const limit = loadedRef.current?.vehicle.mechanical_limits.egt_max_c;
        if (egt !== undefined && limit !== undefined) {
          if (!egtAlarmOn && egt > limit) {
            egtAlarmOn = true;
            pushAlarm(egtAlarmText(egt, limit), "critical");
          } else if (egtAlarmOn && egt < limit - 20) {
            egtAlarmOn = false;
          }
        }
      }
      if (now - lastSlow >= 250) {
        lastSlow = now;
        setFps(loop.fps);
        setEvents((prev) => (prev.length === store.events.length && prev.at(-1) === store.events.at(-1) ? prev : [...store.events]));
        setMissing((prev) => {
          const next = store.missingChannels(subRef.current.channels);
          return prev.join() === next.join() ? prev : next;
        });
        const pending = pendingAlarm.current;
        if (pending && alarmLimiter.current.tryFlash(now)) {
          pendingAlarm.current = null;
          setAlarms((prev) => [...prev.slice(-19), pending]);
        }
      }
    });
    return () => {
      off();
      offDegraded();
      loop.stop();
    };
  }, [loop, store, pushAlarm]);

  // ---- Ações.
  const startRun = useCallback(
    async (req: DynoRunRequest) => {
      setRunError(null);
      try {
        const run = await api.startRun(sessionId, req);
        store.resetRun(run.run_id);
        setFinalRun(null);
        setCursorT(null);
        dispatch({ type: "runStarted", runId: run.run_id });
      } catch (error) {
        const p = problemMessage(error);
        if (p.code === "ENGINE_DESTROYED") {
          dispatch({ type: "engineDestroyed", runId: null });
          setRunError(`${MSG.engineDestroyed}. ${MSG.restoreEngine} para continuar.`);
        } else if (p.code === "RUN_IN_PROGRESS" || p.code === "RUN_ALREADY_ACTIVE") {
          setRunError(MSG.runInProgress);
          try {
            const s = await api.getSession(sessionId);
            if (s.active_run_id) dispatch({ type: "runStarted", runId: s.active_run_id });
          } catch {
            /* mantém o estado atual */
          }
        } else {
          setRunError(`${p.title}: ${p.detail} (${p.code})`);
        }
      }
    },
    [api, sessionId, store],
  );

  const abortRun = useCallback(async () => {
    const st = stateRef.current;
    if (st.kind !== "running") return;
    try {
      const run = await api.abortRun(sessionId, st.runId);
      dispatch({ type: "runState", payload: { run_id: run.run_id, state: "aborted", abort_reason: run.abort_reason ?? "user_abort" } });
      void finishRun(run.run_id, "aborted");
    } catch (error) {
      const p = problemMessage(error);
      setRunError(`${p.title}: ${p.detail} (${p.code})`);
    }
  }, [api, sessionId, finishRun]);

  const restoreEngine = useCallback(async () => {
    await api.restoreEngine(sessionId);
    dispatch({ type: "restored" });
    setFailure(null);
    setFailureSeq(null);
    setAutopsyRunId(null);
    setRunError(null);
    audioRef.current?.repair();
  }, [api, sessionId]);

  const sendThrottle = useCallback((pct: number) => {
    socketRef.current?.sendThrottle(pct);
  }, []);

  const loadReport = useCallback((runId: string) => fetchForensicReportWithRetry(runId, api), [api]);

  const retrySocket = useCallback(() => socketRef.current?.retry(), []);
  const retryLoad = useCallback(() => setLoadAttempt((n) => n + 1), []);

  const selectEvent = useCallback((ev: TimelineEvent) => {
    setSelectedEventId(ev.id);
    setCursorT(ev.t_sim_s);
  }, []);

  const setUnits = useCallback((units: UnitsPrefs) => setPrefs((p) => ({ ...p, units })), [setPrefs]);
  const setTab = useCallback((tab: BottomTab) => setPrefs((p) => ({ ...p, activeBottomTab: tab })), [setPrefs]);
  const togglePanel = useCallback(
    (id: string) =>
      setPrefs((p) => ({
        ...p,
        visiblePanels: p.visiblePanels.includes(id) ? p.visiblePanels.filter((x) => x !== id) : [...p.visiblePanels, id],
      })),
    [setPrefs],
  );
  const toggleMute = useCallback(() => setPrefs((p) => ({ ...p, audio: { ...p.audio, muted: !p.audio.muted } })), [setPrefs]);
  const setVolume = useCallback((volume: number) => setPrefs((p) => ({ ...p, audio: { ...p.audio, volume } })), [setPrefs]);

  const comparison = useMemo(() => {
    const entry = history.find((h) => h.runId === comparisonId && h.runId !== finalRun?.run_id);
    return entry?.run && entry.run.curve.length > 0 ? { label: entry.label, curve: entry.run.curve } : null;
  }, [history, comparisonId, finalRun]);

  const cursorRpm = useMemo(() => {
    if (cursorT === null) return null;
    if (finalRun && finalRun.curve.length > 0) {
      let best = finalRun.curve[0]!;
      for (const p of finalRun.curve) if (Math.abs(p.t_sim_s - cursorT) < Math.abs(best.t_sim_s - cursorT)) best = p;
      return best.rpm;
    }
    return store.rpmAt(cursorT) ?? null;
  }, [cursorT, finalRun, store]);

  return {
    prefs,
    state,
    loaded,
    stats,
    store,
    loop,
    gauges,
    events,
    alarms,
    history,
    finalRun,
    comparison,
    comparisonId,
    setComparisonId,
    focusRun,
    runError,
    backendDown,
    failure,
    failureSeq,
    autopsyRunId,
    setAutopsyRunId,
    audioState,
    fps,
    degraded,
    surface,
    setSurface,
    cursorT,
    setCursorT,
    cursorRpm,
    selectedEventId,
    selectEvent,
    pressureCylinder,
    setPressureCylinder,
    missing,
    subscription,
    loadReport,
    actions: { startRun, abortRun, restoreEngine, sendThrottle, retrySocket, retryLoad, enableAudio, toggleMute, setVolume, setUnits, setTab, togglePanel },
  };
}

export type CockpitController = ReturnType<typeof useCockpit>;
