"""Contratos dos cenários de treino (training-scenarios seção 9; file-formats 5).

- Perfis de jogador: ``PlayerProfileCreate`` e ``PlayerProfile`` (só ``nickname`` e ``role``).
- Cenário: ``Scenario``, ``HiddenDefect``, ``ChallengeCriteria`` (16 ``CriterionKind``),
  ``Hint``, ``ScenarioConstraints`` e ``InitialCalibration``.
- Tentativa e avaliação: ``Attempt``, ``AttemptRun``, ``Evaluation`` (com ``error_code``,
  D-REST-09), ``CriterionResult`` e ``Evidence``.
- Pacotes e estatísticas: ``SignedPackage`` (``format_version = 1``, ``hmac_sha256``
  reservado), ``ScenarioStats`` e os modelos de pedido/resposta da API.

Violações das regras do cenário levantam ``ValueError`` com o campo; o serviço converte em
422 ``SCENARIO_INVALID``.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Any, Final, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from simremap.catalog.contracts import PROFILE_IDS, FuelId, VehicleId
from simremap.core.contracts import ContractModel, Sha256Hex, SimStrEnum
from simremap.core.versions import PACKAGE_FORMAT_VERSION
from simremap.dyno.contracts import AmbientConditions, CorrectionStandard, UuidText
from simremap.physics.contracts import PhysicsFault

__all__ = [
    "EVALUATION_ERROR_CODES",
    "NICKNAME_PATTERN",
    "Attempt",
    "AttemptPage",
    "AttemptRun",
    "AttemptState",
    "AttemptView",
    "ChallengeCriteria",
    "Criterion",
    "CriterionKind",
    "CriterionResult",
    "DefectKind",
    "Evaluation",
    "Evidence",
    "HiddenDefect",
    "Hint",
    "HintReveal",
    "HintUnlock",
    "InitialCalibration",
    "Nickname",
    "PackageExportRequest",
    "PackageImportResult",
    "PackageProducer",
    "PlayerProfile",
    "PlayerProfileCreate",
    "ReplayAccepted",
    "ReplayStatus",
    "Role",
    "Scenario",
    "ScenarioConstraints",
    "ScenarioCreate",
    "ScenarioStats",
    "ScenarioSummary",
    "ScenarioView",
    "SignedPackage",
    "Slug",
    "SubmitAccepted",
    "SubmitRequest",
    "derive_attempt_seed",
]

NICKNAME_PATTERN: Final = r"^[-_0-9A-Za-z]{3,24}$"
SLUG_PATTERN: Final = r"^[0-9a-z][-0-9a-z]{2,63}$"
SEMVER_PATTERN: Final = r"^\d+\.\d+\.\d+$"
KNOCK_MARGIN_MIN_DEG: Final = 0.5
KNOCK_MARGIN_MAX_DEG: Final = 6.0
EVALUATION_ERROR_CODES: Final[frozenset[str]] = frozenset(
    {"TRACE_UNAVAILABLE", "PROBE_FAILED", "EVALUATION_INTERRUPTED", "DAMAGE_MODEL_UNAVAILABLE"}
)

Nickname = Annotated[str, Field(pattern=NICKNAME_PATTERN)]
Slug = Annotated[str, Field(pattern=SLUG_PATTERN)]
ReplayStatus = Literal["not_run", "running", "verified", "mismatch", "incompatible_version"]


def derive_attempt_seed(attempt_id: str) -> int:
    """Semente derivada da tentativa: ``int(sha256(attempt_id)[:15], 16)``."""
    return int(hashlib.sha256(attempt_id.encode()).hexdigest()[:15], 16)


class Role(SimStrEnum):
    STUDENT = "student"
    INSTRUCTOR = "instructor"


class PlayerProfileCreate(ContractModel):
    """Pedido de ``POST /api/v1/profiles`` (E-31). Nenhum outro dado pessoal."""

    nickname: Nickname
    role: Role = Role.STUDENT


class PlayerProfile(PlayerProfileCreate):
    profile_id: UuidText  # UUID4 (valor de X-Player-Profile-Id)
    created_at: AwareDatetime  # UTC, relógio de parede


# --------------------------------------------------------------------------- defeito oculto


class DefectKind(SimStrEnum):
    FUEL_PUMP_WEAK = "fuel_pump_weak"
    INJECTOR_CLOGGED = "injector_clogged"
    IAT_SENSOR_BIAS = "iat_sensor_bias"
    WASTEGATE_STUCK = "wastegate_stuck"
    BOOST_LEAK = "boost_leak"


_DEFECT_PARAMS: Final[dict[str, tuple[str, ...]]] = {
    "fuel_pump_weak": ("fuel_pump_max_lph",),
    "injector_clogged": ("cylinder", "injector_flow_factor"),
    "iat_sensor_bias": ("sensor_bias_c",),
    "wastegate_stuck": ("stuck_position_pct",),
    "boost_leak": ("leak_area_mm2",),
}


class HiddenDefect(ContractModel):
    kind: DefectKind
    fuel_pump_max_lph: float | None = Field(None, ge=60, le=250)  # L/h
    cylinder: int | None = Field(None, ge=1, le=8)
    injector_flow_factor: float | None = Field(None, ge=0.50, le=0.95)  # (-)
    sensor_bias_c: float | None = Field(None, ge=-30, le=30)  # °C
    stuck_position_pct: float | None = Field(None, ge=0, le=100)  # %
    leak_area_mm2: float | None = Field(None, ge=5, le=200)  # mm² (furo de ~2,5 a 16 mm)
    start_t_sim_s: float = Field(0.0, ge=0)  # s

    @model_validator(mode="after")
    def _params(self) -> Self:
        own = _DEFECT_PARAMS[self.kind.value]
        for name in own:
            if getattr(self, name) is None:
                raise ValueError(f"{name} obrigatório para {self.kind.value}")
        others = {n for params in _DEFECT_PARAMS.values() for n in params} - set(own)
        extra = sorted(n for n in others if getattr(self, n) is not None)
        if extra:
            raise ValueError(f"{self.kind.value} não aceita {', '.join(extra)}")
        return self

    def to_physics_fault(self) -> PhysicsFault:
        """Converte para ``PhysicsFault`` (simulation-bus 4.8; D-18 do data-model)."""
        if self.kind == DefectKind.IAT_SENSOR_BIAS:
            return PhysicsFault(
                kind="sensor_bias",
                sensor_channel="iat_c",
                sensor_bias=self.sensor_bias_c,
                start_t_sim_s=self.start_t_sim_s,
            )
        if self.kind == DefectKind.FUEL_PUMP_WEAK:
            return PhysicsFault(
                kind="fuel_pump_weak",
                fuel_pump_max_lph=self.fuel_pump_max_lph,
                start_t_sim_s=self.start_t_sim_s,
            )
        if self.kind == DefectKind.INJECTOR_CLOGGED:
            return PhysicsFault(
                kind="injector_clogged",
                cylinder=self.cylinder,
                injector_flow_factor=self.injector_flow_factor,
                start_t_sim_s=self.start_t_sim_s,
            )
        if self.kind == DefectKind.BOOST_LEAK:
            return PhysicsFault(
                kind="boost_leak",
                leak_area_mm2=self.leak_area_mm2,
                start_t_sim_s=self.start_t_sim_s,
            )
        return PhysicsFault(
            kind="wastegate_stuck",
            stuck_position_pct=self.stuck_position_pct,
            start_t_sim_s=self.start_t_sim_s,
        )


def _hash_stable(data: dict[str, Any], key: str) -> dict[str, Any]:
    """Tira ``leak_area_mm2`` vazio do defeito em ``data[key]`` (campo novo da 002).

    Mantém o ``scenario_sha256`` e o ``evaluation_sha256`` calculados antes do
    ``boost_leak``: pacotes e avaliações antigos continuam a conferir.
    """
    defect = data.get(key)
    if isinstance(defect, dict) and defect.get("leak_area_mm2", 0) is None:
        del defect["leak_area_mm2"]
    return data


# --------------------------------------------------------------------------- cenário


class InitialCalibration(ContractModel):
    source: Literal["vehicle_stock", "embedded"]
    payload: dict[str, Any] | None = None  # Calibration sem metadados (embedded)
    content_hash: Sha256Hex  # hash canônico do ecu-core

    @model_validator(mode="after")
    def _check(self) -> Self:
        if (self.source == "embedded") != (self.payload is not None):
            raise ValueError("payload é obrigatório só em source = 'embedded'")
        return self


class HintUnlock(ContractModel):
    after_failed_submissions: int | None = Field(None, ge=1, le=5)
    after_sim_time_s: float | None = Field(None, ge=0, le=36000)  # s
    after_event: Literal["knock_retard", "engine_failed", "egt_limit", "invalid_run"] | None = None

    @property
    def free(self) -> bool:
        """Dica livre (sem condição de desbloqueio)."""
        return (
            self.after_failed_submissions is None
            and self.after_sim_time_s is None
            and self.after_event is None
        )


class Hint(ContractModel):
    order: int = Field(ge=1, le=5)
    text: str = Field(min_length=1, max_length=500)
    unlock: HintUnlock = Field(default_factory=HintUnlock)  # tudo None ⇒ livre


RunTypeAllowed = Literal["baseline_pull", "sweep_pull", "multi_pull"]


def _all_run_types() -> list[RunTypeAllowed]:
    return ["baseline_pull", "sweep_pull", "multi_pull"]


class ScenarioConstraints(ContractModel):
    allowed_run_types: list[RunTypeAllowed] = Field(default_factory=_all_run_types, min_length=1)
    gear: int = Field(4, ge=1, le=10)
    allowed_final_profiles: list[str] = Field(default_factory=list)  # EcuProfileId
    swap_allowed: bool = False
    locked_table_ids: list[str] = Field(default_factory=list)
    max_submissions: int = Field(5, ge=1, le=20)
    time_limit_min: int | None = Field(None, ge=10, le=600)  # min
    operator_protection: bool = False

    @model_validator(mode="after")
    def _check(self) -> Self:
        unknown = sorted(set(self.allowed_final_profiles) - set(PROFILE_IDS))
        if unknown:
            raise ValueError(f"constraints.allowed_final_profiles com perfis inválidos: {unknown}")
        return self


class CriterionKind(SimStrEnum):
    MIN_WHP = "min_whp"
    MIN_DELTA_WHP = "min_delta_whp"
    MIN_TORQUE_NM = "min_torque_nm"
    MAX_KNOCK_RETARD_DEG = "max_knock_retard_deg"
    MIN_KNOCK_MARGIN_DEG = "min_knock_margin_deg"
    INTEGRITY = "integrity"
    MAX_EGT_C = "max_egt_c"
    MAX_EGT_OVERRUN_C = "max_egt_overrun_c"
    LAMBDA_WOT_MAX = "lambda_wot_max"
    LAMBDA_WOT_MIN = "lambda_wot_min"
    MIN_POP_EVENTS = "min_pop_events"
    VALID_PULLS = "valid_pulls"
    MAX_SPREAD_PCT = "max_spread_pct"
    FINAL_PROFILE = "final_profile"
    LOCKED_TABLES = "locked_tables"
    DEFECT_DIAGNOSIS = "defect_diagnosis"


Comparator = Literal["ge", "le", "bool"]


class Criterion(ContractModel):
    criterion_id: Slug
    kind: CriterionKind
    comparator: Comparator
    threshold: float | None = None  # unidade do kind (whp, N·m, °, °C, λ, %, contagem)
    band: float | None = Field(None, gt=0)  # só "le"; None ⇒ banda padrão
    weight: float = Field(1.0, gt=0, le=10)
    mandatory: bool = True

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.comparator in ("ge", "le") and self.threshold is None:
            raise ValueError(f"criteria.{self.criterion_id}: threshold obrigatório em ge/le")
        if self.band is not None and self.comparator != "le":
            raise ValueError(f"criteria.{self.criterion_id}: band só em comparator 'le'")
        if self.kind == CriterionKind.MIN_KNOCK_MARGIN_DEG and (
            self.threshold is None
            or not KNOCK_MARGIN_MIN_DEG <= self.threshold <= KNOCK_MARGIN_MAX_DEG
        ):
            raise ValueError(f"criteria.{self.criterion_id}: min_knock_margin_deg entre 0,5 e 6°")
        return self


class ChallengeCriteria(ContractModel):
    criteria: list[Criterion] = Field(min_length=1, max_length=20)
    required_valid_pulls: int = Field(2, ge=1, le=10)
    min_end_rpm: float | None = Field(None, ge=1500, le=12000)  # rev/min
    lambda_window_min_rpm: float = Field(3000, ge=1000, le=10000)  # rev/min
    require_defect_diagnosis: bool = False

    @model_validator(mode="after")
    def _check(self) -> Self:
        ids = [c.criterion_id for c in self.criteria]
        if len(set(ids)) != len(ids):
            raise ValueError("criteria com criterion_id duplicado")
        return self

    @property
    def has_defect_diagnosis(self) -> bool:
        return self.require_defect_diagnosis or any(
            c.kind == CriterionKind.DEFECT_DIAGNOSIS for c in self.criteria
        )


class Scenario(ContractModel):
    scenario_id: Slug
    kind: Literal["base", "challenge"]
    title: str = Field(min_length=3, max_length=80)
    briefing: str = Field(max_length=4000)
    vehicle_id: VehicleId
    initial_profile_id: Literal["oem-stage", "ft-pro", "m1-race", "ht-elite"] = "oem-stage"
    initial_calibration: InitialCalibration
    fuel_id: FuelId  # FuelSpec do vehicle-catalog
    ambient: AmbientConditions = Field(default_factory=AmbientConditions)
    correction_standard: CorrectionStandard = CorrectionStandard.SAE_J1349
    seed: int | None = Field(None, ge=0, le=2**63 - 1)  # None ⇒ derivada do attempt_id
    objectives: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        min_length=1, max_length=10
    )
    constraints: ScenarioConstraints = Field(default_factory=ScenarioConstraints)
    criteria: ChallengeCriteria
    hidden_defect: HiddenDefect | None = None
    hints: list[Hint] = Field(default_factory=list, max_length=5)
    author_nickname: Nickname | None = None
    scenario_sha256: Sha256Hex | None = None  # calculado pelo servidor
    builtin: bool = False
    origin: Literal["builtin", "local", "imported"] = "local"
    created_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.criteria.has_defect_diagnosis and self.hidden_defect is None:
            raise ValueError("defect_diagnosis exige hidden_defect")
        orders = sorted(h.order for h in self.hints)
        if orders != list(range(1, len(orders) + 1)):
            raise ValueError("hints.order deve ser 1..n sem repetição")
        if self.builtin != (self.origin == "builtin"):
            raise ValueError("builtin = true só com origin = 'builtin'")
        if self.builtin and self.kind != "base":
            raise ValueError("cenários builtin são do kind 'base'")
        return self

    def evaluable_content(self) -> dict[str, Any]:
        """Conteúdo avaliável para ``scenario_sha256`` (sem ``created_at``, ``builtin``,
        ``origin`` e o próprio hash)."""
        data = self.model_dump(
            mode="json", exclude={"created_at", "builtin", "origin", "scenario_sha256"}
        )
        return _hash_stable(data, "hidden_defect")

    def for_student(self) -> Scenario:
        """Cópia sem ``hidden_defect`` (E-34 para perfil student)."""
        return self.model_copy(update={"hidden_defect": None})


# --------------------------------------------------------------------------- tentativa


class AttemptState(SimStrEnum):
    PREPARING = "preparing"
    IN_PROGRESS = "in_progress"
    EVALUATING = "evaluating"
    PASSED = "passed"
    FAILED_FINAL = "failed_final"
    ABANDONED = "abandoned"
    EXPIRED = "expired"
    FAILED_TO_START = "failed_to_start"


class AttemptRun(ContractModel):
    run_id: str = Field(min_length=1, max_length=36)  # FK lógica (importadas: outra estação)
    run_type: str = Field(min_length=1, max_length=24)
    pull_index: int = Field(0, ge=0)  # 0 = puxada única (D-12)
    valid: bool
    invalid_reason: str | None = Field(None, max_length=48)
    calibration_hash: Sha256Hex | None = None
    peak_whp: float | None = None  # whp

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.valid and self.invalid_reason is not None:
            raise ValueError("invalid_reason só em puxada inválida")
        return self


class Attempt(ContractModel):
    attempt_id: UuidText
    scenario_id: Slug
    scenario_sha256: Sha256Hex
    profile_id: UuidText | None  # perfil de jogador (D-11); None em tentativa importada
    nickname: Nickname
    origin: Literal["local", "imported"] = "local"
    state: AttemptState
    session_id: str | None = Field(None, max_length=36)
    calibration_id: str = Field(min_length=1, max_length=64)
    seed: int = Field(ge=0, le=2**63 - 1)
    baseline_run_id: str | None = Field(None, max_length=36)
    baseline_peak_whp: float | None = None  # whp
    runs: list[AttemptRun] = Field(default_factory=list)
    submissions: int = Field(0, ge=0)
    hints_revealed: list[Annotated[int, Field(ge=1, le=5)]] = Field(default_factory=list)
    engine_restores: int = Field(0, ge=0)
    replay_status: ReplayStatus = "not_run"
    started_at: AwareDatetime

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.origin == "local" and self.profile_id is None:
            raise ValueError("tentativa local exige profile_id")
        if len(set(self.hints_revealed)) != len(self.hints_revealed):
            raise ValueError("hints_revealed com repetição")
        return self


class SubmitRequest(ContractModel):
    calibration_id: str = Field(min_length=1, max_length=64)
    run_ids: list[str] | None = Field(None, max_length=10)
    declared_defect: DefectKind | Literal["none"] | None = None


class Evidence(ContractModel):
    run_id: str = Field(min_length=1, max_length=36)
    log_id: str | None = Field(None, max_length=36)
    channel: str = Field(min_length=1, max_length=48)  # ex.: egt_pre_turbo_c
    t_sim_s: float | None = Field(None, ge=0)  # s
    rpm: float | None = None  # rev/min
    cylinder: int | None = Field(None, ge=1, le=8)
    value: float | None = None
    url: str = Field(min_length=1, max_length=200)  # /api/v1/runs/{run_id}/log?format=json


class CriterionResult(ContractModel):
    criterion_id: Slug
    kind: CriterionKind
    comparator: Comparator
    measured: float | None
    threshold: float | None
    passed: bool
    score: float = Field(ge=0, le=100)
    weight: float = Field(gt=0, le=10)
    mandatory: bool
    evidence: list[Evidence] = Field(default_factory=list, max_length=10)


class Evaluation(ContractModel):
    evaluation_id: UuidText
    attempt_id: UuidText
    submission_index: int = Field(ge=1)
    status: Literal["pending", "completed", "error"]
    error_code: str | None = None  # só em status = error (D-REST-09)
    evaluator_version: str = Field(pattern=SEMVER_PATTERN)
    passed: bool | None = None
    total_score: float | None = Field(None, ge=0, le=100)
    results: list[CriterionResult] = Field(default_factory=list)
    evidence_run_ids: list[str] = Field(default_factory=list)
    ignored_runs: list[str] = Field(default_factory=list)
    calibration_content_hash: Sha256Hex | None = None
    probe_run_sha256: Sha256Hex | None = None
    hints_revealed: list[int] = Field(default_factory=list)
    revealed_defect: HiddenDefect | None = None
    evaluation_sha256: Sha256Hex | None = None  # JCS sem evaluation_id e created_at
    created_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.status == "error":
            if self.error_code not in EVALUATION_ERROR_CODES:
                raise ValueError(f"error_code deve ser um de {sorted(EVALUATION_ERROR_CODES)}")
        elif self.error_code is not None:
            raise ValueError("error_code só em status = 'error'")
        if self.status == "completed" and (self.passed is None or self.total_score is None):
            raise ValueError("avaliação completed exige passed e total_score")
        if self.status == "pending" and (self.passed is not None or self.results):
            raise ValueError("avaliação pending não tem resultado")
        return self

    def hashable_content(self) -> dict[str, Any]:
        """Conteúdo de ``evaluation_sha256`` (sem ``evaluation_id``, ``created_at`` e o hash)."""
        data = self.model_dump(
            mode="json", exclude={"evaluation_id", "created_at", "evaluation_sha256"}
        )
        return _hash_stable(data, "revealed_defect")


# --------------------------------------------------------------------------- pacotes


class PackageProducer(ContractModel):
    app_version: str = Field(min_length=1, max_length=32)
    install_id: UuidText  # UUID4 local de app_meta, sem relação com pessoa
    nickname: Nickname | None = None


class SignedPackage(ContractModel):
    format_version: int = Field(PACKAGE_FORMAT_VERSION, ge=1)  # PACKAGE_FORMAT_VERSION
    kind: Literal["challenge", "attempt"]
    created_at: AwareDatetime  # fora do hash
    producer: PackageProducer  # fora do hash
    payload: dict[str, Any]
    sha256: Sha256Hex  # JCS de {format_version, kind, payload}
    hmac_sha256: str | None = None  # reservado (OQ-02); ignorado no MVP

    def hashable_content(self) -> dict[str, Any]:
        """Objeto canonicalizado por JCS (RFC 8785) para o ``sha256``."""
        return {"format_version": self.format_version, "kind": self.kind, "payload": self.payload}

    @property
    def supported(self) -> bool:
        """``False`` para formatos futuros (422 ``PACKAGE_FORMAT_UNSUPPORTED``)."""
        return self.format_version <= PACKAGE_FORMAT_VERSION


class PackageExportRequest(ContractModel):
    kind: Literal["challenge", "attempt"]
    scenario_id: Slug | None = None  # kind challenge
    attempt_id: UuidText | None = None  # kind attempt
    include_full_logs: bool = False

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.kind == "challenge" and (self.scenario_id is None or self.attempt_id is not None):
            raise ValueError("kind 'challenge' exige só scenario_id")
        if self.kind == "attempt" and (self.attempt_id is None or self.scenario_id is not None):
            raise ValueError("kind 'attempt' exige só attempt_id")
        return self


class PackageImportResult(ContractModel):
    package_sha256: Sha256Hex
    kind: Literal["challenge", "attempt"]
    scenario_id: Slug
    attempt_id: UuidText | None = None
    already_imported: bool = False
    evaluation_mismatch: bool = False
    recomputed_evaluation: Evaluation | None = None


class ScenarioCreate(ContractModel):
    scenario: Scenario
    initial_calibration_id: str | None = Field(None, min_length=1, max_length=64)


class ScenarioSummary(ContractModel):
    scenario_id: Slug
    kind: Literal["base", "challenge"]
    title: str
    vehicle_id: VehicleId
    fuel_id: FuelId
    has_hidden_defect: bool
    available: bool = True
    last_evaluation_passed: bool | None = None  # do perfil indicado no cabeçalho


class ScenarioView(Scenario):
    """Resposta de E-33/E-34: ``Scenario`` (defeito redigido para aluno) + ``has_hidden_defect``."""

    has_hidden_defect: bool = False


class AttemptView(Attempt):
    """Resposta de E-36 a E-40: ``Attempt`` com progresso, última avaliação e dados da turma."""

    scenario_title: str = ""
    max_submissions: int = Field(5, ge=1, le=20)
    hints_total: int = Field(0, ge=0, le=5)
    failure_code: str | None = None  # BASELINE_FAILED em failed_to_start
    progress: list[CriterionResult] = Field(default_factory=list)  # valores provisórios
    last_evaluation: Evaluation | None = None
    evaluation_mismatch: bool = False
    producer_install_id: UuidText | None = None  # só importadas
    package_sha256: Sha256Hex | None = None  # só importadas
    imported_at: AwareDatetime | None = None
    replay_mismatch_run_ids: list[str] = Field(default_factory=list)


class AttemptPage(ContractModel):
    items: list[AttemptView]
    next_cursor: str | None = None


class HintReveal(ContractModel):
    order: int = Field(ge=1, le=5)
    text: str = Field(min_length=1, max_length=500)
    remaining: int = Field(ge=0, le=4)


class SubmitAccepted(ContractModel):
    attempt_id: UuidText
    submission_index: int = Field(ge=1)
    evaluation_status: Literal["pending"] = "pending"


class ReplayAccepted(ContractModel):
    attempt_id: UuidText
    replay_status: Literal["running"] = "running"
    runs_to_replay: int = Field(ge=0)


class ScenarioStats(ContractModel):
    scenario_id: Slug
    started: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed_final: int = Field(ge=0)
    abandoned: int = Field(ge=0)
    completion_rate_pct: float | None = Field(ge=0, le=100)  # None se started = 0
    median_submissions_to_pass: float | None = Field(ge=0)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.passed + self.failed_final + self.abandoned > self.started:
            raise ValueError("passed + failed_final + abandoned não pode exceder started")
        if (self.started == 0) != (self.completion_rate_pct is None):
            raise ValueError("completion_rate_pct é None só quando started = 0")
        return self
