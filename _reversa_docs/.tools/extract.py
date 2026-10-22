"""Extrai modules.json e deps.json do SimuladorRemap (somente leitura do código)."""
import sys
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone

ROOT = sys.argv[1]
OUT = sys.argv[2]
NOW = datetime.now(timezone.utc).isoformat(timespec="seconds")

BRANCH_PY = re.compile(r"\b(if|elif|for|while|except|and|or|case|with)\b")
BRANCH_TS = re.compile(r"\b(if|for|while|case|catch)\b|&&|\|\||\?\?|\?(?!\.)")
PY_IMP = re.compile(r"^\s*(?:from\s+simremap\.(\w+)|import\s+simremap\.(\w+))", re.M)
PY_REL = re.compile(r"^\s*from\s+(\.{2,})(\w+)", re.M)
BRANCH_RS = re.compile(r"\b(if|for|while|match|loop)\b|=>|&&|\|\|")
RS_CRATE = re.compile(r"\bcrate::(\w+)")
NATIVE_USE = re.compile(r"simremap\.core\.native|simremap_rs")
NATIVE_OF = {"ecu": "tables", "physics": "cycle", "damage": "damage", "core": "lib"}
TS_IMP = re.compile(r"""(?:from|import)\s*\(?\s*["']([^"']+)["']""")

SKIP_DIRS = {"__pycache__", "node_modules", "generated", ".mypy_cache"}
modules = []


def walk(base, exts):
    for dp, dns, fns in os.walk(base):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            if os.path.splitext(fn)[1] in exts:
                yield os.path.join(dp, fn)


def loc_of(text):
    return sum(1 for ln in text.splitlines() if ln.strip() and not ln.strip().startswith(("#", "//")))


def add(path, layer, pkg, ftype, text, lang, deps):
    rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
    pat = {"python": BRANCH_PY, "rust": BRANCH_RS}.get(lang, BRANCH_TS)
    modules.append({
        "name": rel,
        "folder": f"{layer}/{pkg}",
        "layer": layer,
        "package": pkg,
        "loc": loc_of(text),
        "complexity": 1 + len(pat.findall(text)),
        "type": ftype,
        "language": lang,
        "deps": sorted(deps),
    })


# Backend: pacotes simremap.*
be_src = os.path.join(ROOT, "backend/src/simremap")
for p in walk(be_src, {".py"}):
    rel = os.path.relpath(p, be_src).split(os.sep)
    pkg = rel[0] if len(rel) > 1 else "simremap"
    text = open(p, encoding="utf-8", errors="replace").read()
    deps = set()
    for a, b in PY_IMP.findall(text):
        deps.add(a or b)
    for dots, name in PY_REL.findall(text):
        if len(dots) == 2 and len(rel) == 2:
            deps.add(name)
    deps.discard(pkg)
    nat = {f"native/{NATIVE_OF[pkg]}"} if pkg in NATIVE_OF and pkg != "core" and NATIVE_USE.search(text) else set()
    add(p, "backend", pkg, "code", text, "python", {f"backend/{d}" for d in deps if os.path.isdir(os.path.join(be_src, d))} | nat)

# Camada nativa: crate Rust simremap_rs (feature 003), distrito por submódulo
rs_src = os.path.join(ROOT, "backend/rust/simremap_rs/src")
for p in walk(rs_src, {".rs"}):
    rel = os.path.relpath(p, rs_src).split(os.sep)
    pkg = os.path.splitext(rel[0])[0]
    text = open(p, encoding="utf-8", errors="replace").read()
    deps = {f"native/{d}" for d in RS_CRATE.findall(text) if d != pkg and os.path.exists(os.path.join(rs_src, d + ".rs"))}
    if pkg == "lib":
        deps |= {"native/tables", "native/cycle", "native/damage"}
    add(p, "native", pkg, "code", text, "rust", deps)

