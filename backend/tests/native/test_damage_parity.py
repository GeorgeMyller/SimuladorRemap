"""Paridade Python × Rust do dano (feature 003, T006; D-04, Q2: tolerância relativa 1e-9).

- ``knock_onset``: Douaud-Eyzat + Livengood-Wu em traços aleatórios com seed;
- ``traces_finite``: validação EC-02 com NaN/inf;
- ``DamageKernel`` via ``DamageModel``: estados aleatórios com seed que exercitam fluência
  de pistão/válvulas/turbina, lambda pobre, temperatura de knock, bronzinas, sobrevelocidade
  e burst do turbo, knock por ciclo e pré-ignição (sorteios no Python, mesma sequência);
  compara por tick saúde, causas, temperaturas e falhas, e também ``load_snapshot`` e
  ``restore`` (o kernel volta a ligar-se aos arrays).

Sem a extensão (``SIMREMAP_NATIVE=off`` ou ``simremap_rs`` ausente) o módulo é ignorado.
"""

from __future__ import annotations

import math
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from simremap.damage import knock, native_bridge
from simremap.damage.config import DamageConfig
from simremap.damage.model import DamageModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "damage"))

from kfm_helpers import (
    SPEC_CONFIG,
    build_e27,
    build_hatch,
    build_v8,
    make_ecu,
    make_event,
    make_state,
)

RTOL = 1e-9
KERNELS = native_bridge.KERNELS

pytestmark = pytest.mark.skipif(KERNELS is None, reason="extensão nativa do dano inativa")


@contextmanager
def python_reference() -> Iterator[None]:
    """Força a referência Python (``native_bridge.KERNELS = None``) no bloco."""
    saved = native_bridge.KERNELS
    native_bridge.KERNELS = None
    try:
        yield
    finally:
        native_bridge.KERNELS = saved


def close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is b
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    return a == b or abs(a - b) <= RTOL * max(abs(a), abs(b))


def assert_arrays(name: str, a: Any, b: Any) -> None:
    x = np.asarray(a, dtype=np.float64)
    y = np.asarray(b, dtype=np.float64)
    assert x.shape == y.shape, name
    np.testing.assert_allclose(x, y, rtol=RTOL, atol=0.0, equal_nan=True, err_msg=name)


# ------------------------------------------------------------------ kernels isolados


def _random_trace(rng: np.random.Generator, n: int) -> tuple[list[float], list[float]]:
    p = rng.uniform(80.0, 16_000.0, n)
    t = rng.uniform(450.0, 1300.0, n)
    p[rng.random(n) < 0.05] = 1.0  # abaixo de tau_min_pressure_kpa (EC-03)
    t[rng.random(n) < 0.05] = 300.0  # abaixo de tau_min_temp_k
    return p.tolist(), t.tolist()


@pytest.mark.parametrize("multiplier", [1.0, 4.25])
def test_knock_onset_parity(multiplier: float) -> None:
    config = DamageConfig(knock_tau_multiplier=multiplier)
    rng = np.random.default_rng(20261019)
    knocked = 0
    for _ in range(400):
        n = int(rng.integers(1, 120))
        pressure, t_u = _random_trace(rng, n)
        rpm = float(rng.uniform(1.0, 9000.0))
        octane = float(rng.uniform(80.0, 105.0))
        event = make_event(1, 0.0, rpm)
        event = event.model_copy(
            update={
                "pressure_kpa": pressure,
                "t_unburned_k": t_u,
                "burned_fraction": np.linspace(0.0, 1.0, n).tolist(),
            }
        )
        with python_reference():
            ref_end, ref_k = knock._knock_onset(event, octane, config)
        nat_end, nat_k = knock._knock_onset(event, octane, config)
        assert nat_k == ref_k
        assert close(nat_end, ref_end), (nat_end, ref_end)
        knocked += ref_k >= 0
    assert 0 < knocked < 400  # a amostra cobre ciclos com e sem knock


def test_evaluate_knock_parity() -> None:
    config = SPEC_CONFIG
    for kwargs in ({"knock": True}, {"knock": True, "xb_k": 0.99}, {}):
        event = make_event(2, 0.01, 4000.0, **kwargs)
        with python_reference():
            ref = knock.evaluate_knock(event, 1935.0, config)
        nat = knock.evaluate_knock(event, 1935.0, config)
        assert nat.knock_class == ref.knock_class
        assert nat.theta_onset_deg_atdc == ref.theta_onset_deg_atdc
        for field in ("lw_integral_end", "mapo_kpa", "intensity", "knock_energy_j"):
            assert close(getattr(nat, field), getattr(ref, field)), field


