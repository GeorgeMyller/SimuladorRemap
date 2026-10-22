"""Montagem do laço de uma sessão a partir do ``init_payload`` (simulation-bus 3.6 e 6; T414).

O worker nunca lê ficheiros do catálogo nem toca no banco: ``VehicleSpec``, ``FuelSpec`` e
o conteúdo da calibração chegam serializados em ``DynoInitPayload`` (JSON) e
``assemble`` constrói ``PhysicsEngine``, a ECU (atrás de ``EcuStage``), ``DamageModel``,
o rolo e o amostrador de telemetria.

ECU (``build_ecu_stage``): com ``profile_hooks = "registry"`` (padrão) e o pacote
``simremap.profiles`` presente, ``ProfiledEcu`` de ``build_profiled_ecu`` (adaptador de
hardware + hooks do perfil, ex.: caminho de torque do ``oem-stage``); ``"null"`` usa o
``EcuRuntime`` com ``NullProfileHooks`` (ecu-core Sprint 2). O comando ``ecu.swap`` troca
o estágio por ``swap_ecu_stage`` (``simremap.profiles.worker.handle_swap_command``).

Oficina com a sessão viva: ``install_hardware`` (comando ``hardware.install``) remonta a
física e o dano com o veículo modificado e mantém ECU, rolo e amostrador. A ECU OEM passa a
conhecer a vazão dos bicos novos; a standalone continua com a base declarada (o usuário
acerta a vazão na base setup).
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from simremap.catalog.contracts import FuelSpec, VehicleSpec
from simremap.damage.config import DamageConfig
from simremap.damage.model import DamageModel
from simremap.dyno.contracts import (
    SEED_MAX,
    AmbientConditions,
    CorrectionStandard,
    DynoRigConfig,
)
from simremap.dyno.correction import CorrectionResult, correction_factor
from simremap.dyno.rig import Driveline, RollerRig
from simremap.dyno.sampler import DEFAULT_FPS, TickSampler, load_sampler
from simremap.ecu.apply import handle_apply_command as ecu_handle_apply
from simremap.ecu.calibration import CalibrationContent
from simremap.ecu.compiled import EcuHardwareConfig, compile_calibration
from simremap.ecu.contracts import EcuStepResult
from simremap.ecu.hooks import NullProfileHooks
from simremap.ecu.runtime import EcuRuntime
from simremap.physics.contracts import PhysicsConfig, PhysicsFault, SensorReadings
from simremap.physics.engine import PhysicsEngine

__all__ = [
    "DEFAULT_IDLE_RPM",
    "DynoInitPayload",
    "EcuStage",
    "ProfiledEcuStage",
    "RuntimeEcuStage",
    "SessionParts",
    "assemble",
    "build_ecu_stage",
    "install_hardware",
    "profiles_available",
    "swap_ecu_stage",
]

DEFAULT_IDLE_RPM: Final = 850.0
PROFILES_ADAPTER_MODULE: Final = "simremap.profiles.adapter"


class DynoInitPayload(BaseModel):
    """Tudo o que o worker precisa para montar a sessão (serializado em JSON)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str = Field(min_length=1, max_length=36)
    seed: int = Field(ge=0, le=SEED_MAX)
    sim_hz: int = Field(ge=100, le=1000)
    vehicle: VehicleSpec
    fuel: FuelSpec
    calibration: CalibrationContent
    calibration_id: str = Field(min_length=1, max_length=64)
    calibration_version: int = Field(1, ge=1)
    calibration_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_id: str = "oem-stage"
    profile_hooks: Literal["registry", "null"] = "registry"
    ecu_state: Literal["oem", "awaiting_base_setup", "standalone_ready"] = "oem"
    stock_fuel: FuelSpec | None = None
    enabled_strategies: list[str] | None = None
    ambient: AmbientConditions = Field(default_factory=AmbientConditions)
    rig: DynoRigConfig = Field(default_factory=DynoRigConfig)
    correction_standard: CorrectionStandard = CorrectionStandard.SAE_J1349
    operator_protection: bool = False
    egt_abort_enabled: bool = True
    egt_abort_margin_c: float = Field(0.0, ge=0.0, le=200.0)
    damage_enabled: bool = True
    damage_config: DamageConfig | None = None
    physics_faults: list[PhysicsFault] = Field(default_factory=list, max_length=8)
    physics_noise: bool = True
    # Oficina e flex (002): veículo já modificado em ``vehicle``; escalas fora do veículo.
    exhaust_backpressure_scale: float = Field(1.0, ge=0.3, le=1.0)
    fuel_pump_capacity_scale: float = Field(1.0, ge=1.0, le=3.0)
    ethanol_pct: float | None = Field(None, ge=27.0, le=100.0)  # teor do blend flex
    initial_ect_c: float = Field(90.0, ge=-20.0, le=120.0)
    idle_rpm: float = Field(DEFAULT_IDLE_RPM, ge=500.0, le=1500.0)
    fps: int = Field(DEFAULT_FPS, ge=30, le=60)
    sampler: str | None = None
    # Espectro e traço de pressão no amostrador (None = padrão dele; a telemetria instala
    # False e liga-os por ``telemetry.config`` quando alguma conexão os pede).
    spectrum: bool | None = None
    pressure_trace: bool | None = None
    steps_per_tick: int = Field(1, ge=1, le=50)
    warmup_s: float = Field(3.0, ge=0.0, le=30.0)
    hold_until_command: bool = True  # espera determinística até o 1.º comando (RF-23)
    attempt_id: str | None = None


