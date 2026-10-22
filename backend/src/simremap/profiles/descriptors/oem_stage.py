"""Descritor ``oem-stage`` ("OEM-Stage"): ECU original com estrutura de torque (RF-01, RF-03).

Navegação do Apêndice B: "Pedido de torque", "Limitação de torque", "Ignição e
eficiência", "Pressão alvo do turbo", "Mistura e proteção de componentes", "Overrun",
"Proteções e checksum". A tabela ``ve`` de série é obrigatória (modelo de enchimento da
própria ECU, RF-08) mas não aparece na navegação do Stage. Trims por cilindro: só
ignição, aceites numa calibração importada mas fora da navegação (003 T032): as
calibrações de série do catálogo não os trazem (os itens "Avanço cil. 1–n" não abriam
nada) e a ECU original corrige cada cilindro pela adaptação do knock control, não por
trims do preparador. Sem ``BaseSetup`` editável (RF-13) e sem two-step, antilag nem
powershift.
"""

from __future__ import annotations

from typing import Final

from simremap.ecu.contracts import AxisQuantity, StrategyKind, TableKind
from simremap.profiles.contracts import (
    DisplayUnits,
    EcuProfileDescriptor,
    EcuProfileId,
    ProfileFamily,
)
from simremap.profiles.descriptors.common import (
    AxisSet,
    flex_section,
    flex_tables,
    nav_info,
    nav_strategy,
    nav_table,
    section,
    strategy,
    table,
    vvt_section,
)

__all__ = ["INSPIRATION", "NAME", "build_descriptor"]

NAME: Final = "OEM-Stage"
INSPIRATION: Final = (
    "ECU original moderna com estrutura de torque: pedido do pedal, limitação, carga alvo, "
    "pressão alvo e eficiência de ignição"
)

_K = TableKind
_S = StrategyKind
_LOAD = AxisQuantity.LOAD_PCT


