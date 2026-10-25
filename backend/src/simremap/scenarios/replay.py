"""Replay determinístico de tentativas importadas (training-scenarios RF-22, EC-03).

O instrutor pede ``POST /api/v1/attempts/{attempt_id}/replay`` (202): para cada puxada de
evidência embutida no pacote, o sistema cria uma sessão sem UI com o mesmo veículo,
perfil, combustível, ambiente, ``seed``, falhas do defeito oculto e a calibração
congelada, repete o mesmo ``DynoRunRequest`` e compara com o pacote.

Regras de comparação (decisão de interpretação registada no relatório):

1. integridade da curva embutida: o ``curve_sha256`` recalculado da curva bruta do pacote
   (forma do dono, ``dyno.curve.curve_sha256``) tem de ser igual ao declarado;
2. reexecução: ``curve_sha256`` idêntico ao do pacote **ou** pico de potência de cada
   puxada dentro de ``REPLAY_PEAK_TOLERANCE_PCT`` do declarado. A tolerância existe porque
   uma sessão nova parte do estado térmico do aquecimento determinístico, e a puxada
   original pode ter sido feita mais tarde na mesma sessão (o tempo entre puxadas segue o
   relógio de parede); uma curva forjada (resumo editado e hash recalculado) fica fora da
   tolerância ou falha a regra 1.

Resultado em ``Attempt.replay_status``: ``verified`` ou ``mismatch`` (com os ``run_id``
divergentes); ``producer.app_version`` diferente do local ⇒ 409
``REPLAY_VERSION_INCOMPATIBLE`` e ``replay_status = incompatible_version``.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from typing import Any, Final

from simremap.core.errors import SimRemapError
from simremap.core.logging import get_logger
from simremap.dyno.contracts import DynoCurvePoint, DynoRun, DynoRunRequest, SessionCreateRequest
from simremap.dyno.curve import curve_sha256
from simremap.scenarios.catalog import ScenarioCatalog
from simremap.scenarios.contracts import PlayerProfile, ReplayAccepted
from simremap.scenarios.errors import scenario_error
from simremap.scenarios.ports import CalibrationPort, SimulationPort
from simremap.scenarios.profiles import require_instructor
from simremap.scenarios.repository import ScenarioRepository
from simremap.scenarios.validity import expected_faults

__all__ = ["REPLAY_PEAK_TOLERANCE_PCT", "REPLAY_RUN_TIMEOUT_S", "ReplayService", "compare_run"]

log = get_logger("simremap.scenarios")

REPLAY_PEAK_TOLERANCE_PCT: Final = 2.0
REPLAY_RUN_TIMEOUT_S: Final = 180.0


def _embedded_sha(item: dict[str, Any]) -> str | None:
    pulls = item.get("pull_curves") or []
    try:
        if pulls:
            return curve_sha256([[DynoCurvePoint.model_validate(p) for p in c] for c in pulls])
        curve = item.get("curve") or []
        if not curve:
            return None
        return curve_sha256([DynoCurvePoint.model_validate(p) for p in curve])
    except ValueError:
        return None


def _peaks(run: DynoRun) -> list[float]:
    if run.pulls:
        return [p.summary.peak_whp for p in run.pulls]
    return [] if run.summary is None else [run.summary.peak_whp]


def compare_run(item: dict[str, Any], replayed: DynoRun) -> bool:
    """``True`` quando a puxada reexecutada confirma a puxada do pacote."""
    declared_sha = item.get("curve_sha256")
    if declared_sha is None or _embedded_sha(item) != declared_sha:
        return False
    if replayed.curve_sha256 == declared_sha:
        return True
    declared = list(item.get("pulls_peak_whp") or []) or (
        [] if item.get("peak_whp") is None else [float(item["peak_whp"])]
    )
    got = _peaks(replayed)
    if not declared or len(declared) != len(got):
        return False
    return all(
        d > 0 and abs(g - d) / d * 100.0 <= REPLAY_PEAK_TOLERANCE_PCT
        for d, g in zip(declared, got, strict=True)
    )


class ReplayService:
    def __init__(
        self,
        repo: ScenarioRepository,
        catalog: ScenarioCatalog,
        sim: SimulationPort,
        calibrations: CalibrationPort,
        *,
        app_version: str,
        timeout_s: float = REPLAY_RUN_TIMEOUT_S,
        spawn: Callable[[Any, str], Any] | None = None,
    ) -> None:
        self.repo = repo
        self.catalog = catalog
        self.sim = sim
        self.calibrations = calibrations
        self.app_version = app_version
        self.timeout_s = timeout_s
        self._spawn = spawn
        self._tasks: set[asyncio.Task[None]] = set()

    async def drain(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        with contextlib.suppress(Exception):
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def start(self, attempt_id: str, profile: PlayerProfile) -> ReplayAccepted:
        require_instructor(profile, "pedir replay de tentativas")
        row = await self.repo.get_attempt(attempt_id.lower())
        if row is None:
            raise scenario_error("ATTEMPT_NOT_FOUND", f"A tentativa {attempt_id} não existe.")
        evaluations = await self.repo.evaluations_of(row.id)
        source = None if not evaluations else evaluations[-1].result_json.get("replay_source")
        if row.origin != "imported" or not isinstance(source, dict):
            raise scenario_error(
                "ATTEMPT_NOT_EVALUATED", "Só tentativas importadas com pacote podem ter replay."
            )
        producer = str(source.get("producer_app_version", ""))
        if producer != self.app_version:
            await self.repo.update_attempt(row.id, replay_status="incompatible_version")
            raise scenario_error(
                "REPLAY_VERSION_INCOMPATIBLE",
                f"O pacote veio da versão {producer}; esta estação é a {self.app_version}.",
                producer_app_version=producer,
                app_version=self.app_version,
            )
        runs = list(source.get("runs", []))
        await self.repo.update_attempt(row.id, replay_status="running")
        task: asyncio.Task[None] = asyncio.create_task(
            self._replay(row.id, evaluations[-1].id, row.scenario_id, row.seed, source),
            name=f"replay-{row.id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return ReplayAccepted(attempt_id=row.id, runs_to_replay=len(runs))

    async def _replay(
        self,
        attempt_id: str,
        evaluation_id: str,
        scenario_id: str,
        seed: int,
        source: dict[str, Any],
    ) -> None:
        scenario = await self.catalog.get(scenario_id)
        session_info = dict(source.get("session", {}))
        mismatched: list[str] = []
        calibration_id: str | None = None
        try:
            calibration = source.get("calibration") or {}
            content = {
                k: calibration[k]
                for k in (
                    "vehicle_id",
                    "profile_id",
                    "fuel_model",
                    "tables",
                    "strategies",
                    "profile_params",
                )
                if k in calibration
            }
            record = await self.calibrations.create(content, f"replay {attempt_id[:8]}")
            calibration_id = record.calibration_id
            for item in source.get("runs", []):
                ok = await self._one(
                    scenario, record.calibration_id, record.profile_id, seed, session_info, item
                )
                if not ok:
                    mismatched.append(str(item.get("run_id")))
        except (SimRemapError, TimeoutError, ValueError, KeyError) as exc:
            log.warning("scenarios.replay_failed", attempt_id=attempt_id, reason=type(exc).__name__)
            mismatched = mismatched or [str(r.get("run_id")) for r in source.get("runs", [])]
        status = "mismatch" if mismatched else "verified"
        await self.repo.update_attempt(attempt_id, replay_status=status)
        evaluation = await self.repo.evaluations_of(attempt_id)
        target = next((e for e in evaluation if e.id == evaluation_id), None)
        if target is not None:
            result = dict(target.result_json)
            result["replay"] = {
                "status": status,
                "mismatch_run_ids": mismatched,
                "calibration_id": calibration_id,
            }
            await self.repo.update_evaluation(evaluation_id, result_json=result)
        log.info(
            "scenarios.replay_done",
            attempt_id=attempt_id,
            status=status,
            mismatched=len(mismatched),
        )

    async def _one(
        self,
        scenario: Any,
        calibration_id: str,
        profile_id: str,
        seed: int,
        session_info: dict[str, Any],
        item: dict[str, Any],
    ) -> bool:
        request = DynoRunRequest.model_validate(item["request"])
        session = await self.sim.create_session(
            SessionCreateRequest(
                vehicle_id=scenario.vehicle_id,
                calibration_id=calibration_id,
                profile_id=profile_id,  # type: ignore[arg-type]
                seed=int(session_info.get("seed", seed)),
                ambient=scenario.ambient,
                correction_standard=scenario.correction_standard,
                damage_enabled=True,
                fuel_id=scenario.fuel_id,
                physics_faults=expected_faults(scenario),
            )
        )
        try:
            started = await self.sim.start_run(session.session_id, request)
            run = await self.sim.wait_run(session.session_id, started.run_id, self.timeout_s)
        finally:
            with contextlib.suppress(SimRemapError):
                await self.sim.delete_session(session.session_id)
        return compare_run(item, run)
