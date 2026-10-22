"""Analyst: metrics.json + metricas.html; timeline.json + timeline.html (fonte: progress.jsonl e artefatos)."""
import json
import os
import re
from collections import Counter, defaultdict
from common import DATA, ROOT, load_json, save_json, render, write_page, register, now

AGENT = "reversa-docs-analyst"
mods = load_json(os.path.join(DATA, "modules.json"))["modules"]
deps = load_json(os.path.join(DATA, "deps.json"))
code = [m for m in mods if m["type"] == "code"]

agg = defaultdict(lambda: {"loc": 0, "modules": 0, "tests_loc": 0, "test_files": 0})
for m in mods:
    if m["layer"] == "backend-tests":
        continue
    a = agg[m["folder"]]
    if m["type"] == "code":
        a["loc"] += m["loc"]; a["modules"] += 1
    else:
        a["tests_loc"] += m["loc"]; a["test_files"] += 1
for m in mods:
    if m["layer"] == "backend-tests":
        a = agg["backend/" + m["package"]] if ("backend/" + m["package"]) in agg else None
        if a is not None:
            a["tests_loc"] += m["loc"]; a["test_files"] += 1

treemap = [{"folder": k, "layer": k.split("/")[0], "loc": v["loc"], "modules": v["modules"],
            "tests_loc": v["tests_loc"], "test_files": v["test_files"]}
           for k, v in sorted(agg.items()) if v["loc"] > 20]
top = sorted(code, key=lambda m: -m["complexity"])[:20]
bins = [0, 50, 100, 200, 500, 1000, 5000]
counts = [0] * (len(bins) - 1)
for m in code:
    for i in range(len(bins) - 1):
        if bins[i] <= m["loc"] < bins[i + 1]:
            counts[i] += 1
            break
def pk(folder):
    layer, name = folder.split("/")
    return "rs." + name if layer == "native" else name


links = [{"source": "usa: " + pk(e["from"]), "target": "provê: " + pk(e["to"]), "value": e["weight"],
          "layer": e["from"].split("/")[0]}
         for e in deps["edges"] if e["from"] not in ("frontend/root",)]
lang = defaultdict(lambda: {"modules": 0, "loc": 0})
for m in mods:
    lang[(m["language"], m["type"])]["modules"] += 1
    lang[(m["language"], m["type"])]["loc"] += m["loc"]

# Testes declarados, contados no código atual (def test_ no pytest; it( e test( no vitest/Playwright)
PY_T = re.compile(r"^\s*(?:async\s+)?def\s+test_", re.M)
TS_T = re.compile(r"(?<![\w.])(?:it|test)\s*\(\s*[\"'`]")
decl_be, decl_fe = Counter(), Counter()
for m in mods:
    if m["type"] != "test":
        continue
    text = open(os.path.join(ROOT, m["name"]), encoding="utf-8", errors="replace").read()
    if m["layer"] == "backend-tests":
        decl_be[m["package"]] += len(PY_T.findall(text))
    elif m["layer"] == "frontend":
        decl_fe[m["package"]] += len(TS_T.findall(text))
decl_be = {k: v for k, v in sorted(decl_be.items()) if v and k != "_root"}
decl_fe = {k: v for k, v in sorted(decl_fe.items()) if v and k not in ("test", "root")}
rs_loc = sum(m["loc"] for m in code if m["layer"] == "native")

