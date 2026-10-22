"""Ponte para os kernels nativos da física (``simremap_rs.cycle``, feature 003 T018).

O Python de ``simremap.physics`` continua a ser a implementação de referência. Quando o
seletor ``simremap.core.native`` devolve a extensão, o ``CycleSolver`` resolve o ciclo
fechado no ``CycleKernel`` e o ``PhysicsEngine`` avança o bloco de gás (VE, borboleta,
compressor/turbina e eixo do turbo, supercharger, intercooler e pressões) no ``GasKernel``,
uma chamada FFI por tick (D-03). A ordem das operações é a mesma do Python; a paridade é
verificada em ``tests/native/test_cycle_parity.py`` (rel 1e-9, Q2).

Fallback transparente: sem a extensão, com ``SIMREMAP_NATIVE=off``, ou se o kernel não
puder ser montado para o veículo (dados fora do que o kernel aceita), fica o Python.
"""

from __future__ import annotations

from types import ModuleType
from typing import TYPE_CHECKING, Any, Final

from simremap.catalog.contracts import Grid1D, Grid2D
from simremap.core.native import native
from simremap.physics.interp import Interp1D, Interp2D

if TYPE_CHECKING:
    from simremap.physics.engine import PhysicsEngine
    from simremap.physics.geometry import CylinderGeometry

__all__ = [
    "GAS_STATE_FIELDS",
    "build_cycle_kernel",
    "build_gas_kernel",
    "build_thermal_kernel",
    "cycle_module",
    "use_native",
]

# Ordem do vetor de estado do ``GasKernel.step`` (atributos de ``EngineVars``).
GAS_STATE_FIELDS: Final = (
    "p_amb_kpa",
    "t_amb_k",
    "fan_m_s",
    "rpm",
    "throttle_pct",
    "vvt_in_deg",
    "vvt_ex_deg",
    "wastegate_x",
    "fuel_rate_kg_s",
    "egt_col_k",
    "p_boost_kpa",
    "p_man_kpa",
    "p_exh_kpa",
    "t_boost_k",
    "t_man_k",
    "turbo_omega",
    "ic_core_k",
    "m_comp_kg_s",
    "m_exh_out_kg_s",
    "surge_s",
    "m_throttle_cum_kg",
)


def cycle_module() -> ModuleType | None:
    """Submódulo ``simremap_rs.cycle`` ou ``None`` (fallback Python)."""
    mod = native()
    if mod is None:
        return None
    cycle = getattr(mod, "cycle", None)
    if not isinstance(cycle, ModuleType) or not hasattr(cycle, "GasKernel"):
        return None
    return cycle


def use_native(requested: bool | None) -> bool:
    """``None`` segue o seletor; ``True`` exige a extensão; ``False`` força o Python."""
    if requested is None:
        return cycle_module() is not None
    if requested and cycle_module() is None:
        raise RuntimeError("kernels nativos pedidos, mas simremap_rs.cycle não está disponível")
    return requested


def build_cycle_kernel(
    geo: CylinderGeometry,
    *,
    woschni_k: float,
    wiebe_a: float,
    wiebe_m: float,
    duration_ref_deg: float,
    rpm_ref: float,
) -> Any:
    cycle = cycle_module()
    if cycle is None:
        raise RuntimeError("simremap_rs.cycle indisponível")
    return cycle.CycleKernel(
        geo.volume_m3,
        geo.dvol_m3_per_deg,
        geo.wall_area_m2,
        geo.stroke_m,
        geo.vd_cyl_m3,
        woschni_k,
        wiebe_a,
        wiebe_m,
        duration_ref_deg,
        rpm_ref,
    )


def _i1(table: Interp1D) -> dict[str, Any]:
    return {"x": list(table.x), "y": list(table.y)}


def _i2(table: Interp2D | None) -> dict[str, Any] | None:
    if table is None:
        return None
    return {"x": list(table.x), "y": list(table.y), "z": [list(r) for r in table.z]}


def _g2(grid: Grid2D | None) -> dict[str, Any] | None:
    return None if grid is None else _i2(Interp2D.from_grid(grid))


