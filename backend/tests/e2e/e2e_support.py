"""Execuções dos E2E de backend em processos separados (T218, T220, T453).

As funções de módulo deste arquivo são serializáveis (``ProcessPoolExecutor`` com ``spawn``):
cada execução corre num processo novo, como o worker de produção (``worker_mode=process``).

- ``lucas_journey``: a jornada do Lucas da ``tests/integration/test_journey_lucas.py``
  (mesmos ajudantes: calibração exagerada, corrigida, ``Probe``, ``run``), resumida em dados
  simples para o processo pai verificar 20 de 20.
- ``determinism_run``: uma ``sweep_pull`` de 30 s simulados a 1000 Hz no laço completo
  (``DynoSimTask`` + ``ProfiledEcu`` + dano padrão + ``TelemetrySampler``), com o log montado
  pelo ``Logbook`` de produção e avaliado pelo avaliador puro dos cenários; devolve os digests
  da física, do dano, da curva, do datalog e da avaliação (simulation-bus 5).
"""

from __future__ import annotations

import asyncio
import importlib.util
import multiprocessing
import os
import platform
import sys
from concurrent.futures import ProcessPoolExecutor
from functools import cache
from pathlib import Path
from types import ModuleType
from typing import Any, Final

TESTS = Path(__file__).resolve().parents[1]
for _sub in ("dyno", "telemetry"):
    if str(TESTS / _sub) not in sys.path:
        sys.path.insert(0, str(TESTS / _sub))

SEED: Final = 42
SIM_HZ: Final = 1000
# sweep_pull de 2000 a 6500 rpm a 150 rpm/s ⇒ 30 s de fase running (+ arming e coastdown).
DETERMINISM_REQUEST: Final[dict[str, Any]] = {
    "run_type": "sweep_pull",
    "start_rpm": 2000,
    "end_rpm": 6500,
    "ramp_rate_rpm_s": 150.0,
}
DIGEST_KEYS: Final = (
    "physics_state_digest",
    "damage_digest",
    "curve_sha256",
    "datalog_sha256",
    "evaluation_sha256",
)


@cache
def integration_module(name: str) -> ModuleType:
    """``tests/integration/<name>.py`` carregado por caminho (ajudantes das jornadas)."""
    path = TESTS / "integration" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"e2e_reuse_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def lucas_module() -> ModuleType:
    """``tests/integration/test_journey_lucas.py`` (ajudantes da jornada, sem duplicar)."""
    return integration_module("test_journey_lucas")


def pool(n_jobs: int) -> ProcessPoolExecutor:
    workers = max(2, min(n_jobs, os.cpu_count() or 2))
    return ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn"))


