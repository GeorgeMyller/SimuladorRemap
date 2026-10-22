"""Paridade Python × Rust das tabelas e estratégias da ECU (feature 003, T004).

- ``interp1``/``interp2`` e ``TableSet.eval`` contra ``simremap.ecu.tables`` (hypothesis);
- ``BoostPid``, ``VvtRate``, ``OverrunFsm``, ``TwoStepFsm`` e ``flex_factors`` contra as
  estratégias Python em sequências aleatórias com seed;
- ``EcuRuntime`` com a vista nativa (``native_tables``) contra o caminho Python, inclusive
  com um wrapper de ``ignition_base`` que reescreve ``load_pct`` (grupo separado).

Tolerância relativa 1e-9 por grandeza (questions.md Q2). Sem a extensão: ``skip``.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from simremap.core.native import native
from simremap.ecu.arbitration import StrategyRequest
from simremap.ecu.calibration import parse_content
from simremap.ecu.compiled import (
    QUANTITY_INDEX,
    CompiledTable1D,
    CompiledTable2D,
    EcuHardwareConfig,
    compile_calibration,
)
from simremap.ecu.contracts import (
    AxisQuantity,
    BoostControlConfig,
    OverrunConfig,
    TableKind,
    TwoStepConfig,
    VvtConfig,
)
from simremap.ecu.limits import (
    FLEX_AFR_E27,
    FLEX_AFR_E100,
    FLEX_DENSITY_E27_G_CC,
    FLEX_DENSITY_E100_G_CC,
    PER_CYLINDER_KINDS,
    TABLE_LIMITS,
    default_failsafe_rules,
)
from simremap.ecu.native_tables import NativeTablePlan
from simremap.ecu.runtime import EcuRuntime
from simremap.ecu.strategies import BoostControl, Overrun, TickContext, TwoStep
from simremap.ecu.strategies.vvt import VvtControl
from simremap.ecu.tables import interp1, interp2
from simremap.physics.contracts import SensorReadings
from simremap.physics.fuel_blend import blend_afr_stoich, blend_density

_MOD = native()
if _MOD is None:
    pytest.skip(
        "extensão simremap_rs ausente (SIMREMAP_NATIVE=off ou não compilada)",
        allow_module_level=True,
    )
NT: Any = _MOD.tables
REL = 1e-9
N_CYL = 6
DT = 0.001


def close(a: float, b: float) -> bool:
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    return a == b or math.isclose(a, b, rel_tol=REL, abs_tol=0.0)


def assert_close(a: Any, b: Any, path: str = "") -> None:
    """Igualdade estrutural com tolerância relativa nos ``float``."""
    if isinstance(a, float) or isinstance(b, float):
        assert isinstance(a, int | float) and isinstance(b, int | float), path
        assert close(float(a), float(b)), f"{path}: {a!r} != {b!r}"
    elif isinstance(a, dict):
        assert isinstance(b, dict) and a.keys() == b.keys(), path
        for k in a:
            assert_close(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list | tuple):
        assert isinstance(b, list | tuple) and len(a) == len(b), path
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            assert_close(x, y, f"{path}[{i}]")
    else:
        assert a == b, f"{path}: {a!r} != {b!r}"


# --------------------------------------------------------------------------- interpolação

_finite = st.floats(min_value=-1e4, max_value=1e4, allow_nan=False, allow_infinity=False)
_probe = st.one_of(_finite, st.just(math.nan), st.just(math.inf), st.just(-math.inf), st.just(0.0))


@st.composite
def axis(draw: st.DrawFn, min_size: int = 2) -> list[float]:
    raw = draw(st.lists(_finite, min_size=min_size, max_size=32, unique=True))
    return sorted(raw)


@settings(max_examples=300, deadline=None)
@given(xs=axis(), data=st.data(), x=_probe)
def test_interp1_parity(xs: list[float], data: st.DataObject, x: float) -> None:
    vs = data.draw(st.lists(_finite, min_size=len(xs), max_size=len(xs)))
    probes = [x, *xs, xs[0] - 1.0, xs[-1] + 1.0, (xs[0] + xs[-1]) / 2.0]
    for p in probes:
        assert close(NT.interp1(xs, vs, p), interp1(xs, vs, p))


@settings(max_examples=300, deadline=None)
@given(xs=axis(), ys=axis(), data=st.data(), x=_probe, y=_probe)
def test_interp2_parity(
    xs: list[float], ys: list[float], data: st.DataObject, x: float, y: float
) -> None:
    row = st.lists(_finite, min_size=len(xs), max_size=len(xs))
    z = data.draw(st.lists(row, min_size=len(ys), max_size=len(ys)))
    for px, py in [(x, y), (xs[0], ys[-1]), (xs[-1], ys[0]), (x, ys[1]), (xs[1], y)]:
        assert close(NT.interp2(xs, ys, z, px, py), interp2(xs, ys, z, px, py))


def _rand_axis(rng: random.Random, lo: float, hi: float) -> list[float]:
    n = rng.randint(2, 20)
    return sorted({rng.uniform(lo, hi) for _ in range(n)} | {lo, hi})


def test_table_set_matches_compiled_tables() -> None:
    rng = random.Random(3)
    n_inputs = len(QUANTITY_INDEX)
    tables: list[CompiledTable1D | CompiledTable2D] = []
    for _ in range(200):
        qx = rng.randrange(n_inputs)
        xs = _rand_axis(rng, -50.0, 500.0)
        if rng.random() < 0.5:
            tables.append(CompiledTable1D(qx, xs, [rng.uniform(-100, 100) for _ in xs]))
        else:
            ys = _rand_axis(rng, -50.0, 500.0)
            z = [[rng.uniform(-100, 100) for _ in xs] for _ in ys]
            tables.append(CompiledTable2D(qx, rng.randrange(n_inputs), xs, ys, z))
    specs = [
        (t.qx, t.qy, t.xs, t.ys, t.z)
        if isinstance(t, CompiledTable2D)
        else (t.qx, -1, t.xs, [], [t.vs])
        for t in tables
    ]
    kernel = NT.TableSet(specs)
    assert len(kernel) == len(tables)
    for _ in range(500):
        inputs = [rng.uniform(-100.0, 600.0) for _ in range(n_inputs)]
        if rng.random() < 0.1:
            inputs[rng.randrange(n_inputs)] = math.nan
        got = kernel.eval(inputs)
        for value, table in zip(got, tables, strict=True):
            assert close(value, table.at(inputs))


def test_table_set_rejects_bad_shapes() -> None:
    with pytest.raises(ValueError):
        NT.TableSet([(0, 1, [0.0, 1.0], [0.0, 1.0], [[1.0, 2.0]])])
    with pytest.raises(ValueError):
        NT.TableSet([(0, -1, [0.0, 1.0], [], [[1.0]])])
    with pytest.raises(IndexError):
        NT.TableSet([(5, -1, [0.0, 1.0], [], [[1.0, 2.0]])]).eval([0.0, 0.0])


# --------------------------------------------------------------------------- estratégias


def _ctx(t: float) -> TickContext:
    ctx = TickContext(N_CYL)
    ctx.t = t
    ctx.dt = DT
    return ctx


def test_boost_pid_parity() -> None:
    rng = random.Random(11)
    for mode in ("closed_loop", "open_loop"):
        cfg = BoostControlConfig(
            mode=mode, kp_pct_per_kpa=0.7, ki_pct_per_kpa_s=3.0, kd_pct_s_per_kpa=0.05
        )
        cal = compile_calibration(_content(rng, {}), N_CYL)
        py = BoostControl(cfg, cal)
        rs = NT.BoostPid(
            cfg.enabled,
            cfg.mode == "closed_loop",
            cfg.kp_pct_per_kpa,
            cfg.ki_pct_per_kpa_s,
            cfg.kd_pct_s_per_kpa,
            cfg.d_filter_tau_s,
            cfg.pid_activation_window_kpa,
            cfg.integrator_limit_pct,
        )
        ctx = _ctx(0.0)
        for i in range(5000):
            ctx.t = i * DT
            ctx.map_kpa = 100.0 + 150.0 * rng.random()
            ctx.inputs[QUANTITY_INDEX[AxisQuantity.RPM]] = rng.uniform(1000.0, 8000.0)
            target = rng.uniform(80.0, 300.0)
            cut = rng.random() < 0.05
            duty_py = py.compute_duty(ctx, target, cut)
            base = cal.tables[TableKind.BOOST_DUTY_BASE].at(ctx.inputs)
            duty_rs = rs.step(ctx.map_kpa, target, DT, base, cut)
            assert close(duty_rs, duty_py)
            assert rs.pid_active == py.pid_active
            assert close(rs.integ, py.integ) and close(rs.map_filt, py.map_filt)


def test_vvt_rate_parity() -> None:
    rng = random.Random(5)
    for cfg in (
        VvtConfig(enabled=False),
        VvtConfig(min_ect_c=50.0, max_rate_deg_s=300.0, intake_offset_deg=3.0),
    ):
        py = VvtControl(cfg)
        rs = NT.VvtRate(
            cfg.enabled,
            cfg.min_ect_c,
            cfg.intake_offset_deg,
            cfg.exhaust_offset_deg,
            cfg.max_rate_deg_s,
        )
        ctx = _ctx(0.0)
        for _ in range(3000):
            ctx.ect_c = rng.uniform(0.0, 110.0)
            a, b = rng.uniform(-40.0, 40.0), rng.uniform(-40.0, 40.0)
            assert_close(rs.targets(ctx.ect_c, DT, a, b), py.targets(ctx, a, b))


def _req_state(req: StrategyRequest) -> tuple[Any, ...]:
    return (
        req.active,
        req.ign_override,
        req.lambda_target,
        req.ign_retard,
        list(req.fuel_cut),
        list(req.spark_cut),
    )


def test_overrun_fsm_parity() -> None:
    rng = random.Random(7)
    configs = [
        OverrunConfig(pops_enabled=True, catalyst_present=False, intensity_pct=50.0),
        OverrunConfig(pops_enabled=True, catalyst_present=True),
        OverrunConfig(pops_enabled=False, dfco_delay_s=0.05),
        OverrunConfig(enabled=False),
    ]
    for cfg in configs:
        py = Overrun(cfg)
        rs = NT.OverrunFsm(
            cfg.enabled,
            cfg.dfco_enabled,
            cfg.dfco_tps_max_pct,
            cfg.dfco_rpm_min,
            cfg.dfco_resume_rpm,
            cfg.dfco_delay_s,
            cfg.pops_enabled,
            cfg.pops_rpm_min,
            cfg.pops_rpm_max,
            cfg.pops_tps_max_pct,
            cfg.fuel_cut_delay_s,
            cfg.intensity_pct,
            cfg.max_duration_s,
            cfg.egt_turbine_max_c,
            cfg.catalyst_present,
            cfg.catalyst_max_intensity_pct,
            cfg.catalyst_max_duration_s,
            N_CYL,
        )
        assert close(rs.window_s, py.window_s)
        ctx = _ctx(0.0)
        req_py, req_rs = StrategyRequest("overrun", N_CYL), StrategyRequest("overrun", N_CYL)
        tps = 0.0
        for i in range(8000):
            ctx.t = i * DT
            if i % 400 == 0:
                tps = rng.choice([0.0, 1.0, 3.0, 30.0])
            ctx.tps_pct = tps
            ctx.rpm = rng.uniform(800.0, 7000.0)
            ctx.egt_c = rng.uniform(700.0, 1000.0)
            ctx.cycle_counter = i // 20
            req_py.reset()
            req_rs.reset()
            ctx.events = []
            py.update(ctx, req_py)
            state, protect, n_cut = rs.update(ctx.t, ctx.rpm, ctx.tps_pct, ctx.egt_c)
            if state == 2:
                req_rs.cut_all("fuel_cut")
            elif state == 1:
                req_rs.active = True
                req_rs.ign_override = cfg.ign_advance_deg
                req_rs.lambda_target = cfg.lambda_target
                req_rs.cut_pattern("fuel_cut", n_cut, ctx.cycle_counter)
            assert rs.state == py.state
            assert protect == bool(ctx.events)
            assert rs.protected == py.protected
            assert_close(_req_state(req_rs), _req_state(req_py))


def test_two_step_fsm_parity() -> None:
    rng = random.Random(13)
    configs = [
        TwoStepConfig(cut_mode="spark_cut", max_active_s=0.5),
        TwoStepConfig(cut_mode="rolling_cut", activation="launch_switch"),
        TwoStepConfig(cut_mode="fuel_cut", release_ramp_s=0.0),
        TwoStepConfig(enabled=False),
    ]
    for cfg in configs:
        py = TwoStep(cfg)
        rs = NT.TwoStepFsm(
            cfg.enabled,
            cfg.target_rpm,
            cfg.cut_mode == "rolling_cut",
            cfg.ign_advance_deg,
            cfg.activation == "clutch",
            cfg.max_speed_kmh,
            cfg.min_tps_pct,
            cfg.max_active_s,
            cfg.release_ramp_s,
        )
        kind = "fuel_cut" if cfg.cut_mode == "fuel_cut" else "spark_cut"
        ctx = _ctx(0.0)
        req_py, req_rs = StrategyRequest("two_step", N_CYL), StrategyRequest("two_step", N_CYL)
        pressed = False
        for i in range(8000):
            ctx.t = i * DT
            if i % 300 == 0:
                pressed = rng.random() < 0.6
            ctx.clutch_pressed = ctx.launch_switch = pressed
            ctx.tps_pct = rng.choice([50.0, 90.0, 100.0])
            ctx.vehicle_speed_kmh = rng.choice([0.0, 2.0, 30.0]) if i % 97 == 0 else 0.0
            ctx.rpm = rng.uniform(3500.0, 4500.0)
            ctx.adv_ref = rng.uniform(-5.0, 35.0)
            ctx.cycle_counter = i // 15
            req_py.reset()
            req_rs.reset()
            ctx.events = []
            py.update(ctx, req_py)
            active, n_cut, retard, timeout = rs.update(
                ctx.t,
                ctx.rpm,
                ctx.tps_pct,
                ctx.vehicle_speed_kmh,
                ctx.clutch_pressed,
                ctx.launch_switch,
                ctx.adv_ref,
                N_CYL,
            )
            if active:
                req_rs.active = True
                req_rs.ign_override = cfg.ign_advance_deg
                req_rs.lambda_target = cfg.lambda_target
                if cfg.cut_mode == "rolling_cut":
                    req_rs.cut_pattern("spark_cut", n_cut, ctx.cycle_counter)
                elif n_cut:
                    req_rs.cut_all(kind)
            elif not math.isnan(retard):
                req_rs.active = True
                req_rs.ign_retard = retard
            assert active == py.active and rs.locked_out == py.locked_out
            assert (not math.isnan(timeout)) == bool(ctx.events)
            if ctx.events:
                assert close(timeout, ctx.events[0].value or 0.0)
            assert_close(_req_state(req_rs), _req_state(req_py))


@settings(max_examples=200, deadline=None)
@given(
    ethanol=st.floats(min_value=-10.0, max_value=150.0, allow_nan=False),
    afr=st.floats(min_value=8.0, max_value=16.0),
    rho=st.floats(min_value=0.6, max_value=0.9),
)
def test_flex_factors_parity(ethanol: float, afr: float, rho: float) -> None:
    mass = afr / blend_afr_stoich(ethanol, FLEX_AFR_E27, FLEX_AFR_E100)
    opening = mass * rho / blend_density(ethanol, FLEX_DENSITY_E27_G_CC, FLEX_DENSITY_E100_G_CC)
    got = NT.flex_factors(
        ethanol,
        afr,
        rho,
        FLEX_AFR_E27,
        FLEX_AFR_E100,
        FLEX_DENSITY_E27_G_CC,
        FLEX_DENSITY_E100_G_CC,
    )
    assert_close(got, (mass, opening))


def test_flex_factors_nan_raises_like_python() -> None:
    with pytest.raises(ValueError):
        blend_afr_stoich(math.nan, FLEX_AFR_E27, FLEX_AFR_E100)
    with pytest.raises(ValueError):
        NT.flex_factors(
            math.nan,
            13.2,
            0.745,
            FLEX_AFR_E27,
            FLEX_AFR_E100,
            FLEX_DENSITY_E27_G_CC,
            FLEX_DENSITY_E100_G_CC,
        )


# --------------------------------------------------------------------------- runtime

# Eixos fora do padrão do Apêndice A para exercitar as janelas de ``inputs``: grandezas
# reescritas no meio do tick (``load_pct`` pelo wrapper, ``boost_target_kpa``).
_AXIS_OVERRIDE: dict[TableKind, tuple[AxisQuantity, AxisQuantity | None]] = {
    TableKind.VE: (AxisQuantity.RPM, AxisQuantity.BOOST_TARGET_KPA),
    TableKind.IGN_CORR_IAT: (AxisQuantity.LOAD_PCT, None),
    TableKind.BOOST_TARGET: (AxisQuantity.RPM, AxisQuantity.LOAD_PCT),
    TableKind.CAM_INTAKE_TARGET: (AxisQuantity.RPM, AxisQuantity.BOOST_TARGET_KPA),
    TableKind.CAM_EXHAUST_TARGET: (AxisQuantity.LOAD_PCT, AxisQuantity.MAP_KPA),
}
_AXIS_RANGE: dict[AxisQuantity, tuple[float, float]] = {
    AxisQuantity.RPM: (500.0, 8000.0),
    AxisQuantity.MAP_KPA: (20.0, 300.0),
    AxisQuantity.LOAD_PCT: (0.0, 250.0),
    AxisQuantity.BOOST_TARGET_KPA: (80.0, 300.0),
    AxisQuantity.TPS_PCT: (0.0, 100.0),
    AxisQuantity.ECT_C: (-20.0, 120.0),
    AxisQuantity.IAT_C: (-20.0, 80.0),
    AxisQuantity.BATTERY_V: (8.0, 16.0),
    AxisQuantity.GEAR: (1.0, 6.0),
    AxisQuantity.TPS_RATE_PCT_S: (0.0, 1000.0),
    AxisQuantity.ETHANOL_PCT: (27.0, 100.0),
}
_SKIP_KINDS = {
    TableKind.INJ_BASE_MS,  # modo direct_pulse_ms (não usado aqui)
    TableKind.TORQUE_REQUEST,
    TableKind.TORQUE_LIMIT,
    TableKind.TORQUE_LIMIT_GEAR,
    TableKind.TORQUE_OPTIMAL,
    TableKind.IGNITION_OPTIMAL,
    TableKind.IGNITION_EFFICIENCY,
    TableKind.OEM_PRESSURE_TARGET,
    TableKind.FRICTION_TORQUE,
    TableKind.LAMBDA_COMPONENT_PROTECTION,
}


def _axis_dict(rng: random.Random, q: AxisQuantity) -> dict[str, Any]:
    lo, hi = _AXIS_RANGE[q]
    n = rng.randint(2, 12)
    values = sorted({round(rng.uniform(lo, hi), 3) for _ in range(n)} | {lo, hi})
    return {"quantity": q.value, "values": values}


def _table(
    rng: random.Random, kind: TableKind, table_id: str, cylinder: int | None = None
) -> dict[str, Any]:
    lim = TABLE_LIMITS[kind]
    xq, yq = _AXIS_OVERRIDE.get(kind, (lim.x, lim.y))
    lo, hi = lim.min, lim.max
    if kind in PER_CYLINDER_KINDS:
        lo, hi = lo / 3.0, hi / 3.0
    data: dict[str, Any] = {
        "table_id": table_id,
        "kind": kind.value,
        "unit": lim.unit,
        "x": _axis_dict(rng, xq),
    }
    nx = len(data["x"]["values"])
    if yq is None:
        data["values"] = [rng.uniform(lo, hi) for _ in range(nx)]
    else:
        data["y"] = _axis_dict(rng, yq)
        ny = len(data["y"]["values"])
        data["values"] = [[rng.uniform(lo, hi) for _ in range(nx)] for _ in range(ny)]
    if cylinder is not None:
        data["cylinder"] = cylinder
    return data


def _content(rng: random.Random, strategies: dict[str, Any]) -> Any:
    tables: dict[str, Any] = {}
    for kind in TABLE_LIMITS:
        if kind in _SKIP_KINDS:
            continue
        if kind in PER_CYLINDER_KINDS:
            for c in range(1, N_CYL + 1):
                if rng.random() < 0.7:
                    tid = f"{kind.value[:8]}_{c}"
                    tables[tid] = _table(rng, kind, tid, cylinder=c)
            continue
        tables[kind.value] = _table(rng, kind, kind.value)
    return parse_content(
        {
            "vehicle_id": "hatch-20t-gdi",
            "profile_id": "ft-pro",
            "tables": tables,
            "strategies": strategies,
        }
    )


def _strategies() -> dict[str, Any]:
    out: dict[str, Any] = {
        k: {"kind": k}
        for k in (
            "closed_loop",
            "knock_control",
            "boost_control",
            "rev_limiter",
            "two_step",
            "antilag",
            "powershift",
        )
    }
    out["boost_control"]["by_gear_enabled"] = True
    out["overrun"] = {"kind": "overrun", "pops_enabled": True}
    out["vvt"] = {"kind": "vvt"}
    out["failsafe"] = {
        "kind": "failsafe",
        "rules": [r.model_dump() for r in default_failsafe_rules(950.0)],
    }
    return out


def _hardware() -> EcuHardwareConfig:
    return EcuHardwareConfig(
        n_cyl=N_CYL,
        displacement_cc=500.0 * N_CYL,
        injector_flow_cc_min=550.0,
        afr_stoich=13.2,
        fuel_density_g_cc=0.745,
    )


def _readings(rng: random.Random, n: int) -> list[SensorReadings]:
    out = []
    rpm = 900.0
    for i in range(n):
        rpm = min(max(rpm + rng.uniform(-60.0, 80.0), 0.0), 8000.0)
        out.append(
            SensorReadings(
                t_sim_s=i * DT,
                tick=i,
                rpm=rpm if i > 5 else 150.0,
                crank_angle_deg=0.0,
                cam_intake_deg=0.0,
                cam_exhaust_deg=0.0,
                map_kpa=rng.uniform(25.0, 280.0),
                baro_kpa=100.0,
                boost_pre_throttle_kpa=100.0,
                iat_c=rng.uniform(10.0, 60.0),
                ect_c=rng.uniform(20.0, 105.0),
                oil_temp_c=90.0,
                tps_pct=rng.choice([0.0, 1.0, 40.0, 100.0])
                if i % 50 == 0
                else rng.uniform(0.0, 100.0),
                pedal_pct=rng.uniform(0.0, 100.0),
                lambda_measured=rng.uniform(0.7, 1.2),
                egt_collector_c=rng.uniform(600.0, 1000.0),
                fuel_pressure_kpa=rng.uniform(250.0, 400.0),
                battery_v=rng.uniform(11.0, 15.0),
                gear=rng.randint(0, 6),
                oil_pressure_kpa=rng.uniform(50.0, 500.0),
                egt_c=[700.0] * N_CYL,
                knock_sensor_v=[0.05] * N_CYL,
                knock_intensity=[rng.random() * 0.6 for _ in range(N_CYL)],
                clutch_pressed=(i // 200) % 3 == 0,
                shift_request=i % 333 < 3,
                antilag_switch=(i // 150) % 4 == 0,
                ethanol_pct=None if (i // 500) % 2 == 0 else rng.uniform(27.0, 100.0),
            )
        )
    return out


@dataclass(slots=True)
class _LoadRewriter(CompiledTable2D):
    """Wrapper de perfil (como o ``_IgnitionWrapper`` do OEM): reescreve ``load_pct``."""

    def at(self, inputs: list[float]) -> float:
        value = CompiledTable2D.at(self, inputs)
        inputs[QUANTITY_INDEX[AxisQuantity.LOAD_PCT]] = value * 3.0 + 40.0
        return value


def _pair(seed: int, wrap_ignition: bool) -> tuple[EcuRuntime, EcuRuntime]:
    rng = random.Random(seed)
    content = _content(rng, _strategies())
    runtimes = []
    for _ in range(2):
        compiled = compile_calibration(content, N_CYL, calibration_id="parity")
        if wrap_ignition:
            base = compiled.tables[TableKind.IGNITION_BASE]
            assert isinstance(base, CompiledTable2D)
            compiled.tables[TableKind.IGNITION_BASE] = _LoadRewriter(
                base.qx, base.qy, base.xs, base.ys, base.z
            )
        runtimes.append(EcuRuntime(compiled, None, _hardware()))
    py, rs = runtimes
    py._native_tables = None  # caminho Python de referência no mesmo processo
    assert rs._native_tables is not None
    return py, rs


@pytest.mark.parametrize(("seed", "wrap"), [(1, False), (2, False), (3, True), (4, True)])
def test_runtime_native_view_parity(seed: int, wrap: bool) -> None:
    py, rs = _pair(seed, wrap)
    for s in _readings(random.Random(seed + 100), 3000):
        a = py.step(s, DT)
        b = rs.step(s, DT)
        assert_close(b.commands.model_dump(), a.commands.model_dump(), f"commands@{s.tick}")
        assert_close(b.status.model_dump(), a.status.model_dump(), f"status@{s.tick}")
        assert_close(
            [e.model_dump() for e in b.events],
            [e.model_dump() for e in a.events],
            f"events@{s.tick}",
        )
    plan = rs._plan
    assert plan is not None
    assert len(plan.groups) == (3 if wrap else 2)


def test_runtime_swap_rebuilds_native_view() -> None:
    py, rs = _pair(9, False)
    readings = _readings(random.Random(19), 600)
    other = compile_calibration(
        _content(random.Random(29), _strategies()), N_CYL, calibration_id="b"
    )
    for s in readings:
        if s.tick == 300:
            py.swap_calibration(other, "full")
            rs.swap_calibration(other, "full")
        a, b = py.step(s, DT), rs.step(s, DT)
        assert_close(b.status.model_dump(), a.status.model_dump(), f"status@{s.tick}")
    assert rs._plan is not None and rs._plan.source is other
    assert rs.fuel.tables is rs._plan.view and other.tables is not rs._plan.view.tables


def test_plan_leaves_real_calibration_untouched() -> None:
    compiled = compile_calibration(_content(random.Random(41), {}), N_CYL)
    before = dict(compiled.tables)
    plan = NativeTablePlan(compiled, NT)
    assert compiled.tables == before
    assert all(type(t) in (CompiledTable1D, CompiledTable2D) for t in compiled.tables.values())
    assert plan.view.content_hash == compiled.content_hash
    assert plan.view.tables.keys() == compiled.tables.keys()
