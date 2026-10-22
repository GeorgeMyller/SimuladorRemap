"""Hooks do ``oem-stage``: caminho de torque, flags de proteção e checksum (profiles RF-05 a RF-13).

Caminho de torque (Apêndice C), executado no hook ``air_charge_mg`` (passo 3 do
``EcuRuntime.step``):

- ``T_req = torque_request(rpm, pedal)``;
- ``T_lim = min(T_req, torque_limit(rpm), torque_limit_gear(gear), T_prot)`` com
  ``T_prot = 0,5 · torque_limit`` em modo de emergência; o termo vencedor vai para
  ``oem_torque_limiter_active``;
- ``T_ind_des = T_lim + friction_torque(rpm, ect)``;
- ``load_target`` resolve ``torque_optimal(rpm, load) · η_base(load) = T_ind_des`` sobre a
  tabela inversa pré-calculada (16 colunas de RPM × 64 pontos de carga, refinada por
  interpolação linear); acima do máximo: borda superior e limitador ``protection`` (EC-16);
- ``p_target = oem_pressure_target(rpm, load_target)`` vira o alvo do controle de boost
  do ecu-core; abaixo de ``baro − 5 kPa`` a borboleta passa a PI sobre o MAP
  (``kp = 0,8 %/kPa``, ``ki = 4,0 %/(kPa·s)``) com wastegate a 0 %;
- ``load_actual = air_charge_mg / m_ref · 100`` com a tabela ``ve`` de série
  (speed-density do ecu-core) e ``m_ref = ρ_ref · V_cyl``;
- intervenção: ``T_poss = torque_optimal(rpm, load_actual) · η_base``; se
  ``T_poss > 1,02 · T_ind_des``, ``η_req = T_ind_des / torque_optimal`` e
  ``ign_cmd = min(ign_base, ignition_optimal − η⁻¹(η_req))``, com atraso ≤ 20°;
- monitorização: ``T_est > 1,10 · torque_limit`` por 0,5 s ⇒ modo de emergência
  (torque a 50 %, boost cortado, evento ``oem_limp_mode``) até a próxima aplicação;
- ``p_target`` no piso da tabela (80 kPa, limite do ecu-core): pressão pela inversão do
  speed-density ``p = load_target/100 · m_ref · MAP / air_charge_mg`` (≥ 10 kPa), para a
  borboleta fechar em carga parcial (complemento inferido);
- pedal fechado (≤ 1 %; complemento inferido, a spec não define marcha lenta):
  ``T_req = T_idle`` com PI de marcha lenta sobre ``idle_rpm`` (padrão 850 rpm ou
  ``profile_params.idle_rpm``; ``kp = 0,10 N·m/rpm``, ``ki = 0,30 N·m/(rpm·s)``, ±60 N·m;
  ``T_ind_des ≥ 0``) e o atrito só é compensado até ``idle_rpm + 400 rpm``; acima disso o torque
  indicado desejado é 0 e a borboleta fecha (desaceleração: DFCO do ecu-core). Sem isto o
  caminho de torque pede o atrito em qualquer rotação e o motor em ponto morto sobe ao
  limitador.

Integração com o runtime genérico (sem alterar o ecu-core): ao ligar uma
``CompiledCalibration`` nova, o hook troca na própria calibração compilada as tabelas
``ignition_base`` (devolve ``ign_cmd`` avaliado na carga real), ``boost_target`` (devolve
``p_target``) e, com ``component_protection``, ``lambda_target`` (devolve
``min(λ_alvo, lambda_component_protection(EGT))``, RF-10). Flags OEM em
``Calibration.profile_params`` (RF-11): ``knock_protection = false`` desliga o knock
control e ``overboost_protection = false`` desliga o corte por overboost do runtime
anexado; cada flag desligada emite ``oem_protection_disabled`` 1 vez por aplicação.

Calibração sem as tabelas do caminho de torque (ex.: importada de outro perfil): o hook
não inventa o caminho e devolve ``None`` (speed-density do ecu-core), com aviso no log.

Checksum (RF-12): ``oem_checksum = crc32(content_hash + ":oem-stage")`` em 8 dígitos
hexadecimais, guardado em ``metadata.extra.oem_checksum`` e verificado em cada
aplicação na sessão (``validate_calibration`` recebe a ``Calibration`` com metadados).
"""