def machine_arch() -> str:
    """``amd64`` ou ``arm64`` (nomes do Docker/D-08) a partir de ``platform.machine()``."""
    machine = platform.machine().lower()
    return {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(
        machine, machine
    )


# --------------------------------------------------------------------------- Lucas (T218)


def _summary(out: Any) -> dict[str, Any]:
    run = out.run
    summary = run.summary
    return {
        "state": str(run.state.value),
        "peak_whp": None if summary is None else summary.peak_whp,
        "peak_torque_engine_nm": None if summary is None else summary.peak_torque_engine_nm,
        "egt_max_c": None if summary is None else summary.egt_max_c,
        "failure_event_id": None if summary is None else summary.failure_event_id,
        "curve_sha256": run.curve_sha256,
        "health": {
            k: out.result.get("health", {}).get(k)
            for k in ("min_health", "integrity_pct", "intact", "engine_locked")
        },
        "failures": [
            {k: f.get(k) for k in ("mode", "mechanism", "catastrophic", "failure_event_id")}
            for f in out.result.get("failures", [])
        ],
    }


def lucas_journey(seed: int = SEED) -> dict[str, Any]:
    """Uma execução completa da jornada do Lucas (base → exagerada → restore → corrigida)."""
    from dyno_helpers import catalog_fuels, make_task

    from simremap.damage.config import DamageConfig
    from simremap.damage.forensic.report import build_forensic_report
    from simremap.dyno.trace_codec import decode_trace

    steps = lucas_module()
    vehicle, stock = steps._catalog()
    task = make_task(
        vehicle=vehicle,
        fuel=catalog_fuels()["e27"],
        calibration=steps._content(stock),
        calibration_id=f"stock-{steps.VEHICLE_ID}-oem-stage",
        profile_hooks="registry",
        damage_config=DamageConfig(),
        seed=seed,
    )
    base = steps.run(task, "baseline_pull")
    steps.apply(task, steps.exaggerated_payload(stock), "lucas-exagerada")
    probe = steps.Probe()
    failed = steps.run(task, "sweep_pull", probe)
    traces = [e["payload"] for e in failed.of_type("damage.trace")]
    report: dict[str, Any] | None = None
    if traces and traces[0]["kind"] == "failure":
        built = build_forensic_report(
            decode_trace(traces[0]["trace"]), failed.run, base.run, None, "failure"
        )
        report = {
            "chain_kinds": [link.kind for link in built.causal_chain],
            "rules": sorted({r.rule_id for r in built.recommendations}),
            "max_lead_time_s": max((w.lead_time_s for w in built.early_warnings), default=0.0),
        }
    task.handle_command({"type": "engine.restore", "request_id": "restore-1"})
    severe_or_moderate = [
        k for k in steps.knock_events(failed) if steps.CLASS_RANK[k["knock_class"]] >= 2
    ]
    cylinders = sorted({int(k["cylinder"]) for k in severe_or_moderate}) or [1, 2, 3, 4]
    rpm_max = max((float(k["rpm"]) for k in severe_or_moderate), default=4000.0)
    steps.apply(task, steps.corrected_payload(stock, cylinders, rpm_max), "lucas-corrigida")
    corrected = steps.run(task, "sweep_pull")
    return {
        "seed": seed,
        "base": {**_summary(base), "worst_knock": steps.worst_knock(base)},
        "failed": {
            **_summary(failed),
            "worst_knock": steps.worst_knock(failed),
            "max_retard_deg": probe.max_retard_deg,
            "report": report,
        },
        "corrected": {**_summary(corrected), "worst_knock": steps.worst_knock(corrected)},
        "knock_cylinders": cylinders,
    }


# --------------------------------------------------------------------------- determinismo


def _scenario(scenario_id: str) -> Any:
    from simremap.scenarios.catalog import builtin_documents
    from simremap.scenarios.contracts import Scenario

    doc = builtin_documents()[scenario_id]
    doc["initial_calibration"] = {**doc["initial_calibration"], "content_hash": "0" * 64}
    return Scenario.model_validate(doc)


def _build_log(task: Any, run_id: str, max_s: float) -> tuple[Any, Any]:
    """Avança a tarefa publicando no ``TelemetryStream`` e fecha o log pelo ``Logbook``."""
    import orjson

    from simremap.dyno.contracts import DynoRun
    from simremap.telemetry.broadcaster import TelemetryStream
    from simremap.telemetry.logbook import Logbook, SessionMeta

    payload = task.session.payload
    meta = SessionMeta(
        payload.vehicle.vehicle_id,
        "oem-stage",
        payload.fuel.fuel_id,
        payload.seed,
        payload.calibration_hash,
    )
    built: list[Any] = []

    async def pump() -> Any:
        book = Logbook(None, lambda sid, rid: meta, end_grace_s=0.0)
        original = book.build

        def capture(pending: Any) -> Any:
            data = original(pending)
            built.append(data)
            return data

        book.build = capture  # type: ignore[method-assign]
        stream = TelemetryStream(payload.session_id, book)
        task.handle_command({"type": "run.start", "run_id": run_id, "request": DETERMINISM_REQUEST})
        result: Any = None
        log_end = False
        for _ in range(round(max_s * task.sim_hz)):
            task.step()
            for raw in task.drain_outputs():
                env = orjson.loads(raw)
                stream.publish(raw)
                if env["type"] == "run.result":
                    result = env["payload"]
                elif env["type"] == "telemetry.log_end":
                    log_end = True
            if result is not None and log_end:
                break
        await book.wait_idle()
        return result

    result = asyncio.run(pump())
    assert result is not None, "a puxada não terminou"
    assert built, "o Logbook não fechou o log"
    return DynoRun.model_validate(result["run"]), built[0]


def determinism_run(seed: int = SEED) -> dict[str, Any]:
    """Uma execução de 30 s a 1000 Hz no laço completo e os 5 digests (RN-10; RF-07)."""
    from dyno_helpers import catalog_fuels, make_task

    from simremap.damage.config import DamageConfig
    from simremap.scenarios.evaluator import EvaluationInput, EvidenceRun, evaluate
    from simremap.scenarios.trace import traces_for_run
    from simremap.telemetry.sampler import SAMPLER_SPEC

    steps = lucas_module()
    vehicle, stock = steps._catalog()
    task = make_task(
        vehicle=vehicle,
        fuel=catalog_fuels()["e27"],
        calibration=steps._content(stock),
        calibration_id=f"stock-{steps.VEHICLE_ID}-oem-stage",
        profile_hooks="registry",
        damage_config=DamageConfig(),
        seed=seed,
        sim_hz=SIM_HZ,
        sampler=SAMPLER_SPEC,
    )
    run_id = "01JE2E0000000000000000DET1"
    run, log = _build_log(task, run_id, max_s=120.0)
    summary = run.summary
    assert summary is not None
    trace = traces_for_run(log, run_id=run_id, pedal_pct=100.0, multi=False)[0]
    evidence = EvidenceRun(
        run_id=run_id,
        run_type="sweep_pull",
        peak_whp=summary.peak_whp,
        peak_whp_rpm=summary.peak_whp_rpm,
        peak_torque_engine_nm=summary.peak_torque_engine_nm,
        peak_torque_rpm=summary.peak_torque_rpm,
        failures=0,
        profile_id="oem-stage",
        trace=trace,
    )
    evaluation = evaluate(
        _scenario("stage1-oem"),
        EvaluationInput(
            attempt_id="00000000-0000-4000-8000-000000000042",
            submission_index=1,
            baseline_peak_whp=summary.peak_whp,
            evidence=[evidence, evidence.model_copy(update={"pull_index": 1})],
            calibration_content_hash=task.session.payload.calibration_hash,
        ),
        evaluation_id="00000000-0000-4000-8000-0000000000e2",
    )
    return {
        "physics_state_digest": task.session.physics.state_digest(),
        "damage_digest": task.session.damage.damage_digest(),
        "curve_sha256": run.curve_sha256,
        "datalog_sha256": log.sha256,
        "evaluation_sha256": evaluation.evaluation_sha256,
        "t_sim_s": task.t_sim_s,
        "log_samples": log.header.n_samples,
        "run_state": str(run.state.value),
    }
