# Contrato: API REST `/api/v1/`

> Feature: `001-simulador-remap` · Fase: plan · Gerado em 2026-10-18 (modo autônomo, greenfield)
> Confidência: 🟢 CONFIRMADO, 🟡 INFERIDO (padrão: specs planejadas), 🔴 LACUNA / DÚVIDA
> Índice: `_reversa_sdd/sdd/platform-foundation.md#8-design-e-interface` ("Catálogo consolidado de endpoints (revisão R1)").
> Delta: componente-novo para todos os endpoints (greenfield, sem legado).

## 1. Convenções transversais

Fonte: `_reversa_sdd/sdd/platform-foundation.md#8-design-e-interface` (RF-03, RF-05, RF-14, RF-16, RF-23, RF-24).

- 🟡 Prefixo único `/api/v1/` para REST e `/ws/v1/` para WebSocket. O registo `simremap.api.registry` recusa outro prefixo no arranque com `RouterPrefixError`.
- 🟡 Um teste de contrato compara o `openapi.json` com a tabela da seção 3. Este documento é a fonte desse teste.
- 🟡 Corpo de pedido e de resposta em `application/json` (UTF-8). Erros em `application/problem+json` com `ProblemDetail` (seção 2).
- 🟡 Sem autenticação (local-first, porta em `127.0.0.1`). CORS só para `http://localhost:<porta>` e `http://127.0.0.1:<porta>`, sem credenciais.
- 🟡 Limite de corpo padrão: 16 MiB (`SIMREMAP_MAX_BODY_BYTES`). Override por rota com `body_limit(bytes)`. Excesso: 413 `PAYLOAD_TOO_LARGE`, sem chamar o handler.
- 🟡 Cabeçalhos de segurança em toda resposta: `Content-Security-Policy` (`'self'`, `connect-src 'self' ws://localhost:* ws://127.0.0.1:*`), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`.
- 🟡 Identificadores: `session_id` UUID4 hex; `run_id` ULID; `calibration_id` UUID; `vehicle_id` slug `^[0-9a-z]+(-[0-9a-z]+){1,5}$`; `profile_id` de ECU ∈ {`oem-stage`, `ft-pro`, `m1-race`, `ht-elite`}; `profile_id` de jogador UUID4; `scenario_id` slug; `attempt_id` UUID4.
- 🟡 Datas em ISO 8601 UTC. Tempo simulado em `t_sim_s` (segundos, `tick / sim_hz`).
- 🟡 Valores numéricos em unidades SI práticas com sufixo no nome (`_kpa`, `_c`, `_nm`, `_kw`, `_pct`, `_deg`, `_ms`).

### 1.1 Cabeçalhos

| Cabeçalho | Direção | Endpoints | Regra | Fonte |
|---|---|---|---|---|
| 🟡 `X-Request-ID` | pedido e resposta | todos | Valor do cliente aceito se tiver ≤ 64 caracteres `[0-9A-Za-z-]`; senão o servidor gera UUID4. O mesmo valor vai para `ProblemDetail.request_id`. | `platform-foundation.md#6-requisitos-funcionais` (RF-14, EC-14) |
| 🟡 `X-Player-Profile-Id` | pedido | tentativas, cenário de instrutor, pacotes (ver seção 3.8) | Ausente em endpoint obrigatório: 400 `PLAYER_PROFILE_REQUIRED`. UUID inexistente: 404 `PLAYER_PROFILE_NOT_FOUND`. | `training-scenarios.md#6-requisitos-funcionais` (RF-02) |
| 🟡 `Location` | resposta | 201 e 202 que criam recurso legível por `GET` | URL relativa do recurso criado. Obrigatório em `POST /api/v1/calibrations` (spec). Estendido aos outros 201/202 com `GET` próprio (decisão D-REST-07). | `ecu-core.md#8-design-e-interface` |
| 🟡 `ETag` / `If-None-Match` | resposta / pedido | 3 endpoints de `vehicle-catalog` | `ETag` = `catalog_sha256`. Pedido com `If-None-Match` igual devolve 304 sem corpo. `Cache-Control: no-cache` em 200. | `vehicle-catalog.md#6-requisitos-funcionais` (RF-17) |
| 🟡 `Retry-After` | resposta | 409 `FORENSIC_REPORT_PENDING` (1 s); 503 `DATABASE_UNAVAILABLE` (2 s) | Segundos inteiros. | `knock-and-failure-model.md#8-design-e-interface`; `ecu-core.md#11-edge-cases-e-tratamento-de-erros` (EC-09) |
| 🟡 `X-Log-Sha256` | resposta | `GET /api/v1/runs/{run_id}/log` | SHA-256 canónico do log (`contracts/file-formats.md` seção 4.4). | `telemetry-datalogger.md#8-design-e-interface` |
| 🟡 `X-Simremap-Persisted` | resposta | `GET /api/v1/runs/{run_id}/forensic-report` | `false` quando o laudo ficou só em memória por falha do banco. | `knock-and-failure-model.md#10-integrações-e-dependências` |
| 🟡 `Content-Disposition` | resposta | export de log e de pacote | `attachment; filename="run-<run_id>.json"` ou `.csv`; pacote `simremap-<kind>-<id>-<8 hex>.simremap.json`. | `telemetry-datalogger.md` RF-17; `training-scenarios.md` RF-18 |
| 🟡 `Content-Encoding: gzip` | pedido | `POST /api/v1/logs/import` | Opcional. O limite de 64 MB vale para o corpo descomprimido. | `telemetry-datalogger.md` RF-18 |

### 1.2 Paginação

- 🟡 Offset: `GET /api/v1/calibrations` com `limit` 1–200 (padrão 50) e `offset` ≥ 0. Resposta `CalibrationPage {items, total}`. Fonte: `ecu-core.md#8-design-e-interface`.
- 🟡 Cursor: `GET /api/v1/attempts` com `limit` 1–200 (padrão 50) e `cursor` opaco. Resposta `AttemptPage {items, next_cursor}`; `next_cursor = null` no fim. Fonte: `training-scenarios.md` RF-23.
- 🟡 Os outros endpoints de lista devolvem a coleção inteira, porque o tamanho é limitado pelo domínio (4 veículos, 4 perfis, ≤ 100 perfis de jogador, ≤ 128 canais por veículo).

### 1.3 Timeouts e prazos

| Prazo | Valor | Efeito | Fonte |
|---|---|---|---|
| 🟡 Timeout do cliente REST da UI | 5 s | Estado de erro com "Tentar de novo" | `vehicle-catalog.md` EC-16 |
| 🟡 Confirmação do worker para aplicar calibração | 100 ms | 504 `CALIBRATION_APPLY_TIMEOUT`, pedido cancelado | `ecu-core.md` EC-08; `ecu-profiles.md` EC-05 |
| 🟡 Arranque do worker de sessão | 5 s | 503 `SIM_WORKER_UNAVAILABLE` | `platform-foundation.md#8-design-e-interface` |
| 🟡 Heartbeat do worker | 2 s sem resposta | Sessão marcada como falhada; 503 `SIM_WORKER_UNAVAILABLE` | `platform-foundation.md` EC-04 |
| 🟡 `arming` | 10 s | Puxada `aborted` com `arming_timeout` | `dyno-bench.md#8-design-e-interface` |
| 🟡 `running` | 60 s | Puxada `aborted` com `run_timeout` | `dyno-bench.md` EC-05 |
| 🟡 `coastdown` | 15 s | `completed` com evento `coastdown_timeout` | `dyno-bench.md#8-design-e-interface` |
| 🟡 Geração do laudo forense | P95 ≤ 500 ms; corte em 5 s | Laudo mínimo (falha + 1 elo) e log `forensic.timeout` | `knock-and-failure-model.md` EC-07 |
| 🟡 Gravação do log após estado terminal | ≤ 2 s | Antes disso, 409 `LOG_NOT_READY` | `telemetry-datalogger.md` RF-15 |
| 🟡 Puxada base automática da tentativa | 120 s | Tentativa `failed_to_start` (`BASELINE_FAILED`) | `training-scenarios.md` EC-13 |
| 🟡 Leitura do traço de avaliação | 2 s, 3 retries (200/400/800 ms) | Avaliação `status = error`, `TRACE_UNAVAILABLE` | `training-scenarios.md` EC-04 |
| 🟡 Health: `SELECT 1` / Redis `PING` | 1 s / 0,5 s | `down` / `degraded` | `platform-foundation.md#8-design-e-interface` |

## 2. Formato de erro RFC 7807 (`ProblemDetail`)

Fonte: `_reversa_sdd/sdd/platform-foundation.md#8-design-e-interface` ("Contratos de erro (RFC 7807)").

```python
from pydantic import BaseModel, ConfigDict, Field

class FieldError(BaseModel):
    loc: list[str | int]
    msg: str
    type: str

class ProblemDetail(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)   # extra: campos do componente (ex.: row, col, latest_version)
    type: str = Field(..., examples=["urn:simremap:problem:vehicle-not-found"])
    title: str = Field(..., max_length=120)
    status: int = Field(..., ge=400, le=599)
    detail: str = Field(..., max_length=2000)                # pt-BR, sem stack trace nem caminhos
    code: str = Field(..., pattern=r"^[A-Z][0-9A-Z_]{2,63}$")
    request_id: str = Field(..., max_length=64)
    instance: str | None = None                              # caminho do pedido, sem query string
    errors: list[FieldError] | None = None                   # só em 422 VALIDATION_FAILED
```

