"""Tabelas 2D/3D da ECU e interpolação com clamp (ecu-core RF-01 a RF-03, Apêndice A e B).

``Axis``, ``AxisQuantity`` e ``TableKind`` vêm de ``ecu/contracts.py`` (não duplicar).
Aqui ficam ``Table2D``/``Table3D`` com a validação de formato, unidade, finitude e
limites do Apêndice A, e as funções de interpolação do hot path (listas Python e
``bisect``, sem NumPy nem Pydantic).

Convenção: ``Table3D.values`` tem ``len(y)`` linhas × ``len(x)`` colunas; ``row`` indexa
``y`` e ``col`` indexa ``x``. ``Table2D.values`` tem ``len(x)`` valores (``row = 0``).
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from math import isfinite
from typing import Annotated, Any, Literal, Self

from pydantic import Discriminator, Field, Tag, ValidationError, computed_field, model_validator

from simremap.core.contracts import ContractModel
from simremap.ecu.contracts import AXIS_UNITS, Axis, EcuValidationError, TableKind
from simremap.ecu.limits import PER_CYLINDER_KINDS, TableLimit, table_limit

__all__ = [
    "AnyTable",
    "AxisView",
    "Table2D",
    "Table2DView",
    "Table3D",
    "Table3DView",
    "TableBase",
    "ecu_error_from_validation",
    "interp1",
    "interp2",
    "table_dims_tag",
    "table_view",
]


# --------------------------------------------------------------------------- interpolação


def interp1(xs: Sequence[float], vs: Sequence[float], x: float) -> float:
    """Interpolação linear com clamp nas bordas (Apêndice B, sem extrapolação)."""
    if not x > xs[0]:  # inclui NaN: vale a primeira borda
        return vs[0]
    last = len(xs) - 1
    if x >= xs[last]:
        return vs[last]
    i = bisect_right(xs, x) - 1
    x0 = xs[i]
    v0 = vs[i]
    return v0 + (x - x0) / (xs[i + 1] - x0) * (vs[i + 1] - v0)


def _locate(axis: Sequence[float], x: float) -> tuple[int, float]:
    """Índice ``i`` (0..n−2) e fração ``f`` (0..1) de ``x`` com clamp."""
    last = len(axis) - 1
    if not x > axis[0]:
        return 0, 0.0
    if x >= axis[last]:
        return last - 1, 1.0
    i = bisect_right(axis, x) - 1
    x0 = axis[i]
    return i, (x - x0) / (axis[i + 1] - x0)


def interp2(
    xs: Sequence[float], ys: Sequence[float], z: Sequence[Sequence[float]], x: float, y: float
) -> float:
    """Interpolação bilinear com clamp: ``z[linha=y][coluna=x]`` (Apêndice B)."""
    j, fx = _locate(xs, x)
    i, fy = _locate(ys, y)
    r0 = z[i]
    r1 = z[i + 1]
    a = r0[j] + fx * (r0[j + 1] - r0[j])
    b = r1[j] + fx * (r1[j + 1] - r1[j])
    return a + fy * (b - a)


# --------------------------------------------------------------------------- modelos


def _check_values(table_id: str, lim: TableLimit, rows: Sequence[Sequence[float]]) -> None:
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            if not isfinite(value):
                raise EcuValidationError(
                    "TABLE_VALUE_NOT_FINITE", {"table_id": table_id, "row": r, "col": c}
                )
            if not lim.min <= value <= lim.max:
                raise EcuValidationError(
                    "TABLE_VALUE_OUT_OF_RANGE",
                    {
                        "table_id": table_id,
                        "row": r,
                        "col": c,
                        "value": value,
                        "min": lim.min,
                        "max": lim.max,
                    },
                )


_VIEW_TABLE_FIELDS = frozenset({"min", "max"})
_VIEW_AXIS_FIELDS = frozenset({"unit", "source_channel"})


class TableBase(ContractModel):
    """Campos comuns de ``Table2D`` e ``Table3D``.

    ``live_tunable`` omitido vale o padrão do tipo (Apêndice A). Um tipo que não é
    live-tunable no Apêndice A nunca passa a sê-lo (o valor é forçado a ``False``),
    para a regra do RF-28 não ser contornada pelo payload. Os campos só de leitura da
    UI (``min``/``max`` e ``unit``/``source_channel`` dos eixos) devolvidos pelo ``GET``
    são descartados na entrada, para o JSON do ``GET`` poder voltar num ``PUT``/import.
    """

    table_id: str = Field(pattern=r"^[a-z][_0-9a-z]{1,47}$")
    kind: TableKind
    unit: str
    live_tunable: bool = False
    cylinder: int | None = Field(default=None, ge=1, le=12)  # só para *_trim_cyl
    description: str = Field(default="", max_length=200)
    decimals: int = Field(default=1, ge=0, le=4)  # casas de exibição na ecu-tuning-ui

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        """Descarta os campos só de leitura da UI e aplica o live-tunable padrão do tipo."""
        if isinstance(data, dict):
            data = {k: v for k, v in data.items() if k not in _VIEW_TABLE_FIELDS}
            for axis in ("x", "y"):
                value = data.get(axis)
                if isinstance(value, dict) and _VIEW_AXIS_FIELDS.intersection(value):
                    data[axis] = {k: v for k, v in value.items() if k not in _VIEW_AXIS_FIELDS}
            kind = data.get("kind")
            try:
                lim = table_limit(kind) if kind is not None else None
            except ValueError:
                return data
            if lim is not None:
                live = data.get("live_tunable")
                data = {**data, "live_tunable": lim.live_tunable and (live is None or bool(live))}
        return data

    @property
    def limit(self) -> TableLimit:
        return table_limit(self.kind)

    def _check_common(self, dims: int) -> TableLimit:
        lim = self.limit
        if lim.dims != dims:
            raise EcuValidationError(
                "TABLE_SHAPE_MISMATCH",
                {"table_id": self.table_id, "reason": "dims", "expected": lim.dims, "got": dims},
            )
        if (self.kind in PER_CYLINDER_KINDS) != (self.cylinder is not None):
            raise EcuValidationError(
                "TABLE_SHAPE_MISMATCH",
                {"table_id": self.table_id, "reason": "cylinder", "kind": self.kind.value},
            )
        if self.unit != lim.unit:
            raise EcuValidationError(
                "TABLE_UNIT_MISMATCH",
                {"table_id": self.table_id, "expected": lim.unit, "got": self.unit},
            )
        return lim


class Table2D(TableBase):
    dims: Literal[2] = 2
    x: Axis
    values: list[float]  # len == len(x.values)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if len(self.values) != len(self.x.values):
            raise EcuValidationError(
                "TABLE_SHAPE_MISMATCH",
                {
                    "table_id": self.table_id,
                    "x_points": len(self.x.values),
                    "values": len(self.values),
                },
            )
        lim = self._check_common(2)
        _check_values(self.table_id, lim, (self.values,))
        return self

    def lookup(self, x: float) -> float:
        return interp1(self.x.values, self.values, x)

    @property
    def n_cells(self) -> int:
        return len(self.values)


class Table3D(TableBase):
    dims: Literal[3] = 3
    x: Axis  # colunas (normalmente rpm)
    y: Axis  # linhas (normalmente map_kpa, tps_pct ou load_pct)
    values: list[list[float]]  # len(y) linhas × len(x) colunas

    @model_validator(mode="after")
    def _check(self) -> Self:
        nx, ny = len(self.x.values), len(self.y.values)
        if len(self.values) != ny or any(len(row) != nx for row in self.values):
            raise EcuValidationError(
                "TABLE_SHAPE_MISMATCH",
                {
                    "table_id": self.table_id,
                    "x_points": nx,
                    "y_points": ny,
                    "rows": len(self.values),
                },
            )
        lim = self._check_common(3)
        _check_values(self.table_id, lim, self.values)
        return self

    def lookup(self, x: float, y: float) -> float:
        return interp2(self.x.values, self.y.values, self.values, x, y)

    @property
    def n_cells(self) -> int:
        return len(self.x.values) * len(self.y.values)


def table_dims_tag(value: Any) -> str | None:
    """Discriminador de ``AnyTable``: usa ``dims``; sem ``dims``, 3D se houver eixo ``y``."""
    if isinstance(value, dict):
        dims = value.get("dims")
        if dims is None:
            return "3" if "y" in value else "2"
        return str(dims)
    dims = getattr(value, "dims", None)
    return None if dims is None else str(dims)


AnyTable = Annotated[
    Annotated[Table2D, Tag("2")] | Annotated[Table3D, Tag("3")],
    Discriminator(table_dims_tag),
]


# --------------------------------------------------------------------------- vistas da UI


class AxisView(Axis):
    """Eixo com os campos só de leitura da UI (fora do hash)."""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def source_channel(self) -> str:
        """Canal de telemetria do cursor (igual à ``quantity``)."""
        return self.quantity.value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def unit(self) -> str:
        """Unidade do eixo (``AXIS_UNITS``)."""
        return AXIS_UNITS[self.quantity.value]


class _ViewLimits:
    kind: TableKind

    @computed_field  # type: ignore[prop-decorator]
    @property
    def min(self) -> float:
        return table_limit(self.kind).min

    @computed_field  # type: ignore[prop-decorator]
    @property
    def max(self) -> float:
        return table_limit(self.kind).max


class Table2DView(_ViewLimits, Table2D):
    x: AxisView


class Table3DView(_ViewLimits, Table3D):
    x: AxisView
    y: AxisView


def table_view(table: Table2D | Table3D) -> Table2DView | Table3DView:
    """Converte a tabela de domínio na vista com ``min``/``max``/``unit``/``source_channel``."""
    data = table.model_dump()
    if isinstance(table, Table3D):
        return Table3DView.model_validate(data)
    return Table2DView.model_validate(data)


# --------------------------------------------------------------------------- erros


def ecu_error_from_validation(exc: ValidationError) -> EcuValidationError | None:
    """Extrai o primeiro ``EcuValidationError`` embrulhado num ``ValidationError``.

    O Pydantic guarda a exceção original do validador em ``ctx["error"]``; o router
    usa-a para responder com o ``code`` estável (ex.: ``TABLE_AXIS_NOT_MONOTONIC``) em vez
    de ``VALIDATION_FAILED``.
    """
    for err in exc.errors():
        ctx = err.get("ctx") or {}
        original = ctx.get("error")
        if isinstance(original, EcuValidationError):
            return original
    return None
