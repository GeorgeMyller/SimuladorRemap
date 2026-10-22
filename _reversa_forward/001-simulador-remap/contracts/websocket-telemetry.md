# Contrato: WebSocket de telemetria `/ws/v1/sessions/{session_id}/telemetry`

> Feature: `001-simulador-remap` · Fase: plan · Gerado em 2026-10-18 (modo autônomo, greenfield)
> Confidência: 🟢 CONFIRMADO, 🟡 INFERIDO (padrão: specs planejadas), 🔴 LACUNA / DÚVIDA
> Dono: `telemetry-datalogger`. Payloads de `run.state` (dono `dyno-bench`) e de `event.failure`/`event.knock` (dono `knock-and-failure-model`) passam sem alteração de semântica.
> Consumidores: `dyno-cockpit-ui` e `ecu-tuning-ui` (cliente `frontend/src/lib/ws/TelemetrySocket`), `training-scenarios` (painel de progresso).
> Delta: componente-novo.

## 1. Handshake e ciclo de vida

Fonte: `_reversa_sdd/sdd/telemetry-datalogger.md#8-design-e-interface` (bloco "WebSocket"), RF-01, RF-10, `#12-segurança-e-privacidade`.

1. 🟡 O cliente abre `ws://<host>/ws/v1/sessions/{session_id}/telemetry` na mesma origem do SPA. Query opcional: `resume_from_seq` (inteiro ≥ 0).
2. 🟡 O servidor valida o cabeçalho `Origin` contra a origem do servidor. Origem diferente: fecho 4403 com `reason = WS_ORIGIN_FORBIDDEN`.
3. 🟡 O servidor valida a sessão. Sessão inexistente: fecho 4404 com `reason = SESSION_NOT_FOUND`.
4. 🟡 O servidor conta as conexões da sessão. A 5.ª conexão simultânea fecha com 4429 e `reason = WS_TOO_MANY_CONNECTIONS`.
5. 🟡 Aceite a conexão, o servidor envia o snapshot atual de `run.state` (com `seq` novo) e passa a emitir `telemetry.frame` com o conjunto padrão de canais: `rpm`, `map_kpa`, `lambda`, `torque_nm`, `power_kw` (sem espectro e sem traço de pressão).
6. 🟡 Com `resume_from_seq`, o servidor reenvia antes do 1.º frame novo os envelopes de evento e `run.state` com `seq > resume_from_seq` ainda no buffer de replay (seção 7).
7. 🟡 O cliente envia `control.subscribe` com os canais dos painéis visíveis. A subscrição vale a partir do frame seguinte. Após reconexão, a subscrição anterior não é restaurada: o cliente reenvia `control.subscribe`.
8. 🟡 Sem autenticação (local-first). `session_id` é UUID opaco e não sequencial.

## 2. Envelope `WsEnvelope` v1

Fonte: `_reversa_sdd/sdd/telemetry-datalogger.md#9-modelo-de-dados`, RF-02, RF-03, RF-25; `_reversa_sdd/sdd/platform-foundation.md#9-modelo-de-dados` (`WS_ENVELOPE_VERSION = 1`).

```python
from typing import Any, Literal
from pydantic import BaseModel, Field

WsType = Literal["telemetry.frame", "run.state", "event.knock",
                 "event.failure", "event.limiter", "error"]

class WsEnvelope(BaseModel):                 # servidor → cliente
    v: Literal[1] = 1
    type: WsType
    seq: int = Field(ge=0)                   # contador único por sessão, partilhado por todos os tipos
    t_sim_s: float = Field(ge=0.0)           # tempo simulado do tick de origem
    payload: dict[str, Any]

ClientType = Literal["control.subscribe", "control.throttle", "control.ping"]

class WsClientMessage(BaseModel):            # cliente → servidor
    v: Literal[1] = 1
    type: ClientType
    payload: dict[str, Any] = {}             # ≤ 16 kB serializado
```

- 🟡 Serialização: JSON compacto UTF-8, uma mensagem de texto por envelope. Floats arredondados aos `decimals` do catálogo de canais (só no WS; o log grava sem arredondar). Espectro em dB com 1 casa decimal.
- 🟡 Nenhum tipo novo de envelope (sem `pong`, sem `resumed`). Keepalive pelo ping do protocolo WebSocket.
- 🟡 O cliente valida `v = 1` e `type` conhecido. Envelope inválido é descartado e contado em `invalidEnvelopes`; o handler nunca lança exceção (`dyno-cockpit-ui.md` EC-04).

### 2.1 Regra do `seq`

