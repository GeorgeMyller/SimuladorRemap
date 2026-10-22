"""Descritor ``ht-elite``: VE e lambda alvo com assistente em destaque (profiles RF-03, RF-16).

O assistente de mapa base é o primeiro item da navegação; correções de combustível e de
ignição por cilindro de 1 a ``n_cyl`` (até 8); antilag por botão ou em rolamento.
"""

from __future__ import annotations

from typing import Final

from simremap.ecu.contracts import StrategyKind, TableKind
from simremap.profiles.contracts import DisplayUnits, EcuProfileDescriptor, EcuProfileId
from simremap.profiles.descriptors.common import (
    AxisSet,
    base_setup_section,
    finish_standalone,
    flex_section,
    nav_strategy,
    nav_table,
    section,
    standalone_tables,
    strategy,
    trim_items,
    vvt_section,
)

__all__ = ["INSPIRATION", "NAME", "build_descriptor"]

NAME: Final = "HT-Elite"
INSPIRATION: Final = (
    "ECU programável com VE e lambda alvo, assistente de mapa base, correções por cilindro e "
    "antilag com rolamento"
)

_K = TableKind
_S = StrategyKind


def build_descriptor(axes: AxisSet) -> EcuProfileDescriptor:
    tables = standalone_tables(axes, "Tabela de VE")
    strategies = [
        strategy(_S.CLOSED_LOOP, "supported", "Malha fechada de lambda"),
        strategy(_S.KNOCK_CONTROL, "supported", "Controle de detonação"),
        strategy(_S.BOOST_CONTROL, "supported", "Controle de boost"),
        strategy(_S.REV_LIMITER, "supported", "Limitador de rotação"),
        strategy(_S.TWO_STEP, "supported", "Controle de largada"),
        strategy(_S.ANTILAG, "supported", "Antilag por botão ou em rolamento"),
        strategy(_S.POWERSHIFT, "supported", "Corte na troca de marcha"),
        strategy(_S.OVERRUN, "supported", "Desaceleração e estalos"),
        strategy(_S.FAILSAFE, "supported", "Proteções do motor"),
        strategy(_S.VVT, "supported", "Comando variável de válvulas"),
    ]
    navigation = [
        base_setup_section("wizard", "Assistente de mapa base", wizard_first=True),
        section("fuel", "Combustível (VE e lambda alvo)", [
            nav_table("fuel.ve", "Tabela de VE", _K.VE),
            nav_table("fuel.lambda_target", "Lambda alvo", _K.LAMBDA_TARGET),
            nav_table("fuel.dead_time", "Tempo morto do bico", _K.INJ_DEAD_TIME),
            nav_table("fuel.cranking", "Partida", _K.CRANKING_FUEL),
            nav_table("fuel.afterstart", "Pós-partida", _K.AFTERSTART_ENRICH),
            nav_table("fuel.accel", "Aceleração rápida", _K.ACCEL_ENRICH),
            nav_table("fuel.corr_ect", "Correção pela temperatura do motor", _K.FUEL_CORR_ECT),
            nav_table("fuel.corr_iat", "Correção pela temperatura do ar", _K.FUEL_CORR_IAT),
            nav_strategy("fuel.closed_loop", "Malha fechada de lambda", _S.CLOSED_LOOP),
        ]),
        section("ignition", "Ignição", [
            nav_table("ign.base", "Avanço de ignição", _K.IGNITION_BASE),
            nav_table("ign.corr_iat", "Correção pela temperatura do ar", _K.IGN_CORR_IAT),
            nav_table("ign.corr_ect", "Correção pela temperatura do motor", _K.IGN_CORR_ECT),
            nav_table("ign.knock_threshold", "Limiar de detonação", _K.KNOCK_THRESHOLD),
            nav_strategy("ign.knock", "Controle de detonação", _S.KNOCK_CONTROL),
        ]),
        section("cylinders", "Correções por cilindro", [
            *trim_items("cyl.fuel", "Combustível", _K.FUEL_TRIM_CYL, axes.n_cyl),
            *trim_items("cyl.ign", "Avanço", _K.IGNITION_TRIM_CYL, axes.n_cyl),
        ]),
        section("boost", "Sobrealimentação e antilag", [
            nav_strategy("boost.control", "Controle de boost", _S.BOOST_CONTROL),
            nav_table("boost.target", "Pressão alvo", _K.BOOST_TARGET),
            nav_table("boost.gear", "Pressão máxima por marcha", _K.BOOST_TARGET_GEAR),
            nav_table("boost.duty", "Duty base da wastegate", _K.BOOST_DUTY_BASE),
            nav_strategy("boost.antilag", "Antilag", _S.ANTILAG),
        ]),
        section("launch", "Arrancada", [
            nav_strategy("launch.two_step", "Controle de largada", _S.TWO_STEP),
            nav_strategy("launch.powershift", "Corte na troca de marcha", _S.POWERSHIFT),
        ]),
        section("protection", "Proteções", [
            nav_strategy("prot.failsafe", "Proteções do motor", _S.FAILSAFE),
            nav_strategy("prot.limiter", "Limitador de rotação", _S.REV_LIMITER),
            nav_strategy("prot.overrun", "Desaceleração e estalos", _S.OVERRUN),
            nav_table("prot.oil", "Pressão mínima de óleo", _K.OIL_PRESSURE_MIN),
        ]),
        vvt_section("cams", "Comando variável (VVT)"),
        flex_section("flex", "Flex (teor de etanol)"),
    ]  # fmt: skip
    return finish_standalone(
        profile_id=EcuProfileId.HT_ELITE,
        name=NAME,
        inspiration=INSPIRATION,
        tables=tables,
        strategies=strategies,
        navigation=navigation,
        fuel_modes=["speed_density_ve"],
        units=DisplayUnits(pressure="kpa_abs", mixture="afr", injection="ve_pct"),
        packages=["base"],
        accent="#6A5F73",
    )
