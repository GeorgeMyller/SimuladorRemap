"""Catálogo único de códigos de erro e o formato ``ProblemDetail`` (RFC 7807/9457).

Fontes: ``platform-foundation`` RF-05, RF-06; ``contracts/rest-api.md`` seções 2 e 4.

Como um componente regista os seus códigos
-----------------------------------------
Crie ``simremap/<pacote>/errors.py`` e, no topo do módulo, chame
``register_error(code, status, title)`` ou declare subclasses de ``SimRemapError``
com ``code``, ``status`` e ``title`` (o registo é automático em ``__init_subclass__``)::

    from simremap.core.errors import SimRemapError, register_error

    register_error("VEHICLE_NOT_FOUND", 404, "Veículo não encontrado")

    class VehicleNotFound(SimRemapError):
        code = "VEHICLE_NOT_FOUND"
        status = 404
        title = "Veículo não encontrado"

O módulo é carregado no arranque por ``load_component_errors()`` a partir da lista
estática ``COMPONENT_ERROR_MODULES`` (módulos ainda inexistentes são ignorados).
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, ClassVar, Final

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CODE_PATTERN",
    "COMPONENT_ERROR_MODULES",
    "PROBLEM_JSON",
    "PROBLEM_TYPE_PREFIX",
    "RETIRED_CODES",
    "ErrorCodeConflict",
    "ErrorCodeInvalid",
    "ErrorSpec",
    "FieldError",
    "ProblemDetail",
    "SimRemapError",
    "catalog",
    "catalog_sha256",
    "get_error",
    "is_registered",
    "load_component_errors",
    "problem_type",
    "register_error",
]

PROBLEM_JSON: Final = "application/problem+json"
PROBLEM_TYPE_PREFIX: Final = "urn:simremap:problem:"
CODE_PATTERN: Final = r"^[A-Z][0-9A-Z_]{2,63}$"
_CODE_RE: Final = re.compile(CODE_PATTERN)

RETIRED_CODES: Final = frozenset(
    {
        "VALIDATION_ERROR",
        "RUN_ALREADY_ACTIVE",
        "CALIBRATION_REVISION_CONFLICT",
        "TABLE_LOCKED_DURING_RUN",
        "STORAGE_UNAVAILABLE",
    }
)
"""Códigos aposentados (rest-api 4.10, D-13 a D-16): nunca podem ser registados."""

COMPONENT_ERROR_MODULES: Final[tuple[str, ...]] = (
    "simremap.catalog.errors",
    "simremap.physics.errors",
    "simremap.dyno.errors",
    "simremap.damage.errors",
    "simremap.ecu.errors",
    "simremap.profiles.errors",
    "simremap.telemetry.errors",
    "simremap.scenarios.errors",
)
"""Ponto de registo fixo: um módulo ``errors`` por componente de backend."""


class ErrorCodeConflict(RuntimeError):
    """O mesmo ``code`` foi registado duas vezes com status HTTP diferente."""


class ErrorCodeInvalid(ValueError):
    """``code`` fora do padrão, status inválido ou código aposentado."""


@dataclass(frozen=True, slots=True)
class ErrorSpec:
    """Entrada do catálogo: ``code`` → status HTTP fixo e título curto em pt-BR."""

    code: str
    status: int
    title: str

    @property
    def type(self) -> str:
        return problem_type(self.code)


_CATALOG: dict[str, ErrorSpec] = {}


def problem_type(code: str) -> str:
    """``urn:simremap:problem:`` + ``code`` em minúsculas com ``_`` trocado por ``-``."""
    return PROBLEM_TYPE_PREFIX + code.lower().replace("_", "-")


def register_error(code: str, status: int, title: str) -> ErrorSpec:
    """Regista ``code`` no catálogo único.

    Repetir o registo com o mesmo status é idempotente (devolve a entrada existente).
    Status diferente lança ``ErrorCodeConflict``; padrão inválido, status fora de
    400–599, título vazio ou com mais de 120 caracteres e código aposentado lançam
    ``ErrorCodeInvalid``.
    """
    if not _CODE_RE.fullmatch(code):
        raise ErrorCodeInvalid(f"code {code!r} não casa com {CODE_PATTERN}")
    if code in RETIRED_CODES:
        raise ErrorCodeInvalid(f"code {code!r} está aposentado e não pode ser registado")
    if not 400 <= status <= 599:  # noqa: PLR2004 - faixa HTTP de erro
        raise ErrorCodeInvalid(f"status {status} do code {code!r} fora de 400–599")
    if not title or len(title) > 120:  # noqa: PLR2004 - limite do ProblemDetail.title
        raise ErrorCodeInvalid(f"title do code {code!r} deve ter 1 a 120 caracteres")
    existing = _CATALOG.get(code)
    if existing is not None:
        if existing.status != status:
            raise ErrorCodeConflict(
                f"code {code!r} já registado com status {existing.status}; "
                f"novo registo pede {status}"
            )
        return existing
    spec = ErrorSpec(code=code, status=status, title=title)
    _CATALOG[code] = spec
    return spec


def get_error(code: str) -> ErrorSpec:
    """Devolve a entrada de ``code``; ``KeyError`` se não estiver registado."""
    return _CATALOG[code]


def is_registered(code: str) -> bool:
    return code in _CATALOG


def catalog() -> Mapping[str, ErrorSpec]:
    """Vista só de leitura do catálogo atual."""
    return MappingProxyType(_CATALOG)


def catalog_sha256() -> str:
    """SHA-256 estável do catálogo (ordenado por ``code``), exposto em ``/api/v1/version``."""
    payload = [[s.code, s.status, s.title] for s in sorted(_CATALOG.values(), key=lambda s: s.code)]
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_component_errors(modules: tuple[str, ...] = COMPONENT_ERROR_MODULES) -> list[str]:
    """Importa os módulos ``errors`` dos componentes; ignora os que ainda não existem.

    Só um ``ModuleNotFoundError`` do próprio módulo (ou do seu pacote) é ignorado; um
    erro de import dentro de um módulo existente propaga-se para falhar o arranque.
    """
    loaded: list[str] = []
    for name in modules:
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as exc:
            missing = exc.name or ""
            if missing == name or name.startswith(missing + "."):
                continue
            raise
        loaded.append(name)
    return loaded


# --------------------------------------------------------------------------- modelos


class FieldError(BaseModel):
    """Erro de um campo num 422 ``VALIDATION_FAILED``."""

    model_config = ConfigDict(frozen=True)

    loc: list[str | int]
    msg: str
    type: str


class ProblemDetail(BaseModel):
    """Corpo ``application/problem+json`` de todas as respostas de erro."""

    model_config = ConfigDict(extra="allow", frozen=True)

    type: str = Field(..., examples=["urn:simremap:problem:vehicle-not-found"])
    title: str = Field(..., max_length=120)
    status: int = Field(..., ge=400, le=599)
    detail: str = Field(..., max_length=2000)
    code: str = Field(..., pattern=CODE_PATTERN)
    request_id: str = Field(..., max_length=64)
    instance: str | None = None
    errors: list[FieldError] | None = None


# --------------------------------------------------------------------------- exceção


class SimRemapError(Exception):
    """Base das exceções de domínio convertidas em ``ProblemDetail``.

    Uso por subclasse (registo automático)::

        class SessionNotFound(SimRemapError):
            code = "SESSION_NOT_FOUND"; status = 404; title = "Sessão não encontrada"

        raise SessionNotFound("A sessão abc não existe.", session_id="abc")

    Uso direto com um ``code`` já registado::

        raise SimRemapError("Fila cheia.", code="SIM_WORKER_BUSY")

    ``extra`` vira campos adicionais do ``ProblemDetail`` (``extra="allow"``);
    ``headers`` vai para a resposta HTTP (ex.: ``{"Retry-After": "2"}``).
    """

    code: ClassVar[str] = "INTERNAL_ERROR"
    status: ClassVar[int] = 500
    title: ClassVar[str] = "Erro interno"

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "code" in cls.__dict__:
            register_error(cls.code, cls.status, cls.title)

    def __init__(
        self,
        detail: str,
        *,
        code: str | None = None,
        headers: Mapping[str, str] | None = None,
        **extra: object,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        if code is not None:
            spec = get_error(code)
            self.error_code = spec.code
            self.error_status = spec.status
            self.error_title = spec.title
        else:
            self.error_code = type(self).code
            self.error_status = type(self).status
            self.error_title = type(self).title
        self.headers: dict[str, str] = dict(headers or {})
        self.extra: dict[str, object] = dict(extra)

    def to_problem(self, request_id: str, instance: str | None = None) -> ProblemDetail:
        data: dict[str, object] = {
            **self.extra,
            "type": problem_type(self.error_code),
            "title": self.error_title,
            "status": self.error_status,
            "detail": self.detail[:2000],
            "code": self.error_code,
            "request_id": request_id[:64],
            "instance": instance,
        }
        return ProblemDetail.model_validate(data)


# --------------------------------------------------------------------------- catálogo da fundação

_FOUNDATION_CODES: Final[tuple[tuple[str, int, str], ...]] = (
    ("VALIDATION_FAILED", 422, "Pedido inválido"),
    ("ROUTE_NOT_FOUND", 404, "Rota não encontrada"),
    ("RESOURCE_NOT_FOUND", 404, "Recurso não encontrado"),
    ("METHOD_NOT_ALLOWED", 405, "Método não permitido"),
    ("PAYLOAD_TOO_LARGE", 413, "Corpo do pedido grande demais"),
    ("UNSUPPORTED_MEDIA_TYPE", 415, "Tipo de conteúdo não suportado"),
    ("CONFLICT", 409, "Conflito de estado"),
    ("INTERNAL_ERROR", 500, "Erro interno"),
    ("SERVICE_UNAVAILABLE", 503, "Serviço indisponível"),
    ("DATABASE_UNAVAILABLE", 503, "Banco de dados indisponível"),
    ("SIM_WORKER_UNAVAILABLE", 503, "Worker de simulação indisponível"),
    ("SIM_WORKER_BUSY", 503, "Worker de simulação ocupado"),
    ("SIM_CAPACITY_EXCEEDED", 409, "Limite de sessões ativas atingido"),
    ("STORAGE_FULL", 507, "Armazenamento cheio"),
    ("STATIC_NOT_BUILT", 404, "Build do frontend ausente"),
)

for _code, _status, _title in _FOUNDATION_CODES:
    register_error(_code, _status, _title)

FOUNDATION_CODES: Final = frozenset(code for code, _, _ in _FOUNDATION_CODES)
