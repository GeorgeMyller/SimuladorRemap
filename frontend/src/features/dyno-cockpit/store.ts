/**
 * Estado de telemetria em memória (RF-03, RF-14; RNF-04): o handler do WS só decodifica e
 * escreve aqui; o `RenderLoop` lê. Buffers com capacidade fixa (RNF-03).
 */
import type {
  FailureEventPayload,
  PressureTrace,
  RunStatePayload,
  TypedEnvelope,
} from "@/lib/ws";

import { RingBuffer } from "./render/RingBuffer";
import { SpectrogramModel } from "./render/SpectrogramModel";

/** Canais que recebem 1 amostra por frame (NaN se ausente) para manter as séries XY alinhadas. */
export const ALIGNED_CHANNELS = ["rpm", "power_kw", "torque_nm", "lambda", "egt_c"] as const;

export const MAX_EVENTS_PER_RUN = 500;

export type TimelineEventKind = "knock" | "limiter" | "failure" | "run";
export type Severity = "info" | "warning" | "critical";

export interface TimelineEvent {
  id: number;
  kind: TimelineEventKind;
  t_sim_s: number;
  rpm: number | null;
  severity: Severity;
  label: string;
  runId: string | null;
  cylinder?: number | null;
  /** Retardo (knock) para o texto do alarme. */
  retardDeg?: number;
  knockClass?: "light" | "moderate" | "severe";
  limiterKind?: string;
  limiterActive?: boolean;
  runState?: string;
  failure?: FailureEventPayload;
}

export interface Gap {
  fromT: number;
  toT: number | null;
}

type Listener = (env: TypedEnvelope) => void;

export class TelemetryStore {
  readonly capacity: number;
  readonly buffers = new Map<string, RingBuffer>();
  readonly latest = new Map<string, number>();
  /** Relógio de parede (ms) da última atualização por canal (EC-14). */
  readonly updatedAt = new Map<string, number>();
  readonly spectrogram = new SpectrogramModel();
  pressureTrace: PressureTrace | null = null;
  events: TimelineEvent[] = [];
  runState: RunStatePayload | null = null;
  currentRunId: string | null = null;
  lastFrameAt = -1;
  lastSeq = -1;
  lastTSim = 0;
  /** Total acumulado de `overrun_afterfire`; cada consumidor (animação, áudio) guarda o seu cursor. */
  afterfireTotal = 0;
  afterfireSeq = 0;
  gaps: Gap[] = [];
  /** Incrementa a cada escrita (os painéis só redesenham quando muda). */
  version = 0;
  private readonly listeners = new Set<Listener>();
  private readonly now: () => number;

  constructor(capacity = 3600, now: () => number = () => performance.now()) {
    this.capacity = capacity;
    this.now = now;
    for (const ch of ALIGNED_CHANNELS) this.buffers.set(ch, new RingBuffer(capacity));
  }

  /** Recebe eventos não-frame (para alarmes, áudio e estado da página). */
  onEvent(cb: Listener): () => void {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  }

  buffer(channel: string): RingBuffer {
    let buf = this.buffers.get(channel);
    if (!buf) {
      buf = new RingBuffer(this.capacity);
      this.buffers.set(channel, buf);
    }
    return buf;
  }

  value(channel: string): number | undefined {
    return this.latest.get(channel);
  }

  /** Canais subscritos sem atualização há mais de `afterMs` enquanto chegam frames (EC-14). */
  missingChannels(subscribed: readonly string[], afterMs = 2000): string[] {
    if (this.lastFrameAt < 0) return [];
    const now = this.now();
    if (now - this.firstFrameAt < afterMs) return [];
    return subscribed.filter((ch) => {
      const at = this.updatedAt.get(ch);
      return at === undefined ? true : now - at > afterMs;
    });
  }

  private firstFrameAt = -1;

  ingest(env: TypedEnvelope): void {
    this.lastSeq = env.seq;
    this.lastTSim = env.t_sim_s;
    switch (env.type) {
      case "telemetry.frame":
        this.ingestFrame(env);
        break;
      case "run.state":
        this.ingestRunState(env.payload, env.t_sim_s, env.seq);
        break;
      case "event.knock": {
        const p = env.payload;
        this.addEvent({
          id: env.seq,
          kind: "knock",
          t_sim_s: env.t_sim_s,
          rpm: p.rpm,
          severity: p.knock_class === "severe" ? "critical" : p.knock_class === "moderate" ? "warning" : "info",
          label: `Knock ${p.knock_class} · cil. ${p.cylinder}`,
          runId: p.run_id ?? this.currentRunId,
          cylinder: p.cylinder,
          retardDeg: p.retard_deg,
          knockClass: p.knock_class,
        });
        break;
      }
      case "event.limiter": {
        const p = env.payload;
        this.addEvent({
          id: env.seq,
          kind: "limiter",
          t_sim_s: env.t_sim_s,
          rpm: p.rpm,
          severity: "warning",
          label: `${p.kind}${p.phase ? ` (${p.phase})` : ""} ${p.active ? "ativo" : "inativo"}`,
          runId: p.run_id ?? this.currentRunId,
          limiterKind: p.kind,
          limiterActive: p.active,
        });
        break;
      }
      case "event.failure": {
        const p = env.payload;
        this.addEvent({
          id: env.seq,
          kind: "failure",
          t_sim_s: env.t_sim_s,
          rpm: this.value("rpm") ?? null,
          severity: p.catastrophic ? "critical" : "warning",
          label: `Falha ${p.mode} · ${p.component_id}`,
          runId: p.run_id ?? this.currentRunId,
          cylinder: p.cylinder,
          failure: p,
        });
        break;
      }
      case "error":
        break;
    }
    this.version += 1;
    if (env.type !== "telemetry.frame") for (const cb of this.listeners) cb(env);
  }

