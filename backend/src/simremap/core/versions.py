"""Constantes de versão expostas em ``GET /api/v1/version`` (platform-foundation RF-08, RF-21).

Regra de compatibilidade: leitores aceitam ``format_version`` menor ou igual ao valor
atual e recusam valores superiores com o ``code`` do componente dono (ex.:
``LOG_FORMAT_UNSUPPORTED``). Mudar a semântica de um campo exige incrementar o inteiro
E acrescentar a entrada correspondente em ``FORMAT_CHANGELOG`` (o teste de contrato
``tests/contract/test_versions.py`` falha se faltar).
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

__all__ = [
    "API_VERSION",
    "DATALOG_FORMAT_VERSION",
    "FORMAT_CHANGELOG",
    "PACKAGE_FORMAT_VERSION",
    "WS_ENVELOPE_VERSION",
    "alembic_head",
]

API_VERSION: Final = "v1"
WS_ENVELOPE_VERSION: Final = 1
PACKAGE_FORMAT_VERSION: Final = 1  # SignedPackage de training-scenarios
DATALOG_FORMAT_VERSION: Final = 1  # DataLog de telemetry-datalogger

FORMAT_CHANGELOG: Final[Mapping[str, Mapping[int, str]]] = MappingProxyType(
    {
        "api_version": MappingProxyType({1: "v1: prefixos /api/v1 e /ws/v1 (D-33)."}),
        "ws_envelope_version": MappingProxyType(
            {1: "Envelope {v, type, seq, t_sim_s, payload} (contracts/websocket-telemetry)."}
        ),
        "package_format_version": MappingProxyType(
            {1: "SignedPackage: sha256 JCS de {format_version, kind, payload}; sem HMAC."}
        ),
        "datalog_format_version": MappingProxyType(
            {1: "DataLog .simlog.gz: cabeçalho canônico + t_sim_s float64 + colunas float32."}
        ),
    }
)
"""Histórico dos formatos versionados: ``{constante: {versão: descrição}}``."""


def alembic_head() -> str:
    """Revisão head da cadeia Alembic em disco (igual a ``alembic heads``)."""
    from simremap.db.migrate import script_head  # noqa: PLC0415 - evita ciclo core → db

    return script_head()
