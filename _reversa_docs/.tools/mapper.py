"""Mapper: arquitetura.html (Code City 3D + diagrama de componentes) e modulos.html (D3)."""
import json
import os
import re
from common import DATA, ROOT, load_json, save_json, render, write_page, register

AGENT = "reversa-docs-mapper"

# 1. Enriquecer modules.json com marcação das features 002 e 003
mods = load_json(os.path.join(DATA, "modules.json"))


def touched_of(feature):
    out = set()
    for line in open(os.path.join(ROOT, f"_reversa_forward/{feature}/progress.jsonl"), encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            for f in json.loads(line).get("files", []):
                if f:
                    out.add(f.split(" ")[0])
        except ValueError:
            pass
    return out


def hit(name, paths):
    return any(name == t or (t.endswith("/") and name.startswith(t)) for t in paths)


touched2, touched3 = touched_of("002-evolucao-comercial"), touched_of("003-rust-audio-qa-total")
NEW_PAT = re.compile(r"backend/src/simremap/career/|catalog/upgrades\.py|physics/fuel_blend\.py|ecu/strategies/vvt\.py|"
                     r"dyno-cockpit/live-tuning/|features/workshop/|features/career/|ecu-tuning/ops/quickTune|"
                     r"render/thermal|render/failureFx|useHoldThrottle|thermalView|audio/engineProfile|"
                     r"0008_career|db/models/career|tests/career/|test_upgrades|test_fuel_blend|test_vvt_overlap|"
                     r"test_stock_immutable|test_builtin_hash_resync|test_defect_scenarios|test_upgrades_flex_session")
NEW3_PAT = re.compile(r"^backend/rust/simremap_rs/|core/native\.py$|physics/kernels\.py$|physics/fastmodel\.py$|"
                      r"ecu/native_tables\.py$|damage/native_bridge\.py$|^backend/tests/(native|qa|bench)/|"
                      r"dyno-cockpit/audio/(archetypes|waveforms|spectrum|graph|voices|audioGraph\.test|archetypes\.test|test-utils/)|"
                      r"^frontend/e2e/(career-workshop|stage-builder-flex|defect-scenarios|live-tuning|audio|native-engine|ecu-workspace|bench-controls)\.spec\.ts$|"
                      r"^frontend/e2e/helpers\.ts$")
for m in mods["modules"]:
    m["new002"] = bool(NEW_PAT.search(m["name"]))
    m["touched002"] = m["new002"] or m["name"] in touched2
    m["new003"] = bool(NEW3_PAT.search(m["name"]))
    m["touched003"] = m["new003"] or hit(m["name"], touched3)
save_json(os.path.join(DATA, "modules.json"), mods, indent=None)
n_new3 = sum(1 for m in mods["modules"] if m["new003"])
n_t3 = sum(1 for m in mods["modules"] if m["touched003"] and not m["new003"])

deps = load_json(os.path.join(DATA, "deps.json"))
# Sub-componentes novos das features 002 e 003 como nós filhos (visíveis no grafo D3)
SUB = [
    ("backend/catalog:upgrades", "backend/catalog", "catalog/upgrades.py: peças e apply_upgrades", "002"),
    ("backend/physics:fuel_blend", "backend/physics", "physics/fuel_blend.py: blend E27 a E100", "002"),
    ("backend/ecu:vvt", "backend/ecu", "ecu/strategies/vvt.py: estratégia VVT", "002"),
    ("frontend/dyno-cockpit:live-tuning", "frontend/dyno-cockpit", "dyno-cockpit/live-tuning: tela dividida", "002"),
    ("frontend/ecu-tuning:quickTune", "frontend/ecu-tuning", "ecu-tuning/ops/quickTune.ts: Q, H, V, B", "002"),
    ("backend/core:native", "backend/core", "core/native.py: seletor SIMREMAP_NATIVE=auto|off|on", "003"),
    ("backend/physics:kernels", "backend/physics", "physics/kernels.py: ponte CycleKernel e GasKernel", "003"),
    ("backend/ecu:native_tables", "backend/ecu", "ecu/native_tables.py: tabelas em lote no TableSet", "003"),
    ("backend/damage:native_bridge", "backend/damage", "damage/native_bridge.py: kernels de knock e dano", "003"),
    ("frontend/dyno-cockpit:audio", "frontend/dyno-cockpit", "dyno-cockpit/audio: síntese por pulsos (003)", "003"),
]
deps["subcomponents"] = [{"id": i, "parent": p, "label": l, "feature": f, "new002": f == "002"} for i, p, l, f in SUB]
deps["new002Packages"] = ["backend/career", "frontend/career", "frontend/workshop"]
deps["new003Packages"] = ["native/tables", "native/cycle", "native/damage", "native/lib"]
save_json(os.path.join(DATA, "deps.json"), deps, indent=1)

code = [m for m in mods["modules"] if m["type"] == "code"]
n_mod = len(mods["modules"])

# 2. arquitetura.html
# (nome, descrição, tags, feature em que nasceu ou None)
LAYERS = [
    ("Frontend (React 18 + TypeScript + Vite + Tailwind)", [
        ("app", "Rotas lazy, tela inicial, sessão ativa, flags", ["rota /workshop", "homeApi (QA 003)"], None),
        ("dyno-cockpit", "Bancada: curvas, gauges, carro no rolo, áudio, datalogger, laudo",
         ["live-tuning", "visão térmica", "áudio por pulsos (003)", "pedal progressivo"], None),
        ("ecu-tuning", "Software de ECU: editor 2D/3D, estratégias, wizard de swap, versões",
         ["Quick Tune Q", "H / V / B", "calibração ativa (003)"], None),
        ("scenarios", "Cenários, briefing, progresso, resultado, painel do instrutor", ["correções de QA (003)"], None),
        ("workshop", "Stage Builder: peças e teor de etanol na criação da sessão", ["novo na 002"], "002"),
        ("career", "Página Oficina (Carreira): saldo, reputação, ordens", ["novo na 002"], "002"),
        ("pixel-cars", "Sprites dos 4 carros", [], None),
        ("lib", "Cliente REST orval, WebSocket, unidades", ["cliente regenerado (003)"], None),
        ("e2e", "Playwright: 3 jornadas, a11y, FPS e 8 specs novos da 003", ["8 specs novos"], "003"),
    ]),
    ("Transporte", [
        ("REST /api/v1", "Erros RFC 7807, catálogo único de códigos",
         ["/upgrades", "/career", "/version: native_enabled (003)", "409 SESSION_CLOSED (003)"], None),
        ("WS /ws/v1/sessions/{id}/telemetry", "Envelope com seq, 30 a 60 FPS, canais subscritos",
         ["cam_*", "ethanol_pct"], None),
    ]),
    ("Backend (Python 3.12 + FastAPI + Pydantic v2 + SQLModel)", [
        ("api", "create_app, lifespan, registry de routers, health", ["native_version (003)"], None),
        ("dyno", "Sessões, 4 tipos de puxada, rolo, correção SAE/DIN",
         ["active_calibration_id (003)", "seed ≤ 2^53−1 (003)"], None),
        ("ecu", "Tabelas 2D/3D, Calibration versionada, estratégias e arbitragem",
         ["native_tables (003)", "dTPS por mediana (003)", "BOV pré-borboleta (003)"], None),
        ("profiles", "OEM-Stage, FT-Pro, M1-Race, HT-Elite, swap e BaseSetup", ["10 kinds", "nav OEM por cilindros (003)"], None),
        ("physics", "Motor 0D/1D Otto, turbo/compressor, EGT, 100 a 1000 Hz",
         ["kernels.py (003)", "fastmodel.py (003)", "linha de surge (003)"], None),
        ("damage", "Knock (Livengood-Wu), pré-ignição, dano, laudo forense", ["native_bridge (003)"], None),
        ("catalog", "4 veículos validados, benchmark, calibração de fábrica", ["upgrades.py", "PID boost do hatch (003)"], None),
        ("telemetry", "WS, decimação, DataLog SHA-256, export/import, espectro", ["canais de came e etanol"], None),
        ("scenarios", "Perfis locais, cenários, tentativas, avaliação, pacotes", ["7 builtins", "liquidação antes da avaliação (003)"], None),
        ("career", "Perfil de carreira, 7 ordens, aceitar e liquidar", ["novo na 002"], "002"),
        ("core", "Config SIMREMAP_, worker do laço, logging JSON, erros", ["native.py (003)", "orçamento de overrun (003)"], None),
        ("db", "SQLite/PostgreSQL, Alembic 0001 a 0008", ["0008_career"], None),
    ]),
    ("Camada nativa (Rust + PyO3 0.23, ABI3 ≥ Python 3.12, maturin)", [
        ("simremap_rs._native", "Módulo PyO3 com 3 submódulos; versão em __version__", ["lib.rs", "novo na 003"], "003"),
        ("tables", "Interpolação 1D/2D, lookup de eixo e estratégias: boost PID, VVT/overlap, overrun, two-step, flex",
         ["tables.rs", "tables/strategies.rs"], "003"),
        ("cycle", "Ciclo Otto (Wiebe, VE, entalpia, EGT), gás, térmico, turbo e compressor",
         ["CycleKernel", "GasKernel", "cycle/{solver,gas,thermal,interp}.rs"], "003"),
        ("damage", "Integral de detonação (Livengood-Wu) e acumulação de dano dos 6 modos", ["damage.rs"], "003"),
    ]),
]
STYLE = {"002": ' style="border-color:#e7c3ab;background:#fffaf6"', "003": ' style="border-color:#b9c9ee;background:#f6f8fe"'}


def layer_html():
    out = []
    for title, items in LAYERS:
        cards = []
        for name, desc, tags, feat in items:
            badges = "".join(f'<span class="badge {"n3" if "003" in t else "new"}">{t}</span>' for t in tags)
            cards.append(f'<div class="card"{STYLE.get(feat, "")}><h3 class="mono">{name}</h3><div class="muted">{desc}</div>'
                         f'<div style="margin-top:6px">{badges}</div></div>')
        out.append(f'<h3>{title}</h3><div class="grid g4">{"".join(cards)}</div>')
    return "\n".join(out)


NATIVE_ROWS = [
    ("ecu", "ecu/native_tables.py, ecu/runtime.py", "simremap_rs.tables.TableSet", "Grupos early e after_ign avaliados numa chamada por tick; estratégias seguem chamando table.at()"),
    ("physics", "physics/kernels.py, physics/engine.py, physics/cycle_solver.py", "simremap_rs.cycle.CycleKernel e GasKernel", "Ciclo fechado e bloco de gás (VE, borboleta, compressor/turbina, eixo do turbo, intercooler, pressões)"),
    ("physics", "physics/fastmodel.py", "(Python puro)", "fast_constructor: EngineState e SensorReadings em cerca de 1/3 do custo do model_construct"),
    ("damage", "damage/native_bridge.py, damage/knock.py, damage/model.py", "simremap_rs._native.damage", "Passo contínuo do dano e integral de knock; cache de ComponentHealth"),
]

arch_payload = f"""
<h1>Arquitetura</h1>
<p class="lead">Monólito modular: 12 pacotes de domínio em <code>backend/src/simremap</code>, 7 features em <code>frontend/src/features</code> e,
desde a feature 003, uma camada nativa opcional em Rust (<code>backend/rust/simremap_rs</code>). Tudo é servido por um único container local-first.
Selos laranja marcam o que a 002 adicionou; selos azuis marcam a 003.</p>

<h2>Laço de simulação (ordem do contrato, a cada tick)</h2>
<div class="flow"><span>sensors</span><b>→</b><span>ecu <small>⇄ tables.rs</small></span><b>→</b><span>physics <small>⇄ cycle.rs</small></span><b>→</b><span>damage <small>⇄ damage.rs</small></span><b>→</b><span>telemetry</span>
<span class="muted" style="background:none;border:0">worker em processo dedicado, 1000 Hz; uma travessia FFI por subsistema por tick (D-03), nunca por célula</span></div>

<h2>Camada nativa com fallback Python</h2>
<div class="grid g2">
<div class="card"><h3>Seletor <code>simremap/core/native.py</code></h3>
<p>Lido uma vez por processo. A variável <code>SIMREMAP_NATIVE</code> decide o caminho:</p>
<ul><li><b>auto</b> (padrão): usa <code>simremap_rs</code> se importar; senão, fica o Python de referência.</li>
<li><b>off</b>: nunca usa a extensão.</li>
<li><b>on</b>: exige a extensão; sem ela, levanta <code>NativeUnavailableError</code>.</li></ul>
<p class="muted">O Python continua a ser a referência. Testes em <code>backend/tests/native/</code> comparam Python × Rust com seed (tolerância relativa 1e-9; na prática, paridade bit a bit).
<code>/api/v1/version</code> publica <code>native_enabled</code> e <code>native_version</code>.</p></div>
<div class="card"><h3>Build e distribuição</h3>
<ul><li>Crate <code>simremap_rs</code> com PyO3 0.23 (<code>abi3-py312</code>), LTO fat e <code>codegen-units = 1</code>.</li>
<li><code>make native</code> roda <code>maturin develop --release</code>; maturin é dependência de desenvolvimento.</li>
<li>Dockerfile com estágio Rust opcional que compila o wheel ABI3; se falhar, a imagem segue válida com o fallback.</li>
<li><code>target/</code> fica fora do contexto Docker (<code>.dockerignore</code>).</li></ul></div>
</div>
<div class="table-wrap"><table><thead><tr><th>Pacote Python</th><th>Ponte</th><th>Kernel</th><th>O que vai para o nativo</th></tr></thead><tbody>
{"".join(f"<tr><td class=mono>{a}</td><td class=mono>{b}</td><td class=mono>{c}</td><td>{d}</td></tr>" for a, b, c, d in NATIVE_ROWS)}
</tbody></table></div>

<h2>Cadeia de áudio da bancada (feature 003)</h2>
<p class="muted">Web Audio sintetizado, sem amostras e sem osciladores senoidais puros no spool. Código em <code>frontend/src/features/dyno-cockpit/audio/</code>
(<code>AudioEngine.ts</code>, <code>EngineSynth.ts</code>, <code>graph.ts</code>, <code>voices.ts</code>, <code>archetypes.ts</code>, <code>spectrum.ts</code>).</p>
<div class="flow"><span>pulsos de combustão</span><b>→</b><span>WaveShaper (saturação)</span><b>→</b><span>lowpass dinâmico 180→1400 Hz</span><b>→</b>
<span>ressonadores 90–140 Hz e 280–450 Hz</span><b>→</b><span>sub-bass</span><b>→</b><span>master com corte de presença em 1–4 kHz</span></div>
<div class="grid g3">
<div class="card"><h3>Turbo</h3><p>Ruído de banda estreita mais um harmônico discreto, com flutter e chirp no alívio (BOV/diverter). Nenhum <code>OscillatorNode</code> contínuo no spool.</p></div>
<div class="card"><h3>Pops &amp; bangs</h3><p>Punch grave de 90 a 160 Hz, estalo filtrado e decay curto.</p></div>
<div class="card"><h3>4 arquétipos</h3><p>i4 turbo, i6 turbo, i4 clássico e V8 com compressor. Energia em 1–4 kHz abaixo de 5 % em todos (máximo medido: 2,2 %).</p></div>
</div>

<h2>Componentes por camada</h2>
{layer_html()}

<h2>Code City 3D</h2>
<p class="muted">Cada prédio é um arquivo ({n_mod} arquivos, {len(code)} de código). Altura = linhas não vazias, base = complexidade aproximada
(contagem de ramificações), distrito = pacote. O distrito <code>native/*</code> é o crate Rust. A feature 003 criou {n_new3} arquivos e alterou outros {n_t3}.
Passe o mouse para ver o arquivo; clique para focar.</p>
<div class="layout-side">
  <div class="chart-card" style="position:relative;height:620px;padding:0;overflow:hidden">
    <div id="loader" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:var(--ink-2)">Carregando cena 3D...</div>
    <canvas id="scene" style="width:100%;height:100%;display:block" aria-label="Code City 3D do SimuladorRemap"></canvas>
  </div>
  <aside class="sidebar" aria-label="Controles da Code City">
    <strong>Controles</strong>
    <label>Altura (LOC) <span data-out="locScale"></span><input type="range" min="0.02" max="0.3" step="0.01" value="0.08" data-param="locScale"></label>
    <label>Base (complexidade) <span data-out="cxScale"></span><input type="range" min="0.2" max="2" step="0.1" value="0.8" data-param="cxScale"></label>
    <label>Intensidade da luz <span data-out="light"></span><input type="range" min="0.2" max="2" step="0.1" value="1" data-param="light"></label>
    <label>Camada <select data-param="layer"><option value="all">Tudo</option><option value="backend">Backend</option><option value="native">Nativo (Rust)</option><option value="frontend">Frontend</option><option value="backend-tests">Testes do backend</option></select></label>
    <label><input type="checkbox" data-param="showTests" checked> Mostrar testes</label>
    <label>Destacar feature <select data-param="hl"><option value="003">003 (Rust, áudio, QA)</option><option value="002">002 (evolução comercial)</option><option value="none">Nenhuma</option></select></label>
    <button class="btn" id="reset">Reset da câmera</button><button class="btn" id="export-png">Exportar PNG</button>
    <div class="legend"><span><i style="background:#3d4a5c"></i>código backend</span><span><i style="background:#2a78d6"></i>código frontend</span>
    <span><i style="background:#8a5a2b"></i>código Rust</span><span><i style="background:#bdb4a4"></i>teste</span>
    <span><i style="background:#eb6834"></i>novo na feature</span><span><i style="background:#eda100"></i>alterado na feature</span></div>
  </aside>
</div>
<div id="tip" class="tooltip" role="status"></div>
"""

arch_script = r"""
<script>
(function () {
  "use strict";
  var loader = document.getElementById("loader");
  function fail(msg) { loader.innerHTML = '<div class="reversa-error-panel">' + msg + '</div>'; }
  if (typeof THREE === "undefined" || !THREE.OrbitControls) { fail("Esta visualização requer a biblioteca Three.js em assets/vendor/. Conecte-se à internet e rode /reversa-docs novamente."); return; }
  var all = (window.RV_DATA && window.RV_DATA.modules && window.RV_DATA.modules.modules) || [];
  if (!all.length) { fail("Nada para visualizar ainda: modules.json vazio."); return; }

  var COLORS = { be: 0x3d4a5c, fe: 0x2a78d6, rs: 0x8a5a2b, test: 0xbdb4a4, nw: 0xeb6834, tc: 0xeda100 };
  var CELL = 4, GAP = 10;
  var canvas = document.getElementById("scene");
  var renderer;
  try { renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, preserveDrawingBuffer: true }); }
  catch (e) { fail("WebGL não está disponível no seu navegador. Use Chrome, Firefox ou Edge atualizados."); return; }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  var scene = new THREE.Scene();
  scene.background = new THREE.Color(0xf5f3ee);
  var camera = new THREE.PerspectiveCamera(45, 1, 1, 5000);
  var controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  var hemi = new THREE.HemisphereLight(0xffffff, 0xbdb4a4, 0.7);
  var dir = new THREE.DirectionalLight(0xffffff, 0.8);
  dir.position.set(200, 400, 150); dir.castShadow = true;
  dir.shadow.mapSize.set(2048, 2048);
  ["left","bottom"].forEach(function(k){ dir.shadow.camera[k] = -500; });
  ["right","top"].forEach(function(k){ dir.shadow.camera[k] = 500; });
  scene.add(hemi, dir, new THREE.AmbientLight(0xffffff, 0.25));
  var group = new THREE.Group(); scene.add(group);
  var mesh = null, shown = [], center = new THREE.Vector3(), span = 300;

  function colorFor(m, hl) {
    if (hl !== "none" && m["new" + hl]) return COLORS.nw;
    if (hl !== "none" && m["touched" + hl]) return COLORS.tc;
    if (m.type === "test") return COLORS.test;
    return m.layer === "frontend" ? COLORS.fe : (m.layer === "native" ? COLORS.rs : COLORS.be);
  }

  function build() {
    while (group.children.length) { var c = group.children.pop(); if (c.geometry) c.geometry.dispose(); if (c.material) c.material.dispose(); }
    var layer = RV_PARAM("layer", "all"), tests = RV_PARAM("showTests", true), hl = String(RV_PARAM("hl", "003"));
    var locS = RV_PARAM("locScale", 0.08), cxS = RV_PARAM("cxScale", 0.8);
    shown = all.filter(function (m) { return (layer === "all" || m.layer === layer) && (tests || m.type !== "test"); });
    var districts = {};
    shown.forEach(function (m) { (districts[m.folder] = districts[m.folder] || []).push(m); });
    var names = Object.keys(districts).sort();
    var cols = Math.ceil(Math.sqrt(names.length));
    var x = 0, z = 0, rowMax = 0, maxX = 0;
    var box = new THREE.BoxGeometry(1, 1, 1); box.translate(0, 0.5, 0);
    mesh = new THREE.InstancedMesh(box, new THREE.MeshStandardMaterial({ roughness: 0.65 }), shown.length);
    mesh.castShadow = true; mesh.receiveShadow = true;
    var dummy = new THREE.Object3D(), col = new THREE.Color(), idx = 0;
    names.forEach(function (name, i) {
      var list = districts[name].sort(function (a, b) { return b.loc - a.loc; });
      var dc = Math.ceil(Math.sqrt(list.length)), size = dc * CELL + 2;
      var plane = new THREE.Mesh(new THREE.PlaneGeometry(size, size),
        new THREE.MeshStandardMaterial({ color: name.indexOf("frontend") === 0 ? 0xdbe7f6 : (name.indexOf("native") === 0 ? 0xeee0d0 : (name.indexOf("tests") > 0 ? 0xeae5da : 0xdfe3e8)) }));
      plane.rotation.x = -Math.PI / 2; plane.position.set(x + size / 2, 0.02, z + size / 2); plane.receiveShadow = true;
      plane.userData = { district: name };
      group.add(plane);
      list.forEach(function (m, k) {
        var w = Math.min(CELL - 0.6, Math.max(1, Math.sqrt(m.complexity) * cxS * 0.35));
        var h = Math.max(0.5, m.loc * locS);
        dummy.position.set(x + 1 + (k % dc) * CELL + CELL / 2, 0, z + 1 + Math.floor(k / dc) * CELL + CELL / 2);
        dummy.scale.set(w, h, w); dummy.updateMatrix();
        mesh.setMatrixAt(idx, dummy.matrix);
        col.setHex(colorFor(m, hl)); mesh.setColorAt(idx, col);
        idx++;
      });
      x += size + GAP; rowMax = Math.max(rowMax, size); maxX = Math.max(maxX, x);
      if ((i + 1) % cols === 0) { x = 0; z += rowMax + GAP; rowMax = 0; }
    });
    group.add(mesh);
    var bb = new THREE.Box3().setFromObject(group);
    bb.getCenter(center); span = Math.max(bb.max.x - bb.min.x, bb.max.z - bb.min.z);
    var ground = new THREE.Mesh(new THREE.PlaneGeometry(span * 3, span * 3), new THREE.MeshStandardMaterial({ color: 0xece8df }));
    ground.rotation.x = -Math.PI / 2; ground.position.set(center.x, 0, center.z); ground.receiveShadow = true;
    group.add(ground);
  }
  function resetCam() {
    camera.position.set(center.x + span * 0.55, span * 0.75, center.z + span * 0.95);
    controls.target.copy(center); controls.update();
  }
  function resize() {
    var r = canvas.parentElement.getBoundingClientRect();
    renderer.setSize(r.width, r.height, false);
    camera.aspect = r.width / r.height; camera.updateProjectionMatrix();
  }
  build(); resize(); resetCam();
  window.addEventListener("resize", resize);
  document.addEventListener("rv:param", function (e) {
    if (e.detail.param === "light") { dir.intensity = 0.8 * e.detail.value; hemi.intensity = 0.7 * e.detail.value; return; }
    build();
  });
  document.getElementById("reset").addEventListener("click", resetCam);
  document.getElementById("export-png").addEventListener("click", function () {
    renderer.domElement.toBlob(function (b) { var a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = "code-city-simuladorremap.png"; a.click(); });
  });
  var ray = new THREE.Raycaster(), mouse = new THREE.Vector2(), tip = document.getElementById("tip");
  function pick(ev) {
    var r = canvas.getBoundingClientRect();
    mouse.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(mouse, camera);
    var hit = ray.intersectObject(mesh, false)[0];
    return hit && hit.instanceId !== undefined ? { m: orderMap()[hit.instanceId], point: hit.point } : null;
  }
  var order = null;
  function orderMap() {
    if (order && order.n === shown.length) return order.list;
    var districts = {}; shown.forEach(function (m) { (districts[m.folder] = districts[m.folder] || []).push(m); });
    var list = []; Object.keys(districts).sort().forEach(function (n) { districts[n].sort(function (a, b) { return b.loc - a.loc; }).forEach(function (m) { list.push(m); }); });
    order = { n: shown.length, list: list }; return list;
  }
  document.addEventListener("rv:param", function () { order = null; });
  canvas.addEventListener("mousemove", function (ev) {
    var p = pick(ev);
    if (!p || !p.m) { tip.style.display = "none"; return; }
    var m = p.m;
    tip.innerHTML = "<b>" + m.name + "</b><br>pacote: " + m.folder + "<br>LOC: " + m.loc + " · complexidade: " + m.complexity +
      (m.new003 ? "<br>novo na feature 003" : (m.touched003 ? "<br>alterado na feature 003" : "")) +
      (m.new002 ? "<br>novo na feature 002" : (m.touched002 ? "<br>alterado na feature 002" : ""));
    tip.style.display = "block"; tip.style.left = (ev.clientX + 14) + "px"; tip.style.top = (ev.clientY + 14) + "px";
  });
  canvas.addEventListener("mouseleave", function () { tip.style.display = "none"; });
  canvas.addEventListener("click", function (ev) { var p = pick(ev); if (p) { controls.target.copy(p.point); controls.update(); } });
  renderer.domElement.addEventListener("webglcontextlost", function (e) { e.preventDefault(); });
  var first = true;
  (function loop() { requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); if (first) { first = false; loader.style.display = "none"; } })();
})();
</script>
"""

arch = render("arquitetura", "Arquitetura 3D", arch_payload, AGENT, "arquitetura",
              head='<script src="assets/vendor/three.min.js"></script>\n<script src="assets/vendor/OrbitControls.js"></script>',
              scripts=arch_script)
write_page("arquitetura.html", arch)

# 3. modulos.html
mod_payload = """
<h1>Módulos e dependências</h1>
<p class="lead">Grafo dirigido de importações entre pacotes (backend <code>simremap.*</code> e features do frontend). A espessura da aresta é o número
de arquivos que importam o destino. Nós castanhos são o crate Rust da 003 (<code>native/*</code>), ligados a <code>ecu</code>, <code>physics</code> e <code>damage</code>.
Nós laranja são componentes novos da 002, nós azul-violeta são sub-componentes da 003 e nós com anel vermelho estão num ciclo.</p>
<div class="layout-side">
  <div class="chart-card" style="height:640px;padding:0;position:relative"><svg id="graph" width="100%" height="100%" role="img" aria-label="Grafo de dependências entre pacotes"></svg></div>
  <aside class="sidebar" aria-label="Filtros do grafo">
    <strong>Filtros</strong>
    <label>Camada <select data-param="lang"><option value="all">Backend e frontend</option><option value="backend">Backend (Python)</option><option value="frontend">Frontend (TypeScript)</option><option value="native">Backend e nativo (Python + Rust)</option></select></label>
    <label>Tipo de nó <select data-param="kind"><option value="all">Pacotes e sub-componentes 002/003</option><option value="pkg">Só pacotes</option></select></label>
    <label>Força de repulsão <span data-out="charge"></span><input type="range" min="-900" max="-100" step="50" value="-420" data-param="charge"></label>
    <label>Distância mínima <span data-out="dist"></span><input type="range" min="40" max="220" step="10" value="110" data-param="dist"></label>
    <div class="legend"><span><i style="background:#3d4a5c"></i>backend</span><span><i style="background:#2a78d6"></i>frontend</span><span><i style="background:#8a5a2b"></i>nativo (Rust)</span><span><i style="background:#eb6834"></i>novo na 002</span><span><i style="background:#6250d6"></i>novo na 003</span><span><i style="background:#fff;border:2px solid #c62f2e"></i>em ciclo</span></div>
  </aside>
</div>
<div id="tip" class="tooltip" role="status"></div>
<h2>Leitura do grafo</h2>
<div class="grid g2">
<div class="card"><h3>Ciclos de importação</h3><div id="cycles" class="muted"></div></div>
<div class="card"><h3>Pares com dependência mútua</h3><div id="mutual" class="muted"></div></div>
</div>
<h2>Tabela de arestas</h2>
<div class="table-wrap"><table id="edges"><thead><tr><th>Origem</th><th>Destino</th><th class="num">Arquivos</th></tr></thead><tbody></tbody></table></div>
"""
mod_script = r"""
<script>
(function () {
  "use strict";
  var svgEl = document.getElementById("graph");
  if (typeof d3 === "undefined") { svgEl.outerHTML = '<div class="reversa-error-panel">Esta visualização requer D3 em assets/vendor/d3.v7.min.js.</div>'; return; }
  var D = (window.RV_DATA && window.RV_DATA.deps) || { nodes: [], edges: [], cycles: [] };
  var mods = (window.RV_DATA && window.RV_DATA.modules && window.RV_DATA.modules.modules) || [];
  var loc = {}; mods.forEach(function (m) { if (m.type === "code") loc[m.folder] = (loc[m.folder] || 0) + m.loc; });
  var inCycle = {}; (D.cycles || []).forEach(function (c) { c.forEach(function (n) { inCycle[n] = true; }); });
  var newPk = {}; (D.new002Packages || []).forEach(function (p) { newPk[p] = true; });
  var tip = document.getElementById("tip");

  // Leitura textual
  document.getElementById("cycles").innerHTML = (D.cycles || []).length ?
    D.cycles.map(function (c) { return "<p><b>" + c.length + " pacotes</b> num componente fortemente conexo: " + c.map(function (x) { return "<code>" + x.split("/")[1] + "</code>"; }).join(" ") + "</p>"; }).join("") +
    "<p>O ciclo é de pacote, não de arquivo: inclui importações tardias e de tipos. Os pares mútuos ao lado mostram onde o acoplamento é direto.</p>" : "Nenhum ciclo detectado.";
  var key = {}; D.edges.forEach(function (e) { key[e.from + ">" + e.to] = e.weight; });
  var mutual = D.edges.filter(function (e) { return e.from < e.to && key[e.to + ">" + e.from]; });
  document.getElementById("mutual").innerHTML = mutual.length ? "<ul>" + mutual.map(function (e) { return "<li><code>" + e.from + "</code> ⇄ <code>" + e.to + "</code> (" + e.weight + " / " + key[e.to + ">" + e.from] + " arquivos)</li>"; }).join("") + "</ul>" : "Nenhum.";
  var tb = document.querySelector("#edges tbody");
  D.edges.slice().sort(function (a, b) { return b.weight - a.weight; }).forEach(function (e) {
    var tr = document.createElement("tr"); tr.innerHTML = "<td class=mono>" + e.from + "</td><td class=mono>" + e.to + "</td><td class=num>" + e.weight + "</td>"; tb.appendChild(tr);
  });

  var svg = d3.select(svgEl), sim = null;
  function draw() {
    svg.selectAll("*").remove();
    var lang = RV_PARAM("lang", "all"), kind = RV_PARAM("kind", "all");
    var W = svgEl.clientWidth || 900, H = svgEl.clientHeight || 640;
    var nodes = D.nodes.filter(function (n) { return n.id !== "backend/simremap" && n.id !== "frontend/root" && (lang === "all" || n.layer === lang || (lang === "native" && n.layer === "backend")); })
      .map(function (n) { return { id: n.id, layer: n.layer, loc: loc[n.id] || 50, sub: false, isNew: !!newPk[n.id] }; });
    var ids = {}; nodes.forEach(function (n) { ids[n.id] = true; });
    var links = D.edges.filter(function (e) { return ids[e.from] && ids[e.to]; }).map(function (e) { return { source: e.from, target: e.to, w: e.weight, sub: false }; });
    if (kind === "all") (D.subcomponents || []).forEach(function (s) {
      if (!ids[s.parent]) return;
      nodes.push({ id: s.id, layer: s.parent.split("/")[0], loc: 120, sub: true, isNew: true, feat: s.feature || "002", label: s.label });
      links.push({ source: s.id, target: s.parent, w: 1, sub: true, feat: s.feature || "002" });
    });
    var r = d3.scaleSqrt().domain([0, d3.max(nodes, function (n) { return n.loc; })]).range([6, 30]);
    var defs = svg.append("defs");
    defs.append("marker").attr("id", "arr").attr("viewBox", "0 -5 10 10").attr("refX", 10).attr("refY", 0).attr("markerWidth", 6).attr("markerHeight", 6).attr("orient", "auto")
      .append("path").attr("d", "M0,-4L10,0L0,4").attr("fill", "#7c8a99");
    var g = svg.append("g");
    var zoom = d3.zoom().scaleExtent([0.2, 3]).on("zoom", function (ev) { g.attr("transform", ev.transform); });
    svg.call(zoom);
    var link = g.append("g").selectAll("line").data(links).join("line")
      .attr("stroke", function (d) { return d.sub ? (d.feat === "003" ? "#6250d6" : "#eb6834") : "#9aa5b1"; }).attr("stroke-dasharray", function (d) { return d.sub ? "4 3" : null; })
      .attr("stroke-opacity", 0.75).attr("stroke-width", function (d) { return 1 + Math.sqrt(d.w); }).attr("marker-end", function (d) { return d.sub ? null : "url(#arr)"; });
    var node = g.append("g").selectAll("g").data(nodes).join("g").style("cursor", "grab");
    node.append("circle").attr("r", function (d) { return r(d.loc); })
      .attr("fill", function (d) { return d.sub && d.feat === "003" ? "#6250d6" : (d.layer === "native" ? "#8a5a2b" : (d.isNew ? "#eb6834" : (d.layer === "frontend" ? "#2a78d6" : "#3d4a5c"))); })
      .attr("stroke", function (d) { return inCycle[d.id] ? "#c62f2e" : "#fcfcfb"; }).attr("stroke-width", function (d) { return inCycle[d.id] ? 2.5 : 2; });
    node.append("text").text(function (d) { return d.sub ? d.id.split(":")[1] : d.id.split("/")[1]; })
      .attr("x", function (d) { return r(d.loc) + 4; }).attr("y", 4).attr("font-size", 12).attr("fill", "#1e2937").attr("paint-order", "stroke").attr("stroke", "#fcfcfb").attr("stroke-width", 3);
    node.on("mousemove", function (ev, d) {
      var outs = links.filter(function (l) { return (l.source.id || l.source) === d.id && !l.sub; }).length;
      var ins = links.filter(function (l) { return (l.target.id || l.target) === d.id && !l.sub; }).length;
      tip.innerHTML = "<b>" + (d.label || d.id) + "</b><br>" + (d.sub ? "sub-componente novo da " + d.feat : "LOC de código: " + d.loc + "<br>importa " + outs + " pacotes · importado por " + ins) + (inCycle[d.id] ? "<br>participa de ciclo" : "");
      tip.style.display = "block"; tip.style.left = (ev.clientX + 14) + "px"; tip.style.top = (ev.clientY + 14) + "px";
      link.attr("stroke-opacity", function (l) { return (l.source.id === d.id || l.target.id === d.id) ? 1 : 0.12; });
    }).on("mouseleave", function () { tip.style.display = "none"; link.attr("stroke-opacity", 0.75); });
    node.call(d3.drag().on("start", function (ev, d) { if (!ev.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
      .on("drag", function (ev, d) { d.fx = ev.x; d.fy = ev.y; }).on("end", function (ev, d) { if (!ev.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }));
    if (sim) sim.stop();
    sim = d3.forceSimulation(nodes)
      .force("link", d3.forceLink(links).id(function (d) { return d.id; }).distance(function (l) { return l.sub ? 40 : RV_PARAM("dist", 110); }))
      .force("charge", d3.forceManyBody().strength(RV_PARAM("charge", -420)))
      .force("x", d3.forceX(function (d) { return lang === "all" ? (d.layer === "frontend" ? W * 0.22 : (d.layer === "native" ? W * 0.85 : W * 0.58)) : (lang === "native" ? (d.layer === "native" ? W * 0.78 : W * 0.4) : W / 2); }).strength(0.08))
      .force("y", d3.forceY(H / 2).strength(0.06))
      .force("collide", d3.forceCollide(function (d) { return r(d.loc) + 6; }))
      .on("tick", ticked);
    function ticked() {
        link.each(function (d) {
          var dx = d.target.x - d.source.x, dy = d.target.y - d.source.y, len = Math.sqrt(dx * dx + dy * dy) || 1, rr = r(d.target.loc) + 3;
          d3.select(this).attr("x1", d.source.x).attr("y1", d.source.y).attr("x2", d.target.x - dx / len * rr).attr("y2", d.target.y - dy / len * rr);
        });
        node.attr("transform", function (d) { return "translate(" + d.x + "," + d.y + ")"; });
    }
    // Layout estável: pré-calcula a simulação e enquadra o grafo inteiro na área visível
    sim.stop();
    for (var t = 0; t < 400; t++) sim.tick();
    ticked();
    var x0 = d3.min(nodes, function (d) { return d.x - r(d.loc); }) - 20, x1 = d3.max(nodes, function (d) { return d.x + r(d.loc) + 90; }),
        y0 = d3.min(nodes, function (d) { return d.y - r(d.loc); }) - 20, y1 = d3.max(nodes, function (d) { return d.y + r(d.loc); }) + 20;
    var k = Math.min(1.6, Math.min(W / (x1 - x0), H / (y1 - y0)));
    svg.call(zoom.transform, d3.zoomIdentity.translate((W - k * (x1 + x0)) / 2, (H - k * (y1 + y0)) / 2).scale(k));
    sim.alphaDecay(0.05);
  }
  draw();
  document.addEventListener("rv:param", draw);
})();
</script>
"""
modp = render("modulos", "Módulos", mod_payload, AGENT, "modulos",
              head='<script src="assets/vendor/d3.v7.min.js"></script>', scripts=mod_script)
write_page("modulos.html", modp)

st = register("mapper", AGENT, ["arquitetura.html", "modulos.html"],
              [("topologia.html", "topology not detected (_reversa_sdd/architecture.md ausente)")])
print("mapper ok", n_mod, "modulos;", len(deps["edges"]), "arestas;", len(deps["cycles"]), "ciclos")
