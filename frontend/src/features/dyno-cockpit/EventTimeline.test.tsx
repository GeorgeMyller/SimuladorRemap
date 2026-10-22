/** T182 — EventTimeline: clicar num evento posiciona o cursor no `t_sim_s` (RF-14). */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { parseEnvelope } from "@/lib/ws";

import { EventTimeline } from "./EventTimeline";
import { MAX_EVENTS_PER_RUN, TelemetryStore, type TimelineEvent } from "./store";
import { installCanvasMock } from "./test-utils/mocks";
import { openSocket, renderCockpit } from "./test-utils/harness";

vi.mock("uplot", () => import("./test-utils/uplotMock"));

const knock = (seq: number, t: number) => ({
  v: 1,
  type: "event.knock",
  seq,
  t_sim_s: t,
  payload: { run_id: "r1", cylinder: 2, knock_class: "severe", intensity: 0.9, intensity_raw: 6.4, retard_deg: 4.5, rpm: 5480, threshold: 0.15 },
});

describe("EventTimeline", () => {
  it("lista knock, limitador, falha e run.state com t_sim_s, RPM e severidade", () => {
    const store = new TelemetryStore();
    store.ingest(parseEnvelope({ v: 1, type: "run.state", seq: 1, t_sim_s: 1, payload: { run_id: "r1", state: "running", previous_state: "arming" } })!);
    store.ingest(parseEnvelope(knock(2, 12.4))!);
    store.ingest(parseEnvelope({ v: 1, type: "event.limiter", seq: 3, t_sim_s: 13, payload: { run_id: "r1", kind: "rev_limiter", phase: "hard", active: true, rpm: 7004 } })!);
    store.ingest(
      parseEnvelope({
        v: 1,
        type: "event.failure",
        seq: 4,
        t_sim_s: 13.1,
        payload: { failure_event_id: "f", run_id: "r1", t_sim_s: 13.1, cylinder: 3, component_id: "piston:3", mode: "piston_failure", catastrophic: true, causal_variables: {} },
      })!,
    );
    render(<EventTimeline events={store.events} onSelect={() => undefined} locale="pt-BR" />);
    const items = screen.getAllByRole("button");
    expect(items).toHaveLength(4);
    expect(items[1]).toHaveTextContent("12,40 s");
    expect(items[1]).toHaveTextContent("5480 rpm");
    expect(items[1]).toHaveTextContent("crítico");
    expect(items[2]).toHaveTextContent("Limitador");
    expect(items[3]).toHaveAttribute("data-event-kind", "failure");
    expect(items[0]).toHaveTextContent("Puxada em curso");
  });

  it("clicar no evento chama onSelect com t_sim_s = 12,40 e destaca-o", () => {
    const ev: TimelineEvent = { id: 9, kind: "knock", t_sim_s: 12.4, rpm: 5480, severity: "critical", label: "k", runId: "r1", cylinder: 2, retardDeg: 4.5, knockClass: "severe" };
    const onSelect = vi.fn();
    const { rerender } = render(<EventTimeline events={[ev]} onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("button"));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ t_sim_s: 12.4 }));
    rerender(<EventTimeline events={[ev]} onSelect={onSelect} selectedId={9} />);
    expect(screen.getByRole("button")).toHaveAttribute("aria-current", "true");
  });

  it("guarda até 500 eventos por puxada", () => {
    const store = new TelemetryStore();
    for (let i = 0; i < 620; i += 1) store.ingest(parseEnvelope(knock(i + 1, i / 10))!);
    expect(store.events).toHaveLength(MAX_EVENTS_PER_RUN);
    expect(store.events[0]?.id).toBe(121);
  });

  it("na cockpit, o clique posiciona o cursor dos gráficos em 12,40 s", async () => {
    const canvas = installCanvasMock({ ctx2d: true });
    await renderCockpit();
    const ws = openSocket();
    act(() => ws.receive(knock(10, 12.4)));
    fireEvent.click(screen.getByRole("tab", { name: /Eventos/ }));
    const item = await screen.findByRole("button", { name: /12,40 s/ }, { timeout: 2000 });
    fireEvent.click(item);
    await waitFor(() => expect(screen.getByTestId("chart-cursor")).toHaveTextContent("Cursor: 12,40 s"));
    expect(screen.getByRole("button", { name: /12,40 s/ })).toHaveAttribute("aria-current", "true");
    canvas.spy.mockRestore();
  });
});
