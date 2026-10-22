"""Acertos reais que aprovam os 7 cenários builtin (003 T021, RF-15).

Cada função recebe o conteúdo editável de uma calibração (``fuel_model``, ``tables``,
``strategies``, ``profile_params``) do ``hatch-20t-gdi`` OEM-Stage e o muda no lugar, como
um preparador faria no editor:

- ``rich_wot``: lambda alvo de plena carga (MAP ≥ ``min_map_kpa``) dentro da janela
  0,75–0,90 a partir de 2900 rpm; a série deixa 0,90–0,95 entre 2900 e 4100 rpm e a
  lambda medida passa de 0,90;
- ``boost_ceiling``: teto do ``oem_pressure_target`` por rotação (kPa abs);
- ``torque_headroom``: pedido e limites de torque da ECU acima do que a pressão entrega;
- ``stage1``/``stage2``/``pops``: os acertos dos cenários de ganho;
- ``fuel_pump_safe``: o acerto do cenário da bomba fraca (menos pressão no topo).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final

from qa_support import Json, interp, map_cells

TIP_IN_MAX_PCT: Final = 5.0  # % de combustível extra na aceleração (alvo 0,80 ⇒ λ ≥ 0,76)
LAMBDA_MID: Final = 0.86  # 2900–4000 rpm
LAMBDA_HIGH: Final = 0.80  # ≥ 4000 rpm (EGT pré-turbina ≤ 950 °C)
LAMBDA_FROM_RPM: Final = 2900.0
LAMBDA_HIGH_FROM_RPM: Final = 4000.0

# Stage 1 (como tests/integration/test_stage1_real_attempt.py): ~1,6 bar relativos no topo.
STAGE1_BOOST_RPM: Final = (4000.0, 4500.0, 5000.0, 5500.0, 6500.0)
STAGE1_BOOST_KPA: Final = (232.0, 236.0, 244.0, 252.0, 262.0)
STAGE1_TORQUE_NM: Final = 430.0
STAGE1_OVERBOOST_KPA: Final = 300.0

# Stage 2 (como o acerto corrigido da jornada do Lucas): até 292 kPa abs a 6300 rpm.
STAGE2_BOOST_RPM: Final = (4000.0, 4500.0, 5000.0, 5500.0, 6000.0, 6300.0, 6500.0)
STAGE2_BOOST_KPA: Final = (225.0, 226.0, 244.0, 260.0, 276.0, 292.0, 296.0)
STAGE2_TORQUE_NM: Final = 520.0
STAGE2_OVERBOOST_KPA: Final = 340.0
STAGE2_LAMBDA: Final = 0.80  # EGT da soltura do pedal (retardo da ECU por torque) ≤ 950 °C

# Bomba fraca (84 L/h): pressão de série até 4500 rpm e teto descendo para 170 kPa abs.
FUEL_PUMP_BOOST_RPM: Final = (4500.0, 5000.0, 5500.0, 6500.0)
FUEL_PUMP_BOOST_KPA: Final = (230.0, 200.0, 175.0, 165.0)


def rich_wot(
    content: Json,
    *,
    mid: float = LAMBDA_MID,
    high: float = LAMBDA_HIGH,
    min_map_kpa: float = 140.0,
) -> None:
    def cell(rpm: float, kpa: float, value: float) -> float:
        if kpa < min_map_kpa or rpm < LAMBDA_FROM_RPM:
            return value
        return min(value, high if rpm >= LAMBDA_HIGH_FROM_RPM else mid)

    map_cells(content["tables"]["lambda_target"], cell)
    calm_tip_in(content)


def calm_tip_in(content: Json) -> None:
    """Enriquecimento de aceleração ≤ ``TIP_IN_MAX_PCT`` (a bancada sobe o pedal a 100 %/s).

    Era o contorno do dTPS/dt espúrio perto de 100 % (até +36 % de combustível e λ 0,63 em
    plena carga), corrigido na ECU em 003 T032 (mediana de 3 do TPS); os 7 cenários passam
    sem ele e o limite fica como acerto conservador.
    """
    table = content["tables"].get("accel_enrich")
    if table is None:  # mapa base do assistente da standalone: sem enriquecimento
        return
    table["values"] = [min(v, TIP_IN_MAX_PCT) for v in table["values"]]


def boost_ceiling(content: Json, rpms: Sequence[float], kpas: Sequence[float]) -> None:
    def cell(rpm: float, _kpa: float, value: float) -> float:
        return min(value, interp(rpm, rpms, kpas))

    map_cells(content["tables"]["oem_pressure_target"], cell)


def torque_headroom(content: Json, *, request_factor: float, limit_nm: float) -> None:
    """Pedido ×``request_factor``; limites de série até 4250 rpm e ``limit_nm`` a 5250 rpm."""
    tables = content["tables"]
    request = tables["torque_request"]
    request["values"] = [[request_factor * v for v in row] for row in request["values"]]
    gear = tables["torque_limit_gear"]
    gear["values"] = [
        max(v, limit_nm) if g >= 3 else v
        for g, v in zip(gear["x"]["values"], gear["values"], strict=True)
    ]
    limit = tables["torque_limit"]
    mid = (400.0 + limit_nm) / 2.0 if limit_nm > 430.0 else 400.0
    limit["values"] = [
        max(v, interp(r, (4250.0, 4750.0, 5250.0), (v, mid, limit_nm))) if r >= 4250.0 else v
        for r, v in zip(limit["x"]["values"], limit["values"], strict=True)
    ]


def _overboost(content: Json, kpa: float) -> None:
    content["strategies"]["boost_control"]["overboost_kpa"] = kpa


def stage1(content: Json) -> None:
    torque_headroom(content, request_factor=1.2, limit_nm=STAGE1_TORQUE_NM)
    boost_ceiling(content, STAGE1_BOOST_RPM, STAGE1_BOOST_KPA)
    rich_wot(content)
    _overboost(content, STAGE1_OVERBOOST_KPA)


POPS_RETARD_DEG: Final = -10.0  # a série sugere −15°: a EGT do overrun passa de 950 °C
POPS_INTENSITY_PCT: Final = 40.0


def pops(content: Json, **overrides: Any) -> None:
    """Pops & bangs no overrun (janela 2500–6500 rpm, limite de EGT da turbina 950 °C)."""
    overrun = content["strategies"]["overrun"]
    overrun.update(
        {
            "pops_enabled": True,
            "catalyst_present": False,
            "ign_advance_deg": POPS_RETARD_DEG,
            "intensity_pct": POPS_INTENSITY_PCT,
            **overrides,
        }
    )


def stage2(content: Json) -> None:
    torque_headroom(content, request_factor=1.4, limit_nm=STAGE2_TORQUE_NM)
    boost_ceiling(content, STAGE2_BOOST_RPM, STAGE2_BOOST_KPA)
    rich_wot(content, mid=LAMBDA_MID, high=STAGE2_LAMBDA)
    map_cells(
        content["tables"]["ignition_base"],
        lambda rpm, _kpa, v: v + interp(rpm, (5000.0, 5500.0), (0.0, 1.0)),
    )
    _overboost(content, STAGE2_OVERBOOST_KPA)
    pops(content)


def fuel_pump_safe(content: Json) -> None:
    boost_ceiling(content, FUEL_PUMP_BOOST_RPM, FUEL_PUMP_BOOST_KPA)
    rich_wot(content)


# --------------------------------------------------------------------------- standalone

STANDALONE_WOT_MAP_KPA: Final = 290.0  # pressão máxima do assistente (plena carga do clássico)
STANDALONE_MIN_MAP_KPA: Final = 150.0  # células com pressão afinadas pela puxada base
STANDALONE_LAMBDA: Final = 0.83  # janela 0,75–0,88 do cenário
STANDALONE_SPOOL_LAMBDA: Final = 0.80
STANDALONE_SPOOL_KPA: Final = 100.0  # enchimento da turbina a 2900–3100 rpm: 120–135 kPa
IGNITION_PER_KPA: Final = 0.08  # ° a menos por kPa acima do MAP do schedule de referência


def classic_base_setup() -> Json:
    """Setup base do ``classic-20t-swap`` pela ficha (como a jornada do Rodrigo)."""
    return {
        "trigger": {"wheel": "60-2", "tdc_offset_deg": 90.0, "firing_order": [1, 3, 4, 2]},
        "injectors": {
            "flow_cc_min": 2000.0,
            "dead_time_v": [8.0, 10.0, 12.0, 14.0, 16.0],
            "dead_time_ms": [1.6, 1.2, 0.95, 0.8, 0.7],
        },
        "fuel": {"fuel_id": "e100", "afr_stoich": 9.0, "density_g_cc": 0.789},
        "sensors": {"map": {"min_kpa": 20.0, "max_kpa": 400.0}, "wideband": {}},
        "protection": {
            "rev_limit_rpm": 7200.0,
            "overspeed_rpm": 7500.0,
            "overboost_kpa": 300.0,
            "egt_max_c": 950.0,
        },
    }


def standalone_wot(content: Json, curve: Sequence[Json], vehicle_id: str) -> None:
    """Plena carga da standalone pela puxada base no mapa do assistente.

    - ``inj_base_ms`` × ``λ_medido / λ_alvo`` (MAP ≥ 150 kPa, faixa da puxada);
    - ``boost_duty_base`` da série (o assistente deixa a turbina na mola);
    - avanço do schedule de referência do veículo (MBT sem knock), −0,08 °/kPa acima do MAP
      do schedule.
    """
    from simremap.catalog.service import load_catalog

    catalog = load_catalog()
    tables = content["tables"]
    stock = catalog.get_factory_calibration_payload(vehicle_id, "oem-stage")
    assert stock is not None
    tables["boost_duty_base"] = stock["tables"]["boost_duty_base"]
    schedule = catalog.get_reference_command_schedule(vehicle_id).points
    s_rpm = [p.rpm for p in schedule]
    s_adv = [p.ignition_advance_deg for p in schedule]
    s_map = [p.map_target_kpa for p in schedule]
    c_rpm = [p["rpm"] for p in curve]
    c_lam = [p["lambda"] for p in curve]
    lam_t = tables["lambda_target"]
    lam_values = {
        (r, kpa): v
        for kpa, row in zip(lam_t["y"]["values"], lam_t["values"], strict=True)
        for r, v in zip(lam_t["x"]["values"], row, strict=True)
    }

    def fuel(rpm: float, kpa: float, value: float) -> float:
        if kpa < STANDALONE_MIN_MAP_KPA or not c_rpm[0] <= rpm <= c_rpm[-1]:
            return value
        target = lam_values.get((rpm, kpa))
        return value if target is None else value * interp(rpm, c_rpm, c_lam) / target

    def spark(rpm: float, kpa: float, value: float) -> float:
        if kpa < STANDALONE_MIN_MAP_KPA:
            return value
        adv = interp(rpm, s_rpm, s_adv) - IGNITION_PER_KPA * (kpa - interp(rpm, s_rpm, s_map))
        return round(min(max(adv, 5.0), 35.0), 2)

    map_cells(tables["inj_base_ms"], fuel)
    map_cells(tables["ignition_base"], spark)
    map_cells(tables["lambda_target"], standalone_lambda)


def standalone_lambda(rpm: float, kpa: float, value: float) -> float:
    """Alvo de plena carga: o enchimento sai ~0,04 pobre e a sobrepressão ~0,04 rica."""
    if rpm < LAMBDA_FROM_RPM or kpa < STANDALONE_SPOOL_KPA:
        return value
    return STANDALONE_SPOOL_LAMBDA if kpa < STANDALONE_MIN_MAP_KPA else STANDALONE_LAMBDA


def table_at(table: Json, rpm: float, kpa: float) -> float:
    """Valor bilinear de uma tabela 3D rpm × MAP."""
    xs, ys = table["x"]["values"], table["y"]["values"]
    column = [interp(rpm, xs, row) for row in table["values"]]
    return interp(kpa, ys, column)


def refine_fuel(content: Json, curve: Sequence[Json]) -> None:
    """2.ª passada de combustível com a puxada com pressão: ``inj_base_ms`` de cada coluna de
    rotação × ``λ_medido / λ_alvo`` no MAP medido (células com MAP ≥ 150 kPa)."""
    tables = content["tables"]
    c_rpm = [p["rpm"] for p in curve]
    factor = [
        p["lambda"] / table_at(tables["lambda_target"], p["rpm"], p["map_kpa"]) for p in curve
    ]

    def fuel(rpm: float, kpa: float, value: float) -> float:
        if kpa < STANDALONE_MIN_MAP_KPA or not c_rpm[0] <= rpm <= c_rpm[-1]:
            return value
        return value * interp(rpm, c_rpm, factor)

    map_cells(tables["inj_base_ms"], fuel)
