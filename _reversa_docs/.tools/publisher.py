"""Publisher: selo, data.js, nav e mini-selo retroativos, auto-discovery, index, placeholders, links, smoke test e telemetria."""
import json
import math
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from common import DOCS, ROOT, DATA, CONFIG, STATE, load_json, save_json, render, write_page, register, now, sha, esc

AGENT = "reversa-docs-publisher"
cfg = load_json(CONFIG)
seed_hex = cfg["seed"]["hash"].split(":")[1]


# 1 e 2. Selo generativo determinístico (fallback SVG da skill reversa-selo-generativo, sem p5.js)
def rng(hexs):
    state = int(hexs[:16], 16) or 1

    def nxt():
        nonlocal state
        state ^= (state << 13) & 0xFFFFFFFFFFFFFFFF
        state ^= state >> 7
        state ^= (state << 17) & 0xFFFFFFFFFFFFFFFF
        return (state & 0xFFFFFFFF) / 0xFFFFFFFF
    return nxt


PAL = {"bg": "#f5f3ee", "fg": ["#3d4a5c", "#7c8a99", "#a06b4a", "#4f6b5d", "#bdb4a4"], "accent": "#1e2937"}
PATTERNS = ["flow-field", "particle-orbit", "crystal-lattice", "wave-interference", "noise-strata"]


def seal(size, mini=False):
    r = rng(seed_hex)
    pattern = PATTERNS[int(seed_hex[:2], 16) % 5]
    c = size / 2
    dom, sec, acc = PAL["fg"][int(seed_hex[2], 16) % 5], PAL["fg"][(int(seed_hex[3], 16) + 1) % 5], PAL["fg"][2]
    sw = 3.2 if mini else 1.4
    parts = [f'<circle cx="{c}" cy="{c}" r="{c}" fill="{PAL["bg"]}"/>']
    sym = 6 + int(seed_hex[4], 16) % 5
    rings = 3 if mini else 7
    for k in range(rings, 0, -1):
        rad = c * 0.88 * k / rings
        rot = r() * math.pi
        pts = [(c + rad * math.cos(rot + 2 * math.pi * i / sym), c + rad * math.sin(rot + 2 * math.pi * i / sym)) for i in range(sym)]
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + " Z"
        col = dom if k % 2 else sec
        parts.append(f'<path d="{d}" fill="{col}" fill-opacity="{0.10 + 0.05 * (k % 3):.2f}" stroke="{col}" stroke-width="{sw}" stroke-linejoin="round"/>')
    for i in range(sym * (1 if mini else 2)):
        a = 2 * math.pi * i / (sym * (1 if mini else 2))
        x2, y2 = c + c * 0.88 * math.cos(a), c + c * 0.88 * math.sin(a)
        parts.append(f'<line x1="{c}" y1="{c}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{PAL["accent"]}" stroke-opacity="0.25" stroke-width="{sw * 0.7:.2f}"/>')
    if not mini:
        for _ in range(40):
            a, rr = r() * 2 * math.pi, c * (0.2 + 0.68 * r())
            parts.append(f'<circle cx="{c + rr * math.cos(a):.1f}" cy="{c + rr * math.sin(a):.1f}" r="{1.5 + 3 * r():.1f}" fill="{acc}" fill-opacity="0.55"/>')
    parts.append(f'<circle cx="{c}" cy="{c}" r="{c * 0.16:.1f}" fill="{PAL["accent"]}"/>')
    parts.append(f'<circle cx="{c}" cy="{c}" r="{c * 0.07:.1f}" fill="{acc}"/>')
    cls = "seal-mini" if mini else "seal"
    return (f'<svg class="{cls}" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}" height="{size}" '
            f'role="img" aria-label="Selo do projeto SimuladorRemap" data-pattern="{pattern}" data-seed="{seed_hex[:8]}">' + "".join(parts) + "</svg>")


os.makedirs(os.path.join(DOCS, "assets/img"), exist_ok=True)
seal_svg, seal_mini = seal(800), seal(64, mini=True)
open(os.path.join(DOCS, "assets/img/seal.svg"), "w", encoding="utf-8").write(seal_svg)
open(os.path.join(DOCS, "assets/img/seal-mini.svg"), "w", encoding="utf-8").write(seal_mini)

# 3. data.js
st = load_json(STATE)
LABELS = [("index", "index.html", "Visão geral"), ("arquitetura", "arquitetura.html", "Arquitetura 3D"),
          ("modulos", "modulos.html", "Módulos"), ("topologia", "topologia.html", "Topologia"),
          ("metricas", "metricas.html", "Métricas"), ("timeline", "timeline.html", "Timeline"),
          ("glossario", "glossario.html", "Glossário"), ("deck", "deck.html", "Deck"),
          ("features", "features/index.html", "Features")]