Fonte: `telemetry-datalogger.md` RF-03, RF-25, OQ-07 (resolvida na R1); `dyno-cockpit-ui.md` EC-02, EC-03; `prd.md` ("Decisões de integração (revisão R1)").

- 🟡 O `seq` começa em 0 na criação da sessão. Cada envelope do servidor, de qualquer `type`, incluindo `error` local a 1 conexão, recebe `seq` = último `seq` da sessão + 1.
- 🟡 O `seq` nunca se repete nem é reutilizado. O servidor atribui o `seq` antes de qualquer filtro por subscrição ou descarte por conexão.
- 🟡 Consequência: uma conexão vê saltos de `seq` normais (envelopes `error` de outra conexão, frames descartados na sua fila). Saltos de `seq` não medem perda.
- 🟡 O cliente descarta envelopes com `seq ≤ último seq aceito` na mesma conexão (deduplicação de replay). Nova conexão reinicia a referência.
- 🟡 Exemplo: 1 subscrição inválida entre 2 frames gera `seq` n (frame), n+1 (`error`), n+2 (frame).

### 2.2 Medida de perda por `frame_index`

Fonte: `telemetry-datalogger.md#8-design-e-interface` ("Decimação e agregação"); `dyno-cockpit-ui.md#9-modelo-de-dados` (`StreamStats`).

- 🟡 A perda de frames mede-se só pelo salto de `payload.frame_index` em envelopes `telemetry.frame` consecutivos da mesma conexão: `lost += frame_index − last_frame_index − 1`.
- 🟡 `frame_index(k) = floor(k · fps / sim_hz)`, com `k` = tick desde o início da sessão. O frame fecha quando o índice do tick k+1 difere.
- 🟡 A `fps` é parâmetro da sessão: todas as conexões recebem o mesmo fluxo de frames. Por isso o salto de `frame_index` mede só perda real.
- 🟡 A cockpit acende o indicador de perda com taxa > 2 % em 5 s e nunca interpola valores inventados.

## 3. Mensagens servidor → cliente

### 3.1 `telemetry.frame`

Fonte: `telemetry-datalogger.md#9-modelo-de-dados` (`TelemetryFrame`, `KnockSpectrum`, `PressureTrace`, `FrameStats`), RF-05 a RF-07, RF-20, RF-21, RF-23.

```python
class FrameStats(BaseModel):
    fps_actual: float
    dropped_frames: int          # ≥ 0, monotônico por conexão
    dropped_events: int          # ≥ 0
    real_time_factor: float | None
    tick: int

class KnockSpectrum(BaseModel):
    bins_hz: list[float]         # sempre 256 valores, 0–20 kHz, largura 78,125 Hz; fixos na sessão
    magnitude_db: list[float]    # 256 valores, dB re 1 V
    resonance_hz: list[float]    # 4 modos de Draper (1,0) (2,0) (0,1) (3,0)
    sensor: Literal["block"] = "block"

class PressureTrace(BaseModel):
    cylinder: int                # 1..n_cyl
    crank_deg: list[int]         # ATDC, 1 ponto por grau
    p_bar: list[float]           # absoluta, mesmo comprimento de crank_deg

class TelemetryFrame(BaseModel):            # payload
    session_id: str
    run_id: str | None           # null sem puxada (motor em marcha lenta ou parado)
    frame_index: int
    window_ticks: int            # 1..34
    channels: dict[str, float | None]        # só canais subscritos; flags 0/1; canal ausente na janela é omitido
    knock_spectrum: KnockSpectrum | None = None   # só com spectrum = true
    cyl_pressure_trace: PressureTrace | None = None  # só com pressure_trace, ≤ 10 Hz
    stats: FrameStats
```

```json
{
  "v": 1, "type": "telemetry.frame", "seq": 18421, "t_sim_s": 37.420,
  "payload": {
    "session_id": "c3f1a2", "run_id": "r-01J9Z", "frame_index": 1871, "window_ticks": 20,
    "channels": {"rpm": 5012.0, "map_kpa": 231.4, "boost_bar": 1.32, "lambda": 0.82,
                 "knock_intensity_cyl3": 0.410, "knock_sensor_v_cyl3": 2.080,
                 "egt_c": 884.0, "fuel_cut": 0},
    "knock_spectrum": {"bins_hz": [0.0, 78.125], "magnitude_db": [-62.1, -61.8],
                       "resonance_hz": [6720.0, 11147.0, 13987.0, 15334.0], "sensor": "block"},
    "cyl_pressure_trace": null,
    "stats": {"fps_actual": 50.0, "dropped_frames": 0, "dropped_events": 0,
              "real_time_factor": 1.0, "tick": 37420}
  }
}
```

