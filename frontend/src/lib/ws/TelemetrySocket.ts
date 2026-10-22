/**
 * Cliente tipado do WebSocket de telemetria (contracts/websocket-telemetry.md).
 * - valida cada `WsEnvelope` (v = 1) e conta inválidos sem lançar (EC-04);
 * - deduplica por `seq` na mesma conexão; o replay do resume é aceito uma vez (EC-03, §7);
 * - mede perda só por salto de `frame_index` (§2.2) numa janela de 5 s;
 * - reconecta com backoff 0,5 s → 8 s, até 10 tentativas, com `resume_from_seq` (RF-05).
 */
import {
  parseEnvelope,
  type TelemetrySubscription,
  type TypedEnvelope,
  type WsClientMessage,
} from "./envelope";

export type StreamState = "connecting" | "open" | "reconnecting" | "failed" | "closed";

export interface StreamStats {
  lastSeq: number;
  lastFrameIndex: number;
  received: number;
  lost: number;
  lossRate5s: number;
  invalidEnvelopes: number;
  duplicates: number;
  reconnectAttempt: number;
  maxAttempts: number;
  state: StreamState;
  /** Código de fecho que impede reconexão (ex.: 4404), ou `null`. */
  closeCode: number | null;
  closeReason: string | null;
}

type WsLike = Pick<WebSocket, "send" | "close" | "readyState"> & {
  onopen: ((ev: Event) => unknown) | null;
  onclose: ((ev: CloseEvent) => unknown) | null;
  onerror: ((ev: Event) => unknown) | null;
  onmessage: ((ev: MessageEvent) => unknown) | null;
};

export type WebSocketFactory = (url: string) => WsLike;

export interface TelemetrySocketOptions {
  /** URL absoluta `ws(s)://…/ws/v1/sessions/{id}/telemetry`. */
  url: string;
  onEnvelope?: (env: TypedEnvelope) => void;
  onStats?: (stats: StreamStats) => void;
  /** Chamado após cada reabertura bem-sucedida (não na 1.ª). */
  onReconnected?: () => void;
  createSocket?: WebSocketFactory;
  /** Relógio de parede em ms (janela de perda). */
  now?: () => number;
  maxAttempts?: number;
  backoffBaseMs?: number;
  backoffCapMs?: number;
  pingIntervalMs?: number;
  idleTimeoutMs?: number;
  lossWindowMs?: number;
  /** Regista envelopes inválidos no console (modo dev). */
  debug?: boolean;
}

/** Fechos em que o cliente não reconecta (§8). */
const NO_RECONNECT_CODES = new Set([1000, 1008, 4403, 4404, 4429]);

/** Atraso da tentativa `n` (1-based): 0,5 s, 1 s, 2 s, 4 s, 8 s, teto 8 s. */
export function backoffDelayMs(attempt: number, baseMs = 500, capMs = 8000): number {
  return Math.min(capMs, baseMs * 2 ** Math.max(0, attempt - 1));
}

const OPEN = 1;

export class TelemetrySocket {
  private readonly opts: Required<
    Omit<TelemetrySocketOptions, "onEnvelope" | "onStats" | "onReconnected" | "createSocket">
  > &
    Pick<TelemetrySocketOptions, "onEnvelope" | "onStats" | "onReconnected">;
  private readonly createSocket: WebSocketFactory;
  private ws: WsLike | null = null;
  private subscription: TelemetrySubscription | null = null;
  private stats: StreamStats;
  /** Maior `seq` aceito em qualquer conexão (ponto de resume). */
  private resumeSeq = -1;
  /** Maior `seq` aceito na conexão atual. */
  private connSeq = -1;
  private connFloor = -1;
  private replayPhase = false;
  private replaySeen = new Set<number>();
  private connFrameIndex = -1;
  private lossWindow: { t: number; received: number; lost: number }[] = [];
  private everOpened = false;
  private openedThisConn = false;
  private stopped = false;
  private retryTimer: ReturnType<typeof setTimeout> | undefined;
  private pingTimer: ReturnType<typeof setInterval> | undefined;
  private idleTimer: ReturnType<typeof setTimeout> | undefined;
  private nonce = 0;

