/** T177 — DynoChart, LambdaEgtChart e CylinderPressureTrace (RF-06, RF-07, RF-10). */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CurvePoint, ReferenceCurve } from "./api";
import { alignXY, clampToScale, limitBandPlugin, overlayPlugin } from "./charts/UPlotChart";
import { CylinderPressureTrace, peakLabel, peakOfTrace, traceToData } from "./CylinderPressureTrace";
import { buildDynoData, buildDynoOptions, DynoChart } from "./DynoChart";
import { buildLambdaEgtData, LambdaEgtChart } from "./LambdaEgtChart";
import { RenderLoop } from "./render/RenderLoop";
import { TelemetryStore } from "./store";
import { frameEnvelope, manualRaf } from "./test-utils/mocks";
import { FakeUPlot } from "./test-utils/uplotMock";
import { parseEnvelope } from "@/lib/ws";

vi.mock("uplot", () => import("./test-utils/uplotMock"));

const curve = (scale = 1): CurvePoint[] =>
  [2000, 3000, 4000, 5000, 6000].map((rpm, i) => ({
    rpm,
    t_sim_s: i,
    power_wheel_kw: (60 + i * 30) * scale,
    torque_engine_nm: 300 + i * 10,
    lambda: 0.85 - i * 0.02,
    egt_c: 700 + i * 60,
  }));

const reference: ReferenceCurve = {
  curve_id: "stock-e27",
  points: [2000, 4000, 6000].map((rpm) => ({ rpm, power_wheel_kw: rpm / 40, torque_crank_nm: 320, lambda_value: 0.86, egt_c: 820 })),
};

beforeEach(() => FakeUPlot.reset());