def test_traces_finite_parity() -> None:
    base = make_event(1, 0.0, 3000.0)
    for bad in (None, math.nan, math.inf, -math.inf):
        pressure = list(base.pressure_kpa)
        if bad is not None:
            pressure[7] = bad
        event = base.model_copy(update={"pressure_kpa": pressure})
        with python_reference():
            ref = knock._traces_finite(event)
        assert knock._traces_finite(event) is ref
        assert ref is (bad is None)


# ------------------------------------------------------------------ modelo completo

StateFn = Callable[[np.random.Generator, int, float, DamageModel], dict[str, Any]]


def _stress_state(
    rng: np.random.Generator, tick: int, t: float, model: DamageModel
) -> dict[str, Any]:
    """Estado aleatório perto e acima dos limites (pistão, EGT, rpm, turbo)."""
    limits = model.limits
    n = model.n_cyl
    rpm = float(rng.uniform(0.8, 1.02) * limits.max_rpm)
    lam = [None if rng.random() < 0.1 else float(rng.uniform(0.75, 1.1)) for _ in range(n)]
    turbo_max = limits.turbo_max_rpm
    turbo = None if turbo_max is None else float(rng.uniform(0.9, 1.06) * turbo_max)
    return {
        "rpm": rpm,
        "map_kpa": float(rng.uniform(100.0, 260.0)),
        "piston_temp_c": rng.uniform(250.0, 380.0, n).tolist(),
        "lambda_cyl": lam,
        "egt_c": rng.uniform(800.0, 1150.0, n).tolist(),
        "egt_collector_c": float(rng.uniform(850.0, 1100.0)),
        "turbo_rpm": turbo,
        "imep_gross_kpa": float(rng.uniform(800.0, 2600.0)),
        "hot_spot_temp_c": rng.uniform(500.0, 900.0, n).tolist(),
    }


def _burst_state(
    rng: np.random.Generator, tick: int, t: float, model: DamageModel
) -> dict[str, Any]:
    over = _stress_state(rng, tick, t, model)
    if tick == 150 and model.limits.turbo_max_rpm is not None:
        over["turbo_rpm"] = 1.2 * model.limits.turbo_max_rpm
    return over


def _events(rng: np.random.Generator, n_cyl: int, t: float, rpm: float) -> list[Any]:
    events = []
    for c in range(1, n_cyl + 1):
        if rng.random() < 0.15:
            events.append(
                make_event(
                    c,
                    t,
                    rpm,
                    knock=bool(rng.random() < 0.6),
                    xb_k=float(rng.uniform(0.3, 0.95)),
                    p_k=float(rng.uniform(4000.0, 14_000.0)),
                    p_max_kpa=float(rng.uniform(8000.0, 13_500.0)),
                    rod_force_n=float(rng.uniform(30_000.0, 60_000.0)),
                    imep_kpa=float(rng.uniform(800.0, 2600.0)),
                )
            )
    return events


def _drive(
    factory: Callable[[], DamageModel],
    ticks: int,
    state_fn: StateFn,
    seed: int,
    *,
    hook: Callable[[DamageModel, int], DamageModel] | None = None,
) -> tuple[DamageModel, list[dict[str, Any]]]:
    model = factory()
    rng = np.random.default_rng(seed)
    dt = 1.0 / 1000
    trail: list[dict[str, Any]] = []
    for tick in range(1, ticks + 1):
        t = tick * dt
        over = state_fn(rng, tick, t, model)
        events = _events(rng, model.n_cyl, t, over["rpm"])
        state = make_state(tick, t, over.pop("rpm"), model.n_cyl, events, **over)
        result = model.step(state, dt, make_ecu(model.n_cyl, retard=float(rng.uniform(0, 4))))
        trail.append(
            {
                "health": model._health.copy(),
                "virtual": model._virtual.copy(),
                "causes": model._causes.copy(),
                "first": model._first_damage.copy(),
                "knock_temp": model._knock_temp.copy(),
                "valve_temp": model._valve_temp.copy(),
                "turbine_temp": model._turbine_temp.copy(),
                "piston_eff": list(result.piston_temp_eff_c),
                "components": [c.model_dump() for c in result.components],
                "failures": [
                    (f.component_id, f.mode, f.mechanism, f.tick, f.catastrophic)
                    for f in result.new_failures
                ],
                "locked": result.engine_locked,
            }
        )
        if hook is not None:
            model = hook(model, tick)
    return model, trail


