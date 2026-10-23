/**
 * Workspace da ECU (tuning RF-01, §8 "Layout" e "Estados da UI"): carrega a sessão, o
 * `EcuProfileDescriptor` do perfil ativo e a calibração ativa; compõe `ProfileNavigator`, os
 * editores de tabela, `StrategyForms`, `CylinderTrims`, `BaseSetupWizard`, `CalibrationVersions`,
 * `TuningWarnings`, `LiveTuneIndicator`, os seletores de carro e de swap, a barra de estado e os
 * atalhos globais (`?`, `Ctrl/Cmd+S`, `Ctrl/Cmd+Enter`).
 */
import { useEffect, useMemo, useRef, useState, useSyncExternalStore, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";

import { setActiveSessionId } from "@/app/activeSession";
import { formatNumber } from "@/lib/units";

import { BaseSetupWizard } from "./BaseSetupWizard";
import type { BaseStep } from "./baseSetupSchemas";
import { BASE_STEPS } from "./baseSetupSchemas";
import { CalibrationVersions, VersionDiff } from "./CalibrationVersions";
import { CylinderTrims, type TrimKind } from "./CylinderTrims";
import { Dialog } from "../dyno-cockpit/Dialog";
import { ApplyToSessionButton, LiveTuneIndicator } from "./LiveTuneIndicator";
import { MSG } from "./messages";
import { ProfileNavigator } from "./ProfileNavigator";
import { ShortcutsDialog } from "./ShortcutsDialog";
import { StrategyForm, problemToFieldErrors } from "./StrategyForms";
import { isStrategyKind, strategyDefaults } from "./strategySchemas";
import { SwapSelector } from "./SwapSelector";
import { TableEditor2D } from "./TableEditor2D";
import { TableEditor3D } from "./TableEditor3D";
import { isRunActive, type TelemetryFeed } from "./telemetryFeed";
import { TuningWarnings } from "./TuningWarnings";
import type { BaseSetupResult, NavItem, Session } from "./types";
import { usePatchQueue, type SaveState } from "./usePatchQueue";
import { VehicleSelector } from "./VehicleSelector";
import { computeWarnings, mbtAvailable } from "./warnings";
import { StockCalibrationBanner } from "./StockCalibrationBanner";
import { useWorkspaceStore } from "./useWorkspaceStore";
import type { WorkspaceDeps, WorkspaceStore } from "./workspaceStore";

export interface EcuWorkspaceProps {
  sessionId: string;
  deps: WorkspaceDeps;
  /** Abre outra sessão (troca de carro). */
  onOpenSession?: (sessionId: string) => void;
}

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  return el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable;
}

const SAVE_TEXT: Record<SaveState, (v: number) => string> = {
  idle: (v) => MSG.saved(v),
  saved: (v) => MSG.saved(v),
  pending: () => MSG.saving,
  saving: () => MSG.saving,
  failed: () => MSG.notSaved,
  error: () => MSG.notSaved,
  conflict: () => MSG.conflict,
  locked: () => `${MSG.notSaved} (${MSG.lockedDuringRun})`,
};