  constructor(options: TelemetrySocketOptions) {
    this.opts = {
      now: () => performance.now(),
      maxAttempts: 10,
      backoffBaseMs: 500,
      backoffCapMs: 8000,
      pingIntervalMs: 5000,
      idleTimeoutMs: 10_000,
      lossWindowMs: 5000,
      debug: false,
      ...options,
    };
    this.createSocket =
      options.createSocket ?? ((url: string) => new WebSocket(url));
    this.stats = {
      lastSeq: -1,
      lastFrameIndex: -1,
      received: 0,
      lost: 0,
      lossRate5s: 0,
      invalidEnvelopes: 0,
      duplicates: 0,
      reconnectAttempt: 0,
      maxAttempts: this.opts.maxAttempts,
      state: "connecting",
      closeCode: null,
      closeReason: null,
    };
  }

  getStats(): StreamStats {
    this.refreshLoss();
    return { ...this.stats };
  }

  connect(): void {
    this.stopped = false;
    this.open(false);
  }

  /** Reinicia depois de `failed` (botão "Tentar de novo"). */
  retry(): void {
    this.clearRetry();
    this.stats.reconnectAttempt = 0;
    this.stats.closeCode = null;
    this.stats.closeReason = null;
    this.stopped = false;
    this.open(this.everOpened);
  }

  close(): void {
    this.stopped = true;
    this.clearRetry();
    this.clearTimers();
    const ws = this.ws;
    this.ws = null;
    if (ws) {
      ws.onclose = null;
      ws.onmessage = null;
      ws.onerror = null;
      ws.onopen = null;
      try {
        ws.close(1000);
      } catch {
        /* socket já fechado */
      }
    }
    this.setState("closed");
  }

  /** Guarda a subscrição e envia-a já, se a conexão estiver aberta; reenviada em cada reconexão. */
  subscribe(subscription: TelemetrySubscription): void {
    this.subscription = subscription;
    this.send({ v: 1, type: "control.subscribe", payload: subscription });
  }

  sendThrottle(throttlePct: number): boolean {
    const pct = Math.min(100, Math.max(0, throttlePct));
    return this.send({ v: 1, type: "control.throttle", payload: { throttle_pct: pct } });
  }

  private send(message: WsClientMessage): boolean {
    if (!this.ws || this.ws.readyState !== OPEN) return false;
    this.ws.send(JSON.stringify(message));
    return true;
  }

  private open(isReconnect: boolean): void {
    this.clearTimers();
    const url =
      isReconnect && this.resumeSeq >= 0
        ? `${this.opts.url}${this.opts.url.includes("?") ? "&" : "?"}resume_from_seq=${this.resumeSeq}`
        : this.opts.url;
    this.openedThisConn = false;
    this.connSeq = -1;
    this.connFloor = isReconnect ? this.resumeSeq : -1;
    this.replayPhase = isReconnect && this.resumeSeq >= 0;
    this.replaySeen.clear();
    this.connFrameIndex = -1;
    if (!isReconnect) this.setState("connecting");
    let ws: WsLike;
    try {
      ws = this.createSocket(url);
    } catch {
      this.handleClose(1006, "");
      return;
    }
    this.ws = ws;
    ws.onopen = () => this.handleOpen();
    ws.onmessage = (ev: MessageEvent) => this.handleMessage(ev.data);
    ws.onerror = () => undefined;
    ws.onclose = (ev: CloseEvent) => {
      if (this.ws === ws) this.handleClose(ev.code, ev.reason);
    };
  }

  private handleOpen(): void {
    const wasReconnect = this.everOpened;
    this.openedThisConn = true;
    this.everOpened = true;
    this.stats.reconnectAttempt = 0;
    this.setState("open");
    if (this.subscription) this.send({ v: 1, type: "control.subscribe", payload: this.subscription });
    this.pingTimer = setInterval(() => {
      this.nonce += 1;
      this.send({ v: 1, type: "control.ping", payload: { nonce: `p${this.nonce}` } });
    }, this.opts.pingIntervalMs);
    this.armIdle();
    if (wasReconnect) this.opts.onReconnected?.();
  }

  private armIdle(): void {
    if (this.idleTimer !== undefined) clearTimeout(this.idleTimer);
    this.idleTimer = setTimeout(() => {
      // 10 s sem envelope: conexão considerada caída (EC-01).
      const ws = this.ws;
      if (!ws) return;
      ws.onclose = null;
      try {
        ws.close(4000, "idle");
      } catch {
        /* ignora */
      }
      this.handleClose(4408, "WS_IDLE_TIMEOUT");
    }, this.opts.idleTimeoutMs);
  }