def _compare(ref: list[dict[str, Any]], nat: list[dict[str, Any]]) -> None:
    assert len(ref) == len(nat)
    for tick, (a, b) in enumerate(zip(ref, nat, strict=True), start=1):
        for key in ("health", "virtual", "causes", "first", "knock_temp", "valve_temp"):
            assert_arrays(f"{key} tick {tick}", a[key], b[key])
        assert_arrays(f"turbine_temp tick {tick}", a["turbine_temp"], b["turbine_temp"])
        assert_arrays(f"piston_eff tick {tick}", a["piston_eff"], b["piston_eff"])
        assert a["failures"] == b["failures"], tick
        assert a["locked"] == b["locked"], tick
        for ca, cb in zip(a["components"], b["components"], strict=True):
            assert ca.keys() == cb.keys()
            assert set(ca["damage_by_cause"]) == set(cb["damage_by_cause"]), tick
            for cause, value in ca["damage_by_cause"].items():
                assert close(value, cb["damage_by_cause"][cause]), (tick, cause)
            assert ca["failed"] == cb["failed"]
            assert close(ca["health"], cb["health"])
            assert close(ca["first_damage_t_sim_s"], cb["first_damage_t_sim_s"])


def _factory(
    vehicle: Any, config: DamageConfig, damage_enabled: bool = True
) -> Callable[[], DamageModel]:
    fuel = build_e27()

    def make() -> DamageModel:
        return DamageModel(config, vehicle, fuel, 42, damage_enabled, session_id="parity")

    return make


def _run_both(
    factory: Callable[[], DamageModel], ticks: int, state_fn: StateFn, **kw: Any
) -> tuple[Any, Any]:
    with python_reference():
        ref_model, ref = _drive(factory, ticks, state_fn, 7, **kw)
        assert not ref_model.native_kernel
    nat_model, nat = _drive(factory, ticks, state_fn, 7, **kw)
    assert nat_model.native_kernel
    _compare(ref, nat)
    return ref_model, nat_model


CONFIGS = {
    "default": DamageConfig(),
    "spec": SPEC_CONFIG,
    "sem_thermal": DamageConfig(features=("knock", "mechanical", "signal", "preignition")),
    "sem_mechanical": DamageConfig(features=("knock", "thermal", "signal", "preignition")),
}


@pytest.mark.parametrize("name", sorted(CONFIGS))
def test_model_parity_hatch(name: str) -> None:
    config = CONFIGS[name]
    ref_model, _ = _run_both(_factory(build_hatch(), config), 600, _stress_state)
    causes = {cause for c in ref_model.components() for cause in c.damage_by_cause}
    if config.enabled("thermal"):
        assert "thermal" in causes  # fluência exercitada
    if config.enabled("mechanical"):
        assert {"overrev", "overload"} <= causes


def test_model_parity_v8_without_turbine() -> None:
    _run_both(_factory(build_v8(), DamageConfig()), 400, _stress_state)


def test_model_parity_damage_off() -> None:
    config = DamageConfig()
    assert config.enabled("damage_off")
    _run_both(_factory(build_hatch(), config, damage_enabled=False), 400, _stress_state)


def test_model_parity_turbo_burst_locks() -> None:
    ref_model, nat_model = _run_both(_factory(build_hatch(), DamageConfig()), 200, _burst_state)
    assert ref_model.engine_locked and nat_model.engine_locked
    assert ref_model.failures[-1].mode == nat_model.failures[-1].mode


def test_model_parity_snapshot_and_restore() -> None:
    def hook(model: DamageModel, tick: int) -> DamageModel:
        if tick == 150:  # snapshot → modelo novo: os arrays são trocados
            blob = model.snapshot()
            fresh = _factory(build_hatch(), DamageConfig())()
            fresh.load_snapshot(blob)
            return fresh
        if tick == 300:
            model.restore()
        return model

    ref_model, nat_model = _run_both(
        _factory(build_hatch(), DamageConfig()), 450, _stress_state, hook=hook
    )
    assert nat_model.native_kernel
    assert ref_model.restore_count == nat_model.restore_count == 1