gen = set(st["pagesGenerated"]) | {"index.html"}
nav = [{"id": i, "href": h, "label": l} for i, h, l in LABELS if h in gen]


def jl(name):
    return load_json(os.path.join(DATA, name), {})


RV = {"modules": jl("modules.json"), "deps": jl("deps.json"), "metrics": jl("metrics.json"), "timeline": jl("timeline.json"),
      "glossary": jl("glossary.json"), "featuresIndex": jl("features-index.json"), "sealSvg": seal_svg, "sealMiniSvg": seal_mini,
      "seedShort": seed_hex[:8], "nav": nav,
      "config": {k: cfg["interview"][k] for k in ("visualStyle", "readerProfile", "depth")}}
with open(os.path.join(DOCS, "assets/js/data.js"), "w", encoding="utf-8") as f:
    f.write("/* Gerado por reversa-docs-publisher. Única fonte de dados das páginas (sem fetch local). */\n")
    f.write("window.RV_DATA = " + json.dumps(RV, ensure_ascii=False, separators=(",", ":")) + ";\n")


def nav_html(base):
    return "".join(f'<a href="{base}{n["href"]}" data-page-id="{n["id"]}">{esc(n["label"])}</a>' for n in nav)


def backpatch(rel):
    path = os.path.join(DOCS, rel)
    s = open(path, encoding="utf-8").read()
    base = "../" * rel.count("/")
    s = s.replace("<!-- MINI_SEAL_SVG -->", seal_mini)
    s = re.sub(r'<svg class="seal-mini".*?</svg>', lambda _: seal_mini, s, flags=re.S)
    s = re.sub(r'(<nav class="reversa-doc-nav"[^>]*>).*?(</nav>)', lambda m: m.group(1) + nav_html(base) + m.group(2), s, flags=re.S)
    s = s.replace("<!-- NAV_LINKS -->", nav_html(base))
    dj, nj = f'<script src="{base}assets/js/data.js"></script>', f'<script src="{base}assets/js/nav.js"></script>'
    if dj not in s or s.index(dj) > s.index(nj):
        s = s.replace(dj + "\n", "").replace(nj, dj + "\n" + nj)
    s = re.sub(r'<script src="https?://[^"]+"></script>\s*', "", s)
    open(path, "w", encoding="utf-8").write(s)


# 5. Auto-discovery de HTMLs auxiliares
aux, aborted, t0 = [], False, time.time()
for root_rel in ("_reversa_sdd", ".reversa"):
    base_dir = os.path.join(ROOT, root_rel)
    for dp, dns, fns in os.walk(base_dir):
        depth = os.path.relpath(dp, base_dir).count(os.sep)
        dns[:] = [d for d in dns if depth < 6 and not (root_rel == ".reversa" and d in ("_config", "context"))]
        if time.time() - t0 > 10:
            aborted = True
            break
        for fn in fns:
            if fn.endswith(".html"):
                p = os.path.join(dp, fn)
                head = open(p, encoding="utf-8", errors="replace").read(8000)
                m = re.search(r'<meta name="reversa-category" content="([^"]+)"', head)
                if m:
                    g = lambda k: (re.search(rf'<meta name="{k}" content="([^"]+)"', head) or [None, None])[1]
                    t = re.search(r"<title>(.*?)</title>", head, re.S)
                    aux.append({"path": os.path.relpath(p, ROOT), "category": m.group(1), "producer": g("reversa-producer-agent"),
                                "generated_at": g("reversa-generated-at"), "title": t.group(1).strip() if t else fn})

# 8. Placeholder da página omitida (fora do nav)
ph = render("topologia", "Topologia (omitida)", """
<h1>Topologia</h1>
<div class="reversa-warning-banner">Página omitida: <code>_reversa_sdd/architecture.md</code> não existe neste projeto greenfield.</div>
<p>Esta página compararia lado a lado as variantes de topologia (legado, moderno, híbrido) detectadas pelo <code>/reversa-architect</code>.
Para habilitar, rode <code>/reversa</code> (ou <code>/reversa-architect</code>) e depois <code>/reversa-docs</code> de novo.</p>
<p>Enquanto isso, a <a href="arquitetura.html">Arquitetura</a> mostra componentes e dependências reais do código.</p>
""", AGENT, "topologia", meta='<meta name="reversa-placeholder" content="true">')
write_page("topologia.html", ph)

