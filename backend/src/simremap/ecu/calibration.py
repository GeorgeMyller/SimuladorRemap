"""Entidade ``Calibration``, hash canónico e edição por versões.

Fontes: ecu-core RF-04, RF-05, RF-26, RF-32.

- ``CalibrationContent``: o conteúdo que entra no ``content_hash`` (``vehicle_id``,
  ``profile_id``, ``fuel_model``, ``tables``, ``strategies``, ``profile_params``).
- ``Calibration``: conteúdo + identidade (``calibration_id``, ``version``,
  ``parent_version``), ``metadata``, ``content_hash`` e ``created_at``.
- ``content_hash``: ``sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
  ensure_ascii=False))`` com floats arredondados a 6 casas (D-11). Metadados, ``version``
  e ``created_at`` ficam fora do hash.
- ``apply_table_patch``: operações ``set``/``add``/``scale`` e troca de eixos (RF-26).
- ``diff_calibrations``: itens alterados entre duas versões, para o modo ``live_tables``
  (RF-28) e para ``changed_tables`` do ``ApplyCalibrationResult``.
- Modelos de pedido e de resposta da API (E-15 a E-20).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from math import isfinite
from typing import Annotated, Any, Final, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    StrictBool,
    Tag,
    ValidationError,
    model_validator,
)

from simremap.catalog.loader import register_calibration_validator
from simremap.core.contracts import ContractModel, EntityId, Sha256Hex
from simremap.ecu.contracts import EcuValidationError, StrategyConfig, TableKind
from simremap.ecu.limits import (
    MAX_PATCH_CELLS,
    MAX_PROFILE_PARAMS,
    MAX_TABLES,
    PER_CYLINDER_KINDS,
)
from simremap.ecu.tables import (
    AnyTable,
    Table2D,
    Table2DView,
    Table3D,
    Table3DView,
    ecu_error_from_validation,
    table_dims_tag,
)
from simremap.profiles.contracts import EcuProfileId

__all__ = [
    "CONTENT_FIELDS",
    "ApplyCalibrationRequest",
    "ApplyCalibrationResult",
    "Calibration",
    "CalibrationContent",
    "CalibrationCreate",
    "CalibrationDiff",
    "CalibrationMetadata",
    "CalibrationPage",
    "CalibrationReplace",
    "CalibrationResponse",
    "CalibrationRevert",
    "CalibrationSource",
    "CalibrationSummary",
    "CalibrationVersionInfo",
    "CellEdit",
    "FuelModelConfig",
    "ProfileParamValue",
    "TablePatch",
    "TablePatchResult",
    "apply_table_patch",
    "build_calibration",
    "canonical_json",
    "compute_content_hash",
    "diff_calibrations",
    "parse_content",
    "round_floats",
    "validate_catalog_calibration",
    "validate_stock_calibration",
]

CONTENT_FIELDS: Final = (
    "vehicle_id",
    "profile_id",
    "fuel_model",
    "tables",
    "strategies",
    "profile_params",
)
"""Campos que entram no ``content_hash`` (ecu-core seção 9; file-formats seção 3)."""

HASH_DECIMALS: Final = 6

CalibrationSource = Literal["user", "wizard", "oem_stock", "import", "clone", "revert", "reference"]
ProfileParamValue = StrictBool | float | str


# --------------------------------------------------------------------------- hash canónico


def round_floats(value: Any, decimals: int = HASH_DECIMALS) -> Any:
    """Arredonda recursivamente os floats (``-0.0`` vira ``0.0``); bool e int ficam iguais."""
    if isinstance(value, float):
        return round(value, decimals) + 0.0
    if isinstance(value, dict):
        return {k: round_floats(v, decimals) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [round_floats(v, decimals) for v in value]
    return value


def canonical_json(payload: Any) -> str:
    """JSON canónico: chaves ordenadas, separadores compactos, UTF-8 sem escape."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_content_hash(content: CalibrationContent) -> str:
    """SHA-256 hex do conteúdo canónico (floats a 6 casas)."""
    payload = round_floats(content.model_dump(mode="json", include=set(CONTENT_FIELDS)))
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- modelos de domínio


