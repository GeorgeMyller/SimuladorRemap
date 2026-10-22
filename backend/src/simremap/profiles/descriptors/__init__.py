"""Descritores dos 4 perfis (um módulo por perfil; profiles RF-01, RF-03, Apêndice B)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from simremap.profiles.contracts import EcuProfileDescriptor, EcuProfileId
from simremap.profiles.descriptors import ft_pro, ht_elite, m1_race, oem_stage
from simremap.profiles.descriptors.common import AxisSet

__all__ = ["DESCRIPTOR_BUILDERS", "PROFILE_ORDER", "AxisSet"]

PROFILE_ORDER: Final[tuple[EcuProfileId, ...]] = (
    EcuProfileId.OEM_STAGE,
    EcuProfileId.FT_PRO,
    EcuProfileId.M1_RACE,
    EcuProfileId.HT_ELITE,
)

DESCRIPTOR_BUILDERS: Final[dict[EcuProfileId, Callable[[AxisSet], EcuProfileDescriptor]]] = {
    EcuProfileId.OEM_STAGE: oem_stage.build_descriptor,
    EcuProfileId.FT_PRO: ft_pro.build_descriptor,
    EcuProfileId.M1_RACE: m1_race.build_descriptor,
    EcuProfileId.HT_ELITE: ht_elite.build_descriptor,
}
