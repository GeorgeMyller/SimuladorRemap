/* eslint-disable @typescript-eslint/require-await, @typescript-eslint/unbound-method -- mocks assíncronos e asserções sobre vi.fn */
/** T184 — DataloggerPanel: cursor, até 8 canais, export, import e compare (RF-17). */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { exportRunLog, type DataLog, type LogComparison } from "./api";
import { DataloggerPanel, MAX_DATALOGGER_CHANNELS, nearestIndex, toggleChannel, type DataloggerApi } from "./DataloggerPanel";
import { FakeUPlot } from "./test-utils/uplotMock";

vi.mock("uplot", () => import("./test-utils/uplotMock"));

const CHANNELS = ["rpm", "power_kw", "torque_nm", "lambda", "egt_c", "map_kpa", "iat_c", "ect_c", "knock_retard_deg", "throttle_pct"];

function makeLog(runId: string): DataLog {
  const t = Array.from({ length: 101 }, (_, i) => i * 0.1);
  return {
    header: { run_id: runId, channels: CHANNELS.map((name) => ({ name, unit: name === "rpm" ? "rpm" : "-" })), terminal_state: "completed" },
    t_sim_s: t,
    data: Object.fromEntries(CHANNELS.map((c, k) => [c, t.map((x) => x * 10 + k)])),
    sha256: "a".repeat(64),
  };
}

const comparison: LogComparison = {
  bin_rpm: 100,
  bins: [2000, 2100, 2200].map((rpm_bin, i) => ({ rpm_bin, power_kw_a: 80 + i, power_kw_b: 85 + i, torque_nm_a: 300, torque_nm_b: 310 })),
  peak_whp_a: 210.5,
  peak_whp_b: 225.3,
  delta_peak_whp_pct: 7.0,
  max_abs_delta: { torque_nm: 12.5, power_kw: 6.1, whp: 8.2, lambda: 0.03, egt_c: 25 },
};

function makeApi(): DataloggerApi & Record<string, ReturnType<typeof vi.fn>> {
  return {
    getLog: vi.fn(async (id: string) => makeLog(id)),
    compareLogs: vi.fn(async () => comparison),
    importLog: vi.fn(async () => ({ log_id: "imp-0123456789ab" })),
    exportLog: vi.fn(async (id: string, f: "json" | "csv") => `run-${id}.${f}`),
  } as never;
}

const runs = [
  { runId: "r-base", label: "Puxada base", state: "completed" },
  { runId: "r-02", label: "#2 Varredura", state: "completed" },
];

afterEach(() => FakeUPlot.reset());

