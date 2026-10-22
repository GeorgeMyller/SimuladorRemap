/* eslint-disable @typescript-eslint/unbound-method -- asserções sobre vi.fn */
/** T179 — KnockSpectrogram com fallback WebGL2 → WebGL1 → Canvas 2D (RF-09; D-22; EC-08). */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { parseEnvelope } from "@/lib/ws";

import { KnockSpectrogram } from "./KnockSpectrogram";
import { createSurface } from "./render/createSurface";
import { RenderLoop } from "./render/RenderLoop";
import { createCanvas2DRenderer, createWebGLRenderer } from "./render/spectrogramRenderers";
import { BIN_WIDTH_HZ, heatColor, SPECTRUM_BINS, SpectrogramModel } from "./render/SpectrogramModel";
import { TelemetryStore } from "./store";
import { frameEnvelope, installCanvasMock, make2dContext, makeWebGLContext, manualRaf } from "./test-utils/mocks";

/** Espectro sintético: ruído de fundo −70 dB e pico gaussiano em `peakHz`. */
function syntheticSpectrum(peakHz: number) {
  const bins_hz = Array.from({ length: SPECTRUM_BINS }, (_, i) => i * BIN_WIDTH_HZ);
  const magnitude_db = bins_hz.map((f) => -70 + 55 * Math.exp(-(((f - peakHz) / 150) ** 2)));
  return { bins_hz, magnitude_db, resonance_hz: [6720, 11147, 13987, 15334], sensor: "block" };
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("SpectrogramModel", () => {
  it("256 bins de 0 a 20 kHz (78,125 Hz) e janela de 10 s a 50 colunas/s", () => {
    const m = new SpectrogramModel();
    expect(m.bins).toBe(256);
    expect(m.columns).toBe(500);
    expect(BIN_WIDTH_HZ).toBe(78.125);
    expect(m.binsHz[255]).toBeCloseTo(20000 - 78.125);
  });

  it("pico sintético em 6,5 kHz gera a linha de maior intensidade em 6,5 ± 0,2 kHz", () => {
    const m = new SpectrogramModel();
    const s = syntheticSpectrum(6500);
    m.push(s.magnitude_db, s.bins_hz, s.resonance_hz);
    expect(Math.abs(m.peakFrequencyHz()! - 6500)).toBeLessThanOrEqual(200);
    expect(m.resonanceHz[0]).toBe(6720);
  });

  it("anel de colunas e decimação (EC-12)", () => {
    const m = new SpectrogramModel(3, 4);
    m.push([1, 2, 3, 4]);
    m.push([-1, -2, -3, -4]);
    m.push([5, 6, 7, 8]);
    m.push([9, 9, 9, 10]);
    expect(m.filled).toBe(3);
    expect([...m.column(m.latestColumn())]).toEqual([9, 9, 9, 10]);
    m.stride = 2;
    expect(m.push([0, 0, 0, 0])).toBe(false);
    expect(m.push([0, 0, 0, 0])).toBe(true);
    expect(heatColor(0)).toEqual([0, 0, 4]);
    expect(heatColor(1)).toEqual([252, 255, 164]);
  });
});

describe("createSurface", () => {
  it("tenta webgl2, depois webgl, depois 2d", () => {
    let mock = installCanvasMock({ webgl2: true, webgl: true, ctx2d: true });
    expect(createSurface(document.createElement("canvas")).kind).toBe("webgl2");
    mock.spy.mockRestore();
    mock = installCanvasMock({ webgl: true, ctx2d: true });
    expect(createSurface(document.createElement("canvas")).kind).toBe("webgl");
    mock.spy.mockRestore();
    mock = installCanvasMock({ ctx2d: true });
    expect(createSurface(document.createElement("canvas")).kind).toBe("2d");
    mock.spy.mockRestore();
    mock = installCanvasMock({});
    expect(createSurface(document.createElement("canvas")).kind).toBe("none");
    mock.spy.mockRestore();
  });

  it("renderizadores WebGL e 2D desenham sem erro", () => {
    const m = new SpectrogramModel(10, 8);
    m.push([0, -10, -20, -30, -40, -50, -60, -70]);
    const gl = makeWebGLContext();
    const r = createWebGLRenderer(gl, m);
    r.update(m);
    r.redrawAll(m);
    r.dispose();
    expect(gl.drawArrays).toHaveBeenCalled();
    const canvas = document.createElement("canvas");
    canvas.width = 20;
    canvas.height = 8;
    const ctx = make2dContext();
    const r2 = createCanvas2DRenderer(ctx, canvas);
    r2.update(m);
    r2.redrawAll(m);
    expect(ctx.putImageData).toHaveBeenCalled();
  });
});

describe("KnockSpectrogram", () => {
  function setup() {
    const r = manualRaf();
    const loop = new RenderLoop({ raf: r.raf, caf: r.caf, doc: null });
    loop.start();
    const store = new TelemetryStore();
    return { r, loop, store };
  }

  it("com WebGL2 usa a textura e não mostra 'modo compatível'", async () => {
    const mock = installCanvasMock({ webgl2: true, webgl: true, ctx2d: true });
    const { loop, store } = setup();
    render(<KnockSpectrogram store={store} loop={loop} nCyl={4} />);
    await waitFor(() => expect(screen.getByRole("img", { name: /Espectrograma/ })).toHaveAttribute("data-surface", "webgl2"));
    expect(screen.queryByTestId("compat-badge")).toBeNull();
    mock.spy.mockRestore();
  });

  it("sem WebGL usa Canvas 2D com o selo 'modo compatível' e marca as ressonâncias", async () => {
    const mock = installCanvasMock({ ctx2d: true });
    const { r, loop, store } = setup();
    render(<KnockSpectrogram store={store} loop={loop} nCyl={4} />);
    await waitFor(() => expect(screen.getByTestId("compat-badge")).toHaveTextContent("modo compatível"));
    store.ingest(parseEnvelope(frameEnvelope(1, 1, { knock_intensity_cyl3: 0.41 }, { knock_spectrum: syntheticSpectrum(6500) }))!);
    act(() => r.tick(300));
    expect(screen.getByTestId("spectrum-peak").textContent).toMatch(/6[,.]4|6[,.]5|6[,.]6/);
    expect(screen.getAllByTestId("resonance-marker")).toHaveLength(4);
    expect(screen.getByText(/c3 0[,.]41/)).toBeInTheDocument();
    mock.spy.mockRestore();
  });

  it("contexto WebGL perdido cai para Canvas 2D sem recarregar (EC-08)", async () => {
    const mock = installCanvasMock({ webgl2: true, ctx2d: true });
    const { loop, store } = setup();
    render(<KnockSpectrogram store={store} loop={loop} nCyl={4} />);
    const canvas = await screen.findByRole("img", { name: /Espectrograma/ });
    await waitFor(() => expect(canvas).toHaveAttribute("data-surface", "webgl2"));
    act(() => {
      fireEvent(canvas, new Event("webglcontextlost", { cancelable: true }));
    });
    await waitFor(() => expect(screen.getByTestId("compat-badge")).toBeInTheDocument());
    expect(screen.getByRole("img", { name: /Espectrograma/ })).toHaveAttribute("data-surface", "2d");
    mock.spy.mockRestore();
  });
});