metrics = {
    "schemaVersion": 1, "generatedAt": now(),
    "treemap_loc_by_folder": treemap,
    "top_complexity": [{"id": m["name"], "complexity": m["complexity"], "loc": m["loc"], "folder": m["folder"]} for m in top],
    "loc_histogram": {"bins": bins, "counts": counts},
    "dependency_sankey": {"links": links},
    "language_distribution": [{"language": k[0], "type": k[1], **v} for k, v in sorted(lang.items())],
    "coverage": {
        "source": "make cov (scripts/coverage_per_package.py), mínimo COV_MIN = 85 %", "min": 85,
        "global_coverage_json": 95.71,
        "packages": [{"package": p, "pct": v} for p, v in [
            ("core", 96.02), ("physics", 97.40), ("damage", 95.44), ("catalog", 96.48), ("dyno", 95.34), ("ecu", 99.10),
            ("profiles", 97.65), ("telemetry", 94.38), ("scenarios", 90.80), ("career", 92.70), ("api", 92.81), ("db", 98.63)]]},
    "tests": {
        "backend": {"passed_002": 2128, "skipped_002": 35, "note": "Na 003: -m accuracy 9/9 com nativo ligado e desligado; -m e2e 49 aprovados; tests/native, tests/qa e tests/bench novos"},
        "frontend": {"passed": 627, "runner": "vitest"},
        "e2e": {"playwright_specs": 14, "new_specs_003": 8, "passed_003": "24+ aprovados (live-tuning e native-engine 4/4)", "result_001": "7/7 (3 jornadas, axe 0 violações A/AA, cockpit 60 FPS)"},
        "mypy": {"command": "mypy --strict src tests", "errors": 0, "files": 440},
        "history": [{"label": "Fecho da 001", "backend": 2035, "frontend": 450}, {"label": "Fecho da 002", "backend": 2128, "frontend": 571},
                    {"label": "Fecho da 003", "backend": None, "frontend": 627, "note": "contagem total do pytest não registrada na 003"}],
        "declared_backend": decl_be,
        "declared_frontend": decl_fe,
    },
    "accuracy": {"limit_pct": 5, "benchmark": "Reference Benchmark Baseline v1", "metric": "desvio máximo de torque por ponto de RPM",
                 "vehicles": [{"vehicle": "Hatch 2.0 turbo GDI (hatch-20t-gdi)", "pct": 3.4}, {"vehicle": "Coupé 3.0 I6 turbo (coupe-30t-i6)", "pct": 1.4},
                              {"vehicle": "Clássico 2.0 turbo swap (classic-20t-swap)", "pct": 2.3}, {"vehicle": "V8 supercharged (muscle-v8-sc)", "pct": 3.5}]},
    "chunks": {"limit_kb": 500,
               "before": [{"chunk": "Table3DSurface", "kb": 530.3}, {"chunk": "index (entrada)", "kb": 346.6}, {"chunk": "DynoCockpitPage", "kb": 158.6},
                          {"chunk": "EcuWorkspacePage", "kb": 141.1}, {"chunk": "ScenariosPage", "kb": 38.4}],
               "after": [{"chunk": "vendor-three", "kb": 352.3}, {"chunk": "vendor-react", "kb": 180.4}, {"chunk": "vendor-three-core", "kb": 176.9},
                         {"chunk": "DynoCockpitPage", "kb": 128.2}, {"chunk": "vendor-zod", "kb": 94.4}, {"chunk": "useWorkspaceStore", "kb": 86.1},
                         {"chunk": "EcuWorkspacePage", "kb": 74.0}, {"chunk": "HomePage", "kb": 67.6}, {"chunk": "vendor-uplot", "kb": 51.0},
                         {"chunk": "ScenariosPage", "kb": 38.5}, {"chunk": "WorkshopPage", "kb": 15.9}, {"chunk": "index (entrada)", "kb": 9.5}]},
    "physics_loop": {"hz": 1000, "tick_us_python": 179, "tick_us_native": 107, "p99_us_python": 490, "p99_us_native": 345,
                     "note": "hatch, hardware de desenvolvimento (Apple Silicon); sem medição no hardware de referência de 4 núcleos"},
    "native": {
        "source": "backend/tests/bench/test_bench_native_tick.py e legacy-impact.md da 003",
        "speedup_physics": 2.8,
        "subsystems_us": [{"name": "Física (hatch)", "python": 104.8, "native": 38.0},
                          {"name": "ECU", "python": 27.5, "native": 19.8},
                          {"name": "Dano", "python": 48.0, "native": 7.5}],
        "tick_by_vehicle_us": [{"vehicle": "Hatch 2.0 turbo GDI", "python": 179, "native": 107},
                               {"vehicle": "Coupé 3.0 I6 turbo", "python": 159, "native": 93},
                               {"vehicle": "Clássico 2.0 turbo swap", "python": 158, "native": 97},
                               {"vehicle": "V8 supercharged", "python": 192, "native": 106}],
        "overrun": {"sweep_pull_windows": 0, "vehicles": 4, "multi_pull_cooling_before_pct": [3.9, 11.5], "multi_pull_cooling_after_pct": 0},
        "rust_loc": rs_loc,
    },
    "qa_physics": {
        "surge_full_load_pct": [{"vehicle": "Hatch 2.0 turbo GDI", "before": 17.2, "after": 1.4},
                                {"vehicle": "Coupé 3.0 I6 turbo", "before": 10.6, "after": 0.6},
                                {"vehicle": "Clássico 2.0 turbo swap", "before": 18.8, "after": 0.1}],
        "surge_limit_pct": 2,
        "hatch_torque_oscillation_nm": {"before": 12.3, "after": 0.44, "freq_hz": 7.5, "limit": 5},
        "hatch_stock_whp": {"before": 216.3, "after": 214.7},
    },
    "audio": {"band_hz": [1000, 4000], "limit_pct": 5, "max_pct": 2.2,
              "chain": ["pulsos de combustão", "WaveShaper", "lowpass 180→1400 Hz", "ressonadores 90–140 e 280–450 Hz", "sub-bass", "corte de presença 1–4 kHz"]},
    "qa": {"scenarios_approved": 7, "scenarios_total": 7, "career_orders_paid": 7, "career_orders_total": 7},
}
save_json(os.path.join(DATA, "metrics.json"), metrics)

be_loc = sum(m["loc"] for m in code if m["layer"] == "backend")
assert rs_loc > 0
fe_loc = sum(m["loc"] for m in code if m["layer"] == "frontend")
test_loc = sum(m["loc"] for m in mods if m["type"] == "test")

def br(n):
    return f"{n:,}".replace(",", ".")


