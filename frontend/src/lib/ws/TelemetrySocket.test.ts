/** T174 — TelemetrySocket (cockpit RF-02, RF-04, RF-05; D-19; contracts/websocket-telemetry.md §2, §7). */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FakeWebSocket, frameEnvelope } from "@/features/dyno-cockpit/test-utils/mocks";

import { parseEnvelope } from "./envelope";
import { backoffDelayMs, TelemetrySocket, type StreamStats } from "./TelemetrySocket";
import { telemetryUrl } from "./index";

function makeSocket(extra: Partial<ConstructorParameters<typeof TelemetrySocket>[0]> = {}) {
  const received: { type: string; seq: number }[] = [];
  let stats: StreamStats | null = null;
  let now = 0;
  const socket = new TelemetrySocket({
    url: "ws://localhost/ws/v1/sessions/s1/telemetry",
    createSocket: (url) => new FakeWebSocket(url),
    onEnvelope: (env) => received.push({ type: env.type, seq: env.seq }),
    onStats: (s) => {
      stats = s;
    },
    now: () => now,
    ...extra,
  });
  return {
    socket,
    received,
    stats: () => stats!,
    advance: (ms: number) => {
      now += ms;
    },
  };
}

describe("parseEnvelope", () => {
  it("aceita envelope v1 válido e rejeita v ≠ 1, JSON malformado e type desconhecido", () => {
    expect(parseEnvelope(JSON.stringify(frameEnvelope(1, 1, { rpm: 3000 })))?.type).toBe("telemetry.frame");
    expect(parseEnvelope(JSON.stringify({ ...frameEnvelope(1, 1, {}), v: 2 }))).toBeNull();
    expect(parseEnvelope("{nao-json")).toBeNull();
    expect(parseEnvelope(JSON.stringify({ ...frameEnvelope(1, 1, {}), type: "pong" }))).toBeNull();
    expect(parseEnvelope(JSON.stringify({ ...frameEnvelope(1, 1, {}), seq: 1.5 }))).toBeNull();
  });

  it("valida o payload de event.failure com os nomes do FailureEvent (mode, component_id)", () => {
    const env = parseEnvelope({
      v: 1,
      type: "event.failure",
      seq: 9,
      t_sim_s: 13.1,
      payload: { failure_event_id: "f", run_id: "r", t_sim_s: 13.1, cylinder: 3, component_id: "piston:3", mode: "piston_failure", catastrophic: true, causal_variables: {} },
    });
    expect(env?.type).toBe("event.failure");
  });

  it("telemetryUrl monta /ws/v1/sessions/{id}/telemetry na mesma origem", () => {
    expect(telemetryUrl("abc", "http://127.0.0.1:8000")).toBe("ws://127.0.0.1:8000/ws/v1/sessions/abc/telemetry");
  });
});

