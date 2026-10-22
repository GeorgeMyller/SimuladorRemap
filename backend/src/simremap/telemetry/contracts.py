"""Contratos da telemetria e do datalogger (telemetry-datalogger seção 9;
contracts/websocket-telemetry.md; contracts/file-formats.md seção 4).

- WebSocket: ``WsEnvelope`` v1, ``WsClientMessage``, ``TelemetrySubscription``,
  ``TelemetryFrame`` (+ ``KnockSpectrum``, ``PressureTrace``, ``FrameStats``) e os payloads
  ``KnockEventPayload`` (união D-WS-02), ``LimiterEventPayload`` e ``WsErrorPayload``.
- Catálogo de canais: ``TelemetryChannel`` com ``Aggregation`` e ``ChannelKind``.
- Log: ``DataLogHeader``, ``DataLog``, ``DataLogSummary``, ``LogRef``,
  ``LogCompareRequest``, ``ComparisonBin`` e ``LogComparison``.
"""

from __future__ import annotations

import json
import re
from typing import Annotated, Any, Final, Literal, Self

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from simremap.core.contracts import ContractModel, Sha256Hex, SimStrEnum
from simremap.core.versions import DATALOG_FORMAT_VERSION, WS_ENVELOPE_VERSION

__all__ = [
    "CHANNEL_NAME_PATTERN",
    "DEFAULT_CHANNELS",
    "MAX_CLIENT_MESSAGE_BYTES",
    "MAX_IMPORT_CHANNELS",
    "SPECTRUM_BINS",
    "Aggregation",
    "ChannelKind",
    "ClientType",
    "ComparisonBin",
    "DataLog",
    "DataLogHeader",
    "DataLogSummary",
    "FrameStats",
    "KnockEventPayload",
    "KnockSpectrum",
    "LimiterEventPayload",
    "LogCompareRequest",
    "LogComparison",
    "LogEvent",
    "LogRef",
    "PressureTrace",
    "PullSegment",
    "TelemetryChannel",
    "TelemetryFrame",
    "TelemetrySubscription",
    "WsClientMessage",
    "WsEnvelope",
    "WsErrorPayload",
    "WsType",
    "channel_name",
    "split_cylinder_channel",
]

CHANNEL_NAME_PATTERN: Final = r"^[a-z][a-z0-9_]{1,47}$"
ERROR_CODE_PATTERN: Final = r"^[A-Z][0-9A-Z_]{2,63}$"
IMPORTED_LOG_ID_PATTERN: Final = r"^imp-[0-9a-f]{12}$"
SPECTRUM_BINS: Final = 256
RESONANCE_MODES: Final = 4
MAX_CLIENT_MESSAGE_BYTES: Final = 16 * 1024
MAX_SUBSCRIBED_CHANNELS: Final = 128
MAX_IMPORT_CHANNELS: Final = 256
MAX_CYLINDERS: Final = 8
DEFAULT_CHANNELS: Final[tuple[str, ...]] = ("rpm", "map_kpa", "lambda", "torque_nm", "power_kw")
"""Canais emitidos logo após o handshake, antes do primeiro ``control.subscribe``."""

_CYL_SUFFIX: Final = re.compile(r"^(?P<base>[a-z][a-z0-9_]*)_cyl(?P<k>[1-8])$")

WsType = Literal[
    "telemetry.frame", "run.state", "event.knock", "event.failure", "event.limiter", "error"
]
ClientType = Literal["control.subscribe", "control.throttle", "control.ping"]
TerminalState = Literal["completed", "aborted", "engine_failed"]
LogSource = Literal["simulated", "imported"]


def channel_name(base: str, cylinder: int | None = None) -> str:
    """Nome expandido do canal: ``<base>`` ou ``<base>_cyl<k>`` (k 1-based)."""
    return base if cylinder is None else f"{base}_cyl{cylinder}"


class Aggregation(SimStrEnum):
    LAST = "last"
    MAX = "max"
    MIN = "min"
    ANY = "any"
    SUM = "sum"


class ChannelKind(SimStrEnum):
    SCALAR = "scalar"
    FLAG = "flag"
    PER_CYLINDER = "per_cylinder"