- 🟡 `type` = `urn:simremap:problem:` + `code` em minúsculas com `_` trocado por `-`.
- 🟡 `RequestValidationError` do FastAPI vira 422 `VALIDATION_FAILED` com `errors` preenchido.
- 🟡 Cada componente regista os seus códigos com `register_error(code, status, title)`. Código repetido com status diferente lança `ErrorCodeConflict` no arranque. `GET /api/v1/version` expõe `error_catalog_sha256`.
- 🟡 Campos extra por domínio (via `extra="allow"`): erros de célula (`table_id`, `row`, `col`, `value`, `min`, `max`), conflito de versão (`latest_version`), base de ECU (`field`, `reason`), hash (`expected_sha256`, `actual_sha256`), resume (`oldest_available_seq`, só no WS), setup (`pending`).

Exemplo:

```json
{
  "type": "urn:simremap:problem:table-value-out-of-range",
  "title": "Valor fora do limite da tabela",
  "status": 422,
  "detail": "A célula (4, 9) da tabela ve vale 151,0 e o máximo é 150,0.",
  "code": "TABLE_VALUE_OUT_OF_RANGE",
  "request_id": "6c1f0a7e-1d2b-4c3a-9f10-2b3c4d5e6f70",
  "instance": "/api/v1/calibrations/0f5e.../tables/ve",
  "table_id": "ve", "row": 4, "col": 9, "value": 151.0, "min": 0.0, "max": 150.0
}
```

## 3. Endpoints por componente dono

Total: 45 endpoints REST (mais 1 WebSocket, descrito em `contracts/websocket-telemetry.md`).

Legenda de idempotência: **Seguro** = sem efeito colateral; **Idempotente** = repetir dá o mesmo estado; **Não idempotente** = repetir cria efeito novo ou erro de estado.

### 3.1 platform-foundation (2)

Fonte: `_reversa_sdd/sdd/platform-foundation.md#8-design-e-interface`, RF-07, RF-08.

**E-01 `GET /api/v1/health`**
- 🟡 Request: sem corpo.
- 🟡 Response: 200 `HealthStatus {status: ok|degraded|down, checks: {database, redis, sim_worker: HealthCheck}, uptime_s, active_sessions}` quando `ok` ou `degraded`.
- 🟡 Erros: 503 `SERVICE_UNAVAILABLE` quando `database = down`.
- 🟡 Idempotência: seguro. Limite: P95 < 50 ms com 1 sessão a 1000 Hz.

**E-02 `GET /api/v1/version`**
- 🟡 Response: 200 `VersionInfo {app_version (SemVer), api_version = "v1", ws_envelope_version = 1, package_format_version = 1, datalog_format_version = 1, alembic_head, error_catalog_sha256, git_sha?, build_time_utc?, python_version}`.
- 🟡 Erros: só os transversais (500 `INTERNAL_ERROR`).
- 🟡 Idempotência: seguro. Limite: P95 < 20 ms.

### 3.2 vehicle-catalog (3)

Fonte: `_reversa_sdd/sdd/vehicle-catalog.md#8-design-e-interface`, `#9-modelo-de-dados`, RF-14 a RF-17, RF-29.

**E-03 `GET /api/v1/vehicles`**
- 🟡 Query: `include_drafts: bool = false`.
- 🟡 Response: 200 `VehicleListResponse {catalog_version, catalog_sha256, items: list[VehicleSummary]}`. Cabeçalho `ETag`.
- 🟡 Erros: 304 (sem corpo, `If-None-Match` igual); 422 `VALIDATION_FAILED`.
- 🟡 Idempotência: seguro.

**E-04 `GET /api/v1/vehicles/{vehicle_id}`**
- 🟡 Path: `vehicle_id` slug.
- 🟡 Response: 200 `VehicleDetail` (= `VehicleSpec` + `estimated_fields`, `data_sha256`, `catalog_version`, `fuels`). Veículo `draft` devolve 200 com `validation_status = "draft"`. Cabeçalho `ETag`.
- 🟡 Erros: 404 `VEHICLE_NOT_FOUND`; 422 `VEHICLE_ID_INVALID`; 304.
- 🟡 Idempotência: seguro. O `vehicle_id` nunca vira caminho de ficheiro (catálogo em memória).

**E-05 `GET /api/v1/vehicles/{vehicle_id}/reference-curves`**
- 🟡 Query: `fuel_id` (opcional, `e27|e100|podium|e0`), `calibration_ref` (padrão `stock`).
- 🟡 Response: 200 `ReferenceCurveListResponse {vehicle_id, catalog_sha256, benchmark_id = "reference-benchmark-baseline-v1", benchmark_sha256, items: list[ReferenceCurve]}`. Cabeçalho `ETag`.
- 🟡 Erros: 404 `VEHICLE_NOT_FOUND`; 404 `REFERENCE_CURVE_NOT_FOUND`; 422 `VALIDATION_FAILED`; 304.
- 🟡 Idempotência: seguro. `benchmark_sha256` igual nas 4 respostas (RF-29).

### 3.3 dyno-bench (6)

Fonte: `_reversa_sdd/sdd/dyno-bench.md#8-design-e-interface`, `#9-modelo-de-dados`, `#11-edge-cases-e-tratamento-de-erros`, RF-01, RF-02, RF-17, RF-20 a RF-26.

**E-06 `POST /api/v1/sessions`**
- 🟡 Request: `SessionCreateRequest {vehicle_id, calibration_id?, profile_id = "oem-stage", seed?, sim_hz = 1000 (100–1000), ambient: AmbientConditions, correction_standard = sae_j1349, rig: DynoRigConfig, operator_protection = false, egt_abort_enabled = true, damage_enabled = true, fuel_id?, physics_faults: list[PhysicsFault] (≤ 8), attempt_id?}`.
- 🟡 Response: 201 `SimulationSession` (inclui `session_id`, `seed` efetiva, `state = "ready"`, `engine_locked`, `ecu_state`, `created_at`). Cabeçalho `Location: /api/v1/sessions/{session_id}`.
- 🟡 Erros: 404 `VEHICLE_NOT_FOUND`; 404 `CALIBRATION_NOT_FOUND`; 404 `ECU_PROFILE_NOT_FOUND`; 409 `SIM_CAPACITY_EXCEEDED` (`detail` com o `session_id` ativo); 409 `VEHICLE_NOT_VALIDATED`; 409 `FUEL_NOT_ALLOWED`; 422 `VALIDATION_FAILED`; 422 `CALIBRATION_VEHICLE_MISMATCH`; 503 `SIM_WORKER_UNAVAILABLE`; 503 `PHYSICS_UNAVAILABLE`; 503 `DAMAGE_MODEL_UNAVAILABLE`; 503 `DATABASE_UNAVAILABLE`.
- 🟡 Idempotência: não idempotente. O limite `max_active_sessions` (padrão 1, máximo 2) impede duplicação por retry: o segundo pedido recebe 409.
- 🟡 Limites: `seed` omitida é gerada em 0..2^63−1 e devolvida (RF-23). Construção da física ≤ 200 ms.

**E-07 `GET /api/v1/sessions/{session_id}`**
- 🟡 Response: 200 `SimulationSession` (com `active_run_id`, `baseline_run_id`, `engine_locked`, `realtime_factor`, `t_sim_s`, `ecu_state`).
- 🟡 Erros: 404 `SESSION_NOT_FOUND`.
- 🟡 Idempotência: seguro.

**E-08 `DELETE /api/v1/sessions/{session_id}`**
- 🟡 Response: 204. Aborta a puxada ativa com `abort_reason = session_closed`, para o worker em < 1 s e liberta o slot. Fecha os WebSockets da sessão com 1000.
- 🟡 Erros: 404 `SESSION_NOT_FOUND`.
- 🟡 Idempotência: idempotente no estado; a repetição devolve 404.

**E-09 `POST /api/v1/sessions/{session_id}/runs`**
- 🟡 Request: `DynoRunRequest {run_type: baseline_pull|sweep_pull|steady_state_hold|multi_pull, gear = 4, start_rpm = 2000, end_rpm?, pedal_pct = 100, ramp_rate_rpm_s = 300 (50–1000), cells (≤ 64, obrigatório só em steady_state_hold), cell_timeout_s = 10, pull_count = 3 (2–10), pull_type, cooldown_s = 60 (0–600), fan_on = true, smoothing_window = 5 (ímpar 1–11), label?, probe: ProbeOverrides?}`.
- 🟡 Response: 202 `DynoRun` com `state = "arming"`. Cabeçalho `Location: /api/v1/runs/{run_id}`. O progresso segue por `run.state` no WebSocket.
- 🟡 Erros: 404 `SESSION_NOT_FOUND`; 409 `RUN_IN_PROGRESS`; 409 `ENGINE_DESTROYED` (`detail` aponta `POST .../engine/restore`); 409 `SESSION_CLOSED`; 409 `ECU_SETUP_INCOMPLETE` (com `pending`); 422 `VALIDATION_FAILED`; 422 `RPM_RANGE_INVALID` (`end_rpm ≤ start_rpm + 500`); 422 `GEAR_NOT_AVAILABLE`; 422 `PROBE_NOT_ALLOWED` (`probe` sem `attempt_id` na sessão); 503 `SIM_WORKER_BUSY`; 503 `DATABASE_UNAVAILABLE`.
- 🟡 Idempotência: não idempotente; a repetição durante a puxada recebe 409 `RUN_IN_PROGRESS`.
- 🟡 Limites: P95 < 200 ms. `end_rpm` limitado a `rev_limit_rpm`; omitido vale `rev_limit_rpm − 200`.

