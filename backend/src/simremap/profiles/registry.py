"""Registo imutável dos 4 perfis e matriz de suporte (profiles RF-01 a RF-04; Apêndice B).

- Ordem fixa: ``oem-stage``, ``ft-pro``, ``m1-race``, ``ht-elite``; cada perfil tem
  ``EcuProfileDescriptor``, hooks (``ProfileHooks`` do ecu-core) e ``descriptor_version``.
- Validação no arranque (``validate_descriptor``): cada ``NavItem.target_id`` deve existir
  nas tabelas, nas estratégias suportadas, nos passos da base ou nas páginas informativas
  do perfil (``NAV_TARGET_NOT_SUPPORTED``); nenhuma string pode conter termo da lista de
  bloqueio (Apêndice G). Falha ⇒ ``RegistryInvalid`` (``PROFILE_REGISTRY_INVALID``).
- ``descriptor_for``: descritor com eixos reescalados ao veículo (RF-02) e, no
  ``m1-race``, a secção de competição omitida com o pacote ``base`` (RF-15).
- ``hooks_for``: hooks de validação (sem estado de laço) para o ecu-core;
  ``runtime_hooks``: hooks novos por runtime (o ``oem-stage`` guarda estado por tick).
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from math import ceil
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal

from simremap.ecu.hooks import ProfileHooks
from simremap.profiles.compliance import find_blocked_terms, iter_strings
from simremap.profiles.contracts import (
    EcuProfileDescriptor,
    EcuProfileId,
    EcuProfileSummary,
    FeaturePackage,
)
from simremap.profiles.descriptors import DESCRIPTOR_BUILDERS, PROFILE_ORDER, AxisSet
from simremap.profiles.errors import profile_error
from simremap.profiles.hooks.common import DescriptorHooks
from simremap.profiles.hooks.oem_stage import OemStageHooks
from simremap.profiles.hooks.standalone import StandaloneHooks

if TYPE_CHECKING:
    from simremap.catalog.contracts import VehicleSpec
    from simremap.core.errors import SimRemapError

__all__ = [
    "INFO_TARGETS",
    "ProfileRegistry",
    "RegistryHooksProvider",
    "RegistryInvalid",
    "axes_for_vehicle",
    "build_registry",
    "for_package",
    "get_registry",
    "support_matrix",
    "validate_descriptor",
]

INFO_TARGETS: Final = frozenset(
    {"oem_protection_flags", "oem_checksum", "channels", "injector_model", "fuel_model_mode"}
)
"""Páginas informativas aceites em ``NavItem.kind = info``."""
WIZARD_TARGET: Final = "wizard"
_BARO_KPA: Final = 101.325


class RegistryInvalid(ValueError):
    """Descritor inválido no arranque (``PROFILE_REGISTRY_INVALID``)."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def validate_descriptor(desc: EcuProfileDescriptor) -> None:
    """``NAV_TARGET_NOT_SUPPORTED`` e conformidade de marcas (RF-03, G-06)."""
    tables = {t.kind.value for t in desc.tables}
    strategies = {s.kind.value for s in desc.strategies if s.level != "unsupported"}
    race_only = {s.kind.value for s in desc.strategies if s.level == "package_race"}
    steps: set[str] = set(desc.base_setup_steps)
    if steps:
        steps.add(WIZARD_TARGET)
    for section in desc.navigation:
        for item in section.items:
            ok = {
                "table": item.target_id in tables,
                "strategy": item.target_id in strategies,
                "base_setup": item.target_id in steps,
                "info": item.target_id in INFO_TARGETS,
            }[item.kind]
            if not ok:
                raise RegistryInvalid(
                    "NAV_TARGET_NOT_SUPPORTED",
                    f"{desc.profile_id.value}: {item.id} aponta para {item.kind} "
                    f"{item.target_id!r} fora do perfil",
                )
            if (
                item.kind == "strategy"
                and item.target_id in race_only
                and not item.requires_package
            ):
                raise RegistryInvalid(
                    "NAV_TARGET_NOT_SUPPORTED",
                    f"{desc.profile_id.value}: {item.id} exige requires_package = race",
                )
    blocked = sorted(
        {t for s in iter_strings(desc.model_dump(mode="json")) for t in find_blocked_terms(s)}
    )
    if blocked:
        raise RegistryInvalid(
            "PROFILE_REGISTRY_INVALID",
            f"{desc.profile_id.value}: termos bloqueados {blocked}",
        )


