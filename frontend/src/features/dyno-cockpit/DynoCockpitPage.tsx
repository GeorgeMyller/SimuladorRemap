/**
 * Página da bancada `/sessions/:sessionId/dyno` (RF-01): carrega a sessão, liga a telemetria,
 * subscreve por painel visível e compõe os painéis (§8 "Layout"). Atalhos de teclado (RF-22): as setas
 * nunca rolam a página (borboleta em `RunControls`). Layout responsivo: coluna única abaixo de `lg`
 * (instrumentos, carro no rolo, gráficos, controles da puxada e abas), duas colunas a partir de `lg`.
 * Feature 002 (RF-05, T045): "Tela Dividida (Live Tuning)" (tecla `L`) troca o layout para carro no
 * rolo + instrumentos + controles de um lado e o `LiveTuningPanel` do outro.
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { setActiveSessionId } from "@/app/activeSession";
import type { WorkspaceDeps } from "@/features/ecu-tuning/workspaceStore";
import { AttemptProgressPanel } from "@/features/scenarios/AttemptProgressPanel";

import { convertPower, formatNumber, POWER_LABEL, UnitsProvider } from "@/lib/units";

import { AudioControls } from "./AudioControls";
import { CarOnRollerView } from "./CarOnRollerView";
import { AlarmRegion, ConnectionIndicator } from "./ConnectionIndicator";
import { CylinderPressureTrace } from "./CylinderPressureTrace";
import { DataloggerPanel } from "./DataloggerPanel";
import { DiagnosticsPanel } from "./DiagnosticsPanel";
import { DynoChart } from "./DynoChart";
import { EngineAutopsyView } from "./EngineAutopsyView";
import { EventTimeline } from "./EventTimeline";
import { GaugeCluster } from "./GaugeCluster";
import { KnockSpectrogram } from "./KnockSpectrogram";
import { LambdaEgtChart } from "./LambdaEgtChart";
import { LiveTuningPanel } from "./live-tuning/LiveTuningPanel";
import { LIVE_TUNING_CHANNELS } from "./live-tuning/liveCell";
import { failureAlarmText, MSG } from "./messages";
import { BOTTOM_STRIP, BOTTOM_TABS, type BottomTab } from "./prefs";
import { RunControls } from "./RunControls";
import { ShortcutsDialog } from "./ShortcutsDialog";
import { UnitsMenu } from "./UnitsMenu";
import { useCockpit, type CockpitDeps } from "./useCockpit";

const TAB_LABEL: Record<BottomTab, string> = {
  spectrogram: "Espectrograma",
  pressure: "Pressão no cilindro",
  events: "Eventos",
  datalogger: "Datalogger",
};

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}

/** Teclas dentro do editor do Live Tuning pertencem ao editor (setas, Esc, letras de operação). */
function insideLiveTuning(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest("[data-live-tuning]") !== null;
}

const SPLIT_LABEL = "Tela Dividida (Live Tuning)";

function PanelFrame({ id, title, expanded, onToggle, children }: { id: string; title: string; expanded: boolean; onToggle: () => void; children: ReactNode }) {
  return (
    <section aria-labelledby={`panel-${id}-title`} className="rounded border border-zinc-700 bg-zinc-900/60 p-2">
      <div className="mb-1 flex items-center justify-between">
        <h2 id={`panel-${id}-title`} className="text-xs font-semibold uppercase tracking-wide text-zinc-300">
          {title}
        </h2>
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={`panel-${id}`}
          aria-label={`${expanded ? "Recolher" : "Expandir"} ${title}`}
          onClick={onToggle}
          className="rounded px-1.5 text-xs text-zinc-300 hover:bg-zinc-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-400"
        >
          {expanded ? "Recolher" : "Expandir"}
        </button>
      </div>
      <div id={`panel-${id}`} hidden={!expanded}>
        {expanded ? children : null}
      </div>
    </section>
  );
}

/** Puxada a abrir ao entrar (`?run=<run_id>&t=<t_sim_s>` gerado pelo EvidenceLink dos cenários). */
export interface RunFocus {
  runId: string;
  t: number | null;
}

export function parseRunFocus(params: URLSearchParams): RunFocus | null {
  const runId = params.get("run");
  if (!runId) return null;
  const raw = params.get("t");
  const t = raw === null || raw.trim() === "" ? NaN : Number(raw);
  return { runId, t: Number.isFinite(t) ? t : null };
}

