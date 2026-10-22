"""Descritor ``ft-pro``: injeção programável de arrancada (profiles RF-03, RF-14).

Injeção principal MAP × RPM em ms (``direct_pulse_ms``, padrão) ou em VE
(``speed_density_ve``) por escolha do usuário; setup guiado obrigatório; secção
"Funções de arrancada" com two-step, powershift, antilag (só ``activation = switch``) e
boost por marcha; o assistente sugere E100.
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
    table,
    trim_items,
    vvt_section,
)

__all__ = ["INSPIRATION", "NAME", "SUGGESTED_FUEL_ID", "build_descriptor"]

NAME: Final = "FT-Pro"
INSPIRATION: Final = (
    "Injeção programável de arrancada: mapa MAP×RPM em ms ou VE, setup guiado, two-step, "
    "powershift, antilag, boost por marcha e foco em E100"
)
SUGGESTED_FUEL_ID: Final = "e100"

_K = TableKind
_S = StrategyKind


def build_descriptor(axes: AxisSet) -> EcuProfileDescriptor:
    tables = [
        table(axes, _K.INJ_BASE_MS, "Mapa principal de injeção (ms)"),
        *standalone_tables(axes, "Mapa principal de injeção (VE)"),
    ]
    strategies = [
        strategy(_S.CLOSED_LOOP, "supported", "Malha fechada de lambda"),
        strategy(_S.KNOCK_CONTROL, "supported", "Controle de detonação"),
        strategy(_S.BOOST_CONTROL, "supported", "Boost por marcha"),
        strategy(_S.REV_LIMITER, "supported", "Corte de rotação"),
        strategy(_S.TWO_STEP, "supported", "Two-step"),
        strategy(_S.ANTILAG, "supported", "Antilag por botão", {"activation": ["switch"]}),
        strategy(_S.POWERSHIFT, "supported", "Powershift"),
        strategy(_S.OVERRUN, "supported", "Corte em desaceleração e estalos"),
        strategy(_S.FAILSAFE, "supported", "Proteções do motor"),
        strategy(_S.VVT, "supported", "Comando variável de válvulas"),
    ]
    navigation = [
        base_setup_section("base-setup", "Configuração base (setup guiado)"),
        section("injection", "Injeção principal", [
            nav_table("inj.base_ms", "Mapa principal (ms)", _K.INJ_BASE_MS),
            nav_table("inj.ve", "Mapa principal (VE)", _K.VE),
            nav_table("inj.lambda_target", "Lambda alvo", _K.LAMBDA_TARGET),
            nav_table("inj.dead_time", "Tempo morto do bico", _K.INJ_DEAD_TIME),
            nav_table("inj.cranking", "Partida", _K.CRANKING_FUEL),
            nav_table("inj.afterstart", "Pós-partida", _K.AFTERSTART_ENRICH),
            nav_table("inj.accel", "Aceleração rápida", _K.ACCEL_ENRICH),
            nav_strategy("inj.closed_loop", "Malha fechada de lambda", _S.CLOSED_LOOP),
        ]),
        section("ignition", "Ignição", [
            nav_table("ign.base", "Avanço de ignição", _K.IGNITION_BASE),
            nav_table("ign.corr_iat", "Correção pela temperatura do ar", _K.IGN_CORR_IAT),
            nav_table("ign.corr_ect", "Correção pela temperatura do motor", _K.IGN_CORR_ECT),
            nav_table("ign.knock_threshold", "Limiar de detonação", _K.KNOCK_THRESHOLD),
            nav_strategy("ign.knock", "Controle de detonação", _S.KNOCK_CONTROL),
        ]),
        section("drag", "Funções de arrancada", [
            nav_strategy("drag.two_step", "Two-step", _S.TWO_STEP),
            nav_strategy("drag.powershift", "Powershift", _S.POWERSHIFT),
            nav_strategy("drag.antilag", "Antilag por botão", _S.ANTILAG),
            nav_strategy("drag.boost", "Boost por marcha", _S.BOOST_CONTROL),
            nav_table("drag.boost_target", "Pressão alvo", _K.BOOST_TARGET),
            nav_table("drag.boost_gear", "Pressão máxima por marcha", _K.BOOST_TARGET_GEAR),
            nav_table("drag.boost_duty", "Duty base da wastegate", _K.BOOST_DUTY_BASE),
        ]),
        section("corrections", "Correções", [
            nav_table("corr.fuel_ect", "Mistura pela temperatura do motor", _K.FUEL_CORR_ECT),
            nav_table("corr.fuel_iat", "Mistura pela temperatura do ar", _K.FUEL_CORR_IAT),
            *trim_items("corr.fuel_cyl", "Combustível", _K.FUEL_TRIM_CYL, axes.n_cyl),
            *trim_items("corr.ign_cyl", "Avanço", _K.IGNITION_TRIM_CYL, axes.n_cyl),
            nav_strategy("corr.overrun", "Desaceleração e estalos", _S.OVERRUN),
        ]),
        section("protection", "Proteções", [
            nav_strategy("prot.failsafe", "Proteções do motor", _S.FAILSAFE),
            nav_strategy("prot.limiter", "Corte de rotação", _S.REV_LIMITER),
            nav_table("prot.oil", "Pressão mínima de óleo", _K.OIL_PRESSURE_MIN),
        ]),
        vvt_section("cams", "Comando variável (VVT)"),
        flex_section("flex", "Flex (teor de etanol)"),
    ]  # fmt: skip
    return finish_standalone(
        profile_id=EcuProfileId.FT_PRO,
        name=NAME,
        inspiration=INSPIRATION,
        tables=tables,
        strategies=strategies,
        navigation=navigation,
        fuel_modes=["direct_pulse_ms", "speed_density_ve"],
        units=DisplayUnits(pressure="bar_rel", mixture="lambda", injection="ms"),
        packages=["base"],
        accent="#7A6F5A",
    )
