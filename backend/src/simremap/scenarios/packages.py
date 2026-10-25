"""Pacotes ``SignedPackage`` de desafio e de tentativa (training-scenarios RF-18 a RF-21;
file-formats 5; D-11; premissas OQ-01/OQ-02: só SHA-256, sem HMAC e sem PIN).

- ``sha256 = hex(SHA-256(JCS({"format_version", "kind", "payload"})))`` com a biblioteca
  ``rfc8785``. O ``payload`` é gravado já preparado para JCS (inteiros acima de 2^53 − 1,
  como ``seed``, em texto decimal), para que qualquer recálculo independente com
  ``rfc8785.dumps`` dê o mesmo hash.
- Export: nome ``simremap-<kind>-<id>-<8 hex>.simremap.json``; ``NaN``/``Infinity`` ⇒ 422
  ``PACKAGE_NOT_CANONICALIZABLE`` com o caminho JSON no ``detail``.
- Import (ordem fixa): JSON inválido/truncado ⇒ ``PACKAGE_MALFORMED``; ``format_version``
  acima de ``PACKAGE_FORMAT_VERSION`` ⇒ ``PACKAGE_FORMAT_UNSUPPORTED``; não finito ⇒
  ``PACKAGE_NOT_CANONICALIZABLE``; fora do schema ⇒ ``PACKAGE_SCHEMA_INVALID``; hash
  divergente ⇒ ``PACKAGE_HASH_MISMATCH`` (``expected_sha256``/``actual_sha256``); já
  importado ⇒ 200 ``already_imported``. Pacote de tentativa: só instrutor, cenário local com
  o mesmo ``scenario_sha256`` (senão 409 ``SCENARIO_VERSION_MISMATCH``) e avaliação
  recalculada a partir das evidências embutidas (``evaluation_mismatch``). Tudo numa
  transação: em erro nada é gravado.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from pydantic import ValidationError

from simremap.core.errors import SimRemapError
from simremap.core.logging import get_logger
from simremap.core.versions import PACKAGE_FORMAT_VERSION
from simremap.db.base import utcnow
from simremap.db.models.scenarios import (
    AttemptRow,
    AttemptRunRow,
    EvaluationRow,
    ImportedPackageRow,
)
from simremap.dyno.contracts import DynoRun
from simremap.scenarios.attempts import StoredRun
from simremap.scenarios.catalog import ScenarioCatalog, scenario_sha256, validate_rules
from simremap.scenarios.contracts import (
    Attempt,
    Evaluation,
    PackageExportRequest,
    PackageImportResult,
    PackageProducer,
    PlayerProfile,
    Scenario,
    SignedPackage,
)
from simremap.scenarios.errors import scenario_error
from simremap.scenarios.evaluator import EvaluationInput, ProbeResult, evaluate
from simremap.scenarios.events import EventLog
from simremap.scenarios.jcs import NotCanonicalizableError, find_non_finite, jcs_sha256, prepare
from simremap.scenarios.ports import CalibrationPort, SimulationPort
from simremap.scenarios.profiles import require_instructor
from simremap.scenarios.repository import ImportBundle, ScenarioRepository, scenario_row
from simremap.scenarios.trace import TRACE_COLUMNS
from simremap.telemetry.export import iter_json

__all__ = [
    "PACKAGE_MAX_BYTES",
    "ExportedPackage",
    "PackageService",
    "package_filename",
    "package_sha256",
    "sign",
]

log = get_logger("simremap.scenarios")

PACKAGE_MAX_BYTES: Final = 64 * 1024 * 1024


def package_sha256(format_version: int, kind: str, payload: dict[str, Any]) -> str:
    """SHA-256 do JCS de ``{format_version, kind, payload}``."""
    return jcs_sha256({"format_version": format_version, "kind": kind, "payload": payload})


def package_filename(kind: str, ident: str, sha256: str) -> str:
    return f"simremap-{kind}-{ident}-{sha256[:8]}.simremap.json"


def sign(
    kind: str, payload: dict[str, Any], producer: PackageProducer, created_at: datetime
) -> SignedPackage:
    """Pacote assinado (payload preparado para JCS; ``created_at`` e ``producer`` fora do hash)."""
    prepared = prepare(payload)
    return SignedPackage(
        format_version=PACKAGE_FORMAT_VERSION,
        kind=kind,  # type: ignore[arg-type]
        created_at=created_at,
        producer=producer,
        payload=prepared,
        sha256=package_sha256(PACKAGE_FORMAT_VERSION, kind, prepared),
        hmac_sha256=None,
    )


@dataclass(frozen=True, slots=True)
class ExportedPackage:
    package: SignedPackage
    filename: str


def _schema(detail: str, **extra: object) -> SimRemapError:
    return scenario_error("PACKAGE_SCHEMA_INVALID", detail[:2000], **extra)


def _validation_detail(exc: ValidationError) -> str:
    err = exc.errors()[0]
    loc = ".".join(str(p) for p in err.get("loc", ()))
    return f"{loc}: {err.get('msg', '')}"


class PackageService:
    """Export e import de pacotes."""

    def __init__(
        self,
        repo: ScenarioRepository,
        catalog: ScenarioCatalog,
        sim: SimulationPort,
        calibrations: CalibrationPort,
        events: EventLog,
        *,
        app_version: str,
        install_id: Callable[[], str | None],
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.repo = repo
        self.catalog = catalog
        self.sim = sim
        self.calibrations = calibrations
        self.events = events
        self.app_version = app_version
        self.install_id = install_id
        self.clock = clock

    def _producer(self, nickname: str | None) -> PackageProducer:
        install = self.install_id() or "00000000-0000-4000-8000-000000000000"
        return PackageProducer(app_version=self.app_version, install_id=install, nickname=nickname)

    # ------------------------------------------------------------------ export
    async def export(self, body: PackageExportRequest, profile: PlayerProfile) -> ExportedPackage:
        if body.kind == "challenge":
            assert body.scenario_id is not None  # noqa: S101 - garantido pelo contrato
            payload, ident, scenario_id, attempt_id = await self._challenge_payload(
                body.scenario_id
            )
        else:
            assert body.attempt_id is not None  # noqa: S101 - garantido pelo contrato
            payload, ident, scenario_id = await self._attempt_payload(
                body.attempt_id, body.include_full_logs
            )
            attempt_id = ident
        try:
            package = sign(body.kind, payload, self._producer(profile.nickname), self.clock())
        except NotCanonicalizableError as exc:
            raise scenario_error(
                "PACKAGE_NOT_CANONICALIZABLE",
                f"Valor não finito (NaN ou Infinity) em {exc.path.replace('$', '$.payload', 1)}.",
                path=exc.path.replace("$", "$.payload", 1),
            ) from exc
        await self.events.record(
            "package_exported",
            scenario_id,
            attempt_id or "",
            {"kind": body.kind, "package_sha256": package.sha256, "profile_id": profile.profile_id},
        )
        return ExportedPackage(package, package_filename(body.kind, ident, package.sha256))

    async def _challenge_payload(self, scenario_id: str) -> tuple[dict[str, Any], str, str, None]:
        scenario = await self.catalog.get(scenario_id)
        initial = scenario.initial_calibration
        content: dict[str, Any] | None = initial.payload
        if initial.source == "vehicle_stock":
            stock = await self.calibrations.stock(scenario.vehicle_id, scenario.initial_profile_id)
            content = None if stock is None else stock.content
        payload = {"scenario": scenario.model_dump(mode="json"), "initial_calibration": content}
        return payload, scenario.scenario_id, scenario.scenario_id, None

    async def _attempt_payload(
        self, attempt_id: str, include_logs: bool
    ) -> tuple[dict[str, Any], str, str]:
        row = await self.repo.get_attempt(attempt_id.lower())
        if row is None:
            raise scenario_error("ATTEMPT_NOT_FOUND", f"A tentativa {attempt_id} não existe.")
        evaluations = [e for e in await self.repo.evaluations_of(row.id) if e.status == "completed"]
        if not evaluations or "input" not in evaluations[-1].result_json:
            raise scenario_error(
                "ATTEMPT_NOT_EVALUATED",
                f"A tentativa {attempt_id} ainda não tem avaliação concluída.",
            )
        ev_row = evaluations[-1]
        scenario = await self.catalog.get(row.scenario_id)
        stored = await self.repo.runs_of(row.id)
        runs_rows = [StoredRun.from_row(r) for r in stored]
        from simremap.scenarios.attempts import attempt_from_row

        attempt = attempt_from_row(
            row,
            sorted(runs_rows, key=lambda r: (r.started_at_tick, r.run_id, r.pull_index)),
            str(scenario.scenario_sha256),
        )
        inp = EvaluationInput.model_validate(ev_row.result_json["input"])
        cal = ev_row.result_json.get("calibration", {})
        frozen = await self.calibrations.get(str(cal.get("calibration_id")), cal.get("version"))
        wanted = list(
            dict.fromkeys(
                [
                    *([row.baseline_run_id] if row.baseline_run_id else []),
                    *(e.run_id for e in inp.evidence),
                ]
            )
        )
        runs: list[dict[str, Any]] = []
        logs: list[dict[str, Any]] = []
        for run_id in wanted:
            run = await self.sim.get_run(run_id)
            if run is None:
                continue
            runs.append(run.model_dump(mode="json", by_alias=True))
            if include_logs:
                data = await self.sim.load_log(run_id)
                logs.append(json.loads(b"".join(iter_json(data))))
        traces = [
            {
                "run_id": r.run_id,
                "pull_index": r.pull_index,
                "run_type": r.run_type,
                "valid": r.valid,
                "invalid_reason": r.invalid_reason,
                "calibration_hash": r.calibration_hash,
                "peak_whp": r.peak_whp,
                "columns": list(TRACE_COLUMNS),
                "rows": r.trace.rows,
                "run": r.meta,
            }
            for r in runs_rows
        ]
        submission = inp.model_dump(mode="json")
        submission["evidence"] = []
        payload: dict[str, Any] = {
            "scenario": scenario.model_dump(mode="json"),
            "attempt": attempt.model_dump(mode="json"),
            "calibration": frozen.full,
            "runs": runs,
            "traces": traces,
            "evidence_refs": [
                {"run_id": e.run_id, "pull_index": e.pull_index} for e in inp.evidence
            ],
            "submission": submission,
            "probe": None if inp.probe is None else inp.probe.model_dump(mode="json"),
            "evaluation": ev_row.result_json["evaluation"],
            "session": {
                "vehicle_id": scenario.vehicle_id,
                "profile_id": scenario.initial_profile_id,
                "fuel_id": scenario.fuel_id,
                "seed": row.seed,
            },
        }
        if include_logs:
            payload["logs"] = logs
        return payload, row.id, row.scenario_id

    # ------------------------------------------------------------------ import
    @staticmethod
    def parse(body: bytes) -> SignedPackage:
        """Valida o corpo cru (malformado, versão, não finito, schema, hash)."""
        if len(body) > PACKAGE_MAX_BYTES:
            raise SimRemapError("O pacote passa de 64 MiB.", code="PAYLOAD_TOO_LARGE")
        try:
            data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise scenario_error(
                "PACKAGE_MALFORMED", f"JSON inválido ou truncado: {exc}"[:2000]
            ) from exc
        if not isinstance(data, dict):
            raise scenario_error("PACKAGE_MALFORMED", "O pacote deve ser um objeto JSON.")
        version = data.get("format_version", PACKAGE_FORMAT_VERSION)
        if (
            isinstance(version, int)
            and not isinstance(version, bool)
            and version > PACKAGE_FORMAT_VERSION
        ):
            raise scenario_error(
                "PACKAGE_FORMAT_UNSUPPORTED",
                f"format_version {version} não suportado; "
                f"esta versão lê até {PACKAGE_FORMAT_VERSION}.",
                supported=PACKAGE_FORMAT_VERSION,
            )
        bad = find_non_finite(data)
        if bad is not None:
            raise scenario_error(
                "PACKAGE_NOT_CANONICALIZABLE", f"Valor não finito em {bad}.", path=bad
            )
        payload, kind, declared = data.get("payload"), data.get("kind"), data.get("sha256")
        if (
            not isinstance(payload, dict)
            or not isinstance(kind, str)
            or not isinstance(declared, str)
        ):
            raise _schema("o pacote exige format_version, kind, payload (objeto) e sha256")
        try:
            actual = package_sha256(int(version), kind, payload)
        except (TypeError, ValueError) as exc:
            raise _schema(f"pacote não canonicalizável: {exc}") from exc
        if actual != declared:
            raise scenario_error(
                "PACKAGE_HASH_MISMATCH",
                "O SHA-256 recalculado do pacote não confere: o conteúdo foi alterado.",
                expected_sha256=declared,
                actual_sha256=actual,
            )
        try:
            package = SignedPackage.model_validate(data)
        except ValidationError as exc:
            raise _schema(_validation_detail(exc)) from exc
        return package

    async def import_package(
        self, body: bytes, profile: PlayerProfile
    ) -> tuple[PackageImportResult, bool]:
        """Importa; devolve ``(resultado, criado)`` (``criado = False`` ⇒ 200 já importado)."""
        package = self.parse(body)
        if package.kind == "attempt":
            require_instructor(profile, "importar pacotes de tentativa")
        existing = await self.repo.imported_package(package.sha256)
        if existing is not None:
            return (
                PackageImportResult(
                    package_sha256=package.sha256,
                    kind=package.kind,
                    scenario_id=existing.scenario_id,
                    attempt_id=existing.attempt_id,
                    already_imported=True,
                ),
                False,
            )
        if package.kind == "challenge":
            return await self._import_challenge(package, len(body)), True
        return await self._import_attempt(package, len(body)), True

    def _package_row(
        self, package: SignedPackage, scenario_id: str, attempt_id: str | None, size: int
    ) -> ImportedPackageRow:
        return ImportedPackageRow(
            sha256=package.sha256,
            kind=package.kind,
            scenario_id=scenario_id,
            attempt_id=attempt_id,
            size_bytes=max(1, size),
            imported_at=self.clock(),
        )

    def _payload_scenario(self, package: SignedPackage) -> Scenario:
        raw = package.payload.get("scenario")
        if not isinstance(raw, dict):
            raise _schema("payload.scenario ausente")
        try:
            return Scenario.model_validate(raw)
        except ValidationError as exc:
            raise _schema(f"payload.scenario.{_validation_detail(exc)}") from exc

    async def _import_challenge(self, package: SignedPackage, size: int) -> PackageImportResult:
        scenario = self._payload_scenario(package)
        if scenario.kind != "challenge" or scenario.builtin:
            raise _schema("pacote de desafio só aceita cenários kind 'challenge'")
        info = self.catalog.vehicle(scenario.vehicle_id)
        try:
            validate_rules(scenario, info, wastegate_enabled=self.catalog.wastegate_enabled())
        except SimRemapError as exc:
            detail = str(exc.args[0]) if exc.args else "cenário inválido"
            if "defeito não suportado" in detail:
                detail = "defeito não suportado: " + detail
            raise _schema(detail) from exc
        local_sha = scenario_sha256(scenario)
        current = await self.repo.get_scenario(scenario.scenario_id)
        if current is not None and current.scenario_sha256 != local_sha:
            raise scenario_error(
                "SCENARIO_VERSION_MISMATCH",
                f"O cenário {scenario.scenario_id} já existe nesta estação com outro conteúdo.",
                expected_sha256=current.scenario_sha256,
                actual_sha256=local_sha,
            )
        new_row = None
        if current is None:
            imported = scenario.model_copy(
                update={
                    "origin": "imported",
                    "builtin": False,
                    "created_at": self.clock(),
                    "scenario_sha256": local_sha,
                }
            )
            new_row = scenario_row(imported)
        await self.repo.import_bundle(
            ImportBundle(
                self._package_row(package, scenario.scenario_id, None, size), scenario=new_row
            )
        )
        log.info("scenarios.package_imported", kind="challenge", scenario_id=scenario.scenario_id)
        return PackageImportResult(
            package_sha256=package.sha256, kind="challenge", scenario_id=scenario.scenario_id
        )

    async def _import_attempt(self, package: SignedPackage, size: int) -> PackageImportResult:
        payload = package.payload
        embedded = self._payload_scenario(package)
        local = await self.repo.get_scenario(embedded.scenario_id)
        if local is None:
            raise scenario_error(
                "SCENARIO_NOT_FOUND",
                f"O cenário {embedded.scenario_id} não existe nesta estação.",
                scenario_id=embedded.scenario_id,
            )
        embedded_sha = scenario_sha256(embedded)
        try:
            attempt = Attempt.model_validate(payload.get("attempt"))
            declared = Evaluation.model_validate(payload.get("evaluation"))
            submission = EvaluationInput.model_validate(payload.get("submission"))
            probe = (
                None
                if payload.get("probe") is None
                else ProbeResult.model_validate(payload["probe"])
            )
            runs = [DynoRun.model_validate(r) for r in payload.get("runs", [])]
            traces = [self._stored(t) for t in payload.get("traces", [])]
            refs = [
                (str(r["run_id"]), int(r.get("pull_index", 0)))
                for r in payload.get("evidence_refs", [])
            ]
        except (ValidationError, KeyError, TypeError, ValueError) as exc:
            detail = _validation_detail(exc) if isinstance(exc, ValidationError) else str(exc)
            raise _schema(f"payload: {detail}") from exc
        if (
            local.scenario_sha256 != embedded_sha
            or attempt.scenario_sha256 != local.scenario_sha256
        ):
            raise scenario_error(
                "SCENARIO_VERSION_MISMATCH",
                "O cenário do pacote é diferente do cenário original desta estação.",
                expected_sha256=local.scenario_sha256,
                actual_sha256=embedded_sha,
            )
        current = await self.repo.get_attempt(attempt.attempt_id)
        if current is not None and current.origin != "imported":
            raise _schema(f"a tentativa {attempt.attempt_id} já existe localmente nesta estação")
        recomputed = self._recompute(local, attempt, submission, probe, runs, traces, refs)
        mismatch = recomputed.evaluation_sha256 != declared.evaluation_sha256
        now = self.clock()
        replay_source = {
            "producer_app_version": package.producer.app_version,
            "session": payload.get("session", {}),
            "calibration": payload.get("calibration"),
            "runs": [
                {
                    "run_id": r.run_id,
                    "request": r.request.model_dump(mode="json"),
                    "curve_sha256": r.curve_sha256,
                    "run_type": r.run_type.value,
                    "peak_whp": None if r.summary is None else r.summary.peak_whp,
                    "pulls_peak_whp": [p.summary.peak_whp for p in r.pulls],
                    "curve": [p.model_dump(mode="json", by_alias=True) for p in r.curve],
                    "pull_curves": [
                        [p.model_dump(mode="json", by_alias=True) for p in pr.curve]
                        for pr in r.pulls
                    ],
                }
                for r in runs
                if r.run_id in {ref[0] for ref in refs}
            ],
        }
        attempt_row = AttemptRow(
            id=attempt.attempt_id,
            scenario_id=local.scenario_id,
            profile_id=None,
            nickname=attempt.nickname,
            origin="imported",
            state=attempt.state.value,
            session_id=None,
            calibration_id=attempt.calibration_id,
            seed=attempt.seed,
            baseline_run_id=attempt.baseline_run_id,
            baseline_peak_whp=attempt.baseline_peak_whp,
            submissions=attempt.submissions,
            hints_revealed_json=list(attempt.hints_revealed),
            engine_restores=attempt.engine_restores,
            producer_install_id=package.producer.install_id,
            package_sha256=package.sha256,
            replay_status="not_run",
            started_at=attempt.started_at,
            updated_at=now,
        )
        run_rows = [
            AttemptRunRow(
                attempt_id=attempt.attempt_id,
                run_id=t.run_id,
                pull_index=t.pull_index,
                run_type=t.run_type,
                valid=t.valid,
                invalid_reason=t.invalid_reason,
                calibration_hash=t.calibration_hash,
                peak_whp=t.peak_whp,
                trace_json={"columns": list(TRACE_COLUMNS), "rows": t.trace.rows, "run": t.meta},
            )
            for t in traces
        ]
        evaluation_row = EvaluationRow(
            id=str(uuid.uuid4()),
            attempt_id=attempt.attempt_id,
            submission_index=recomputed.submission_index,
            status="completed",
            passed=recomputed.passed,
            total_score=recomputed.total_score,
            evaluation_sha256=recomputed.evaluation_sha256,
            evaluation_mismatch=mismatch,
            result_json={
                "evaluation": recomputed.model_dump(mode="json"),
                "declared": declared.model_dump(mode="json"),
                "scenario_sha256": local.scenario_sha256,
                "replay_source": replay_source,
            },
            created_at=now,
        )
        await self.repo.import_bundle(
            ImportBundle(
                self._package_row(package, local.scenario_id, attempt.attempt_id, size),
                attempt=attempt_row,
                runs=run_rows,
                evaluation=evaluation_row,
                replace_attempt=current is not None,
            )
        )
        log.info(
            "scenarios.package_imported",
            kind="attempt",
            attempt_id=attempt.attempt_id,
            evaluation_mismatch=mismatch,
        )
        return PackageImportResult(
            package_sha256=package.sha256,
            kind="attempt",
            scenario_id=local.scenario_id,
            attempt_id=attempt.attempt_id,
            evaluation_mismatch=mismatch,
            recomputed_evaluation=recomputed,
        )

    @staticmethod
    def _stored(item: Any) -> StoredRun:
        if not isinstance(item, dict):
            raise ValueError("traces[] deve ser objeto")
        if list(item.get("columns", TRACE_COLUMNS)) != list(TRACE_COLUMNS):
            raise ValueError("traces[].columns fora da ordem fixa")
        row = AttemptRunRow(
            attempt_id="x",
            run_id=str(item["run_id"]),
            pull_index=int(item.get("pull_index", 0)),
            run_type=str(item["run_type"]),
            valid=bool(item["valid"]),
            invalid_reason=item.get("invalid_reason"),
            calibration_hash=item.get("calibration_hash"),
            peak_whp=item.get("peak_whp"),
            trace_json={"rows": list(item.get("rows", [])), "run": dict(item.get("run", {}))},
        )
        return StoredRun.from_row(row)

    @staticmethod
    def _recompute(
        scenario: Scenario,
        attempt: Attempt,
        submission: EvaluationInput,
        probe: ProbeResult | None,
        runs: list[DynoRun],
        traces: list[StoredRun],
        refs: list[tuple[str, int]],
    ) -> Evaluation:
        """Avaliação recalculada a partir das puxadas e traços embutidos (RF-20)."""
        by_run = {r.run_id: r for r in runs}
        by_key = {(t.run_id, t.pull_index): t for t in traces}
        evidence = []
        for run_id, pull_index in refs:
            stored = by_key.get((run_id, pull_index))
            if stored is None:
                raise _schema(f"evidência {run_id}#{pull_index} sem traço no pacote")
            ev = stored.evidence()
            run = by_run.get(run_id)
            summary = None
            if run is not None:
                pulls = {p.pull_index: p for p in run.pulls}
                summary = pulls[pull_index].summary if pull_index in pulls else run.summary
            if summary is not None:
                ev = ev.model_copy(
                    update={
                        "peak_whp": summary.peak_whp,
                        "peak_whp_rpm": summary.peak_whp_rpm,
                        "peak_torque_engine_nm": summary.peak_torque_engine_nm,
                        "peak_torque_rpm": summary.peak_torque_rpm,
                    }
                )
            evidence.append(ev)
        baseline = attempt.baseline_peak_whp
        base_run = by_run.get(attempt.baseline_run_id or "")
        if base_run is not None and base_run.summary is not None:
            baseline = base_run.summary.peak_whp
        inp = submission.model_copy(
            update={"evidence": evidence, "probe": probe, "baseline_peak_whp": baseline}
        )
        return evaluate(scenario, inp, evaluation_id=str(uuid.uuid4()))