describe("TelemetrySocket", () => {
  beforeEach(() => {
    FakeWebSocket.reset();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("descarta envelope v ≠ 1 e conta em invalidEnvelopes sem lançar", () => {
    const t = makeSocket();
    t.socket.connect();
    const ws = FakeWebSocket.last();
    ws.open();
    ws.receive({ ...frameEnvelope(1, 1, { rpm: 1 }), v: 2 });
    ws.receive("lixo");
    ws.receive(frameEnvelope(2, 2, { rpm: 1 }));
    expect(t.stats().invalidEnvelopes).toBe(2);
    expect(t.received.map((r) => r.seq)).toEqual([2]);
  });

  it("deduplica por seq na mesma conexão sem descartar envelopes error (seq + 1)", () => {
    const t = makeSocket();
    t.socket.connect();
    const ws = FakeWebSocket.last();
    ws.open();
    ws.receive(frameEnvelope(10, 1, { rpm: 1 }));
    ws.receive({ v: 1, type: "error", seq: 11, t_sim_s: 0.02, payload: { code: "WS_UNKNOWN_CHANNEL", title: "Canal desconhecido", detail: "x", fatal: false } });
    ws.receive(frameEnvelope(12, 2, { rpm: 1 }));
    ws.receive(frameEnvelope(12, 2, { rpm: 1 })); // duplicado
    ws.receive(frameEnvelope(8, 3, { rpm: 1 })); // regressivo
    expect(t.received).toEqual([
      { type: "telemetry.frame", seq: 10 },
      { type: "error", seq: 11 },
      { type: "telemetry.frame", seq: 12 },
    ]);
    expect(t.stats().lastSeq).toBe(12);
  });

  it("saltos de seq sem salto de frame_index não contam como perda", () => {
    const t = makeSocket();
    t.socket.connect();
    const ws = FakeWebSocket.last();
    ws.open();
    ws.receive(frameEnvelope(1, 1, {}));
    ws.receive(frameEnvelope(5, 2, {}));
    ws.receive(frameEnvelope(9, 3, {}));
    expect(t.stats().lost).toBe(0);
    expect(t.stats().lossRate5s).toBe(0);
  });

  it("10 saltos em 250 frames (4 %) acendem a perda > 2 %; 5 s sem saltos apagam", () => {
    const t = makeSocket();
    t.socket.connect();
    const ws = FakeWebSocket.last();
    ws.open();
    let fi = 0;
    let seq = 0;
    for (let i = 0; i < 240; i += 1) {
      fi += i % 24 === 0 && i > 0 ? 2 : 1; // salta 1 frame a cada 24
      seq += 1;
      ws.receive(frameEnvelope(seq, fi, { rpm: 3000 }));
      t.advance(20);
    }
    const s = t.stats();
    expect(s.lost).toBe(9);
    // 9 saltos + o 10.º abaixo: 10 perdidos em 250 frames.
    fi += 2;
    seq += 1;
    ws.receive(frameEnvelope(seq, fi, { rpm: 3000 }));
    expect(t.stats().lost).toBe(10);
    expect(t.stats().lossRate5s).toBeGreaterThan(0.02);
    expect(t.stats().lossRate5s).toBeCloseTo(10 / 251, 2);
    // 5 s seguidos sem saltos.
    for (let i = 0; i < 260; i += 1) {
      t.advance(20);
      fi += 1;
      seq += 1;
      ws.receive(frameEnvelope(seq, fi, { rpm: 3000 }));
    }
    expect(t.stats().lossRate5s).toBe(0);
  });

  it("backoff 0,5 s, 1 s, 2 s, 4 s, 8 s (teto 8 s)", () => {
    expect([1, 2, 3, 4, 5, 6, 10].map((n) => backoffDelayMs(n))).toEqual([500, 1000, 2000, 4000, 8000, 8000, 8000]);
  });

  it("após queda a 1.ª tentativa ocorre em 500 ± 50 ms, com resume_from_seq e novo control.subscribe", () => {
    const t = makeSocket();
    t.socket.subscribe({ channels: ["rpm"], fps: 50 });
    t.socket.connect();
    const ws = FakeWebSocket.last();
    ws.open();
    expect(ws.sentMessages()[0]).toMatchObject({ type: "control.subscribe", payload: { channels: ["rpm"] } });
    ws.receive(frameEnvelope(42, 1, { rpm: 1 }));
    ws.drop(1011);
    expect(t.stats().state).toBe("reconnecting");
    expect(t.stats().reconnectAttempt).toBe(1);
    vi.advanceTimersByTime(449);
    expect(FakeWebSocket.instances).toHaveLength(1);
    vi.advanceTimersByTime(51);
    expect(FakeWebSocket.instances).toHaveLength(2);
    const ws2 = FakeWebSocket.last();
    expect(ws2.url).toContain("resume_from_seq=42");
    ws2.open();
    expect(ws2.sentMessages()[0]?.type).toBe("control.subscribe");
    expect(t.stats().state).toBe("open");
    expect(t.stats().reconnectAttempt).toBe(0);
  });

  it("aceita o replay do resume (seq originais menores que o run.state novo) uma vez", () => {
    const t = makeSocket();
    t.socket.connect();
    FakeWebSocket.last().open();
    FakeWebSocket.last().receive(frameEnvelope(100, 1, {}));
    FakeWebSocket.last().drop(1011);
    vi.advanceTimersByTime(500);
    const ws = FakeWebSocket.last();
    ws.open();
    ws.receive({ v: 1, type: "run.state", seq: 120, t_sim_s: 3, payload: { run_id: "r1", state: "running" } });
    const knock = (seq: number) => ({
      v: 1,
      type: "event.knock",
      seq,
      t_sim_s: 2.5,
      payload: { run_id: "r1", cylinder: 2, knock_class: "severe", intensity: 0.9, retard_deg: 4.5, rpm: 5000 },
    });
    ws.receive(knock(105));
    ws.receive(knock(105)); // repetido
    ws.receive(knock(99)); // anterior ao resume
    ws.receive(frameEnvelope(121, 60, {}));
    ws.receive(knock(110)); // após o replay: regressivo
    expect(t.received.map((r) => r.seq)).toEqual([100, 120, 105, 121]);
  });

  it("após 10 falhas mostra failed e retry() recomeça", () => {
    const t = makeSocket();
    t.socket.connect();
    FakeWebSocket.last().open();
    FakeWebSocket.last().drop(1006);
    for (let attempt = 1; attempt <= 10; attempt += 1) {
      expect(t.stats().reconnectAttempt).toBe(attempt);
      vi.advanceTimersByTime(backoffDelayMs(attempt));
      FakeWebSocket.last().drop(1006);
    }
    expect(t.stats().state).toBe("failed");
    expect(FakeWebSocket.instances).toHaveLength(11);
    t.socket.retry();
    expect(FakeWebSocket.instances).toHaveLength(12);
    FakeWebSocket.last().open();
    expect(t.stats().state).toBe("open");
  });

  it("não reconecta em fechos 4404 (SESSION_NOT_FOUND) e 1000", () => {
    const t = makeSocket();
    t.socket.connect();
    FakeWebSocket.last().open();
    FakeWebSocket.last().drop(4404, "SESSION_NOT_FOUND");
    vi.advanceTimersByTime(10_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(t.stats().state).toBe("failed");
    expect(t.stats().closeReason).toBe("SESSION_NOT_FOUND");
  });

  it("envia control.ping a cada 5 s e considera a conexão caída após 10 s sem envelopes", () => {
    const t = makeSocket();
    t.socket.connect();
    const ws = FakeWebSocket.last();
    ws.open();
    vi.advanceTimersByTime(5000);
    expect(ws.sentMessages().filter((m) => m.type === "control.ping")).toHaveLength(1);
    vi.advanceTimersByTime(5000);
    expect(t.stats().state).toBe("reconnecting");
  });

  it("sendThrottle envia control.throttle preso em 0–100 só com a conexão aberta", () => {
    const t = makeSocket();
    t.socket.connect();
    const ws = FakeWebSocket.last();
    expect(t.socket.sendThrottle(50)).toBe(false);
    ws.open();
    expect(t.socket.sendThrottle(140)).toBe(true);
    expect(ws.sentMessages().at(-1)).toEqual({ v: 1, type: "control.throttle", payload: { throttle_pct: 100 } });
  });

  it("nova conexão reinicia a referência de frame_index (sem perda falsa entre conexões)", () => {
    const t = makeSocket();
    t.socket.connect();
    FakeWebSocket.last().open();
    FakeWebSocket.last().receive(frameEnvelope(1, 10, {}));
    FakeWebSocket.last().drop(1011);
    vi.advanceTimersByTime(500);
    FakeWebSocket.last().open();
    FakeWebSocket.last().receive(frameEnvelope(50, 400, {}));
    expect(t.stats().lost).toBe(0);
  });

  it("close() fecha sem reconectar", () => {
    const t = makeSocket();
    t.socket.connect();
    FakeWebSocket.last().open();
    t.socket.close();
    vi.advanceTimersByTime(20_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(t.stats().state).toBe("closed");
  });
});