export function EcuWorkspace({ sessionId, deps, onOpenSession }: EcuWorkspaceProps) {
  const store = useWorkspaceStore(sessionId, deps);
  const snap = useSyncExternalStore(store.subscribe, store.getSnapshot);
  const save = usePatchQueue(store.queue);
  const [showShortcuts, setShowShortcuts] = useState(false);
  const [showVersions, setShowVersions] = useState(false);
  const [versionLabel, setVersionLabel] = useState("");

  useEffect(() => {
    if (snap.load.kind === "error" && snap.load.code === "SESSION_NOT_FOUND") {
      setActiveSessionId(null);
    }
  }, [snap.load]);

  const warnings = useMemo(
    () =>
      computeWarnings({
        tables: Object.values(snap.tables),
        strategies: snap.calibration?.strategies ?? {},
        mbtReference: snap.vehicle?.engine.mbt_reference ?? null,
        maxRpm: snap.vehicle?.mechanical_limits.max_rpm ?? null,
        boostMaxKpa: store.boostMaxKpa(),
      }),
    [snap.tables, snap.calibration?.strategies, snap.vehicle, store],
  );

  const labelOf = useMemo(() => {
    const map = new Map<string, string>();
    for (const s of snap.profile?.navigation ?? []) for (const item of s.items) {
      const id = item.kind === "table" ? store.resolveTableId(item, snap.calibration) : null;
      if (id && !map.has(id)) map.set(id, item.label);
    }
    return (tableId: string) => map.get(tableId) ?? tableId;
  }, [snap.profile, snap.calibration, store]);

  const mainRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (mainRef.current) mainRef.current.scrollTop = 0;
  }, [snap.activeItemId]);

  const autoApply = snap.prefs.autoApply === "on";
  useEffect(() => {
    store.setAutoApply(autoApply);
  }, [store, autoApply]);

  if (snap.load.kind === "loading") {
    return (
      <section aria-busy="true" aria-labelledby="ecu-ws-title" className="p-4">
        <h1 id="ecu-ws-title" className="text-lg font-semibold">
          Workspace da ECU
        </h1>
        <p role="status" className="text-sm text-zinc-300">
          {MSG.loading}
        </p>
        <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-[260px_1fr]" aria-hidden="true">
          <div className="h-64 animate-pulse rounded bg-zinc-800" />
          <div className="h-64 animate-pulse rounded bg-zinc-800" />
        </div>
      </section>
    );
  }
  if (snap.load.kind === "error") {
    return (
      <section role="alert" className="m-4 rounded border border-red-500 bg-red-950/40 p-4 text-sm">
        <h1 className="mb-2 text-lg font-semibold">Workspace da ECU</h1>
        <h2 className="text-base font-semibold text-red-200">{snap.load.title}</h2>
        <p className="mt-1 text-red-100">{snap.load.detail}</p>
        <p className="mt-1 font-mono text-xs text-red-300">{snap.load.code}</p>
        <div className="mt-3 flex gap-2">
          <button type="button" onClick={() => void store.load()} className="rounded border border-red-300 px-3 py-1 text-xs hover:bg-red-900">
            Tentar de novo
          </button>
          {snap.load.code === "SESSION_NOT_FOUND" && (
            <Link
              to="/"
              onClick={() => setActiveSessionId(null)}
              className="rounded bg-amber-500 px-3 py-1 text-xs font-semibold text-zinc-950 hover:bg-amber-400"
            >
              Voltar ao Início
            </Link>
          )}
        </div>
      </section>
    );
  }
  if (snap.load.kind === "noNavigation") {
    return (
      <section role="alert" className="m-4 rounded border border-red-500 bg-red-950/40 p-4 text-sm text-red-100">
        <h1 className="mb-2 text-lg font-semibold">Workspace da ECU</h1>
        <p>{MSG.noNavigation(snap.load.profileId)}</p>
      </section>
    );
  }

  const profile = snap.profile!;
  const cal = snap.calibration!;
  const session = snap.session!;
  const runActive = isRunActive(snap.runState);
  const active = store.activeItem();
  const activeTableId = active ? store.resolveTableId(active) : null;
  const liveTables = Object.values(snap.tables).map((t) => ({ tableId: t.tableId, label: labelOf(t.tableId), live: store.isLiveTunable(t.tableId) }));
  const version = save.version || cal.version;

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === "s") {
      e.preventDefault();
      void store.saveVersion(versionLabel.trim());
      return;
    }
    if (mod && e.key === "Enter") {
      e.preventDefault();
      if (store.canApply()) void store.applyToSession();
      return;
    }
    if (e.key === "?" && !isTyping(e.target)) {
      e.preventDefault();
      setShowShortcuts(true);
    }
  };

  const saveStrategy = async (kind: string, config: Record<string, unknown>) => {
    const next = await store.saveStrategy(kind, config);
    return next ? null : problemToFieldErrors(store.lastPutProblem, kind);
  };

  const renderItem = (item: NavItem | null) => {
    if (!item) return <p className="p-4 text-sm text-zinc-300">{MSG.emptySection}</p>;
    if (!store.itemAvailable(item)) return <p className="p-4 text-sm text-zinc-300">{item.label}: {MSG.orphanItem}</p>;
    if (item.kind === "table") {
      const tableId = store.resolveTableId(item)!;
      const t = snap.tables[tableId]!;
      const Editor = t.y ? TableEditor3D : TableEditor2D;
      const trim = t.kind === "fuel_trim_cyl" || t.kind === "ignition_trim_cyl";
      return (
        <div className="flex flex-col gap-3">
          {trim && <TrimsPanel store={store} key={`trims-${cal.version}`} />}
          <Editor key={tableId} store={store} tableId={tableId} title={item.label} warnings={warnings} />
        </div>
      );
    }
    if (item.kind === "strategy") {
      if (!isStrategyKind(item.target_id)) return <p className="p-4 text-sm text-zinc-300">{item.label}</p>;
      const kind = item.target_id;
      const value = (cal.strategies[kind] as Record<string, unknown> | undefined) ?? strategyDefaults(kind);
      return (
        <StrategyForm
          key={`${kind}-${cal.version}`}
          kind={kind}
          title={item.label}
          value={value}
          support={profile.strategies.find((s) => s.kind === kind)}
          disabled={snap.readOnly || runActive}
          warnings={warnings}
          onSave={(config) => saveStrategy(kind, config)}
        />
      );
    }
    if (item.kind === "base_setup") {
      if (!profile.requires_base_setup) return <p className="p-4 text-sm text-zinc-300">O perfil {profile.name} usa a configuração de fábrica.</p>;
      const step = (BASE_STEPS as readonly string[]).includes(item.target_id) ? (item.target_id as BaseStep) : "trigger";
      return <WizardHost store={store} initialStep={step} key={`wiz-${item.id}`} />;
    }
    return (
      <p className="p-4 text-sm text-zinc-300">
        {item.label}
        {profile.terminology[item.target_id] ? `: ${profile.terminology[item.target_id]}` : ""}
      </p>
    );
  };

  const activeTable = activeTableId ? snap.tables[activeTableId] : undefined;

  return (
    <div onKeyDown={onKeyDown} className="flex min-h-[calc(100vh-5rem)] max-h-[calc(100vh-5rem)] flex-col gap-2 text-zinc-100 overflow-hidden">
      <header className="flex flex-wrap items-center justify-between gap-3 rounded border border-zinc-700 bg-zinc-900 px-3 py-2 flex-shrink-0" style={{ borderLeft: `4px solid ${profile.accent_color}` }}>
        <div>
          <div className="flex items-baseline gap-2">
            <h1 className="text-lg font-semibold">Workspace da ECU</h1>
            {/* A cor de destaque do perfil (ex.: #6b7a8f, #7a6f5a) não tem contraste AA como texto sobre o
                zinc-900: fica numa marca ao lado do nome (axe no navegador real, T224). */}
            <span aria-hidden="true" className="inline-block h-3 w-3 self-center rounded-full" style={{ backgroundColor: profile.accent_color }} />
            <span className="text-lg font-semibold text-zinc-100" data-testid="workspace-profile">
              {profile.name}
            </span>
          </div>
          <p className="text-xs text-zinc-400">
            {snap.vehicle?.display_name ?? session.vehicle_id} · calibração {cal.metadata.name}
            {snap.readOnly && ` · ${MSG.readOnly}`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <VehicleSelector
            api={store.api}
            currentVehicleId={session.vehicle_id}
            disabled={runActive}
            onSwitch={(v, p, close) => store.switchVehicle(v, p, close)}
            onSwitched={(s: Session) => onOpenSession?.(s.session_id)}
          />
          <SwapSelector currentProfileId={profile.profile_id} profiles={snap.profiles} runActive={runActive} onSwap={(body) => store.swap(body)} />
          <button type="button" aria-pressed={showVersions} onClick={() => setShowVersions((v) => !v)} className="rounded border border-zinc-500 px-3 py-1 text-xs hover:bg-zinc-800">
            Versões
          </button>
          <button type="button" onClick={() => setShowShortcuts(true)} className="rounded border border-zinc-500 px-3 py-1 text-xs hover:bg-zinc-800" aria-label="Atalhos de teclado (?)">
            ?
          </button>
        </div>
      </header>
      <StockCalibrationBanner store={store} />

      <div className="grid flex-1 min-h-0 grid-cols-1 gap-2 lg:grid-cols-[minmax(200px,260px)_minmax(0,1fr)] xl:grid-cols-[minmax(240px,300px)_minmax(0,1fr)_minmax(220px,300px)] overflow-hidden">
        <aside className="h-full overflow-y-auto rounded border border-zinc-700 bg-zinc-900 lg:min-w-[200px] lg:max-w-[320px] lg:resize-x">
          <ProfileNavigator
            descriptor={profile}
            activeItemId={snap.activeItemId}
            onSelect={(item) => store.selectItem(item.id)}
            isAvailable={(item) => store.itemAvailable(item)}
            isLocked={(item) => {
              const id = store.resolveTableId(item);
              return id !== null && store.isLocked(id);
            }}
          />
        </aside>
        <main ref={mainRef} className="min-w-0 h-full overflow-y-auto rounded border border-zinc-700 bg-zinc-900/40 p-2" aria-label="Editor">
          {snap.wizardOpen && profile.requires_base_setup ? (
            <WizardHost store={store} initialStep="trigger" />
          ) : showVersions ? (
            <CalibrationVersions
              key={cal.version}
              versions={cal.versions ?? []}
              currentVersion={version}
              fetchVersion={(v) => store.fetchVersion(v)}
              onRevert={(v) => store.revertTo(v)}
              onApply={() => void store.applyToSession()}
              disabled={snap.readOnly}
              tableLabel={labelOf}
            />
          ) : (
            renderItem(active)
          )}
        </main>
        <aside className="flex min-w-0 h-full overflow-y-auto flex-col gap-2 lg:col-span-2 xl:col-span-1" aria-label="Painel lateral">
          <TuningWarnings
            warnings={warnings}
            mbtAvailable={mbtAvailable({ mbtReference: snap.vehicle?.engine.mbt_reference ?? null })}
            tableLabel={labelOf}
            onFocusCell={(tableId, row, col) => {
              const item = profile.navigation.flatMap((s) => s.items).find((i) => store.resolveTableId(i) === tableId);
              if (item) store.selectItem(item.id);
              store.setSelection(tableId, { anchor: { row, col }, focus: { row, col }, mode: "cells" });
            }}
          />
          <LiveTuneIndicator runActive={runActive} telemetryFresh={snap.telemetryFresh} tables={liveTables} activeTableId={activeTableId} />
          {activeTable && (
            <section aria-labelledby="props-title" className="rounded border border-zinc-700 bg-zinc-900 p-2 text-xs">
              <h2 id="props-title" className="mb-1 text-xs font-semibold uppercase tracking-wide text-zinc-300">
                Propriedades
              </h2>
              <dl className="grid grid-cols-2 gap-x-2">
                <dt className="text-zinc-400">Unidade</dt>
                <dd>{activeTable.unit}</dd>
                <dt className="text-zinc-400">Limites</dt>
                <dd>
                  {formatNumber(activeTable.min, activeTable.decimals)} a {formatNumber(activeTable.max, activeTable.decimals)}
                </dd>
                <dt className="text-zinc-400">Eixo X</dt>
                <dd>
                  {activeTable.x.quantity} ({activeTable.x.unit})
                </dd>
                {activeTable.y && (
                  <>
                    <dt className="text-zinc-400">Eixo Y</dt>
                    <dd>
                      {activeTable.y.quantity} ({activeTable.y.unit})
                    </dd>
                  </>
                )}
                <dt className="text-zinc-400">Live-tune</dt>
                <dd>{store.isLiveTunable(activeTable.tableId) ? "sim" : "não"}</dd>
              </dl>
            </section>
          )}
        </aside>
      </div>

      <footer className="flex flex-wrap items-center gap-3 rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs" aria-label="Barra de estado">
        <span>
          Revisão <strong data-testid="revision">{version}</strong>
        </span>
        <span role="status" data-testid="save-state" className={save.state === "failed" || save.state === "error" ? "font-semibold text-red-400" : save.state === "conflict" ? "font-semibold text-amber-300" : "text-zinc-200"}>
          {SAVE_TEXT[save.state](version)}
        </span>
        {save.state === "failed" && (
          <button type="button" onClick={() => store.retrySave()} className="rounded border border-red-400 px-2 py-0.5 text-red-200 hover:bg-red-900">
            Tentar de novo
          </button>
        )}
        <label className="flex items-center gap-1">
          <span className="text-zinc-400">Nome da versão</span>
          <input value={versionLabel} maxLength={60} onChange={(e) => setVersionLabel(e.target.value)} className="w-40 rounded border border-zinc-600 bg-zinc-950 px-1 py-0.5" />
        </label>
        <button type="button" disabled={snap.readOnly} onClick={() => void store.saveVersion(versionLabel.trim())} className="rounded border border-sky-500 px-3 py-1 text-sky-200 hover:bg-sky-900 disabled:opacity-50">
          Salvar versão
        </button>
        <label className="flex items-center gap-1" title="Cada alteração gravada é aplicada à sessão, como no Live Tuning.">
          <input type="checkbox" checked={autoApply} onChange={(e) => store.setPrefs({ autoApply: e.target.checked ? "on" : "off" })} />
          <span>Aplicar automaticamente</span>
        </label>
        {autoApply ? (
          snap.applying && <span className="text-zinc-300">A aplicar…</span>
        ) : (
          <ApplyToSessionButton
            version={version}
            runActive={runActive}
            onlyLiveChanges={store.onlyLiveChanges() && snap.dirtyTables.length > 0}
            disabled={!snap.calibration}
            applying={snap.applying}
            onApply={() => void store.applyToSession()}
          />
        )}
        {snap.applied && (
          <span className="text-emerald-300" data-testid="applied">
            {MSG.applied(snap.applied.version)}
          </span>
        )}
        {store.feed && <MiniGauges feed={store.feed} />}
      </footer>

      <div aria-live="polite" className="fixed bottom-16 right-4 z-40 flex w-[calc(100vw-2rem)] max-w-96 flex-col gap-1">
        {snap.notices.map((n) => (
          <div key={n.id} className={`flex items-start justify-between gap-2 rounded border px-2 py-1 text-xs shadow ${n.tone === "error" ? "border-red-500 bg-red-950" : n.tone === "warn" ? "border-amber-500 bg-amber-950" : n.tone === "success" ? "border-emerald-500 bg-emerald-950" : "border-zinc-500 bg-zinc-900"}`}>
            <span>{n.text}</span>
            <button type="button" onClick={() => store.dismissNotice(n.id)} aria-label="Fechar aviso" className="px-1 text-zinc-300 hover:text-white">
              ×
            </button>
          </div>
        ))}
      </div>

      {snap.conflict && (
        <Dialog titleId="conflict-title" title="Conflito de versão" onClose={() => void store.resolveConflict("reload")}>
          <p className="mb-2 text-sm">
            Outra gravação criou a versão {snap.conflict.latestVersion ?? "nova"} no servidor. Recarregue a versão do servidor ou sobrescreva com as suas alterações.
          </p>
          {snap.conflict.diff ? <VersionDiff a={snap.conflict.latestVersion ?? 0} b={version} diff={snap.conflict.diff} tableLabel={labelOf} /> : <p className="text-xs text-zinc-400">A calcular as diferenças…</p>}
          <div className="mt-3 flex justify-end gap-2">
            <button type="button" onClick={() => void store.resolveConflict("reload")} className="rounded border border-zinc-500 px-3 py-1 text-sm hover:bg-zinc-800">
              Recarregar
            </button>
            <button type="button" onClick={() => void store.resolveConflict("overwrite")} className="rounded bg-amber-600 px-3 py-1 text-sm font-semibold text-black hover:bg-amber-500">
              Sobrescrever com as minhas alterações
            </button>
          </div>
        </Dialog>
      )}
      {showShortcuts && <ShortcutsDialog onClose={() => setShowShortcuts(false)} />}
    </div>
  );
}