# 6. index.html
fi = RV["featuresIndex"]
n_files = len(RV["modules"].get("modules", []))
n_terms = len(RV["glossary"].get("concepts", []))
CARDS = [("arquitetura.html", "Arquitetura 3D", f"Camada nativa Rust com fallback Python, cadeia de áudio, componentes por camada e Code City com {n_files} arquivos."),
         ("modulos.html", "Módulos", "Grafo de importações entre pacotes, ciclos e pares mútuos."),
         ("metricas.html", "Métricas", "Tick Python × Rust, surge, testes, cobertura, benchmark de precisão e chunks do build."),
         ("timeline.html", "Timeline", "Do brief ao fecho da 003, a partir do progress.jsonl."),
         ("glossario.html", "Glossário", f"{n_terms} termos: lambda, VE, VVT, PyO3, ABI3, FFI, surge, WaveShaper, ciclo-limite PID e mais."),
         ("deck.html", "Deck", "10 slides para apresentar o projeto."),
         ("features/index.html", "Features", "Features 001, 002 e 003 e as 11 specs SDD.")]
aux_html = ""
for cat_id, label in (("review", "Code Reviews"), ("design-system", "Design System"), ("diagram", "Diagramas adicionais")):
    items = [a for a in aux if a["category"] == cat_id and not (a["producer"] or "").startswith("reversa-docs")]
    if items:
        aux_html += f"<h2>{label}</h2><ul>" + "".join(f'<li><a href="../{esc(a["path"])}">{esc(a["title"])}</a> <span class="muted">{esc(a["producer"] or "")}</span></li>' for a in items) + "</ul>"
idx_payload = f"""
<section class="hero">
  <div>{seal_svg}</div>
  <div>
    <p class="muted mono">seed {seed_hex[:8]} · estilo sóbrio · leitor: novo dev</p>
    <h1 style="font-size:40px">SimuladorRemap</h1>
    <p class="lead">Simulador e plataforma de treino de remap automotivo em dinamômetro: ECU OEM e standalone sobre um motor termodinâmico 0D/1D
    que ganha potência ou quebra com laudo da causa. Local-first, um container por estação. Desde a feature 003, os kernels do tick rodam em Rust
    quando a extensão está instalada.</p>
    <div><span class="badge">Python 3.12 · FastAPI</span><span class="badge">Rust · PyO3 ABI3</span><span class="badge">React 18 · TypeScript · Vite</span><span class="badge">física 1000 Hz</span>
    <span class="badge ok">benchmark &lt; 5 % nos 4 veículos</span><span class="badge ok">física 2,8× com Rust</span><span class="badge ok">627 vitest · 24+ Playwright</span></div>
  </div>
</section>
<h2>Comece por aqui</h2>
<div class="grid g3">{"".join(f'<a class="card" href="{h}"><h3>{esc(t)}</h3><p class="muted">{esc(d)}</p></a>' for h, t, d in CARDS if h in gen)}</div>
<h2>Features</h2>
<div class="grid g2">{"".join(f'<a class="card" href="{f["href"]}"><h3>{esc(f["id"])}</h3><p>{esc(f["title"])}</p></a>' for f in fi.get("features", []))}</div>
<h2>Para um novo dev</h2>
<ol>
<li>Leia a <a href="features/001-simulador-remap.html">feature 001</a> para entender o MVP e as 3 jornadas.</li>
<li>Leia a <a href="features/003-rust-audio-qa-total.html">feature 003</a> antes de mexer em <code>physics</code>, <code>ecu</code> ou <code>damage</code>: toda mudança no hot path precisa de paridade com o Rust.</li>
<li>Veja a <a href="arquitetura.html">arquitetura</a>: o laço <code>sensors → ecu → physics → damage → telemetry</code> é o coração.</li>
<li>Consulte o <a href="glossario.html">glossário</a> antes de ler as specs em <code>_reversa_sdd/sdd/</code>.</li>
<li>Suba o ambiente com <code>make dev</code>, compile a extensão com <code>make native</code> (opcional) e rode <code>make check</code> antes de cada entrega.</li>
</ol>
{aux_html or '<p class="muted">Nenhum HTML auxiliar com meta reversa-category encontrado em _reversa_sdd/ e .reversa/.</p>'}
<p class="muted">Página omitida: Topologia (sem <code>_reversa_sdd/architecture.md</code>). Placeholder em <a href="topologia.html">topologia.html</a>.</p>
"""
write_page("index.html", render("index", "Índice", idx_payload, AGENT, "index", category="index"))

pages = sorted(set(st["pagesGenerated"]) | {"index.html"})
for rel in pages + ["topologia.html"]:
    backpatch(rel)