  private ingestFrame(env: Extract<TypedEnvelope, { type: "telemetry.frame" }>): void {
    const now = this.now();
    if (this.firstFrameAt < 0) this.firstFrameAt = now;
    this.lastFrameAt = now;
    const { channels, knock_spectrum, cyl_pressure_trace } = env.payload;
    const t = env.t_sim_s;
    if (env.payload.run_id && env.payload.run_id !== this.currentRunId && this.currentRunId === null) {
      this.currentRunId = env.payload.run_id;
    }
    for (const ch of ALIGNED_CHANNELS) {
      const v = channels[ch];
      this.buffer(ch).push(t, typeof v === "number" ? v : Number.NaN);
    }
    for (const [ch, v] of Object.entries(channels)) {
      if (typeof v !== "number") continue;
      this.latest.set(ch, v);
      this.updatedAt.set(ch, now);
      if (!(ALIGNED_CHANNELS as readonly string[]).includes(ch)) this.buffer(ch).push(t, v);
      if (ch === "overrun_afterfire" && v > 0) {
        this.afterfireTotal += Math.round(v);
        this.afterfireSeq = env.seq;
      }
    }
    if (knock_spectrum) {
      this.spectrogram.push(knock_spectrum.magnitude_db, knock_spectrum.bins_hz, knock_spectrum.resonance_hz);
      this.updatedAt.set("knock_spectrum", now);
    }
    if (cyl_pressure_trace) {
      this.pressureTrace = cyl_pressure_trace;
      this.updatedAt.set("cyl_pressure_trace", now);
    }
  }

  private ingestRunState(p: RunStatePayload, t: number, seq: number): void {
    const isNewRun = p.run_id !== null && p.run_id !== this.currentRunId && (p.state === "arming" || p.state === "running");
    if (isNewRun) this.resetRun(p.run_id);
    this.runState = p;
    if (p.run_id) this.currentRunId = p.run_id;
    if (p.previous_state !== p.state) {
      this.addEvent({
        id: seq,
        kind: "run",
        t_sim_s: t,
        rpm: p.rpm ?? null,
        severity: p.state === "engine_failed" ? "critical" : p.state === "aborted" ? "warning" : "info",
        label: `Puxada: ${p.state}${p.abort_reason ? ` (${p.abort_reason})` : ""}`,
        runId: p.run_id,
        runState: p.state,
      });
    }
  }

  /** Nova puxada: limpa as séries ao vivo e a lista de eventos (≤ 500 por puxada). */
  resetRun(runId: string | null): void {
    this.currentRunId = runId;
    for (const ch of ALIGNED_CHANNELS) this.buffer(ch).clear();
    this.events = [];
    this.gaps = [];
    this.version += 1;
  }

  private addEvent(ev: TimelineEvent): void {
    this.events.push(ev);
    if (this.events.length > MAX_EVENTS_PER_RUN) this.events.splice(0, this.events.length - MAX_EVENTS_PER_RUN);
  }

  /** Marca o início de uma lacuna (queda do WS) e o fim ao reconectar (Fluxo D). */
  markGapStart(): void {
    const open = this.gaps.at(-1);
    if (open && open.toT === null) return;
    this.gaps.push({ fromT: this.lastTSim, toT: null });
  }

  markGapEnd(): void {
    const open = this.gaps.at(-1);
    if (open && open.toT === null) open.toT = this.lastTSim;
  }

  /** Estalos novos desde o cursor `since` do consumidor. */
  afterfireSince(since: number): { count: number; seq: number; total: number } {
    return { count: Math.max(0, this.afterfireTotal - since), seq: this.afterfireSeq, total: this.afterfireTotal };
  }

  /** Degradação por FPS (EC-12): espectrograma a 25 colunas/s. */
  setSpectrogramDegraded(degraded: boolean): void {
    this.spectrogram.stride = degraded ? 2 : 1;
  }

  /** RPM no instante `t` (cursor dos gráficos vs. RPM). */
  rpmAt(t: number): number | undefined {
    return this.buffer("rpm").valueAt(t);
  }
}