describe("DynoChart (RF-06)", () => {
  it("eixos duplos com unidades, curvas atuais contínuas e comparação/referência tracejadas", () => {
    const opts = buildDynoOptions({ powerUnit: "whp", rpmRange: [800, 7000], peakRef: { power_kw: 164.1, torque_nm: 350 }, comparisonLabel: "Base", width: 600, height: 300 });
    expect(opts.axes?.[1]).toMatchObject({ label: "Potência (whp)", scale: "power", side: 3 });
    expect(opts.axes?.[2]).toMatchObject({ label: "Torque (N·m)", scale: "torque", side: 1 });
    expect(opts.scales?.power?.range).toEqual([0, expect.closeTo(1.2 * (164.1 / 0.7457), 3)]);
    expect(opts.scales?.torque?.range).toEqual([0, 420]);
    expect(opts.scales?.x?.range).toEqual([800, 7000]);
    const s = opts.series;
    expect(s[1]?.dash).toBeUndefined();
    expect(s[2]?.dash).toBeUndefined();
    expect(s[3]).toMatchObject({ label: "Potência Base", dash: [8, 4] });
    expect(s[4]).toMatchObject({ label: "Torque Base", dash: [8, 4] });
    expect(s[5]?.dash).toEqual([2, 4]);
    expect(s[3]?.stroke).toBe(s[1]?.stroke);
  });

  it("dados alinhados por RPM com conversão de potência", () => {
    const data = buildDynoData(
      { rpm: [2000, 3000], power_kw: [74.57, 149.14], torque_nm: [300, 310] },
      { rpm: [2500], power_kw: [100], torque_nm: [305] },
      null,
      "whp",
    );
    expect(data[0]).toEqual([2000, 2500, 3000]);
    expect(data[1]).toEqual([expect.closeTo(100, 6), null, expect.closeTo(200, 6)]);
    expect(data[3]).toEqual([null, expect.closeTo(100 / 0.7457, 6), null]);
    expect(data[5]).toEqual([null, null, null]);
  });

  it("renderiza com a puxada atual + comparação, legenda, pico e delta de pico em whp", () => {
    render(
      <DynoChart
        finalCurve={curve(1.1)}
        comparison={{ label: "Puxada base", curve: curve(1) }}
        reference={reference}
        powerUnit="whp"
        rpmRange={[800, 7000]}
        peakRef={{ power_kw: 180, torque_nm: 360 }}
      />,
    );
    const u = FakeUPlot.instances.at(-1)!;
    expect(u.opts.series).toHaveLength(7);
    expect((u.data[1] as (number | null)[]).filter((v) => v !== null)).toHaveLength(5);
    expect(screen.getByTestId("dyno-peak")).toHaveTextContent("whp @ 6000 rpm");
    // Δ = (180·1,1 − 180)/0,7457 = 24,1 whp
    expect(screen.getByTestId("dyno-delta").textContent?.replace(/\s/g, "")).toMatch(/\+24[,.]1whp/);
    expect(screen.getByText(/referência/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /potência em whp e torque/ })).toBeInTheDocument();
  });

  it("traço ao vivo pelo RenderLoop a partir do buffer em anel, só quando a versão muda", () => {
    const r = manualRaf();
    const loop = new RenderLoop({ raf: r.raf, caf: r.caf, doc: null });
    const store = new TelemetryStore();
    loop.start();
    render(<DynoChart powerUnit="kW" rpmRange={[800, 7000]} peakRef={{ power_kw: 150, torque_nm: 300 }} store={store} loop={loop} />);
    const u = FakeUPlot.instances.at(-1)!;
    store.ingest(parseEnvelope(frameEnvelope(1, 1, { rpm: 3000, power_kw: 90, torque_nm: 280 }))!);
    act(() => r.tick(16));
    const calls = u.setDataCalls;
    expect(u.data[0]).toEqual([3000]);
    expect(u.data[1]).toEqual([90]);
    act(() => r.tick(32));
    expect(u.setDataCalls).toBe(calls);
    expect(screen.getByText("Curvas de referência indisponíveis")).toBeInTheDocument();
  });

  it("o cursor vertical (evento selecionado) é desenhado pelo plugin de sobreposição", () => {
    const { rerender } = render(<DynoChart finalCurve={curve()} powerUnit="whp" rpmRange={[800, 7000]} peakRef={{ power_kw: 150, torque_nm: 300 }} cursorRpm={null} />);
    const u = FakeUPlot.instances.at(-1)!;
    const redraws = u.redraws;
    rerender(<DynoChart finalCurve={curve()} powerUnit="whp" rpmRange={[800, 7000]} peakRef={{ power_kw: 150, torque_nm: 300 }} cursorRpm={4500} />);
    expect(u.redraws).toBeGreaterThan(redraws);
    expect(() => u.runDrawHooks()).not.toThrow();
  });
});

describe("DynoChart: placar de comparação (003 T024, contraste WCAG AA)", () => {
  it("sem comparação, os cartões vazios não usam opacidade (que derruba o contraste do texto)", () => {
    const { container } = render(<DynoChart finalCurve={curve()} powerUnit="whp" rpmRange={[800, 7000]} peakRef={{ power_kw: 150, torque_nm: 300 }} />);
    expect(screen.getByText("Sem seleção")).toBeInTheDocument();
    const faded = [...container.querySelectorAll<HTMLElement>("[class]")].filter((el) => /(^|\s)opacity-\d+/.test(el.className));
    expect(faded.map((el) => el.className)).toEqual([]);
    expect(screen.getByText("Sem seleção").className).not.toMatch(/text-zinc-(5|6|7)00/);
  });
});

