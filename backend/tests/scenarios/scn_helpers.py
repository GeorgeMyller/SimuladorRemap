"""Auxiliares dos testes do training-scenarios (importados pelo conftest via ``sys.path``).

- ``RunSpec``: comportamento sintético de uma puxada (pico de whp, EGT, knock, lambda,
  pops, saúde final, estado, eventos de knock da sonda).
- ``make_log``/``make_run``: ``LogData`` (canais reais do catálogo da telemetria, 200 Hz) e
  ``DynoRun`` coerentes com o ``RunSpec`` — arming 1 s, rampa 2000 → ``end_rpm`` a
  300 rpm/s, coastdown 3 s (``multi_pull``: N puxadas com segmentos).
- ``FakeSimulation`` (``SimulationPort``): sessões e puxadas em memória; o comportamento de
  cada puxada vem de ``behaviour[content_hash]`` da calibração ativa da sessão (ou de
  ``queue``); ``apply`` simula ``POST .../calibration`` e regista na ``CalibrationAudit``.
- ``FakeCalibrations`` (``CalibrationPort``) e ``fake_vehicles`` (catálogo dos 4 veículos).
"""

from __future__ import annotations

import hashlib
import itertools
import json
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

import numpy as np

from simremap.core.errors import SimRemapError
from simremap.dyno.contracts import (
    AbortReason,
    DynoCurvePoint,
    DynoRun,
    DynoRunRequest,
    PullResult,
    RunState,
    RunSummary,
    RunType,
    SessionCreateRequest,
    SimulationSession,
)
from simremap.dyno.curve import curve_sha256
from simremap.scenarios.catalog import VehicleInfo
from simremap.scenarios.ports import CalibrationApply, CalibrationAudit, CalibrationRecord
from simremap.telemetry.channels import build_catalog
from simremap.telemetry.contracts import DataLogHeader, LogEvent, PullSegment
from simremap.telemetry.datalog import LogData

SIM_HZ = 200
CHANNELS = (
    "rpm",
    "lambda_measured",
    "egt_pre_turbo_c",
    "knock_retard_deg",
    "overrun_afterfire",
    "health_min_pct",
    "whp",
)
STOCK_HASH = {
    "hatch-20t-gdi": "a" * 64,
    "coupe-30t-i6": "b" * 64,
    "classic-20t-swap": "c" * 64,
    "muscle-v8-sc": "d" * 64,
}
REV_LIMIT = {
    "hatch-20t-gdi": 6500.0,
    "coupe-30t-i6": 7000.0,
    "classic-20t-swap": 7500.0,
    "muscle-v8-sc": 7500.0,
}
FUELS = {
    "hatch-20t-gdi": ("e27", "podium", "e0"),
    "coupe-30t-i6": ("e27", "podium", "e0"),
    "classic-20t-swap": ("e100", "e27", "podium"),
    "muscle-v8-sc": ("e27", "podium", "e0"),
}
N_CYL = {"hatch-20t-gdi": 4, "coupe-30t-i6": 6, "classic-20t-swap": 4, "muscle-v8-sc": 8}
_ids = itertools.count(1)


def new_run_id() -> str:
    return f"01J{next(_ids):023d}"


@dataclass(frozen=True)
class RunSpec:
    peak_whp: float = 262.0
    peak_torque_nm: float = 400.0
    egt_max_c: float = 930.0
    egt_peak_rpm: float = 6100.0
    egt_overrun_c: float = 880.0
    knock_max_deg: float = 1.5
    lambda_wot: float = 0.82
    pops: int = 0
    health_end_pct: float = 100.0
    state: RunState = RunState.COMPLETED
    abort_reason: AbortReason | None = None
    knock_events: tuple[tuple[float, int], ...] = ()  # (rpm, cilindro) só na fase running
    failure: bool = False


def vehicle_info(vehicle_id: str) -> VehicleInfo | None:
    if vehicle_id not in STOCK_HASH:
        return None
    stock_hash = STOCK_HASH[vehicle_id]
    return VehicleInfo(
        vehicle_id=vehicle_id,
        rev_limit_rpm=REV_LIMIT[vehicle_id],
        fuels=FUELS[vehicle_id],
        stock_profile_id="oem-stage",
        validated=True,
        factory_content_hash=lambda _profile_id: stock_hash,
    )


def fake_vehicles(vehicle_id: str) -> VehicleInfo | None:
    return vehicle_info(vehicle_id)


# --------------------------------------------------------------------------- logs