**E-10 `POST /api/v1/sessions/{session_id}/runs/{run_id}/abort`**
- 🟡 Request: corpo vazio.
- 🟡 Response: 200 `DynoRun` com `state = "aborted"`, `abort_reason = "user_abort"`.
- 🟡 Erros: 404 `RUN_NOT_FOUND`; 404 `SESSION_NOT_FOUND`; 409 `RUN_NOT_ACTIVE`.
- 🟡 Idempotência: não idempotente; a repetição recebe 409 `RUN_NOT_ACTIVE`.

**E-11 `GET /api/v1/runs/{run_id}`**
- 🟡 Query: `include_curve: bool = true`, `curve: raw|smoothed = smoothed`.
- 🟡 Response: 200 `DynoRun {run_id, session_id, run_type, request, state, abort_reason?, started_at_tick, ended_at_tick?, calibration_id, calibration_hash, seed, sim_hz, summary: RunSummary?, curve, pulls, repeatability?, curve_sha256?}`. Campo `persisted = false` quando a gravação falhou (EC-04).
- 🟡 Erros: 404 `RUN_NOT_FOUND`; 422 `VALIDATION_FAILED`.
- 🟡 Idempotência: seguro. Limite: P95 < 100 ms com curva de até 400 pontos. A curva suavizada é recalculada na leitura.

### 3.4 knock-and-failure-model (3)

Fonte: `_reversa_sdd/sdd/knock-and-failure-model.md#8-design-e-interface`, `#9-modelo-de-dados`, RF-20, RF-21, RF-27.

**E-12 `GET /api/v1/sessions/{session_id}/engine/health`**
- 🟡 Query: `include_failures: bool = true`.
- 🟡 Response: 200 `EngineHealth {session_id, vehicle_id, t_sim_s, damage_enabled, engine_locked, components: list[ComponentHealth], min_health, integrity_pct, intact, failures, restore_count, last_forensic_report_url?}` (≤ 8 KB). Com worker morto, devolve o último estado persistido com `t_sim_s` antigo.
- 🟡 Erros: 404 `SESSION_NOT_FOUND`; 503 `SIM_WORKER_UNAVAILABLE`.
- 🟡 Idempotência: seguro.

**E-13 `POST /api/v1/sessions/{session_id}/engine/restore`**
- 🟡 Request: `EngineRestoreRequest {note?: str ≤ 120}` (corpo opcional).
- 🟡 Response: 200 `EngineHealth` com todas as saúdes em 1,0, `engine_locked = false` e `restore_count` + 1. O worker chama `PhysicsEngine.reset_mechanical()`.
- 🟡 Erros: 404 `SESSION_NOT_FOUND`; 409 `RUN_IN_PROGRESS`; 409 `SESSION_CLOSED`; 503 `SIM_WORKER_UNAVAILABLE`.
- 🟡 Idempotência: idempotente na saúde; `restore_count` cresce a cada chamada (EC-10).

**E-14 `GET /api/v1/runs/{run_id}/forensic-report`**
- 🟡 Query: `audience: beginner|intermediate|instructor|all = all`.
- 🟡 Response: 200 `ForensicReport` (≤ 64 KB) com `report_sha256`. Cabeçalho `X-Simremap-Persisted: false` quando o laudo ficou só em memória.
- 🟡 Erros: 404 `RUN_NOT_FOUND`; 404 `FORENSIC_REPORT_NOT_FOUND`; 409 `FORENSIC_REPORT_PENDING` com `Retry-After: 1`; 422 `VALIDATION_FAILED`.
- 🟡 Idempotência: seguro. Limite: P95 ≤ 100 ms com laudo persistido.

### 3.5 ecu-core (6)

Fonte: `_reversa_sdd/sdd/ecu-core.md#8-design-e-interface`, `#9-modelo-de-dados`, `#11-edge-cases-e-tratamento-de-erros`, RF-25 a RF-28.

**E-15 `GET /api/v1/calibrations`**
- 🟡 Query: `vehicle_id?`, `profile_id?`, `limit` 1–200 (padrão 50), `offset` ≥ 0.
- 🟡 Response: 200 `CalibrationPage {items: list[CalibrationSummary], total}`. `CalibrationSummary {calibration_id, vehicle_id, profile_id, name, latest_version, content_hash, updated_at}` (campos derivados da tabela `calibration`, decisão D-REST-05).
- 🟡 Erros: 422 `VALIDATION_FAILED`.
- 🟡 Idempotência: seguro. `total = 0` é o estado vazio da UI.

**E-16 `POST /api/v1/calibrations`**
- 🟡 Request: `CalibrationCreate {vehicle_id, profile_id, metadata: CalibrationMetadata, source: clone|payload|reference, clone_from_id?, clone_from_version?, fuel_model?, tables?, strategies?}`.
- 🟡 Response: 201 `Calibration` (versão 1, `content_hash` calculado pelo servidor). Cabeçalho `Location: /api/v1/calibrations/{calibration_id}`.
- 🟡 Erros: 404 `VEHICLE_NOT_FOUND`; 404 `ECU_PROFILE_NOT_FOUND`; 404 `CALIBRATION_NOT_FOUND` (clone); 422 `TABLE_*` (seção 4); 422 `STRATEGY_NOT_SUPPORTED_BY_PROFILE`; 422 `STRATEGY_CONFIG_INVALID`; 422 `TABLE_NOT_SUPPORTED_BY_PROFILE`; 422 `STRATEGY_REQUIRES_PACKAGE`; 422 `STRATEGY_OPTION_NOT_SUPPORTED`; 422 `VALIDATION_FAILED`; 503 `DATABASE_UNAVAILABLE` com `Retry-After: 2`.
- 🟡 Idempotência: não idempotente (cada chamada cria `calibration_id` novo). Transação única: nada é gravado em erro.

**E-17 `GET /api/v1/calibrations/{calibration_id}`**
- 🟡 Query: `version?` (padrão: última), `include=versions` (lista `CalibrationVersionInfo`).
- 🟡 Response: 200 `Calibration` (+ `versions`). Campos só de leitura fora do hash: `min`/`max` por tabela, `unit` e `source_channel` por eixo.
- 🟡 Erros: 404 `CALIBRATION_NOT_FOUND`; 404 `CALIBRATION_VERSION_NOT_FOUND`.
- 🟡 Idempotência: seguro. A linhagem que a `ecu-tuning-ui` pedia por `?lineage=` sai de `include=versions` (decisão D-REST-03).

**E-18 `PUT /api/v1/calibrations/{calibration_id}`**
- 🟡 Request: `CalibrationReplace {base_version, fuel_model, tables, strategies, profile_params, metadata}` ou `{base_version, revert_to_version}`.
- 🟡 Response: 200 `Calibration` (nova versão imutável, `parent_version = base_version`).
- 🟡 Erros: 404 `CALIBRATION_NOT_FOUND`; 409 `CALIBRATION_VERSION_CONFLICT` (com `latest_version`); 409 `CALIBRATION_VERSION_LIMIT` (1001.ª versão); 422 `TABLE_*`; 422 `CALIBRATION_PROFILE_IMMUTABLE`; 422 `STRATEGY_CONFIG_INVALID`; 503 `DATABASE_UNAVAILABLE`.
- 🟡 Idempotência: concorrência otimista por `base_version`. O retry com a mesma `base_version` recebe 409 e não cria versão dupla.

**E-19 `PATCH /api/v1/calibrations/{calibration_id}/tables/{table_id}`**
- 🟡 Request: `TablePatch {base_version, op: set|add|scale = set, cells: list[CellEdit {row, col, value}] (≤ 1024), x_values?, y_values?, change_summary?}`.
- 🟡 Response: 200 `TablePatchResult {version, content_hash, table}`.
- 🟡 Erros: 404 `CALIBRATION_NOT_FOUND`; 404 `TABLE_NOT_FOUND`; 409 `CALIBRATION_VERSION_CONFLICT`; 409 `CALIBRATION_VERSION_LIMIT`; 422 `TABLE_VALUE_OUT_OF_RANGE`; 422 `TABLE_VALUE_NOT_FINITE`; 422 `TABLE_AXIS_NOT_MONOTONIC`; 422 `PATCH_TOO_LARGE`; 422 `PATCH_CELL_OUT_OF_BOUNDS`; 503 `DATABASE_UNAVAILABLE`.
- 🟡 Idempotência: concorrência otimista por `base_version`. A UI agrupa edições com debounce de 300 ms.