- 🟡 O exemplo encurta `bins_hz` e `magnitude_db`; no fio são sempre 256 valores. O cliente pode guardar `bins_hz` da 1.ª mensagem.
- 🟡 Valor não finito vindo da física sai como `null` no frame e NaN no log (EC-17).

### 3.2 `run.state`

Fonte: `_reversa_sdd/sdd/dyno-bench.md#8-design-e-interface` (payload `run.state`, máquina de estados), RF-13.

```json
{
  "v": 1, "type": "run.state", "seq": 1842, "t_sim_s": 37.412,
  "payload": {
    "session_id": "c3f1a2", "run_id": "r-01J9Z", "run_type": "multi_pull",
    "state": "running", "previous_state": "arming", "phase": "pull",
    "pull_index": 1, "pull_count": 3, "abort_reason": null,
    "progress_pct": 12.5, "rpm": 2010.0,
    "realtime_factor": 1.0, "forensic_report_url": null
  }
}
```

- 🟡 `state` ∈ `RunState` do `dyno-bench`: `idle`, `arming`, `running`, `coastdown`, `completed`, `aborted`, `engine_failed`.
- 🟡 `abort_reason` ∈ `AbortReason`: `user_abort`, `egt_limit`, `severe_knock_protection`, `catastrophic_failure`, `arming_timeout`, `session_closed`, `run_timeout`, `internal_error`.
- 🟡 1 envelope por transição. Em `engine_failed`, `forensic_report_url = /api/v1/runs/{run_id}/forensic-report`.
- 🟡 Avisos do laço (`realtime_degraded`, `telemetry_degraded`, `ramp_not_sustained`, `rev_limiter_hit`) seguem no `DynoRun.summary.event_codes`, não em `run.state`.

### 3.3 `event.knock`

Fonte: `_reversa_sdd/sdd/knock-and-failure-model.md#8-design-e-interface` (payload WS), RF-04, RF-28; `telemetry-datalogger.md#9-modelo-de-dados` (`KnockEventPayload`), RF-11; `dyno-cockpit-ui.md#9-modelo-de-dados` (campos mínimos).

```python
class KnockEventPayload(BaseModel):
    run_id: str | None
    cylinder: int                 # 1..8
    knock_class: Literal["light", "moderate", "severe"]   # classe ≥ light dispara o evento
    intensity: float              # índice normalizado knock_intensity do cilindro no tick (0,0–1,0)
    intensity_raw: float          # I do ciclo em bar de MAPO (escala do knock-and-failure-model)
    mapo_kpa: float
    theta_onset_deg_atdc: float | None
    retard_deg: float             # EcuStatus.knock_retard_deg[k−1] do mesmo tick (0 sem ECU)
    rpm: float
    p_max_bar: float              # CombustionEvent.p_max_kpa / 100
    threshold: float | None       # limiar knock_threshold da ECU no rpm (mesma escala de intensity)
    simulated_only: bool          # true com damage_enabled = false
```

```json
{"v": 1, "type": "event.knock", "seq": 18422, "t_sim_s": 37.4213,
 "payload": {"run_id": "r-01J9Z", "cylinder": 3, "knock_class": "severe",
             "intensity": 0.98, "intensity_raw": 6.4, "mapo_kpa": 640.0,
             "theta_onset_deg_atdc": 14.0, "retard_deg": 8.0, "rpm": 5480.0,
             "p_max_bar": 118.6, "threshold": 0.15, "simulated_only": false}}
```

- 🟡 Disparo: ciclo com `knock_class ≥ light` (I ≥ 0,3).
- 🟡 Taxa: no máximo **10 eventos por segundo por cilindro** (em `t_sim_s`). Excedentes não são publicados no WS; o log grava todas as intensidades por tick.
- 🟡 Knock `severe` em todos os ciclos de um cilindro a 6000 rpm gera 10 `event.knock`/s, não 50.

### 3.4 `event.failure`

Fonte: `knock-and-failure-model.md#9-modelo-de-dados` (`FailureEvent`), RF-18, RF-28; `telemetry-datalogger.md` RF-13.

```json
{"v": 1, "type": "event.failure", "seq": 1907, "t_sim_s": 13.118,
 "payload": {"failure_event_id": "01JAB0000000000000000000", "session_id": "c3f1a2",
             "run_id": "r-01J9Z", "tick": 13118, "t_sim_s": 13.118, "cylinder": 3,
             "component_id": "piston:3", "mode": "piston_failure",
             "mechanism": "knock_erosion", "catastrophic": true, "simulated_only": false,
             "health_after": 0.0,
             "causal_variables": {"knock_signal_raw": 7.9, "knock_intensity": 1.0,
                                  "piston_temp_eff_c": 371.0}}}
```

