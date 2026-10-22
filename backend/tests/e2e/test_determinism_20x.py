"""E2E de determinismo: 20 execuções de 30 s a 1000 Hz (T220, T453; RN-10; req RF-07; D-08).

Cada execução (``e2e_support.determinism_run``) corre num processo ``spawn`` novo: ``hatch-20t-gdi``
OEM-Stage do catálogo, E27, ``seed`` 42, ``ProfiledEcu``, ``DamageConfig`` padrão e
``TelemetrySampler``; ``sweep_pull`` 2000 → 6500 rpm a 150 rpm/s (30 s de fase ``running``).
O log é fechado pelo ``Logbook`` de produção e avaliado pelo avaliador puro (``stage1-oem``).
As 20 execuções têm de dar os mesmos 5 digests (simulation-bus 5): ``state_digest`` da física,
``damage_digest``, ``curve_sha256``, ``DataLog.sha256`` e ``evaluation_sha256``.

Digests de referência por arquitetura (T453) em ``tests/fixtures/digests/<arch>.json``:
``amd64`` é normativo (falha se divergir) e ``arm64`` é informativo (divergência só avisa,
porque o determinismo entre arquiteturas fica fora do MVP, engine-physics-core OQ-04).
Sem o arquivo da arquitetura o teste salta essa comparação com a instrução de geração:
``SIMREMAP_WRITE_DIGESTS=1 pytest -m e2e tests/e2e/test_determinism_20x.py`` (o ``amd64``
normativo tem de ser gravado numa máquina/CI x86-64 com a imagem de produção).
"""

from __future__ import annotations

import json
import os
import platform
import sys
import time
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from e2e_support import (
    DETERMINISM_REQUEST,
    DIGEST_KEYS,
    SEED,
    SIM_HZ,
    determinism_run,
    machine_arch,
    pool,
)

RUNS = 20
DIGESTS_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "digests"
NORMATIVE_ARCH = "amd64"
WRITE_ENV = "SIMREMAP_WRITE_DIGESTS"


@pytest.fixture(scope="module")
def executions() -> dict[str, Any]:
    start = time.perf_counter()
    with pool(RUNS) as executor:
        results = list(executor.map(determinism_run, [SEED] * RUNS))
    elapsed = time.perf_counter() - start
    print(f"\ndeterminismo: {RUNS} execuções em {elapsed:.1f} s (processos spawn)")
    return {"results": results, "elapsed_s": elapsed}


def test_twenty_runs_have_identical_digests(executions: dict[str, Any]) -> None:
    results = executions["results"]
    assert len(results) == RUNS
    for result in results:
        assert result["run_state"] == "completed"
        assert result["t_sim_s"] >= 30.0
        assert result["log_samples"] >= 30 * SIM_HZ
    for key in DIGEST_KEYS:
        values = {r[key] for r in results}
        assert len(values) == 1, f"{key}: {len(values)} valores distintos"
        (value,) = values
        assert isinstance(value, str) and len(value) == 64, key


def _reference_document(result: dict[str, Any]) -> dict[str, Any]:
    arch = machine_arch()
    return {
        "arch": arch,
        "normative": arch == NORMATIVE_ARCH,
        "note": (
            "Digests de referência do E2E de determinismo (T453; D-08). amd64 é normativo e "
            "tem de ser gerado em CI/x86-64 com a imagem de produção; arm64 é informativo."
        ),
        "config": {
            "vehicle_id": "hatch-20t-gdi",
            "profile_id": "oem-stage",
            "fuel_id": "e27",
            "seed": SEED,
            "sim_hz": SIM_HZ,
            "request": DETERMINISM_REQUEST,
            "evaluation_scenario": "stage1-oem",
        },
        "environment": {
            "machine": platform.machine(),
            "system": platform.system(),
            "python": platform.python_version(),
            "numpy": np.__version__,
        },
        "t_sim_s": result["t_sim_s"],
        "log_samples": result["log_samples"],
        "digests": {key: result[key] for key in DIGEST_KEYS},
    }


def test_reference_digests_for_this_architecture(executions: dict[str, Any]) -> None:
    result = executions["results"][0]
    current = _reference_document(result)
    path = DIGESTS_DIR / f"{current['arch']}.json"
    if os.environ.get(WRITE_ENV) == "1":
        DIGESTS_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n", "utf-8")
        print(f"\ndigests gravados em {path}", file=sys.stderr)
    if not path.exists():
        pytest.skip(
            f"sem digests de referência para {current['arch']}: gere com {WRITE_ENV}=1 "
            "nessa arquitetura (amd64 normativo em CI/x86-64)"
        )
    stored = json.loads(path.read_text("utf-8"))
    assert stored["config"] == current["config"], "configuração diferente da referência"
    diverged = {
        key: (stored["digests"][key], current["digests"][key])
        for key in DIGEST_KEYS
        if stored["digests"][key] != current["digests"][key]
    }
    if not diverged:
        return
    if current["arch"] == NORMATIVE_ARCH:
        pytest.fail(f"digests normativos ({NORMATIVE_ARCH}) divergentes: {diverged}")
    warnings.warn(
        f"digests informativos ({current['arch']}) divergentes da referência gravada "
        f"(ambiente {stored['environment']} → {current['environment']}): {sorted(diverged)}",
        stacklevel=1,
    )


def test_normative_reference_documents_the_architecture() -> None:
    """Os arquivos gravados declaram a arquitetura e o caráter normativo/informativo."""
    files = sorted(DIGESTS_DIR.glob("*.json"))
    assert files, f"nenhum digest de referência em {DIGESTS_DIR}"
    for path in files:
        doc = json.loads(path.read_text("utf-8"))
        assert doc["arch"] == path.stem
        assert doc["normative"] is (doc["arch"] == NORMATIVE_ARCH)
        assert set(doc["digests"]) == set(DIGEST_KEYS)