**E-20 `POST /api/v1/sessions/{session_id}/calibration`**
- 🟡 Request: `ApplyCalibrationRequest {calibration_id, version?, profile_options: dict[str, bool]}`.
- 🟡 Response: 200 `ApplyCalibrationResult {session_id, calibration_id, version, content_hash, mode: full|live_tables, changed_tables, applied_t_sim_s}`. A troca é atómica numa fronteira de tick.
- 🟡 Erros: 404 `SESSION_NOT_FOUND`; 404 `CALIBRATION_NOT_FOUND`; 409 `TABLE_NOT_LIVE_TUNABLE` (lista de tabelas); 422 `CALIBRATION_PROFILE_MISMATCH`; 422 `CALIBRATION_VEHICLE_MISMATCH`; 422 `OEM_CHECKSUM_INVALID` (hook do perfil, com `stored` e `expected`); 422 `OEM_TORQUE_MODEL_NOT_MONOTONIC`; 503 `SIM_WORKER_BUSY`; 504 `CALIBRATION_APPLY_TIMEOUT`.
- 🟡 Idempotência: idempotente; reaplicar a mesma versão devolve `changed_tables = []`.
- 🟡 Timeout: 100 ms para a confirmação do worker; depois o pedido é cancelado e nenhum tick usa a versão nova.

### 3.6 ecu-profiles (5)

Fonte: `_reversa_sdd/sdd/ecu-profiles.md#8-design-e-interface`, `#9-modelo-de-dados`, `#11-edge-cases-e-tratamento-de-erros`, RF-03, RF-17, RF-20.

**E-21 `GET /api/v1/ecu-profiles`**
- 🟡 Response: 200 `list[EcuProfileSummary {profile_id, name, family: oem|standalone, inspiration, descriptor_version}]`. O perfil OEM chama-se "OEM-Stage" (id `oem-stage`).
- 🟡 Erros: 500 `PROFILE_REGISTRY_INVALID`.
- 🟡 Idempotência: seguro.

**E-22 `GET /api/v1/ecu-profiles/{profile_id}`**
- 🟡 Query: `vehicle_id?`.
- 🟡 Response: 200 `EcuProfileDescriptor` (inclui `navigation`, `live_tunable_table_ids`, `load_axis_channel`, `accent_color`, `tables`, `strategies`, `terminology`, `display_units`, `requires_base_setup`, `base_setup_steps`, `feature_packages`).
- 🟡 Erros: 404 `ECU_PROFILE_NOT_FOUND`; 404 `VEHICLE_NOT_FOUND`; 500 `PROFILE_REGISTRY_INVALID`.
- 🟡 Idempotência: seguro.

**E-23 `POST /api/v1/sessions/{session_id}/ecu/swap`**
- 🟡 Request: `SwapRequest {target_profile_id, confirm_snapshot, feature_package: base|race = base, prefill_from_hardware_sheet = false, request_id? (≤ 64)}`.
- 🟡 Response: 200 `SwapResult {session_id, previous_profile_id, profile_id, ecu_state, oem_snapshot?, base_setup_version?, calibration_id?, checklist, hardware_sheet}`.
- 🟡 Erros: 404 `SESSION_NOT_FOUND`; 404 `ECU_PROFILE_NOT_FOUND`; 409 `RUN_IN_PROGRESS`; 409 `SESSION_CLOSED`; 422 `SWAP_TARGET_INVALID`; 422 `SWAP_CONFIRMATION_REQUIRED`; 422 `SWAP_NOT_SUPPORTED_FOR_VEHICLE`; 503 `DATABASE_UNAVAILABLE` com `Retry-After: 2`.
- 🟡 Idempotência: por `request_id` durante 10 min (devolve o mesmo `SwapResult`, sem novo snapshot). Transação única com rollback.

**E-24 `GET /api/v1/sessions/{session_id}/ecu/base-setup`**
- 🟡 Response: 200 `BaseSetupResult` (sem gerar calibração).
- 🟡 Erros: 404 `SESSION_NOT_FOUND`.
- 🟡 Idempotência: seguro. `hardware_override_json` nunca é exposto.

**E-25 `PUT /api/v1/sessions/{session_id}/ecu/base-setup`**
- 🟡 Request: `BaseSetupUpdate {base_version? (None só na 1.ª gravação), base_setup: BaseSetup, generate_base_map = false, wizard: WizardInputs?, apply_limits_to_calibration = true}`.
- 🟡 Response: 200 `BaseSetupResult {session_id, profile_id, editable, ecu_state, base_setup_version, base_setup, setup_hash, checklist, hardware_sheet, calibration_id?, calibration_version?, estimated_peak_duty_pct?, warnings}`.
- 🟡 Erros: 404 `SESSION_NOT_FOUND`; 409 `BASE_SETUP_NOT_EDITABLE_OEM`; 409 `BASE_SETUP_VERSION_CONFLICT`; 409 `RUN_IN_PROGRESS`; 422 `BASE_SETUP_INVALID` (com `field` e `reason`); 422 `WIZARD_INPUT_INVALID`; 422 `TABLE_*`; 503 `DATABASE_UNAVAILABLE`; 504 `CALIBRATION_APPLY_TIMEOUT` (base gravada, item `base_map` em `invalid`).
- 🟡 Idempotência: concorrência otimista por `base_version`.

### 3.7 telemetry-datalogger (4 REST + 1 WS)

Fonte: `_reversa_sdd/sdd/telemetry-datalogger.md#8-design-e-interface`, `#9-modelo-de-dados`, RF-04, RF-17 a RF-19. O WebSocket está em `contracts/websocket-telemetry.md`.

**E-26 `GET /api/v1/telemetry/channels`**
- 🟡 Query: `vehicle_id` (obrigatório).
- 🟡 Response: 200 `list[TelemetryChannel {name, base, cylinder?, unit, kind, aggregation, decimals, min_value?, max_value?, source, nullable}]`, expandido por cilindro (`<base>_cyl<k>`).
- 🟡 Erros: 404 `VEHICLE_NOT_FOUND`; 422 `VALIDATION_FAILED`.
- 🟡 Idempotência: seguro.

**E-27 `GET /api/v1/runs/{run_id}/log`**
- 🟡 Query: `format: json|csv = json`; `channels` (lista separada por vírgula, só CSV); `decimate` (1–100, só CSV).
- 🟡 Response: 200 `application/json` (`DataLog`) ou `text/csv; charset=utf-8` em streaming. Cabeçalhos `X-Log-Sha256` e `Content-Disposition`.
- 🟡 Erros: 404 `RUN_NOT_FOUND`; 404 `LOG_NOT_FOUND`; 409 `LOG_NOT_READY`; 422 `VALIDATION_FAILED` (ex.: `format=xml`); 500 `LOG_CORRUPTED`; 507 `STORAGE_FULL`.
- 🟡 Idempotência: seguro. Limite: CSV de 15 s a 1000 Hz em ≤ 1,5 s.

**E-28 `POST /api/v1/logs/import`**
- 🟡 Request: `application/json` com `DataLog` (≤ 64 MB, `Content-Encoding: gzip` opcional, profundidade JSON ≤ 32, ≤ 256 canais).
- 🟡 Response: 201 `DataLogSummary {log_id ("imp-" + 12 hex), run_id?, vehicle_id, sha256, n_samples, sim_hz, source = imported}`.
- 🟡 Erros: 409 `LOG_ALREADY_IMPORTED` (`detail` com o `log_id` existente); 413 `PAYLOAD_TOO_LARGE`; 415 `UNSUPPORTED_MEDIA_TYPE`; 422 `LOG_SCHEMA_INVALID`; 422 `LOG_FORMAT_UNSUPPORTED`; 422 `LOG_HASH_MISMATCH` (`expected` e `computed`); 507 `STORAGE_FULL`.
- 🟡 Idempotência: idempotente pelo `sha256` (a repetição recebe 409 com o `log_id` a reutilizar). Nada é gravado em erro.

**E-29 `POST /api/v1/logs/compare`**
- 🟡 Request: `LogCompareRequest {a: LogRef, b: LogRef, bin_rpm = 100 (50–500), pull_index_a?, pull_index_b?, min_samples_per_bin = 5}`; `LogRef` exige exatamente um de `run_id` ou `log_id`.
- 🟡 Response: 200 `LogComparison` (bins comuns B − A, picos, `vehicle_mismatch`).
- 🟡 Erros: 404 `LOG_NOT_FOUND`; 409 `LOG_NOT_READY`; 422 `LOG_COMPARE_NO_OVERLAP`; 422 `VALIDATION_FAILED`; 500 `LOG_CORRUPTED`.
- 🟡 Idempotência: seguro (função pura sobre logs imutáveis). Limite: ≤ 500 ms para 2 logs de 15 s.

### 3.8 training-scenarios (16)

Fonte: `_reversa_sdd/sdd/training-scenarios.md#8-design-e-interface`, `#9-modelo-de-dados`, `#11-edge-cases-e-tratamento-de-erros`, RF-01 a RF-27.

Coluna "Perfil" indica o uso de `X-Player-Profile-Id`: **obr.** = obrigatório; **opc.** = opcional; **—** = não usado.

| # | Método e caminho | Perfil |
|---|---|---|
| E-30 | `GET /api/v1/profiles` | — |
| E-31 | `POST /api/v1/profiles` | — |
| E-32 | `GET /api/v1/scenarios` | opc. |
| E-33 | `POST /api/v1/scenarios` | obr. (instrutor) |
| E-34 | `GET /api/v1/scenarios/{scenario_id}` | opc. |
| E-35 | `GET /api/v1/scenarios/{scenario_id}/stats` | — |
| E-36 | `POST /api/v1/scenarios/{scenario_id}/attempts` | obr. |
| E-37 | `GET /api/v1/attempts` | obr. |
| E-38 | `GET /api/v1/attempts/{attempt_id}` | obr. |
| E-39 | `POST /api/v1/attempts/{attempt_id}/hints` | obr. |
| E-40 | `POST /api/v1/attempts/{attempt_id}/abandon` | obr. |
| E-41 | `POST /api/v1/attempts/{attempt_id}/submit` | obr. |
| E-42 | `GET /api/v1/attempts/{attempt_id}/evaluation` | obr. |
| E-43 | `POST /api/v1/attempts/{attempt_id}/replay` | obr. (instrutor) |
| E-44 | `POST /api/v1/packages/export` | obr. |
| E-45 | `POST /api/v1/packages/import` | obr. (instrutor para `kind = attempt`) |