- 🟡 O payload é o `FailureEvent` completo, sem renomear campos: `mode` (não `failure_mode`), `component_id` (não `component`).
- 🟡 `mode` ∈ {`knock_damage`, `pre_ignition`, `egt_overtemp`, `rod_failure`, `piston_failure`, `turbo_meltdown`}. `component_id` ∈ `piston:i`, `rod:i`, `valves:i`, `head_gasket`, `bearings`, `turbo:turbine`.
- 🟡 Publicado no mesmo tick da falha, antes do `run.state` = `engine_failed`. Nunca é descartado.

### 3.5 `event.limiter`

Fonte: `telemetry-datalogger.md#9-modelo-de-dados` (`LimiterEventPayload`), RF-12; `ecu-core.md#9-modelo-de-dados` (`EcuEvent`, `EcuStatus.limiter_state`).

```json
{"v": 1, "type": "event.limiter", "seq": 19010, "t_sim_s": 41.002,
 "payload": {"run_id": "r-01J9Z", "kind": "rev_limiter", "phase": "hard", "active": true, "rpm": 7004.0}}
```

- 🟡 `kind` ∈ {`rev_limiter`, `two_step`, `overboost_cut`, `antilag_protect`, `overrun_protect`}; `phase` ∈ {`soft`, `hard`, `null`}.
- 🟡 1 envelope por transição de estado (`active: true` ao entrar, `active: false` ao sair), com o `t_sim_s` do `EcuEvent`.

### 3.6 `error`

Fonte: `telemetry-datalogger.md#9-modelo-de-dados` (`WsErrorPayload`), apêndice "Catálogo de `code` de erro do componente".

```python
class WsErrorPayload(BaseModel):
    code: str                     # ^[A-Z][0-9A-Z_]{2,63}$
    title: str
    detail: str = ""
    fatal: bool = False           # true ⇒ o servidor fecha a conexão a seguir
    oldest_available_seq: int | None = None   # só WS_RESUME_GAP
```

```json
{"v": 1, "type": "error", "seq": 19011, "t_sim_s": 41.002,
 "payload": {"code": "WS_UNKNOWN_CHANNEL", "title": "Canal desconhecido",
             "detail": "egt_c_cyl9", "fatal": false}}
```

| Code | Fatal | Fecho | Quando |
|---|---|---|---|
| 🟡 `WS_MESSAGE_INVALID` | não | — | JSON inválido, `type` desconhecido ou > 16 kB. |
| 🟡 `WS_UNKNOWN_CHANNEL` | não | — | Canal fora do catálogo do veículo; canais válidos ficam ativos. |
| 🟡 `WS_FPS_OUT_OF_RANGE` | não | — | `fps` fora de 30–60. |
| 🟡 `WS_CYLINDER_OUT_OF_RANGE` | não | — | Cilindro do traço > `n_cyl`. |
| 🟡 `WS_RESUME_GAP` | não | — | `resume_from_seq` anterior ao buffer (com `oldest_available_seq`). |
| 🟡 `WS_RESUME_INVALID` | não | — | `resume_from_seq` maior que o `seq` atual; tratado como conexão nova. |
| 🟡 `SPECTRUM_UNAVAILABLE` | não | — | Veículo sem `bore_mm`; espectro desligado. |
| 🟡 `THROTTLE_LOCKED_BY_RUN` | não | — | `control.throttle` fora do estado `idle` (dono `dyno-bench`). |
| 🟡 `WS_RATE_LIMITED` | sim | 1008 | > 20 mensagens inválidas em 10 s ou > 100 mensagens/s. |
| 🟡 `SIM_INTERNAL_ERROR` | não | — | Exceção no tick; a puxada passa a `aborted` (dono `dyno-bench`). |
| 🟡 `SIM_WORKER_UNAVAILABLE` | sim | 1011 | Worker sem heartbeat por 2 s (dono `platform-foundation`). |

- 🟡 Todo `error` recebe `seq` + 1 (seção 2.1). O catálogo completo, com status HTTP, está em `contracts/rest-api.md` seção 4.

## 4. Mensagens cliente → servidor

Fonte: `telemetry-datalogger.md#9-modelo-de-dados` (`TelemetrySubscription`, `WsClientMessage`), RF-07, RF-22, RF-24; `dyno-bench.md` RF-24.

### 4.1 `control.subscribe`

```python
class TelemetrySubscription(BaseModel):     # payload
    channels: list[str]                     # 1..128 nomes expandidos do catálogo
    fps: int = 50                           # 30..60; parâmetro da sessão (último pedido vence)
    spectrum: bool = False
    pressure_trace: dict[str, int] | None = None   # {"cylinder": 1..n_cyl}
```