payload = f"""
<h1>Métricas</h1>
<p class="lead">Tamanho do código, qualidade e desempenho no fecho da feature 003. Contagens de linhas vêm da leitura estática do código
(linhas não vazias, sem comentários). Testes, benchmarks do tick, QA de física e áudio vêm dos relatórios de verificação das features.</p>
<h2>Motor nativo (feature 003)</h2>
<div class="grid g4" id="kpis-native">
  <div class="card kpi"><div class="v">2,8×</div><div class="l">física mais rápida</div><div class="s">hatch: 104,8 → 38,0 µs por tick</div></div>
  <div class="card kpi"><div class="v">179 → 107 µs</div><div class="l">tick médio do hatch</div><div class="s">P99 490 → 345 µs; orçamento 1000 µs</div></div>
  <div class="card kpi"><div class="v">−28 %</div><div class="l">ECU por tick</div><div class="s">27,5 → 19,8 µs</div></div>
  <div class="card kpi"><div class="v">−84 %</div><div class="l">dano por tick</div><div class="s">48,0 → 7,5 µs</div></div>
  <div class="card kpi"><div class="v">0</div><div class="l">janelas com overrun no sweep_pull</div><div class="s">nos 4 veículos</div></div>
  <div class="card kpi"><div class="v">3,9–11,5 % → 0 %</div><div class="l">overrun no arrefecimento do multi_pull</div><div class="s">orçamento de parede declarado (FX1)</div></div>
  <div class="card kpi"><div class="v">9/9</div><div class="l">-m accuracy</div><div class="s">com nativo ligado e desligado</div></div>
  <div class="card kpi"><div class="v">{br(rs_loc)}</div><div class="l">LOC de Rust</div><div class="s">crate simremap_rs, {sum(1 for m in code if m['layer']=='native')} arquivos</div></div>
</div>
<h2>QA de física, áudio e fluxos</h2>
<div class="grid g4" id="kpis-qa">
  <div class="card kpi"><div class="v">17,2 → 1,4 %</div><div class="l">surge a plena carga no hatch</div><div class="s">coupé 10,6 → 0,6; clássico 18,8 → 0,1</div></div>
  <div class="card kpi"><div class="v">±12,3 → ±0,44</div><div class="l">oscilação de torque do hatch (N·m)</div><div class="s">ciclo-limite PID de 7,5 Hz eliminado</div></div>
  <div class="card kpi"><div class="v">2,2 %</div><div class="l">maior energia de áudio em 1–4 kHz</div><div class="s">limite 5 % nos 4 arquétipos</div></div>
  <div class="card kpi"><div class="v">7/7 · 7/7</div><div class="l">cenários aprovados · ordens pagas</div><div class="s">com acerto real (tests/qa)</div></div>
</div>
<h2>Código e testes</h2>
<div class="grid g4" id="kpis">
  <div class="card kpi"><div class="v">{br(be_loc)}</div><div class="l">LOC de código no backend</div><div class="s">{sum(1 for m in code if m['layer']=='backend')} arquivos Python</div></div>
  <div class="card kpi"><div class="v">{br(fe_loc)}</div><div class="l">LOC de código no frontend</div><div class="s">{sum(1 for m in code if m['layer']=='frontend')} arquivos TypeScript</div></div>
  <div class="card kpi"><div class="v">627</div><div class="l">testes do frontend aprovados</div><div class="s">vitest (571 na 002)</div></div>
  <div class="card kpi"><div class="v">24+</div><div class="l">testes Playwright aprovados</div><div class="s">14 specs; live-tuning e native-engine 4/4</div></div>
  <div class="card kpi"><div class="v">49</div><div class="l">testes -m e2e do backend</div><div class="s">aprovados na 003</div></div>
  <div class="card kpi"><div class="v">0 erros</div><div class="l">mypy --strict src tests</div><div class="s">440 arquivos; make type limpo</div></div>
  <div class="card kpi"><div class="v">{br(test_loc)}</div><div class="l">LOC de testes</div><div class="s">backend e frontend, inclui e2e</div></div>
  <div class="card kpi"><div class="v">95,71 %</div><div class="l">cobertura global do backend</div><div class="s">medição da 002; mínimo por pacote 85 %</div></div>
</div>
"""
payload += """
<div class="grid g2" style="margin-top:16px">
  <div class="chart-card"><div id="c-native-tick" class="chart"></div></div>
  <div class="chart-card"><div id="c-native-sub" class="chart"></div></div>
  <div class="chart-card"><div id="c-surge" class="chart"></div></div>
  <div class="chart-card"><div id="c-p99" class="chart"></div></div>
  <div class="chart-card"><div id="c-treemap" class="chart"></div></div>
  <div class="chart-card"><div id="c-coverage" class="chart"></div></div>
  <div class="chart-card"><div id="c-accuracy" class="chart"></div></div>
  <div class="chart-card"><div id="c-chunks" class="chart" style="min-height:420px"></div></div>
  <div class="chart-card"><div id="c-tests" class="chart"></div></div>
  <div class="chart-card"><div id="c-history" class="chart"></div></div>
  <div class="chart-card"><div id="c-hist" class="chart"></div></div>
  <div class="chart-card"><div id="c-complex" class="chart" style="min-height:520px"></div></div>
</div>
<div class="chart-card" style="margin-top:16px"><div id="c-sankey" style="min-height:760px"></div></div>
<h2>Tabela por pacote</h2>
<div class="table-wrap"><table id="t-pkg"><thead><tr><th>Pacote</th><th class="num">Arquivos</th><th class="num">LOC código</th><th class="num">LOC testes</th><th class="num">Cobertura</th></tr></thead><tbody></tbody></table></div>
<p class="muted">Cobertura existe só para pacotes do backend. "Testes declarados" contam funções <code>def test_</code> e chamadas <code>it(</code>/<code>test(</code>; o número executado é maior por causa da parametrização.</p>
"""