def _segment(
    spec: RunSpec, start_rpm: float, end_rpm: float, ramp: float, t0: float
) -> tuple[dict[str, list[float]], list[tuple[int, str, str]], list[float]]:
    """Amostras de 1 puxada: (colunas, marcas de fase (índice, state, phase), tempos)."""
    arming = int(1.0 * SIM_HZ)
    running = int((end_rpm - start_rpm) / ramp * SIM_HZ)
    coast = int(3.0 * SIM_HZ)
    cols: dict[str, list[float]] = {c: [] for c in CHANNELS}
    times: list[float] = []
    marks = [
        (0, "arming", "arming"),
        (arming, "running", "pull"),
        (arming + running, "coastdown", "coastdown"),
    ]
    total = arming + running + coast
    for i in range(total):
        times.append(round(t0 + i / SIM_HZ, 6))
        if i < arming:
            rpm, wot = start_rpm, True
        elif i < arming + running:
            rpm, wot = start_rpm + (i - arming) / SIM_HZ * ramp, True
        else:
            rpm, wot = max(1500.0, end_rpm - (i - arming - running) / SIM_HZ * 1200.0), False
        frac = max(0.0, min(1.0, (rpm - start_rpm) / max(1.0, end_rpm - start_rpm)))
        cols["rpm"].append(rpm)
        cols["lambda_measured"].append(spec.lambda_wot if wot else 1.05)
        if wot:
            gap = max(0.0, abs(rpm - spec.egt_peak_rpm) - 20.0)
            egt = 700.0 + (spec.egt_max_c - 700.0) * max(0.0, 1.0 - gap / 5000.0)
        else:
            egt = (
                spec.egt_overrun_c
                if i < arming + running + coast // 2
                else spec.egt_overrun_c - 50.0
            )
        cols["egt_pre_turbo_c"].append(egt)
        cols["knock_retard_deg"].append(spec.knock_max_deg * frac if wot else 0.0)
        k = i - arming - running
        pop_at = {int(j * coast / spec.pops) for j in range(spec.pops)} if spec.pops else set()
        pop = 1.0 if (not wot and k in pop_at) else 0.0
        cols["overrun_afterfire"].append(pop)
        cols["health_min_pct"].append(
            100.0 - (100.0 - spec.health_end_pct) * (i / max(1, total - 1))
        )
        cols["whp"].append(spec.peak_whp * frac if wot else 0.0)
    return cols, marks, times


def make_log(
    run_id: str,
    session_id: str,
    specs: list[RunSpec],
    request: DynoRunRequest,
    *,
    profile_id: str = "oem-stage",
    calibration_hash: str = "a" * 64,
    seed: int = 7,
    start_tick: int = 600,
    rev_limit: float = 6500.0,
) -> LogData:
    end_rpm = request.effective_end_rpm(rev_limit)
    cols: dict[str, list[float]] = {c: [] for c in CHANNELS}
    times: list[float] = []
    events: list[LogEvent] = []
    pulls: list[PullSegment] = []
    t0 = start_tick / SIM_HZ
    multi = len(specs) > 1
    for k, spec in enumerate(specs, start=1):
        base = len(times)
        seg_cols, marks, seg_t = _segment(
            spec, request.start_rpm, end_rpm, request.ramp_rate_rpm_s, t0 + base / SIM_HZ
        )
        for c in CHANNELS:
            cols[c].extend(seg_cols[c])
        times.extend(seg_t)
        for index, state, phase in marks:
            payload: dict[str, Any] = {
                "state": "running" if multi and state != "arming" else state,
                "phase": phase,
            }
            if multi:
                payload["pull_index"] = k
            events.append(LogEvent(index=base + index, type="run.state", payload=payload))
        running_start = base + marks[1][0]
        for j, (rpm, cyl) in enumerate(spec.knock_events):
            idx = running_start + int((rpm - request.start_rpm) / request.ramp_rate_rpm_s * SIM_HZ)
            events.append(
                LogEvent(
                    index=idx + j,
                    type="event.knock",
                    payload={
                        "cylinder": cyl,
                        "rpm": rpm,
                        "intensity": 0.6,
                        "intensity_raw": 1.8,
                        "knock_class": "moderate",
                        "run_id": run_id,
                    },
                )
            )
        if spec.failure:
            events.append(
                LogEvent(
                    index=base + marks[2][0] - 1,
                    type="event.failure",
                    payload={"component_id": "piston:1"},
                )
            )
        pulls.append(
            PullSegment(
                pull_index=k, start_index=base, end_index=len(times), state=spec.state.value
            )
        )
    n = len(times)
    catalog = build_catalog(4, True)
    channels = [catalog.get(c) for c in CHANNELS]
    header = DataLogHeader(
        run_id=run_id,
        session_id=session_id,
        vehicle_id="hatch-20t-gdi",
        profile_id=profile_id,
        calibration_hash=calibration_hash,
        fuel_id="e27",
        seed=seed,
        sim_hz=SIM_HZ,
        start_tick=start_tick,
        n_samples=n,
        channels=[c for c in channels if c is not None],
        pulls=pulls,
        events=sorted(events, key=lambda e: e.index),
        terminal_state=specs[-1].state.value,  # type: ignore[arg-type]
    )
    data = np.array([cols[c] for c in CHANNELS], dtype=np.float32)
    return LogData.build(header, np.array(times, dtype=np.float64), data)


