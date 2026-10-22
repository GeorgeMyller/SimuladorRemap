/** OperationCursor: posição bilinear em RPM × carga pela telemetria e trilha de 2 s (tuning RF-11, EC-12). */
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { TypedEnvelope } from "@/lib/ws";

import { channelFor, cursorPosition, fractionalIndex, OperationCursor } from "./OperationCursor";
import { TelemetryFeed, TRAIL_MAX_POINTS } from "./telemetryFeed";
import type { GridAxis } from "./model";
import { loadedStore, renderTable } from "./test-utils/harness";

const X: GridAxis = { quantity: "rpm", values: [1000, 2000, 4000, 6000], unit: "rev/min", sourceChannel: "rpm" };
const Y: GridAxis = { quantity: "map_kpa", values: [50, 100, 200], unit: "kPa", sourceChannel: "map_kpa" };
const GEOM = { colW: 64, rowH: 28, headerW: 84, headerH: 30, rows: 3, cols: 4 };

function frame(i: number, channels: Record<string, number>): TypedEnvelope {
  return { type: "telemetry.frame", seq: i, t_sim_s: i / 50, payload: { session_id: "s", run_id: "r", frame_index: i, channels } };
}

let now = 0;
beforeEach(() => {
  now = 0;
  vi.useFakeTimers();
});
afterEach(() => vi.useRealTimers());

describe("posição do cursor (RF-11)", () => {
  it("rpm 3000 entre os breakpoints 2000 e 4000 fica a 50 % entre as colunas", () => {
    expect(fractionalIndex(X.values, 3000)).toBeCloseTo(1.5, 10);
    const p = cursorPosition(X, Y, 3000, 150);
    expect(p.w).toBeCloseTo(1.5, 10);
    expect(p.u).toBeCloseTo(1.5, 10);
    expect(p.neighbors.map((n) => [n.row, n.col, n.weight])).toEqual([
      [1, 1, 0.25],
      [1, 2, 0.25],
      [2, 1, 0.25],
      [2, 2, 0.25],
    ]);
  });

  it("preso aos limites da grade", () => {
    expect(cursorPosition(X, Y, 500, 10)).toMatchObject({ u: 0, w: 0 });
    expect(cursorPosition(X, Y, 9000, 400)).toMatchObject({ u: 2, w: 3 });
  });

  it("canal do eixo de carga a partir de source_channel", () => {
    expect(channelFor(Y)).toBe("map_kpa");
    expect(channelFor({ ...Y, quantity: "tps_pct", sourceChannel: "tps_pct" })).toBe("throttle_pct");
    expect(channelFor({ ...Y, quantity: "gear", sourceChannel: "gear" })).toBeNull();
  });
});

describe("trilha e telemetria (RF-11, EC-12)", () => {
  it("guarda ≤ 100 pontos e desaparece 2 s após o fim da puxada", () => {
    const feed = new TelemetryFeed({ sessionId: "s", now: () => now });
    feed.ingest({ type: "run.state", seq: 0, t_sim_s: 0, payload: { run_id: "r", state: "running" } });
    for (let i = 1; i <= 150; i += 1) {
      now = i * 10;
      feed.ingest(frame(i, { rpm: 2000 + i, map_kpa: 100 }));
    }
    expect(feed.trail.length).toBeLessThanOrEqual(TRAIL_MAX_POINTS);
    expect(feed.visibleTrail(now).length).toBe(100);
    feed.ingest({ type: "run.state", seq: 151, t_sim_s: 3, payload: { run_id: "r", state: "completed" } });
    expect(feed.visibleTrail(now + 1999).length).toBeGreaterThan(0);
    expect(feed.visibleTrail(now + 2000)).toEqual([]);
  });

  it("o overlay posiciona o cursor e some sem frames por 2 s", () => {
    const feed = new TelemetryFeed({ sessionId: "s", now: () => now });
    render(<div style={{ position: "relative" }}><OperationCursor feed={feed} x={X} y={Y} geom={GEOM} /></div>);
    expect(screen.queryByTestId("operation-cursor")).toBeNull();
    act(() => {
      for (let i = 1; i <= 5; i += 1) {
        now = i * 20;
        feed.ingest(frame(i, { rpm: 2500 + i * 100, map_kpa: 150 }));
      }
    });
    const cursor = screen.getByTestId("operation-cursor");
    expect(cursor).toHaveAttribute("data-w", "1.500");
    expect(cursor).toHaveAttribute("data-u", "1.500");
    expect(cursor.querySelectorAll("[data-trail-point]")).toHaveLength(5);
    expect(cursor.querySelectorAll("[data-neighbor]")).toHaveLength(4);
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.queryByTestId("operation-cursor")).toBeNull();
  });

  it("o editor mostra o cursor com a telemetria da store", async () => {
    vi.useRealTimers();
    localStorage.clear();
    const store = await loadedStore(undefined, { telemetry: true, wsOrigin: "http://localhost" });
    store.start();
    renderTable(store, "ve", "VE");
    act(() => store.feed!.ingest(frame(1, { rpm: 3000, map_kpa: 100 })));
    expect(screen.getByTestId("operation-cursor")).toBeInTheDocument();
    store.stop();
  });
});