script = r"""
<script>
(function () {
  "use strict";
  if (typeof Highcharts === "undefined") { document.getElementById("c-treemap").outerHTML = '<div class="reversa-error-panel">Highcharts não encontrado em assets/vendor/.</div>'; return; }
  var M = (window.RV_DATA && window.RV_DATA.metrics) || {};
  var S = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];
  var INK = "#1e2937", INK2 = "#4a5463", GRID = "#e6e2d9";
  Highcharts.setOptions({
    lang: { decimalPoint: ",", thousandsSep: ".", contextButtonTitle: "Exportar", downloadPNG: "Baixar PNG", downloadSVG: "Baixar SVG", viewFullscreen: "Tela cheia", exitFullscreen: "Sair da tela cheia", printChart: "Imprimir" },
    colors: S,
    chart: { backgroundColor: "#fcfcfb", style: { fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif" }, spacing: [14, 14, 14, 14] },
    title: { align: "left", style: { fontSize: "15px", fontWeight: "600", color: INK } },
    subtitle: { align: "left", style: { color: INK2, fontSize: "12.5px" } },
    xAxis: { lineColor: GRID, tickColor: GRID, labels: { style: { color: INK2 } } },
    yAxis: { gridLineColor: GRID, labels: { style: { color: INK2 } }, title: { style: { color: INK2 } } },
    legend: { itemStyle: { color: INK2, fontWeight: "500" } },
    tooltip: { backgroundColor: "#1e2937", borderWidth: 0, style: { color: "#f5f3ee" } },
    plotOptions: { series: { animation: { duration: 500 } }, bar: { borderRadius: 4, borderWidth: 0, pointPadding: 0.08, groupPadding: 0.1 }, column: { borderRadius: 4, borderWidth: 0 } },
    credits: { enabled: false },
    exporting: { buttons: { contextButton: { menuItems: ["viewFullscreen", "downloadPNG", "downloadSVG"] } } }
  });
  var N = M.native || {}, Q = M.qa_physics || {}, PL = M.physics_loop || {};
  var tv = N.tick_by_vehicle_us || [];
  Highcharts.chart("c-native-tick", {
    chart: { type: "bar" }, title: { text: "Tick médio por veículo: Python × Rust" }, subtitle: { text: "Microssegundos por tick a 1000 Hz (orçamento de 1000 µs); benchmark da 003" },
    xAxis: { categories: tv.map(function (d) { return d.vehicle; }) }, yAxis: { min: 0, title: { text: "µs por tick" } },
    series: [{ name: "Python (referência)", color: "#3d4a5c", data: tv.map(function (d) { return d.python; }) }, { name: "Rust (simremap_rs)", color: "#8a5a2b", data: tv.map(function (d) { return d.native; }) }],
    plotOptions: { bar: { dataLabels: { enabled: true, format: "{y} µs", style: { textOutline: "none", color: INK, fontWeight: "400" } } } },
    tooltip: { shared: true, valueSuffix: " µs" }
  });
  var sb = N.subsystems_us || [];
  Highcharts.chart("c-native-sub", {
    chart: { type: "column" }, title: { text: "Custo por subsistema no tick" }, subtitle: { text: "Física 2,8× mais rápida; ECU −28 %; dano −84 %" },
    xAxis: { categories: sb.map(function (d) { return d.name; }) }, yAxis: { min: 0, title: { text: "µs por tick" } },
    series: [{ name: "Python", color: "#3d4a5c", data: sb.map(function (d) { return d.python; }) }, { name: "Rust", color: "#8a5a2b", data: sb.map(function (d) { return d.native; }) }],
    plotOptions: { column: { dataLabels: { enabled: true, format: "{y:.1f}", style: { textOutline: "none", color: INK, fontWeight: "400" } } } },
    tooltip: { shared: true, valueSuffix: " µs", valueDecimals: 1 }
  });
  var sg = Q.surge_full_load_pct || [];
  Highcharts.chart("c-surge", {
    chart: { type: "column" }, title: { text: "Surge do compressor a plena carga (série)" }, subtitle: { text: "Fração do tempo em surge antes e depois da correção FX3 (linha de surge com recuo em baixa rotação)" },
    xAxis: { categories: sg.map(function (d) { return d.vehicle; }) }, yAxis: { min: 0, title: { text: "% do tempo" }, plotLines: [{ value: Q.surge_limit_pct || 2, color: "#c62f2e", width: 2, dashStyle: "Dash", zIndex: 5, label: { text: "vigilância W323: 2 %", style: { color: "#c62f2e" } } }] },
    series: [{ name: "Antes", color: S[1], data: sg.map(function (d) { return d.before; }) }, { name: "Depois", color: S[2], data: sg.map(function (d) { return d.after; }) }],
    plotOptions: { column: { dataLabels: { enabled: true, format: "{y:.1f} %", style: { textOutline: "none", color: INK, fontWeight: "400" } } } },
    tooltip: { shared: true, valueSuffix: " %" }
  });
  Highcharts.chart("c-p99", {
    chart: { type: "column" }, title: { text: "Latência do tick do hatch: média e P99" }, subtitle: { text: "Microssegundos; sem worker.overrun no sweep_pull dos 4 veículos" },
    xAxis: { categories: ["Tick médio", "P99"] }, yAxis: { min: 0, title: { text: "µs" }, plotLines: [{ value: 1000, color: "#c62f2e", width: 2, dashStyle: "Dash", zIndex: 5, label: { text: "orçamento 1000 µs", style: { color: "#c62f2e" } } }], max: 1050 },
    series: [{ name: "Python", color: "#3d4a5c", data: [PL.tick_us_python, PL.p99_us_python] }, { name: "Rust", color: "#8a5a2b", data: [PL.tick_us_native, PL.p99_us_native] }],
    plotOptions: { column: { dataLabels: { enabled: true, format: "{y} µs", style: { textOutline: "none", color: INK, fontWeight: "400" } } } },
    tooltip: { shared: true, valueSuffix: " µs" }
  });
  var tm = M.treemap_loc_by_folder || [];
  Highcharts.chart("c-treemap", {
    title: { text: "Linhas de código por pacote" }, subtitle: { text: "Área proporcional à LOC; agrupado por camada" },
    series: [{ type: "treemap", layoutAlgorithm: "squarified", alternateStartingDirection: true, borderColor: "#fcfcfb", borderWidth: 2,
      levels: [{ level: 1, dataLabels: { enabled: true, align: "left", verticalAlign: "top", style: { fontSize: "13px", fontWeight: "700", textOutline: "none", color: "#fff" } }, borderWidth: 4 },
               { level: 2, dataLabels: { enabled: true, style: { fontSize: "11px", fontWeight: "500", textOutline: "none", color: "#fff" } } }],
      data: [{ id: "backend", name: "backend", color: "#3d4a5c" }, { id: "frontend", name: "frontend", color: "#2a78d6" }, { id: "native", name: "native (Rust)", color: "#8a5a2b" }].concat(
        tm.map(function (d) { return { name: d.folder.split("/")[1], parent: d.layer, value: d.loc, modules: d.modules }; })) }],
    tooltip: { pointFormat: "<b>{point.name}</b>: {point.value} LOC<br>{point.modules} arquivos" }
  });
  var cov = (M.coverage && M.coverage.packages) || [];
  cov = cov.slice().sort(function (a, b) { return b.pct - a.pct; });
  Highcharts.chart("c-coverage", {
    chart: { type: "bar" }, title: { text: "Cobertura de testes por pacote do backend" }, subtitle: { text: "Portão make cov exige no mínimo 85 % por pacote" },
    xAxis: { categories: cov.map(function (d) { return d.package; }) },
    yAxis: { min: 80, max: 100, title: { text: "%" }, plotLines: [{ value: 85, color: "#c62f2e", width: 2, dashStyle: "Dash", zIndex: 5, label: { text: "mínimo 85 %", style: { color: "#c62f2e" } } }] },
    legend: { enabled: false },
    series: [{ name: "Cobertura", color: S[0], data: cov.map(function (d) { return d.pct; }), dataLabels: { enabled: true, format: "{y:.2f} %", style: { textOutline: "none", color: INK, fontWeight: "500" } } }],
    tooltip: { valueSuffix: " %", valueDecimals: 2 }
  });
  var acc = (M.accuracy && M.accuracy.vehicles) || [];
  Highcharts.chart("c-accuracy", {
    chart: { type: "bar" }, title: { text: "Precisão da física contra o benchmark" }, subtitle: { text: "Desvio máximo de torque por ponto de RPM, Reference Benchmark Baseline v1" },
    xAxis: { categories: acc.map(function (d) { return d.vehicle; }) },
    yAxis: { min: 0, max: 6, title: { text: "desvio (%)" }, plotLines: [{ value: 5, color: "#c62f2e", width: 2, dashStyle: "Dash", zIndex: 5, label: { text: "limite 5 %", style: { color: "#c62f2e" } } }] },
    legend: { enabled: false },
    series: [{ name: "Desvio", color: S[2], data: acc.map(function (d) { return d.pct; }), dataLabels: { enabled: true, format: "{y:.1f} %", style: { textOutline: "none", color: INK } } }],
    tooltip: { valueSuffix: " %" }
  });
  var ch = M.chunks || { before: [], after: [] };
  var names = []; ch.after.concat(ch.before).forEach(function (d) { if (names.indexOf(d.chunk) < 0) names.push(d.chunk); });
  function byName(list) { var o = {}; list.forEach(function (d) { o[d.chunk] = d.kb; }); return names.map(function (n) { return o[n] === undefined ? null : o[n]; }); }
  Highcharts.chart("c-chunks", {
    chart: { type: "bar" }, title: { text: "Chunks JavaScript do build" }, subtitle: { text: "Fecho da 001 e depois do code-splitting da 002 (medição da 002); limite de 500 kB" },
    xAxis: { categories: names, labels: { style: { fontSize: "10.5px" } } },
    yAxis: { min: 0, title: { text: "kB" }, plotLines: [{ value: 500, color: "#c62f2e", width: 2, dashStyle: "Dash", zIndex: 5, label: { text: "limite 500 kB", style: { color: "#c62f2e" } } }] },
    series: [{ name: "Antes (001)", color: S[1], data: byName(ch.before) }, { name: "Depois (002)", color: S[0], data: byName(ch.after) }],
    plotOptions: { bar: { dataLabels: { enabled: true, format: "{y:.0f}", style: { textOutline: "none", color: INK, fontWeight: "400", fontSize: "10.5px" } } } },
    tooltip: { shared: true, valueSuffix: " kB", valueDecimals: 1 }
  });
  var db = (M.tests && M.tests.declared_backend) || {}, df = (M.tests && M.tests.declared_frontend) || {};
  var tcat = Object.keys(db).map(function (k) { return "backend/" + k; }).concat(Object.keys(df).map(function (k) { return "frontend/" + k; }));
  Highcharts.chart("c-tests", {
    chart: { type: "column" }, title: { text: "Testes declarados por pasta" }, subtitle: { text: "Contados no código atual; parametrização aumenta o total executado. frontend/e2e = Playwright" },
    xAxis: { categories: tcat, labels: { rotation: -45, style: { fontSize: "10.5px" } } }, yAxis: { title: { text: "testes declarados" } },
    legend: { enabled: false },
    series: [{ name: "Testes", data: tcat.map(function (c) { var p = c.split("/"); var nw = ["native", "qa", "bench", "e2e"].indexOf(p[1]) >= 0; return { y: (p[0] === "backend" ? db : df)[p[1]], color: nw ? "#6250d6" : (p[0] === "backend" ? "#3d4a5c" : S[0]) }; }) }]
  });
  var hist = (M.tests && M.tests.history) || [];
  Highcharts.chart("c-history", {
    chart: { type: "column" }, title: { text: "Testes aprovados por fecho de feature" }, subtitle: { text: "Backend (pytest) e frontend (vitest). Na 003 o total do pytest não foi registrado" },
    xAxis: { categories: hist.map(function (h) { return h.label; }) }, yAxis: { title: { text: "testes aprovados" } },
    series: [{ name: "Backend", color: "#3d4a5c", data: hist.map(function (h) { return h.backend; }) }, { name: "Frontend", color: S[0], data: hist.map(function (h) { return h.frontend; }) }],
    plotOptions: { column: { dataLabels: { enabled: true, style: { textOutline: "none", color: INK } } } }
  });
  var lh = M.loc_histogram || { bins: [], counts: [] };
  Highcharts.chart("c-hist", {
    chart: { type: "column" }, title: { text: "Distribuição do tamanho dos arquivos de código" }, subtitle: { text: "Número de arquivos por faixa de LOC" },
    xAxis: { categories: lh.counts.map(function (_, i) { return lh.bins[i] + " a " + (lh.bins[i + 1] - 1); }), title: { text: "LOC" } },
    yAxis: { title: { text: "arquivos" } }, legend: { enabled: false },
    series: [{ name: "Arquivos", color: S[0], data: lh.counts, dataLabels: { enabled: true, style: { textOutline: "none", color: INK } } }],
    plotOptions: { column: { pointPadding: 0, groupPadding: 0.02 } }
  });
  var tc = M.top_complexity || [];
  Highcharts.chart("c-complex", {
    chart: { type: "bar" }, title: { text: "Top 20 arquivos por complexidade aproximada" }, subtitle: { text: "Contagem de ramificações (if, for, while, case, operadores lógicos)" },
    xAxis: { categories: tc.map(function (d) { return d.id.replace("backend/src/simremap/", "").replace("frontend/src/features/", "fe/").replace("backend/rust/simremap_rs/src/", "rs/"); }), labels: { style: { fontSize: "10.5px" } } },
    yAxis: { title: { text: "complexidade" } }, legend: { enabled: false },
    series: [{ name: "Complexidade", data: tc.map(function (d) { return { y: d.complexity, loc: d.loc, color: d.folder.indexOf("frontend") === 0 ? S[0] : (d.folder.indexOf("native") === 0 ? "#8a5a2b" : "#3d4a5c") }; }) }],
    tooltip: { pointFormat: "complexidade {point.y}<br>{point.loc} LOC" }
  });
  var lk = (M.dependency_sankey && M.dependency_sankey.links) || [];
  Highcharts.chart("c-sankey", {
    title: { text: "Fluxo de dependências entre pacotes" }, subtitle: { text: "Esquerda: pacote que importa. Direita: pacote importado. Largura = arquivos que importam" },
    series: [{ type: "sankey", name: "Dependências", keys: ["from", "to", "weight"], nodePadding: 6, curveFactor: 0.4,
      data: lk.map(function (l) { return [l.source, l.target, l.value]; }),
      nodes: Array.from(new Set(lk.map(function (l) { return l.source; }).concat(lk.map(function (l) { return l.target; })))).map(function (id) {
        var isFe = lk.some(function (l) { return (l.source === id || l.target === id) && l.layer === "frontend"; });
        var n = id.split(": ")[1];
        var isNew = n === "career" || n === "workshop";
        var isRs = n.indexOf("rs.") === 0;
        return { id: id, color: isRs ? "#8a5a2b" : (isNew ? S[1] : (isFe ? S[0] : "#3d4a5c")) };
      }),
      dataLabels: { style: { textOutline: "none", color: INK, fontWeight: "500" } } }],
    tooltip: { pointFormat: "{point.fromNode.name} → {point.toNode.name}: {point.weight} arquivos", nodeFormat: "{point.name}: {point.sum} arquivos" }
  });
  var covMap = {}; ((M.coverage && M.coverage.packages) || []).forEach(function (c) { covMap["backend/" + c.package] = c.pct; });
  var tb = document.querySelector("#t-pkg tbody");
  tm.forEach(function (d) {
    var tr = document.createElement("tr");
    tr.innerHTML = "<td class=mono>" + d.folder + "</td><td class=num>" + d.modules + "</td><td class=num>" + d.loc.toLocaleString("pt-BR") +
      "</td><td class=num>" + d.tests_loc.toLocaleString("pt-BR") + "</td><td class=num>" + (covMap[d.folder] ? covMap[d.folder].toFixed(2).replace(".", ",") + " %" : "n/d") + "</td>";
    tb.appendChild(tr);
  });
})();
</script>
"""
HC = "\n".join(f'<script src="assets/vendor/{f}"></script>' for f in
               ["highcharts.js", "highcharts-accessibility.js", "highcharts-exporting.js", "highcharts-treemap.js", "highcharts-sankey.js"])