```json
{"v": 1, "type": "control.subscribe",
 "payload": {"channels": ["rpm", "torque_nm", "power_kw", "lambda", "boost_bar",
                          "knock_intensity_cyl1", "knock_intensity_cyl2",
                          "knock_intensity_cyl3", "knock_intensity_cyl4", "egt_c"],
             "fps": 50, "spectrum": true, "pressure_trace": {"cylinder": 2}}}
```

- 🟡 Os frames só trazem os canais subscritos, a partir do frame seguinte. Eventos e `run.state` vão a todas as conexões, sem filtro.
- 🟡 Os nomes compostos `knock_spectrum` e `cyl_pressure_trace` em `channels` equivalem a `spectrum = true` e `pressure_trace = {cylinder: 1}`.
- 🟡 Partes inválidas geram `error` não fatal; as partes válidas aplicam-se.
- 🟡 Uma `fps` diferente altera a taxa da sessão na fronteira de frame seguinte, para todas as conexões.

### 4.2 `control.throttle`

```json
{"v": 1, "type": "control.throttle", "payload": {"throttle_pct": 50.0}}
```

- 🟡 `throttle_pct` ∈ 0..100. Encaminhado ao `dyno-bench` pela fila de comandos do worker.
- 🟡 Aceite só no estado `idle` da sessão; o `throttle_pct` do frame seguinte muda em ≤ 100 ms.
- 🟡 Em `arming`, `running` ou `coastdown`: `error` `THROTTLE_LOCKED_BY_RUN`, sem efeito.
- 🟡 Fila de comandos cheia: `error` não fatal com `code = SIM_WORKER_BUSY`.

### 4.3 `control.ping`

```json
{"v": 1, "type": "control.ping", "payload": {"nonce": "a1b2c3"}}
```

- 🟡 Reinicia o timeout de inatividade de 30 s. Não tem resposta.
- 🟡 A cockpit envia `control.ping` a cada 5 s e considera a conexão caída após 10 s sem nenhum envelope.

## 5. Catálogo de canais

Fonte: `telemetry-datalogger.md#9-modelo-de-dados` ("Catálogo `TelemetryChannel`"), RF-04, RF-06; `engine-physics-core.md#6-requisitos-funcionais` (RF-26, Apêndice A.10).

- 🟡 Canais por cilindro expandem-se como `<base>_cyl<k>`, k = 1..`n_cyl` do veículo (índice 1-based no nome; listas Python com índice 0 = cilindro 1).
- 🟡 O catálogo por veículo é servido por `GET /api/v1/telemetry/channels?vehicle_id=` (E-26).
- 🟡 Agregação por janela de frame: `last` (último tick), `max`/`min` (extremos ignorando `null`), `any` (1 se algum tick tem a flag), `sum` (soma).