# 7. Validação de links
broken = []
for rel in pages + ["topologia.html"]:
    s = open(os.path.join(DOCS, rel), encoding="utf-8").read()
    for href in re.findall(r'href="([^"#]+)', s):
        if re.match(r"^(https?:|mailto:|data:)", href):
            continue
        target = os.path.normpath(os.path.join(DOCS, os.path.dirname(rel), href))
        if not os.path.exists(target):
            broken.append({"from": rel, "href": href, "expected_path": os.path.relpath(target, DOCS)})

# 9. Smoke test (http.server + GET + grep)
ERR_PAT = ["is not defined", "Failed to fetch", "Erro ao carregar", "Access to fetch", "NetworkError"]
errors = []
class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a, **k):
        pass

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            pass


handler = partial(Quiet, directory=DOCS)
srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
th = threading.Thread(target=srv.serve_forever, daemon=True)
th.start()
port = srv.server_address[1]
checked = 0
for rel in pages:
    url = f"http://127.0.0.1:{port}/{rel}"
    try:
        body = urllib.request.urlopen(url, timeout=10).read().decode("utf-8")
    except Exception as e:  # noqa: BLE001
        errors.append({"page": rel, "kind": "http", "detail": str(e)})
        continue
    for src in re.findall(r'<script src="([^"]+)"', body):
        if src.startswith(("http://", "https://")):
            errors.append({"page": rel, "kind": "cdn", "detail": src})
            continue
        su = urllib.parse.urljoin(url, src)
        try:
            resp = urllib.request.urlopen(su, timeout=10)
            resp.read()
            code = resp.status
            checked += 1
            if code != 200:
                errors.append({"page": rel, "kind": "asset", "detail": f"{src} -> {code}"})
        except Exception as e:  # noqa: BLE001
            errors.append({"page": rel, "kind": "asset", "detail": f"{src} -> {e}"})
    for pat in ERR_PAT:
        if pat in body:
            errors.append({"page": rel, "kind": "pattern", "detail": pat})
    if re.search(r"\bfetch\s*\(", body):
        errors.append({"page": rel, "kind": "fetch", "detail": "fetch() local na página"})
    for marker in ("<!-- NAV_LINKS -->", "<!-- MINI_SEAL_SVG -->", "<!-- PAYLOAD -->"):
        if marker in body:
            errors.append({"page": rel, "kind": "marker", "detail": marker})
srv.shutdown()

# 10. Telemetria final
st = register("publisher", AGENT, ["index.html"])
st = load_json(STATE)
for rel in pages + ["topologia.html"]:
    with open(os.path.join(DOCS, rel), encoding="utf-8") as f:
        prev = st["pages"].get(rel, {"agent": AGENT})
        st["pages"][rel] = {"status": "created", "agent": prev["agent"], "hash": sha(f.read())}
st["pages"]["topologia.html"]["status"] = "placeholder"
start_ms = int(open(os.path.join(DOCS, ".logs/start_ms.txt")).read().strip())
vendor = sorted(os.listdir(os.path.join(DOCS, "assets/vendor")))
st.update({"lastCheckpoint": now(), "pipelineDurationMs": int(time.time() * 1000) - start_ms,
           "pagesGenerated": pages, "auxiliaryHtmls": aux, "auxiliaryHtmlsDiscovered": len(aux),
           "auxiliaryDiscoveryAborted": aborted, "vendorFiles": vendor, "smokeTestFailed": bool(errors),
           "smokeTestErrors": errors, "smokeTestAssetsChecked": checked, "brokenLinks": broken,
           "sourceNotes": ["soul.md ausente: glossário derivado do glossário da 001, das specs e da 002",
                           "chronicle.md ausente: timeline derivada de progress.jsonl e datas dos artefatos",
                           "features: _reversa_forward/001, 002 e 003 (não há _reversa_sdd/*/requirements.md)",
                           "003: métricas de desempenho, áudio e QA vêm dos relatórios de verificação da feature; total do pytest da 003 não registrado",
                           "cobertura do backend: backend/coverage.json é da 002 (sem nova medição na 003)"],
           "nextSuggested": "Fechar T027 (make check com nativo ligado e desligado); /reversa-sync para o adendo da 003 (T030); /reversa para gerar soul e chronicle"})
save_json(STATE, st)
print(json.dumps({"pages": pages, "aux": len(aux), "broken": broken, "smokeErrors": errors, "assetsChecked": checked,
                  "durationS": st["pipelineDurationMs"] // 1000}, ensure_ascii=False, indent=1))