from __future__ import annotations

import itertools
import zlib
from bisect import bisect_right
from dataclasses import dataclass
from math import inf
from typing import TYPE_CHECKING, Final, Literal

from simremap.core.logging import get_logger
from simremap.ecu.calibration import Calibration, CalibrationContent
from simremap.ecu.compiled import (
    N_INPUTS,
    QUANTITY_INDEX,
    CompiledCalibration,
    CompiledTable,
    CompiledTable1D,
    CompiledTable2D,
)
from simremap.ecu.contracts import AxisQuantity, TableKind
from simremap.ecu.limits import R_AIR_J_KG_K, TABLE_LIMITS
from simremap.ecu.strategies.fuel import speed_density_air_g
from simremap.ecu.tables import Table3D, interp1
from simremap.profiles.contracts import EcuProfileDescriptor, OemProtectionFlags
from simremap.profiles.hooks.common import DescriptorHooks, Problem

if TYPE_CHECKING:
    from simremap.ecu.arbitration import EcuRequests
    from simremap.ecu.runtime import EcuRuntime
    from simremap.physics.contracts import SensorReadings

__all__ = [
    "IDLE_RPM_DEFAULT",
    "INVERSE_LOAD_POINTS",
    "LIMP_TORQUE_FRACTION",
    "MAX_INTERVENTION_DEG",
    "RHO_REF_KG_M3",
    "OemStageHooks",
    "OemTorqueState",
    "efficiency_inverse",
    "missing_torque_tables",
    "oem_checksum",
    "oem_flags",
]

logger = get_logger("simremap.profiles.oem_stage")

RHO_REF_KG_M3: Final = 101.325e3 / (R_AIR_J_KG_K * 273.15)  # 1,2922 kg/m³ (Apêndice C)
INVERSE_LOAD_POINTS: Final = 64
INTERVENTION_MARGIN: Final = 1.02  # T_poss > 1,02 · T_ind_des
MAX_INTERVENTION_DEG: Final = 20.0  # °
MONITOR_RATIO: Final = 1.10  # T_est > 1,10 · torque_limit
MONITOR_CONFIRM_S: Final = 0.5  # s
LIMP_TORQUE_FRACTION: Final = 0.5
THROTTLE_KP: Final = 0.8  # %/kPa
THROTTLE_KI: Final = 4.0  # %/(kPa·s)
THROTTLE_MARGIN_KPA: Final = 5.0  # kPa abaixo do baro ⇒ PI de borboleta
THROTTLE_OVER_MARGIN_KPA: Final = 20.0  # kPa acima do alvo (compressor) ⇒ PI de borboleta
PRESSURE_TABLE_MIN_KPA: Final = TABLE_LIMITS[TableKind.OEM_PRESSURE_TARGET].min  # 80 kPa
PRESSURE_FLOOR_EPS_KPA: Final = 0.5  # kPa: tabela no piso ⇒ inversão pelo speed-density
PRESSURE_MIN_KPA: Final = 10.0  # kPa de pressão alvo mínima (borboleta fechada)
IDLE_RPM_DEFAULT: Final = 850.0  # rev/min (igual ao DEFAULT_IDLE_RPM do dyno-bench)
IDLE_PEDAL_MAX_PCT: Final = 1.0  # % de pedal abaixo do qual vale a marcha lenta
IDLE_KP: Final = 0.10  # N·m/rpm
IDLE_KI: Final = 0.30  # N·m/(rpm·s)
IDLE_TORQUE_MAX_NM: Final = 60.0  # N·m de reserva máxima do PI de marcha lenta
IDLE_FRICTION_BAND_RPM: Final = 400.0  # atrito compensado só até idle_rpm + banda

