/** T186 — acessibilidade da cockpit: aria-live, ordem de foco, atalhos e nenhum flash acima de 3 Hz (RF-21, RF-22, RNF-06). */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AlarmRegion } from "./ConnectionIndicator";
import { FlashLimiter } from "./flashGuard";
import { knockAlarmText } from "./messages";
import { PREFS_KEY, type CockpitPrefs } from "./prefs";
import { ShortcutsDialog, SHORTCUTS } from "./ShortcutsDialog";
import { installCanvasMock } from "./test-utils/mocks";
import { makeApi, openSocket, renderCockpit } from "./test-utils/harness";

vi.mock("uplot", () => import("./test-utils/uplotMock"));

let canvas: ReturnType<typeof installCanvasMock>;
beforeEach(() => {
  canvas = installCanvasMock({ ctx2d: true });
  localStorage.clear();
});
afterEach(() => canvas.spy.mockRestore());

const severeKnock = (seq: number) => ({
  v: 1,
  type: "event.knock",
  seq,
  t_sim_s: 5 + seq / 100,
  payload: { run_id: "r1", cylinder: 2, knock_class: "severe", intensity: 0.95, retard_deg: 4.5, rpm: 5200 },
});

describe("alternativa textual aos alarmes (RF-21)", () => {
  it("com áudio mudo, knock severo gera 'Knock severo, cilindro 2, 4,5° de retardo' em aria-live assertive", async () => {
    localStorage.setItem(PREFS_KEY, JSON.stringify({ version: 1, units: { power: "whp", boost: "bar", temperature: "C", torque: "Nm" }, audio: { enabled: false, muted: true, volume: 0.6 }, visiblePanels: ["dyno"], activeBottomTab: "events" }));
    await renderCockpit(makeApi(), localStorage);
    const ws = openSocket();
    act(() => ws.receive(severeKnock(1)));
    const live = screen.getByTestId("alarm-live");
    expect(live).toHaveAttribute("aria-live", "assertive");
    await waitFor(() => expect(live).toHaveTextContent("Knock severo, cilindro 2, 4,5° de retardo"));
    expect(screen.getByTestId("alarm-banner")).toHaveTextContent("Knock severo, cilindro 2, 4,5° de retardo");
  });

  it("EGT alta, limitador e falha também têm texto", async () => {
    await renderCockpit();
    const ws = openSocket();
    act(() => ws.receive({ v: 1, type: "event.limiter", seq: 2, t_sim_s: 1, payload: { run_id: "r1", kind: "rev_limiter", phase: "hard", active: true, rpm: 7004 } }));
    await waitFor(() => expect(screen.getByTestId("alarm-live")).toHaveTextContent("Limitador de rotação ativo (7004 rpm)"));
    await new Promise((r) => setTimeout(r, 360));
    act(() => ws.receive({ v: 1, type: "telemetry.frame", seq: 3, t_sim_s: 1.1, payload: { session_id: "s", run_id: "r1", frame_index: 1, channels: { egt_c: 960 } } }));
    await waitFor(() => expect(screen.getByTestId("alarm-live")).toHaveTextContent("EGT alta: 960 °C (limite 950 °C)"), { timeout: 2000 });
  });

  it("nenhum flash acima de 3 Hz: rajada de alarmes atualiza o banner no máximo 3 vezes por segundo", () => {
    const limiter = new FlashLimiter(3);
    let flashes = 0;
    for (let t = 0; t < 1000; t += 10) if (limiter.tryFlash(t)) flashes += 1;
    expect(flashes).toBeLessThanOrEqual(3);
    const { container } = render(<AlarmRegion alarms={[{ id: 1, text: knockAlarmText("severe", 2, 4.5, "pt-BR"), severity: "critical" }]} />);
    expect(container.innerHTML).not.toMatch(/animate-(pulse|ping|bounce)|blink/);
  });

  it("na cockpit, 10 knocks severos em 100 ms não mudam o banner mais de 3 vezes em 1 s", async () => {
    await renderCockpit();
    const ws = openSocket();
    const banner = () => screen.queryByTestId("alarm-banner")?.textContent ?? "";
    const seen = new Set<string>();
    for (let i = 0; i < 10; i += 1) {
      act(() => ws.receive({ ...severeKnock(10 + i), payload: { ...severeKnock(10 + i).payload, cylinder: (i % 4) + 1 } }));
      seen.add(banner());
    }
    expect(seen.size).toBeLessThanOrEqual(2);
  });
});