def _curve(spec: RunSpec, start: float, end: float) -> list[DynoCurvePoint]:
    points = []
    rpm = start
    while rpm <= end:
        frac = (rpm - start) / max(1.0, end - start)
        kw = spec.peak_whp * frac * 0.7457
        points.append(
            DynoCurvePoint(
                rpm=rpm,
                t_sim_s=1.0 + (rpm - start) / 300.0,
                power_wheel_kw=kw,
                power_wheel_kw_corr=kw,
                power_crank_kw=kw * 1.15,
                power_crank_kw_corr=kw * 1.15,
                torque_wheel_nm=spec.peak_torque_nm * 0.9,
                torque_engine_nm=spec.peak_torque_nm,
                torque_engine_nm_corr=spec.peak_torque_nm,
                lambda_=spec.lambda_wot,
                afr=spec.lambda_wot * 14.0,
                egt_c=spec.egt_max_c,
                map_kpa=220.0,
                iat_c=35.0,
                ect_c=90.0,
                oil_c=100.0,
                ignition_deg_btdc=20.0,
                knock_retard_max_deg=spec.knock_max_deg * frac,
            )
        )
        rpm += 250.0
    return points


def _summary(spec: RunSpec) -> RunSummary:
    return RunSummary(
        peak_whp=spec.peak_whp,
        peak_whp_rpm=6000.0,
        peak_power_crank_kw=spec.peak_whp * 0.7457 * 1.15,
        peak_torque_engine_nm=spec.peak_torque_nm,
        peak_torque_rpm=3500.0,
        lambda_min=spec.lambda_wot,
        lambda_max=spec.lambda_wot,
        egt_max_c=spec.egt_max_c,
        iat_max_c=40.0,
        correction_factor=1.0,
        correction_out_of_range=False,
        knock_events=len(spec.knock_events),
        failure_event_id="fail-1" if spec.failure else None,
    )


def make_run(
    run_id: str,
    session_id: str,
    request: DynoRunRequest,
    specs: list[RunSpec],
    *,
    calibration_id: str,
    calibration_hash: str,
    seed: int,
    started_at_tick: int,
    rev_limit: float = 6500.0,
) -> DynoRun:
    end = request.effective_end_rpm(rev_limit)
    last = specs[-1]
    multi = request.run_type == RunType.MULTI_PULL
    pulls = []
    if multi:
        pulls = [
            PullResult(
                pull_index=k,
                state=s.state,
                summary=_summary(s),
                curve=_curve(s, request.start_rpm, end),
            )
            for k, s in enumerate(specs, start=1)
        ]
    curve = _curve(last, request.start_rpm, end)
    sha = curve_sha256([p.curve for p in pulls]) if multi else curve_sha256(curve)
    abort = last.abort_reason
    if last.state == RunState.ABORTED and abort is None:
        abort = AbortReason.USER_ABORT
    duration = int(
        sum(
            (1.0 + (end - request.start_rpm) / request.ramp_rate_rpm_s + 3.0) * SIM_HZ
            for _ in specs
        )
    )
    return DynoRun(
        run_id=run_id,
        session_id=session_id,
        run_type=request.run_type,
        request=request,
        state=last.state,
        abort_reason=abort,
        started_at_tick=started_at_tick,
        ended_at_tick=started_at_tick + duration,
        calibration_id=calibration_id,
        calibration_hash=calibration_hash,
        seed=seed,
        sim_hz=SIM_HZ,
        summary=_summary(last),
        curve=curve,
        pulls=pulls,
        curve_sha256=sha,
    )


# --------------------------------------------------------------------------- simulação