write_page("metricas.html", render("metricas", "Métricas", payload, AGENT, "metricas", head=HC, scripts=script))

# Timeline (sem chronicle.md: fonte são progress.jsonl e os artefatos datados)
EV = [
    ("2026-10-17T23:20:42Z", "Brief inicial", "Ideação", "/reversa-new registra a ideia: simulador de remap em dinamômetro com física real, ECU OEM e standalone, falhas catastróficas.", "_reversa_sdd/newproject-brief.md"),
    ("2026-10-17T23:21:42Z", "Ideation", "Ideação", "Problema, valor, alternativas (FTManager, MoTeC, WinOLS, BeamNG) e premissas a validar.", "_reversa_sdd/ideation.md"),
    ("2026-10-17T23:23:13Z", "Personas", "Ideação", "Lucas (aluno OEM), Rodrigo (preparador standalone) e Prof. Marcos (instrutor) com jornadas.", "_reversa_sdd/personas.md"),
    ("2026-10-17T23:25:39Z", "PRD 1.0 a 1.2", "Ideação", "Métricas de sucesso (desvio < 5 %, conclusão >= 80 %, laço >= 100 Hz), escopo, não objetivos e revisão R1.", "_reversa_sdd/prd.md"),
    ("2026-10-17T23:59:44Z", "11 specs SDD", "Especificação", "platform-foundation, engine-physics-core, vehicle-catalog, dyno-bench, knock-and-failure-model, ecu-core, ecu-profiles, telemetry-datalogger, training-scenarios, dyno-cockpit-ui, ecu-tuning-ui. Horário pela data de modificação.", "_reversa_sdd/sdd/*.md"),
    ("2026-10-18T00:10:12Z", "Requirements e plano da 001", "Feature 001", "Requirements integrando as 11 specs, roadmap com 34 decisões, data-model com 19 tabelas e actions com 453 ações em 5 fases.", "_reversa_forward/001-simulador-remap/"),
    ("2026-10-18T01:11:05Z", "Início do código da 001", "Feature 001", "T001: pyproject.toml, uv.lock e Python 3.12. T002 cria os 11 pacotes simremap.*.", "progress.jsonl T001"),
    ("2026-10-18T02:00:00Z", "Pico de entrega", "Feature 001", "201 ações registradas entre 02:00 e 03:00 UTC: contratos, testes vermelhos e física.", "progress.jsonl"),
    ("2026-10-18T04:19:51Z", "Benchmark do laço", "Feature 001", "T128: bench do laço do dyno. Física a 0,078 ms por tick, laço >= 1000 Hz em Apple Silicon.", "progress.jsonl T128"),
    ("2026-10-18T06:03:26Z", "UI de cenários", "Feature 001", "T398: painel de progresso da tentativa; perfis, avaliação e pacotes assinados.", "progress.jsonl T398"),
    ("2026-10-18T09:11:49Z", "Fecho da 001", "Feature 001", "T223 e T224: jornadas Playwright e acessibilidade; T453 determinismo 20x. 452 de 453 ações; T091 (smoke do container) bloqueada por disco do Docker.", "progress.jsonl T453"),
    ("2026-10-18T11:03:17Z", "Adendo da 001", "Sincronização", "Sincronização parcial: deltas por spec, benchmark atingido nos 4 veículos, 2035 testes no backend e 450 no frontend.", "_reversa_sdd/addenda/001-simulador-remap.md"),
    ("2026-10-18T21:02:58Z", "Snapshot pré-002", "Feature 002", "Projeto sem git: snapshot .reversa/snapshots/pre-002-20261018-220258.tgz antes de editar.", ".reversa/snapshots/"),
    ("2026-10-18T21:08:06Z", "Requirements da 002", "Feature 002", "28 requisitos funcionais em 6 frentes; roadmap com 17 decisões; 62 ações em 6 trilhas paralelas.", "_reversa_forward/002-evolucao-comercial/requirements.md"),
    ("2026-10-18T21:25:34Z", "Imersão e Live Tuning", "Feature 002", "T012, T035 e T038: visão térmica, áudio por arquitetura, pedal progressivo; T034 Live Cell Tracing.", "progress.jsonl"),
    ("2026-10-18T22:00:03Z", "Física, ECU e upgrades", "Feature 002", "T020 estratégia VVT, T024 catálogo de upgrades, T009 blend de etanol, T041 canais cam_* e ethanol_pct.", "progress.jsonl"),
    ("2026-10-18T22:11:29Z", "Oficina e carreira na UI", "Feature 002", "T047 Stage Builder e T055 testes da página Oficina (Carreira).", "progress.jsonl"),
    ("2026-10-18T23:16:27Z", "Build da 002", "Feature 002", "T060 e T061: tsc, eslint, 571 vitest e build sem chunk > 500 kB. Registro: depois do build, um agente externo editou DynoCockpitPage.tsx e DynoChart.tsx e introduziu 2 erros TS.", "progress.jsonl T060"),
    ("2026-10-18T23:09:52Z", "Cobertura medida", "Qualidade", "backend/coverage.json: 95,71 % global; todos os 12 pacotes acima de 85 %. Horário convertido do fuso local (+01:00) para UTC.", "backend/coverage.json"),
    ("2026-10-18T23:30:40Z", "Documentação visual da 002", "Feature 002", "T062: /reversa-docs gera a primeira versão deste mini-site em _reversa_docs/.", "_reversa_docs/.state.json"),
    ("2026-10-18T23:32:08Z", "Adendo da 002", "Sincronização", "Adendo vigente da 002: 62 de 62 ações, 2128 testes no backend, 571 no frontend; registra os 2 erros TS abertos.", "_reversa_sdd/addenda/002-evolucao-comercial.md"),
    ("2026-10-18T23:36:16Z", "Requirements e plano da 003", "Feature 003", "Modo autônomo: 18 RF em 4 frentes (Rust, áudio, QA, E2E), 8 decisões, 30 ações em 9 trilhas; premissas Q1 (Docker) e Q2 (tolerância 1e-9).", "_reversa_forward/003-rust-audio-qa-total/requirements.md"),
    ("2026-10-18T23:36:46Z", "Crate simremap_rs", "Feature 003", "T001: maturin como dev dependency e crate PyO3 ABI3 com submódulos tables, cycle e damage. T002 corrige os 2 erros TS da DynoCockpitPage.", "progress.jsonl T001, T002"),
    ("2026-10-18T23:37:38Z", "Seletor SIMREMAP_NATIVE", "Feature 003", "T003: simremap/core/native.py com os modos auto, off e on, e o benchmark de referência do tick Python.", "progress.jsonl T003"),
    ("2026-10-18T23:57:25Z", "Nova síntese de áudio", "Feature 003", "T007, T013 a T015: pulsos, WaveShaper, passa-baixa 180→1400 Hz, ressonadores, turbo por ruído, pops graves e 4 arquétipos sem estridência.", "progress.jsonl T013"),
    ("2026-10-19T00:04:19Z", "make type limpo", "Qualidade", "T016: __init__.py nos testes e configuração do mypy; mypy --strict src tests sem erros em 440 arquivos.", "progress.jsonl T016"),
    ("2026-10-19T00:07:39Z", "ECU nativa", "Feature 003", "T004, T008, T009, T017: interpolação e estratégias em tables.rs; ecu/native_tables.py avalia as tabelas em lote.", "progress.jsonl T017"),
    ("2026-10-19T00:08:15Z", "Dano nativo", "Feature 003", "T006, T012, T019: integral de knock e dano dos 6 modos em damage.rs; dano por tick 48,0 → 7,5 µs.", "progress.jsonl T019"),
    ("2026-10-19T00:33:14Z", "Física nativa e benchmark", "Feature 003", "T005, T010, T011, T018, T025, T026: CycleKernel e GasKernel, física 2,8× mais rápida, Dockerfile com estágio Rust e make native.", "progress.jsonl T018, T025"),
    ("2026-10-19T00:40:00Z", "QA das telas e 8 specs E2E", "Feature 003", "T023 e T024: 9 correções de QA no frontend e 8 specs Playwright novos (carreira, Stage Builder, defeitos, Live Tuning, áudio, motor nativo, ECU, bancada).", "progress.jsonl T024"),
    ("2026-10-19T01:03:09Z", "QA de fluxos, cenários e carreira", "Feature 003", "T020 a T022: tests/qa; os 7 cenários aprovados com acerto real e as 7 ordens da carreira pagas.", "progress.jsonl T021, T022"),
    ("2026-10-19T01:24:59Z", "FX3: surge e oscilação", "Qualidade", "T033: linha de surge com recuo em baixa rotação (Python e Rust); surge do hatch 17,2 → 1,4 %.", "progress.jsonl T033"),
    ("2026-10-19T01:38:04Z", "FX1: calibração ativa e overrun", "Qualidade", "T031: active_calibration_id, seeds ≤ 2^53−1, native_enabled em /version, 409 SESSION_CLOSED e arrefecimento do multi_pull sem overrun.", "progress.jsonl T031"),
    ("2026-10-19T01:55:08Z", "FX2: ECU", "Qualidade", "T032: dTPS por mediana de 3 amostras, diff do 1.º aplicar e PID de boost do hatch (±12,3 → ±0,44 N·m).", "progress.jsonl T032"),
    ("2026-10-19T01:55:29Z", "Build de produção da 003", "Feature 003", "T028: npm run build sem erros e frontend/dist atualizado.", "progress.jsonl T028"),
    (now(), "Documentação visual da 003", "Feature 003", "T029: /reversa-docs regenera este mini-site com a feature 003.", "_reversa_docs/"),
]
EV.sort(key=lambda e: e[0])