# Backend: testes (agrupados pela pasta de teste)
be_tests = os.path.join(ROOT, "backend/tests")
for p in walk(be_tests, {".py"}):
    rel = os.path.relpath(p, be_tests).split(os.sep)
    pkg = rel[0] if len(rel) > 1 else "_root"
    text = open(p, encoding="utf-8", errors="replace").read()
    add(p, "backend-tests", pkg, "test", text, "python", set())

# Frontend: features, app, lib
fe_src = os.path.join(ROOT, "frontend/src")


def fe_group(path):
    rel = os.path.relpath(path, fe_src).split(os.sep)
    if rel[0] == "features" and len(rel) > 2:
        return rel[1]
    if rel[0] in ("app", "lib", "test") and len(rel) > 1:
        return rel[0]
    return "root"


for p in walk(fe_src, {".ts", ".tsx"}):
    grp = fe_group(p)
    text = open(p, encoding="utf-8", errors="replace").read()
    is_test = bool(re.search(r"\.test\.tsx?$", p)) or grp == "test"
    deps = set()
    for spec in TS_IMP.findall(text):
        target = None
        if spec.startswith("@/"):
            target = os.path.join(fe_src, spec[2:])
        elif spec.startswith("."):
            target = os.path.normpath(os.path.join(os.path.dirname(p), spec))
        if target:
            g = fe_group(target + ".ts")
            if g != grp:
                deps.add(g)
    add(p, "frontend", grp, "test" if is_test else "code", text, "typescript",
        set() if is_test else {f"frontend/{d}" for d in deps})

# Frontend: specs Playwright (frontend/e2e)
for p in walk(os.path.join(ROOT, "frontend/e2e"), {".ts"}):
    text = open(p, encoding="utf-8", errors="replace").read()
    add(p, "frontend", "e2e", "test", text, "typescript", set())

# Grafo agregado por pacote
edges = Counter()
for m in modules:
    for d in m["deps"]:
        edges[(m["folder"], d)] += 1
pkgs = sorted({m["folder"] for m in modules if m["type"] == "code"})
adj = defaultdict(set)
for (a, b) in edges:
    adj[a].add(b)

# Ciclos simples (Tarjan SCC)
index, low, stack, on, sccs, counter = {}, {}, [], set(), [], [0]


def strong(v):
    index[v] = low[v] = counter[0]
    counter[0] += 1
    stack.append(v)
    on.add(v)
    for w in adj[v]:
        if w not in index:
            strong(w)
            low[v] = min(low[v], low[w])
        elif w in on:
            low[v] = min(low[v], index[w])
    if low[v] == index[v]:
        comp = []
        while True:
            w = stack.pop()
            on.discard(w)
            comp.append(w)
            if w == v:
                break
        if len(comp) > 1:
            sccs.append(sorted(comp))


sys.setrecursionlimit(10000)
for v in pkgs:
    if v not in index:
        strong(v)

for m in modules:
    m.pop("deps")

os.makedirs(OUT, exist_ok=True)
json.dump({"schemaVersion": 1, "generatedAt": NOW, "root": "SimuladorRemap", "modules": modules},
          open(os.path.join(OUT, "modules.json"), "w", encoding="utf-8"), ensure_ascii=False)
json.dump({
    "schemaVersion": 1, "generatedAt": NOW, "granularity": "package",
    "nodes": [{"id": p, "layer": p.split("/")[0]} for p in pkgs],
    "edges": [{"from": a, "to": b, "weight": w} for (a, b), w in sorted(edges.items())],
    "cycles": sccs,
}, open(os.path.join(OUT, "deps.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

agg = defaultdict(lambda: [0, 0])
for m in modules:
    agg[(m["folder"], m["type"])][0] += 1
    agg[(m["folder"], m["type"])][1] += m["loc"]
for k in sorted(agg):
    print(k, agg[k])
print("modules", len(modules), "edges", len(edges), "cycles", sccs)