describe("DataloggerPanel", () => {
  it("carrega o log da puxada mais recente e mostra o cursor com os valores dos canais", async () => {
    const api = makeApi();
    const onCursor = vi.fn();
    render(<DataloggerPanel runs={runs} api={api} onCursorChange={onCursor} />);
    expect(await screen.findByRole("group", { name: /Canais/ })).toBeInTheDocument();
    expect(api.getLog).toHaveBeenCalledWith("r-02");
    fireEvent.change(screen.getByRole("slider", { name: "Cursor do datalogger" }), { target: { value: "5" } });
    expect(onCursor).toHaveBeenCalledWith(5);
    expect(screen.getByTestId("datalogger-cursor").textContent).toMatch(/5[,.]00 s/);
    const table = screen.getByRole("table", { name: "Valores no cursor" });
    expect(within(table).getByText("rpm").closest("tr")).toHaveTextContent("50");
  });

  it("permite até 8 canais", async () => {
    render(<DataloggerPanel runs={runs} api={makeApi()} />);
    const group = await screen.findByRole("group", { name: /Canais/ });
    const boxes = within(group).getAllByRole("checkbox");
    for (const b of boxes) if (!(b as HTMLInputElement).checked) fireEvent.click(b);
    const checked = within(group).getAllByRole("checkbox").filter((b) => (b as HTMLInputElement).checked);
    expect(checked).toHaveLength(MAX_DATALOGGER_CHANNELS);
    expect(within(group).getAllByRole("checkbox").filter((b) => (b as HTMLInputElement).disabled)).toHaveLength(CHANNELS.length - 8);
    expect(FakeUPlot.instances.at(-1)!.opts.series).toHaveLength(9);
    expect(toggleChannel(["a"], "a")).toEqual([]);
    expect(nearestIndex([0, 1, 2, 3], 2.4)).toBe(2);
    expect(nearestIndex([], 1)).toBe(-1);
  });

  it("export CSV dispara o download run-<run_id>.csv", async () => {
    const api = makeApi();
    render(<DataloggerPanel runs={runs} api={api} />);
    await screen.findByRole("group", { name: /Canais/ });
    fireEvent.click(screen.getByRole("button", { name: "Exportar CSV" }));
    expect(await screen.findByText("Exportado: run-r-02.csv")).toBeInTheDocument();
    expect(api.exportLog).toHaveBeenCalledWith("r-02", "csv");
  });

  it("exportRunLog cria o link de download com o nome run-<run_id>.csv", async () => {
    const created: HTMLAnchorElement[] = [];
    const origCreate = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const el = origCreate(tag);
      if (tag === "a") {
        created.push(el as HTMLAnchorElement);
        vi.spyOn(el as HTMLAnchorElement, "click").mockImplementation(() => undefined);
      }
      return el;
    });
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    const fetchImpl = vi.fn(async () => new Response("t_sim_s (s),tick (-)\n", { status: 200, headers: { "Content-Type": "text/csv" } }));
    const name = await exportRunLog("01J9Z", "csv", fetchImpl);
    expect(name).toBe("run-01J9Z.csv");
    expect(fetchImpl).toHaveBeenCalledWith("/api/v1/runs/01J9Z/log?format=csv", expect.anything());
    expect(created[0]?.download).toBe("run-01J9Z.csv");
    expect(created[0]?.click).toHaveBeenCalled();
  });

  it("importa um log JSON", async () => {
    const api = makeApi();
    render(<DataloggerPanel runs={runs} api={api} />);
    await screen.findByRole("group", { name: /Canais/ });
    const file = new File([JSON.stringify(makeLog("x"))], "run-x.json", { type: "application/json" });
    fireEvent.change(screen.getByLabelText("Importar log JSON"), { target: { files: [file] } });
    expect(await screen.findByText("Log importado: imp-0123456789ab")).toBeInTheDocument();
    expect(api.importLog).toHaveBeenCalledWith(expect.stringContaining('"run_id":"x"'));
  });

  it("compara duas puxadas: mostra as duas curvas e o delta máximo por canal", async () => {
    const api = makeApi();
    render(<DataloggerPanel runs={runs} api={api} />);
    await screen.findByRole("group", { name: /Canais/ });
    fireEvent.change(screen.getByRole("combobox", { name: "Puxada de comparação" }), { target: { value: "r-base" } });
    fireEvent.click(screen.getByRole("button", { name: "Comparar" }));
    const block = await screen.findByTestId("comparison");
    expect(api.compareLogs).toHaveBeenCalledWith("r-base", "r-02");
    const chart = FakeUPlot.instances.at(-1)!;
    expect(chart.opts.series.map((s) => s.label)).toEqual(["RPM", "A", "B"]);
    expect(chart.data[1]).toHaveLength(3);
    const table = within(block).getByRole("table", { name: "Delta máximo por canal" });
    expect(within(table).getAllByRole("row")).toHaveLength(5);
    expect(table).toHaveTextContent("Δ máx. torque_nm");
  });

  it("puxada abortada aparece com o selo 'parcial'", async () => {
    render(<DataloggerPanel runs={[{ runId: "r-ab", label: "#1 (parcial)", state: "aborted" }]} api={makeApi()} />);
    await waitFor(() => expect(screen.getByTestId("partial-badge")).toHaveTextContent("parcial"));
  });

  it("sem puxadas mostra o estado vazio", () => {
    render(<DataloggerPanel runs={[]} api={makeApi()} />);
    expect(screen.getByText(/Sem puxadas para rever/)).toBeInTheDocument();
  });
});
