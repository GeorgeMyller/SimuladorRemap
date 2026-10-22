"""Varredura zero-PII (T090, T451; platform RF-20; data-model 7.3; RN-03).

- T090: colunas SQLModel e campos dos contratos Pydantic sem nomes de PII; ``nickname`` só
  nas colunas autorizadas.
- T451: ``scenario_event.data_json``, ``datalog`` (linhas e arquivos ``.simlog.gz``),
  ``forensic_report`` e logs estruturados sem ``nickname`` nem chaves de PII, com uma
  tentativa real (perfil com nickname-canário) e um laudo real do modelo de dano.
"""

from __future__ import annotations

import asyncio
import gzip
import importlib
import json
import pkgutil
import re
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager
from pydantic import BaseModel
from sqlalchemy import text

import simremap
from simremap.api.main import create_app
from simremap.damage.contracts import ForensicReport
from simremap.db.models import metadata
from simremap.telemetry.contracts import DataLog, DataLogHeader

PII = re.compile(
    r"(?i)(email|e_mail|phone|telefone|cpf|documento|address|ip_addr|client_ip|remote_addr|"
    r"real_name|nome_real|full_name)"
)
NICKNAME_COLUMNS = frozenset(
    {
        ("player_profile", "nickname"),
        ("attempt", "nickname"),
        ("calibration_version", "author_nickname"),
    }
)
"""Únicas colunas autorizadas a guardar ``nickname`` (data-model 7.3)."""

_SKIP_PREFIXES = ("simremap.db.migrations",)


def _modules() -> Iterator[str]:
    for info in pkgutil.walk_packages(simremap.__path__, prefix="simremap."):
        if not info.name.startswith(_SKIP_PREFIXES):
            yield info.name


def _pydantic_models() -> list[type[BaseModel]]:
    models: list[type[BaseModel]] = []
    for name in _modules():
        try:
            module = importlib.import_module(name)
        except ImportError:
            continue  # componente em construção: os seus testes cobrem o import
        for value in vars(module).values():
            if (
                isinstance(value, type)
                and issubclass(value, BaseModel)
                and value.__module__ == module.__name__
            ):
                models.append(value)
    return models


def test_no_pii_columns_in_tables() -> None:
    assert metadata.tables, "metadata sem tabelas"
    for table in metadata.tables.values():
        for column in table.columns:
            assert not PII.search(column.name), f"{table.name}.{column.name}"
            if "nickname" in column.name.lower():
                assert (table.name, column.name) in NICKNAME_COLUMNS, f"{table.name}.{column.name}"


def test_no_pii_fields_in_pydantic_contracts() -> None:
    models = _pydantic_models()
    assert len(models) >= 5
    offenders = [
        f"{model.__module__}.{model.__qualname__}.{field}"
        for model in models
        for field in model.model_fields
        if PII.search(field)
    ]
    assert offenders == []


@pytest.mark.parametrize(
    "name", ["email", "user_phone", "cpf", "home_address", "client_ip", "real_name", "ip_addr"]
)
def test_pattern_catches_pii(name: str) -> None:
    assert PII.search(name)


@pytest.mark.parametrize("name", ["nickname", "vehicle_id", "install_id", "profile_id", "role"])
def test_pattern_allows_domain_fields(name: str) -> None:
    assert not PII.search(name)


# --------------------------------------------------------------------------- T451

CANARY = "canario_pii_77"
FORBIDDEN_NICKNAME_MODELS: tuple[type[BaseModel], ...] = (ForensicReport, DataLog, DataLogHeader)
"""Contratos gravados em ``forensic_report.report_json`` e ``datalog`` (sem nickname)."""


def _field_names(model: type[BaseModel], seen: set[type[BaseModel]] | None = None) -> set[str]:
    """Nomes de campos do modelo e dos submodelos (recursivo)."""
    seen = set() if seen is None else seen
    if model in seen:
        return set()
    seen.add(model)
    names: set[str] = set()
    for name, field in model.model_fields.items():
        names.add(name)
        for arg in _type_args(field.annotation):
            if isinstance(arg, type) and issubclass(arg, BaseModel):
                names |= _field_names(arg, seen)
    return names


def _type_args(annotation: Any) -> Iterator[Any]:
    yield annotation
    for arg in getattr(annotation, "__args__", ()) or ():
        yield from _type_args(arg)


