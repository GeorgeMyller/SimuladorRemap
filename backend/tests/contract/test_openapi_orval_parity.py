"""Paridade entre o OpenAPI do backend e os tipos gerados por ``orval`` (T172; D-24).

O frontend consome ``frontend/src/lib/api/generated/`` (``make api-types``). Este teste falha
quando o OpenAPI muda e os tipos não foram regenerados, ou quando a geração perde clientes:

- cada schema de ``components.schemas`` tem ``model/<camelCase>.ts`` com o tipo exportado;
- nenhum ficheiro de ``model/`` é órfão (sem schema nem operação de origem);
- cada ``operationId`` tem a função do cliente ``fetch`` e o schema zod da resposta;
- o ``openapi.json`` usado na geração (``frontend/openapi.json``) é igual ao atual.

Sem o diretório gerado o teste é saltado (rode ``make api-types``). Variáveis:
``SIMREMAP_ORVAL_GENERATED`` (diretório gerado) e ``SIMREMAP_OPENAPI_SNAPSHOT`` (JSON usado).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
DEFAULT_GENERATED = REPO / "frontend" / "src" / "lib" / "api" / "generated"
DEFAULT_SNAPSHOT = REPO / "frontend" / "openapi.json"
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def orval_name(name: str) -> str:
    """Nome camelCase do orval para schemas e operações (``ProblemDetail`` → ``problemDetail``)."""
    parts = [p for p in re.split(r"[^0-9A-Za-z]+", name) if p]
    joined = "".join(p[0].upper() + p[1:] for p in parts)
    return joined[:1].lower() + joined[1:]


def pascal(name: str) -> str:
    camel = orval_name(name)
    return camel[:1].upper() + camel[1:]


@pytest.fixture(scope="module")
def generated_dir() -> Path:
    path = Path(os.environ.get("SIMREMAP_ORVAL_GENERATED", DEFAULT_GENERATED))
    if not (path / "model").is_dir():
        pytest.skip(f"tipos orval ausentes em {path}; rode `make api-types`")
    return path


@pytest.fixture(scope="module")
def spec(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    from simremap.api.main import create_app
    from simremap.core.config import Settings

    root = tmp_path_factory.mktemp("orval")
    settings = Settings(
        _env_file=None,
        env="test",
        data_dir=root,
        static_dir=None,
        database_url=f"sqlite+aiosqlite:///{root.as_posix()}/o.db",
        worker_mode="thread",
        log_level="WARNING",
    )
    data: dict[str, Any] = create_app(settings).openapi()
    return data


def _operations(spec: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    ops: list[tuple[str, str, dict[str, Any]]] = []
    for path, item in spec.get("paths", {}).items():
        for method, op in item.items():
            if method in HTTP_METHODS and isinstance(op, dict) and op.get("operationId"):
                ops.append((path, method, op))
    return ops


def _client_sources(generated: Path) -> str:
    """Conteúdo de todos os ficheiros gerados fora de ``model/``."""
    texts = [
        p.read_text(encoding="utf-8")
        for p in generated.rglob("*.ts")
        if "model" not in p.relative_to(generated).parts
    ]
    return "\n".join(texts)


def test_every_schema_has_a_generated_model(spec: dict[str, Any], generated_dir: Path) -> None:
    schemas = spec.get("components", {}).get("schemas", {})
    assert schemas, "OpenAPI sem components.schemas"
    missing: list[str] = []
    for name in schemas:
        file = generated_dir / "model" / f"{orval_name(name)}.ts"
        if not file.is_file():
            missing.append(f"{name} (model/{file.name} ausente)")
            continue
        if not re.search(
            rf"export (interface|type|const) {re.escape(pascal(name))}\b",
            file.read_text(encoding="utf-8"),
        ):
            missing.append(f"{name} (tipo {pascal(name)} não exportado)")
    assert not missing, "Tipos orval desatualizados; rode `make api-types`: " + ", ".join(missing)


def test_no_orphan_generated_models(spec: dict[str, Any], generated_dir: Path) -> None:
    roots = [orval_name(n) for n in spec.get("components", {}).get("schemas", {})]
    roots += [orval_name(op["operationId"]) for _, _, op in _operations(spec)]
    orphans = [
        f.name
        for f in sorted((generated_dir / "model").glob("*.ts"))
        if f.stem != "index" and not any(f.stem.startswith(r) for r in roots)
    ]
    assert not orphans, "Modelos gerados sem origem no OpenAPI atual (regenere): " + ", ".join(
        orphans
    )


def test_every_operation_has_fetch_client_and_zod_response(
    spec: dict[str, Any], generated_dir: Path
) -> None:
    sources = _client_sources(generated_dir)
    problems: list[str] = []
    for path, method, op in _operations(spec):
        fn = orval_name(op["operationId"])
        if not re.search(rf"export (const|async function|function) {re.escape(fn)}\b", sources):
            problems.append(f"{method.upper()} {path}: cliente {fn} ausente")
        responses = op.get("responses", {})
        ok = next((responses[c] for c in ("200", "201", "202") if c in responses), None)
        has_json = bool(
            ok
            and "application/json" in ok.get("content", {})
            and ok["content"]["application/json"].get("schema")
        )
        if has_json and not re.search(
            rf"export const {re.escape(pascal(op['operationId']))}Response\b", sources
        ):
            problems.append(
                f"{method.upper()} {path}: schema zod {pascal(op['operationId'])}Response ausente"
            )
    assert not problems, "Clientes orval incompletos: " + "; ".join(problems)


def test_generation_input_matches_current_openapi(
    spec: dict[str, Any], generated_dir: Path
) -> None:
    snapshot = Path(os.environ.get("SIMREMAP_OPENAPI_SNAPSHOT", DEFAULT_SNAPSHOT))
    if not snapshot.is_file():
        pytest.skip(f"snapshot {snapshot} ausente (gerado por `make api-types`)")
    used = json.loads(snapshot.read_text(encoding="utf-8"))
    assert used.get("paths") == spec.get("paths"), (
        "openapi.json da geração difere do atual: rode `make api-types`"
    )
    assert used.get("components") == spec.get("components"), (
        "schemas mudaram desde a geração: rode `make api-types`"
    )


def test_orval_name_convention() -> None:
    assert orval_name("ProblemDetail") == "problemDetail"
    assert (
        orval_name("get_vehicle_api_v1_vehicles__vehicle_id__get")
        == "getVehicleApiV1VehiclesVehicleIdGet"
    )
    assert pascal("get_health_api_v1_health_get") == "GetHealthApiV1HealthGet"