@dataclass
class _Session:
    view: SimulationSession
    calibration_id: str
    content_hash: str
    t_tick: int = 600
    runs: list[DynoRun] = field(default_factory=list)
    restores: int = 0
    closed: bool = False


class FakeSimulation:
    """``SimulationPort`` em memória com puxadas sintéticas."""

    def __init__(
        self, calibrations: FakeCalibrations, audit: CalibrationAudit | None = None
    ) -> None:
        self.calibrations = calibrations
        self.audit = audit
        self.sessions: dict[str, _Session] = {}
        self.runs: dict[str, DynoRun] = {}
        self.logs: dict[str, LogData] = {}
        self.behaviour: dict[str, RunSpec] = {}
        self.queue: list[list[RunSpec]] = []
        self.default = RunSpec(peak_whp=220.0, egt_max_c=900.0, knock_max_deg=0.5)
        self.deleted: list[str] = []
        self.capacity = 1
        self.fail_logs: set[str] = set()
        self.probe_spec: RunSpec | None = None
        self.requests: list[DynoRunRequest] = []

    def active(self) -> list[str]:
        return [sid for sid, s in self.sessions.items() if not s.closed]

    async def create_session(self, request: SessionCreateRequest) -> SimulationSession:
        if len(self.active()) >= self.capacity:
            raise SimRemapError("Limite de sessões.", code="SIM_CAPACITY_EXCEEDED")
        sid = uuid.uuid4().hex
        cal = await self.calibrations.get(str(request.calibration_id))
        view = SimulationSession(
            **request.model_dump(exclude={"seed", "calibration_id", "fuel_id"}),
            session_id=sid,
            seed=request.seed if request.seed is not None else 1,
            calibration_id=cal.calibration_id,
            fuel_id=request.fuel_id or "e27",
            state="ready",
            created_at=datetime.now(UTC),
        )
        self.sessions[sid] = _Session(
            view=view, calibration_id=cal.calibration_id, content_hash=cal.content_hash
        )
        return view

    async def delete_session(self, session_id: str) -> None:
        s = self.sessions.get(session_id)
        if s is None or s.closed:
            return
        s.closed = True
        self.deleted.append(session_id)

    async def session(self, session_id: str) -> SimulationSession | None:
        s = self.sessions.get(session_id)
        if s is None:
            return None
        return s.view.model_copy(update={"t_sim_s": s.t_tick / SIM_HZ})

    def apply(
        self,
        session_id: str,
        calibration_id: str,
        content_hash: str,
        *,
        profile_id: str | None = None,
    ) -> None:
        s = self.sessions[session_id]
        s.calibration_id = calibration_id
        s.content_hash = content_hash
        if profile_id is not None:
            s.view = s.view.model_copy(update={"profile_id": profile_id})
        if self.audit is not None:
            self.audit.record(
                session_id,
                CalibrationApply(
                    t_sim_s=s.t_tick / SIM_HZ,
                    calibration_id=calibration_id,
                    content_hash=content_hash,
                ),
            )

    async def start_run(self, session_id: str, request: DynoRunRequest) -> DynoRun:
        s = self.sessions.get(session_id)
        if s is None or s.closed:
            raise SimRemapError("Sessão inexistente.", code="SESSION_NOT_FOUND")
        self.requests.append(request)
        if request.probe is not None:
            spec = self.probe_spec or RunSpec()
            specs = [spec]
        elif self.queue:
            specs = self.queue.pop(0)
        else:
            spec = self.behaviour.get(s.content_hash, self.default)
            n = request.pull_count if request.run_type == RunType.MULTI_PULL else 1
            specs = [spec] * n
        rev = REV_LIMIT.get(s.view.vehicle_id, 6500.0)
        run_id = new_run_id()
        run = make_run(
            run_id,
            session_id,
            request,
            specs,
            calibration_id=s.calibration_id,
            calibration_hash=s.content_hash,
            seed=s.view.seed,
            started_at_tick=s.t_tick,
            rev_limit=rev,
        )
        log = make_log(
            run_id,
            session_id,
            specs,
            request,
            profile_id=str(s.view.profile_id),
            calibration_hash=s.content_hash,
            seed=s.view.seed,
            start_tick=s.t_tick,
            rev_limit=rev,
        )
        s.t_tick = int(run.ended_at_tick or s.t_tick) + 2 * SIM_HZ
        s.runs.append(run)
        self.runs[run_id] = run
        self.logs[run_id] = log
        return run

    async def wait_run(self, session_id: str, run_id: str, timeout_s: float) -> DynoRun:
        return self.runs[run_id]

    async def runs_of(self, session_id: str) -> list[DynoRun]:
        s = self.sessions.get(session_id)
        return [] if s is None else list(s.runs)

    async def get_run(self, run_id: str) -> DynoRun | None:
        return self.runs.get(run_id)

    async def load_log(self, run_id: str) -> LogData:
        if run_id in self.fail_logs or run_id not in self.logs:
            raise SimRemapError("Log inexistente.", code="LOG_NOT_FOUND")
        return self.logs[run_id]

    async def restore_count(self, session_id: str) -> int | None:
        s = self.sessions.get(session_id)
        return None if s is None else s.restores

    def current_calibration_hash(self, session_id: str) -> str | None:
        s = self.sessions.get(session_id)
        return None if s is None else s.content_hash