| Canal | Unidade | Agregação | Decimais | Fonte |
|---|---|---|---|---|
| 🟡 `rpm` | rpm | last | 0 | `EngineState.rpm` |
| 🟡 `map_kpa` | kPa (abs) | last | 1 | `SensorReadings.map_kpa` |
| 🟡 `baro_kpa` | kPa (abs) | last | 1 | `SensorReadings.baro_kpa` |
| 🟡 `boost_bar` | bar (rel) | last | 2 | `(map_kpa − baro_kpa) / 100` |
| 🟡 `lambda_cyl<k>` | – | last | 3 | `EngineState.lambda_cyl[k−1]` (null em corte) |
| 🟡 `lambda` | – | last | 3 | média dos `lambda_cyl` não nulos |
| 🟡 `lambda_measured` | – | last | 3 | `SensorReadings.lambda_measured` (wideband com atraso) |
| 🟡 `afr` | – | last | 2 | `lambda × FuelSpec.afr_stoich` |
| 🟡 `spark_deg_cyl<k>` | °BTDC | last | 1 | `ActuatorCommands.ignition_advance_deg[k−1]` |
| 🟡 `knock_sensor_v_cyl<k>` | V (0,0–5,0) | max | 3 | `SensorReadings.knock_sensor_v[k−1]` |
| 🟡 `knock_intensity_cyl<k>` | – (0,0–1,0) | max | 3 | `SensorReadings.knock_intensity[k−1]` (derivado de `knock_sensor_v`) |
| 🟡 `knock_retard_deg` | ° | max | 1 | `max(EcuStatus.knock_retard_deg)` |
| 🟡 `knock_retard_deg_cyl<k>` | ° | max | 1 | `EcuStatus.knock_retard_deg[k−1]` |
| 🟡 `cyl_pressure_peak_bar_cyl<k>` | bar (abs) | max | 1 | `EngineState.p_max_kpa[k−1] / 100` |
| 🟡 `cyl_pressure_peak_bar` | bar (abs) | max | 1 | máximo entre cilindros |
| 🟡 `egt_c_cyl<k>` | °C | max | 0 | `SensorReadings.egt_c[k−1]` (termopar) |
| 🟡 `egt_c` | °C | max | 0 | máximo de `egt_c_cyl<k>` |
| 🟡 `egt_pre_turbo_c` | °C | max | 0 | `SensorReadings.egt_collector_c` |
| 🟡 `iat_c`, `ect_c`, `oil_temp_c` | °C | last | 1 | `SensorReadings` |
| 🟡 `turbo_rpm` | rpm | last | 0 | `SensorReadings.turbo_rpm` (nullable) |
| 🟡 `wastegate_duty_pct` | % | last | 1 | `ActuatorCommands.wastegate_duty_pct` (nullable sem turbo) |
| 🟡 `injector_duty_pct` | % | max | 1 | `EcuStatus.inj_duty_pct` |
| 🟡 `injector_pw_ms_cyl<k>` | ms | max | 2 | `ActuatorCommands.injector_pw_ms[k−1]` (decisão D-WS-06) |
| 🟡 `torque_nm` | N·m | last | 1 | `EngineState.torque_nm` (cambota) |
| 🟡 `power_kw` | kW | last | 2 | `EngineState.power_kw` |
| 🟡 `whp` | hp | last | 1 | `EngineState.whp` (1 hp = 0,7457 kW) |
| 🟡 `throttle_pct` | % | last | 1 | `SensorReadings.tps_pct` |
| 🟡 `load_pct` | % | last | 1 | `EcuStatus.load_pct` |
| 🟡 `torque_request_nm` | N·m | last | 1 | `EcuStatus.torque_request_nm` (null fora do `oem-stage`) |
| 🟡 `lambda_target` | – | last | 3 | `EcuStatus.lambda_target` |
| 🟡 `boost_target_kpa` | kPa (abs) | last | 1 | `EcuStatus.boost_target_kpa` |
| 🟡 `fuel_cut` | flag | any | 0 | `any(ActuatorCommands.fuel_cut)` |
| 🟡 `ign_cut` | flag | any | 0 | `any(ActuatorCommands.spark_cut)` |
| 🟡 `overrun_afterfire` | contagem | sum | 0 | nº de `CombustionEvent.pop_event` na janela |
| 🟡 `roller_speed_kmh` | km/h | last | 1 | estado do rolo do `dyno-bench` (🔴 origem em aberto: OQ-04 da telemetria) |
| 🟡 `health_<componente>_pct` | % | min | 1 | `DamageState.components` (`piston_cyl<k>`, `rod_cyl<k>`, `valves_cyl<k>`, `head_gasket`, `bearings`, `turbine`) |
| 🟡 `health_min_pct` | % | min | 1 | menor saúde entre componentes |
| 🟡 `real_time_factor` | – | last | 3 | `EngineState.real_time_factor` |

- 🟡 Canais compostos fora do log: `knock_spectrum` (256 bins) e `cyl_pressure_trace` (1 cilindro, ≤ 10 Hz).
- 🟡 Motor sem turbo: `turbo_rpm` e `wastegate_duty_pct` são `null`; a subscrição é aceite sem erro.

## 6. Backpressure

Fonte: `telemetry-datalogger.md` RF-08, RF-09, EC-01, EC-03; `platform-foundation.md#8-design-e-interface` (filas do worker), RF-12.

| Fila | Capacidade | Política | Nunca descarta |
|---|---|---|---|
| 🟡 Saída do worker (worker → event loop) | 256 | Descarta o item mais antigo; conta `dropped_outputs` | — |
| 🟡 Canal de controlo do worker | 64 | Sem descarte; se cheio, o worker marca `telemetry_degraded` no `DynoRun` (nunca bloqueia) | `run.state`, `event.failure`, fecho de log |
| 🟡 Frames por conexão | 8 | Descarta o frame mais antigo; `stats.dropped_frames` + 1 | — |
| 🟡 Eventos por conexão | 256 | Descarta o `event.knock` mais antigo; `dropped_events` no próximo frame | `run.state`, `event.failure`, `event.limiter`, `error` |

