"""Validação da ``BaseSetup``, checklist do Apêndice A e guarda de partida (RF-13, RF-19, RF-20).

- ``validate_base_setup``: regras que dependem do veículo (ordem de ignição com
  ``n_cyl`` cilindros) ⇒ 422 ``BASE_SETUP_INVALID`` com ``field`` e ``reason``.
- ``build_checklist``: os 13 itens do Apêndice A. Obrigatórios: ``trigger.wheel``,
  ``injectors.flow``, ``injectors.dead_time``, ``fuel.type``, ``sensors.map`` e ``base_map``
  (6); ``minimum_valid`` exige os 5 primeiros em ``ok`` ou ``warning``.
- ``pending_items``: itens obrigatórios fora de ``ok``/``warning`` (corpo do 409
  ``ECU_SETUP_INCOMPLETE``).
- ``setup_hash``: SHA-256 do JSON canônico da base (floats a 6 casas).
- ``oem_base_setup``: base fixa do ``oem-stage`` = hardware de série do veículo (RF-13).
- ``prefill_base_setup``: base pré-preenchida pela ficha (roda, ordem, bico, combustível, MAP).
- ``hardware_config``: ``EcuHardwareConfig`` declarado (vazão, ΔP de referência, dead time,
  AFR, densidade) entregue à compilação do runtime (OQ-01).
- ``ProfileSessionGuard``: ``can_start_run(session_id) -> list[str]`` (vazio = pode arrancar),
  consultado pelo dyno-bench antes de ``POST .../runs`` (D-REST-06).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING, Final, Literal

from simremap.ecu.calibration import canonical_json, round_floats
from simremap.ecu.compiled import EcuHardwareConfig
from simremap.profiles.contracts import (
    MINIMUM_CHECKLIST_IDS,
    BaseSetup,
    ChecklistItem,
    EcuState,
    FuelSetup,
    InjectorSetup,
    MapSensorSetup,
    NtcSensorSetup,
    ProtectionLimits,
    SensorSetup,
    SetupChecklist,
    TriggerSetup,
    VehicleEcuHardware,
    WidebandSetup,
)
from simremap.profiles.errors import base_setup_invalid, profile_error

if TYPE_CHECKING:
    from simremap.catalog.contracts import CatalogFuelId, FuelSpec, VehicleSpec
    from simremap.core.errors import SimRemapError

__all__ = [
    "CHECKLIST_ORDER",
    "REQUIRED_ITEMS",
    "BaseMapStatus",
    "ProfileSessionGuard",
    "SessionSetupState",
    "build_checklist",
    "hardware_config",
    "oem_base_setup",
    "pending_items",
    "prefill_base_setup",
    "setup_hash",
    "setup_incomplete_error",
    "validate_base_setup",
]

CHECKLIST_ORDER: Final[tuple[str, ...]] = (
    "trigger.wheel",
    "trigger.tdc_offset",
    "trigger.phase",
    "trigger.firing_order",
    "injectors.flow",
    "injectors.dead_time",
    "fuel.type",
    "sensors.map",
    "sensors.iat",
    "sensors.ect",
    "sensors.wideband",
    "protection.limits",
    "base_map",
)
REQUIRED_ITEMS: Final = frozenset(MINIMUM_CHECKLIST_IDS | {"base_map"})
BaseMapStatus = Literal["ok", "missing", "invalid"]
_OK_STATES: Final = ("ok", "warning")
_INJECTOR_REF_MAX_KPA: Final = 600.0  # limite de InjectorSetup.ref_pressure_kpa
_RAIL_MAX_KPA: Final = 800.0  # limite de InjectorSetup.rail_pressure_kpa

_MESSAGES: Final[dict[tuple[str, str], str]] = {
    ("trigger.wheel", "missing"): "Declare a roda fônica do sensor de rotação.",
    ("trigger.tdc_offset", "missing"): "Declare o PMS (padrão: valor nominal da ficha).",
    ("trigger.phase", "missing"): "Configure o sensor de fase e os modos de injeção e ignição.",
    ("trigger.firing_order", "missing"): "Declare a ordem de ignição (padrão: ficha).",
    ("injectors.flow", "missing"): "Declare a vazão dos bicos.",
    ("injectors.dead_time", "missing"): "Declare o tempo morto dos bicos.",
    ("fuel.type", "missing"): "Declare o combustível.",
    ("sensors.map", "missing"): "Declare a faixa do sensor MAP.",
    ("base_map", "missing"): "Gere e aplique o mapa base.",
    ("base_map", "invalid"): "O mapa base foi gravado mas não foi confirmado pelo simulador.",
}


def setup_hash(base: BaseSetup) -> str:
    """``sha256`` do JSON canônico da base (floats arredondados a 6 casas)."""
    payload = round_floats(base.model_dump(mode="json"))
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def validate_base_setup(base: BaseSetup, n_cyl: int) -> None:
    """Regras da base que dependem do veículo (422 ``BASE_SETUP_INVALID``)."""
    trig = base.trigger
    if trig is not None and len(trig.firing_order) != n_cyl:
        raise base_setup_invalid(
            "trigger.firing_order",
            f"FIRING_ORDER_INVALID: o motor tem {n_cyl} cilindros",
        )


def _item(
    item_id: str, status: str, *, code: str | None = None, message: str | None = None
) -> ChecklistItem:
    return ChecklistItem.model_validate(
        {
            "id": item_id,
            "required": item_id in REQUIRED_ITEMS,
            "status": status,
            "code": code,
            "message": message if message is not None else _MESSAGES.get((item_id, status), ""),
        }
    )


def build_checklist(
    base: BaseSetup | None,
    hardware: VehicleEcuHardware | None,
    *,
    base_map: BaseMapStatus = "missing",
    fuel_mismatch_suspected: bool = False,
    injector_undersized: bool = False,
    n_cyl: int | None = None,
) -> SetupChecklist:
    """Checklist do Apêndice A (``base = None`` ⇒ obrigatórios em ``missing``)."""
    b = base or BaseSetup()
    items: dict[str, ChecklistItem] = {}
    trig = b.trigger
    if trig is None:
        for item_id in ("trigger.wheel", "trigger.tdc_offset", "trigger.phase"):
            items[item_id] = _item(item_id, "missing")
        items["trigger.firing_order"] = _item("trigger.firing_order", "missing")
    else:
        items["trigger.wheel"] = _item("trigger.wheel", "ok")
        items["trigger.tdc_offset"] = _item("trigger.tdc_offset", "ok")
        if (
            trig.phase_sensor != "none"
            and hardware is not None
            and not hardware.phase_sensor_present
        ):
            items["trigger.phase"] = _item(
                "trigger.phase",
                "warning",
                code="PHASE_SENSOR_ABSENT",
                message="A ficha não mostra sensor de fase no motor.",
            )
        else:
            items["trigger.phase"] = _item("trigger.phase", "ok")
        size = n_cyl if n_cyl is not None else len(trig.firing_order)
        status = "ok" if len(trig.firing_order) == size else "invalid"
        items["trigger.firing_order"] = _item(
            "trigger.firing_order",
            status,
            code=None if status == "ok" else "FIRING_ORDER_INVALID",
        )
    inj = b.injectors
    for item_id in ("injectors.flow", "injectors.dead_time"):
        items[item_id] = _item(item_id, "missing" if inj is None else "ok")
    if inj is not None and injector_undersized:
        items["injectors.flow"] = _item(
            "injectors.flow",
            "warning",
            code="INJECTOR_UNDERSIZED",
            message="Duty estimado acima de 85 % no ponto de carga máxima.",
        )
    if b.fuel is None:
        items["fuel.type"] = _item("fuel.type", "missing")
    elif fuel_mismatch_suspected:
        items["fuel.type"] = _item(
            "fuel.type",
            "warning",
            code="FUEL_MISMATCH_SUSPECTED",
            message="Correção de malha fechada no limite: confira o combustível do tanque.",
        )
    else:
        items["fuel.type"] = _item("fuel.type", "ok")
    items["sensors.map"] = _item("sensors.map", "missing" if b.sensors.map is None else "ok")
    items["sensors.iat"] = _item("sensors.iat", "ok")
    items["sensors.ect"] = _item("sensors.ect", "ok")
    if b.sensors.wideband is None:
        items["sensors.wideband"] = _item(
            "sensors.wideband",
            "warning",
            code="WIDEBAND_ABSENT",
            message="Sem wideband: a malha fechada fica indisponível.",
        )
    else:
        items["sensors.wideband"] = _item("sensors.wideband", "ok")
    items["protection.limits"] = _item("protection.limits", "ok")
    items["base_map"] = _item("base_map", base_map)
    return SetupChecklist.from_items([items[i] for i in CHECKLIST_ORDER])


def pending_items(checklist: SetupChecklist) -> list[str]:
    """Itens obrigatórios fora de ``ok``/``warning``, na ordem do Apêndice A."""
    return [i.id for i in checklist.items if i.required and i.status not in _OK_STATES]


def setup_incomplete_error(session_id: str, pending: list[str]) -> SimRemapError:
    return profile_error(
        "ECU_SETUP_INCOMPLETE",
        "A ECU standalone não tem o setup mínimo: " + ", ".join(pending) + ".",
        session_id=session_id,
        pending=pending,
    )


# --------------------------------------------------------------------------- bases


def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else (high if value > high else value)


def _catalog_fuel_id(fuel: FuelSpec) -> CatalogFuelId:
    """Combustível do tanque da ECU: sempre do catálogo (o ``flex`` só existe na física)."""
    fuel_id = fuel.fuel_id
    if fuel_id == "flex":
        raise ValueError("o setup da ECU exige um combustível do catálogo, não 'flex'")
    return fuel_id


def oem_base_setup(vehicle: VehicleSpec, hardware: VehicleEcuHardware, fuel: FuelSpec) -> BaseSetup:
    """Base fixa do ``oem-stage``: hardware de série do veículo (RF-13).

    Pressões de bicos GDI (dezenas de MPa) são mostradas no limite do formulário
    (600 kPa de referência, 800 kPa de rail): a base OEM é só informativa.
    """
    inj = vehicle.injectors
    grid = inj.dead_time_ms
    row = min(range(len(grid.y_values)), key=lambda i: abs(grid.y_values[i] - inj.dp_ref_kpa))
    sequential = hardware.phase_sensor_present
    limits = vehicle.mechanical_limits
    rev = _clamp(limits.rev_limit_rpm, 2000.0, 12000.0)
    return BaseSetup(
        trigger=TriggerSetup(
            wheel=hardware.trigger_wheel,
            tdc_offset_deg=hardware.tdc_offset_nominal_deg,
            phase_sensor="cam_hall" if sequential else "none",
            phase_edge_deg=hardware.phase_edge_true_deg,
            injection_mode="sequential" if sequential else "semi_sequential",
            ignition_mode="sequential" if sequential else "wasted_spark",
            firing_order=list(hardware.firing_order),
        ),
        injectors=InjectorSetup(
            flow_cc_min=inj.flow_cc_min * inj.count_per_cyl,
            ref_pressure_kpa=_clamp(inj.dp_ref_kpa, 200.0, _INJECTOR_REF_MAX_KPA),
            dead_time_v=list(grid.x_values),
            dead_time_ms=[_clamp(v, 0.0, 5.0) for v in grid.z_values[row]],
            fuel_pressure_mode="map_referenced"
            if inj.pressure_reference == "manifold"
            else "fixed_rail",
            rail_pressure_kpa=_clamp(inj.rail_pressure_max_kpa, 200.0, _RAIL_MAX_KPA),
        ),
        fuel=FuelSetup(
            fuel_id=_catalog_fuel_id(fuel),
            afr_stoich=fuel.afr_stoich,
            density_g_cc=_clamp(fuel.density_kg_m3 / 1000.0, 0.68, 0.82),
        ),
        sensors=SensorSetup(
            map=MapSensorSetup(
                min_kpa=hardware.map_sensor_kpa[0], max_kpa=hardware.map_sensor_kpa[1]
            ),
            iat=NtcSensorSetup(curve=hardware.iat_curve),
            ect=NtcSensorSetup(curve=hardware.ect_curve),
            wideband=WidebandSetup(
                lambda_at_0v=hardware.wideband_true[0], lambda_at_5v=hardware.wideband_true[1]
            ),
        ),
        protection=ProtectionLimits(
            rev_limit_rpm=rev,
            overspeed_rpm=max(_clamp(limits.max_rpm, 2000.0, 13000.0), rev + 100.0),
            egt_max_c=_clamp(limits.egt_max_c, 600.0, 1100.0),
        ),
    )


def prefill_base_setup(
    vehicle: VehicleSpec, hardware: VehicleEcuHardware, fuel: FuelSpec
) -> BaseSetup:
    """Base pré-preenchida pela ficha (``prefill_from_hardware_sheet``).

    Roda, ordem de ignição, bico (vazão e tempo morto da etiqueta), combustível do tanque e
    faixa do MAP; PMS = nominal da ficha; modo semissequencial com centelha perdida.
    """
    oem = oem_base_setup(vehicle, hardware, fuel)
    assert oem.trigger is not None and oem.injectors is not None  # noqa: S101 - montado acima
    trigger = oem.trigger.model_copy(
        update={
            "phase_sensor": "none",
            "injection_mode": "semi_sequential",
            "ignition_mode": "wasted_spark",
        }
    )
    injectors = InjectorSetup(
        flow_cc_min=oem.injectors.flow_cc_min,
        ref_pressure_kpa=oem.injectors.ref_pressure_kpa,
        dead_time_v=oem.injectors.dead_time_v,
        dead_time_ms=oem.injectors.dead_time_ms,
    )
    return BaseSetup(
        trigger=trigger,
        injectors=injectors,
        fuel=oem.fuel,
        sensors=SensorSetup(map=oem.sensors.map),
    )


def hardware_config(base: BaseSetup, vehicle: VehicleSpec) -> EcuHardwareConfig:
    """``EcuHardwareConfig`` declarado pela base (a física usa o hardware real)."""
    inj = base.injectors
    fuel = base.fuel
    if inj is None or fuel is None:
        raise ValueError("base sem bicos ou combustível: setup mínimo incompleto")
    return EcuHardwareConfig(
        n_cyl=vehicle.engine.n_cyl,
        displacement_cc=vehicle.engine.displacement_cc,
        injector_flow_cc_min=inj.flow_cc_min,
        afr_stoich=fuel.afr_stoich,
        fuel_density_g_cc=fuel.density_g_cc,
        ref_pressure_kpa=inj.ref_pressure_kpa,
        dead_time_v=tuple(inj.dead_time_v),
        dead_time_ms=tuple(inj.dead_time_ms),
        use_rail_pressure=not inj.flow_vs_dp_kpa,
    )


# --------------------------------------------------------------------------- guarda


@dataclass(frozen=True, slots=True)
class SessionSetupState:
    """Estado de ECU de uma sessão para a guarda de partida."""

    profile_id: str
    ecu_state: EcuState
    pending: tuple[str, ...] = ()


class ProfileSessionGuard:
    """Guarda de partida (simulation-bus 3.3; profiles RF-20; D-REST-06).

    Mantida em memória pelo serviço de perfis a cada swap e gravação de base (e
    carregável a partir de ``ecu_session_state``). Sessão desconhecida pode arrancar
    (estado ``oem`` por omissão).
    """

    def __init__(self) -> None:
        self._states: dict[str, SessionSetupState] = {}
        self._lock = Lock()

    def update(self, session_id: str, state: SessionSetupState) -> None:
        with self._lock:
            self._states[session_id] = state

    def forget(self, session_id: str) -> None:
        with self._lock:
            self._states.pop(session_id, None)

    def state(self, session_id: str) -> SessionSetupState | None:
        with self._lock:
            return self._states.get(session_id)

    def can_start_run(self, session_id: str) -> list[str]:
        """Itens pendentes; lista vazia = a sessão pode iniciar puxadas."""
        state = self.state(session_id)
        if state is None or state.ecu_state != "awaiting_base_setup":
            return []
        return list(state.pending) or ["base_map"]

    def require_can_start(self, session_id: str) -> None:
        """Levanta 409 ``ECU_SETUP_INCOMPLETE`` com ``pending`` quando há itens pendentes."""
        pending = self.can_start_run(session_id)
        if pending:
            raise setup_incomplete_error(session_id, pending)

    def snapshot(self) -> Mapping[str, SessionSetupState]:
        with self._lock:
            return dict(self._states)