class TelemetryChannel(ContractModel):
    """Item do catálogo de canais (E-26)."""

    name: str = Field(pattern=CHANNEL_NAME_PATTERN)  # nome expandido (ex.: egt_c_cyl3)
    base: str = Field(pattern=CHANNEL_NAME_PATTERN)  # nome base (ex.: egt_c)
    cylinder: int | None = Field(None, ge=1, le=MAX_CYLINDERS)
    unit: str = Field(max_length=16)  # "rpm", "kPa", "bar", "-", "°BTDC", "°C", "N·m", ...
    kind: ChannelKind
    aggregation: Aggregation
    decimals: int = Field(ge=0, le=4)  # arredondamento só no WS
    min_value: float | None = None
    max_value: float | None = None
    source: str = Field(max_length=120)  # ex.: "EngineState.p_max_kpa/100"
    nullable: bool = False  # ex.: turbo_rpm em aspirado

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.name != channel_name(self.base, self.cylinder):
            raise ValueError("name deve ser <base> ou <base>_cyl<k>")
        if (self.kind == ChannelKind.PER_CYLINDER) != (self.cylinder is not None):
            raise ValueError("cylinder é obrigatório só em canais per_cylinder")
        if self.kind == ChannelKind.FLAG and self.aggregation != Aggregation.ANY:
            raise ValueError("canais flag usam a agregação 'any'")
        if (
            self.min_value is not None
            and self.max_value is not None
            and self.max_value < self.min_value
        ):
            raise ValueError("max_value deve ser ≥ min_value")
        return self


# --------------------------------------------------------------------------- WebSocket


class WsEnvelope(ContractModel):
    """Envelope servidor → cliente (v1). ``seq`` é único por sessão e partilhado."""

    v: Literal[1] = WS_ENVELOPE_VERSION
    type: WsType
    seq: int = Field(ge=0)
    t_sim_s: float = Field(ge=0.0)  # s, tick de origem
    payload: dict[str, Any]

    @classmethod
    def wrap(cls, type_: WsType, seq: int, t_sim_s: float, payload: BaseModel) -> WsEnvelope:
        """Envelope com o ``payload`` serializado em modo JSON."""
        return cls(type=type_, seq=seq, t_sim_s=t_sim_s, payload=payload.model_dump(mode="json"))


class WsClientMessage(ContractModel):
    """Mensagem cliente → servidor (≤ 16 kB serializada)."""

    v: Literal[1] = WS_ENVELOPE_VERSION
    type: ClientType
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_size(self) -> Self:
        size = len(json.dumps(self.payload, separators=(",", ":"), ensure_ascii=False).encode())
        if size > MAX_CLIENT_MESSAGE_BYTES:
            raise ValueError("WS_MESSAGE_INVALID: payload acima de 16 kB")
        return self


class TelemetrySubscription(ContractModel):
    """Payload de ``control.subscribe``."""

    channels: list[str] = Field(min_length=1, max_length=MAX_SUBSCRIBED_CHANNELS)
    fps: int = Field(50, ge=30, le=60)  # FPS da sessão (último pedido vence)
    spectrum: bool = False
    pressure_trace: dict[str, int] | None = None  # {"cylinder": 1..n_cyl}

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.pressure_trace is not None:
            if set(self.pressure_trace) != {"cylinder"}:
                raise ValueError("pressure_trace aceita só a chave 'cylinder'")
            if not 1 <= self.pressure_trace["cylinder"] <= MAX_CYLINDERS:
                raise ValueError("WS_CYLINDER_OUT_OF_RANGE")
        return self

    @property
    def wants_spectrum(self) -> bool:
        """``spectrum = true`` ou o nome composto ``knock_spectrum`` em ``channels``."""
        return self.spectrum or "knock_spectrum" in self.channels

    @property
    def trace_cylinder(self) -> int | None:
        """Cilindro do traço de pressão (``cyl_pressure_trace`` em ``channels`` = cilindro 1)."""
        if self.pressure_trace is not None:
            return self.pressure_trace["cylinder"]
        return 1 if "cyl_pressure_trace" in self.channels else None

    @property
    def scalar_channels(self) -> list[str]:
        """Canais escalares (sem os nomes compostos)."""
        return [c for c in self.channels if c not in ("knock_spectrum", "cyl_pressure_trace")]


class KnockSpectrum(ContractModel):
    bins_hz: list[float] = Field(min_length=SPECTRUM_BINS, max_length=SPECTRUM_BINS)  # Hz
    magnitude_db: list[float] = Field(min_length=SPECTRUM_BINS, max_length=SPECTRUM_BINS)  # dB
    resonance_hz: list[float] = Field(min_length=RESONANCE_MODES, max_length=RESONANCE_MODES)
    sensor: Literal["block"] = "block"


class PressureTrace(ContractModel):
    cylinder: int = Field(ge=1, le=MAX_CYLINDERS)
    crank_deg: list[int]  # ° ATDC, 1 ponto por grau
    p_bar: list[float]  # bar abs

    @model_validator(mode="after")
    def _check(self) -> Self:
        if len(self.crank_deg) != len(self.p_bar):
            raise ValueError("crank_deg e p_bar devem ter o mesmo comprimento")
        return self