- 🟡 A decimação e a agregação correm no worker (50 itens/s em vez de 1000). O filtro por subscrição corre no event loop, perto do socket.
- 🟡 O envio nunca bloqueia o worker nem o produtor de frames. Meta: ≥ 99 % de `sim_hz` com 4 conexões, 2 delas sem leitura por 60 s.
- 🟡 Memória por conexão ≤ 2 MB. Ao retomar a leitura, o 1.º frame tem `t_sim_s` a ≤ 200 ms do tempo atual.
- 🟡 Banda por conexão ≤ 150 kB/s com subscrição completa e espectro a 50 FPS. Latência tick → envio P95 ≤ 40 ms, P99 ≤ 80 ms.

## 7. Resume e replay

Fonte: `telemetry-datalogger.md` RF-10, EC-04, EC-05; `#15-decisões-tomadas-decision-log`.

- 🟡 Buffer de replay por sessão: últimos 10 s simulados **ou** 512 envelopes, o limite que chegar primeiro. Contém só `run.state`, `event.knock`, `event.failure` e `event.limiter`. Nunca contém frames.
- 🟡 Reconexão com `?resume_from_seq=n`: o servidor envia o `run.state` atual (com `seq` novo), depois os eventos com `seq > n` com o **`seq` original**, depois os frames ao vivo.
- 🟡 `n` anterior ao evento mais antigo do buffer: `error` `WS_RESUME_GAP` com `oldest_available_seq`; o fluxo ao vivo continua. O histórico completo vem do log REST no fim da puxada.
- 🟡 `n` maior que o `seq` atual (ex.: sessão recriada): `error` `WS_RESUME_INVALID`; conexão tratada como nova, sem replay.
- 🟡 O cliente reconecta com backoff 0,5 s, 1 s, 2 s, 4 s, 8 s (teto 8 s), até 10 tentativas, e reenvia `control.subscribe`. Após reconectar, busca `GET /api/v1/runs/{run_id}`. Fonte: `dyno-cockpit-ui.md` RF-05, EC-01.

## 8. Códigos de fecho

Fonte: `telemetry-datalogger.md#8-design-e-interface`, RF-01, RF-24, EC-15, EC-16, `#12-segurança-e-privacidade`.

| Código | `reason` | Quando | Cliente deve reconectar |
|---|---|---|---|
| 🟡 1000 | — | Sessão apagada (`DELETE /api/v1/sessions/{id}`); `run.state` final enviado antes | não |
| 🟡 1008 | `WS_RATE_LIMITED` | Abuso de mensagens | não (até ação do usuário) |
| 🟡 1011 | `SIM_WORKER_UNAVAILABLE` ou erro interno | Worker morto ou exceção do servidor | sim, com backoff |
| 🟡 4403 | `WS_ORIGIN_FORBIDDEN` | `Origin` diferente da origem do servidor | não |
| 🟡 4404 | `SESSION_NOT_FOUND` | Sessão inexistente | não |
| 🟡 4408 | `WS_IDLE_TIMEOUT` | 30 s sem leitura nem `control.ping` | sim, com resume |
| 🟡 4429 | `WS_TOO_MANY_CONNECTIONS` | 5.ª conexão simultânea | não |

## 9. Limites e timeouts

| Limite | Valor | Fonte |
|---|---|---|
| 🟡 Conexões por sessão | 4 | `telemetry-datalogger.md` RF-01 |
| 🟡 Sessões ativas por container | 1 (padrão), máximo 2 | `platform-foundation.md#9-modelo-de-dados` |
| 🟡 `fps` | 30–60, padrão 50 (`Settings.ws_fps`) | RF-05 |
| 🟡 Canais por subscrição | 1–128 | `TelemetrySubscription` |
| 🟡 Tamanho de mensagem do cliente | 16 kB | RF-24 |
| 🟡 Mensagens inválidas | 20 em 10 s ⇒ 1008 | RF-24, EC-18 |
| 🟡 Taxa de mensagens do cliente | 100/s ⇒ 1008 | EC-18 |
| 🟡 `event.knock` | máximo 10 eventos/s por cilindro | `knock-and-failure-model.md` RF-28 |
| 🟡 Traço de pressão | ≤ 10 Hz | RF-21 |
| 🟡 Timeout de inatividade | 30 s (reiniciado por leitura ou `control.ping`) ⇒ 4408 | `telemetry-datalogger.md#8-design-e-interface` |
| 🟡 Ping do protocolo | a cada 15 s (servidor) | idem; `uvicorn --ws-ping-interval 15` (decisão D-WS-05) |
| 🟡 Buffer de replay | 10 s ou 512 envelopes | RF-10 |
| 🟡 Heartbeat do worker | 2 s ⇒ `error` fatal + 1011 | `platform-foundation.md` EC-04 |

## 10. Espectro de knock (origem dos dados)

Fonte: `knock-and-failure-model.md` RF-06, Apêndice B.6; `telemetry-datalogger.md#8-design-e-interface` ("Espectrograma de knock").