function TrimsPanel({ store }: { store: WorkspaceStore }) {
  const snap = store.getSnapshot();
  const nCyl = snap.vehicle?.engine.n_cyl ?? Math.max(1, ...Object.values(snap.tables).map((t) => t.cylinder ?? 0));
  const mean = (kind: TrimKind) => {
    const out: Record<number, number | null> = {};
    for (let c = 1; c <= nCyl; c += 1) out[c] = null;
    for (const t of Object.values(snap.tables)) {
      if (t.kind !== kind || t.cylinder === null) continue;
      const all = t.values.flat();
      out[t.cylinder] = all.reduce((a, b) => a + b, 0) / Math.max(1, all.length);
    }
    return out;
  };
  return (
    <CylinderTrims
      nCyl={nCyl}
      fuel={mean("fuel_trim_cyl")}
      ignition={mean("ignition_trim_cyl")}
      disabled={snap.readOnly}
      onSave={async (kind, values) => {
        await store.saveCylinderTrims(kind, values);
      }}
    />
  );
}

function WizardHost({ store, initialStep }: { store: WorkspaceStore; initialStep: BaseStep }) {
  const snap = useSyncExternalStore(store.subscribe, store.getSnapshot);
  const [base, setBase] = useState<BaseSetupResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const swap = snap.swap;
  useEffect(() => {
    if (swap) return;
    let cancelled = false;
    store.api
      .getBaseSetup(store.sessionId)
      .then((r) => {
        if (!cancelled) setBase(r);
      })
      .catch(() => {
        if (!cancelled) setError("Configuração base indisponível.");
      });
    return () => {
      cancelled = true;
    };
  }, [store, swap]);
  const hardware = swap?.hardware_sheet ?? base?.hardware_sheet;
  if (!hardware) {
    return (
      <p role={error ? "alert" : "status"} className="p-4 text-sm text-zinc-300">
        {error ?? "A carregar a configuração base…"}
      </p>
    );
  }
  return (
    <BaseSetupWizard
      sessionId={store.sessionId}
      api={store.api}
      profileName={snap.profile?.name ?? ""}
      hardware={hardware}
      existing={base?.base_setup ?? null}
      baseVersion={swap?.base_setup_version ?? base?.base_setup_version ?? null}
      checklist={swap?.checklist ?? base?.checklist ?? null}
      fuels={snap.vehicle?.fuels}
      initialStep={initialStep}
      onDone={(result) => void store.onBaseSetupDone(result)}
      onCancel={snap.wizardOpen ? () => store.openWizard(false) : undefined}
    />
  );
}

function MiniGauges({ feed }: { feed: TelemetryFeed }) {
  const f = useSyncExternalStore(feed.subscribe, () => feed.snapshot);
  if (!f.fresh) return <span className="text-zinc-400">{MSG.noBenchData}</span>;
  const ch = f.channels;
  const item = (label: string, v: number | undefined, d: number, unit: string) => (
    <span className="font-mono">
      <span className="text-zinc-400">{label}</span> {v === undefined ? "—" : formatNumber(v, d)}
      {unit}
    </span>
  );
  return (
    <span className="ml-auto flex gap-3" aria-label="Leituras da bancada">
      {item("RPM", ch.rpm, 0, "")}
      {item("Carga", ch.map_kpa ?? ch.load_pct, 0, ch.map_kpa !== undefined ? " kPa" : " %")}
      {item("λ", ch.lambda, 3, "")}
    </span>
  );
}