class FrameStats(ContractModel):
    fps_actual: float = Field(ge=0.0)  # Hz
    dropped_frames: int = Field(ge=0)
    dropped_events: int = Field(ge=0)
    real_time_factor: float | None = Field(ge=0.0)
    tick: int = Field(ge=0)


class TelemetryFrame(ContractModel):
    """Payload de ``telemetry.frame``."""

    session_id: str = Field(min_length=1, max_length=36)
    run_id: str | None  # null sem puxada
    frame_index: int = Field(ge=0)  # floor(k · fps / sim_hz)
    window_ticks: int = Field(ge=1, le=34)
    channels: dict[str, float | None]  # só canais subscritos; flags 0/1
    knock_spectrum: KnockSpectrum | None = None  # só com spectrum = true
    cyl_pressure_trace: PressureTrace | None = None  # só com pressure_trace, ≤ 10 Hz
    stats: FrameStats


class KnockEventPayload(ContractModel):
    """Payload de ``event.knock`` (união D-WS-02)."""

    run_id: str | None
    cylinder: int = Field(ge=1, le=MAX_CYLINDERS)
    knock_class: Literal["light", "moderate", "severe"]
    intensity: float = Field(ge=0.0, le=1.0)  # knock_intensity normalizado (0–1)
    intensity_raw: float = Field(ge=0.0)  # bar de MAPO
    mapo_kpa: float = Field(ge=0.0)  # kPa
    theta_onset_deg_atdc: float | None  # ° ATDC
    retard_deg: float = Field(ge=0.0)  # ° (0 sem ECU)
    rpm: float = Field(ge=0.0)  # rev/min
    p_max_bar: float = Field(ge=0.0)  # bar abs
    threshold: float | None  # limiar knock_threshold (escala de intensity)
    simulated_only: bool = False  # true com damage_enabled = false


class LimiterEventPayload(ContractModel):
    run_id: str | None
    kind: Literal["rev_limiter", "two_step", "overboost_cut", "antilag_protect", "overrun_protect"]
    phase: Literal["soft", "hard"] | None = None
    active: bool
    rpm: float = Field(ge=0.0)  # rev/min


class WsErrorPayload(ContractModel):
    code: str = Field(pattern=ERROR_CODE_PATTERN)
    title: str = Field(min_length=1, max_length=120)
    detail: str = Field("", max_length=500)
    fatal: bool = False  # true ⇒ o servidor fecha a conexão a seguir
    oldest_available_seq: int | None = Field(None, ge=0)  # só WS_RESUME_GAP

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.oldest_available_seq is not None and self.code != "WS_RESUME_GAP":
            raise ValueError("oldest_available_seq só acompanha WS_RESUME_GAP")
        return self


# --------------------------------------------------------------------------- DataLog


class PullSegment(ContractModel):
    pull_index: int = Field(ge=1)
    start_index: int = Field(ge=0)  # índice de amostra inclusivo
    end_index: int = Field(ge=0)  # exclusivo
    state: str = Field(min_length=1, max_length=16)  # RunState ao fim da puxada

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.end_index < self.start_index:
            raise ValueError("end_index deve ser ≥ start_index")
        return self


class LogEvent(ContractModel):
    index: int = Field(ge=0)  # amostra do tick do evento
    type: Literal["event.knock", "event.failure", "event.limiter", "run.state"]
    payload: dict[str, Any]


class DataLogHeader(ContractModel):
    format_version: Literal[1] = DATALOG_FORMAT_VERSION
    run_id: str = Field(min_length=1, max_length=36)
    session_id: str = Field(min_length=1, max_length=36)
    vehicle_id: str = Field(min_length=1, max_length=48)
    profile_id: str = Field(min_length=1, max_length=16)
    calibration_hash: Sha256Hex  # SHA-256 da calibração (ecu-core)
    fuel_id: str = Field(min_length=1, max_length=16)
    seed: int = Field(ge=0, le=2**63 - 1)
    sim_hz: int = Field(ge=100, le=1000)  # Hz
    start_tick: int = Field(ge=0)  # tick da sessão da 1.ª amostra
    n_samples: int = Field(ge=0)
    channels: list[TelemetryChannel] = Field(min_length=1, max_length=MAX_IMPORT_CHANNELS)
    pulls: list[PullSegment] = Field(default_factory=list)
    events: list[LogEvent] = Field(default_factory=list)
    terminal_state: TerminalState
    truncated: bool = False  # puxada > 300 s

    @model_validator(mode="after")
    def _check(self) -> Self:
        names = [c.name for c in self.channels]
        if len(set(names)) != len(names):
            raise ValueError("LOG_SCHEMA_INVALID: canal duplicado")
        if any(seg.end_index > self.n_samples for seg in self.pulls):
            raise ValueError("LOG_SCHEMA_INVALID: segmento além de n_samples")
        if any(event.index >= max(self.n_samples, 1) for event in self.events):
            raise ValueError("LOG_SCHEMA_INVALID: evento além de n_samples")
        return self


