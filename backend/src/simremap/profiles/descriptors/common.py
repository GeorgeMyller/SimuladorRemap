"""Peças comuns dos descritores: eixos padrão, tabelas, estratégias e itens de navegação.

Eixos padrão (Apêndice B, sem ``vehicle_id``): RPM em 16 pontos ``500..8000``; MAP em
16 pontos ``20..320`` kPa; carga OEM em 16 pontos ``10..250`` %; pedal em 16 pontos
``0, 2, 5, 10, ..., 95, 100`` %; marcha ``1..6``. Com ``vehicle_id`` (RF-02), o último
ponto de RPM passa a ``rev_limit_rpm`` arredondado a 100 rpm (passo uniforme) e o MAP vai
até ``max(320, pressão máxima do turbo/compressor + 20)`` kPa.

Os nomes exibidos são genéricos (sem marcas, Apêndice G).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, Literal

from simremap.ecu.contracts import Axis, AxisQuantity, StrategyKind, TableKind
from simremap.ecu.limits import TABLE_LIMITS
from simremap.profiles.contracts import (
    BaseSetupStep,
    DisplayUnits,
    EcuProfileDescriptor,
    EcuProfileId,
    FeaturePackage,
    FuelModelMode,
    NavItem,
    NavSection,
    ProfileFamily,
    StrategySupport,
    TableSupport,
)

__all__ = [
    "BASE_STEP_LABELS",
    "DEFAULT_PEDAL_AXIS",
    "STANDALONE_STEPS",
    "AxisSet",
    "StrategyLevel",
    "base_setup_section",
    "finish_standalone",
    "flex_section",
    "flex_tables",
    "nav_base",
    "nav_info",
    "nav_strategy",
    "nav_table",
    "section",
    "standalone_tables",
    "strategy",
    "table",
    "trim_items",
    "uniform",
    "vvt_section",
]

_Q = AxisQuantity
_K = TableKind
StrategyLevel = Literal["supported", "package_race", "unsupported"]

DEFAULT_PEDAL_AXIS: Final[tuple[float, ...]] = (
    0.0, 2.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 95.0, 100.0,
)  # fmt: skip
_TPS_AXIS: Final[tuple[float, ...]] = (
    0.0, 5.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 75.0, 80.0, 85.0, 90.0, 95.0, 98.0, 100.0,
)  # fmt: skip
STANDALONE_STEPS: Final[tuple[BaseSetupStep, ...]] = (
    "trigger",
    "injectors",
    "fuel",
    "sensors",
    "protection",
    "review",
)
BASE_STEP_LABELS: Final[dict[str, str]] = {
    "trigger": "Roda fônica e sincronismo",
    "injectors": "Bicos injetores",
    "fuel": "Combustível",
    "sensors": "Sensores",
    "protection": "Proteções do motor",
    "review": "Revisão e mapa base",
}


def uniform(start: float, stop: float, n: int = 16) -> list[float]:
    """``n`` pontos uniformes de ``start`` a ``stop`` (3 casas decimais)."""
    step = (stop - start) / (n - 1)
    return [round(start + step * i, 3) for i in range(n)]


@dataclass(frozen=True, slots=True)
class AxisSet:
    """Eixos padrão de um descritor (genéricos ou reescalados a um veículo)."""

    rpm_max: float = 8000.0  # rev/min
    map_max_kpa: float = 320.0  # kPa abs
    n_cyl: int = 8
    n_gears: int = 6
    values: dict[AxisQuantity, list[float]] = field(
        default_factory=dict, compare=False, hash=False, repr=False
    )

    def __post_init__(self) -> None:
        axes = self.values
        axes[_Q.RPM] = uniform(500.0, self.rpm_max)
        axes[_Q.MAP_KPA] = uniform(20.0, self.map_max_kpa)
        axes[_Q.LOAD_PCT] = uniform(10.0, 250.0)
        axes[_Q.PEDAL_PCT] = list(DEFAULT_PEDAL_AXIS)
        axes[_Q.TPS_PCT] = list(_TPS_AXIS)
        axes[_Q.GEAR] = [float(g) for g in range(1, self.n_gears + 1)]
        axes[_Q.ECT_C] = [-20.0, 0.0, 20.0, 40.0, 60.0, 80.0, 90.0, 110.0]
        axes[_Q.IAT_C] = [-20.0, 0.0, 20.0, 40.0, 60.0, 80.0, 100.0]
        axes[_Q.BATTERY_V] = [8.0 + i for i in range(9)]
        axes[_Q.TPS_RATE_PCT_S] = [0.0, 50.0, 100.0, 200.0, 400.0, 800.0]
        axes[_Q.EGT_C] = [600.0, 850.0, 900.0, 950.0, 1000.0]
        axes[_Q.IGN_DELTA_DEG] = uniform(0.0, 45.0)
        axes[_Q.BOOST_TARGET_KPA] = uniform(100.0, self.map_max_kpa)
        axes[_Q.TORQUE_NM] = uniform(0.0, 600.0)
        axes[_Q.ETHANOL_PCT] = [27.0, 40.0, 50.0, 60.0, 70.0, 85.0, 100.0]

    def axis(self, quantity: AxisQuantity) -> Axis:
        return Axis(quantity=quantity, values=list(self.values[quantity]))


# Eixos (x, y) de cada tipo de tabela; o perfil OEM troca MAP por carga onde indicado.
_DEFAULT_XY: Final[dict[TableKind, tuple[AxisQuantity, AxisQuantity | None]]] = {
    kind: (lim.x, lim.y) for kind, lim in TABLE_LIMITS.items()
}
_FRICTION_ECT: Final = [-20.0 + 10.0 * i for i in range(16)]


def table(
    axes: AxisSet,
    kind: TableKind,
    display_name: str,
    *,
    required: bool = False,
    y: AxisQuantity | None = None,
    per_cylinder: bool = False,
    live_tunable: bool | None = None,
) -> TableSupport:
    """``TableSupport`` com os eixos padrão do tipo (``y`` sobrepõe o eixo das linhas)."""
    lim = TABLE_LIMITS[kind]
    qx, qy = _DEFAULT_XY[kind]
    if y is not None and qy is not None:
        qy = y
    default_y = None
    if qy is not None:
        default_y = (
            Axis(quantity=qy, values=_FRICTION_ECT) if kind == _K.FRICTION_TORQUE else axes.axis(qy)
        )
    return TableSupport(
        kind=kind,
        required=required,
        default_x=axes.axis(qx),
        default_y=default_y,
        display_name=display_name,
        per_cylinder=per_cylinder,
        live_tunable=lim.live_tunable
        if live_tunable is None
        else live_tunable and lim.live_tunable,
    )


def strategy(
    kind: StrategyKind,
    level: StrategyLevel,
    display_name: str,
    restricted: dict[str, list[str]] | None = None,
) -> StrategySupport:
    return StrategySupport(
        kind=kind, level=level, display_name=display_name, restricted_options=restricted or {}
    )


def nav_table(item_id: str, label: str, kind: TableKind, *, cylinder: int | None = None) -> NavItem:
    return NavItem(id=item_id, label=label, kind="table", target_id=kind.value, cylinder=cylinder)


def nav_strategy(
    item_id: str, label: str, kind: StrategyKind, *, package: Literal["race"] | None = None
) -> NavItem:
    return NavItem(
        id=item_id, label=label, kind="strategy", target_id=kind.value, requires_package=package
    )


def nav_base(item_id: str, label: str, step: str) -> NavItem:
    return NavItem(id=item_id, label=label, kind="base_setup", target_id=step)


def nav_info(item_id: str, label: str, target: str) -> NavItem:
    return NavItem(id=item_id, label=label, kind="info", target_id=target)


def section(section_id: str, label: str, items: list[NavItem]) -> NavSection:
    return NavSection(id=section_id, label=label, items=items)


def base_setup_section(section_id: str, label: str, *, wizard_first: bool = False) -> NavSection:
    """Secção do assistente de 6 passos (ecu-tuning-ui RF-15)."""
    items = [nav_base(f"{section_id}.{s}", BASE_STEP_LABELS[s], s) for s in STANDALONE_STEPS]
    if wizard_first:
        items.insert(0, nav_base(f"{section_id}.wizard", "Gerar mapa base", "wizard"))
    return section(section_id, label, items)


def trim_items(prefix: str, label: str, kind: TableKind, n_cyl: int) -> list[NavItem]:
    """Itens por cilindro (``fuel_trim_cyl``/``ignition_trim_cyl``) de 1 a ``n_cyl``."""
    return [
        nav_table(f"{prefix}.{c}", f"{label} cil. {c}", kind, cylinder=c)
        for c in range(1, n_cyl + 1)
    ]


def standalone_tables(axes: AxisSet, ve_label: str) -> list[TableSupport]:
    """Tabelas comuns dos perfis standalone (sem ``inj_base_ms``)."""
    return [
        table(axes, _K.VE, ve_label),
        table(axes, _K.LAMBDA_TARGET, "Lambda alvo", required=True),
        table(axes, _K.IGNITION_BASE, "Avanço de ignição", required=True),
        table(axes, _K.INJ_DEAD_TIME, "Tempo morto do bico", required=True),
        table(axes, _K.FUEL_TRIM_CYL, "Correção de combustível por cilindro", per_cylinder=True),
        table(axes, _K.IGNITION_TRIM_CYL, "Correção de avanço por cilindro", per_cylinder=True),
        table(axes, _K.IGN_CORR_IAT, "Correção de avanço pela temperatura do ar"),
        table(axes, _K.IGN_CORR_ECT, "Correção de avanço pela temperatura do motor"),
        table(axes, _K.FUEL_CORR_ECT, "Correção de mistura pela temperatura do motor"),
        table(axes, _K.FUEL_CORR_IAT, "Correção de mistura pela temperatura do ar"),
        table(axes, _K.ACCEL_ENRICH, "Enriquecimento de aceleração"),
        table(axes, _K.CRANKING_FUEL, "Combustível de partida"),
        table(axes, _K.AFTERSTART_ENRICH, "Enriquecimento pós-partida"),
        table(axes, _K.BOOST_TARGET, "Pressão alvo do turbo"),
        table(axes, _K.BOOST_TARGET_GEAR, "Pressão máxima por marcha"),
        table(axes, _K.BOOST_DUTY_BASE, "Duty base da wastegate"),
        table(axes, _K.KNOCK_THRESHOLD, "Limiar de detonação"),
        table(axes, _K.OIL_PRESSURE_MIN, "Pressão mínima de óleo"),
        table(axes, _K.CAM_INTAKE_TARGET, "Comando de admissão alvo"),
        table(axes, _K.CAM_EXHAUST_TARGET, "Comando de escape alvo"),
        *flex_tables(axes),
    ]


def flex_tables(axes: AxisSet) -> list[TableSupport]:
    """Tabelas opcionais do sensor flex (eixo ``ethanol_pct``, 002 RF-18)."""
    return [
        table(axes, _K.FLEX_IGN_ADD, "Avanço adicional por etanol"),
        table(axes, _K.FLEX_BOOST_ADD, "Pressão adicional por etanol"),
    ]


def vvt_section(prefix: str, label: str) -> NavSection:
    """Secção de came variável: tabelas de came e a estratégia ``vvt`` (002 RF-12)."""
    return section(prefix, label, [
        nav_table(f"{prefix}.intake", "Comando de admissão alvo", _K.CAM_INTAKE_TARGET),
        nav_table(f"{prefix}.exhaust", "Comando de escape alvo", _K.CAM_EXHAUST_TARGET),
        nav_strategy(f"{prefix}.control", "Controle do comando variável", StrategyKind.VVT),
    ])  # fmt: skip


def flex_section(prefix: str, label: str) -> NavSection:
    """Secção do sensor flex: avanço e pressão adicionais por teor de etanol."""
    return section(prefix, label, [
        nav_table(f"{prefix}.ign_add", "Avanço adicional por etanol", _K.FLEX_IGN_ADD),
        nav_table(f"{prefix}.boost_add", "Pressão adicional por etanol", _K.FLEX_BOOST_ADD),
    ])  # fmt: skip


def finish_standalone(
    *,
    profile_id: EcuProfileId,
    name: str,
    inspiration: str,
    tables: list[TableSupport],
    strategies: list[StrategySupport],
    navigation: list[NavSection],
    fuel_modes: list[FuelModelMode],
    units: DisplayUnits,
    packages: list[FeaturePackage],
    accent: str,
    extra_terms: dict[str, str] | None = None,
) -> EcuProfileDescriptor:
    """Monta um descritor standalone (terminologia e ``live_tunable_table_ids`` derivados)."""
    terminology = {t.kind.value: t.display_name for t in tables}
    terminology.update({s.kind.value: s.display_name for s in strategies})
    terminology.update({"map_kpa": "Pressão no coletor (MAP)", "rpm": "Rotação"})
    terminology.update(extra_terms or {})
    nav_tables = {i.target_id for s in navigation for i in s.items if i.kind == "table"}
    return EcuProfileDescriptor(
        profile_id=profile_id,
        name=name,
        family=ProfileFamily.STANDALONE,
        inspiration=inspiration,
        descriptor_version="1.0.0",
        fuel_model_modes=fuel_modes,
        default_fuel_model_mode=fuel_modes[0],
        tables=tables,
        strategies=strategies,
        terminology=terminology,
        display_units=units,
        requires_base_setup=True,
        base_setup_steps=list(STANDALONE_STEPS),
        feature_packages=packages,
        navigation=navigation,
        live_tunable_table_ids=[
            t.kind.value for t in tables if t.live_tunable and t.kind.value in nav_tables
        ],
        load_axis_channel="map_kpa",
        accent_color=accent,
    )