@runtime_checkable
class EcuStage(Protocol):
    """Estágio ECU do tick (``EcuRuntime`` direto ou ``ProfiledEcu`` do ecu-profiles)."""

    @property
    def runtime(self) -> EcuRuntime | None: ...

    @property
    def profile_id(self) -> str: ...

    @property
    def ecu_state(self) -> str: ...

    @property
    def fuel_mismatch_suspected(self) -> bool: ...

    def step(self, sensors: SensorReadings, dt: float) -> EcuStepResult: ...

    def set_knock_open_loop(self, enabled: bool) -> None: ...

    def apply_calibration(self, command: dict[str, object]) -> dict[str, object]: ...


class RuntimeEcuStage:
    """``EcuRuntime`` direto com ``NullProfileHooks`` (ecu-core Sprint 2, sem adaptador)."""

    __slots__ = ("_profile_id", "_runtime")

    def __init__(self, runtime: EcuRuntime, profile_id: str = "oem-stage") -> None:
        self._runtime = runtime
        self._profile_id = profile_id

    @property
    def runtime(self) -> EcuRuntime:
        return self._runtime

    @property
    def profile_id(self) -> str:
        return self._profile_id

    @property
    def ecu_state(self) -> str:
        return "oem" if self._profile_id == "oem-stage" else "standalone_ready"

    @property
    def fuel_mismatch_suspected(self) -> bool:
        return False

    def step(self, sensors: SensorReadings, dt: float) -> EcuStepResult:
        return self._runtime.step(sensors, dt)

    def set_knock_open_loop(self, enabled: bool) -> None:
        self._runtime.set_knock_open_loop(enabled)

    def apply_calibration(self, command: dict[str, object]) -> dict[str, object]:
        return ecu_handle_apply(self._runtime, command)


class ProfiledEcuStage:
    """``ProfiledEcu`` do ecu-profiles (adaptador de hardware + runtime com hooks do perfil)."""

    __slots__ = ("_worker", "profiled")

    def __init__(self, profiled: Any) -> None:
        from simremap.profiles import worker  # noqa: PLC0415 - pré-carrega fora do tick

        self.profiled = profiled
        self._worker = worker

    @property
    def runtime(self) -> EcuRuntime | None:
        runtime: EcuRuntime | None = self.profiled.runtime
        return runtime

    @property
    def profile_id(self) -> str:
        return str(self.profiled.profile_id.value)

    @property
    def ecu_state(self) -> str:
        return str(self.profiled.ecu_state)

    @property
    def fuel_mismatch_suspected(self) -> bool:
        return bool(self.profiled.fuel_mismatch_suspected)

    def step(self, sensors: SensorReadings, dt: float) -> EcuStepResult:
        result: EcuStepResult = self.profiled.step(sensors, dt)
        return result

    def set_knock_open_loop(self, enabled: bool) -> None:
        runtime = self.runtime
        if runtime is not None:
            runtime.set_knock_open_loop(enabled)

    def apply_calibration(self, command: dict[str, object]) -> dict[str, object]:
        ack: dict[str, object] = self._worker.handle_apply_command(self.profiled, command)
        return ack