class DataLog(ContractModel):
    """Log de puxada (JSON do E-27 e do import E-28)."""

    header: DataLogHeader
    t_sim_s: list[float]  # s, len == n_samples
    data: dict[str, list[float | None]]  # chave = TelemetryChannel.name; null = ausente
    sha256: Sha256Hex
    # metadados voláteis, fora do hash
    log_id: str | None = Field(None, min_length=1, max_length=36)
    created_at: AwareDatetime | None = None  # ISO 8601 UTC
    source: LogSource = "simulated"

    @model_validator(mode="after")
    def _lengths(self) -> Self:
        n = self.header.n_samples
        names = [c.name for c in self.header.channels]
        if (
            len(self.t_sim_s) != n
            or list(self.data) != names
            or any(len(v) != n for v in self.data.values())
        ):
            raise ValueError("LOG_SCHEMA_INVALID")
        if self.source == "imported" and self.log_id is not None:
            if re.fullmatch(IMPORTED_LOG_ID_PATTERN, self.log_id) is None:
                raise ValueError("log_id importado deve ser 'imp-' + 12 hex")
        return self


class DataLogSummary(ContractModel):
    log_id: str = Field(min_length=1, max_length=36)
    run_id: str | None
    vehicle_id: str = Field(min_length=1, max_length=48)
    sha256: Sha256Hex
    n_samples: int = Field(ge=0)
    sim_hz: int = Field(ge=100, le=1000)
    source: LogSource


class LogRef(ContractModel):
    run_id: str | None = Field(None, min_length=1, max_length=36)
    log_id: str | None = Field(None, min_length=1, max_length=36)

    @model_validator(mode="after")
    def _exactly_one(self) -> Self:
        if (self.run_id is None) == (self.log_id is None):
            raise ValueError("LogRef exige exatamente um de run_id ou log_id")
        return self


class LogCompareRequest(ContractModel):
    a: LogRef  # referência (ex.: puxada base)
    b: LogRef  # candidata
    bin_rpm: int = Field(100, ge=50, le=500)  # rev/min
    pull_index_a: int | None = Field(None, ge=1)  # None = 1.ª puxada do log
    pull_index_b: int | None = Field(None, ge=1)
    min_samples_per_bin: int = Field(5, ge=1, le=1000)


class ComparisonBin(ContractModel):
    rpm_bin: int = Field(ge=0)  # limite inferior do bin (rev/min)
    torque_nm_a: float
    torque_nm_b: float
    delta_torque_nm: float  # N·m (B − A)
    power_kw_a: float
    power_kw_b: float
    delta_power_kw: float  # kW
    whp_a: float
    whp_b: float
    delta_whp: float  # hp
    lambda_a: float | None
    lambda_b: float | None
    delta_lambda: float | None  # (-)
    egt_c_a: float
    egt_c_b: float
    delta_egt_c: float  # °C
    knock_intensity_max_a: float = Field(ge=0.0, le=1.0)
    knock_intensity_max_b: float = Field(ge=0.0, le=1.0)
    n_a: int = Field(ge=0)
    n_b: int = Field(ge=0)


class LogComparison(ContractModel):
    a: DataLogSummary
    b: DataLogSummary
    bin_rpm: int = Field(ge=50, le=500)
    vehicle_mismatch: bool
    bins: list[ComparisonBin]  # só bins comuns, ordem crescente de rpm
    peak_torque_nm_a: float
    peak_torque_nm_b: float
    peak_whp_a: float
    peak_whp_b: float
    delta_peak_whp_pct: float  # %
    max_abs_delta: dict[str, Annotated[float, Field(ge=0.0)]]  # torque_nm, power_kw, ...
    bins_only_in_a: int = Field(ge=0)
    bins_only_in_b: int = Field(ge=0)

    @model_validator(mode="after")
    def _check(self) -> Self:
        rpms = [b.rpm_bin for b in self.bins]
        if rpms != sorted(set(rpms)):
            raise ValueError("bins devem estar em rpm estritamente crescente")
        return self


def split_cylinder_channel(name: str) -> tuple[str, int | None]:
    """Separa ``<base>_cyl<k>`` em ``(base, k)``; canais globais devolvem ``(name, None)``."""
    match = _CYL_SUFFIX.fullmatch(name)
    if match is None:
        return name, None
    return match["base"], int(match["k"])
