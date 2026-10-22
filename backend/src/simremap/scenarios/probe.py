"""Sonda determinística de margem de knock (training-scenarios RF-14; dyno RF-26).

Repete sem UI a primeira puxada de evidência na sessão da tentativa (mesma ``seed``,
``sim_hz``, ambiente, falhas e calibração congelada) com ``ProbeOverrides``:
``ignition_offset_deg = min_knock_margin_deg`` somado ao avanço depois da arbitragem da
ECU, ``knock_control_open_loop = true`` (retardo fixo em 0°) e ``damage_enabled = false``.
A puxada de um ``multi_pull`` é repetida como uma puxada única do ``pull_type`` do pedido.

Aprovação: puxada ``completed`` e 0 ciclos com knock (classe diferente de ``none`` no
``knock-and-failure-model``; eventos ``event.knock`` do log, que nunca suprime o 1.º
evento de cada cilindro) entre ``start_rpm`` e ``end_rpm`` na fase ``running``. A falha
traz o primeiro ciclo com knock (cilindro, rpm, ``t_sim_s``, intensidade).

Falha interna (exceção do worker, ``internal_error`` ou sessão indisponível) ⇒
``ProbeFailed`` (``Evaluation.status = error``, ``error_code = PROBE_FAILED``, EC-06).
"""

from __future__ import annotations

from typing import Final

from simremap.core.errors import SimRemapError
from simremap.core.logging import get_logger
from simremap.dyno.contracts import (
    AbortReason,
    DynoRun,
    DynoRunRequest,
    ProbeOverrides,
    RunType,
)
from simremap.scenarios.evaluator import KnockCycle, ProbeResult
from simremap.scenarios.ports import SimulationPort, sleep
from simremap.scenarios.trace import phase_of
from simremap.telemetry.datalog import LogData

__all__ = ["PROBE_TIMEOUT_S", "ProbeFailed", "knock_cycles", "probe_request", "run_probe"]

log = get_logger("simremap.scenarios")

PROBE_TIMEOUT_S: Final = 120.0
LOG_RETRY_DELAYS_S: Final[tuple[float, ...]] = (0.2, 0.4, 0.8)


class ProbeFailed(RuntimeError):
    """Falha interna da sonda (``PROBE_FAILED``)."""


def probe_request(source: DynoRunRequest, offset_deg: float) -> DynoRunRequest:
    """Pedido da sonda a partir do pedido da puxada de evidência."""
    data = source.model_dump(mode="json")
    if source.run_type == RunType.MULTI_PULL:
        data["run_type"] = source.pull_type
    data["probe"] = ProbeOverrides(
        ignition_offset_deg=offset_deg, knock_control_open_loop=True, damage_enabled=False
    ).model_dump(mode="json")
    data["label"] = "sonda de knock"
    return DynoRunRequest.model_validate(data)


def knock_cycles(
    log_data: LogData, start_rpm: float, end_rpm: float
) -> tuple[int, KnockCycle | None]:
    """Eventos de knock na fase ``running`` entre ``start_rpm`` e ``end_rpm``."""
    phases = phase_of(log_data)
    count = 0
    first: KnockCycle | None = None
    for event in sorted(log_data.header.events, key=lambda e: e.index):
        if event.type != "event.knock":
            continue
        payload = event.payload
        index = min(max(event.index, 0), max(log_data.header.n_samples - 1, 0))
        rpm = float(payload.get("rpm", 0.0))
        if log_data.header.n_samples and phases[index] != "running":
            continue
        if not start_rpm - 1e-9 <= rpm <= end_rpm + 1e-9:
            continue
        count += 1
        if first is None:
            t = float(log_data.t_sim_s[index]) if log_data.header.n_samples else 0.0
            first = KnockCycle(
                cylinder=int(payload.get("cylinder", 1)),
                rpm=rpm,
                t_sim_s=t,
                intensity=float(payload.get("intensity_raw", payload.get("intensity", 0.0))),
                knock_class=str(payload.get("knock_class", "light")),
            )
    return count, first


async def _load_log(sim: SimulationPort, run_id: str) -> LogData | None:
    for delay in (*LOG_RETRY_DELAYS_S, None):
        try:
            return await sim.load_log(run_id)
        except SimRemapError:
            if delay is None:
                return None
            await sleep(delay)
    return None  # pragma: no cover


async def run_probe(
    sim: SimulationPort,
    session_id: str,
    source: DynoRun,
    offset_deg: float,
    *,
    rev_limit_rpm: float,
    timeout_s: float = PROBE_TIMEOUT_S,
) -> ProbeResult:
    """Executa a sonda e devolve o ``ProbeResult`` (``ProbeFailed`` em falha interna)."""
    request = probe_request(source.request, offset_deg)
    try:
        started = await sim.start_run(session_id, request)
        run = await sim.wait_run(session_id, started.run_id, timeout_s)
    except (SimRemapError, TimeoutError) as exc:
        log.warning("scenarios.probe_failed", session_id=session_id, reason=type(exc).__name__)
        raise ProbeFailed(str(exc)) from exc
    if run.abort_reason == AbortReason.INTERNAL_ERROR:
        raise ProbeFailed("a puxada da sonda terminou com erro interno")
    end_rpm = request.effective_end_rpm(rev_limit_rpm)
    data = await _load_log(sim, run.run_id)
    if data is not None:
        count, first = knock_cycles(data, request.start_rpm, end_rpm)
    else:
        count = 0 if run.summary is None else run.summary.knock_events
        first = None
    log.info(
        "scenarios.probe_done",
        session_id=session_id,
        run_id=run.run_id,
        state=run.state.value,
        knock_cycles=count,
    )
    return ProbeResult(
        run_id=run.run_id,
        source_run_id=source.run_id,
        ignition_offset_deg=offset_deg,
        state=run.state.value,
        knock_cycles=count,
        first_knock=first,
        curve_sha256=run.curve_sha256,
    )