Erros comuns a todo endpoint com perfil **obr.**: 400 `PLAYER_PROFILE_REQUIRED`; 404 `PLAYER_PROFILE_NOT_FOUND`. Endpoints com perfil **opc.** devolvem 404 `PLAYER_PROFILE_NOT_FOUND` só quando o cabeçalho vem com UUID inexistente.

**E-30 `GET /api/v1/profiles`**
- 🟡 Response: 200 `list[PlayerProfile {profile_id, nickname, role, created_at}]`.
- 🟡 Idempotência: seguro.

**E-31 `POST /api/v1/profiles`**
- 🟡 Request: `PlayerProfileCreate {nickname (^[-_0-9A-Za-z]{3,24}$), role: student|instructor = student}`. Nenhum outro campo pessoal.
- 🟡 Response: 201 `PlayerProfile`.
- 🟡 Erros: 409 `NICKNAME_TAKEN` (sem distinção de maiúsculas); 409 `PROFILE_LIMIT_REACHED` (101.º perfil); 422 `VALIDATION_FAILED`.
- 🟡 Idempotência: não idempotente; a repetição recebe 409 `NICKNAME_TAKEN`.

**E-32 `GET /api/v1/scenarios`**
- 🟡 Query: `kind: base|challenge` (opcional).
- 🟡 Response: 200 `list[ScenarioSummary {scenario_id, kind, title, vehicle_id, fuel_id, has_hidden_defect, available, last_evaluation_passed?}]`.
- 🟡 Erros: 422 `VALIDATION_FAILED`.
- 🟡 Idempotência: seguro.

**E-33 `POST /api/v1/scenarios`**
- 🟡 Request: `ScenarioCreate {scenario: Scenario, initial_calibration_id?}`.
- 🟡 Response: 201 `Scenario` com `scenario_sha256` (JCS). Cabeçalho `Location: /api/v1/scenarios/{scenario_id}`.
- 🟡 Erros: 403 `INSTRUCTOR_ROLE_REQUIRED`; 404 `VEHICLE_NOT_FOUND`; 404 `CALIBRATION_NOT_FOUND`; 409 `SCENARIO_ALREADY_EXISTS`; 422 `SCENARIO_INVALID`; 422 `VALIDATION_FAILED`.
- 🟡 Idempotência: não idempotente; a repetição recebe 409. O cenário é imutável: `PUT`/`PATCH` devolvem 405 `METHOD_NOT_ALLOWED`.

**E-34 `GET /api/v1/scenarios/{scenario_id}`**
- 🟡 Response: 200 `Scenario`. Para perfil `student`, `hidden_defect = null`.
- 🟡 Erros: 404 `SCENARIO_NOT_FOUND`.
- 🟡 Idempotência: seguro.

**E-35 `GET /api/v1/scenarios/{scenario_id}/stats`**
- 🟡 Query: `from`, `to` (datas ISO 8601, opcionais).
- 🟡 Response: 200 `ScenarioStats {scenario_id, started, passed, failed_final, abandoned, completion_rate_pct?, median_submissions_to_pass?}`.
- 🟡 Erros: 404 `SCENARIO_NOT_FOUND`; 422 `VALIDATION_FAILED`.
- 🟡 Idempotência: seguro. Premissa 🟡: a métrica de produto (≥ 80 %) usa só cenários base, com tentativas `abandoned` no denominador (`requirements.md#10-lacunas`).

**E-36 `POST /api/v1/scenarios/{scenario_id}/attempts`**
- 🟡 Request: corpo vazio.
- 🟡 Response: 201 `Attempt` com `state = "preparing"`, `session_id` e `calibration_id`. Cabeçalho `Location: /api/v1/attempts/{attempt_id}`. A puxada base corre em segundo plano.
- 🟡 Erros: 404 `SCENARIO_NOT_FOUND`; 409 `SIM_CAPACITY_EXCEEDED`; 422 `SCENARIO_CALIBRATION_HASH_MISMATCH`; 503 `SIM_WORKER_UNAVAILABLE`; 503 `CALIBRATION_SERVICE_UNAVAILABLE`.
- 🟡 Idempotência: não idempotente. Nova tentativa do mesmo cenário e perfil marca a anterior `abandoned` e apaga a sessão anterior (RF-27).

**E-37 `GET /api/v1/attempts`**
- 🟡 Query: `scenario_id?`, `origin: local|imported?`, `profile_id?`, `cursor?`, `limit` 1–200 (padrão 50).
- 🟡 Response: 200 `AttemptPage {items: list[Attempt], next_cursor?}`.
- 🟡 Erros: 422 `VALIDATION_FAILED`.
- 🟡 Idempotência: seguro. Limite: P95 < 300 ms com 50 itens.

**E-38 `GET /api/v1/attempts/{attempt_id}`**
- 🟡 Response: 200 `Attempt` (com `runs` classificadas e progresso).
- 🟡 Erros: 404 `ATTEMPT_NOT_FOUND`.
- 🟡 Idempotência: seguro.

**E-39 `POST /api/v1/attempts/{attempt_id}/hints`**
- 🟡 Request: corpo vazio.
- 🟡 Response: 200 `HintReveal {order, text, remaining}`.
- 🟡 Erros: 403 `ATTEMPT_NOT_OWNED`; 404 `ATTEMPT_NOT_FOUND`; 409 `HINT_LOCKED`; 409 `HINTS_EXHAUSTED`.
- 🟡 Idempotência: não idempotente (cada chamada revela a próxima dica).

**E-40 `POST /api/v1/attempts/{attempt_id}/abandon`**
- 🟡 Request: corpo vazio.
- 🟡 Response: 200 `Attempt` com `state = "abandoned"`; a sessão associada recebe `DELETE`.
- 🟡 Erros: 403 `ATTEMPT_NOT_OWNED`; 404 `ATTEMPT_NOT_FOUND`; 409 `ATTEMPT_NOT_IN_PROGRESS`.
- 🟡 Idempotência: não idempotente; a repetição recebe 409.

**E-41 `POST /api/v1/attempts/{attempt_id}/submit`**
- 🟡 Request: `SubmitRequest {calibration_id, run_ids? (≤ 10), declared_defect?}`.
- 🟡 Response: 202 `SubmitAccepted {attempt_id, submission_index, evaluation_status = "pending"}`. Cabeçalho `Location: /api/v1/attempts/{attempt_id}/evaluation?submission={n}`.
- 🟡 Erros: 403 `ATTEMPT_NOT_OWNED`; 404 `ATTEMPT_NOT_FOUND`; 409 `ATTEMPT_NOT_IN_PROGRESS`; 409 `SUBMISSION_LIMIT_REACHED` (padrão 5); 409 `RUN_IN_PROGRESS`; 422 `CALIBRATION_NOT_IN_ATTEMPT`.
- 🟡 Idempotência: não idempotente (cada chamada gasta uma submissão, salvo erro de avaliação: `TRACE_UNAVAILABLE`, `PROBE_FAILED`, `EVALUATION_INTERRUPTED`).

**E-42 `GET /api/v1/attempts/{attempt_id}/evaluation`**
- 🟡 Query: `submission?` (padrão: última).
- 🟡 Response: 200 `Evaluation` (`status: pending|completed|error`; com `error_code` quando `error`).
- 🟡 Erros: 404 `ATTEMPT_NOT_FOUND`; 404 `EVALUATION_NOT_FOUND`.
- 🟡 Idempotência: seguro. O cliente faz polling enquanto `status = pending`.

**E-43 `POST /api/v1/attempts/{attempt_id}/replay`**
- 🟡 Request: corpo vazio.
- 🟡 Response: 202 `ReplayAccepted {attempt_id, replay_status = "running", runs_to_replay}`. Resultado em `Attempt.replay_status` (`verified|mismatch|incompatible_version`).
- 🟡 Erros: 403 `INSTRUCTOR_ROLE_REQUIRED`; 404 `ATTEMPT_NOT_FOUND`; 409 `REPLAY_VERSION_INCOMPATIBLE`; 409 `SIM_CAPACITY_EXCEEDED`.
- 🟡 Idempotência: não idempotente (cada chamada re-executa as puxadas); o resultado é determinístico.

**E-44 `POST /api/v1/packages/export`**
- 🟡 Request: `PackageExportRequest {kind: challenge|attempt, scenario_id? (challenge), attempt_id? (attempt), include_full_logs = false}`.
- 🟡 Response: 200 `SignedPackage` com `Content-Disposition: attachment; filename="simremap-<kind>-<id>-<8 hex>.simremap.json"`.
- 🟡 Erros: 404 `SCENARIO_NOT_FOUND`; 404 `ATTEMPT_NOT_FOUND`; 409 `ATTEMPT_NOT_EVALUATED`; 422 `PACKAGE_NOT_CANONICALIZABLE` (`detail` com o caminho JSON); 503 `PACKAGE_SERVICE_UNAVAILABLE`.
- 🟡 Idempotência: seguro no estado; o `sha256` repete-se para o mesmo conteúdo (`created_at` fica fora do hash).