export interface DynoCockpitViewProps {
  sessionId: string;
  deps?: CockpitDeps;
  focus?: RunFocus | null;
  /** Dependências do editor do Live Tuning (testes injetam a API falsa da ECU). */
  liveTuningDeps?: Partial<WorkspaceDeps>;
}

export function DynoCockpitView({ sessionId, deps, focus = null, liveTuningDeps }: DynoCockpitViewProps) {
  const [split, setSplit] = useState(false);
  const c = useCockpit(sessionId, deps, { extraChannels: split ? LIVE_TUNING_CHANNELS : undefined });
  const { prefs, state, loaded, actions } = c;
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [unitsOpen, setUnitsOpen] = useState(false);
  const [diagOpen, setDiagOpen] = useState(false);

  // Abre a puxada da evidência uma vez por (sessão, run, t), depois de a sessão carregar.
  const focusKey = focus && loaded ? `${loaded.session.session_id}|${focus.runId}|${focus.t ?? ""}` : null;
  const appliedFocus = useRef<string | null>(null);
  const { focusRun } = c;
  const { setTab } = actions;
  useEffect(() => {
    if (!focus || !focusKey || appliedFocus.current === focusKey) return;
    appliedFocus.current = focusKey;
    void focusRun(focus.runId, focus.t);
    if (focus.t !== null) setTab("datalogger");
  }, [focus, focusKey, focusRun, setTab]);

  const vehicle = loaded?.vehicle;
  const limits = vehicle?.mechanical_limits;
  const rpmRange = useMemo<[number, number]>(() => [vehicle?.idle_rpm ?? 800, limits?.max_rpm ?? 7000], [vehicle?.idle_rpm, limits?.max_rpm]);
  const peakRef = useMemo(() => {
    const pts = loaded?.reference?.points ?? [];
    const p = Math.max(0, ...pts.map((x) => x.power_wheel_kw ?? 0));
    const t = Math.max(0, ...pts.map((x) => x.torque_crank_nm ?? 0));
    return {
      power_kw: p > 0 ? p : (vehicle?.rated?.peak_power_whp ?? 270) * 0.7457,
      torque_nm: t > 0 ? t : (vehicle?.rated?.peak_torque_nm ?? 400),
    };
  }, [loaded?.reference, vehicle?.rated]);
  const gaugeLimits = useMemo(
    () => ({
      maxRpm: limits?.max_rpm ?? 7000,
      revLimitRpm: limits?.rev_limit_rpm ?? 6800,
      egtMaxC: limits?.egt_max_c ?? 950,
      boostMaxBar: vehicle?.induction === "turbo" ? 2.0 : vehicle?.induction === "supercharger" ? 1.0 : 0.3,
      turbo: vehicle?.induction === "turbo",
    }),
    [limits, vehicle?.induction],
  );

  const dialogOpen = shortcutsOpen || c.autopsyRunId !== null;

  // Atalhos globais (RF-22). `Esc` com diálogo aberto é tratado pelo próprio diálogo.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || insideLiveTuning(e.target)) return;
      if (e.key === "Escape") {
        if (!dialogOpen && !unitsOpen && state.kind === "running") {
          e.preventDefault();
          void actions.abortRun();
        }
        return;
      }
      if (dialogOpen || isTyping(e.target)) return;
      const key = e.key;
      if (key === "?") {
        e.preventDefault();
        setShortcutsOpen(true);
      } else if (key === "m" || key === "M") {
        e.preventDefault();
        actions.toggleMute();
      } else if (key === "u" || key === "U") {
        e.preventDefault();
        setUnitsOpen((o) => !o);
      } else if (key === "d" || key === "D") {
        e.preventDefault();
        setDiagOpen((o) => !o);
      } else if (key === "l" || key === "L") {
        e.preventDefault();
        setSplit((o) => !o);
      } else if (key >= "1" && key <= "4") {
        e.preventDefault();
        actions.setTab(BOTTOM_TABS[Number(key) - 1]!);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [actions, dialogOpen, unitsOpen, state.kind]);

  useEffect(() => {
    if (state.kind === "error" && state.code === "SESSION_NOT_FOUND") {
      setActiveSessionId(null);
    }
  }, [state]);

  if (state.kind === "error") {
    return (
      <section aria-labelledby="dyno-cockpit-title" className="py-12 text-center">
        <h1 id="dyno-cockpit-title" className="text-xl font-semibold">
          {MSG.title}
        </h1>
        <div role="alert" className="mx-auto mt-4 max-w-lg rounded border border-red-500 p-4">
          <p className="text-lg font-semibold">{state.title}</p>
          {state.detail && <p className="mt-1 text-sm text-zinc-200">{state.detail}</p>}
          <p className="mt-1 font-mono text-xs text-zinc-400">{state.code}</p>
          <div className="mt-3 flex justify-center gap-2">
            <Link
              to="/"
              onClick={() => setActiveSessionId(null)}
              className="rounded border border-zinc-500 px-3 py-1.5 hover:bg-zinc-800"
            >
              {MSG.back}
            </Link>
            <button type="button" onClick={actions.retryLoad} className="rounded bg-amber-500 px-3 py-1.5 font-semibold text-zinc-950 hover:bg-amber-400">
              {MSG.retry}
            </button>
          </div>
        </div>
      </section>
    );
  }

  if (state.kind === "loading" || !loaded || !vehicle || !limits) {
    return (
      <section aria-labelledby="dyno-cockpit-title" aria-busy="true" className="py-12 text-center">
        <h1 id="dyno-cockpit-title" className="text-xl font-semibold">
          {MSG.title}
        </h1>
        <div role="status" className="mt-4 flex items-center justify-center gap-2 text-zinc-300">
          <span aria-hidden="true" className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-zinc-500 border-t-amber-400" />
          {MSG.connecting}
        </div>
        <div aria-hidden="true" className="mx-auto mt-6 grid max-w-5xl grid-cols-1 gap-3 lg:grid-cols-5">
          <div className="h-48 rounded bg-zinc-800 lg:col-span-3" />
          <div className="h-48 rounded bg-zinc-800 lg:col-span-2" />
        </div>
      </section>
    );
  }

  const destroyed = state.kind === "destroyed";
  const wsReady = c.stats.state === "open";
  const disabledReason = c.backendDown ? MSG.backendDown : c.stats.state === "connecting" ? MSG.connecting : null;
  const visible = (id: string) => prefs.visiblePanels.includes(id);
  const bottomExpanded = visible(BOTTOM_STRIP);
  const finalCurve = c.finalRun?.curve ?? null;
  const showEmpty = state.kind === "empty" && !finalCurve;
  const lastRunId = "runId" in state ? state.runId : null;

  const attemptId = loaded.session.attempt_id ?? null;

  const carPanel = (
    <PanelFrame id="car" title="Bancada" expanded={visible("car")} onToggle={() => actions.togglePanel("car")}>
      <CarOnRollerView store={c.store} loop={c.loop} maxRpm={limits.max_rpm} vehicleId={vehicle.vehicle_id} failureSeq={c.failureSeq} degraded={c.degraded} />
    </PanelFrame>
  );
  const gaugesPanel = (
    <PanelFrame id="gauges" title="Instrumentos" expanded={visible("gauges")} onToggle={() => actions.togglePanel("gauges")}>
      <GaugeCluster values={c.gauges} limits={gaugeLimits} boostUnit={prefs.units.boost} frozen={destroyed} missingChannels={wsReady ? c.missing : []} />
    </PanelFrame>
  );
  const runControls = (
    <RunControls
      state={state}
      disabledReason={disabledReason}
      defaultEndRpm={(limits.rev_limit_rpm ?? 7000) - 200}
      onStart={(req) => void actions.startRun(req)}
      onAbort={() => void actions.abortRun()}
      onThrottle={actions.sendThrottle}
      error={c.runError}
      arrowKeys={!dialogOpen && !unitsOpen}
    />
  );

  return (
    <UnitsProvider value={prefs.units} onChange={actions.setUnits}>
      <div className={attemptId ? "flex flex-col gap-3 lg:flex-row lg:items-start" : undefined}>
      <section aria-labelledby="dyno-cockpit-title" className="flex min-w-0 flex-1 flex-col gap-3">
        <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-zinc-800 pb-2 sm:gap-x-6">
          <h1 id="dyno-cockpit-title" className="text-lg font-semibold">
            {MSG.title}
          </h1>
          <dl className="flex flex-wrap gap-x-4 text-sm">
            <div className="flex gap-1">
              <dt className="text-zinc-400">Veículo</dt>
              <dd data-testid="vehicle-name">{vehicle.display_name}</dd>
            </div>
            <div className="flex gap-1">
              <dt className="text-zinc-400">ECU</dt>
              <dd data-testid="profile-name">{loaded.profileName}</dd>
            </div>
            <div className="flex gap-1">
              <dt className="text-zinc-400">Combustível</dt>
              <dd>{loaded.session.fuel_id ?? vehicle.stock_fuel_id ?? "–"}</dd>
            </div>
          </dl>
          <ConnectionIndicator stats={c.stats} onRetry={actions.retrySocket} />
          <UnitsMenu open={unitsOpen} onOpenChange={setUnitsOpen} />
          <AudioControls
            state={c.audioState}
            muted={prefs.audio.muted}
            volume={prefs.audio.volume}
            onEnable={() => void actions.enableAudio()}
            onToggleMute={actions.toggleMute}
            onVolume={actions.setVolume}
          />
          <button
            type="button"
            aria-pressed={split}
            aria-keyshortcuts="L"
            onClick={() => setSplit((o) => !o)}
            className={`border px-2 py-0.5 text-sm transition-transform active:scale-[0.97] focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-400 motion-reduce:transition-none ${split ? "border-lime-400 bg-lime-400 font-semibold text-zinc-950" : "border-zinc-500 hover:border-lime-400 hover:bg-zinc-800"}`}
          >
            {SPLIT_LABEL}
          </button>
          <button type="button" onClick={() => setShortcutsOpen(true)} aria-keyshortcuts="?" className="hidden sm:inline-block rounded border border-zinc-500 px-2 py-0.5 text-sm hover:bg-zinc-800">
            Atalhos (?)
          </button>
        </header>

        {c.backendDown && (
          <div role="alert" className="rounded bg-red-800 px-3 py-1 text-sm font-semibold text-white">
            {MSG.backendDown} — nova tentativa a cada 5 s.
          </div>
        )}
        {c.stats.state === "failed" && (
          <div role="alert" className="flex items-center gap-3 rounded border border-red-500 px-3 py-1 text-sm">
            <span className="font-semibold">{MSG.telemetryUnavailable}</span>
            <button type="button" onClick={actions.retrySocket} className="rounded bg-amber-500 px-2 py-0.5 text-xs font-semibold text-zinc-950">
              {MSG.retry}
            </button>
          </div>
        )}
        <AlarmRegion alarms={c.alarms} />
        {diagOpen && <DiagnosticsPanel fps={c.fps} surface={c.surface} stats={c.stats} degraded={c.degraded} />}
        {showEmpty && <p className="text-sm text-zinc-300">{MSG.empty}</p>}
        {state.kind === "completed" && c.finalRun?.summary && (
          <p role="status" className="text-sm text-emerald-300">
            Puxada concluída: pico {formatNumber(convertPower(c.finalRun.summary.peak_whp * 0.7457, prefs.units.power), 1)} {prefs.units.power} a{" "}
            {formatNumber(c.finalRun.summary.peak_whp_rpm, 0)} rpm · {formatNumber(c.finalRun.summary.peak_torque_engine_nm, 1)} N·m a{" "}
            {formatNumber(c.finalRun.summary.peak_torque_rpm, 0)} rpm
          </p>
        )}
        {c.cursorT !== null && (
          <p data-testid="chart-cursor" className="text-xs text-yellow-200">
            Cursor: {formatNumber(c.cursorT, 2)} s{c.cursorRpm !== null ? ` · ${formatNumber(c.cursorRpm, 0)} rpm` : ""}
          </p>
        )}

        <div className="relative">
          {destroyed && (
            <div className="pointer-events-none absolute inset-0 z-10 rounded bg-red-900/40" aria-hidden="true" />
          )}
          {destroyed && (
            <div role="alert" className="relative z-20 mb-2 flex flex-wrap items-center gap-3 rounded bg-red-900 px-3 py-2 text-white">
              <span className="font-semibold">{c.failure ? failureAlarmText(c.failure.mode) : MSG.engineDestroyed}</span>
              {lastRunId && (
                <button type="button" onClick={() => c.setAutopsyRunId(lastRunId)} className="rounded bg-white px-2 py-1 text-sm font-semibold text-red-900">
                  {MSG.viewReport}
                </button>
              )}
              <button type="button" onClick={() => void actions.restoreEngine()} className="rounded border border-white px-2 py-1 text-sm font-semibold">
                {MSG.restoreEngine}
              </button>
            </div>
          )}
          {split ? (
            <div data-testid="split-layout" className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(320px,2fr)_minmax(0,3fr)]">
              <div className="flex min-w-0 flex-col gap-3">
                {carPanel}
                {gaugesPanel}
                {runControls}
              </div>
              <LiveTuningPanel sessionId={sessionId} telemetry={c.store} loop={c.loop} deps={liveTuningDeps} />
            </div>
          ) : (
          <>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-5">
            <div className="order-2 flex min-w-0 flex-col gap-3 lg:order-none lg:col-span-3">
              <PanelFrame id="dyno" title="Dinamômetro" expanded={visible("dyno")} onToggle={() => actions.togglePanel("dyno")}>
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-zinc-800 bg-zinc-950/70 p-2 text-xs">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="flex items-center gap-1 font-semibold text-zinc-300">
                      <span className="text-amber-400">⇄</span> Comparar passagens:
                    </span>
                    <button
                      type="button"
                      onClick={() => c.setComparisonId(null)}
                      className={`rounded px-2.5 py-1 text-xs font-medium transition-all ${
                        !c.comparisonId
                          ? "bg-zinc-700 text-white shadow-sm ring-1 ring-zinc-500"
                          : "bg-zinc-900 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
                      }`}
                    >
                      Sem comparação
                    </button>
                    {c.history.map((h) => {
                      const isSelected = c.comparisonId === h.runId;
                      const isCurrent = c.finalRun?.run_id === h.runId;
                      const peakWhpRaw = h.run?.summary?.peak_whp;
                      const peakWhp = peakWhpRaw != null ? convertPower(peakWhpRaw * 0.7457, prefs.units.power) : null;
                      const powerUnitLabel = POWER_LABEL[prefs.units.power];
                      return (
                        <button
                          key={h.runId}
                          type="button"
                          disabled={isCurrent}
                          title={isCurrent ? "Esta é a puxada atual em exibição" : `Comparar com ${h.label}`}
                          onClick={() => c.setComparisonId(isSelected ? null : h.runId)}
                          className={`flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium transition-all disabled:opacity-40 disabled:cursor-not-allowed ${
                            isSelected
                              ? "bg-sky-600/30 text-sky-200 ring-1 ring-sky-400 shadow-sm"
                              : "bg-zinc-900 text-zinc-300 hover:bg-zinc-800 hover:text-white"
                          }`}
                        >
                          <span
                            className={`inline-block h-1.5 w-1.5 rounded-full ${
                              isSelected ? "bg-sky-400 shadow-[0_0_6px_rgba(56,189,248,1)]" : "bg-zinc-500"
                            }`}
                          />
                          <span>{h.label}</span>
                          {peakWhp && (
                            <span className="rounded bg-black/40 px-1 font-mono text-[10px] text-zinc-400">
                              {formatNumber(peakWhp, 0)} {powerUnitLabel}
                            </span>
                          )}
                        </button>
                      );
                    })}
                  </div>

                  <div className="flex items-center gap-2">
                    <label className="flex items-center gap-1.5 text-xs text-zinc-400">
                      <span className="text-[11px]">Selecionar:</span>
                      <select
                        aria-label="Puxada de comparação do gráfico"
                        value={c.comparisonId ?? ""}
                        onChange={(e) => c.setComparisonId(e.target.value || null)}
                        className="rounded border border-zinc-700 bg-zinc-900 px-2 py-0.5 text-xs text-zinc-200 focus:outline-none focus:ring-1 focus:ring-amber-400"
                      >
                        <option value="">— Sem comparação —</option>
                        {c.history.map((h) => (
                          <option key={h.runId} value={h.runId} disabled={h.runId === c.finalRun?.run_id}>
                            {h.label} {h.runId === c.finalRun?.run_id ? "(atual)" : ""}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                </div>
                <DynoChart
                  finalCurve={finalCurve}
                  comparison={c.comparison}
                  reference={loaded.reference}
                  powerUnit={prefs.units.power}
                  rpmRange={rpmRange}
                  peakRef={peakRef}
                  store={c.store}
                  loop={c.loop}
                  cursorRpm={c.cursorRpm}
                />
              </PanelFrame>
              <PanelFrame id="lambda-egt" title="Lambda e EGT" expanded={visible("lambda-egt")} onToggle={() => actions.togglePanel("lambda-egt")}>
                <LambdaEgtChart
                  finalCurve={finalCurve}
                  comparison={c.comparison}
                  reference={loaded.reference}
                  egtLimitC={limits.egt_max_c}
                  rpmRange={rpmRange}
                  store={c.store}
                  loop={c.loop}
                  cursorRpm={c.cursorRpm}
                />
              </PanelFrame>
            </div>
            <div className="order-1 flex min-w-0 flex-col gap-3 lg:order-none lg:col-span-2">
              {carPanel}
              <div className="order-first lg:order-none">{gaugesPanel}</div>
              {runControls}
            </div>
          </div>
          <div className="mt-3">
            <section aria-label="Painéis inferiores" className="min-w-0 rounded border border-zinc-700 bg-zinc-900/60 p-2">
              <div className="mb-2 flex items-start justify-between gap-2">
                <div role="tablist" aria-label="Painéis inferiores" className="flex flex-wrap gap-1">
                  {BOTTOM_TABS.map((tab, i) => (
                    <button
                      key={tab}
                      type="button"
                      role="tab"
                      id={`tab-${tab}`}
                      aria-selected={prefs.activeBottomTab === tab}
                      aria-controls="bottom-panel"
                      aria-keyshortcuts={String(i + 1)}
                      tabIndex={prefs.activeBottomTab === tab ? 0 : -1}
                      onClick={() => actions.setTab(tab)}
                      onKeyDown={(e) => {
                        if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
                          e.preventDefault();
                          const next = (i + (e.key === "ArrowRight" ? 1 : BOTTOM_TABS.length - 1)) % BOTTOM_TABS.length;
                          actions.setTab(BOTTOM_TABS[next]!);
                          document.getElementById(`tab-${BOTTOM_TABS[next]!}`)?.focus();
                        }
                      }}
                      className={`rounded px-2 py-1 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-400 ${prefs.activeBottomTab === tab ? "bg-zinc-700 text-amber-300" : "text-zinc-200 hover:bg-zinc-800"}`}
                    >
                      {i + 1}. {TAB_LABEL[tab]}
                    </button>
                  ))}
                </div>
                <button
                  type="button"
                  aria-expanded={bottomExpanded}
                  aria-controls="bottom-panel"
                  aria-label={`${bottomExpanded ? "Recolher" : "Expandir"} painel inferior`}
                  onClick={() => actions.togglePanel(BOTTOM_STRIP)}
                  className="rounded px-1.5 text-xs text-zinc-300 hover:bg-zinc-800"
                >
                  {bottomExpanded ? "Recolher" : "Expandir"}
                </button>
              </div>
              <div id="bottom-panel" role="tabpanel" aria-labelledby={`tab-${prefs.activeBottomTab}`} hidden={!bottomExpanded}>
                {bottomExpanded && prefs.activeBottomTab === "spectrogram" && (
                  <KnockSpectrogram store={c.store} loop={c.loop} nCyl={vehicle.engine.n_cyl} degraded={c.degraded} onSurfaceChange={c.setSurface} />
                )}
                {bottomExpanded && prefs.activeBottomTab === "pressure" && (
                  <CylinderPressureTrace nCyl={vehicle.engine.n_cyl} cylinder={c.pressureCylinder} onCylinderChange={c.setPressureCylinder} store={c.store} loop={c.loop} />
                )}
                {bottomExpanded && prefs.activeBottomTab === "events" && <EventTimeline events={c.events} selectedId={c.selectedEventId} onSelect={c.selectEvent} />}
                {bottomExpanded && prefs.activeBottomTab === "datalogger" && (
                  <DataloggerPanel runs={c.history} cursorT={c.cursorT} onCursorChange={c.setCursorT} gaps={c.store.gaps} />
                )}
              </div>
            </section>
          </div>
          </>
          )}
        </div>

        {c.autopsyRunId && (
          <EngineAutopsyView
            runId={c.autopsyRunId}
            nCyl={vehicle.engine.n_cyl}
            turbo={vehicle.induction === "turbo"}
            failure={c.failure}
            onClose={() => c.setAutopsyRunId(null)}
            onRestore={actions.restoreEngine}
            loadReport={c.loadReport}
          />
        )}
        {shortcutsOpen && <ShortcutsDialog onClose={() => setShortcutsOpen(false)} />}
      </section>
      {attemptId && (
        <div data-testid="attempt-sidebar" className="lg:sticky lg:top-2">
          <AttemptProgressPanel attemptId={attemptId} sidebar refreshKey={state.kind !== "running" && lastRunId ? `${lastRunId}:${state.kind}` : null} />
        </div>
      )}
      </div>
    </UnitsProvider>
  );
}

/** Rota lazy fixa de `app/routes.tsx` (`/sessions/:sessionId/dyno`). */
export default function DynoCockpitPage() {
  const { sessionId } = useParams();
  const [params] = useSearchParams();
  const focus = useMemo(() => parseRunFocus(params), [params]);
  if (!sessionId) return <p role="alert">Sessão não indicada.</p>;
  return <DynoCockpitView sessionId={sessionId} focus={focus} />;
}