# Ritmo: ações concluídas por hora (UTC), lido do progress.jsonl de cada feature (sem correções nem linhas inválidas)
pace = defaultdict(Counter)
for fid, fname in (("001", "001-simulador-remap"), ("002", "002-evolucao-comercial"), ("003", "003-rust-audio-qa-total")):
    seen = set()
    for line in open(os.path.join(ROOT, "_reversa_forward", fname, "progress.jsonl"), encoding="utf-8"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        act = str(r.get("action", ""))
        if r.get("status") != "done" or not re.match(r"^T\d+", act) or act in seen:
            continue
        seen.add(act)
        pace[fid][r["ts"][:13]] += 1
hours = sorted({h for c in pace.values() for h in c})
pace_out = {"hours": [h[8:10] + "/10 " + h[11:13] + "h" for h in hours],
            "series": {fid: [pace[fid].get(h, 0) for h in hours] for fid in ("001", "002", "003")}}
timeline = {"schemaVersion": 1, "generatedAt": now(), "source": "progress.jsonl das features + datas dos artefatos (sem .reversa/chronicle.md)",
            "events": [{"ts": t, "title": ti, "category": c, "detail": d, "source": s} for t, ti, c, d, s in EV], "pace": pace_out}
save_json(os.path.join(DATA, "timeline.json"), timeline)

tl_payload = """
<h1>Linha do tempo</h1>
<p class="lead">Do brief ao fecho da feature 003, em cerca de 29 horas. Não existe <code>.reversa/chronicle.md</code>: os eventos vêm do
<code>progress.jsonl</code> das features e das datas dos artefatos. Horários em UTC.</p>
<div class="layout-side">
  <div class="chart-card"><div id="c-timeline" style="min-height:1180px"></div><div id="c-pace" style="min-height:300px"></div></div>
  <aside class="sidebar" id="event-details" aria-live="polite"><!-- EVENT_DETAILS --><strong>Detalhes do evento</strong><p class="muted">Clique num evento para ver os detalhes.</p></aside>
</div>
<h2>Eventos</h2>
<div class="table-wrap"><table id="t-ev"><thead><tr><th>UTC</th><th>Evento</th><th>Fase</th><th>Fonte</th></tr></thead><tbody></tbody></table></div>
"""
tl_script = r"""
<script>
(function () {
  "use strict";
  var T = (window.RV_DATA && window.RV_DATA.timeline) || { events: [] };
  var CAT = { "Ideação": "#6250d6", "Especificação": "#1baf7a", "Feature 001": "#2a78d6", "Sincronização": "#eda100", "Feature 002": "#eb6834", "Feature 003": "#8a5a2b", "Qualidade": "#008300" };
  var side = document.getElementById("event-details");
  function fmt(ts) { return ts.replace("T", " ").replace(/(\+00:00|Z)$/, ""); }
  function show(e) {
    side.innerHTML = "<strong>" + e.title + "</strong><p class='muted mono'>" + fmt(e.ts) + " UTC</p><p><span class='badge'>" + e.category + "</span></p><p>" + e.detail + "</p><p class='muted'>Fonte: <code>" + e.source + "</code></p>";
  }
  var tb = document.querySelector("#t-ev tbody");
  T.events.forEach(function (e) { var tr = document.createElement("tr"); tr.innerHTML = "<td class=mono>" + fmt(e.ts) + "</td><td>" + e.title + "</td><td>" + e.category + "</td><td class=mono>" + e.source + "</td>"; tr.style.cursor = "pointer"; tr.onclick = function () { show(e); }; tb.appendChild(tr); });
  if (typeof Highcharts === "undefined") return;
  Highcharts.setOptions({ lang: { decimalPoint: ",", thousandsSep: "." }, chart: { backgroundColor: "#fcfcfb", style: { fontFamily: "system-ui, sans-serif" } }, credits: { enabled: false } });
  Highcharts.chart("c-timeline", {
    chart: { type: "timeline", inverted: true, height: 1180 },
    title: { text: "Marcos do projeto", align: "left", style: { fontSize: "15px" } },
    xAxis: { visible: false }, yAxis: { visible: false }, legend: { enabled: false },
    tooltip: { formatter: function () { return "<b>" + this.point.name + "</b><br>" + fmt(this.point.ev.ts) + " UTC"; } },
    series: [{ dataLabels: { connectorColor: "#9aa5b1", connectorWidth: 1, style: { fontWeight: "500", color: "#1e2937", textOutline: "none" }, format: "<b>{point.name}</b><br><span style='color:#6b7480'>{point.label}</span>" },
      marker: { symbol: "circle", radius: 6 },
      point: { events: { click: function () { show(this.ev); } } },
      data: T.events.map(function (e) { return { name: e.title, label: fmt(e.ts).slice(5, 16) + " · " + e.category, color: CAT[e.category] || "#3d4a5c", ev: e }; }) }]
  });
  // Ritmo de entrega: ações concluídas por hora (progress.jsonl)
  var P = T.pace || { hours: [], series: {} };
  Highcharts.chart("c-pace", {
    chart: { type: "column" }, title: { text: "Ações concluídas por hora (UTC)", align: "left", style: { fontSize: "15px" } },
    subtitle: { text: "Só horas com atividade; cada ação conta uma vez", align: "left" },
    xAxis: { categories: P.hours, labels: { rotation: -45, style: { fontSize: "10.5px" } } },
    yAxis: { title: { text: "ações" } },
    series: [{ name: "Feature 001", color: "#2a78d6", data: P.series["001"] || [] },
             { name: "Feature 002", color: "#eb6834", data: P.series["002"] || [] },
             { name: "Feature 003", color: "#8a5a2b", data: P.series["003"] || [] }],
    plotOptions: { column: { borderRadius: 4, borderWidth: 0, stacking: "normal" } }
  });
})();
</script>
"""
HCT = "\n".join(f'<script src="assets/vendor/{f}"></script>' for f in
                ["highcharts.js", "highcharts-accessibility.js", "highcharts-exporting.js", "highcharts-timeline.js"])
write_page("timeline.html", render("timeline", "Linha do tempo", tl_payload, AGENT, "timeline", head=HCT, scripts=tl_script))
register("analyst", AGENT, ["metricas.html", "timeline.html"])
print("analyst ok", len(treemap), "pacotes;", len(EV), "eventos")