def _json_keys(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for key, inner in value.items():
            yield str(key)
            yield from _json_keys(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _json_keys(inner)


def _offending_keys(value: Any) -> list[str]:
    return [k for k in _json_keys(value) if PII.search(k) or "nickname" in k.lower()]


@pytest.mark.parametrize("model", FORBIDDEN_NICKNAME_MODELS, ids=lambda m: m.__name__)
def test_stored_report_and_log_contracts_have_no_nickname(model: type[BaseModel]) -> None:
    names = _field_names(model)
    assert len(names) > 5
    assert [n for n in names if "nickname" in n.lower() or PII.search(n)] == []


def test_real_forensic_report_has_no_pii() -> None:
    """Laudo real (jornada do Lucas no modelo de dano) sem chaves de PII nem nickname."""
    damage_tests = Path(__file__).resolve().parents[1] / "damage"
    sys.path.insert(0, str(damage_tests))
    try:
        kfm = importlib.import_module("kfm_helpers")
    finally:
        sys.path.remove(str(damage_tests))
    from simremap.damage.model import DamageModel

    model = DamageModel(
        kfm.SPEC_CONFIG, kfm.build_hatch(), kfm.build_e27(), 42, True, session_id="s" * 32
    )
    kfm.run_lucas(model)
    report = kfm.lucas_report(model)
    payload = report.model_dump(mode="json")
    assert report.causal_chain
    assert _offending_keys(payload) == []


async def _poll(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    done: Callable[[dict[str, Any]], bool],
    timeout_s: float = 180.0,
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        body: dict[str, Any] = (await client.get(url, headers=headers)).json()
        if done(body):
            return body
        await asyncio.sleep(0.2)
    raise AssertionError(f"tempo esgotado em {url}")


async def test_attempt_flow_keeps_nickname_out_of_events_logs_and_datalog(
    settings_factory: Callable[..., Any],
    caplog: pytest.LogCaptureFixture,
    log_events: Callable[[pytest.LogCaptureFixture], list[dict[str, Any]]],
) -> None:
    """Tentativa real com nickname-canário: ele só pode existir nas colunas autorizadas."""
    settings = settings_factory(log_level="INFO", worker_mode="process")
    app = create_app(settings)
    app.state.dyno_task_options = {"steps_per_tick": 10}
    caplog.set_level("INFO")
    async with LifespanManager(app, startup_timeout=60, shutdown_timeout=60) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t", timeout=60) as c:
            created = await c.post("/api/v1/profiles", json={"nickname": CANARY})
            assert created.status_code == 201, created.text
            headers = {"X-Player-Profile-Id": created.json()["profile_id"]}
            started = await c.post("/api/v1/scenarios/stage1-oem/attempts", headers=headers)
            assert started.status_code == 201, started.text
            url = f"/api/v1/attempts/{started.json()['attempt_id']}"
            attempt = await _poll(c, url, headers, lambda b: b["state"] != "preparing")
            assert attempt["state"] == "in_progress", attempt
            submit = await c.post(
                f"{url}/submit", headers=headers, json={"calibration_id": attempt["calibration_id"]}
            )
            assert submit.status_code == 202, submit.text
            await _poll(c, f"{url}/evaluation", headers, lambda b: b["status"] != "pending")
        async with app.state.sessionmaker() as db:
            events = (await db.execute(text("SELECT kind, data_json FROM scenario_event"))).all()
            datalogs = (await db.execute(text("SELECT * FROM datalog"))).mappings().all()
            reports = (await db.execute(text("SELECT report_json FROM forensic_report"))).all()
            nick_rows = (
                await db.execute(
                    text("SELECT nickname FROM attempt WHERE nickname = :n"), {"n": CANARY}
                )
            ).all()
    assert nick_rows, "o nickname deve ficar na coluna autorizada attempt.nickname"
    assert {k for k, _ in events} >= {"attempt_started", "baseline_completed", "attempt_submitted"}
    for kind, data in events:
        raw = data if isinstance(data, str) else json.dumps(data)
        assert CANARY not in raw, kind
        assert _offending_keys(json.loads(raw)) == [], kind
    assert datalogs, "a puxada base deve gravar um datalog"
    for row in datalogs:
        assert CANARY not in json.dumps({k: str(v) for k, v in row.items()})
        path = Path(str(row["path"]))
        path = path if path.is_absolute() else settings.data_dir / path
        content = gzip.decompress(path.read_bytes())
        assert CANARY.encode() not in content
        header = json.loads(content.split(b"\n", 1)[0]) if content[:1] == b"{" else {}
        assert _offending_keys(header) == []
    for (report,) in reports:
        raw = report if isinstance(report, str) else json.dumps(report)
        assert CANARY not in raw and _offending_keys(json.loads(raw)) == []
    records = log_events(caplog)
    assert any(e.get("event") == "http.request" for e in records)
    leaked = [e.get("event") for e in records if CANARY in json.dumps(e, default=str)]
    assert leaked == []
    pii_keys = [(e.get("event"), k) for e in records for k in e if PII.search(str(k))]
    assert pii_keys == []