def profiles_available() -> bool:
    """``True`` quando o pacote ``simremap.profiles`` expõe a montagem do ``ProfiledEcu``."""
    try:
        module = importlib.import_module(PROFILES_ADAPTER_MODULE)
    except ImportError:
        return False
    return callable(getattr(module, "build_profiled_ecu", None))


def build_ecu_stage(payload: DynoInitPayload, vehicle: VehicleSpec, fuel: FuelSpec) -> EcuStage:
    """Estágio ECU da sessão (ponto de troca ``EcuRuntime`` ↔ ``ProfiledEcu``).

    ``profile_hooks = "registry"`` (padrão) com o ecu-profiles instalado: ``ProfiledEcu``
    montado por ``simremap.profiles.adapter.build_profiled_ecu`` (perfil, ``ecu_state``,
    calibração). ``"null"`` ou sem o pacote de perfis: ``EcuRuntime`` com ``NullProfileHooks``.
    """
    stock_fuel = payload.stock_fuel or fuel
    enabled = (
        frozenset(payload.enabled_strategies) if payload.enabled_strategies is not None else None
    )
    if payload.profile_hooks == "registry" and profiles_available():
        from simremap.profiles.adapter import build_profiled_ecu  # noqa: PLC0415

        profiled = build_profiled_ecu(
            vehicle=vehicle,
            stock_fuel=stock_fuel,
            profile_id=payload.profile_id,
            ecu_state=payload.ecu_state,
            base_setup=None,
            calibration=payload.calibration,
            calibration_id=payload.calibration_id,
            calibration_version=payload.calibration_version,
            content_hash=payload.calibration_hash,
            enabled_strategies=enabled,
        )
        if profiled.runtime is not None:
            profiled.runtime.reset_session()
        return ProfiledEcuStage(profiled)
    compiled = compile_calibration(
        payload.calibration,
        vehicle.engine.n_cyl,
        calibration_id=payload.calibration_id,
        version=payload.calibration_version,
        content_hash=payload.calibration_hash,
    )
    runtime = EcuRuntime(
        compiled,
        NullProfileHooks(payload.profile_id),
        EcuHardwareConfig.from_vehicle(vehicle, stock_fuel),
        enabled_strategies=enabled,
    )
    runtime.reset_session()
    return RuntimeEcuStage(runtime, payload.profile_id)


def swap_ecu_stage(
    payload: DynoInitPayload, command: dict[str, object]
) -> tuple[EcuStage, dict[str, object]]:
    """Comando ``ecu.swap``: novo ``ProfiledEcu`` e o ``ack`` (sem ``applied_t_sim_s``)."""
    from simremap.profiles.worker import handle_swap_command  # noqa: PLC0415

    enabled = (
        frozenset(payload.enabled_strategies) if payload.enabled_strategies is not None else None
    )
    profiled, ack = handle_swap_command(
        command,
        vehicle=payload.vehicle,
        stock_fuel=payload.stock_fuel or payload.fuel,
        enabled_strategies=enabled,
    )
    return ProfiledEcuStage(profiled), ack


@dataclass(slots=True)
class SessionParts:
    """Componentes vivos de uma sessão no worker."""

    payload: DynoInitPayload
    vehicle: VehicleSpec
    fuel: FuelSpec
    physics: PhysicsEngine
    ecu: EcuStage
    damage: DamageModel
    damage_config: DamageConfig
    driveline: Driveline
    rig: RollerRig
    sampler: TickSampler
    correction: CorrectionResult

    def make_damage(self, *, damage_enabled: bool) -> DamageModel:
        """Novo ``DamageModel`` da sessão (sondas usam ``damage_enabled = false``)."""
        config = self.damage_config if damage_enabled else probe_damage_config(self.payload)
        return DamageModel(
            config,
            self.vehicle,
            self.fuel,
            self.payload.seed,
            damage_enabled,
            session_id=self.payload.session_id,
            sim_hz=self.payload.sim_hz,
            physics=self.physics if damage_enabled else None,
            ethanol_pct=self.payload.ethanol_pct,
        )


def _damage_config(payload: DynoInitPayload, *, probe: bool = False) -> DamageConfig:
    config = payload.damage_config or DamageConfig()
    if (not payload.damage_enabled or probe) and not config.enabled("damage_off"):
        config = config.model_copy(update={"features": (*config.features, "damage_off")})
    return config


