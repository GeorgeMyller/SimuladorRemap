"""Máquina de estados da puxada e regras de aborto (T122; dyno RF-13 a RF-17).

``RunController`` alimentado com observações sintéticas (sem física): os números das RFs
são verificados tick a tick.
"""

from __future__ import annotations

from typing import Any

import pytest
from dyno_helpers import RUN_ID, SESSION_ID, fixture_hatch

from simremap.damage.contracts import (
    FailureEvent,
    FailureMechanism,
    FailureMode,
    KnockClass,
    KnockObservation,
)
from simremap.dyno.contracts import (
    RUN_STATE_TRANSITIONS,
    AbortReason,
    AmbientConditions,
    CorrectionStandard,
    DynoRigConfig,
    DynoRunRequest,
    RunState,
)
from simremap.dyno.correction import correction_factor
from simremap.dyno.curve import CurveSample
from simremap.dyno.rig import Driveline
from simremap.dyno.runs import (
    ARMING_TIMEOUT_S,
    COASTDOWN_TIMEOUT_S,
    MeasuredSample,
    RunContext,
    RunController,
    RunMachine,
    TickObservation,
)

HZ = 1000
DT = 1.0 / HZ


def make_run(request: dict[str, Any] | None = None, **ctx: Any) -> RunController:
    rig = DynoRigConfig()
    data: dict[str, Any] = {
        "session_id": SESSION_ID,
        "run_id": RUN_ID,
        "request": DynoRunRequest.model_validate(
            request or {"run_type": "baseline_pull", "end_rpm": 6300}
        ),
        "sim_hz": HZ,
        "driveline": Driveline.from_vehicle(fixture_hatch(), rig),
        "rig": rig,
        "end_rpm": 6300.0,
        "idle_rpm": 850.0,
        "egt_limit_c": 950.0,
        "egt_abort_enabled": True,
        "operator_protection": False,
        "correction": correction_factor(CorrectionStandard.SAE_J1349, AmbientConditions()),
        "calibration_id": "stock-hatch-20t-gdi-oem-stage",
        "calibration_hash": "a" * 64,
        "seed": 7,
        "started_at_tick": 0,
    }
    data.update(ctx)
    run = RunController(RunContext(**data))
    run.start(0, 0.0)
    return run


class Driver:
    """Avança o ``RunController`` com rpm/EGT/knock escolhidos pelo teste."""

    def __init__(self, run: RunController) -> None:
        self.run = run
        self.k = 0
        self.rpm = 2000.0

    def tick(self, **over: Any) -> None:
        run = self.run
        run.begin_tick(self.k)
        if run.terminal:
            self.k += 1
            return
        plan = run.plan(self.k * DT)
        measured = None
        if plan.measure_tag is not None:
            measured = MeasuredSample(_sample(self.rpm, self.k * DT), plan.measure_tag)
        obs = TickObservation(
            tick=self.k,
            t_sim_s=self.k * DT,
            rpm=over.pop("rpm", self.rpm),
            egt_c=over.pop("egt_c", 800.0),
            map_kpa=over.pop("map_kpa", 220.0),
            limiter_active=over.pop("limiter_active", False),
            absorber_nm=over.pop("absorber_nm", 0.0),
            failures=over.pop("failures", []),
            knock_last=over.pop("knock_last", []),
            knock_events=over.pop("knock_events", 0),
            measured=over.pop("measured", measured),
        )
        run.observe(obs)
        self.k += 1

    def until(self, predicate: Any, limit_s: float = 120.0, **over: Any) -> None:
        for _ in range(round(limit_s * HZ)):
            if predicate():
                return
            self.tick(**dict(over))
        raise AssertionError("condição não atingida")

    def to_running(self) -> None:
        self.rpm = 2000.0
        self.until(lambda: self.run.state == RunState.RUNNING)


def _sample(rpm: float, t: float) -> CurveSample:
    return CurveSample(
        rpm=rpm,
        t_sim_s=t,
        power_wheel_kw=100.0,
        power_crank_kw=117.6,
        torque_wheel_nm=1000.0,
        torque_engine_nm=300.0,
        lambda_=0.85,
        afr=11.2,
        egt_c=850.0,
        map_kpa=220.0,
        iat_c=40.0,
        ect_c=90.0,
        oil_c=95.0,
        ignition_deg_btdc=18.0,
        knock_retard_max_deg=0.0,
        pedal_pct=100.0,
    )


def failure(tick: int, catastrophic: bool = True, simulated: bool = False) -> FailureEvent:
    return FailureEvent(
        failure_event_id="01JAB0000000000000000000FF",
        session_id=SESSION_ID,
        run_id=RUN_ID,
        tick=tick,
        t_sim_s=tick * DT,
        cylinder=1,
        component_id="rod:1",
        mode=FailureMode.ROD_FAILURE,
        mechanism=FailureMechanism.ROD_OVERLOAD,
        catastrophic=catastrophic,
        simulated_only=simulated,
        health_after=0.0,
        causal_variables={"torque_nm": 450.0},
    )