**E-45 `POST /api/v1/packages/import`**
- 🟡 Request: `SignedPackage` (JSON, ≤ 64 MiB via `body_limit`).
- 🟡 Response: 201 `PackageImportResult {package_sha256, kind, scenario_id, attempt_id?, already_imported, evaluation_mismatch, recomputed_evaluation?}`; 200 com `already_imported = true` quando o `sha256` já existe.
- 🟡 Erros: 403 `INSTRUCTOR_ROLE_REQUIRED` (`kind = attempt`); 404 `SCENARIO_NOT_FOUND`; 409 `SCENARIO_VERSION_MISMATCH`; 413 `PAYLOAD_TOO_LARGE`; 422 `PACKAGE_HASH_MISMATCH`; 422 `PACKAGE_FORMAT_UNSUPPORTED`; 422 `PACKAGE_MALFORMED`; 422 `PACKAGE_SCHEMA_INVALID`; 422 `PACKAGE_NOT_CANONICALIZABLE`; 503 `PACKAGE_SERVICE_UNAVAILABLE`; 507 `STORAGE_FULL`.
- 🟡 Idempotência: idempotente pelo `sha256` (RF-21). Transação revertida em erro; o pacote não fica marcado como importado.
- 🟡 Limites: a UI do instrutor envia até 2 uploads em paralelo, 20 a 50 ficheiros por turma.

### 3.9 Rotas fora do catálogo `/api/v1/`

- 🟡 `GET /` e `/assets/*`: build estático do frontend; fallback SPA para `index.html` em rotas que não começam por `/api/` nem `/ws/`. Sem build: 404 `STATIC_NOT_BUILT`. Fonte: `platform-foundation.md` RF-15, EC-11.
- 🟡 Rota inexistente sob `/api/*` ou `/ws/*`: 404 `ROUTE_NOT_FOUND`.

## 4. Catálogo unificado de códigos de erro

Fonte de cada linha: seção 8 (tabela de endpoints), seção 11 (edge cases) e apêndices da spec dona. O registo é feito por `register_error` no arranque (`platform-foundation.md#8-design-e-interface`). Normalizações aplicadas: ver seção 5.

Coluna "Canal": **HTTP** = resposta REST; **WS** = envelope `error` ou código de fecho; **Interno** = log ou estado de domínio, nunca resposta HTTP direta.

### 4.1 platform-foundation (transversais)

| Code | Status | Canal | Significado |
|---|---|---|---|
| 🟡 `VALIDATION_FAILED` | 422 | HTTP | Corpo, query ou path inválido segundo o schema Pydantic (inclui `errors`). |
| 🟡 `ROUTE_NOT_FOUND` | 404 | HTTP | Rota `/api/*` ou `/ws/*` inexistente. |
| 🟡 `RESOURCE_NOT_FOUND` | 404 | HTTP | Base genérica; os componentes usam códigos específicos. |
| 🟡 `METHOD_NOT_ALLOWED` | 405 | HTTP | Método não suportado (ex.: `PUT` em cenário). |
| 🟡 `PAYLOAD_TOO_LARGE` | 413 | HTTP | Corpo acima de `max_body_bytes` ou do override da rota. |
| 🟡 `UNSUPPORTED_MEDIA_TYPE` | 415 | HTTP | `Content-Type` não aceite pela rota. |
| 🟡 `CONFLICT` | 409 | HTTP | Base genérica de conflito de estado. |
| 🟡 `INTERNAL_ERROR` | 500 | HTTP | Exceção não tratada; sem stack trace na resposta. |
| 🟡 `SERVICE_UNAVAILABLE` | 503 | HTTP | Health `down` (banco indisponível). |
| 🟡 `DATABASE_UNAVAILABLE` | 503 | HTTP | Falha de ligação ou de I/O do banco num pedido (`Retry-After: 2`). |
| 🟡 `SIM_WORKER_UNAVAILABLE` | 503 | HTTP, WS (fatal + 1011) | Worker morreu ou não arrancou em 5 s. |
| 🟡 `SIM_WORKER_BUSY` | 503 | HTTP | Fila de comandos do worker cheia (64 itens). |
| 🟡 `SIM_CAPACITY_EXCEEDED` | 409 | HTTP | Nova sessão acima de `max_active_sessions`. |
| 🟡 `STORAGE_FULL` | 507 | HTTP | Volume `/data` sem espaço. |
| 🟡 `STATIC_NOT_BUILT` | 404 | HTTP | `GET /` sem build do frontend. |

### 4.2 vehicle-catalog

| Code | Status | Canal | Significado |
|---|---|---|---|
| 🟡 `VEHICLE_NOT_FOUND` | 404 | HTTP | `vehicle_id` válido e inexistente. |
| 🟡 `VEHICLE_ID_INVALID` | 422 | HTTP | `vehicle_id` fora do padrão slug. |
| 🟡 `VEHICLE_NOT_VALIDATED` | 409 | HTTP | Sessão pedida para veículo `draft` com drafts desligados. |
| 🟡 `REFERENCE_CURVE_NOT_FOUND` | 404 | HTTP | Nenhuma curva para o filtro pedido. |
| 🟡 `FUEL_NOT_FOUND` | 404 | HTTP | `fuel_id` desconhecido. |
| 🟡 `FUEL_NOT_ALLOWED` | 409 | HTTP | Combustível fora de `allowed_fuel_ids` do veículo. |
| 🟡 `CATALOG_INVALID` | 500 | Interno (arranque, saída 4) | Catálogo inválido; o arranque falha antes dos routers. Subcódigos em `contracts/file-formats.md` seção 2.7. |

### 4.3 engine-physics-core

| Code | Status | Canal | Significado |
|---|---|---|---|
| 🟡 `PHYSICS_CONFIG_INVALID` | 422 | HTTP (via dyno-bench) | `PhysicsConfig` ou dados do veículo inválidos. |
| 🟡 `ACTUATOR_COMMAND_INVALID` | 422 | HTTP (via dyno-bench) | Listas por cilindro com tamanho errado ou valor fora do limite. |
| 🟡 `PHYSICS_NUMERIC_DIVERGENCE` | 500 | HTTP, WS | NaN, Inf, p < 0 ou T > 4000 K; a puxada é abortada. |
| 🟡 `PHYSICS_FUEL_CHANGE_WHILE_RUNNING` | 409 | HTTP | `set_fuel()` com rpm > 0. |
| 🟡 `PHYSICS_DT_MISMATCH` | 500 | Interno | `dt` ≠ `1/sim_hz` (erro de programação). |
| 🟡 `PHYSICS_SNAPSHOT_INVALID` | 422 | Interno | Snapshot com hash ou `schema_version` divergente. |

### 4.4 dyno-bench

| Code | Status | Canal | Significado |
|---|---|---|---|
| 🟡 `SESSION_NOT_FOUND` | 404 | HTTP, WS (fecho 4404) | Sessão inexistente. |
| 🟡 `SESSION_CLOSED` | 409 | HTTP | Sessão encerrada. |
| 🟡 `RUN_NOT_FOUND` | 404 | HTTP | Puxada inexistente. |
| 🟡 `RUN_IN_PROGRESS` | 409 | HTTP | Já existe puxada ativa na sessão (puxada simultânea, restore, swap, submit). |
| 🟡 `RUN_NOT_ACTIVE` | 409 | HTTP | Abort de puxada em estado terminal. |
| 🟡 `ENGINE_DESTROYED` | 409 | HTTP | Motor bloqueado após falha catastrófica. |
| 🟡 `RPM_RANGE_INVALID` | 422 | HTTP | `end_rpm ≤ start_rpm + 500`. |
| 🟡 `GEAR_NOT_AVAILABLE` | 422 | HTTP | Marcha acima do número de marchas do veículo. |
| 🟡 `PROBE_NOT_ALLOWED` | 422 | HTTP | `probe` numa sessão sem `attempt_id`. |
| 🟡 `PHYSICS_UNAVAILABLE` | 503 | HTTP | Física indisponível na criação da sessão. |
| 🟡 `THROTTLE_LOCKED_BY_RUN` | — | WS (`error` não fatal) | `control.throttle` fora do estado `idle`. |
| 🟡 `SIM_INTERNAL_ERROR` | — | WS (`error`) | Exceção não tratada no tick; puxada `aborted` com `internal_error`. |

### 4.5 knock-and-failure-model

| Code | Status | Canal | Significado |
|---|---|---|---|
| 🟡 `FORENSIC_REPORT_NOT_FOUND` | 404 | HTTP | Puxada sem falha nem quase-falha. |
| 🟡 `FORENSIC_REPORT_PENDING` | 409 | HTTP | Laudo em geração (`Retry-After: 1`). |
| 🟡 `DAMAGE_CONFIG_INVALID` | 422 | HTTP (via dyno-bench) | Limite mecânico ausente ou `DamageConfig` inválido. |
| 🟡 `DAMAGE_MODEL_UNAVAILABLE` | 503 | HTTP | Modelo de dano indisponível; também `Evaluation.error_code`. |
| 🟡 `DAMAGE_DT_MISMATCH` | 500 | Interno | `dt` ≠ `1/sim_hz`. |
| 🟡 `DAMAGE_SNAPSHOT_INVALID` | 422 | Interno | Snapshot do dano inválido. |
| 🟡 `DAMAGE_INPUT_INVALID` | 500 | Interno (puxada `aborted`) | Vetores do `CombustionEvent` incoerentes ou não finitos. |
| 🟡 `DAMAGE_FUEL_CHANGE_WHILE_RUNNING` | 409 | HTTP (via dyno-bench) | Troca de combustível com motor em funcionamento. |

