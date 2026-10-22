/**
 * Telemetria para o editor (tuning RF-11, RF-17, EC-12): reutiliza o `TelemetrySocket` da
 * cockpit (`lib/ws`) para `rpm`, carga, lambda (medido/alvo, Quick Tune) e `run.state`. Guarda o último frame, a trilha de 2 s
 * (≤ 100 pontos) e marca os dados como indisponíveis sem frames por 2 s.
 */
import { telemetryUrl, TelemetrySocket, type RunState, type TypedEnvelope, type WebSocketFactory } from "@/lib/ws";

export const TRAIL_WINDOW_MS = 2000;
export const TRAIL_MAX_POINTS = 100;
export const STALE_MS = 2000;
export const CURSOR_CHANNELS = ["rpm", "map_kpa", "load_pct", "throttle_pct", "lambda", "lambda_measured", "lambda_target", "torque_nm"] as const;

export interface TrailPoint {
  t: number;
  channels: Record<string, number>;
}

export interface FeedSnapshot {
  connected: boolean;
  /** Há frame com menos de 2 s. */
  fresh: boolean;
  runState: RunState | null;
  channels: Record<string, number>;
  lastFrameAt: number | null;
  /** Fim da puxada (relógio de parede) para apagar a trilha 2 s depois. */
  runEndedAt: number | null;
}

const ACTIVE_STATES: ReadonlySet<RunState> = new Set(["arming", "running", "coastdown"]);

export function isRunActive(state: RunState | null): boolean {
  return state !== null && ACTIVE_STATES.has(state);
}

export interface TelemetryFeedOptions {
  sessionId: string;
  createSocket?: WebSocketFactory;
  origin?: string;
  now?: () => number;
}

export class TelemetryFeed {
  private socket: TelemetrySocket | null = null;
  private readonly opts: TelemetryFeedOptions;
  private readonly now: () => number;
  private listeners = new Set<() => void>();
  private staleTimer: ReturnType<typeof setTimeout> | undefined;
  readonly trail: TrailPoint[] = [];
  snapshot: FeedSnapshot = { connected: false, fresh: false, runState: null, channels: {}, lastFrameAt: null, runEndedAt: null };

  constructor(opts: TelemetryFeedOptions) {
    this.opts = opts;
    this.now = opts.now ?? (() => performance.now());
  }

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  connect(): void {
    if (this.socket) return;
    const socket = new TelemetrySocket({
      url: telemetryUrl(this.opts.sessionId, this.opts.origin),
      createSocket: this.opts.createSocket,
      onEnvelope: (env) => this.ingest(env),
      onStats: (stats) => {
        const connected = stats.state === "open";
        if (connected !== this.snapshot.connected) this.update({ connected, fresh: connected && this.snapshot.fresh });
      },
    });
    this.socket = socket;
    socket.connect();
    socket.subscribe({ channels: [...CURSOR_CHANNELS], fps: 50 });
  }

  close(): void {
    this.socket?.close();
    this.socket = null;
    if (this.staleTimer !== undefined) clearTimeout(this.staleTimer);
    this.staleTimer = undefined;
  }

  /** Processa um envelope já validado (público para testes e para o replay). */
  ingest(env: TypedEnvelope): void {
    if (env.type === "run.state") {
      const prev = this.snapshot.runState;
      const next = env.payload.state;
      const ended = isRunActive(prev) && !isRunActive(next);
      this.update({ runState: next, runEndedAt: ended ? this.now() : isRunActive(next) ? null : this.snapshot.runEndedAt });
      return;
    }
    if (env.type !== "telemetry.frame") return;
    const channels: Record<string, number> = {};
    for (const [k, v] of Object.entries(env.payload.channels)) if (typeof v === "number" && Number.isFinite(v)) channels[k] = v;
    const t = this.now();
    this.trail.push({ t, channels });
    const cutoff = t - TRAIL_WINDOW_MS;
    while (this.trail.length > 0 && (this.trail[0]!.t < cutoff || this.trail.length > TRAIL_MAX_POINTS)) this.trail.shift();
    if (this.staleTimer !== undefined) clearTimeout(this.staleTimer);
    this.staleTimer = setTimeout(() => this.update({ fresh: false }), STALE_MS);
    this.update({ channels, lastFrameAt: t, fresh: true, connected: true });
  }

  /** Trilha visível: vazia 2 s após o fim da puxada (RF-11). */
  visibleTrail(at: number = this.now()): TrailPoint[] {
    const ended = this.snapshot.runEndedAt;
    if (ended !== null && at - ended >= TRAIL_WINDOW_MS) return [];
    return this.trail.filter((p) => at - p.t <= TRAIL_WINDOW_MS);
  }

  private update(patch: Partial<FeedSnapshot>): void {
    this.snapshot = { ...this.snapshot, ...patch };
    for (const l of this.listeners) l();
  }
}
