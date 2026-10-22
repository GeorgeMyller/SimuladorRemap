"""Base dos hooks de perfil: matriz de suporte aplicada à calibração (profiles RF-04).

``DescriptorHooks`` implementa ``ecu.hooks.ProfileHooks`` a partir do descritor:

- ``supported_strategies()``: kinds com nível ``supported`` ou ``package_race`` (o
  ecu-core recusa os outros com 422 ``STRATEGY_NOT_SUPPORTED_BY_PROFILE``);
- ``validate_calibration()``: tabela fora do perfil ⇒ ``TABLE_NOT_SUPPORTED_BY_PROFILE``;
  modo de combustível fora do perfil ⇒ ``STRATEGY_OPTION_NOT_SUPPORTED``; estratégia do
  pacote race com pacote ``base`` ⇒ ``STRATEGY_REQUIRES_PACKAGE``; opção restrita (ex.:
  ``antilag.activation = rolling`` no ``ft-pro``) ⇒ ``STRATEGY_OPTION_NOT_SUPPORTED``.

O pacote do ``m1-race`` vem de ``Calibration.profile_params["feature_package"]``
(``base`` por omissão), gravado pelo assistente a partir da ``BaseSetup``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from simremap.profiles import errors as _errors  # noqa: F401 - regista os códigos do perfil
from simremap.profiles.contracts import EcuProfileDescriptor

if TYPE_CHECKING:
    from simremap.ecu.calibration import CalibrationContent

__all__ = ["FEATURE_PACKAGE_PARAM", "DescriptorHooks", "Problem", "feature_package_of"]

FEATURE_PACKAGE_PARAM: Final = "feature_package"
Problem = tuple[str, str]


def feature_package_of(cal: CalibrationContent) -> str:
    value = cal.profile_params.get(FEATURE_PACKAGE_PARAM, "base")
    return value if value in ("base", "race") else "base"


class DescriptorHooks:
    """Hooks sem estado de laço (validação e suporte); base dos hooks de cada perfil."""

    def __init__(self, descriptor: EcuProfileDescriptor) -> None:
        self.descriptor = descriptor
        self.profile_id = descriptor.profile_id.value
        self._levels = {s.kind.value: s.level for s in descriptor.strategies}
        self._restricted = {s.kind.value: s.restricted_options for s in descriptor.strategies}
        self._supported = frozenset(k for k, lvl in self._levels.items() if lvl != "unsupported")
        self._tables = frozenset(t.kind for t in descriptor.tables)
        self._modes = frozenset(descriptor.fuel_model_modes)

    def supported_strategies(self) -> frozenset[str]:
        return self._supported

    def validate_calibration(
        self, cal: CalibrationContent, options: dict[str, bool]
    ) -> list[Problem]:
        problems: list[Problem] = []
        for table_id, tbl in sorted(cal.tables.items()):
            if tbl.kind not in self._tables:
                problems.append(
                    (
                        "TABLE_NOT_SUPPORTED_BY_PROFILE",
                        f"A tabela {table_id} ({tbl.kind.value}) não é suportada pelo perfil "
                        f"{self.profile_id}.",
                    )
                )
        if cal.fuel_model.mode not in self._modes:
            problems.append(
                (
                    "STRATEGY_OPTION_NOT_SUPPORTED",
                    f"O modo de combustível {cal.fuel_model.mode} não é suportado pelo perfil "
                    f"{self.profile_id}; use {', '.join(sorted(self._modes))}.",
                )
            )
        package = feature_package_of(cal)
        for kind, cfg in sorted(cal.strategies.items()):
            if not cfg.enabled:
                continue
            if self._levels.get(kind) == "package_race" and package != "race":
                problems.append(
                    (
                        "STRATEGY_REQUIRES_PACKAGE",
                        f"A estratégia {kind} exige o pacote race no perfil {self.profile_id}.",
                    )
                )
            for option, allowed in self._restricted.get(kind, {}).items():
                value = getattr(cfg, option, None)
                if value is not None and str(value) not in allowed:
                    problems.append(
                        (
                            "STRATEGY_OPTION_NOT_SUPPORTED",
                            f"{kind}.{option} = {value} não é suportado pelo perfil "
                            f"{self.profile_id}; valores aceites: {', '.join(allowed)}.",
                        )
                    )
        problems.extend(self.validate_profile(cal, options))
        return problems

    def validate_profile(self, cal: CalibrationContent, options: dict[str, bool]) -> list[Problem]:
        """Validação própria do perfil (sobrescrita pelo ``oem-stage``)."""
        return []

    def air_charge_mg(self, sensors: object, compiled: object) -> float | None:
        return None

    def adjust_requests(self, sensors: object, requests: object) -> None:
        return None
