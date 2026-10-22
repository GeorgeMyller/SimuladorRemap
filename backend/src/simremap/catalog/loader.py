"""Carga e validação do catálogo no arranque (vehicle-catalog RF-01 a RF-13, RF-19 a RF-29).

Ordem:
1. Diretório: existe e é legível (``CATALOG_DIR_UNAVAILABLE``).
2. Inventário: links simbólicos para fora da raiz (``PATH_OUTSIDE_CATALOG``), arquivos
   fora do manifesto (``FILE_NOT_IN_MANIFEST``) ou em falta (``FILE_MISSING``).
3. Por arquivo, antes do parse: tamanho ≤ 2 MiB (``FILE_TOO_LARGE``), SHA-256 dos bytes
   igual ao manifesto (``FILE_HASH_MISMATCH``), UTF-8 sem BOM (``FILE_ENCODING_INVALID``)
   e JSON válido com linha e coluna (``JSON_INVALID``).
4. Contratos Pydantic (``SCHEMA_INVALID`` e ``GRID_*``) com ponteiro JSON, marcas em
   textos exibidos (``TRADEMARK_IN_DISPLAY_TEXT``), ``vehicle_id`` = diretório, os 4
   veículos e os 4 combustíveis canónicos.
5. Validações cruzadas: curvas (RF-12, RF-13, EC-07), calibrações de fábrica (RF-19,
   RF-20, EC-12, EC-13) e proveniência (RF-06).
6. Hashes: ``data_sha256`` por veículo, ``catalog_sha256`` e ``benchmark_sha256``.

Qualquer erro termina em ``CatalogInvalid`` (``code = CATALOG_INVALID``, saída 4) com a
lista completa de ``CatalogIssue``; nada é carregado parcialmente. Nomes começados por
``.`` e ``__pycache__`` são ignorados no inventário.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from pydantic import Field, ValidationError

from simremap.catalog.canonical import benchmark_sha256, canonical_sha256, sha256_bytes
from simremap.catalog.contracts import (
    FUEL_IDS,
    CatalogModel,
    FuelSpec,
    ReferenceCurve,
    VehicleSpec,
)
from simremap.catalog.drivetrain import crank_power_kw, crank_to_wheel_kw
from simremap.catalog.errors import CatalogInvalid, CatalogIssue
from simremap.catalog.provenance import estimated_fields, invalid_provenance_pointers
from simremap.catalog.settings import DEFAULT_CATALOG_DIR
from simremap.catalog.trademarks import find_trademarks
from simremap.core.contracts import Sha256Hex

__all__ = [
    "CALIBRATION_VALIDATOR_MODULES",
    "CANONICAL_VEHICLE_IDS",
    "MANIFEST_NAME",
    "MAX_FILE_BYTES",
    "CalibrationValidator",
    "Catalog",
    "ManifestEntry",
    "ManifestFile",
    "VehicleEntry",
    "clear_calibration_validators",
    "load_catalog_data",
    "register_calibration_validator",
    "registered_calibration_validators",
]

MANIFEST_NAME: Final = "manifest.json"
MAX_FILE_BYTES: Final = 2 * 1024 * 1024
POWER_TOLERANCE: Final = 0.01  # RF-13: erro ≤ 1 %
CANONICAL_VEHICLE_IDS: Final[tuple[str, ...]] = (
    "hatch-20t-gdi",
    "coupe-30t-i6",
    "classic-20t-swap",
    "muscle-v8-sc",
)
CALIBRATION_VALIDATOR_MODULES: Final[tuple[str, ...]] = ("simremap.ecu.calibration",)
"""Módulos importados antes da validação das calibrações de fábrica: o ``ecu-core`` chama
``register_calibration_validator`` no import (RF-20). Ausentes no Sprint 1."""

_FUEL_RE: Final = re.compile(r"^fuels/(?P<fuel>[^/]+)\.json$")
_VEHICLE_RE: Final = re.compile(r"^vehicles/(?P<vid>[^/]+)/vehicle\.json$")
_CURVE_RE: Final = re.compile(r"^vehicles/(?P<vid>[^/]+)/reference-curves/(?P<cid>[^/]+)\.json$")
_CALIB_RE: Final = re.compile(r"^vehicles/(?P<vid>[^/]+)/calibrations/(?P<pid>[^/]+)\.json$")
_SEMVER: Final = r"^\d+\.\d+\.\d+$"

CalibrationValidator = Callable[[dict[str, object]], None]
_CALIBRATION_VALIDATORS: list[CalibrationValidator] = []


def register_calibration_validator(fn: CalibrationValidator) -> None:
    """Chamado pelo ecu-core no import; o loader valida as calibrações de fábrica com ``fn``.

    ``fn`` recebe o payload JSON da calibração e lança uma exceção com atributo ``code``
    (ex.: ``EcuValidationError("TABLE_AXIS_NOT_MONOTONIC")``) ou ``ValueError`` para
    recusar. Registar a mesma função duas vezes não a duplica.
    """
    if fn not in _CALIBRATION_VALIDATORS:
        _CALIBRATION_VALIDATORS.append(fn)


def registered_calibration_validators() -> tuple[CalibrationValidator, ...]:
    return tuple(_CALIBRATION_VALIDATORS)


def clear_calibration_validators() -> None:
    """Remove os validadores registados (uso em testes)."""
    _CALIBRATION_VALIDATORS.clear()


# --------------------------------------------------------------------------- modelos


class ManifestFile(CatalogModel):
    path: str = Field(min_length=1, max_length=200, pattern=r"^[0-9a-z][-_0-9a-z./]*\.json$")
    sha256: Sha256Hex


class ManifestEntry(CatalogModel):
    catalog_version: str = Field(pattern=_SEMVER)
    files: list[ManifestFile] = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class VehicleEntry:
    spec: VehicleSpec
    curves: tuple[ReferenceCurve, ...]
    calibrations: Mapping[str, Mapping[str, Any]]  # profile_id → payload (só leitura)
    estimated_fields: tuple[str, ...]
    data_sha256: str


@dataclass(frozen=True, slots=True)
class Catalog:
    """Catálogo imutável em memória, resultado de ``load_catalog_data``."""

    root: Path
    catalog_version: str
    catalog_sha256: str
    benchmark_sha256: str
    manifest: ManifestEntry
    fuels: Mapping[str, FuelSpec]
    vehicles: Mapping[str, VehicleEntry]
    load_ms: float


@dataclass
class _Ctx:
    root: Path
    issues: list[CatalogIssue] = field(default_factory=list)

    def add(self, code: str, file: str, pointer: str, message: str) -> None:
        self.issues.append(CatalogIssue(code, file, pointer, message))

    def check(self) -> None:
        if self.issues:
            raise CatalogInvalid(self.issues)


# --------------------------------------------------------------------------- leitura


def _scan(ctx: _Ctx) -> set[str]:
    """Arquivos de dados presentes (relativos, com ``/``), sem o manifesto."""
    root_real = ctx.root.resolve()
    found: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(ctx.root, followlinks=False):
        base = Path(dirpath)
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d != "__pycache__")
        for name in sorted([*dirnames, *filenames]):
            if name.startswith("."):
                continue
            path = base / name
            rel = path.relative_to(ctx.root).as_posix()
            if path.is_symlink():
                target = path.resolve()
                if not target.is_relative_to(root_real):
                    ctx.add("PATH_OUTSIDE_CATALOG", rel, "", "link simbólico para fora do catálogo")
                    continue
                if target.is_dir():
                    ctx.add("CATALOG_LAYOUT_INVALID", rel, "", "diretório por link simbólico")
                    continue
            if name in dirnames and not path.is_symlink():
                continue
            if rel != MANIFEST_NAME:
                found.add(rel)
    return found


def _read_json(ctx: _Ctx, rel: str, expected_sha: str | None) -> Any:  # noqa: PLR0911
    path = ctx.root / rel
    try:
        size = path.stat().st_size
    except OSError as exc:
        ctx.add("FILE_MISSING", rel, "", f"arquivo ilegível: {type(exc).__name__}")
        return None
    if size > MAX_FILE_BYTES:
        ctx.add("FILE_TOO_LARGE", rel, "", f"{size} bytes (máximo {MAX_FILE_BYTES})")
        return None
    data = path.read_bytes()
    if expected_sha is not None:
        actual = sha256_bytes(data)
        if actual != expected_sha:
            ctx.add("FILE_HASH_MISMATCH", rel, "", f"manifesto {expected_sha}, arquivo {actual}")
            return None
    if data.startswith(b"\xef\xbb\xbf"):
        ctx.add("FILE_ENCODING_INVALID", rel, "", "UTF-8 com BOM não é aceite")
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        ctx.add("FILE_ENCODING_INVALID", rel, "", f"não é UTF-8 (byte {exc.start})")
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        ctx.add("JSON_INVALID", rel, "", f"linha {exc.lineno}, coluna {exc.colno}: {exc.msg}")
        return None


def _read_manifest(ctx: _Ctx) -> ManifestEntry:
    if not ctx.root.is_dir() or not os.access(ctx.root, os.R_OK | os.X_OK):
        ctx.add("CATALOG_DIR_UNAVAILABLE", str(ctx.root), "", "diretório inexistente ou ilegível")
        ctx.check()
    if not (ctx.root / MANIFEST_NAME).is_file():
        ctx.add("FILE_MISSING", MANIFEST_NAME, "", "manifest.json ausente")
        ctx.check()
    raw = _read_json(ctx, MANIFEST_NAME, None)
    ctx.check()
    try:
        manifest = ManifestEntry.model_validate(raw)
    except ValidationError as exc:
        _add_validation(ctx, MANIFEST_NAME, exc, "MANIFEST_INVALID")
        ctx.check()
        raise  # pragma: no cover - ctx.check() lança antes
    paths = [f.path for f in manifest.files]
    for dup in sorted({p for p in paths if paths.count(p) > 1}):
        ctx.add("MANIFEST_INVALID", MANIFEST_NAME, "/files", f"caminho repetido: {dup}")
    for path in paths:
        if ".." in path.split("/"):
            ctx.add("PATH_OUTSIDE_CATALOG", MANIFEST_NAME, "/files", f"caminho inválido: {path}")
    ctx.check()
    return manifest


# --------------------------------------------------------------------------- erros Pydantic


def _pointer(loc: tuple[int | str, ...]) -> str:
    return "".join(f"/{str(p).replace('~', '~0').replace('/', '~1')}" for p in loc)


def _classify(message: str, err_type: str, pointer: str) -> str:
    in_grid = any(
        key in pointer
        for key in ("true_ve", "g_vvt", "dead_time_ms", "mbt_reference", "efficiency", "/table")
    )
    if "estritamente crescente" in message and (in_grid or "eixo" in message):
        return "GRID_AXIS_NOT_MONOTONIC"
    if "linhas" in message or "colunas" in message or "mesmo comprimento de x_values" in message:
        return "GRID_SHAPE_MISMATCH"
    if "true_ve deve ficar" in message or "valores finitos" in message:
        return "GRID_VALUE_OUT_OF_RANGE"
    if in_grid and err_type in {
        "greater_than",
        "greater_than_equal",
        "less_than",
        "less_than_equal",
    }:
        return "GRID_VALUE_OUT_OF_RANGE"
    return "SCHEMA_INVALID"


_FIELD_PREFIX: Final = re.compile(r"^([a-z][a-z0-9]*_[a-z0-9_]+)\b")


def _add_validation(ctx: _Ctx, rel: str, exc: ValidationError, default: str = "") -> None:
    for err in exc.errors():
        message = str(err.get("msg", "")).removeprefix("Value error, ")
        pointer = _pointer(tuple(err.get("loc", ())))
        match = _FIELD_PREFIX.match(message)
        if match and err.get("type") == "value_error":
            pointer = f"{pointer}/{match.group(1)}"
        code = default or _classify(message, str(err.get("type", "")), pointer)
        ctx.add(code, rel, pointer, message)


def _validate[M: CatalogModel](ctx: _Ctx, rel: str, model: type[M], raw: Any) -> M | None:
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        _add_validation(ctx, rel, exc)
        return None


# --------------------------------------------------------------------------- validações


def _check_texts(ctx: _Ctx, rel: str, texts: Mapping[str, str]) -> None:
    for pointer, text in texts.items():
        terms = find_trademarks(text)
        if terms:
            ctx.add("TRADEMARK_IN_DISPLAY_TEXT", rel, pointer, f"termo(s) proibido(s): {terms}")


def _missing_values(ctx: _Ctx, rel: str, raw: Any) -> bool:
    """EC-07: valor nulo numa grandeza declarada → ``REFERENCE_POINT_MISSING_VALUE``."""
    if not isinstance(raw, dict):
        return False
    quantities = raw.get("quantities")
    points = raw.get("points")
    if not isinstance(quantities, list) or not isinstance(points, list):
        return False
    bad = False
    for i, point in enumerate(points):
        if not isinstance(point, dict):
            continue
        for quantity in quantities:
            if isinstance(quantity, str) and point.get(quantity) is None:
                ctx.add("REFERENCE_POINT_MISSING_VALUE", rel, f"/points/{i}/{quantity}",
                        "valor nulo numa grandeza declarada")  # fmt: skip
                bad = True
    return bad


def _check_curve(ctx: _Ctx, rel: str, curve: ReferenceCurve, spec: VehicleSpec, cid: str) -> None:
    if curve.curve_id != cid:
        ctx.add("REFERENCE_CURVE_INVALID", rel, "/curve_id", "curve_id difere do nome do arquivo")
    if curve.vehicle_id != spec.vehicle_id:
        ctx.add("REFERENCE_CURVE_INVALID", rel, "/vehicle_id", "vehicle_id difere do diretório")
    if curve.fuel_id not in spec.allowed_fuel_ids:
        ctx.add("REFERENCE_CURVE_INVALID", rel, "/fuel_id", "combustível fora de allowed_fuel_ids")
    if not curve.covers_rev_limit(spec.mechanical_limits.rev_limit_rpm):
        ctx.add("REFERENCE_CURVE_INVALID", rel, "/points",
                "último ponto abaixo de rev_limit_rpm − 250")  # fmt: skip
    _check_texts(ctx, rel, {"/source": curve.source})
    if "torque_crank_nm" in curve.quantities and "power_wheel_kw" in curve.quantities:
        for i, point in enumerate(curve.points):
            if point.torque_crank_nm is None or point.power_wheel_kw is None:
                continue
            expected = crank_to_wheel_kw(spec, crank_power_kw(point.torque_crank_nm, point.rpm))
            if abs(point.power_wheel_kw - expected) > POWER_TOLERANCE * abs(expected):
                ctx.add("REFERENCE_CURVE_INCONSISTENT", rel, f"/points/{i}/power_wheel_kw",
                        f"a {point.rpm:g} rpm: {point.power_wheel_kw} kW, esperado "
                        f"{expected:.2f} kW (torque · ω · η − P_fixa)")  # fmt: skip
                break


def _validator_code(exc: BaseException) -> str:
    code = getattr(exc, "code", None)
    if isinstance(code, str):
        return code
    if isinstance(exc, ValidationError):
        for err in exc.errors():
            inner = (err.get("ctx") or {}).get("error")
            inner_code = getattr(inner, "code", None)
            if isinstance(inner_code, str):
                return inner_code
    return "CALIBRATION_INVALID"


def _run_validators(ctx: _Ctx, rel: str, payload: dict[str, object]) -> None:
    for module in CALIBRATION_VALIDATOR_MODULES:
        try:
            importlib.import_module(module)
        except ModuleNotFoundError as exc:
            if exc.name is None or not module.startswith(exc.name):
                raise
    for fn in _CALIBRATION_VALIDATORS:
        try:
            fn(payload)
        except (ValueError, ValidationError) as exc:
            ctx.add(_validator_code(exc), rel, "", str(exc)[:300])
        except Exception as exc:  # EC-13: falha interna do validador, sem fallback
            ctx.add("CALIBRATION_VALIDATOR_ERROR", rel, "", f"{type(exc).__name__}: {exc}"[:300])


def _check_calibrations(
    ctx: _Ctx, spec: VehicleSpec, vehicle_rel: str, docs: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    base = f"vehicles/{spec.vehicle_id}/"
    payloads: dict[str, dict[str, Any]] = {}
    referenced = set()
    for i, ref in enumerate(spec.factory_calibrations):
        rel = base + ref.file
        referenced.add(rel)
        if rel not in docs:
            ctx.add("FILE_MISSING", vehicle_rel, f"/factory_calibrations/{i}/file",
                    f"calibração {ref.file} ausente do catálogo")  # fmt: skip
            continue
        actual = sha256_bytes((ctx.root / rel).read_bytes())
        if actual != ref.sha256:
            ctx.add("FILE_HASH_MISMATCH", vehicle_rel, f"/factory_calibrations/{i}/sha256",
                    f"vehicle.json {ref.sha256}, arquivo {actual}")  # fmt: skip
            continue
        payload = docs[rel]
        if not isinstance(payload, dict):
            ctx.add("CALIBRATION_INVALID", rel, "", "a calibração deve ser um objeto JSON")
            continue
        for key, expected in (
            ("calibration_id", ref.calibration_id),
            ("vehicle_id", spec.vehicle_id),
            ("profile_id", ref.profile_id),
        ):
            if payload.get(key) != expected:
                ctx.add("CALIBRATION_INVALID", rel, f"/{key}", f"esperado {expected!r}")
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict) or metadata.get("source") != "oem_stock":
            ctx.add("CALIBRATION_INVALID", rel, "/metadata/source", "esperado 'oem_stock'")
        _run_validators(ctx, rel, payload)
        payloads[ref.profile_id] = payload
    for rel in sorted(docs):
        if rel.startswith(base + "calibrations/") and rel not in referenced:
            ctx.add("CATALOG_LAYOUT_INVALID", rel, "", "calibração sem FactoryCalibrationRef")
    return payloads


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


# --------------------------------------------------------------------------- carga


def _load_fuels(ctx: _Ctx, docs: Mapping[str, Any], require_canonical: bool) -> dict[str, FuelSpec]:
    fuels: dict[str, FuelSpec] = {}
    for rel in sorted(docs):
        match = _FUEL_RE.match(rel)
        if match is None:
            continue
        fuel = _validate(ctx, rel, FuelSpec, docs[rel])
        if fuel is None:
            continue
        if fuel.fuel_id != match["fuel"]:
            ctx.add("CATALOG_LAYOUT_INVALID", rel, "/fuel_id", "fuel_id difere do nome do arquivo")
        _check_texts(ctx, rel, {"/display_name": fuel.display_name})
        fuels[fuel.fuel_id] = fuel
    if require_canonical and set(fuels) != set(FUEL_IDS) and not ctx.issues:
        ctx.add("CATALOG_LAYOUT_INVALID", "fuels/", "", f"esperados os combustíveis {FUEL_IDS}")
    return fuels


def _load_vehicle(ctx: _Ctx, vid: str, docs: Mapping[str, Any]) -> VehicleEntry | None:
    rel = f"vehicles/{vid}/vehicle.json"
    spec = _validate(ctx, rel, VehicleSpec, docs[rel])
    if spec is None:
        return None
    if spec.vehicle_id != vid:
        ctx.add("VEHICLE_ID_MISMATCH", rel, "/vehicle_id",
                f"vehicle_id {spec.vehicle_id!r} difere do diretório {vid!r}")  # fmt: skip
    _check_texts(ctx, rel, {"/display_name": spec.display_name,
                            "/architecture_note": spec.architecture_note})  # fmt: skip
    for pointer in invalid_provenance_pointers(spec):
        ctx.add(
            "PROVENANCE_POINTER_INVALID", rel, "/provenance", f"ponteiro inexistente: {pointer}"
        )
    curves: list[ReferenceCurve] = []
    curve_files = {
        m["cid"]: r for r in docs if (m := _CURVE_RE.match(r)) is not None and m["vid"] == vid
    }
    for i, cid in enumerate(spec.reference_curve_ids):
        crel = curve_files.get(cid)
        if crel is None:
            ctx.add("FILE_MISSING", rel, f"/reference_curve_ids/{i}", f"curva {cid} ausente")
            continue
        if _missing_values(ctx, crel, docs[crel]):
            continue
        curve = _validate(ctx, crel, ReferenceCurve, docs[crel])
        if curve is not None:
            _check_curve(ctx, crel, curve, spec, cid)
            curves.append(curve)
    for cid, crel in sorted(curve_files.items()):
        if cid not in spec.reference_curve_ids:
            ctx.add("CATALOG_LAYOUT_INVALID", crel, "", "curva não listada em reference_curve_ids")
    if not any(c.calibration_ref == "stock" and c.fuel_id == spec.stock_fuel_id for c in curves):
        ctx.add("REFERENCE_CURVE_INVALID", rel, "/reference_curve_ids",
                "falta a curva de série no combustível de série")  # fmt: skip
    payloads = _check_calibrations(ctx, spec, rel, docs)
    data_sha = canonical_sha256(
        {
            "vehicle": spec.model_dump(mode="json"),
            "reference_curves": {c.curve_id: c.model_dump(mode="json") for c in curves},
            "calibrations": payloads,
        }
    )
    return VehicleEntry(
        spec=spec,
        curves=tuple(curves),
        calibrations=MappingProxyType({k: _freeze(v) for k, v in payloads.items()}),
        estimated_fields=tuple(estimated_fields(spec)),
        data_sha256=data_sha,
    )


def load_catalog_data(root: Path | None = None, *, require_canonical: bool = True) -> Catalog:
    """Lê, valida e devolve o catálogo; lança ``CatalogInvalid`` com todos os erros."""
    started = time.perf_counter()
    ctx = _Ctx(root=Path(root) if root is not None else DEFAULT_CATALOG_DIR)
    manifest = _read_manifest(ctx)
    present = _scan(ctx)
    listed = {f.path: f.sha256 for f in manifest.files}
    for rel in sorted(present - listed.keys()):
        ctx.add("FILE_NOT_IN_MANIFEST", rel, "", "arquivo presente e não listado no manifesto")
    for rel in sorted(listed.keys() - present):
        ctx.add("FILE_MISSING", rel, "", "arquivo listado no manifesto e ausente")
    ctx.check()
    docs: dict[str, Any] = {}
    for rel in sorted(listed):
        if not any(rx.match(rel) for rx in (_FUEL_RE, _VEHICLE_RE, _CURVE_RE, _CALIB_RE)):
            ctx.add("CATALOG_LAYOUT_INVALID", rel, "", "caminho fora da estrutura do catálogo")
            continue
        docs[rel] = _read_json(ctx, rel, listed[rel])
    ctx.check()

    fuels = _load_fuels(ctx, docs, require_canonical)
    vehicle_ids = sorted(m["vid"] for r in docs if (m := _VEHICLE_RE.match(r)) is not None)
    for rel in sorted(docs):
        match = _CURVE_RE.match(rel) or _CALIB_RE.match(rel)
        if match is not None and match["vid"] not in vehicle_ids:
            ctx.add("CATALOG_LAYOUT_INVALID", rel, "", "diretório de veículo sem vehicle.json")
    if require_canonical and set(vehicle_ids) != set(CANONICAL_VEHICLE_IDS):
        ctx.add("CATALOG_VEHICLES_MISMATCH", "vehicles/", "",
                f"esperados {list(CANONICAL_VEHICLE_IDS)}, há {vehicle_ids}")  # fmt: skip
    vehicles: dict[str, VehicleEntry] = {}
    for vid in vehicle_ids:
        entry = _load_vehicle(ctx, vid, docs)
        if entry is not None:
            vehicles[vid] = entry
    ctx.check()

    order = {vid: i for i, vid in enumerate(CANONICAL_VEHICLE_IDS)}
    ordered = dict(sorted(vehicles.items(), key=lambda kv: (order.get(kv[0], 99), kv[0])))
    catalog_sha = canonical_sha256(
        {
            "catalog_version": manifest.catalog_version,
            "fuels": {k: fuels[k].model_dump(mode="json") for k in sorted(fuels)},
            "vehicles": {k: v.data_sha256 for k, v in sorted(ordered.items())},
        }
    )
    return Catalog(
        root=ctx.root,
        catalog_version=manifest.catalog_version,
        catalog_sha256=catalog_sha,
        benchmark_sha256=benchmark_sha256(f.model_dump() for f in manifest.files),
        manifest=manifest,
        fuels=MappingProxyType({k: fuels[k] for k in sorted(fuels, key=_fuel_order)}),
        vehicles=MappingProxyType(ordered),
        load_ms=(time.perf_counter() - started) * 1000.0,
    )


def _fuel_order(fuel_id: str) -> tuple[int, str]:
    return (FUEL_IDS.index(fuel_id) if fuel_id in FUEL_IDS else len(FUEL_IDS), fuel_id)