### 4.6 ecu-core

| Code | Status | Canal | Significado |
|---|---|---|---|
| 🟡 `CALIBRATION_NOT_FOUND` | 404 | HTTP | Calibração inexistente. |
| 🟡 `CALIBRATION_VERSION_NOT_FOUND` | 404 | HTTP | Versão inexistente. |
| 🟡 `CALIBRATION_VERSION_CONFLICT` | 409 | HTTP | `base_version` desatualizada (com `latest_version`). |
| 🟡 `CALIBRATION_VERSION_LIMIT` | 409 | HTTP | 1001.ª versão; o usuário deve clonar. |
| 🟡 `CALIBRATION_PROFILE_IMMUTABLE` | 422 | HTTP | `PUT` tenta mudar o `profile_id`. |
| 🟡 `CALIBRATION_PROFILE_MISMATCH` | 422 | HTTP | Perfil da calibração ≠ perfil da sessão. |
| 🟡 `CALIBRATION_VEHICLE_MISMATCH` | 422 | HTTP | Veículo da calibração ≠ veículo da sessão. |
| 🟡 `CALIBRATION_APPLY_TIMEOUT` | 504 | HTTP | Worker não confirmou a troca em 100 ms. |
| 🟡 `TABLE_NOT_FOUND` | 404 | HTTP | `table_id` inexistente na calibração. |
| 🟡 `TABLE_NOT_LIVE_TUNABLE` | 409 | HTTP | Alteração não live durante a puxada (lista de itens). |
| 🟡 `TABLE_AXIS_NOT_MONOTONIC` | 422 | HTTP, Interno (catálogo) | Eixo não estritamente crescente. |
| 🟡 `TABLE_SIZE_EXCEEDED` | 422 | HTTP | Eixo com mais de 32 pontos. |
| 🟡 `TABLE_VALUE_NOT_FINITE` | 422 | HTTP | Valor NaN ou infinito. |
| 🟡 `TABLE_VALUE_OUT_OF_RANGE` | 422 | HTTP | Valor fora de mín/máx do tipo (com `row`, `col`, `min`, `max`). |
| 🟡 `TABLE_SHAPE_MISMATCH` | 422 | HTTP | Dimensões de `values` ≠ eixos. |
| 🟡 `TABLE_UNIT_MISMATCH` | 422 | HTTP | Unidade ≠ unidade do `kind`. |
| 🟡 `TABLE_ID_MISMATCH` | 422 | HTTP | Chave do dicionário ≠ `table_id`. |
| 🟡 `STRATEGY_KIND_MISMATCH` | 422 | HTTP | Chave do dicionário ≠ `kind` da estratégia. |
| 🟡 `STRATEGY_CONFIG_INVALID` | 422 | HTTP | Configuração incoerente entre estratégias. |
| 🟡 `STRATEGY_NOT_SUPPORTED_BY_PROFILE` | 422 | HTTP | Estratégia fora da matriz do perfil. |
| 🟡 `PATCH_TOO_LARGE` | 422 | HTTP | Mais de 1024 células num PATCH. |
| 🟡 `PATCH_CELL_OUT_OF_BOUNDS` | 422 | HTTP | `row`/`col` fora da tabela. |

### 4.7 ecu-profiles

| Code | Status | Canal | Significado |
|---|---|---|---|
| 🟡 `ECU_PROFILE_NOT_FOUND` | 404 | HTTP | Perfil de ECU inexistente (código transversal R1, todas as specs). |
| 🟡 `PROFILE_REGISTRY_INVALID` | 500 | HTTP | Registo de perfis inválido após o boot. |
| 🟡 `SWAP_TARGET_INVALID` | 422 | HTTP | Perfil alvo igual ao atual ou não permitido. |
| 🟡 `SWAP_CONFIRMATION_REQUIRED` | 422 | HTTP | Saída do OEM sem `confirm_snapshot = true`. |
| 🟡 `SWAP_NOT_SUPPORTED_FOR_VEHICLE` | 422 | HTTP | Veículo sem ficheiro de hardware ou com `swap_supported = false`. |
| 🟡 `BASE_SETUP_NOT_EDITABLE_OEM` | 409 | HTTP | Edição de base com o perfil OEM ativo. |
| 🟡 `BASE_SETUP_VERSION_CONFLICT` | 409 | HTTP | `base_version` desatualizada. |
| 🟡 `BASE_SETUP_INVALID` | 422 | HTTP | Campo da base inválido (com `field` e `reason`). |
| 🟡 `WIZARD_INPUT_INVALID` | 422 | HTTP | Entrada do assistente inválida. |
| 🟡 `ECU_SETUP_INCOMPLETE` | 409 | HTTP | Puxada pedida em `awaiting_base_setup` (com `pending`). |
| 🟡 `OEM_CHECKSUM_INVALID` | 422 | HTTP | Checksum OEM inválido sem correção automática. |
| 🟡 `OEM_TORQUE_MODEL_NOT_MONOTONIC` | 422 | HTTP | `torque_optimal` não invertível. |
| 🟡 `TABLE_NOT_SUPPORTED_BY_PROFILE` | 422 | HTTP | Tabela fora do perfil. |
| 🟡 `STRATEGY_REQUIRES_PACKAGE` | 422 | HTTP | Estratégia exige o pacote `race`. |
| 🟡 `STRATEGY_OPTION_NOT_SUPPORTED` | 422 | HTTP | Opção da estratégia restrita no perfil. |
| 🟡 `NAV_TARGET_NOT_SUPPORTED` | — | Interno (arranque) | `NavItem.target_id` sem tabela ou estratégia suportada. |
| 🟡 `HARDWARE_FILE_MISSING` | — | Interno (log) | Ficheiro de hardware ausente; veículo sem swap. |

### 4.8 telemetry-datalogger

| Code | Status | Canal | Significado |
|---|---|---|---|
| 🟡 `LOG_NOT_FOUND` | 404 | HTTP | Log inexistente ou descartado por falha do worker. |
| 🟡 `LOG_NOT_READY` | 409 | HTTP | Puxada ainda em gravação. |
| 🟡 `LOG_CORRUPTED` | 500 | HTTP | Gzip inválido ou hash divergente no disco. |
| 🟡 `LOG_SCHEMA_INVALID` | 422 | HTTP | `DataLog` fora do schema. |
| 🟡 `LOG_FORMAT_UNSUPPORTED` | 422 | HTTP | `format_version` maior que o suportado. |
| 🟡 `LOG_HASH_MISMATCH` | 422 | HTTP | SHA-256 recalculado ≠ declarado. |
| 🟡 `LOG_ALREADY_IMPORTED` | 409 | HTTP | `sha256` já existe (com o `log_id`). |
| 🟡 `LOG_COMPARE_NO_OVERLAP` | 422 | HTTP | Nenhum bin de RPM comum. |
| 🟡 `WS_TOO_MANY_CONNECTIONS` | — | WS (fecho 4429) | Mais de 4 conexões por sessão. |
| 🟡 `WS_ORIGIN_FORBIDDEN` | — | WS (fecho 4403) | `Origin` diferente da origem do servidor. |
| 🟡 `WS_MESSAGE_INVALID` | — | WS (`error`) | JSON inválido, `type` desconhecido ou > 16 kB. |
| 🟡 `WS_UNKNOWN_CHANNEL` | — | WS (`error`) | Canal fora do catálogo do veículo. |
| 🟡 `WS_FPS_OUT_OF_RANGE` | — | WS (`error`) | `fps` fora de 30–60. |
| 🟡 `WS_CYLINDER_OUT_OF_RANGE` | — | WS (`error`) | Cilindro do traço > `n_cyl`. |
| 🟡 `WS_RESUME_GAP` | — | WS (`error`) | `resume_from_seq` anterior ao buffer de replay. |
| 🟡 `WS_RESUME_INVALID` | — | WS (`error`) | `resume_from_seq` maior que o `seq` atual. |
| 🟡 `WS_RATE_LIMITED` | — | WS (`error` + fecho 1008) | Abuso de mensagens. |
| 🟡 `SPECTRUM_UNAVAILABLE` | — | WS (`error` não fatal) | Veículo sem `bore_mm`. |

### 4.9 training-scenarios