REQUIRED_TABLES: Final = (
    TableKind.TORQUE_REQUEST,
    TableKind.TORQUE_LIMIT,
    TableKind.TORQUE_OPTIMAL,
    TableKind.IGNITION_OPTIMAL,
    TableKind.IGNITION_BASE,
    TableKind.IGNITION_EFFICIENCY,
    TableKind.OEM_PRESSURE_TARGET,
    TableKind.FRICTION_TORQUE,
    TableKind.VE,
)

_Q = QUANTITY_INDEX
_I_RPM = _Q[AxisQuantity.RPM]
_I_MAP = _Q[AxisQuantity.MAP_KPA]
_I_TPS = _Q[AxisQuantity.TPS_PCT]
_I_PEDAL = _Q[AxisQuantity.PEDAL_PCT]
_I_LOAD = _Q[AxisQuantity.LOAD_PCT]
_I_ECT = _Q[AxisQuantity.ECT_C]
_I_IAT = _Q[AxisQuantity.IAT_C]
_I_BAT = _Q[AxisQuantity.BATTERY_V]
_I_GEAR = _Q[AxisQuantity.GEAR]
_I_EGT = _Q[AxisQuantity.EGT_C]
_I_DELTA = _Q[AxisQuantity.IGN_DELTA_DEG]
_K = TableKind

Limiter = Literal["none", "torque_limit", "gear", "limp", "protection"]
_FLAG_NAMES: Final = tuple(OemProtectionFlags.model_fields)


def oem_checksum(content_hash: str) -> str:
    """``crc32(content_hash + ":oem-stage")`` em 8 dígitos hexadecimais (RF-12)."""
    return format(zlib.crc32(f"{content_hash}:oem-stage".encode()), "08x")


def oem_flags(params: dict[str, float | bool | str]) -> OemProtectionFlags:
    """Flags OEM de ``profile_params`` (ausentes ou não booleanas = ativas)."""
    return OemProtectionFlags(**{name: params.get(name) is not False for name in _FLAG_NAMES})


def efficiency_inverse(xs: list[float], vs: list[float], eta: float) -> float:
    """Δ de ignição com ``ignition_efficiency(Δ) = η`` (tabela não crescente, com clamp)."""
    if eta >= vs[0]:
        return xs[0]
    last = len(vs) - 1
    for i in range(last):
        v0, v1 = vs[i], vs[i + 1]
        if v0 >= eta >= v1:
            if v0 == v1:
                return xs[i]
            return xs[i] + (v0 - eta) / (v0 - v1) * (xs[i + 1] - xs[i])
    return xs[last]


@dataclass(slots=True)
class OemTorqueState:
    """Canais do caminho de torque do tick (ProfileStatus ``oem_*``)."""

    torque_request_nm: float = 0.0
    torque_limit_nm: float = 0.0
    torque_desired_ind_nm: float = 0.0
    limiter: Limiter = "none"
    load_target_pct: float = 0.0
    load_actual_pct: float = 0.0
    pressure_target_kpa: float = 101.325
    ign_base_deg: float = 0.0
    ign_cmd_deg: float = 0.0
    ign_retard_deg: float = 0.0
    torque_estimated_nm: float = 0.0
    air_mg: float = 0.0
    limp: bool = False
    throttle_pct: float = 0.0
    throttle_pi: bool = False
    decel: bool = False  # pedal fechado acima da banda de marcha lenta


@dataclass(slots=True)
class _IgnitionWrapper(CompiledTable2D):
    """``ignition_base`` do OEM: devolve ``ign_cmd`` e passa a carga real ao resto do passo."""

    state: OemTorqueState | None = None

    def at(self, inputs: list[float]) -> float:
        state = self.state
        if state is None:  # pragma: no cover - sempre ligado pelo hook
            return CompiledTable2D.at(self, inputs)
        inputs[_I_LOAD] = state.load_actual_pct
        return state.ign_cmd_deg