def knock_obs(t: float, klass: KnockClass, cylinder: int = 1) -> KnockObservation:
    return KnockObservation(
        cylinder=cylinder,
        t_sim_s=t,
        rpm=4000.0,
        lw_integral_end=1.5,
        theta_onset_deg_atdc=10.0,
        burned_fraction_onset=0.6,
        autoignited_fraction=0.2,
        mapo_kpa=400.0,
        intensity={KnockClass.SEVERE: 4.0, KnockClass.MODERATE: 2.0}.get(klass, 0.5),
        knock_energy_j=1.0,
        knock_class=klass,
        in_sensor_window=True,
        preignition="none",
        p_preignition_kpa=None,
    )


# --------------------------------------------------------------------------- transições


@pytest.mark.parametrize("current", list(RunState))
@pytest.mark.parametrize("target", list(RunState))
def test_machine_rejects_transitions_outside_table(current: RunState, target: RunState) -> None:
    machine = RunMachine()
    machine.state = current
    if target in RUN_STATE_TRANSITIONS[current]:
        assert machine.transition(target) == current
        assert machine.state == target
    else:
        with pytest.raises(ValueError, match="transição inválida"):
            machine.transition(target)


def test_happy_path_emits_exactly_one_run_state_per_transition() -> None:
    run = make_run()
    d = Driver(run)
    d.to_running()
    d.until(lambda: run.state == RunState.COASTDOWN, rpm=6300.0)
    d.until(lambda: run.terminal, rpm=1000.0)
    states = [(p.previous_state, p.state) for p in run.drain()]
    assert states == [
        (RunState.IDLE, RunState.ARMING),
        (RunState.ARMING, RunState.RUNNING),
        (RunState.RUNNING, RunState.COASTDOWN),
        (RunState.COASTDOWN, RunState.COMPLETED),
    ]
    result = run.result()
    assert result.state == RunState.COMPLETED
    assert result.abort_reason is None
    assert result.curve and result.summary is not None
    assert result.curve_sha256 is not None


def test_arming_needs_one_second_within_25_rpm() -> None:
    run = make_run()
    d = Driver(run)
    for _ in range(999):
        d.tick(rpm=2010.0)
    states = [run.state]
    d.tick(rpm=2030.0)  # sai da tolerância: recomeça
    for _ in range(999):
        d.tick(rpm=2000.0)
    states.append(run.state)
    d.tick(rpm=2000.0)
    states.append(run.state)
    assert states == [RunState.ARMING, RunState.ARMING, RunState.RUNNING]


def test_arming_timeout_aborts() -> None:
    run = make_run()
    d = Driver(run)
    d.until(lambda: run.terminal, limit_s=ARMING_TIMEOUT_S + 1, rpm=1500.0)
    assert run.result().abort_reason == AbortReason.ARMING_TIMEOUT
    assert d.k == pytest.approx(ARMING_TIMEOUT_S * HZ, abs=2)


def test_rf14_catastrophic_failure_at_tick_k_ends_at_k_plus_1() -> None:
    run = make_run()
    d = Driver(run)
    d.to_running()
    k = d.k
    d.tick(failures=[failure(k)])
    assert run.state == RunState.RUNNING  # transição no tick seguinte
    d.tick()
    result = run.result()
    assert result.state == RunState.ENGINE_FAILED
    assert result.ended_at_tick == k + 1
    assert result.abort_reason == AbortReason.CATASTROPHIC_FAILURE
    assert result.summary is not None
    assert result.summary.failure_event_id == "01JAB0000000000000000000FF"
    assert result.summary.forensic_report_url == f"/api/v1/runs/{RUN_ID}/forensic-report"
    last = run.drain()[-1]
    assert last.forensic_report_url == result.summary.forensic_report_url


def test_failure_in_coastdown_is_engine_failed_and_simulated_ignored() -> None:
    run = make_run()
    d = Driver(run)

    def in_coastdown() -> bool:
        return run.state == RunState.COASTDOWN

    d.to_running()
    d.tick(failures=[failure(d.k, catastrophic=True, simulated=True)])
    d.tick(failures=[failure(d.k, catastrophic=False)])
    assert run.state == RunState.RUNNING
    d.until(in_coastdown, rpm=6300.0)
    d.tick(rpm=5000.0, failures=[failure(d.k)])
    d.tick(rpm=4900.0)
    assert run.result().state == RunState.ENGINE_FAILED


def test_rf15_egt_abort_after_half_second_but_not_before() -> None:
    run = make_run()
    d = Driver(run)
    d.to_running()
    for _ in range(400):
        d.tick(rpm=3000.0, egt_c=960.0)
    d.tick(rpm=3000.0, egt_c=900.0)
    assert run.state == RunState.RUNNING  # 0,4 s não aborta
    for _ in range(600):
        d.tick(rpm=3000.0, egt_c=960.0)
        if run.terminal:
            break
    result = run.result()
    assert result.state == RunState.ABORTED
    assert result.abort_reason == AbortReason.EGT_LIMIT