describe("LambdaEgtChart (RF-07)", () => {
  it("escalas lambda 0,60–1,30 e EGT 0–1100 °C com a faixa de EGT máxima em 950 °C (hatch-20t-gdi)", () => {
    render(<LambdaEgtChart finalCurve={curve()} egtLimitC={950} rpmRange={[800, 7000]} reference={reference} />);
    const u = FakeUPlot.instances.at(-1)!;
    expect(u.opts.scales?.lambda?.range).toEqual([0.6, 1.3]);
    expect(u.opts.scales?.egt?.range).toEqual([0, 1100]);
    expect(u.opts.axes?.[2]).toMatchObject({ label: "EGT (°C)", side: 1 });
    expect(screen.getByTestId("egt-limit")).toHaveTextContent("950 °C");
    expect(() => u.runDrawHooks()).not.toThrow();
  });

  it("valores fora da escala ficam presos na borda com marcador 'fora de escala'", () => {
    const hot = curve().map((p, i) => (i === 4 ? { ...p, egt_c: 1180, lambda: 1.45 } : p));
    const res = buildLambdaEgtData({ rpm: hot.map((p) => p.rpm), lambda: hot.map((p) => p.lambda), egt_c: hot.map((p) => p.egt_c) }, null, null);
    expect(res.outOfScale).toBe(true);
    expect(res.data[1]?.[4]).toBe(1.3);
    expect(res.data[2]?.[4]).toBe(1100);
    render(<LambdaEgtChart finalCurve={hot} egtLimitC={950} rpmRange={[800, 7000]} />);
    expect(screen.getByTestId("out-of-scale")).toHaveTextContent("fora de escala");
  });

  it("limitBandPlugin e clampToScale", () => {
    expect(clampToScale(-1, 0, 10)).toEqual({ value: 0, out: true });
    expect(clampToScale(5, 0, 10)).toEqual({ value: 5, out: false });
    const p = limitBandPlugin("egt", 950, 1100, "red", "x");
    const u = new FakeUPlot({ width: 1, height: 1, series: [], plugins: [p, overlayPlugin(() => ({ markers: [{ x: 1, color: "y", label: "l" }], gaps: [{ fromT: 0, toT: null }] }))] }, [[]]);
    expect(() => u.runDrawHooks()).not.toThrow();
    expect(alignXY([null])).toEqual([[], []]);
  });
});

describe("CylinderPressureTrace (RF-10)", () => {
  const trace = (peakDeg: number) => {
    const crank_deg = Array.from({ length: 721 }, (_, i) => i - 360);
    return { cylinder: 1, crank_deg, p_bar: crank_deg.map((d) => 1 + 80 * Math.exp(-(((d - peakDeg) / 25) ** 2))) };
  };

  it("traço sintético com pico em 15° ATDC mostra 'pico 15° ATDC' e eixo −360°…+360°", () => {
    const t = trace(15);
    expect(peakOfTrace(t)?.deg).toBe(15);
    expect(peakLabel(15)).toBe("pico 15° ATDC");
    expect(peakLabel(-4)).toBe("pico 4° BTDC");
    expect(peakLabel(0)).toBe("pico no PMS");
    expect(traceToData(t)[0]).toHaveLength(721);
    render(<CylinderPressureTrace nCyl={4} cylinder={1} onCylinderChange={() => undefined} trace={t} />);
    expect(screen.getByTestId("pressure-peak")).toHaveTextContent("pico 15° ATDC");
    const u = FakeUPlot.instances.at(-1)!;
    expect(u.opts.scales?.x?.range).toEqual([-360, 360]);
    expect(() => u.runDrawHooks()).not.toThrow();
  });

  it("cilindro selecionável entre 1 e n_cyl", () => {
    const onChange = vi.fn();
    render(<CylinderPressureTrace nCyl={6} cylinder={1} onCylinderChange={onChange} trace={null} />);
    const select = screen.getByRole("combobox", { name: "Cilindro do traço de pressão" });
    expect(select.querySelectorAll("option")).toHaveLength(6);
    fireEvent.change(select, { target: { value: "5" } });
    expect(onChange).toHaveBeenCalledWith(5);
    expect(screen.getByText("sem dados de cyl_pressure_trace")).toBeInTheDocument();
  });

  it("lê o traço ao vivo do store a ≤ 10 Hz", () => {
    const r = manualRaf();
    const loop = new RenderLoop({ raf: r.raf, caf: r.caf, doc: null });
    loop.start();
    const store = new TelemetryStore();
    render(<CylinderPressureTrace nCyl={4} cylinder={1} onCylinderChange={() => undefined} store={store} loop={loop} />);
    store.ingest(parseEnvelope(frameEnvelope(1, 1, {}, { cyl_pressure_trace: trace(12) }))!);
    act(() => r.tick(200));
    expect(screen.getByTestId("pressure-peak")).toHaveTextContent("pico 12° ATDC");
  });
});
