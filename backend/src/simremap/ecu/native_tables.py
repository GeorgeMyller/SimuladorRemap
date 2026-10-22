"""Avaliação nativa em lote das tabelas da ECU (feature 003, T017).

Com a extensão ``simremap_rs`` presente, o ``EcuRuntime`` troca, numa *vista* da
calibração compilada, as tabelas puras (``CompiledTable1D``/``CompiledTable2D`` exatos)
por ``NativeSlot``. Cada slot pertence a um grupo; a primeira leitura de um slot no tick
avalia o grupo inteiro numa única chamada a ``simremap_rs.tables.TableSet.eval`` e as
seguintes leem o valor guardado. As estratégias continuam a chamar ``table.at(inputs)``.

Os grupos seguem as janelas do pipeline em que o vetor ``inputs`` não muda, por isso o
resultado é igual ao da avaliação tabela a tabela (bit a bit: mesma aritmética):

- ``early``: combustível, trims de combustível, limiar de knock e avanço base;
- ``after_ign``: correções e trims de avanço, alvo de boost, óleo e ``flex_boost_add``.
  Só é separado quando ``ignition_base`` é um wrapper de perfil (o OEM reescreve
  ``load_pct`` ao lê-lo); senão junta-se ao ``early``;
- ``late``: tabelas lidas depois de ``inputs[boost_target_kpa]`` receber o alvo final
  (duty base da wastegate, ``flex_ign_add`` e alvos de came).

Wrappers de perfil e tabelas fora destes conjuntos (torque OEM, proteção de lambda)
ficam intocados e seguem pelo Python. A calibração real nunca é alterada.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Final, cast

from simremap.ecu.compiled import (
    CompiledCalibration,
    CompiledTable,
    CompiledTable1D,
    CompiledTable2D,
)
from simremap.ecu.contracts import TableKind

__all__ = ["NativeSlot", "NativeTablePlan", "is_pure_table"]

_K = TableKind

_EARLY: Final = frozenset(
    {
        _K.VE,
        _K.INJ_BASE_MS,
        _K.LAMBDA_TARGET,
        _K.IGNITION_BASE,
        _K.FUEL_CORR_ECT,
        _K.FUEL_CORR_IAT,
        _K.ACCEL_ENRICH,
        _K.CRANKING_FUEL,
        _K.AFTERSTART_ENRICH,
        _K.INJ_DEAD_TIME,
        _K.KNOCK_THRESHOLD,
    }
)
_AFTER_IGN: Final = frozenset(
    {
        _K.IGN_CORR_IAT,
        _K.IGN_CORR_ECT,
        _K.BOOST_TARGET,
        _K.BOOST_TARGET_GEAR,
        _K.OIL_PRESSURE_MIN,
        _K.FLEX_BOOST_ADD,
    }
)
_LATE: Final = frozenset(
    {_K.BOOST_DUTY_BASE, _K.FLEX_IGN_ADD, _K.CAM_INTAKE_TARGET, _K.CAM_EXHAUST_TARGET}
)

Spec = tuple[int, int, list[float], list[float], list[list[float]]]


def is_pure_table(table: object) -> bool:
    """Tabela compilada sem comportamento de perfil (tipo exato, não subclasse)."""
    cls = type(table)
    return cls is CompiledTable1D or cls is CompiledTable2D


def _spec(table: CompiledTable) -> Spec:
    if isinstance(table, CompiledTable2D):
        return table.qx, table.qy, table.xs, table.ys, table.z
    return table.qx, -1, table.xs, [], [table.vs]


class _Group:
    """Tabelas avaliadas juntas; ``valid`` cai no início de cada tick."""

    __slots__ = ("buf", "kernel", "valid")

    def __init__(self, kernel: Any) -> None:
        self.kernel = kernel
        self.buf: list[float] = []
        self.valid = False


class NativeSlot:
    """Substituto de ``CompiledTable`` com o valor do grupo nativo (mesmo ``at``)."""

    __slots__ = ("group", "index")

    def __init__(self, group: _Group, index: int) -> None:
        self.group = group
        self.index = index

    def at(self, inputs: list[float]) -> float:
        g = self.group
        if not g.valid:
            g.buf = g.kernel.eval(inputs)
            g.valid = True
        return g.buf[self.index]


class _Builder:
    def __init__(self) -> None:
        self.specs: list[Spec] = []
        self.slots: list[NativeSlot] = []

    def add(self, table: CompiledTable) -> CompiledTable:
        slot = NativeSlot(cast("_Group", None), len(self.specs))
        self.specs.append(_spec(table))
        self.slots.append(slot)
        return cast("CompiledTable", slot)  # duck typing: só ``at`` é usado pelas estratégias

    def build(self, tables_mod: Any) -> _Group | None:
        if not self.specs:
            return None
        group = _Group(tables_mod.TableSet(self.specs))
        for slot in self.slots:
            slot.group = group
        return group


class NativeTablePlan:
    """Vista nativa de uma ``CompiledCalibration`` (uma por calibração ativa do runtime)."""

    __slots__ = ("groups", "source", "view")

    def __init__(self, compiled: CompiledCalibration, tables_mod: Any) -> None:
        self.source = compiled
        early = _Builder()
        base = compiled.tables.get(_K.IGNITION_BASE)
        split = base is not None and not is_pure_table(base)
        after = _Builder() if split else early
        late = _Builder()
        view_tables: dict[TableKind, CompiledTable] = {}
        for kind, table in compiled.tables.items():
            target = None
            if is_pure_table(table):
                if kind in _EARLY:
                    target = early
                elif kind in _AFTER_IGN:
                    target = after
                elif kind in _LATE:
                    target = late
            view_tables[kind] = target.add(table) if target is not None else table
        fuel_trim = [
            early.add(t) if t is not None and is_pure_table(t) else t
            for t in compiled.fuel_trim_cyl
        ]
        ign_trim = [
            after.add(t) if t is not None and is_pure_table(t) else t for t in compiled.ign_trim_cyl
        ]
        builders = (early, after, late) if split else (early, late)
        self.groups = [g for g in (b.build(tables_mod) for b in builders) if g is not None]
        self.view = replace(
            compiled, tables=view_tables, fuel_trim_cyl=fuel_trim, ign_trim_cyl=ign_trim
        )

    def invalidate(self) -> None:
        """Início do tick: a próxima leitura de cada grupo reavalia-o com o ``inputs`` atual."""
        for g in self.groups:
            g.valid = False