def test_egt_abort_disabled() -> None:
    run = make_run(egt_abort_enabled=False)
    d = Driver(run)
    d.to_running()
    for _ in range(1000):
        d.tick(rpm=3000.0, egt_c=1000.0)
    assert run.state == RunState.RUNNING


@pytest.mark.parametrize("protection", [True, False])
def test_rf16_severe_knock_three_cycles_with_protection(protection: bool) -> None:
    run = make_run(operator_protection=protection)
    d = Driver(run)
    d.to_running()
    for i in range(3):
        t = d.k * DT
        d.tick(rpm=3000.0, knock_last=[knock_obs(t, KnockClass.SEVERE), None, None, None])
        d.tick(rpm=3000.0, knock_last=[knock_obs(t, KnockClass.SEVERE), None, None, None])
        del i
    if protection:
        assert run.result().abort_reason == AbortReason.SEVERE_KNOCK_PROTECTION
    else:
        assert run.state == RunState.RUNNING


def test_severe_knock_counter_resets_on_lighter_cycle() -> None:
    run = make_run(operator_protection=True)
    d = Driver(run)
    d.to_running()
    pattern = [
        KnockClass.SEVERE,
        KnockClass.SEVERE,
        KnockClass.LIGHT,
        KnockClass.SEVERE,
        KnockClass.SEVERE,
    ]
    for klass in pattern:
        d.tick(rpm=3000.0, knock_last=[knock_obs(d.k * DT, klass)])
    assert run.state == RunState.RUNNING


def test_rf17_user_abort_and_abort_in_coastdown() -> None:
    run = make_run()
    d = Driver(run)
    d.to_running()
    run.request_abort(AbortReason.USER_ABORT)
    run.request_abort(AbortReason.SESSION_CLOSED)  # ignorado: já pendente
    d.tick()
    assert run.result().abort_reason == AbortReason.USER_ABORT
    other = make_run()
    d2 = Driver(other)
    d2.to_running()
    d2.until(lambda: other.state == RunState.COASTDOWN, rpm=6300.0)
    other.request_abort(AbortReason.USER_ABORT)
    d2.tick(rpm=5000.0)
    result = other.result()
    assert result.state == RunState.COMPLETED
    assert "user_abort_in_coastdown" in (result.summary.event_codes if result.summary else [])
    other.request_abort(AbortReason.USER_ABORT)  # terminal: ignorado
    with pytest.raises(RuntimeError):
        make_run().result()


def test_ec07_rev_limiter_ends_running_and_ec05_run_timeout() -> None:
    run = make_run()
    d = Driver(run)
    d.to_running()
    for _ in range(301):
        d.tick(rpm=5900.0, limiter_active=True)
    assert run.state == RunState.COASTDOWN
    d.until(lambda: run.terminal, rpm=900.0)
    assert "rev_limiter_hit" in (run.result().summary.event_codes or [])  # type: ignore[union-attr]
    slow = make_run()
    d2 = Driver(slow)
    d2.to_running()
    d2.until(lambda: slow.terminal, limit_s=62.0, rpm=3000.0)
    assert slow.result().abort_reason == AbortReason.RUN_TIMEOUT


def test_coastdown_timeout_completes_with_event() -> None:
    run = make_run()
    d = Driver(run)
    d.to_running()
    d.until(lambda: run.state == RunState.COASTDOWN, rpm=6300.0)
    d.until(lambda: run.terminal, limit_s=COASTDOWN_TIMEOUT_S + 1, rpm=4000.0)
    result = run.result()
    assert result.state == RunState.COMPLETED
    assert "coastdown_timeout" in (result.summary.event_codes if result.summary else [])


def test_internal_error_aborts_and_progress() -> None:
    run = make_run()
    d = Driver(run)
    d.to_running()
    d.tick(rpm=4150.0)
    states = run.drain()
    assert (
        states[-1].progress_pct == pytest.approx(0.0, abs=1.0)
        or states[-1].progress_pct is not None
    )
    run.fail_now(AbortReason.INTERNAL_ERROR, d.k)
    assert run.result().abort_reason == AbortReason.INTERNAL_ERROR
    run.fail_now(AbortReason.INTERNAL_ERROR, d.k)  # já terminal


def test_internal_error_in_coastdown_completes() -> None:
    run = make_run()
    d = Driver(run)
    d.to_running()
    d.until(lambda: run.state == RunState.COASTDOWN, rpm=6300.0)
    run.fail_now(AbortReason.INTERNAL_ERROR, d.k)
    assert run.result().state == RunState.COMPLETED


def test_ramp_not_sustained_event_on_sweep() -> None:
    run = make_run({"run_type": "sweep_pull", "end_rpm": 6300, "ramp_rate_rpm_s": 1000})
    d = Driver(run)
    d.to_running()
    for _ in range(700):
        d.tick(rpm=2000.0, absorber_nm=0.0)
    assert "ramp_not_sustained" in run.current.events