@dataclass(slots=True)
class _BoostTargetWrapper(CompiledTable2D):
    """``boost_target`` do OEM: devolve ``oem_pressure_target(rpm, load_target)``."""

    state: OemTorqueState | None = None

    def at(self, inputs: list[float]) -> float:
        state = self.state
        return state.pressure_target_kpa if state is not None else 101.325


@dataclass(slots=True)
class _LambdaWrapper(CompiledTable2D):
    """``lambda_target`` com proteção de componentes: ``min(λ_alvo, λ_cp(EGT))`` (RF-10)."""

    protection: CompiledTable | None = None

    def at(self, inputs: list[float]) -> float:
        lam = CompiledTable2D.at(self, inputs)
        prot = self.protection
        if prot is None:
            return lam
        cap = prot.at(inputs)
        return cap if cap < lam else lam


def missing_torque_tables(tables: dict[TableKind, CompiledTable]) -> list[str]:
    """Tabelas do caminho de torque ausentes ou com dimensão errada."""
    one_d = {_K.TORQUE_LIMIT, _K.IGNITION_EFFICIENCY}
    missing = []
    for kind in REQUIRED_TABLES:
        table = tables.get(kind)
        expected = CompiledTable1D if kind in one_d else CompiledTable2D
        if not isinstance(table, expected):
            missing.append(kind.value)
    return missing


def _require2d(table: CompiledTable | None) -> CompiledTable2D:
    if not isinstance(table, CompiledTable2D):
        raise ValueError("tabela 3D obrigatória do oem-stage ausente")
    return table


def _require1d(table: CompiledTable | None) -> CompiledTable1D:
    if not isinstance(table, CompiledTable1D):
        raise ValueError("tabela 2D obrigatória do oem-stage ausente")
    return table