def for_package(desc: EcuProfileDescriptor, package: FeaturePackage | None) -> EcuProfileDescriptor:
    """Sem o pacote ``race``, omite itens ``requires_package`` (e secções vazias)."""
    if package != "base" or "race" not in desc.feature_packages:
        return desc
    sections = []
    for section in desc.navigation:
        items = [i for i in section.items if i.requires_package is None]
        if items:
            sections.append(section.model_copy(update={"items": items}))
    return desc.model_copy(update={"navigation": sections})


def _max_pressure_kpa(vehicle: VehicleSpec) -> float:
    if vehicle.turbo is not None:
        return vehicle.turbo.compressor.pr_design * _BARO_KPA
    if vehicle.supercharger is not None:
        return max(vehicle.supercharger.adiabatic_efficiency.x_values) * _BARO_KPA
    return _BARO_KPA


def axes_for_vehicle(vehicle: VehicleSpec | None) -> AxisSet:
    """Eixos padrão (sem veículo) ou reescalados ao veículo (RF-02)."""
    if vehicle is None:
        return AxisSet()
    rpm_max = round(vehicle.mechanical_limits.rev_limit_rpm / 100.0) * 100.0
    map_max = max(320.0, ceil((_max_pressure_kpa(vehicle) + 20.0) / 10.0) * 10.0)
    return AxisSet(
        rpm_max=rpm_max,
        map_max_kpa=map_max,
        n_cyl=vehicle.engine.n_cyl,
        n_gears=len(vehicle.gear_ratios),
    )


def support_matrix(
    descriptors: Mapping[EcuProfileId, EcuProfileDescriptor],
) -> dict[str, dict[str, str]]:
    """Matriz do Apêndice B: ``{profile_id: {strategy_kind: level}}``."""
    return {
        pid.value: {s.kind.value: s.level for s in desc.strategies}
        for pid, desc in descriptors.items()
    }