def _build_physics(payload: DynoInitPayload) -> PhysicsEngine:
    physics_config = PhysicsConfig(
        sim_hz=payload.sim_hz,
        seed=payload.seed,
        ambient_pressure_kpa=payload.ambient.pressure_kpa,
        ambient_temp_c=payload.ambient.temperature_c,
        noise_enabled=payload.physics_noise,
        faults=list(payload.physics_faults),
        exhaust_backpressure_scale=payload.exhaust_backpressure_scale,
        fuel_pump_capacity_scale=payload.fuel_pump_capacity_scale,
    )
    return PhysicsEngine(
        physics_config,
        payload.vehicle,
        payload.fuel,
        initial_ect_c=payload.initial_ect_c,
        ethanol_pct=payload.ethanol_pct,
    )


def _build_damage(
    payload: DynoInitPayload, config: DamageConfig, physics: PhysicsEngine
) -> DamageModel:
    return DamageModel(
        config,
        payload.vehicle,
        payload.fuel,
        payload.seed,
        payload.damage_enabled,
        session_id=payload.session_id,
        sim_hz=payload.sim_hz,
        physics=physics,
        ethanol_pct=payload.ethanol_pct,
    )


def assemble(payload: DynoInitPayload) -> SessionParts:
    """Constrói os componentes; erros de configuração propagam (``setup`` falha)."""
    vehicle = payload.vehicle
    fuel = payload.fuel
    physics = _build_physics(payload)
    ecu = build_ecu_stage(payload, vehicle, fuel)
    damage_config = _damage_config(payload)
    damage = _build_damage(payload, damage_config, physics)
    driveline = Driveline.from_vehicle(vehicle, payload.rig)
    rig = RollerRig(payload.rig, driveline, payload.ambient)
    sampler = load_sampler(
        payload.sampler,
        session_id=payload.session_id,
        sim_hz=payload.sim_hz,
        fps=payload.fps,
        n_cyl=vehicle.engine.n_cyl,
        afr_stoich=fuel.afr_stoich,
    )
    return SessionParts(
        payload=payload,
        vehicle=vehicle,
        fuel=fuel,
        physics=physics,
        ecu=ecu,
        damage=damage,
        damage_config=damage_config,
        driveline=driveline,
        rig=rig,
        sampler=sampler,
        correction=correction_factor(payload.correction_standard, payload.ambient),
    )


def install_hardware(
    parts: SessionParts,
    vehicle: VehicleSpec,
    *,
    exhaust_backpressure_scale: float,
    fuel_pump_capacity_scale: float,
) -> SessionParts:
    """Peças novas com a sessão viva: física e dano novos sobre ``vehicle`` (motor parado).

    Transmissão, rolo e amostrador ficam (as peças da oficina não mudam marchas, cilindros
    nem combustível). Erros de validação propagam antes de qualquer troca.
    """
    payload = parts.payload.model_copy(
        update={
            "vehicle": vehicle,
            "exhaust_backpressure_scale": exhaust_backpressure_scale,
            "fuel_pump_capacity_scale": fuel_pump_capacity_scale,
        }
    )
    physics = _build_physics(payload)
    damage = _build_damage(payload, parts.damage_config, physics)
    _update_ecu_injectors(parts.ecu, vehicle, payload.stock_fuel or payload.fuel)
    parts.payload = payload
    parts.vehicle = vehicle
    parts.physics = physics
    parts.damage = damage
    return parts


def _update_ecu_injectors(stage: EcuStage, vehicle: VehicleSpec, stock_fuel: FuelSpec) -> None:
    """ECU OEM lê a vazão dos bicos do catálogo: passa a ver os bicos instalados."""
    runtime = stage.runtime
    if runtime is None or stage.ecu_state != "oem":
        return
    hardware = EcuHardwareConfig.from_vehicle(vehicle, stock_fuel)
    runtime.hardware = hardware
    runtime.fuel.hw = hardware
    runtime.fuel.q_inj_g_ms = hardware.q_inj_ref_g_ms


def probe_damage_config(payload: DynoInitPayload) -> DamageConfig:
    """``DamageConfig`` das sondas (sempre com ``damage_off``)."""
    return _damage_config(payload, probe=True)


def payload_json(**fields: Any) -> bytes:
    """Atalho: ``DynoInitPayload(**fields)`` serializado (testes e serviço)."""
    return DynoInitPayload(**fields).model_dump_json().encode("utf-8")
