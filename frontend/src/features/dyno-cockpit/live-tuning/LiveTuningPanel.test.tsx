/**
 * T054 — Live Tuning na bancada (feature 002, RF-05 a RF-08): célula ao vivo piscante a partir dos
 * frames, aplicação automática após o PATCH, Quick Tune com o λ da bancada e a Tela Dividida.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { calibrationFixture, makeApi as makeEcuApi, type FakeApi } from "@/features/ecu-tuning/test-utils/fixtures";
import type { TypedEnvelope } from "@/lib/ws";

import { DynoCockpitView } from "../DynoCockpitPage";
import { RenderLoop } from "../render/RenderLoop";
import { TelemetryStore } from "../store";
import { makeApi, SESSION_ID } from "../test-utils/harness";
import { fakeAudioFactory, FakeWebSocket, frameEnvelope, installCanvasMock, manualRaf } from "../test-utils/mocks";
import { FakeUPlot } from "../test-utils/uplotMock";
import { LIVE_CELL_CLASS, LIVE_STALE_MS, LIVE_TUNING_CHANNELS, liveCellFor, liveChannels } from "./liveCell";
import { LiveTuningPanel } from "./LiveTuningPanel";

vi.mock("uplot", () => import("../test-utils/uplotMock"));

// O Vitest esvazia as folhas .css importadas: lê o ficheiro real.
const LIVE_CELL_CSS = readFileSync(resolve(process.cwd(), "src/features/dyno-cockpit/live-tuning/liveCell.css"), "utf8");

let canvas: ReturnType<typeof installCanvasMock>;
beforeEach(() => {
  canvas = installCanvasMock({ ctx2d: true });
  FakeUPlot.reset();
  localStorage.clear();
});
afterEach(() => canvas.spy.mockRestore());

let seq = 0;
function frame(telemetry: TelemetryStore, channels: Record<string, number>) {
  seq += 1;
  telemetry.ingest(frameEnvelope(seq, seq, channels) as unknown as TypedEnvelope);
}

function setup(api: FakeApi = makeEcuApi()) {
  const telemetry = new TelemetryStore();
  const raf = manualRaf();
  const loop = new RenderLoop({ raf: raf.raf, caf: raf.caf, doc: null });
  loop.start();
  let t = 0;
  const tick = () =>
    act(() => {
      t += 16;
      raf.tick(t);
    });
  render(<LiveTuningPanel sessionId={SESSION_ID} telemetry={telemetry} loop={loop} deps={{ api, storage: localStorage, debounceMs: 5 }} />);
  return { telemetry, loop, tick, api };
}

const liveCell = () => document.querySelector<HTMLElement>('[data-testid="live-cell"]');

describe("liveCell (RF-06, T034)", () => {
  it("célula mais próxima pelo eixo RPM × MAP e nada sem frames frescos", () => {
    const telemetry = new TelemetryStore(3600, () => 1000);
    const table = { ...calibrationFixture().tables.ve!, x: { quantity: "rpm", values: [1000, 2000, 3000], unit: "rpm", sourceChannel: "rpm" }, y: { quantity: "map_kpa", values: [50, 100], unit: "kPa", sourceChannel: "map_kpa" }, values: [[1, 2, 3], [4, 5, 6]], tableId: "ve", kind: "ve", liveTunable: true, cylinder: null };
    expect(liveCellFor(table, telemetry, 1000)).toBeNull();
    telemetry.ingest(frameEnvelope(1, 1, { rpm: 2400, map_kpa: 90, lambda: 0.9 }) as unknown as TypedEnvelope);
    expect(liveCellFor(table, telemetry, 1000)).toEqual({ row: 1, col: 1 });
    expect(liveCellFor(table, telemetry, 1000 + LIVE_STALE_MS + 1)).toBeNull();
    expect(liveChannels(telemetry, ["rpm", "lambda", "egt_c"], 1000)).toEqual({ rpm: 2400, lambda: 0.9 });
    expect(liveChannels(telemetry, undefined, 1000)).toMatchObject({ rpm: 2400, map_kpa: 90 });
    expect(LIVE_TUNING_CHANNELS).toEqual(["rpm", "map_kpa", "load_pct", "lambda_measured", "lambda_target"]);
  });

  it("avanço do OEM-Stage (RPM × load_pct): o canal do eixo está na subscrição e a célula aparece", () => {
    const telemetry = new TelemetryStore(3600, () => 1000);
    const table = { ...calibrationFixture().tables.ve!, x: { quantity: "rpm", values: [1000, 2000, 3000], unit: "rpm", sourceChannel: "rpm" }, y: { quantity: "load_pct", values: [20, 60, 100], unit: "%", sourceChannel: "load_pct" }, values: [[1, 2, 3], [4, 5, 6], [7, 8, 9]], tableId: "ignition_base", kind: "ignition_base", liveTunable: true, cylinder: null };
    for (const axis of [table.x, table.y]) expect(LIVE_TUNING_CHANNELS).toContain(axis.sourceChannel);
    telemetry.ingest(frameEnvelope(1, 1, { rpm: 2900, load_pct: 95 }) as unknown as TypedEnvelope);
    expect(liveCellFor(table, telemetry, 1000)).toEqual({ row: 2, col: 2 });
  });

  it("o destaque anima só sem prefers-reduced-motion (estático com reduce)", () => {
    expect(LIVE_CELL_CSS).toMatch(new RegExp(`\\.${LIVE_CELL_CLASS} \\{\\s*box-shadow`));
    expect(LIVE_CELL_CSS).toMatch(/@media \(prefers-reduced-motion: no-preference\)[^}]*animation: live-cell-blink/);
  });
});

describe("LiveTuningPanel (T033, T054)", () => {
  it("não injeta <style> inline (o CSP de produção style-src 'self' bloqueia-o)", async () => {
    setup();
    await screen.findByRole("grid");
    expect(document.querySelector("[data-live-tuning] style")).toBeNull();
  });

  it("frame com rpm 3000 e map 100 kPa destaca a célula mais próxima; a célula muda com o frame", async () => {
    const { telemetry, tick } = setup();
    await screen.findByRole("grid");
    expect(liveCell()).toBeNull();
    expect(screen.getByTestId("live-cell-label")).toHaveTextContent("sem dados da bancada");

    frame(telemetry, { rpm: 3000, map_kpa: 100 });
    tick();
    expect(liveCell()).toHaveAttribute("data-cell", "4,5");
    expect(liveCell()).toHaveClass(LIVE_CELL_CLASS);
    expect(screen.getByTestId("live-cell-label")).toHaveTextContent("3000 rev/min × 100 kPa");

    frame(telemetry, { rpm: 5000, map_kpa: 200 });
    tick();
    expect(liveCell()).toHaveAttribute("data-cell", "9,9");
  });

  it("editar a célula dispara o PATCH e em seguida o POST /sessions/{id}/calibration (aplicado rev N)", async () => {
    const { api } = setup();
    const grid = await screen.findByRole("grid");
    fireEvent.keyDown(grid, { key: "7" });
    const input = screen.getByRole("textbox", { name: /Editar/ });
    fireEvent.change(input, { target: { value: "77" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(api.applyToSession).toHaveBeenCalledTimes(1));
    expect(api.patchTable).toHaveBeenCalledTimes(1);
    expect(api.patchTable.mock.invocationCallOrder[0]!).toBeLessThan(api.applyToSession.mock.invocationCallOrder[0]!);
    expect(api.applyToSession).toHaveBeenCalledWith(SESSION_ID, { calibration_id: "cal-0001", version: 7, profile_options: {} });
    await waitFor(() => expect(screen.getByTestId("live-status")).toHaveTextContent("aplicado rev 7"));
  });

  it("Q usa o λ da bancada na célula ao vivo e aplica à sessão", async () => {
    const { telemetry, tick, api } = setup();
    const grid = await screen.findByRole("grid");
    frame(telemetry, { rpm: 3000, map_kpa: 100, lambda_measured: 0.935, lambda_target: 0.85 });
    tick();
    fireEvent.keyDown(grid, { key: "q" });
    await waitFor(() => expect(api.patchTable).toHaveBeenCalled());
    const body = api.patchTable.mock.calls[0]![2] as { cells: { row: number; col: number; value: number }[] };
    expect(body.cells).toEqual([{ row: 4, col: 5, value: 75.9 }]);
    await waitFor(() => expect(api.applyToSession).toHaveBeenCalledTimes(1));
  });

  it("seletor com as tabelas live-tunable (VE, avanço, lambda alvo) e run.state da bancada", async () => {
    const { telemetry } = setup();
    await screen.findByRole("grid");
    const group = screen.getByRole("group", { name: "Tabela em Live Tuning" });
    const labels = within(group).getAllByRole("button").map((b) => b.textContent);
    expect(labels).toEqual(["Mapa principal (VE)", "Avanço de ignição", "Lambda alvo"]);
    expect(within(group).getByRole("button", { name: "Mapa principal (VE)" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(within(group).getByRole("button", { name: "Lambda alvo" }));
    expect(screen.getByRole("grid")).toHaveAccessibleName(/Lambda alvo/);
    act(() => telemetry.ingest({ v: 1, type: "run.state", seq: 99, t_sim_s: 1, payload: { run_id: "r1", state: "running" } } as unknown as TypedEnvelope));
    fireEvent.keyDown(screen.getByRole("grid"), { key: "q" });
    expect(screen.getByText("Quick Tune só atua na tabela VE")).toBeInTheDocument();
  });

  it("erro ao carregar mostra o problema e permite tentar de novo", async () => {
    const api = makeEcuApi({ getSession: vi.fn(() => Promise.reject(new Error("falhou"))) });
    setup(api);
    expect(await screen.findByRole("alert")).toHaveTextContent("falhou");
    fireEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    await waitFor(() => expect(api.getSession).toHaveBeenCalledTimes(2));
  });
});

describe("Tela Dividida (Live Tuning) na bancada (RF-05, T045)", () => {
  async function renderPage(ecu: FakeApi = makeEcuApi()) {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 1920 });
    FakeWebSocket.reset();
    render(
      <MemoryRouter>
        <DynoCockpitView
          sessionId={SESSION_ID}
          deps={{ api: makeApi(), createWebSocket: (url) => new FakeWebSocket(url), createAudioContext: fakeAudioFactory, storage: null, wsOrigin: "http://localhost" }}
          liveTuningDeps={{ api: ecu, storage: localStorage, debounceMs: 5 }}
        />
      </MemoryRouter>,
    );
    await screen.findByTestId("vehicle-name");
  }

  it("o botão alterna o layout; a VE 16×16 aparece ao lado do carro no rolo", async () => {
    await renderPage();
    const button = screen.getByRole("button", { name: "Tela Dividida (Live Tuning)" });
    expect(button).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByTestId("split-layout")).toBeNull();
    expect(screen.getByRole("region", { name: "Dinamômetro" })).toBeInTheDocument();

    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-pressed", "true");
    const split = screen.getByTestId("split-layout");
    expect(within(split).getByRole("region", { name: "Bancada" })).toBeInTheDocument();
    expect(within(split).getByRole("region", { name: "Instrumentos" })).toBeInTheDocument();
    const grid = await within(split).findByRole("grid");
    expect(grid).toHaveAttribute("aria-rowcount", "17");
    expect(grid).toHaveAttribute("aria-colcount", "17");
    expect(screen.queryByRole("region", { name: "Dinamômetro" })).toBeNull();

    fireEvent.click(button);
    expect(screen.queryByTestId("split-layout")).toBeNull();
    expect(screen.getByRole("region", { name: "Dinamômetro" })).toBeInTheDocument();
  });

  it("a tecla L alterna; teclas dentro do editor não disparam os atalhos da bancada", async () => {
    await renderPage();
    fireEvent.keyDown(document.body, { key: "L" });
    const grid = await screen.findByRole("grid");
    expect(screen.getByRole("button", { name: "Tela Dividida (Live Tuning)" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.keyDown(grid, { key: "l" });
    expect(screen.getByTestId("split-layout")).toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: "l" });
    expect(screen.queryByTestId("split-layout")).toBeNull();
  });
});