def build_descriptor(axes: AxisSet) -> EcuProfileDescriptor:
    tables = [
        table(axes, _K.TORQUE_REQUEST, "Pedido de torque do pedal", required=True),
        table(axes, _K.TORQUE_LIMIT, "Limite de torque por rotação", required=True),
        table(axes, _K.TORQUE_LIMIT_GEAR, "Limite de torque por marcha", required=True),
        table(axes, _K.TORQUE_OPTIMAL, "Torque ótimo por carga", required=True),
        table(axes, _K.IGNITION_OPTIMAL, "Avanço ótimo", required=True),
        table(axes, _K.IGNITION_BASE, "Avanço base", required=True, y=_LOAD),
        table(axes, _K.IGNITION_EFFICIENCY, "Eficiência de ignição", required=True),
        table(axes, _K.OEM_PRESSURE_TARGET, "Pressão alvo do turbo", required=True),
        table(axes, _K.FRICTION_TORQUE, "Torque de atrito", required=True),
        table(
            axes, _K.LAMBDA_COMPONENT_PROTECTION, "Lambda de proteção de componentes", required=True
        ),
        table(axes, _K.LAMBDA_TARGET, "Lambda alvo", required=True),
        table(axes, _K.VE, "Modelo de enchimento de série", required=True),
        table(axes, _K.IGNITION_TRIM_CYL, "Correção de avanço por cilindro", y=_LOAD,
              per_cylinder=True),
        table(axes, _K.IGN_CORR_IAT, "Correção de avanço pela temperatura do ar"),
        table(axes, _K.IGN_CORR_ECT, "Correção de avanço pela temperatura do motor"),
        table(axes, _K.FUEL_CORR_ECT, "Correção de mistura pela temperatura do motor"),
        table(axes, _K.FUEL_CORR_IAT, "Correção de mistura pela temperatura do ar"),
        table(axes, _K.ACCEL_ENRICH, "Enriquecimento de aceleração"),
        table(axes, _K.CRANKING_FUEL, "Combustível de partida"),
        table(axes, _K.AFTERSTART_ENRICH, "Enriquecimento pós-partida"),
        table(axes, _K.INJ_DEAD_TIME, "Tempo morto do bico"),
        table(axes, _K.BOOST_DUTY_BASE, "Duty base da wastegate"),
        table(axes, _K.KNOCK_THRESHOLD, "Limiar de detonação"),
        table(axes, _K.OIL_PRESSURE_MIN, "Pressão mínima de óleo"),
        table(axes, _K.CAM_INTAKE_TARGET, "Comando de admissão alvo"),
        table(axes, _K.CAM_EXHAUST_TARGET, "Comando de escape alvo"),
        *flex_tables(axes),
    ]  # fmt: skip
    strategies = [
        strategy(_S.CLOSED_LOOP, "supported", "Malha fechada de lambda"),
        strategy(_S.KNOCK_CONTROL, "supported", "Proteção contra detonação"),
        strategy(_S.BOOST_CONTROL, "supported", "Controle da pressão do turbo"),
        strategy(_S.REV_LIMITER, "supported", "Limitador de rotação"),
        strategy(_S.TWO_STEP, "unsupported", "Two-step"),
        strategy(_S.ANTILAG, "unsupported", "Antilag"),
        strategy(_S.POWERSHIFT, "unsupported", "Troca rápida de marcha"),
        strategy(_S.OVERRUN, "supported", "Corte em desaceleração e estalos"),
        strategy(_S.FAILSAFE, "supported", "Proteções de componentes"),
        strategy(_S.VVT, "supported", "Comando variável de válvulas"),
    ]
    navigation = [
        section("torque-request", "Pedido de torque", [
            nav_table("torque.request", "Pedido de torque do pedal", _K.TORQUE_REQUEST),
        ]),
        section("torque-limit", "Limitação de torque", [
            nav_table("torque.limit", "Limite por rotação", _K.TORQUE_LIMIT),
            nav_table("torque.limit_gear", "Limite por marcha", _K.TORQUE_LIMIT_GEAR),
        ]),
        section("ignition", "Ignição e eficiência", [
            nav_table("ign.base", "Avanço base", _K.IGNITION_BASE),
            nav_table("ign.optimal", "Avanço ótimo", _K.IGNITION_OPTIMAL),
            nav_table("ign.efficiency", "Eficiência de ignição", _K.IGNITION_EFFICIENCY),
            nav_table("ign.torque_optimal", "Torque ótimo por carga", _K.TORQUE_OPTIMAL),
            nav_table("ign.corr_iat", "Correção pela temperatura do ar", _K.IGN_CORR_IAT),
        ]),
        section("boost", "Pressão alvo do turbo", [
            nav_table("boost.pressure_target", "Pressão alvo", _K.OEM_PRESSURE_TARGET),
            nav_strategy("boost.control", "Controle da wastegate", _S.BOOST_CONTROL),
        ]),
        section("mixture", "Mistura e proteção de componentes", [
            nav_table("mix.lambda_target", "Lambda alvo", _K.LAMBDA_TARGET),
            nav_table("mix.component_protection", "Lambda de proteção",
                      _K.LAMBDA_COMPONENT_PROTECTION),
            nav_strategy("mix.closed_loop", "Malha fechada de lambda", _S.CLOSED_LOOP),
        ]),
        section("overrun", "Overrun", [
            nav_strategy("overrun.config", "Corte em desaceleração e estalos", _S.OVERRUN),
        ]),
        section("protection", "Proteções e checksum", [
            nav_info("prot.flags", "Flags de proteção", "oem_protection_flags"),
            nav_strategy("prot.knock", "Proteção contra detonação", _S.KNOCK_CONTROL),
            nav_strategy("prot.limiter", "Limitador de rotação", _S.REV_LIMITER),
            nav_strategy("prot.failsafe", "Proteções de componentes", _S.FAILSAFE),
            nav_info("prot.checksum", "Checksum da calibração", "oem_checksum"),
        ]),
        vvt_section("cams", "Comando variável (VVT)"),
        flex_section("flex", "Flex (teor de etanol)"),
    ]  # fmt: skip
    terminology = {t.kind.value: t.display_name for t in tables}
    terminology.update({s.kind.value: s.display_name for s in strategies})
    terminology.update(
        {
            "load_pct": "Carga relativa",
            "oem_torque_request_nm": "Pedido de torque",
            "oem_load_target_pct": "Carga alvo",
            "oem_torque_limiter_active": "Limitador de torque ativo",
            "oem_torque_ign_retard_deg": "Atraso de intervenção de torque",
        }
    )
    nav_tables = {i.target_id for s in navigation for i in s.items if i.kind == "table"}
    return EcuProfileDescriptor(
        profile_id=EcuProfileId.OEM_STAGE,
        name=NAME,
        family=ProfileFamily.OEM,
        inspiration=INSPIRATION,
        descriptor_version="1.0.0",
        fuel_model_modes=["profile_air_model"],
        default_fuel_model_mode="profile_air_model",
        tables=tables,
        strategies=strategies,
        terminology=terminology,
        display_units=DisplayUnits(pressure="bar_rel", mixture="lambda", injection="fuel_mass_mg"),
        requires_base_setup=False,
        base_setup_steps=[],
        feature_packages=["base"],
        navigation=navigation,
        live_tunable_table_ids=[
            t.kind.value for t in tables if t.live_tunable and t.kind.value in nav_tables
        ],
        load_axis_channel="load_pct",
        accent_color="#6B7A8F",
    )