| Code | Status | Canal | Significado |
|---|---|---|---|
| 🟡 `PLAYER_PROFILE_REQUIRED` | 400 | HTTP | Cabeçalho `X-Player-Profile-Id` ausente. |
| 🟡 `PLAYER_PROFILE_NOT_FOUND` | 404 | HTTP | Perfil de jogador inexistente. |
| 🟡 `NICKNAME_TAKEN` | 409 | HTTP | Nickname já usado na estação. |
| 🟡 `PROFILE_LIMIT_REACHED` | 409 | HTTP | 101.º perfil de jogador. |
| 🟡 `INSTRUCTOR_ROLE_REQUIRED` | 403 | HTTP | Ação exclusiva do instrutor. |
| 🟡 `SCENARIO_NOT_FOUND` | 404 | HTTP | Cenário inexistente. |
| 🟡 `SCENARIO_ALREADY_EXISTS` | 409 | HTTP | `scenario_id` já existe. |
| 🟡 `SCENARIO_INVALID` | 422 | HTTP | Regras adicionais do cenário violadas. |
| 🟡 `SCENARIO_CALIBRATION_HASH_MISMATCH` | 422 | HTTP | Calibração clonada com hash ≠ `initial_calibration.content_hash`. |
| 🟡 `SCENARIO_VERSION_MISMATCH` | 409 | HTTP | `scenario_sha256` do pacote ≠ cenário local. |
| 🟡 `ATTEMPT_NOT_FOUND` | 404 | HTTP | Tentativa inexistente. |
| 🟡 `ATTEMPT_NOT_OWNED` | 403 | HTTP | Tentativa de outro perfil. |
| 🟡 `ATTEMPT_NOT_IN_PROGRESS` | 409 | HTTP | Tentativa em estado terminal. |
| 🟡 `ATTEMPT_NOT_EVALUATED` | 409 | HTTP | Export de tentativa sem avaliação. |
| 🟡 `HINT_LOCKED` | 409 | HTTP | Dica ainda bloqueada. |
| 🟡 `HINTS_EXHAUSTED` | 409 | HTTP | Sem dicas restantes. |
| 🟡 `SUBMISSION_LIMIT_REACHED` | 409 | HTTP | Submissões acima de `max_submissions`. |
| 🟡 `CALIBRATION_NOT_IN_ATTEMPT` | 422 | HTTP | Calibração submetida não pertence à tentativa. |
| 🟡 `EVALUATION_NOT_FOUND` | 404 | HTTP | Submissão sem avaliação. |
| 🟡 `REPLAY_VERSION_INCOMPATIBLE` | 409 | HTTP | `producer.app_version` ≠ versão local. |
| 🟡 `PACKAGE_HASH_MISMATCH` | 422 | HTTP | SHA-256 do pacote inválido. |
| 🟡 `PACKAGE_FORMAT_UNSUPPORTED` | 422 | HTTP | `format_version` maior que o suportado. |
| 🟡 `PACKAGE_MALFORMED` | 422 | HTTP | JSON truncado ou inválido. |
| 🟡 `PACKAGE_SCHEMA_INVALID` | 422 | HTTP | Pacote fora do schema ou defeito não suportado. |
| 🟡 `PACKAGE_NOT_CANONICALIZABLE` | 422 | HTTP | NaN ou Infinity impedem o JCS. |
| 🟡 `CALIBRATION_SERVICE_UNAVAILABLE` | 503 | HTTP | ecu-core indisponível ao criar a tentativa. |
| 🟡 `PACKAGE_SERVICE_UNAVAILABLE` | 503 | HTTP | Biblioteca JCS indisponível. |
| 🟡 `TRACE_UNAVAILABLE` | — | Interno (`Evaluation.error_code`) | Log da puxada ilegível após 3 retries. |
| 🟡 `PROBE_FAILED` | — | Interno (`Evaluation.error_code`) | Sonda de knock terminou com falha interna. |
| 🟡 `BASELINE_FAILED` | — | Interno (estado da tentativa) | Puxada base `aborted` ou timeout de 120 s. |
| 🟡 `EVALUATION_INTERRUPTED` | — | Interno (`Evaluation.error_code`) | Avaliação `pending` > 5 min após reinício. |

### 4.10 Totais

- 🟡 Códigos únicos no catálogo: 136. Destes, 112 têm resposta HTTP (3 deles também saem no WebSocket: `SESSION_NOT_FOUND`, `SIM_WORKER_UNAVAILABLE`, `PHYSICS_NUMERIC_DIVERGENCE`), 12 são só WebSocket e 12 são internos (arranque, log ou estado de domínio).
- 🟡 Distribuição por status registado em `register_error` (inclui internos com status): 400 (1), 403 (2), 404 (18), 405 (1), 409 (29), 413 (1), 415 (1), 422 (47), 500 (8), 503 (8), 504 (1), 507 (1); sem status (WS ou interno): 18.
- 🟡 Códigos aposentados (não registar): `VALIDATION_ERROR`, `RUN_ALREADY_ACTIVE`, `CALIBRATION_REVISION_CONFLICT`, `TABLE_LOCKED_DURING_RUN`, `STORAGE_UNAVAILABLE`.
- 🟡 O teste de contrato do catálogo verifica: (a) cada código aparece uma única vez; (b) o status é o desta tabela; (c) nenhum dos códigos aposentados da seção 5 está registado.

## 5. Divergências resolvidas

| ID | Divergência | Specs envolvidas | Decisão | Confiança |
|---|---|---|---|---|
| D-REST-01 | Código de validação `VALIDATION_ERROR` vs `VALIDATION_FAILED`. | `dyno-bench`, `ecu-core`, `training-scenarios`, `vehicle-catalog` vs `platform-foundation` | Adotado `VALIDATION_FAILED` (422, dono `platform-foundation`). `VALIDATION_ERROR` fica aposentado. | 🟡 |
| D-REST-02 | Puxada simultânea `RUN_ALREADY_ACTIVE` vs `RUN_IN_PROGRESS`. | `dyno-cockpit-ui` vs `dyno-bench` | Adotado `RUN_IN_PROGRESS` (409, dono `dyno-bench`). | 🟡 |
| D-REST-03 | Concorrência de calibração: `base_revision`, `revision`, `CALIBRATION_REVISION_CONFLICT`, `TABLE_LOCKED_DURING_RUN`, filtro `?lineage=`. | `ecu-tuning-ui` vs `ecu-core` | Adotados `base_version`, `version`, `CALIBRATION_VERSION_CONFLICT` e `TABLE_NOT_LIVE_TUNABLE`. A linhagem usa `GET /api/v1/calibrations/{id}?include=versions`. A resposta do PATCH é `TablePatchResult {version, content_hash, table}`. | 🟡 |
| D-REST-04 | Perfil de jogador inexistente devolvia `ECU_PROFILE_NOT_FOUND`. | `training-scenarios` vs revisão R1 | Adotado `PLAYER_PROFILE_NOT_FOUND` (404, dono `training-scenarios`). `ECU_PROFILE_NOT_FOUND` fica só para perfil de ECU. | 🟡 |
| D-REST-05 | Indisponibilidade de banco `STORAGE_UNAVAILABLE` vs `DATABASE_UNAVAILABLE`. | `ecu-core`, `ecu-profiles` vs `platform-foundation` | Adotado `DATABASE_UNAVAILABLE` (503, `Retry-After: 2`), dono `platform-foundation`. `STORAGE_UNAVAILABLE` fica aposentado. Modelos `CalibrationSummary`, `CalibrationReplace` e `TablePatchResult`, citados mas não definidos no `ecu-core`, ficam definidos pelos campos listados em E-15, E-18 e E-19. | 🟡 |
| D-REST-06 | Guarda de partida do perfil (`ECU_SETUP_INCOMPLETE`) e campo `ecu_state` na sessão (OQ-02 da `ecu-profiles`). | `ecu-profiles` vs `dyno-bench` | `POST .../runs` passa a devolver 409 `ECU_SETUP_INCOMPLETE` via `ProfileSessionGuard.can_start_run()`. `SimulationSession` ganha `ecu_state`. | 🟡 |
| D-REST-07 | `Location` só definido em `POST /api/v1/calibrations`. | `ecu-core` vs demais | Estendido a todo 201/202 que cria recurso com `GET` próprio (E-06, E-09, E-16, E-33, E-36, E-41). | 🟡 |
| D-REST-08 | `POST /api/v1/sessions` não listava os erros do catálogo e do combustível. | `dyno-bench` vs `vehicle-catalog` | Acrescentados 409 `VEHICLE_NOT_VALIDATED` e 409 `FUEL_NOT_ALLOWED` (RF-25 do `dyno-bench`, RF-23 do `vehicle-catalog`). | 🟡 |
| D-REST-09 | `Evaluation` tinha `status = error` sem campo para o código. | `training-scenarios` | `Evaluation` ganha `error_code: str | None` (`TRACE_UNAVAILABLE`, `PROBE_FAILED`, `EVALUATION_INTERRUPTED`, `DAMAGE_MODEL_UNAVAILABLE`). | 🟡 |
| D-REST-10 | Estilo de import idempotente: logs devolvem 409 `LOG_ALREADY_IMPORTED`; pacotes devolvem 200 `already_imported = true`. | `telemetry-datalogger` vs `training-scenarios` | Mantidos os dois comportamentos, cada um definido pelo dono. A UI trata os dois como sucesso. | 🟡 |
| D-REST-11 | Status de códigos internos da física e do dano sem HTTP definido (`PHYSICS_DT_MISMATCH`, `PHYSICS_SNAPSHOT_INVALID`, `DAMAGE_INPUT_INVALID`). | `engine-physics-core`, `knock-and-failure-model` | Registados como internos com status 500 (erro de programação) ou 422 (snapshot inválido), para o `register_error` não ficar sem status. | 🟡 |
| D-REST-12 | Meta de potência do `standalone-swap` e métrica de conclusão em aberto. | `training-scenarios` OQ-06, `requirements.md#10-lacunas` | Premissas: `min_whp = 300` absoluto; taxa de conclusão só em cenários base, com `abandoned` no denominador; pacotes só com SHA-256, sem PIN. | 🟡 |