def _g1(grid: Grid1D) -> dict[str, Any]:
    return _i1(Interp1D.from_grid(grid))


def gas_config(engine: PhysicsEngine) -> dict[str, Any]:
    """Configuração plana do ``GasKernel`` a partir dos modelos Python do motor."""
    ve = engine.ve_model
    overlap = ve.overlap
    ve_cfg: dict[str, Any] = {
        "map": _i2(ve._map),
        "rc": ve._rc,
        "k_vvt": ve._k_vvt,
        "g_vvt": _i2(ve._g_vvt),
        "overlap": (
            None
            if overlap is None
            else {
                "base_deg": overlap.base_deg,
                "ref_rpm": list(overlap._ref_rpm),
                "ref_overlap": list(overlap._ref_overlap),
            }
        ),
    }
    turbo_spec = engine.vehicle.turbo
    turbo: dict[str, Any] | None = None
    if turbo_spec is not None and engine.turbine is not None and engine.compressor is not None:
        c = engine.compressor.spec
        turbo = {
            "compressor": {
                "m_choke_max_kg_s": c.m_choke_max_kg_s,
                "n_max_rpm": c.n_max_rpm,
                "n_design_rpm": c.n_design_rpm,
                "pr_design": c.pr_design,
                "eta_max": c.eta_max,
                "k1": c.k1,
                "k2": c.k2,
                "m_peak_kg_s": c.m_peak_kg_s,
                "m_range_kg_s": c.m_range_kg_s,
                "n_peak_rpm": c.n_peak_rpm,
                "table": _g2(c.table),
            },
            "area_m2": engine.turbine.area_m2,
            "wg_area_max_m2": engine.turbine.wg_area_max_m2,
            "eta": _g1(turbo_spec.turbine_efficiency),
            "blow_off_valve": bool(turbo_spec.blow_off_valve),
            "inertia": turbo_spec.rotor_inertia_kg_m2,
            "friction_k": turbo_spec.bearing_friction_k,
            "comp_passive_area": engine.comp_passive_area,
        }
    sc: dict[str, Any] | None = None
    if engine.sc is not None:
        s = engine.sc.spec
        sc = {
            "disp_m3": engine.sc.disp_m3,
            "pulley_ratio": s.pulley_ratio,
            "k_leak": s.k_leak,
            "n_ref_rpm": s.n_ref_rpm,
            "mech_efficiency": s.mech_efficiency,
            "eta_ad": _g1(s.adiabatic_efficiency),
            "bypass_valve": bool(s.bypass_valve),
        }
    ic = engine.intercooler
    res = engine.resolved
    return {
        "induction": engine.induction,
        "pre_compressor": engine.pre_compressor,
        "has_boost_volume": engine.has_boost_volume,
        "v_boost": engine.v_boost,
        "v_man": engine.v_man,
        "v_exh": engine.v_exh,
        "throttle_d": engine.throttle_d,
        "vd_total_m3": engine.geo.vd_total_m3,
        "exh_backpressure_kpa": engine.exh_backpressure_kpa,
        "exh_ref_flow": engine.exh_ref_flow,
        "na_exhaust_area": engine.na_exhaust_area,
        "n_substeps": res.n_substeps,
        "h": res.h,
        "ve": ve_cfg,
        "turbo": turbo,
        "sc": sc,
        "ic_present": ic.spec is not None,
        "ic_effectiveness": ic.effectiveness,
        "ic_k_dp": ic.k_dp,
    }


def build_gas_kernel(engine: PhysicsEngine) -> Any:
    cycle = cycle_module()
    if cycle is None:
        raise RuntimeError("simremap_rs.cycle indisponível")
    return cycle.GasKernel(gas_config(engine))


def build_thermal_kernel(engine: PhysicsEngine) -> Any:
    cycle = cycle_module()
    if cycle is None:
        raise RuntimeError("simremap_rs.cycle indisponível")
    return cycle.ThermalKernel(
        engine.n_cyl,
        engine.exh_ua_w_k,
        engine.egt_backpressure_factor,
        engine.config.egt_thermocouple_tau_s,
    )