- 🟡 O espectro só é calculado com ≥ 1 conexão com `spectrum = true`. O log não grava o espectro; ele é regenerável a partir das intensidades e da `seed`.
- 🟡 Ressonâncias de Draper `f_mn = ρ_mn · c / (π · B)`, `c = √(γ · R · T)` com γ = 1,3, R = 287 J/(kg·K), T = 2400 K; ρ = (1,841; 3,054; 3,832; 4,201). Para B = 82,5 mm: 6,72 / 11,15 / 13,99 / 15,33 kHz.
- 🔴 Os coeficientes do espectro (T, C, τ_d, σ) são inferidos e precisam de validação (OQ-03 da telemetria).

## 11. Divergências resolvidas

| ID | Divergência | Specs envolvidas | Decisão | Confiança |
|---|---|---|---|---|
| D-WS-01 | Taxa de `event.knock`: 10/s por cilindro vs 1 por ciclo (≤ 50/s a 6000 rpm). | `knock-and-failure-model` RF-28 vs `telemetry-datalogger` RF-11 | Vale o limite mais restritivo: máximo 10 eventos/s por cilindro. | 🟡 |
| D-WS-02 | Payload de `event.knock` diferente: `knock_class`, `intensity` bruta (6,4), `mapo_kpa`, `theta_onset_deg_atdc`, `simulated_only` vs `intensity` normalizada (0,41), `p_max_bar`, `threshold`. | `knock-and-failure-model` §8 vs `telemetry-datalogger` §9 | União dos campos. `intensity` = índice normalizado `knock_intensity` (0–1), mesma escala do limiar da ECU e da UI; a intensidade bruta passa a `intensity_raw`. Disparo pela classe ≥ `light` (dono `knock-and-failure-model`). | 🟡 |
| D-WS-03 | Campos de `event.failure` na cockpit (`failure_mode`, `component`) vs `FailureEvent` (`mode`, `component_id`). | `dyno-cockpit-ui` §9 e `telemetry-datalogger` RF-13 vs `knock-and-failure-model` §9 | Adotados os nomes do `FailureEvent` (`mode`, `component_id`), sem renomear. | 🟡 |
| D-WS-04 | Estados de `run.state` na cockpit (`queued`, `failed`) vs `RunState` do `dyno-bench`. | `dyno-cockpit-ui` §9 vs `dyno-bench` §9 | Adotado `RunState` (`idle`, `arming`, `running`, `coastdown`, `completed`, `aborted`, `engine_failed`). | 🟡 |
| D-WS-05 | Ping do protocolo: 15 s na telemetria vs `--ws-ping-interval 20` no `CMD` do Dockerfile. | `telemetry-datalogger` §8 vs `platform-foundation` §8 | Adotado 15 s (dono do WS). O `CMD` usa `--ws-ping-interval 15`. | 🟡 |
| D-WS-06 | Sinal de knock e nomes de campo. | revisão R1 (`prd.md`) | Canais `knock_sensor_v_cyl<k>` (0–5 V) e `knock_intensity_cyl<k>` (0–1); `lambda_measured`; o pulso de bico publica-se como `injector_pw_ms_cyl<k>` (nome R1), acrescentado ao catálogo para o diagnóstico de bicos. | 🟡 |
| D-WS-07 | `seq` do envelope `error`. | `telemetry-datalogger` OQ-07, `dyno-cockpit-ui` EC-03, revisão R1 | Todo envelope do servidor, incluindo `error`, recebe `seq` + 1; perda medida só por `frame_index`. | 🟡 |
| D-WS-08 | Fonte do espectro: `DamageModel.spectrum_frame` (picos gaussianos de 3 modos) vs FFT de sinal sintético com 4 modos no `telemetry-datalogger`. | `knock-and-failure-model` RF-06 vs `telemetry-datalogger` RF-20 | Um só gerador: `DamageModel.spectrum_frame` (substream `spectrum` do dano), com 4 modos de Draper. O `telemetry-datalogger` só converte para `KnockSpectrum` (256 bins, dB 1 casa). | 🟡 |
| D-WS-09 | Código de fecho 4408 sem `reason` definido. | `telemetry-datalogger` §8 | `reason = WS_IDLE_TIMEOUT` (texto de fecho, não registado no catálogo HTTP). | 🟡 |
| D-WS-10 | Campos `realtime_factor` e `forensic_report_url` em `run.state` não constavam no exemplo. | `dyno-bench` §8 (estados da UI), `engine-physics-core` Fluxo B | Acrescentados ao payload de `run.state` como opcionais. | 🟡 |
