"""Chassis e utilitários compartilhados pelos 4 agentes do Time Reversa Docs."""
import sys
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

import hashlib
import html
import json
import os
from datetime import datetime, timezone

DOCS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ROOT = os.path.abspath(os.path.join(DOCS, ".."))
DATA = os.path.join(DOCS, "assets", "data")
STATE = os.path.join(DOCS, ".state.json")
CONFIG = os.path.join(DOCS, ".config.json")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def esc(s):
    return html.escape(str(s), quote=True)


def sha(text):
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, obj, indent=2):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)


def load_state():
    st = load_json(STATE)
    if not st:
        st = {"schemaVersion": 1, "startedAt": now(), "completedAgents": [], "pendingAgents":
              ["mapper", "analyst", "storyteller", "publisher"], "pages": {}, "pagesGenerated": [],
              "pagesOmitted": []}
    return st


def register(agent_key, agent_name, written, omitted=()):
    st = load_state()
    for rel in written:
        with open(os.path.join(DOCS, rel), encoding="utf-8") as f:
            st["pages"][rel] = {"status": "created", "agent": agent_name, "hash": sha(f.read())}
        if rel not in st["pagesGenerated"]:
            st["pagesGenerated"].append(rel)
    for page, reason in omitted:
        if not any(o["page"] == page for o in st["pagesOmitted"]):
            st["pagesOmitted"].append({"page": page, "reason": reason})
    if agent_key not in st["completedAgents"]:
        st["completedAgents"].append(agent_key)
    st["pendingAgents"] = [a for a in st.get("pendingAgents", []) if a != agent_key]
    st["lastCheckpoint"] = now()
    save_json(STATE, st)
    return st


VIEWER = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title><!-- TITLE --> | SimuladorRemap</title>
<meta name="reversa-category" content="<!-- REVERSA_CATEGORY -->">
<meta name="reversa-producer-agent" content="<!-- REVERSA_PRODUCER_AGENT -->">
<meta name="reversa-template" content="<!-- REVERSA_TEMPLATE -->">
<meta name="reversa-generated-at" content="<!-- GENERATED_AT -->">
<!-- META_EXTRAS -->
<link rel="stylesheet" href="<!-- BASE -->assets/css/site.css">
<!-- HEAD_EXTRAS -->
</head>
<body data-style="<!-- VISUAL_STYLE -->" data-page-id="<!-- PAGE_ID -->" data-base="<!-- BASE -->">
<a class="skip" href="#main">Pular para o conteúdo</a>
<header class="rv-header">
  <a class="rv-brand" href="<!-- BASE -->index.html"><span class="seal-slot"><!-- MINI_SEAL_SVG --></span><span>SimuladorRemap <small>docs</small></span></a>
  <nav class="reversa-doc-nav" aria-label="Navegação do mini-site"><!-- NAV_LINKS --></nav>
</header>
<main id="main" class="rv-main">
<!-- PAYLOAD -->
</main>
<footer class="rv-footer">Gerado por <!-- REVERSA_PRODUCER_AGENT --> em <!-- GENERATED_AT --> · Time Reversa Docs · funciona offline via file://</footer>
<!-- SCRIPTS -->
</body>
</html>
"""


def render(page_id, title, payload, agent, template, *, base="", head="", scripts="",
           category="diagram", meta=""):
    cfg = load_json(CONFIG, {})
    style = cfg.get("interview", {}).get("visualStyle", "sober")
    base_scripts = (f'<script src="{base}assets/js/data.js"></script>\n'
                    f'<script src="{base}assets/js/nav.js"></script>\n'
                    f'<script src="{base}assets/js/sidebar.js"></script>\n')
    out = VIEWER
    rep = {
        "<!-- TITLE -->": esc(title), "<!-- PAGE_ID -->": page_id,
        "<!-- REVERSA_CATEGORY -->": category, "<!-- REVERSA_PRODUCER_AGENT -->": agent,
        "<!-- REVERSA_TEMPLATE -->": template, "<!-- VISUAL_STYLE -->": style,
        "<!-- GENERATED_AT -->": now(), "<!-- BASE -->": base, "<!-- META_EXTRAS -->": meta,
        "<!-- HEAD_EXTRAS -->": head, "<!-- PAYLOAD -->": payload,
        "<!-- SCRIPTS -->": base_scripts + scripts,
    }
    for k, v in rep.items():
        out = out.replace(k, v)
    return out


def write_page(rel, content):
    path = os.path.join(DOCS, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return rel