describe("teclado (RF-22)", () => {
  it("'?' abre os atalhos; Esc fecha e o foco fica preso no diálogo", async () => {
    await renderCockpit();
    fireEvent.keyDown(document.body, { key: "?" });
    const dialog = await screen.findByRole("dialog", { name: "Atalhos de teclado" });
    expect(within(dialog).getAllByRole("row")).toHaveLength(SHORTCUTS.length + 1);
    // A tecla L (Tela Dividida, 002 RF-05) aparece na lista (003 T023).
    expect(within(dialog).getByRole("cell", { name: "L" })).toBeInTheDocument();
    const close = within(dialog).getByRole("button", { name: "Fechar" });
    expect(document.activeElement).toBe(close);
    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(document.activeElement).toBe(close);
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("'M' alterna o mudo e persiste em localStorage; 'U' abre unidades; '1'–'4' trocam a aba; 'D' mostra o diagnóstico", async () => {
    await renderCockpit(makeApi(), localStorage);
    fireEvent.keyDown(document.body, { key: "m" });
    await waitFor(() => expect((JSON.parse(localStorage.getItem(PREFS_KEY)!) as CockpitPrefs).audio.muted).toBe(true));
    fireEvent.keyDown(document.body, { key: "M" });
    await waitFor(() => expect((JSON.parse(localStorage.getItem(PREFS_KEY)!) as CockpitPrefs).audio.muted).toBe(false));
    fireEvent.keyDown(document.body, { key: "u" });
    expect(await screen.findByRole("radio", { name: "kW" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "kW" }));
    expect(screen.getByRole("button", { name: /Unidades: kW/ })).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("radio", { name: "kW" }), { key: "Escape" });
    fireEvent.keyDown(document.body, { key: "3" });
    expect(screen.getByRole("tab", { name: /Eventos/ })).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(document.body, { key: "4" });
    expect(screen.getByRole("tab", { name: /Datalogger/ })).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(document.body, { key: "d" });
    expect(screen.getByRole("complementary", { name: "Diagnóstico" })).toBeInTheDocument();
  });

  it("ordem de foco lógica: sem tabindex positivo; barra superior → painéis → controles da puxada", async () => {
    const { container } = await renderCockpit();
    expect(container.querySelectorAll("[tabindex]:not([tabindex='0']):not([tabindex='-1'])")).toHaveLength(0);
    const focusables = [...container.querySelectorAll<HTMLElement>("button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex='0']")];
    const idx = (el: HTMLElement) => focusables.indexOf(el);
    const units = screen.getByRole("button", { name: /Unidades/ });
    const collapseDyno = screen.getByRole("button", { name: /Recolher Dinamômetro/ });
    const runType = screen.getByRole("combobox", { name: "Tipo de puxada" });
    expect(idx(units)).toBeGreaterThanOrEqual(0);
    expect(idx(units)).toBeLessThan(idx(collapseDyno));
    expect(idx(collapseDyno)).toBeLessThan(idx(runType));
    // abas com roving tabindex: setas trocam a aba
    const tab1 = screen.getByRole("tab", { name: /Espectrograma/ });
    fireEvent.keyDown(tab1, { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: /Pressão/ })).toHaveAttribute("aria-selected", "true");
  });

  it("Esc aborta a puxada ativa", async () => {
    const api = makeApi({ abortRun: vi.fn(() => new Promise(() => undefined)) });
    await renderCockpit(api);
    openSocket();
    await waitFor(() => expect(screen.getByRole("button", { name: "Iniciar" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Iniciar" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Abortar" })).toBeEnabled());
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(api.abortRun).toHaveBeenCalled();
  });

  it("ShortcutsDialog documenta todas as teclas da spec", () => {
    render(<ShortcutsDialog onClose={() => undefined} />);
    for (const k of ["Esc", "M", "U", "1–4", "D", "?"]) expect(screen.getByText(k)).toBeInTheDocument();
  });
});