class ProfileRegistry:
    """Registo imutável carregado no arranque."""

    def __init__(self, descriptors: Mapping[EcuProfileId, EcuProfileDescriptor]) -> None:
        if tuple(descriptors) != PROFILE_ORDER:
            raise RegistryInvalid(
                "PROFILE_REGISTRY_INVALID",
                "o registo deve ter exatamente oem-stage, ft-pro, m1-race e ht-elite, nesta ordem",
            )
        for desc in descriptors.values():
            validate_descriptor(desc)
        self._descriptors: Mapping[EcuProfileId, EcuProfileDescriptor] = MappingProxyType(
            dict(descriptors)
        )
        self._hooks: dict[EcuProfileId, DescriptorHooks] = {
            pid: self._make_hooks(desc) for pid, desc in descriptors.items()
        }

    @staticmethod
    def _make_hooks(
        desc: EcuProfileDescriptor,
        v_cyl_m3: float | None = None,
        *,
        throttle_above_baro: bool = False,
    ) -> DescriptorHooks:
        if desc.profile_id == EcuProfileId.OEM_STAGE:
            return OemStageHooks(desc, v_cyl_m3=v_cyl_m3, throttle_above_baro=throttle_above_baro)
        return StandaloneHooks(desc)

    @property
    def profile_ids(self) -> tuple[EcuProfileId, ...]:
        return tuple(self._descriptors)

    @property
    def descriptors(self) -> Mapping[EcuProfileId, EcuProfileDescriptor]:
        return self._descriptors

    def summaries(self, enabled: frozenset[str] | None = None) -> list[EcuProfileSummary]:
        return [
            EcuProfileSummary(
                profile_id=d.profile_id,
                name=d.name,
                family=d.family,
                inspiration=d.inspiration,
                descriptor_version=d.descriptor_version,
            )
            for d in self._descriptors.values()
            if enabled is None or d.profile_id.value in enabled
        ]

    def resolve(self, profile_id: str) -> EcuProfileId:
        """``EcuProfileId`` ou 404 ``ECU_PROFILE_NOT_FOUND``."""
        try:
            pid = EcuProfileId(profile_id)
        except ValueError:
            raise _not_found(profile_id) from None
        if pid not in self._descriptors:  # pragma: no cover - registo completo
            raise _not_found(profile_id)
        return pid

    def get(self, profile_id: str | EcuProfileId) -> EcuProfileDescriptor:
        return self._descriptors[self.resolve(str(profile_id))]

    def descriptor_for(
        self,
        profile_id: str | EcuProfileId,
        vehicle: VehicleSpec | None = None,
        feature_package: FeaturePackage | None = None,
    ) -> EcuProfileDescriptor:
        pid = self.resolve(str(profile_id))
        if vehicle is None:
            desc = self._descriptors[pid]
        else:
            desc = _vehicle_descriptor(pid, vehicle.vehicle_id, axes_for_vehicle(vehicle))
        return for_package(desc, feature_package)

    def hooks_for(self, profile_id: str) -> ProfileHooks:
        """Hooks de validação do ecu-core (``ProfileHooksProvider``)."""
        return self._hooks[self.resolve(profile_id)]

    def runtime_hooks(
        self, profile_id: str, v_cyl_m3: float, *, throttle_above_baro: bool = False
    ) -> DescriptorHooks:
        """Hooks novos para um ``EcuRuntime`` (estado do caminho de torque por sessão).

        ``throttle_above_baro``: compressor volumétrico (borboleta antes do compressor, sem
        wastegate): o OEM regula o MAP pela borboleta também acima do baro.
        """
        pid = self.resolve(profile_id)
        return self._make_hooks(
            self._descriptors[pid], v_cyl_m3, throttle_above_baro=throttle_above_baro
        )

    def family(self, profile_id: str | EcuProfileId) -> Literal["oem", "standalone"]:
        return "oem" if self.get(profile_id).family.value == "oem" else "standalone"

    def matrix(self) -> dict[str, dict[str, str]]:
        return support_matrix(self._descriptors)


def _not_found(profile_id: str) -> SimRemapError:
    return profile_error(
        "ECU_PROFILE_NOT_FOUND",
        f"O perfil de ECU {profile_id[:32]!r} não existe.",
        profile_id=profile_id[:32],
    )


@lru_cache(maxsize=64)
def _vehicle_descriptor_cached(
    pid: EcuProfileId, vehicle_id: str, rpm_max: float, map_max: float, n_cyl: int, n_gears: int
) -> EcuProfileDescriptor:
    axes = AxisSet(rpm_max=rpm_max, map_max_kpa=map_max, n_cyl=n_cyl, n_gears=n_gears)
    desc = DESCRIPTOR_BUILDERS[pid](axes)
    validate_descriptor(desc)
    return desc


def _vehicle_descriptor(pid: EcuProfileId, vehicle_id: str, axes: AxisSet) -> EcuProfileDescriptor:
    return _vehicle_descriptor_cached(
        pid, vehicle_id, axes.rpm_max, axes.map_max_kpa, axes.n_cyl, axes.n_gears
    )


def build_registry() -> ProfileRegistry:
    """Constrói os 4 descritores com os eixos padrão e valida o registo."""
    axes = AxisSet()
    return ProfileRegistry({pid: DESCRIPTOR_BUILDERS[pid](axes) for pid in PROFILE_ORDER})


_REGISTRY: list[ProfileRegistry] = []


def get_registry() -> ProfileRegistry:
    """Registo único do processo (construído e validado no primeiro uso ou no arranque)."""
    if not _REGISTRY:
        _REGISTRY.append(build_registry())
    return _REGISTRY[0]


class RegistryHooksProvider:
    """``ecu.ports.ProfileHooksProvider`` com os hooks reais (``app.state.ecu_profile_hooks``)."""

    def __init__(self, registry: ProfileRegistry | None = None) -> None:
        self.registry = registry or get_registry()

    def hooks_for(self, profile_id: str) -> ProfileHooks:
        return self.registry.hooks_for(profile_id)