class FuelModelConfig(ContractModel):
    mode: Literal["speed_density_ve", "direct_pulse_ms", "profile_air_model"] = "speed_density_ve"
    charge_temp_blend: float = Field(default=0.0, ge=0.0, le=1.0)  # T = IAT + k·(ECT − IAT)
    accel_enrich_tau_s: float = Field(default=0.2, gt=0.0, le=2.0)  # s
    afterstart_decay_s: float = Field(default=15.0, gt=0.0, le=120.0)  # s
    cranking_rpm: float = Field(default=400.0, ge=100.0, le=800.0)  # rev/min
    cranking_ign_deg: float = Field(default=10.0, ge=-5.0, le=20.0)  # ° BTDC
    inj_duty_warn_pct: float = Field(default=85.0, ge=50.0, le=100.0)  # %


class CalibrationMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    author_nickname: str | None = Field(default=None, pattern=r"^[-_0-9A-Za-z]{3,24}$")
    notes: str = Field(default="", max_length=2000)
    source: CalibrationSource = "user"
    change_summary: str = Field(default="", max_length=200)  # ex.: "ignition_base: 12 células"
    extra: dict[str, str] = Field(default_factory=dict)  # chaves de perfil, ex.: "oem_checksum"


def _check_tables(tables: Mapping[str, Table2D | Table3D]) -> None:
    seen_kinds: set[TableKind] = set()
    seen_cyl: set[tuple[TableKind, int]] = set()
    for key, table in tables.items():
        if key != table.table_id:
            raise EcuValidationError("TABLE_ID_MISMATCH", {"key": key, "table_id": table.table_id})
        if table.kind in PER_CYLINDER_KINDS:
            pair = (table.kind, table.cylinder or 0)
            if pair in seen_cyl:
                raise EcuValidationError(
                    "TABLE_ID_MISMATCH",
                    {"key": key, "reason": "cylinder_duplicated", "cylinder": table.cylinder},
                )
            seen_cyl.add(pair)
        else:
            if table.kind in seen_kinds:
                raise EcuValidationError(
                    "TABLE_ID_MISMATCH",
                    {"key": key, "reason": "kind_duplicated", "kind": table.kind.value},
                )
            seen_kinds.add(table.kind)


def _check_strategy_coherence(content: CalibrationContent) -> None:
    """EC-13: configurações incoerentes entre estratégias e com o modo de combustível."""
    strategies = content.strategies
    two_step = strategies.get("two_step")
    limiter = strategies.get("rev_limiter")
    if (
        two_step is not None
        and limiter is not None
        and two_step.kind == "two_step"
        and limiter.kind == "rev_limiter"
        and two_step.enabled
        and limiter.enabled
        and two_step.target_rpm >= limiter.hard_rpm
    ):
        raise EcuValidationError(
            "STRATEGY_CONFIG_INVALID",
            {
                "fields": ["strategies.two_step.target_rpm", "strategies.rev_limiter.hard_rpm"],
                "reason": "two_step.target_rpm deve ser menor que rev_limiter.hard_rpm",
            },
        )
    kinds = {table.kind for table in content.tables.values()}
    required = {
        "speed_density_ve": TableKind.VE,
        "direct_pulse_ms": TableKind.INJ_BASE_MS,
    }.get(content.fuel_model.mode)
    if required is not None and required not in kinds:
        raise EcuValidationError(
            "STRATEGY_CONFIG_INVALID",
            {
                "fields": ["fuel_model.mode", f"tables.{required.value}"],
                "reason": f"o modo {content.fuel_model.mode} exige a tabela {required.value}",
            },
        )