# --------------------------------------------------------------------------- calibrações


def _content(vehicle_id: str, profile_id: str, marker: str) -> dict[str, Any]:
    return {
        "vehicle_id": vehicle_id,
        "profile_id": profile_id,
        "fuel_model": {"mode": "speed_density_ve"},
        "tables": {"ignition_base": {"marker": marker}},
        "strategies": {},
        "profile_params": {},
    }


class FakeCalibrations:
    """``CalibrationPort`` em memória (hash = SHA-256 do JSON do conteúdo, ou o de série)."""

    def __init__(self) -> None:
        self.items: dict[str, list[CalibrationRecord]] = {}
        for vehicle_id, sha in STOCK_HASH.items():
            cal_id = f"stock-{vehicle_id}-oem-stage"
            content = _content(vehicle_id, "oem-stage", "stock")
            self.items[cal_id] = [
                CalibrationRecord(
                    cal_id,
                    1,
                    vehicle_id,
                    "oem-stage",
                    sha,
                    content,
                    {**content, "calibration_id": cal_id, "version": 1, "content_hash": sha},
                )
            ]
        self.fail = False
        # Hash que ``factory_clone`` grava (payload de fábrica do catálogo).
        self.factory_hash: dict[str, str] = dict(STOCK_HASH)
        self.factory_clones = 0

    @staticmethod
    def hash_of(content: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()

    async def stock(self, vehicle_id: str, profile_id: str) -> CalibrationRecord | None:
        if self.fail:
            raise SimRemapError("db", code="DATABASE_UNAVAILABLE")
        versions = self.items.get(f"stock-{vehicle_id}-{profile_id}")
        return None if not versions else versions[-1]

    async def get(self, calibration_id: str, version: int | None = None) -> CalibrationRecord:
        versions = self.items.get(calibration_id)
        if not versions:
            raise SimRemapError("Calibração inexistente.", code="CALIBRATION_NOT_FOUND")
        if version is None:
            return versions[-1]
        return versions[version - 1]

    async def create(
        self, content: dict[str, Any], name: str, *, content_hash: str | None = None
    ) -> CalibrationRecord:
        cal_id = str(uuid.uuid4())
        sha = content_hash or self.hash_of(content)
        record = CalibrationRecord(
            cal_id,
            1,
            str(content["vehicle_id"]),
            str(content["profile_id"]),
            sha,
            dict(content),
            {**content, "calibration_id": cal_id, "version": 1, "content_hash": sha},
        )
        self.items[cal_id] = [record]
        return record

    async def clone(self, source: CalibrationRecord, name: str) -> CalibrationRecord:
        return await self.create(source.content, name, content_hash=source.content_hash)

    async def factory_clone(
        self, vehicle_id: str, profile_id: str, name: str
    ) -> CalibrationRecord | None:
        sha = self.factory_hash.get(vehicle_id)
        if sha is None:
            return None
        self.factory_clones += 1
        return await self.create(
            _content(vehicle_id, profile_id, "factory"), name, content_hash=sha
        )

    def clone_hash(self, source: CalibrationRecord) -> str:
        return source.content_hash

    def new_version(self, calibration_id: str, marker: str) -> CalibrationRecord:
        """Nova versão (edição na ecu-tuning-ui) com conteúdo e hash novos."""
        last = self.items[calibration_id][-1]
        content = {**last.content, "tables": {"ignition_base": {"marker": marker}}}
        sha = self.hash_of(content)
        record = replace(
            last,
            version=last.version + 1,
            content_hash=sha,
            content=content,
            full={
                **content,
                "calibration_id": calibration_id,
                "version": last.version + 1,
                "content_hash": sha,
            },
        )
        self.items[calibration_id].append(record)
        return record