class OemStageHooks(DescriptorHooks):
    """Hooks do ``oem-stage`` (um objeto por runtime: guarda o estado do laço)."""

    def __init__(
        self,
        descriptor: EcuProfileDescriptor,
        *,
        v_cyl_m3: float | None = None,
        throttle_above_baro: bool = False,
    ) -> None:
        super().__init__(descriptor)
        self.throttle_above_baro = throttle_above_baro
        self.v_cyl_m3 = v_cyl_m3
        self.m_ref_mg = RHO_REF_KG_M3 * v_cyl_m3 * 1e6 if v_cyl_m3 is not None else 0.0
        self.state = OemTorqueState()
        self.flags = OemProtectionFlags()
        self.runtime: EcuRuntime | None = None
        self.pending_events: list[tuple[str, str]] = []
        self.torque_path = True
        self._inputs = [0.0] * N_INPUTS
        self._bound: CompiledCalibration | None = None
        self._monitor_since = inf
        self._throttle_integ = -1.0
        self._throttle_over = False
        self._idle_integ = 0.0
        self._idle_t = -1.0
        self.idle_rpm = IDLE_RPM_DEFAULT
        self._t = 0.0

    # ------------------------------------------------------------------ validação (API)

    def validate_profile(self, cal: CalibrationContent, options: dict[str, bool]) -> list[Problem]:
        problems: list[Problem] = []
        opt = next((t for t in cal.tables.values() if t.kind == _K.TORQUE_OPTIMAL), None)
        if isinstance(opt, Table3D):
            for col in range(len(opt.x.values)):
                column = [row[col] for row in opt.values]
                if any(b <= a for a, b in itertools.pairwise(column)):
                    problems.append(
                        (
                            "OEM_TORQUE_MODEL_NOT_MONOTONIC",
                            f"torque_optimal não é crescente na coluna {col} "
                            f"({opt.x.values[col]:g} rpm): a carga alvo não é invertível.",
                        )
                    )
                    break
        eff = next((t for t in cal.tables.values() if t.kind == _K.IGNITION_EFFICIENCY), None)
        if eff is not None and not isinstance(eff, Table3D):
            vals = eff.values
            if any(b > a for a, b in itertools.pairwise(vals)):
                problems.append(
                    (
                        "OEM_TORQUE_MODEL_NOT_MONOTONIC",
                        "ignition_efficiency deve ser não crescente com o atraso de ignição.",
                    )
                )
        problems.extend(self._check_checksum(cal, options))
        return problems

    def _check_checksum(self, cal: CalibrationContent, options: dict[str, bool]) -> list[Problem]:
        if not isinstance(cal, Calibration):
            return []  # criação/edição: o checksum é verificado só na aplicação à sessão
        if not oem_flags(cal.profile_params).checksum_check:
            return []
        expected = oem_checksum(cal.content_hash)
        stored = cal.metadata.extra.get("oem_checksum", "")
        if stored == expected:
            return []
        if options.get("auto_fix_checksum"):
            logger.info(
                "profiles.oem_checksum_corrected",
                calibration_id=cal.calibration_id,
                version=cal.version,
                stored=stored or None,
                expected=expected,
            )
            return []
        return [
            (
                "OEM_CHECKSUM_INVALID",
                f"Checksum OEM desatualizado: stored={stored or 'ausente'}, expected={expected}. "
                "Corrija metadata.extra.oem_checksum ou aplique com "
                "profile_options.auto_fix_checksum = true.",
            )
        ]

    # ------------------------------------------------------------------ laço

    def attach_runtime(self, runtime: EcuRuntime) -> None:
        """Runtime cujas estratégias as flags OEM podem desligar (knock, overboost)."""
        self.runtime = runtime

    def _bind(self, compiled: CompiledCalibration) -> None:
        tables = compiled.tables
        self.flags = oem_flags(compiled.profile_params)
        idle = compiled.profile_params.get("idle_rpm")
        self.idle_rpm = (
            float(idle)
            if isinstance(idle, int | float) and not isinstance(idle, bool) and idle > 0.0
            else IDLE_RPM_DEFAULT
        )
        missing = missing_torque_tables(tables)
        self.torque_path = not missing
        if missing:
            logger.warning("profiles.oem_torque_path.disabled", missing=missing)
            self._apply_flags(compiled)
            return
        self._tq_req = _require2d(tables.get(_K.TORQUE_REQUEST))
        self._tq_lim = _require1d(tables.get(_K.TORQUE_LIMIT))
        gear = tables.get(_K.TORQUE_LIMIT_GEAR)
        self._tq_gear = gear if isinstance(gear, CompiledTable1D) else None
        self._tq_opt = _require2d(tables.get(_K.TORQUE_OPTIMAL))
        self._ign_opt = _require2d(tables.get(_K.IGNITION_OPTIMAL))
        base = tables.get(_K.IGNITION_BASE)
        if isinstance(base, _IgnitionWrapper):
            base_orig: CompiledTable2D = CompiledTable2D(base.qx, base.qy, base.xs, base.ys, base.z)
        else:
            base_orig = _require2d(base)
        self._ign_base = base_orig
        self._eff = _require1d(tables.get(_K.IGNITION_EFFICIENCY))
        self._p_target = _require2d(tables.get(_K.OEM_PRESSURE_TARGET))
        self._friction = tables.get(_K.FRICTION_TORQUE)
        self._ve = tables.get(_K.VE)
        self._blend = compiled.charge_temp_blend
        self._build_inverse()
        st = self.state
        tables[_K.IGNITION_BASE] = _IgnitionWrapper(
            base_orig.qx, base_orig.qy, base_orig.xs, base_orig.ys, base_orig.z, state=st
        )
        tables[_K.BOOST_TARGET] = _BoostTargetWrapper(
            _I_RPM, _I_TPS, [0.0, 1.0], [0.0, 1.0], [[0.0, 0.0], [0.0, 0.0]], state=st
        )
        lam = tables.get(_K.LAMBDA_TARGET)
        lcp = tables.get(_K.LAMBDA_COMPONENT_PROTECTION)
        if isinstance(lam, CompiledTable2D):
            tables[_K.LAMBDA_TARGET] = _LambdaWrapper(
                lam.qx,
                lam.qy,
                lam.xs,
                lam.ys,
                lam.z,
                protection=lcp if self.flags.component_protection else None,
            )
        self._apply_flags(compiled)

    def _apply_flags(self, compiled: CompiledCalibration) -> None:
        """Flags OEM no runtime anexado e eventos ``oem_protection_disabled`` (1 por aplicação)."""
        self.state.limp = False  # emergência dura até a próxima aplicação de calibração
        self._monitor_since = inf
        runtime = self.runtime
        if runtime is not None:
            if not self.flags.knock_protection:
                runtime.knock.enabled = False
            if not self.flags.overboost_protection:
                runtime.boost.overboost_kpa = inf
        for name in _FLAG_NAMES:
            if not getattr(self.flags, name):
                self.pending_events.append(("oem_protection_disabled", name))
        self._bound = compiled

    def _build_inverse(self) -> None:
        """Tabela inversa: ``f(rpm_i, load_k) = torque_optimal · η_base`` (16 × 64)."""
        opt = self._tq_opt
        ys = opt.ys
        lo, hi = ys[0], ys[-1]
        n = INVERSE_LOAD_POINTS
        loads = [lo + (hi - lo) * k / (n - 1) for k in range(n)]
        inp = [0.0] * N_INPUTS
        grid: list[list[float]] = []
        for rpm in opt.xs:
            inp[_I_RPM] = rpm
            row: list[float] = []
            for load in loads:
                inp[_I_LOAD] = load
                inp[_I_DELTA] = self._ign_opt.at(inp) - self._ign_base.at(inp)
                row.append(opt.at(inp) * self._eff.at(inp))
            grid.append(row)
        self._inv_rpm = list(opt.xs)
        self._inv_loads = loads
        self._inv_f = grid

    def invert_load(self, rpm: float, torque_nm: float) -> tuple[float, bool]:
        """``load_target`` para ``torque_nm`` indicado; ``True`` se saturou na borda (EC-16)."""
        xs = self._inv_rpm
        last = len(xs) - 1
        if not rpm > xs[0]:
            i, fr = 0, 0.0
        elif rpm >= xs[last]:
            i, fr = last - 1, 1.0
        else:
            i = bisect_right(xs, rpm) - 1
            fr = (rpm - xs[i]) / (xs[i + 1] - xs[i])
        r0 = self._inv_f[i]
        r1 = self._inv_f[i + 1]
        loads = self._inv_loads
        n = len(loads) - 1
        f_first = r0[0] + fr * (r1[0] - r0[0])
        if torque_nm <= f_first:
            return loads[0], False
        f_last = r0[n] + fr * (r1[n] - r0[n])
        if torque_nm >= f_last:
            return loads[n], torque_nm > f_last
        lo, hi = 0, n
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if r0[mid] + fr * (r1[mid] - r0[mid]) < torque_nm:
                lo = mid
            else:
                hi = mid
        f_lo = r0[lo] + fr * (r1[lo] - r0[lo])
        f_hi = r0[hi] + fr * (r1[hi] - r0[hi])
        if f_hi <= f_lo:
            return loads[hi], False
        return loads[lo] + (torque_nm - f_lo) / (f_hi - f_lo) * (loads[hi] - loads[lo]), False

    def air_charge_mg(  # noqa: PLR0912, PLR0915 - caminho de torque do Apêndice C (hot path)
        self, sensors: object, compiled: object
    ) -> float | None:
        """Passo 3: caminho de torque e massa de ar pelo modelo de enchimento da ECU (RF-08)."""
        if not isinstance(compiled, CompiledCalibration):
            return None
        if compiled is not self._bound:
            self._bind(compiled)
        if not self.torque_path:
            return None  # sem as tabelas de torque: speed-density do ecu-core
        s: SensorReadings = sensors  # type: ignore[assignment]
        inp = self._inputs
        rpm = s.rpm
        map_kpa = s.map_kpa
        inp[_I_RPM] = rpm
        inp[_I_MAP] = map_kpa
        inp[_I_TPS] = s.tps_pct
        inp[_I_PEDAL] = s.pedal_pct
        inp[_I_GEAR] = float(s.gear)
        inp[_I_ECT] = s.ect_c
        inp[_I_IAT] = s.iat_c
        inp[_I_EGT] = s.egt_collector_c
        inp[_I_BAT] = s.battery_v
        self._t = s.t_sim_s
        st = self.state

        # Massa de ar e carga real (tabela ve de série).
        ve_pct = self._ve.at(inp) if self._ve is not None else 100.0
        v_cyl = self.v_cyl_m3 or 0.0
        air_mg = speed_density_air_g(ve_pct, map_kpa, v_cyl, s.iat_c, s.ect_c, self._blend) * 1e3
        st.air_mg = air_mg
        m_ref = self.m_ref_mg
        load_actual = air_mg / m_ref * 100.0 if m_ref > 0.0 else 0.0
        st.load_actual_pct = load_actual

        # Pedido e limitação de torque.
        t_req = self._tq_req.at(inp)
        idle = s.pedal_pct <= IDLE_PEDAL_MAX_PCT
        if idle:
            t_req = self._idle_torque(rpm, s.t_sim_s)
        else:
            self._idle_integ = 0.0
            self._idle_t = -1.0
        t_tl = self._tq_lim.at(inp)
        t_lim = t_req
        limiter: Limiter = "none"
        if t_tl < t_lim:
            t_lim, limiter = t_tl, "torque_limit"
        if self._tq_gear is not None and s.gear >= 1:
            t_gear = self._tq_gear.at(inp)
            if t_gear < t_lim:
                t_lim, limiter = t_gear, "gear"
        if st.limp:
            t_prot = LIMP_TORQUE_FRACTION * t_tl
            if t_prot < t_lim:
                t_lim, limiter = t_prot, "limp"
        friction = self._friction.at(inp) if self._friction is not None else 0.0
        decel = idle and rpm > self.idle_rpm + IDLE_FRICTION_BAND_RPM
        if decel:
            friction = 0.0  # desaceleração: torque indicado 0 (borboleta fechada, DFCO)
        st.decel = decel
        t_ind = t_lim + friction
        t_ind = max(t_ind, 0.0)
        load_target, saturated = self.invert_load(rpm, t_ind)
        if saturated:
            limiter = "protection"
        st.torque_request_nm = t_req
        st.torque_limit_nm = t_tl
        st.torque_desired_ind_nm = t_ind
        st.limiter = limiter
        st.load_target_pct = load_target
        inp[_I_LOAD] = load_target
        p_target = self._p_target.at(inp)
        if p_target <= PRESSURE_TABLE_MIN_KPA + PRESSURE_FLOOR_EPS_KPA and air_mg > 0.0 < map_kpa:
            # Abaixo do piso da tabela (80 kPa, ecu-core Apêndice A): pressão pela inversão
            # do speed-density na VE de série (ar ∝ MAP no mesmo ponto), para a borboleta
            # fechar em carga parcial, marcha lenta e desaceleração.
            p_sd = load_target / 100.0 * m_ref * map_kpa / air_mg
            p_target = min(p_target, max(p_sd, PRESSURE_MIN_KPA))
        st.pressure_target_kpa = p_target

        # Intervenção rápida por ignição na carga real (RF-09).
        inp[_I_LOAD] = load_actual
        ign_base = self._ign_base.at(inp)
        ign_opt = self._ign_opt.at(inp)
        t_opt = self._tq_opt.at(inp)
        eff = self._eff
        eta_base = interp1(eff.xs, eff.vs, ign_opt - ign_base)
        ign_cmd = ign_base
        if t_opt > 0.0 and t_opt * eta_base > INTERVENTION_MARGIN * t_ind:
            eta_req = t_ind / t_opt
            delta_req = efficiency_inverse(eff.xs, eff.vs, eta_req)
            ign_cmd = min(ign_base, ign_opt - delta_req)
            ign_cmd = max(ign_cmd, ign_base - MAX_INTERVENTION_DEG)
        st.ign_base_deg = ign_base
        st.ign_cmd_deg = ign_cmd
        st.ign_retard_deg = ign_base - ign_cmd

        # Monitorização de torque (RF-11).
        t_est = t_opt * interp1(eff.xs, eff.vs, ign_opt - ign_cmd) - friction
        st.torque_estimated_nm = t_est
        if self.flags.torque_monitoring and not st.limp and t_est > MONITOR_RATIO * t_tl:
            if self._monitor_since == inf:
                self._monitor_since = s.t_sim_s
            if s.t_sim_s - self._monitor_since >= MONITOR_CONFIRM_S - 1e-9:
                st.limp = True
                self.pending_events.append(("oem_limp_mode", f"{t_est:.1f}"))
        else:
            self._monitor_since = inf
        return air_mg

    def _idle_torque(self, rpm: float, t: float) -> float:
        """PI de marcha lenta: reserva de torque ``kp·e + ∫ki·e`` com ``e = idle_rpm − rpm``."""
        dt = t - self._idle_t if self._idle_t >= 0.0 else 0.0
        self._idle_t = t
        err = self.idle_rpm - rpm
        lim = IDLE_TORQUE_MAX_NM
        integ = self._idle_integ + IDLE_KI * err * dt
        integ = -lim if integ < -lim else (lim if integ > lim else integ)
        self._idle_integ = integ
        torque = IDLE_KP * err + integ
        return -lim if torque < -lim else (lim if torque > lim else torque)

    def adjust_requests(self, sensors: object, requests: object) -> None:
        """Modo de emergência: boost cortado no nível failsafe (RF-11)."""
        if self.state.limp:
            reqs: EcuRequests = requests  # type: ignore[assignment]
            reqs.failsafe.active = True
            reqs.failsafe.boost_cut = True

    def throttle(self, map_kpa: float, baro_kpa: float, pedal_pct: float, dt: float) -> float:
        """Borboleta do OEM (RF-07): 100 % com pressão alvo ≥ baro − 5 kPa, senão PI sobre o MAP.

        Complemento inferido para compressor volumétrico (borboleta antes do compressor e
        sem wastegate): com alvo acima do baro e MAP > alvo + 20 kPa a borboleta fecha pelo
        mesmo PI (sem isto o pedido de torque entre a carga do baro e a plena carga vira
        liga-desliga da borboleta). O PI sai desse modo quando volta a pedir 100 %.
        Só com ``throttle_above_baro`` (veículo ``supercharger``): nos turbos a wastegate
        segura o MAP e os picos de boost não podem fechar a borboleta.
        """
        st = self.state
        if st.decel:  # desaceleração: borboleta fechada (o DFCO do ecu-core corta a injeção)
            st.throttle_pi = True
            st.throttle_pct = 0.0
            self._throttle_integ = 0.0
            self._throttle_over = False
            return 0.0
        target = st.pressure_target_kpa
        above = target >= baro_kpa - THROTTLE_MARGIN_KPA
        if (
            above
            and self.throttle_above_baro
            and not self._throttle_over
            and map_kpa > target + THROTTLE_OVER_MARGIN_KPA
        ):
            self._throttle_over = True
            self._throttle_integ = 100.0
        if above and not self._throttle_over:
            st.throttle_pi = False
            st.throttle_pct = 100.0
            self._throttle_integ = 100.0
            return 100.0
        if self._throttle_integ < 0.0:
            self._throttle_integ = pedal_pct
        err = target - map_kpa
        integ = self._throttle_integ + THROTTLE_KI * err * dt
        integ = 0.0 if integ < 0.0 else (100.0 if integ > 100.0 else integ)  # noqa: PLR2004
        self._throttle_integ = integ
        thr = THROTTLE_KP * err + integ
        thr = 0.0 if thr < 0.0 else (100.0 if thr > 100.0 else thr)  # noqa: PLR2004
        if not above:
            self._throttle_over = False
        elif thr >= 100.0:  # noqa: PLR2004
            self._throttle_over = False
        st.throttle_pi = not above
        st.throttle_pct = thr
        return thr

    def drain_events(self) -> list[tuple[str, str]]:
        events = self.pending_events
        if events:
            self.pending_events = []
        return events