  private handleMessage(raw: unknown): void {
    try {
      this.armIdle();
      const env = parseEnvelope(raw);
      if (!env) {
        this.stats.invalidEnvelopes += 1;
        if (this.opts.debug) console.warn("[TelemetrySocket] envelope inválido descartado", raw);
        this.emitStats();
        return;
      }
      if (!this.accept(env)) {
        this.stats.duplicates += 1;
        return;
      }
      if (env.type === "telemetry.frame") this.trackFrame(env.payload.frame_index);
      this.opts.onEnvelope?.(env);
      this.emitStats();
    } catch (error) {
      // O handler nunca propaga exceção (EC-04).
      if (this.opts.debug) console.error("[TelemetrySocket] erro no handler", error);
    }
  }

  /** Regra do `seq` (§2.1, §7). */
  private accept(env: TypedEnvelope): boolean {
    const seq = env.seq;
    if (this.replayPhase) {
      if (env.type === "telemetry.frame") {
        this.replayPhase = false;
      } else {
        if (seq <= this.connFloor || this.replaySeen.has(seq)) return false;
        this.replaySeen.add(seq);
        this.connSeq = Math.max(this.connSeq, seq);
        this.resumeSeq = Math.max(this.resumeSeq, seq);
        this.stats.lastSeq = this.resumeSeq;
        return true;
      }
    }
    if (seq <= this.connSeq || seq <= this.connFloor) return false;
    this.connSeq = seq;
    this.resumeSeq = Math.max(this.resumeSeq, seq);
    this.stats.lastSeq = this.resumeSeq;
    return true;
  }

  private trackFrame(frameIndex: number): void {
    let lost = 0;
    if (this.connFrameIndex >= 0 && frameIndex > this.connFrameIndex + 1) {
      lost = frameIndex - this.connFrameIndex - 1;
    }
    if (frameIndex > this.connFrameIndex) this.connFrameIndex = frameIndex;
    this.stats.lastFrameIndex = frameIndex;
    this.stats.received += 1;
    this.stats.lost += lost;
    this.lossWindow.push({ t: this.opts.now(), received: 1, lost });
    this.refreshLoss();
  }

  private refreshLoss(): void {
    const cutoff = this.opts.now() - this.opts.lossWindowMs;
    let drop = 0;
    while (drop < this.lossWindow.length && this.lossWindow[drop]!.t < cutoff) drop += 1;
    if (drop > 0) this.lossWindow.splice(0, drop);
    let received = 0;
    let lost = 0;
    for (const item of this.lossWindow) {
      received += item.received;
      lost += item.lost;
    }
    this.stats.lossRate5s = received + lost > 0 ? lost / (received + lost) : 0;
  }

  private handleClose(code: number, reason: string): void {
    this.clearTimers();
    this.ws = null;
    if (this.stopped) return;
    if (NO_RECONNECT_CODES.has(code)) {
      this.stats.closeCode = code;
      this.stats.closeReason = reason || null;
      this.setState(code === 1000 ? "closed" : "failed");
      return;
    }
    if (!this.openedThisConn && this.stats.reconnectAttempt >= this.opts.maxAttempts) {
      this.setState("failed");
      return;
    }
    this.scheduleReconnect();
  }

  private scheduleReconnect(): void {
    if (this.stats.reconnectAttempt >= this.opts.maxAttempts) {
      this.setState("failed");
      return;
    }
    this.stats.reconnectAttempt += 1;
    this.setState("reconnecting");
    const delay = backoffDelayMs(
      this.stats.reconnectAttempt,
      this.opts.backoffBaseMs,
      this.opts.backoffCapMs,
    );
    this.clearRetry();
    this.retryTimer = setTimeout(() => {
      this.retryTimer = undefined;
      if (!this.stopped) this.open(true);
    }, delay);
  }

  private setState(state: StreamState): void {
    this.stats.state = state;
    this.emitStats();
  }

  private emitStats(): void {
    this.opts.onStats?.(this.getStats());
  }

  private clearRetry(): void {
    if (this.retryTimer !== undefined) clearTimeout(this.retryTimer);
    this.retryTimer = undefined;
  }

  private clearTimers(): void {
    if (this.pingTimer !== undefined) clearInterval(this.pingTimer);
    if (this.idleTimer !== undefined) clearTimeout(this.idleTimer);
    this.pingTimer = undefined;
    this.idleTimer = undefined;
  }
}