class CalibrationContent(ContractModel):
    """Conteúdo de uma calibração: tudo o que entra no ``content_hash``."""

    vehicle_id: EntityId
    profile_id: EcuProfileId
    fuel_model: FuelModelConfig = Field(default_factory=FuelModelConfig)
    tables: dict[str, AnyTable] = Field(default_factory=dict)  # chave == table_id
    strategies: dict[str, StrategyConfig] = Field(default_factory=dict)  # chave == kind
    profile_params: dict[str, ProfileParamValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _keys(self) -> Self:
        if len(self.tables) > MAX_TABLES:
            raise EcuValidationError("TABLE_SIZE_EXCEEDED", {"tables": len(self.tables)})
        _check_tables(self.tables)
        for key, strat in self.strategies.items():
            if key != strat.kind:
                raise EcuValidationError("STRATEGY_KIND_MISMATCH", {"key": key, "kind": strat.kind})
        if len(self.profile_params) > MAX_PROFILE_PARAMS:
            raise ValueError(f"profile_params aceita no máximo {MAX_PROFILE_PARAMS} chaves")
        for key, value in self.profile_params.items():
            if isinstance(value, float) and not isfinite(value):
                raise ValueError(f"profile_params.{key} deve ser finito")
        _check_strategy_coherence(self)
        return self

    def content(self) -> CalibrationContent:
        """Só o conteúdo (descarta identidade e metadados)."""
        return CalibrationContent.model_validate(self.model_dump(include=set(CONTENT_FIELDS)))

    def content_hash_value(self) -> str:
        return compute_content_hash(self)

    def table(self, table_id: str) -> Table2D | Table3D | None:
        return self.tables.get(table_id)


class Calibration(CalibrationContent):
    """Versão imutável de uma calibração (RF-04)."""

    calibration_id: EntityId
    version: int = Field(ge=1)
    parent_version: int | None = Field(default=None, ge=1)
    metadata: CalibrationMetadata
    content_hash: Sha256Hex
    created_at: datetime  # relógio de parede, fora do laço e fora do hash

    def verify_hash(self) -> bool:
        return compute_content_hash(self) == self.content_hash


def build_calibration(
    content: CalibrationContent,
    *,
    calibration_id: str,
    version: int,
    parent_version: int | None,
    metadata: CalibrationMetadata,
    created_at: datetime,
) -> Calibration:
    """Monta a ``Calibration`` calculando o ``content_hash`` no servidor."""
    data = content.model_dump(include=set(CONTENT_FIELDS))
    return Calibration.model_validate(
        {
            **data,
            "calibration_id": calibration_id,
            "version": version,
            "parent_version": parent_version,
            "metadata": metadata.model_dump(),
            "content_hash": compute_content_hash(content),
            "created_at": created_at,
        }
    )


def validate_stock_calibration(
    data: Mapping[str, Any], *, vehicle_id: str, profile_id: str, created_at: datetime
) -> Calibration:
    """Valida uma calibração de série do catálogo (catalog RF-20, ``oem_stock``).

    Uso previsto pelo ``register_calibration_validator`` do loader do catálogo. Lança
    ``EcuValidationError`` (ex.: ``TABLE_AXIS_NOT_MONOTONIC``) ou ``ValueError``.
    """
    content = parse_content({**data, "vehicle_id": vehicle_id, "profile_id": profile_id})
    meta = CalibrationMetadata.model_validate(
        {**dict(data.get("metadata") or {"name": f"Série {vehicle_id}"}), "source": "oem_stock"}
    )
    return build_calibration(
        content,
        calibration_id=f"stock-{vehicle_id}-{profile_id}",
        version=1,
        parent_version=None,
        metadata=meta,
        created_at=created_at,
    )


def parse_content(data: Mapping[str, Any]) -> CalibrationContent:
    """Valida o conteúdo e devolve o ``EcuValidationError`` original quando existir."""
    payload = {k: data[k] for k in CONTENT_FIELDS if k in data and data[k] is not None}
    try:
        return CalibrationContent.model_validate(payload)
    except ValidationError as exc:
        original = ecu_error_from_validation(exc)
        if original is not None:
            raise original from exc
        raise


# --------------------------------------------------------------------------- PATCH de tabela


class CellEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row: int = Field(ge=0, le=31)  # 0 para Table2D
    col: int = Field(ge=0, le=31)
    value: float


class TablePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_version: int = Field(ge=1)
    op: Literal["set", "add", "scale"] = "set"  # add soma value; scale multiplica por value
    cells: list[CellEdit] = Field(default_factory=list)  # máximo 1024, validado no serviço
    x_values: list[float] | None = None  # substitui o eixo x (mesmo número de pontos)
    y_values: list[float] | None = None
    change_summary: str = Field(default="", max_length=200)


def _apply_op(op: str, old: float, value: float) -> float:
    if op == "add":
        return old + value
    if op == "scale":
        return old * value
    return value


def apply_table_patch(table: Table2D | Table3D, patch: TablePatch) -> Table2D | Table3D:
    """Aplica ``patch`` e devolve a tabela nova validada (RF-26, EC-01, EC-02)."""
    if len(patch.cells) > MAX_PATCH_CELLS:
        raise EcuValidationError(
            "PATCH_TOO_LARGE", {"cells": len(patch.cells), "max": MAX_PATCH_CELLS}
        )
    data = table.model_dump()
    is_3d = isinstance(table, Table3D)
    for name, values in (("x", patch.x_values), ("y", patch.y_values)):
        if values is None:
            continue
        if name == "y" and not is_3d:
            raise EcuValidationError(
                "TABLE_SHAPE_MISMATCH", {"table_id": table.table_id, "reason": "y_values em 2D"}
            )
        if len(values) != len(data[name]["values"]):
            raise EcuValidationError(
                "TABLE_SHAPE_MISMATCH",
                {
                    "table_id": table.table_id,
                    "axis": name,
                    "expected": len(data[name]["values"]),
                    "got": len(values),
                },
            )
        data[name] = {**data[name], "values": list(values)}
    if is_3d:
        grid: list[list[float]] = [list(row) for row in data["values"]]
    else:
        grid = [list(data["values"])]
    for cell in patch.cells:
        if cell.row >= len(grid) or cell.col >= len(grid[0]):
            raise EcuValidationError(
                "PATCH_CELL_OUT_OF_BOUNDS",
                {"table_id": table.table_id, "row": cell.row, "col": cell.col},
            )
        grid[cell.row][cell.col] = _apply_op(patch.op, grid[cell.row][cell.col], cell.value)
    data["values"] = grid if is_3d else grid[0]
    model: type[Table2D] | type[Table3D] = Table3D if is_3d else Table2D
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        original = ecu_error_from_validation(exc)
        if original is not None:
            raise original from exc
        raise


# --------------------------------------------------------------------------- diff (RF-28)


class CalibrationDiff(BaseModel):
    """Diferenças entre a calibração ativa e a nova."""

    model_config = ConfigDict(frozen=True)

    changed_tables: list[str]  # table_id com qualquer alteração
    not_live: list[str]  # itens que impedem o modo live_tables (ex.: strategies.rev_limiter)

    @property
    def live_compatible(self) -> bool:
        return not self.not_live


def diff_calibrations(old: CalibrationContent, new: CalibrationContent) -> CalibrationDiff:
    """Compara o conteúdo: só células de tabelas live-tunable podem mudar em puxada."""
    changed: list[str] = []
    not_live: list[str] = []
    for table_id in sorted(set(old.tables) | set(new.tables)):
        a = old.tables.get(table_id)
        b = new.tables.get(table_id)
        if a == b:
            continue
        changed.append(table_id)
        if a is None or b is None:
            not_live.append(f"tables.{table_id}")
            continue
        same_axes = a.x == b.x and (
            not isinstance(a, Table3D) or (isinstance(b, Table3D) and a.y == b.y)
        )
        same_shape = a.model_dump(exclude={"values"}) == b.model_dump(exclude={"values"})
        if not (same_axes and same_shape and a.live_tunable and b.live_tunable):
            not_live.append(f"tables.{table_id}")
    for kind in sorted(set(old.strategies) | set(new.strategies)):
        if old.strategies.get(kind) != new.strategies.get(kind):
            not_live.append(f"strategies.{kind}")
    if old.fuel_model != new.fuel_model:
        not_live.append("fuel_model")
    if old.profile_params != new.profile_params:
        not_live.append("profile_params")
    return CalibrationDiff(changed_tables=changed, not_live=not_live)


# --------------------------------------------------------------------------- API: pedidos


class CalibrationCreate(BaseModel):
    """Corpo de ``POST /api/v1/calibrations`` (E-16)."""

    model_config = ConfigDict(extra="forbid")

    vehicle_id: EntityId
    profile_id: EcuProfileId
    metadata: CalibrationMetadata
    source: Literal["clone", "payload", "reference"]
    clone_from_id: EntityId | None = None
    clone_from_version: int | None = Field(default=None, ge=1)
    fuel_model: FuelModelConfig | None = None
    tables: dict[str, AnyTable] | None = None
    strategies: dict[str, StrategyConfig] | None = None
    profile_params: dict[str, ProfileParamValue] | None = None


class CalibrationReplace(BaseModel):
    """Corpo de ``PUT`` com o conteúdo completo (E-18)."""

    model_config = ConfigDict(extra="forbid")

    base_version: int = Field(ge=1)
    vehicle_id: EntityId | None = None  # se enviado, deve ser igual ao atual
    profile_id: EcuProfileId | None = None  # se diferente: CALIBRATION_PROFILE_IMMUTABLE
    fuel_model: FuelModelConfig
    tables: dict[str, AnyTable]
    strategies: dict[str, StrategyConfig]
    profile_params: dict[str, ProfileParamValue] = Field(default_factory=dict)
    metadata: CalibrationMetadata


class CalibrationRevert(BaseModel):
    """Corpo de ``PUT`` de reversão: ``{base_version, revert_to_version}`` (Fluxo B)."""

    model_config = ConfigDict(extra="forbid")

    base_version: int = Field(ge=1)
    revert_to_version: int = Field(ge=1)
    change_summary: str = Field(default="", max_length=200)
    author_nickname: str | None = Field(default=None, pattern=r"^[-_0-9A-Za-z]{3,24}$")


class ApplyCalibrationRequest(BaseModel):
    """Corpo de ``POST /api/v1/sessions/{session_id}/calibration`` (E-20)."""

    model_config = ConfigDict(extra="forbid")

    calibration_id: EntityId
    version: int | None = Field(default=None, ge=1)  # padrão: última
    profile_options: dict[str, bool] = Field(default_factory=dict)  # repassado ao hook


# --------------------------------------------------------------------------- API: respostas


class CalibrationVersionInfo(BaseModel):
    version: int
    parent_version: int | None
    content_hash: str
    source: str
    author_nickname: str | None
    change_summary: str
    created_at: AwareDatetime


class CalibrationSummary(BaseModel):
    calibration_id: str
    vehicle_id: str
    profile_id: str
    name: str
    latest_version: int
    content_hash: str
    updated_at: AwareDatetime


class CalibrationPage(BaseModel):
    items: list[CalibrationSummary]
    total: int = Field(ge=0)


TableView = Annotated[
    Annotated[Table2DView, Tag("2")] | Annotated[Table3DView, Tag("3")],
    Discriminator(table_dims_tag),
]


class CalibrationResponse(BaseModel):
    """``Calibration`` com os campos só de leitura da UI.

    Campos extra: ``min``/``max`` por tabela e ``unit``/``source_channel`` por eixo.
    """

    model_config = ConfigDict(extra="forbid")

    calibration_id: str
    vehicle_id: str
    profile_id: str
    version: int
    parent_version: int | None
    fuel_model: FuelModelConfig
    tables: dict[str, TableView]
    strategies: dict[str, StrategyConfig]
    profile_params: dict[str, ProfileParamValue]
    metadata: CalibrationMetadata
    content_hash: str
    created_at: datetime
    versions: list[CalibrationVersionInfo] | None = None

    @classmethod
    def from_calibration(
        cls, cal: Calibration, versions: list[CalibrationVersionInfo] | None = None
    ) -> CalibrationResponse:
        return cls.model_validate({**cal.model_dump(), "versions": versions})


class TablePatchResult(BaseModel):
    version: int
    content_hash: str
    table: TableView


class ApplyCalibrationResult(BaseModel):
    session_id: str
    calibration_id: str
    version: int
    content_hash: str
    mode: Literal["full", "live_tables"]
    changed_tables: list[str]
    applied_t_sim_s: float


# --------------------------------------------------------------------------- catálogo (RF-20)

_CATALOG_EPOCH: Final = datetime(2000, 1, 1, tzinfo=UTC)


def validate_catalog_calibration(payload: Mapping[str, Any]) -> None:
    """Validador das calibrações de fábrica do catálogo (vehicle-catalog RF-20; T413).

    Registado no loader do catálogo no import deste módulo. Valida o conteúdo como uma
    ``Calibration`` ``oem_stock`` (tabelas, eixos, limites, estratégias) e confere o
    ``content_hash`` gravado no arquivo, quando presente. Lança ``EcuValidationError``
    com o ``code`` do ecu-core (ex.: ``TABLE_AXIS_NOT_MONOTONIC``), propagado pelo loader
    para os ``issues`` do ``CATALOG_INVALID``.
    """
    vehicle_id = payload.get("vehicle_id")
    profile_id = payload.get("profile_id")
    if not isinstance(vehicle_id, str) or not isinstance(profile_id, str):
        raise EcuValidationError("CALIBRATION_INVALID", {"reason": "vehicle_id/profile_id"})
    raw_created = payload.get("created_at")
    created = (
        datetime.fromisoformat(raw_created.replace("Z", "+00:00"))
        if isinstance(raw_created, str)
        else _CATALOG_EPOCH
    )
    cal = validate_stock_calibration(
        payload, vehicle_id=vehicle_id, profile_id=profile_id, created_at=created
    )
    stored = payload.get("content_hash")
    if isinstance(stored, str) and stored != cal.content_hash:
        raise EcuValidationError(
            "CALIBRATION_INVALID",
            {"reason": "content_hash", "stored": stored, "computed": cal.content_hash},
        )


register_calibration_validator(validate_catalog_calibration)
