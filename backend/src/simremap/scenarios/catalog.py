"""Catálogo de cenários: base embutidos, desafios do instrutor e ``scenario_sha256``
(training-scenarios RF-04 a RF-06; D-11; premissa OQ-06).

- ``scenario_sha256(scenario)`` = SHA-256 do JCS (RFC 8785) do conteúdo avaliável (tudo
  menos ``created_at``, ``builtin``, ``origin`` e o próprio hash). Reordenar chaves não muda o
  hash; mudar 1 limiar muda.
- ``builtin/*.json``: ``stage1-oem``, ``stage2-pops-bangs`` e ``standalone-swap``
  (``min_whp = 300`` absolutos, OQ-06) e os 4 de diagnóstico com defeito oculto (002 D-14):
  ``defect-fuel-pump``, ``defect-boost-leak``, ``defect-lean-injector`` e
  ``defect-wastegate-stuck`` (kind ``base``, contam na taxa de conclusão). O
  ``initial_calibration.content_hash`` da calibração de série é preenchido no arranque
  pela rota do clone (``compute_content_hash(parse_content(stock.content))``, D-01), para
  coincidir com a cópia clonada pela tentativa; ``resync_builtin_hash`` corrige-o em tempo
  de execução (D-02).
  Veículo ausente ⇒ cenário não carregado (log ``scenarios.builtin_skipped``).
- Desafios (``POST /api/v1/scenarios``): regras adicionais da seção 9 (comparador por
  ``kind``, combustível do veículo, ``wastegate_stuck`` atrás de
  ``SIMREMAP_FEATURE_DEFECT_WASTEGATE``); violação ⇒ 422 ``SCENARIO_INVALID``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from importlib import resources
from typing import Any, Final

from pydantic import ValidationError

from simremap.core.errors import SimRemapError
from simremap.core.logging import get_logger
from simremap.db.base import utcnow
from simremap.scenarios.contracts import (
    CriterionKind,
    DefectKind,
    PlayerProfile,
    Scenario,
    ScenarioCreate,
    ScenarioSummary,
)
from simremap.scenarios.errors import scenario_error
from simremap.scenarios.evaluator import KIND_COMPARATOR
from simremap.scenarios.jcs import jcs_sha256
from simremap.scenarios.ports import CalibrationPort, CalibrationRecord
from simremap.scenarios.repository import ScenarioRepository

__all__ = [
    "BUILTIN_IDS",
    "ScenarioCatalog",
    "VehicleInfo",
    "builtin_documents",
    "example_challenge",
    "scenario_sha256",
    "validate_rules",
    "with_hash",
]

log = get_logger("simremap.scenarios")

BUILTIN_IDS: Final[tuple[str, ...]] = (
    "stage1-oem",
    "stage2-pops-bangs",
    "standalone-swap",
    "defect-fuel-pump",
    "defect-boost-leak",
    "defect-lean-injector",
    "defect-wastegate-stuck",
)
_PACKAGE: Final = "simremap.scenarios.builtin"


def scenario_sha256(scenario: Scenario) -> str:
    """SHA-256 hex do JCS do conteúdo avaliável (RF-06)."""
    return jcs_sha256(scenario.evaluable_content())


def with_hash(scenario: Scenario) -> Scenario:
    return scenario.model_copy(update={"scenario_sha256": scenario_sha256(scenario)})


def builtin_documents() -> dict[str, dict[str, Any]]:
    """JSON embutidos dos cenários base (sem o ``content_hash`` da calibração)."""
    root = resources.files(_PACKAGE)
    return {
        sid: json.loads(root.joinpath(f"{sid}.json").read_text(encoding="utf-8"))
        for sid in BUILTIN_IDS
    }


def example_challenge() -> dict[str, Any]:
    """Desafio de exemplo do instrutor: 400 whp com E27 e EGT ≤ 900 °C no ``coupe-30t-i6``."""
    path = resources.files(_PACKAGE).joinpath("examples/challenge-400whp-e27.json")
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


class VehicleInfo:
    """Visão do vehicle-catalog usada pelos cenários (``rev_limit_rpm``, combustíveis)."""

    def __init__(
        self,
        vehicle_id: str,
        rev_limit_rpm: float,
        fuels: tuple[str, ...],
        stock_profile_id: str,
        validated: bool,
        factory_content_hash: Callable[[str], str | None],
    ) -> None:
        self.vehicle_id = vehicle_id
        self.rev_limit_rpm = rev_limit_rpm
        self.fuels = fuels
        self.stock_profile_id = stock_profile_id
        self.validated = validated
        self.factory_content_hash = factory_content_hash


VehicleLookup = Callable[[str], VehicleInfo | None]


def catalog_vehicle(vehicle_id: str) -> VehicleInfo | None:
    """``VehicleInfo`` do catálogo real (``simremap.catalog.service.get_catalog``)."""
    from simremap.catalog.service import get_catalog
    from simremap.ecu.calibration import compute_content_hash, parse_content

    service = get_catalog()
    try:
        spec = service.get_vehicle(vehicle_id)
    except SimRemapError:
        return None

    def factory_hash(profile_id: str) -> str | None:
        try:
            payload = service.get_factory_calibration_payload(vehicle_id, profile_id)
            content = parse_content({**payload, "vehicle_id": vehicle_id, "profile_id": profile_id})
        except Exception:
            return None
        return compute_content_hash(content)

    status = getattr(spec, "validation_status", "validated")
    return VehicleInfo(
        vehicle_id=vehicle_id,
        rev_limit_rpm=float(spec.mechanical_limits.rev_limit_rpm),
        fuels=tuple(f.fuel_id for f in service.allowed_fuels(vehicle_id)),
        stock_profile_id=str(spec.stock_profile_id),
        validated=status == "validated",
        factory_content_hash=factory_hash,
    )


def validate_rules(scenario: Scenario, vehicle: VehicleInfo, *, wastegate_enabled: bool) -> None:
    """Regras adicionais da seção 9 (422 ``SCENARIO_INVALID`` com o campo no ``detail``)."""
    for c in scenario.criteria.criteria:
        expected = KIND_COMPARATOR[c.kind]
        if c.comparator != expected:
            raise scenario_error(
                "SCENARIO_INVALID",
                f"criteria.{c.criterion_id}: kind {c.kind.value} exige comparator {expected!r}.",
                field=f"criteria.criteria.{c.criterion_id}.comparator",
            )
        if c.kind == CriterionKind.DEFECT_DIAGNOSIS and scenario.hidden_defect is None:
            raise scenario_error(
                "SCENARIO_INVALID",
                "defect_diagnosis exige hidden_defect.",
                field="hidden_defect",
            )
    if scenario.fuel_id not in vehicle.fuels:
        raise scenario_error(
            "SCENARIO_INVALID",
            f"fuel_id {scenario.fuel_id} não é permitido no veículo {vehicle.vehicle_id}.",
            field="fuel_id",
        )
    defect = scenario.hidden_defect
    if defect is not None and defect.kind == DefectKind.WASTEGATE_STUCK and not wastegate_enabled:
        raise scenario_error(
            "SCENARIO_INVALID",
            "defeito não suportado: wastegate_stuck desligado (SIMREMAP_FEATURE_DEFECT_WASTEGATE).",
            field="hidden_defect.kind",
        )
    if defect is not None and defect.cylinder is not None:
        from simremap.catalog.service import get_catalog

        try:
            n_cyl = get_catalog().get_vehicle(vehicle.vehicle_id).engine.n_cyl
        except SimRemapError:
            n_cyl = 8
        if defect.cylinder > n_cyl:
            raise scenario_error(
                "SCENARIO_INVALID",
                f"hidden_defect.cylinder {defect.cylinder} acima dos {n_cyl} cilindros.",
                field="hidden_defect.cylinder",
            )


class ScenarioCatalog:
    """Cenários base e desafios (repositório + catálogo de veículos + ecu-core)."""

    def __init__(
        self,
        repo: ScenarioRepository,
        calibrations: CalibrationPort,
        *,
        vehicles: VehicleLookup = catalog_vehicle,
        wastegate_enabled: Callable[[], bool] = lambda: True,
        profile_enabled: Callable[[str], bool] = lambda _p: True,
    ) -> None:
        self.repo = repo
        self.calibrations = calibrations
        self.vehicles = vehicles
        self.wastegate_enabled = wastegate_enabled
        self.profile_enabled = profile_enabled

    # ------------------------------------------------------------------ consulta
    def vehicle(self, vehicle_id: str) -> VehicleInfo:
        info = self.vehicles(vehicle_id)
        if info is None:
            raise SimRemapError(
                f"O veículo {vehicle_id} não existe.",
                code="VEHICLE_NOT_FOUND",
                vehicle_id=vehicle_id,
            )
        return info

    async def get(self, scenario_id: str) -> Scenario:
        scenario = await self.repo.get_scenario(scenario_id)
        if scenario is None:
            raise scenario_error(
                "SCENARIO_NOT_FOUND",
                f"O cenário {scenario_id} não existe.",
                scenario_id=scenario_id,
            )
        return scenario

    def available(self, scenario: Scenario) -> bool:
        info = self.vehicles(scenario.vehicle_id)
        if info is None or not info.validated:
            return False
        allowed = scenario.constraints.allowed_final_profiles
        if allowed and not any(self.profile_enabled(p) for p in allowed):
            return False
        defect = scenario.hidden_defect
        return not (
            defect is not None
            and defect.kind == DefectKind.WASTEGATE_STUCK
            and not self.wastegate_enabled()
        )

    async def summaries(
        self, kind: str | None, profile: PlayerProfile | None
    ) -> list[ScenarioSummary]:
        scenarios = await self.repo.list_scenarios(kind)
        last = {} if profile is None else await self.repo.last_passed_by_profile(profile.profile_id)
        return [
            ScenarioSummary(
                scenario_id=s.scenario_id,
                kind=s.kind,
                title=s.title,
                vehicle_id=s.vehicle_id,
                fuel_id=s.fuel_id,
                has_hidden_defect=s.hidden_defect is not None,
                available=self.available(s),
                last_evaluation_passed=last.get(s.scenario_id),
            )
            for s in scenarios
        ]

    # ------------------------------------------------------------------ calibração de série
    async def stock_hash(self, vehicle_id: str, profile_id: str) -> str | None:
        """``content_hash`` que o clone da calibração de série terá (D-01).

        Usa a rota do clone (``compute_content_hash(parse_content(content))``) e não o
        ``content_hash`` guardado na versão: o servidor recalcula o hash ao clonar e o hash
        guardado fica velho quando o ``CalibrationContent`` evolui. Sem série no banco (ou
        série ilegível no schema atual) ⇒ fábrica do catálogo, pela mesma rota.
        """
        record = await self.calibrations.stock(vehicle_id, profile_id)
        if record is not None:
            try:
                return self.calibrations.clone_hash(record)
            except ValueError:
                log.warning("scenarios.stock_unparseable", calibration_id=record.calibration_id)
        info = self.vehicles(vehicle_id)
        return None if info is None else info.factory_content_hash(profile_id)

    async def resync_builtin_hash(self, scenario_id: str, content_hash: str) -> Scenario:
        """Regrava o ``initial_calibration.content_hash`` de um builtin (D-02).

        Recalcula o ``scenario_sha256`` e grava por ``upsert_builtin``; devolve o cenário novo.
        """
        scenario = await self.get(scenario_id)
        if not scenario.builtin:
            raise scenario_error(
                "SCENARIO_INVALID",
                f"O cenário {scenario_id} não é builtin; o hash não é ressincronizado.",
                field="initial_calibration.content_hash",
            )
        initial = scenario.initial_calibration.model_copy(update={"content_hash": content_hash})
        updated = with_hash(scenario.model_copy(update={"initial_calibration": initial}))
        await self.repo.upsert_builtin([updated])
        return updated

    # ------------------------------------------------------------------ carga embutida
    async def load_builtin(self) -> dict[str, str]:
        """Carga idempotente dos cenários base (RF-04); devolve o desfecho por cenário."""
        loaded: list[Scenario] = []
        outcome: dict[str, str] = {}
        for sid, doc in builtin_documents().items():
            info = self.vehicles(doc["vehicle_id"])
            stock = (
                None
                if info is None
                else await self.stock_hash(
                    doc["vehicle_id"], doc.get("initial_profile_id", "oem-stage")
                )
            )
            if info is None or stock is None:
                log.warning(
                    "scenarios.builtin_skipped", scenario_id=sid, vehicle_id=doc["vehicle_id"]
                )
                outcome[sid] = "skipped"
                continue
            data = json.loads(json.dumps(doc))
            data["initial_calibration"]["content_hash"] = stock
            scenario = with_hash(Scenario.model_validate(data))
            validate_rules(scenario, info, wastegate_enabled=True)
            loaded.append(scenario)
        outcome.update(await self.repo.upsert_builtin(loaded))
        log.info("scenarios.builtin_loaded", outcome=outcome)
        return outcome

    # ------------------------------------------------------------------ desafios
    async def prepare_challenge(
        self, body: ScenarioCreate, author: PlayerProfile | None, *, origin: str = "local"
    ) -> Scenario:
        """Valida um desafio e devolve-o com o hash, a calibração inicial e a autoria."""
        scenario = body.scenario
        if scenario.builtin or scenario.kind != "challenge":
            raise scenario_error(
                "SCENARIO_INVALID",
                "Só é possível criar cenários do kind 'challenge'.",
                field="kind",
            )
        info = self.vehicle(scenario.vehicle_id)
        validate_rules(scenario, info, wastegate_enabled=self.wastegate_enabled())
        initial = await self._initial_calibration(scenario, body.initial_calibration_id)
        update: dict[str, Any] = {
            "initial_calibration": initial,
            "builtin": False,
            "origin": origin,
            "created_at": utcnow(),
            "scenario_sha256": None,
        }
        if author is not None:
            update["author_nickname"] = author.nickname
        try:
            prepared = Scenario.model_validate(
                {**scenario.model_dump(mode="json"), **_json(update)}
            )
        except ValidationError as exc:
            raise scenario_error("SCENARIO_INVALID", _first_error(exc)) from exc
        return with_hash(prepared)

    async def create(self, body: ScenarioCreate, author: PlayerProfile) -> Scenario:
        scenario = await self.prepare_challenge(body, author)
        return await self.repo.add_scenario(scenario)

    async def _initial_calibration(
        self, scenario: Scenario, calibration_id: str | None
    ) -> dict[str, Any]:
        if calibration_id is not None:
            record: CalibrationRecord = await self.calibrations.get(calibration_id)
            if record.vehicle_id != scenario.vehicle_id:
                raise scenario_error(
                    "SCENARIO_INVALID",
                    f"A calibração {calibration_id} é do veículo {record.vehicle_id}.",
                    field="initial_calibration_id",
                )
            if record.profile_id != scenario.initial_profile_id:
                raise scenario_error(
                    "SCENARIO_INVALID",
                    f"A calibração {calibration_id} é do perfil {record.profile_id}.",
                    field="initial_calibration_id",
                )
            return {
                "source": "embedded",
                "payload": record.content,
                "content_hash": record.content_hash,
            }
        initial = scenario.initial_calibration
        if initial.source == "embedded":
            return initial.model_dump(mode="json")
        stock = await self.stock_hash(scenario.vehicle_id, scenario.initial_profile_id)
        if stock is None:
            raise SimRemapError(
                f"Não há calibração de série para {scenario.vehicle_id}.",
                code="CALIBRATION_NOT_FOUND",
            )
        return {"source": "vehicle_stock", "payload": None, "content_hash": stock}


def _json(update: dict[str, Any]) -> dict[str, Any]:
    out = dict(update)
    created = out.get("created_at")
    if created is not None:
        out["created_at"] = created.isoformat()
    return out


def _first_error(exc: ValidationError) -> str:
    err = exc.errors()[0]
    loc = ".".join(str(p) for p in err.get("loc", ()))
    return f"{loc}: {err.get('msg', '')}"[:2000]
