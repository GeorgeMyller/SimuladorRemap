"""Descritor ``m1-race``: ECU de competição por canais e funções (profiles RF-03, RF-15).

Eficiência do motor (VE) com lambda alvo, temperatura de carga combinada
(``charge_temp_blend`` padrão 0,25), modelo físico do bico (vazão vs ΔP e adição de
pulso curto) e o "pacote race" (opção gratuita de configuração, NG-07) que libera
two-step, antilag e powershift. Com pacote ``base`` a secção de competição é omitida
(ver ``registry.for_package``).
"""

from __future__ import annotations

from typing import Final, Literal

from simremap.ecu.contracts import StrategyKind, TableKind
from simremap.profiles.contracts import DisplayUnits, EcuProfileDescriptor, EcuProfileId
from simremap.profiles.descriptors.common import (
    AxisSet,
    finish_standalone,
    flex_section,
    nav_base,
    nav_info,
    nav_strategy,
    nav_table,
    section,
    standalone_tables,
    strategy,
    trim_items,
    vvt_section,
)

__all__ = ["CHARGE_TEMP_BLEND", "INSPIRATION", "NAME", "build_descriptor"]

NAME: Final = "M1-Race"
INSPIRATION: Final = (
    "ECU de competição por canais e funções: eficiência e lambda alvo, modelo físico do bico "
    "e pacote race"
)
CHARGE_TEMP_BLEND: Final = 0.25

_K = TableKind
_S = StrategyKind


def build_descriptor(axes: AxisSet) -> EcuProfileDescriptor:
    tables = standalone_tables(axes, "Eficiência do motor")
    strategies = [
        strategy(_S.CLOSED_LOOP, "supported", "Controle de lambda"),
        strategy(_S.KNOCK_CONTROL, "supported", "Controle de detonação"),
        strategy(_S.BOOST_CONTROL, "supported", "Controle de sobrealimentação"),
        strategy(_S.REV_LIMITER, "supported", "Limite de rotação"),
        strategy(_S.TWO_STEP, "package_race", "Controle de largada"),
        strategy(_S.ANTILAG, "package_race", "Antilag"),
        strategy(_S.POWERSHIFT, "package_race", "Troca sem levantar o pé"),
        strategy(_S.OVERRUN, "supported", "Desaceleração e estalos"),
        strategy(_S.FAILSAFE, "supported", "Proteções do motor"),
        strategy(_S.VVT, "supported", "Comando variável de válvulas"),
    ]
    race: Literal["race"] = "race"
    navigation = [
        section("channels", "Canais", [
            nav_info("chan.list", "Canais de entrada e saída", "channels"),
            nav_base("chan.trigger", "Rotação e sincronismo", "trigger"),
            nav_base("chan.sensors", "Sensores", "sensors"),
            nav_base("chan.fuel", "Combustível", "fuel"),
            nav_base("chan.protection", "Limites", "protection"),
            nav_base("chan.review", "Revisão e mapa base", "review"),
        ]),
        section("fn-fuel", "Funções: combustível", [
            nav_table("fuel.ve", "Eficiência do motor", _K.VE),
            nav_table("fuel.lambda_target", "Lambda alvo", _K.LAMBDA_TARGET),
            nav_table("fuel.cranking", "Partida", _K.CRANKING_FUEL),
            nav_table("fuel.afterstart", "Pós-partida", _K.AFTERSTART_ENRICH),
            nav_table("fuel.accel", "Transiente", _K.ACCEL_ENRICH),
            nav_table("fuel.corr_ect", "Temperatura do motor", _K.FUEL_CORR_ECT),
            nav_table("fuel.corr_iat", "Temperatura do ar", _K.FUEL_CORR_IAT),
            *trim_items("fuel.cyl", "Combustível", _K.FUEL_TRIM_CYL, axes.n_cyl),
            nav_strategy("fuel.lambda_control", "Controle de lambda", _S.CLOSED_LOOP),
        ]),
        section("fn-ignition", "Funções: ignição", [
            nav_table("ign.base", "Avanço de ignição", _K.IGNITION_BASE),
            nav_table("ign.corr_iat", "Temperatura do ar", _K.IGN_CORR_IAT),
            nav_table("ign.corr_ect", "Temperatura do motor", _K.IGN_CORR_ECT),
            *trim_items("ign.cyl", "Avanço", _K.IGNITION_TRIM_CYL, axes.n_cyl),
            nav_table("ign.knock_threshold", "Limiar de detonação", _K.KNOCK_THRESHOLD),
            nav_strategy("ign.knock", "Controle de detonação", _S.KNOCK_CONTROL),
        ]),
        section("fn-boost", "Funções: sobrealimentação", [
            nav_strategy("boost.control", "Controle de sobrealimentação", _S.BOOST_CONTROL),
            nav_table("boost.target", "Pressão alvo", _K.BOOST_TARGET),
            nav_table("boost.gear", "Pressão máxima por marcha", _K.BOOST_TARGET_GEAR),
            nav_table("boost.duty", "Duty base da wastegate", _K.BOOST_DUTY_BASE),
        ]),
        section("fn-race", "Funções: competição", [
            nav_strategy("race.launch", "Controle de largada", _S.TWO_STEP, package=race),
            nav_strategy("race.antilag", "Antilag", _S.ANTILAG, package=race),
            nav_strategy("race.shift", "Troca sem levantar o pé", _S.POWERSHIFT, package=race),
        ]),
        section("injector-model", "Modelo do bico", [
            nav_base("inj.setup", "Vazão, tempo morto e pulso curto", "injectors"),
            nav_table("inj.dead_time", "Tempo morto do bico", _K.INJ_DEAD_TIME),
            nav_info("inj.model", "Vazão vs pressão diferencial", "injector_model"),
        ]),
        section("protection", "Proteções", [
            nav_strategy("prot.failsafe", "Proteções do motor", _S.FAILSAFE),
            nav_strategy("prot.limiter", "Limite de rotação", _S.REV_LIMITER),
            nav_strategy("prot.overrun", "Desaceleração e estalos", _S.OVERRUN),
            nav_table("prot.oil", "Pressão mínima de óleo", _K.OIL_PRESSURE_MIN),
        ]),
        vvt_section("cams", "Comando variável (VVT)"),
        flex_section("flex", "Flex (teor de etanol)"),
    ]  # fmt: skip
    return finish_standalone(
        profile_id=EcuProfileId.M1_RACE,
        name=NAME,
        inspiration=INSPIRATION,
        tables=tables,
        strategies=strategies,
        navigation=navigation,
        fuel_modes=["speed_density_ve"],
        units=DisplayUnits(pressure="kpa_abs", mixture="lambda", injection="ve_pct"),
        packages=["base", "race"],
        accent="#5E6B5E",
        extra_terms={"charge_temp_blend": "Temperatura de carga combinada"},
    )
