# Contrato: formatos de arquivo

> Feature: `001-simulador-remap` · Fase: plan · Gerado em 2026-10-18 (modo autônomo, greenfield)
> Confidência: 🟢 CONFIRMADO, 🟡 INFERIDO (padrão: specs planejadas), 🔴 LACUNA / DÚVIDA
> Escopo: ficheiros lidos ou escritos pelo produto (catálogo embutido, calibração exportada, DataLog, pacote assinado, CSV de notas) e as suas regras de versão.
> Delta: componente-novo.

## 1. Regras comuns

- 🟡 Texto em UTF-8 sem BOM. JSON sem comentários. Fim de linha `\n`.
- 🟡 SHA-256 sempre em hexadecimal minúsculo de 64 caracteres (`^[0-9a-f]{64}$`).
- 🟡 Cada artefacto tem a sua regra canónica de hash (tabela da seção 7). As regras não se misturam: o catálogo usa `repr` de float; calibração, curva e cabeçalho de log arredondam a 6 casas; pacotes usam JCS (RFC 8785).
- 🟡 Nomes de ficheiro gerados pelo servidor; nunca a partir de caminho vindo do cliente (`telemetry-datalogger.md#12-segurança-e-privacidade`).

## 2. Catálogo de veículos (`backend/src/simremap/catalog/data/`)

Fonte: `_reversa_sdd/sdd/vehicle-catalog.md#8-design-e-interface`, `#9-modelo-de-dados`, `#11-edge-cases-e-tratamento-de-erros`, RF-01, RF-02, RF-19, RF-24, RF-25, RF-27, RF-29, Apêndices A.4 e A.8.

### 2.1 Estrutura

```text
backend/src/simremap/catalog/data/          (ou SIMREMAP_CATALOG_DIR)
  manifest.json
  fuels/<fuel_id>.json                       e27 | e100 | podium | e0
  vehicles/<vehicle_id>/vehicle.json         hatch-20t-gdi | coupe-30t-i6 | classic-20t-swap | muscle-v8-sc
  vehicles/<vehicle_id>/reference-curves/<curve_id>.json
  vehicles/<vehicle_id>/calibrations/<profile_id>.json
backend/src/simremap/profiles/data/hardware/<vehicle_id>.json   (dono ecu-profiles; fora do manifesto do catálogo)
backend/src/simremap/scenarios/builtin/<scenario_id>.json      (dono training-scenarios; fora do manifesto do catálogo)
```

- 🟡 `vehicle_id` igual ao nome do diretório. Exatamente 4 veículos canónicos.
- 🟡 Limites: ficheiro ≤ 2 MiB; links simbólicos para fora do diretório recusados; codificação ≠ UTF-8 recusada.
- 🟡 O catálogo não cria tabelas no banco. Os dados vêm empacotados na imagem Docker. O worker recebe `VehicleSpec` e `FuelSpec` serializados.
- 🟡 Qualquer erro de carga faz o arranque falhar com `CATALOG_INVALID` e código de saída 4 (seção 2.7).

### 2.2 `manifest.json`

```json
{
  "catalog_version": "1.0.0",
  "files": [
    {"path": "fuels/e27.json", "sha256": "<64 hex>"},
    {"path": "vehicles/hatch-20t-gdi/vehicle.json", "sha256": "<64 hex>"},
    {"path": "vehicles/hatch-20t-gdi/reference-curves/stock-e27.json", "sha256": "<64 hex>"},
    {"path": "vehicles/hatch-20t-gdi/calibrations/oem-stage.json", "sha256": "<64 hex>"}
  ]
}
```

- 🟡 `catalog_version`: SemVer. `path`: relativo à raiz do catálogo, com `/`.
- 🟡 `sha256` de cada ficheiro: SHA-256 dos bytes do ficheiro.
- 🟡 Ficheiro ausente, extra (não listado) ou alterado recusa o arranque (`FILE_NOT_IN_MANIFEST`, `FILE_HASH_MISMATCH`). O desenvolvedor recalcula com `tools/rehash.py`.
- 🟡 `catalog_sha256` (global) e `data_sha256` (por veículo): SHA-256 do JSON canónico (chaves ordenadas, separadores compactos, UTF-8, floats em `repr`). Reordenar chaves não muda o hash. `ETag` dos endpoints do catálogo = `catalog_sha256`.

### 2.3 `vehicles/<vehicle_id>/vehicle.json`

- 🟡 Schema: `VehicleSpec` (Pydantic, `extra="forbid"`, `frozen=True`) com `EngineSpec`, `TurboSpec | None`, `SuperchargerSpec | None`, `InjectorSpec`, `MechanicalLimits`, `RatedFigures`, `ReferenceCommandSchedule`, `FactoryCalibrationRef`, `provenance`.
- 🟡 `MechanicalLimits` exige os 4 limites estruturais: `max_rod_load_kn` (kN), `max_cylinder_pressure_bar` (bar abs.), `max_piston_temp_c` (°C), `valve_float_rpm` (rpm), mais `rod_torque_limit_nm`, `egt_max_c`, `max_rpm`, `rev_limit_rpm`, `turbo_max_rpm` (só turbo). Invariante: `rev_limit_rpm ≤ max_rpm < valve_float_rpm`.
- 🟡 `provenance`: dicionário com chave = ponteiro JSON (ex.: `/engine/bore_mm`) e valor `{kind: prd|public_spec|literature|derived|estimate, note, source?}`. Campo numérico sem `prd`, `public_spec` ou `literature` aparece em `estimated_fields`.
- 🟡 Textos exibidos (`display_name`, `architecture_note`) sem termos da lista de marcas (Apêndice A.6); violação: `TRADEMARK_IN_DISPLAY_TEXT`.

Exemplo resumido (Apêndice A.8):

```json
{
  "vehicle_id": "hatch-20t-gdi",
  "display_name": "Hatch 2.0 turbo GDI",
  "architecture_note": "Inspirado em arquitetura 2.0 turbo GDI de 4 cilindros",
  "body": "hatch", "data_version": 1, "validation_status": "validated", "validated_on": "2026-10-25",
  "induction": "turbo",
  "engine": {"architecture": "inline", "n_cyl": 4, "bore_mm": 82.5, "stroke_mm": 92.8,
             "rod_length_mm": 144.0, "compression_ratio": 9.6, "displacement_cc": 1984,
             "firing_order": [1, 3, 4, 2], "injection_type": "gdi", "valvetrain": "dohc",
             "valves_per_cyl": 4, "ivc_deg_abdc": 40, "evo_deg_bbdc": 45},
  "stock_fuel_id": "e27", "allowed_fuel_ids": ["e27", "podium", "e0"],
  "drive_layout": "fwd", "drivetrain_efficiency": 0.85, "drivetrain_fixed_loss_kw": 0.0,
  "driveline_inertia_kg_m2": 2.4,
  "mechanical_limits": {"rod_torque_limit_nm": 420, "egt_max_c": 950, "max_rpm": 6800,
                        "rev_limit_rpm": 6500, "valve_float_rpm": 7200, "turbo_max_rpm": 210000,
                        "max_rod_load_kn": 52, "max_cylinder_pressure_bar": 120, "max_piston_temp_c": 330},
  "stock_profile_id": "oem-stage",
  "stock_calibration_id": "stock-hatch-20t-gdi-oem-stage",
  "provenance": {"/engine/compression_ratio": {"kind": "prd", "note": "PRD seção 7, item 1"}}
}
```

### 2.4 `fuels/<fuel_id>.json`

- 🟡 Schema: `FuelSpec {fuel_id, display_name, afr_stoich, lhv_mj_kg, ron, mon, knock_on, h_fg_kj_kg, density_kg_m3, ethanol_mass_fraction, laminar_bm_m_s, laminar_bphi_m_s, laminar_phi_m, preignition_surface_temp_c, provenance}`. Campo calculado `density_g_cc = density_kg_m3 / 1000` (consumido pelo `ecu-core`).
- 🟡 Valores de referência (Apêndice A.5): `e27` AFR 13,2, ρ 745; `e100` AFR 9,0, ρ 789; `podium` AFR 14,4, ρ 755; `e0` AFR 14,7, ρ 740.

### 2.5 Curvas de referência — `Reference Benchmark Baseline v1`

Ficheiro: `vehicles/<vehicle_id>/reference-curves/<curve_id>.json` (ex.: `stock-e27.json`).

```json
{
  "curve_id": "stock-e27",
  "vehicle_id": "hatch-20t-gdi",
  "calibration_ref": "stock",
  "fuel_id": "e27",
  "conditions": {"correction": "sae_j1349", "ambient_temp_c": 25.0, "ambient_pressure_kpa": 99.0,
                 "dyno_type": "inertial_roller", "gear": 4},
  "quantities": ["torque_crank_nm", "power_wheel_kw", "lambda_value", "egt_c"],
  "points": [
    {"rpm": 2000, "torque_crank_nm": 350.0, "power_wheel_kw": 62.3, "lambda_value": 0.95, "egt_c": 720},
    {"rpm": 2250, "torque_crank_nm": 350.0, "power_wheel_kw": 70.1, "lambda_value": 0.95, "egt_c": 740}
  ],
  "source": "Reference Benchmark Baseline v1 (estimativa interna)",
  "license": "internal-estimate",
  "confidence": "estimated",
  "quantity_confidence": {},
  "tolerance_pct": 5.0,
  "benchmark_id": "reference-benchmark-baseline-v1"
}
```

- 🟡 `benchmark_id` fixo: `"reference-benchmark-baseline-v1"` (nome exibido: `Reference Benchmark Baseline v1`), benchmark canónico do desvio < 5 % desde a revisão R1.
- 🟡 Pontos: RPM estritamente crescente, passo 250 rpm, 8–64 pontos, 1.º ≤ 3000 rpm, último ≥ `rev_limit_rpm − 250`. Âncoras a 500 rpm; pontos intermédios interpolam torque, lambda e EGT, e a potência recalcula-se: `P = T · 2π · rpm / 60 / 1000` (kW), `P_roda = P · η_drv − P_fixa`.
- 🟡 Coerência torque/potência por ponto com erro ≤ 1 % (`REFERENCE_CURVE_INCONSISTENT`). Valor nulo numa grandeza declarada: `REFERENCE_POINT_MISSING_VALUE`.
- 🟡 Unidades: `torque_crank_nm` (N·m, cambota), `power_wheel_kw` (kW, roda; whp = kW / 0,7457), `lambda_value` (-), `egt_c` (°C; o desvio de EGT compara em °C).
- 🟡 `benchmark_sha256` (D-FF-02): SHA-256 do JSON canónico (chaves ordenadas, separadores compactos) da lista `[{path, sha256}]` das entradas do `manifest.json` cujo `path` casa com `vehicles/*/reference-curves/*.json`, ordenada por `path`. Igual nas 4 respostas de `GET .../reference-curves`. Alterar 1 ponto sem mudar a versão falha o arranque (`FILE_HASH_MISMATCH`).

### 2.6 Calibração de fábrica (`vehicles/<vehicle_id>/calibrations/<profile_id>.json`)

- 🟡 Conteúdo: o formato de calibração exportada da seção 3, com `metadata.source = "oem_stock"`.
- 🟡 Referência no `vehicle.json`: `FactoryCalibrationRef {profile_id, calibration_id = "stock-<vehicle_id>-<profile_id>", file = "calibrations/<profile_id>.json", sha256}`.
- 🟡 A partir do Sprint 2, o validador registado pelo `ecu-core` (`register_calibration_validator`) valida cada ficheiro; erro de tabela vira `CATALOG_INVALID` com o código original (ex.: `TABLE_AXIS_NOT_MONOTONIC`).

### 2.7 Códigos internos de validação do catálogo (só no log de arranque)

| Code | Quando |
|---|---|
| 🟡 `FILE_HASH_MISMATCH` | SHA-256 do ficheiro ≠ `manifest.json`. |
| 🟡 `FILE_NOT_IN_MANIFEST` | Ficheiro presente e não listado. |
| 🟡 `FILE_TOO_LARGE` | Ficheiro > 2 MiB. |
| 🟡 `PATH_OUTSIDE_CATALOG` | Link simbólico para fora do diretório. |
| 🟡 `GRID_AXIS_NOT_MONOTONIC` | Eixo de grelha não estritamente crescente. |
| 🟡 `GRID_SHAPE_MISMATCH` | `z_values` ≠ `len(y) × len(x)`. |
| 🟡 `GRID_VALUE_OUT_OF_RANGE` | Valor fora do limite do campo (ex.: VE fora de 0,20–1,35). |
| 🟡 `TRADEMARK_IN_DISPLAY_TEXT` | Termo de marca em texto exibido. |
| 🟡 `REFERENCE_CURVE_INCONSISTENT` | Potência ≠ torque · ω · η − P_fixa (> 1 %). |
| 🟡 `REFERENCE_POINT_MISSING_VALUE` | Valor nulo numa grandeza declarada. |
| 🟡 `CALIBRATION_VALIDATOR_ERROR` | O validador do `ecu-core` lançou exceção imprevista. |

Todos sobem como `CATALOG_INVALID` (saída 4). Não são respostas HTTP; por isso não entram no total do catálogo de `contracts/rest-api.md`.

## 3. Calibração exportada

Fonte: `_reversa_sdd/sdd/ecu-core.md#9-modelo-de-dados` (`Calibration`, hash canónico), RF-04, RF-32; `training-scenarios.md#9-modelo-de-dados` (`InitialCalibration`).

- 🟡 Forma: o JSON de `Calibration` devolvido por `GET /api/v1/calibrations/{calibration_id}?version=n`, sem os campos calculados para a UI (`min`, `max`, `unit`, `source_channel`).
- 🟡 Nome sugerido no download: `calibration-<calibration_id>-v<version>.json` (D-FF-04).
- 🟡 Import: `POST /api/v1/calibrations` com `source = "payload"`. O servidor recalcula o `content_hash` e ignora o valor recebido.

```json
{
  "calibration_id": "0f5e9c2a-...", "vehicle_id": "hatch-20t-gdi", "profile_id": "oem-stage",
  "version": 4, "parent_version": 3,
  "fuel_model": {"mode": "profile_air_model", "charge_temp_blend": 0.0, "accel_enrich_tau_s": 0.2,
                 "afterstart_decay_s": 15.0, "cranking_rpm": 400.0, "cranking_ign_deg": 10.0,
                 "inj_duty_warn_pct": 85.0},
  "tables": {"ignition_base": {"table_id": "ignition_base", "kind": "ignition_base", "dims": 3,
                               "unit": "°BTDC", "live_tunable": true, "decimals": 1,
                               "x": {"quantity": "rpm", "values": [1000, 2000]},
                               "y": {"quantity": "map_kpa", "values": [30, 250]},
                               "values": [[10.0, 25.0], [5.0, 12.0]]}},
  "strategies": {"knock_control": {"kind": "knock_control", "enabled": true, "retard_step_deg": 2.0,
                                   "max_retard_deg": 8.0}},
  "profile_params": {"torque_monitoring": true, "checksum_check": true},
  "metadata": {"name": "Stage 1", "author_nickname": "lucas", "notes": "", "source": "user",
               "change_summary": "ignition_base: 12 células", "extra": {"oem_checksum": "a1b2"}},
  "content_hash": "<64 hex>",
  "created_at": "2026-10-18T10:00:00Z"
}
```

- 🟡 `content_hash = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False))`, com `payload = {vehicle_id, profile_id, fuel_model, tables, strategies, profile_params}` e floats arredondados a 6 casas. `metadata`, `version` e `created_at` ficam fora do hash.
- 🟡 Tabelas: eixos de 2 a 32 pontos finitos e estritamente crescentes; `values` com `len(y)` linhas × `len(x)` colunas; unidade e mín/máx do Apêndice A do `ecu-core`; máximo 128 tabelas; `profile_params` ≤ 64 chaves.
- 🟡 A `BaseSetup` do perfil standalone tem hash próprio: `setup_hash = sha256(json.dumps(base_setup, sort_keys=True, separators=(",", ":")))` com floats a 6 casas; a calibração gerada guarda `metadata.extra.base_setup_hash` (`ecu-profiles.md#9-modelo-de-dados`).

## 4. DataLog

Fonte: `_reversa_sdd/sdd/telemetry-datalogger.md#8-design-e-interface`, `#9-modelo-de-dados` (`DataLogHeader`, `DataLog`, formato `.simlog.gz`), RF-14 a RF-18, apêndice "Exemplo de cabeçalho CSV".

### 4.1 Conteúdo lógico

```python
class DataLogHeader(BaseModel):
    format_version: Literal[1] = 1          # DATALOG_FORMAT_VERSION
    run_id: str; session_id: str; vehicle_id: str; profile_id: str
    calibration_hash: str                   # SHA-256 da calibração (ecu-core)
    fuel_id: str
    seed: int
    sim_hz: int                             # 100..1000
    start_tick: int                         # tick da sessão da 1.ª amostra
    n_samples: int
    channels: list[TelemetryChannel]        # ordem = ordem das colunas
    pulls: list[PullSegment]                # {pull_index, start_index (incl.), end_index (excl.), state}
    events: list[LogEvent]                  # {index, type: event.knock|event.failure|event.limiter|run.state, payload}
    terminal_state: str                     # completed | aborted | engine_failed
    truncated: bool = False                 # puxada > 300 s

class DataLog(BaseModel):
    header: DataLogHeader
    t_sim_s: list[float]                    # len == n_samples
    data: dict[str, list[float | None]]     # chave = TelemetryChannel.name, na ordem do cabeçalho; null = ausente
    sha256: str
    log_id: str | None = None               # volátil, fora do hash
    created_at: str | None = None           # volátil, fora do hash
    source: Literal["simulated", "imported"] = "simulated"   # volátil, fora do hash
```

- 🟡 1 amostra por tick, à taxa total do laço, de `arming` até o estado terminal. Todos os canais escalares do catálogo (seção 5 de `contracts/websocket-telemetry.md`), sem `knock_spectrum` nem `cyl_pressure_trace`.
- 🟡 Os eventos gravam-se todos no log, incluindo `event.knock` acima do limite de taxa do WebSocket.

### 4.2 JSON (`GET /api/v1/runs/{run_id}/log?format=json`, import)

- 🟡 Ficheiro de download `run-<run_id>.json`, `application/json`.
- 🟡 Cada valor float32 serializa-se com `repr(float(np.float32(v)))` (round-trip exato); NaN vira `null`. O import converte de volta para float32 e recalcula o hash, por isso export → import preserva o `sha256`.
- 🟡 Import: ≤ 64 MB (descomprimido; `Content-Encoding: gzip` aceite), profundidade JSON ≤ 32, ≤ 256 canais. Validação: schema (`LOG_SCHEMA_INVALID`), `format_version` (`LOG_FORMAT_UNSUPPORTED`), hash (`LOG_HASH_MISMATCH`), duplicado (`LOG_ALREADY_IMPORTED`). `log_id` importado = `"imp-"` + 12 hex.

### 4.3 CSV (`GET /api/v1/runs/{run_id}/log?format=csv`)

- 🟡 Ficheiro `run-<run_id>.csv`, `text/csv; charset=utf-8`, gerado em streaming.
- 🟡 Separador `,`, ponto decimal, fim de linha `\n`, valor ausente = campo vazio, flags `0`/`1`. Eventos não entram no CSV.
- 🟡 1.ª linha: cabeçalho `nome (unidade)` por coluna. Colunas fixas iniciais: `t_sim_s (s)`, `tick (-)`; depois os canais na ordem do cabeçalho (ou na ordem de `?channels=`).
- 🟡 `tick = start_tick + índice da amostra`. `?decimate=n` (1–100) mantém 1 amostra a cada n.
- 🟡 Linhas: `n_samples + 1` (ex.: 15 000 amostras → 15 001 linhas).

```text
t_sim_s (s),tick (-),rpm (rpm),map_kpa (kPa),boost_bar (bar),lambda (-),lambda_measured (-),lambda_cyl1 (-),spark_deg_cyl1 (°BTDC),knock_sensor_v_cyl1 (V),knock_intensity_cyl1 (-),injector_pw_ms_cyl1 (ms),egt_c_cyl1 (°C),torque_nm (N·m),power_kw (kW),whp (hp),fuel_cut (flag)
```

| Unidade no cabeçalho | Canais (exemplos) |
|---|---|
| 🟡 `s` | `t_sim_s` |
| 🟡 `-` | `tick`, `lambda`, `lambda_measured`, `lambda_cyl<k>`, `knock_intensity_cyl<k>`, `afr`, `real_time_factor`, `lambda_target` |
| 🟡 `rpm` | `rpm`, `turbo_rpm` |
| 🟡 `kPa` | `map_kpa`, `baro_kpa`, `boost_target_kpa` |
| 🟡 `bar` | `boost_bar` (relativa), `cyl_pressure_peak_bar*` (absoluta) |
| 🟡 `V` | `knock_sensor_v_cyl<k>` |
| 🟡 `ms` | `injector_pw_ms_cyl<k>` |
| 🟡 `°BTDC` | `spark_deg_cyl<k>` |
| 🟡 `°` | `knock_retard_deg*` |
| 🟡 `°C` | `egt_c*`, `egt_pre_turbo_c`, `iat_c`, `ect_c`, `oil_temp_c` |
| 🟡 `N·m` | `torque_nm`, `torque_request_nm` |
| 🟡 `kW` | `power_kw` |
| 🟡 `hp` | `whp` |
| 🟡 `%` | `throttle_pct`, `wastegate_duty_pct`, `injector_duty_pct`, `load_pct`, `health_*_pct` |
| 🟡 `km/h` | `roller_speed_kmh` |
| 🟡 `flag` | `fuel_cut`, `ign_cut` |
| 🟡 `contagem` | `overrun_afterfire` |

- 🔴 Separador `;` com vírgula decimal (Excel pt-BR) em aberto (OQ-06 da telemetria). Padrão do MVP: `,` e ponto decimal.

### 4.4 Binário compactado `/data/logs/{run_id}.simlog.gz` e hash canónico

- 🟡 Conteúdo antes do gzip (nível 6), em ordem:
  1. Magic `b"SIMLOG1\n"` (8 bytes).
  2. Tamanho do cabeçalho canónico: `uint32` little-endian.
  3. Cabeçalho canónico UTF-8.
  4. Coluna `t_sim_s`: `float64` LE, `n_samples` valores.
  5. 1 coluna `float32` LE por canal, na ordem de `header.channels`; ausente = NaN quiet `0x7FC00000`.
  6. 64 bytes do `sha256` em hexadecimal ASCII.
- 🟡 Cabeçalho canónico: `json.dumps(header.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)`; floats do cabeçalho (payloads de eventos) arredondados a 6 casas antes da serialização.
- 🟡 Hash: `sha256(cabeçalho_canónico_utf8 + t_sim_s_float64_le + Σ colunas_float32_le)`. `log_id`, `created_at` e `source` ficam fora do hash.
- 🟡 Registo no banco (`datalog`): `log_id` (= `run_id` em logs simulados), `sha256` (único), `format_version`, `sim_hz`, `n_samples`, `n_channels`, `compressed_bytes`, `path` relativo a `data_dir`, `terminal_state`, `truncated`, `source`.
- 🟡 Tamanho: 15 s a 1000 Hz ≤ 3 MB. Escrita em ≤ 2 s após o estado terminal. Gzip inválido ou hash divergente: `LOG_CORRUPTED`.
- 🟡 Determinismo: 10 execuções com a mesma `seed`, `sim_hz`, calibração e comandos produzem o mesmo `sha256`, em SQLite e em PostgreSQL.

## 5. `SignedPackage` (pacotes de desafio e de tentativa)

Fonte: `_reversa_sdd/sdd/training-scenarios.md#8-design-e-interface` ("Pacote `SignedPackage`"), `#9-modelo-de-dados`, RF-06, RF-18 a RF-22, EC-01 a EC-09, apêndice "Exemplo de `SignedPackage`".

```python
class PackageProducer(BaseModel):
    app_version: str
    install_id: str                          # UUID4 local de app_meta, sem relação com pessoa
    nickname: str | None = None

class SignedPackage(BaseModel):
    format_version: int = 1                  # PACKAGE_FORMAT_VERSION
    kind: Literal["challenge", "attempt"]
    created_at: datetime                     # fora do hash
    producer: PackageProducer                # fora do hash
    payload: dict[str, Any]
    sha256: str                              # 64 hex
    hmac_sha256: str | None = None           # reservado; null no MVP
```

- 🟡 Hash: `sha256 = hex(SHA-256(JCS({"format_version": v, "kind": k, "payload": p})))`, com JCS conforme RFC 8785 (chaves ordenadas por unidades UTF-16, números no formato ECMAScript, sem espaços). Biblioteca `rfc8785` (PyPI, Apache-2.0). O frontend não calcula hashes.
- 🟡 `NaN` ou `Infinity` tornam o pacote não canonicalizável: 422 `PACKAGE_NOT_CANONICALIZABLE` no export e no import (no export, o `detail` aponta o caminho JSON).
- 🟡 Ficheiro: `simremap-<kind>-<id>-<8 primeiros hex do sha256>.simremap.json`; `<id>` = `scenario_id` (challenge) ou `attempt_id` (attempt). Tamanho ≤ 64 MiB.
- 🟡 Payload `challenge`: `{"scenario": Scenario completo (inclui hidden_defect), "initial_calibration": calibração inicial embutida}`.
- 🟡 Payload `attempt`: `Scenario` com `scenario_sha256`; `Attempt`; calibração congelada completa (seção 3); `DynoRun` das puxadas base e de evidência (resumo + curva bruta + `curve_sha256`); `EvaluationTrace` por puxada (100 Hz); resultado da sonda; `Evaluation` declarada; com `include_full_logs = true`, os `DataLog` completos (seção 4.2).
- 🟡 `scenario_sha256`: SHA-256 do JCS do conteúdo avaliável do `Scenario` (tudo menos `created_at`, `builtin`, `origin` e estatísticas). `evaluation_sha256`: JCS da `Evaluation` sem `evaluation_id` e `created_at`.
- 🟡 Import: recalcula o hash (`PACKAGE_HASH_MISMATCH`), recusa `format_version` maior (`PACKAGE_FORMAT_UNSUPPORTED`), JSON truncado (`PACKAGE_MALFORMED`), schema inválido (`PACKAGE_SCHEMA_INVALID`); compara `scenario_sha256` com o cenário local (`SCENARIO_VERSION_MISMATCH`); recalcula a avaliação e marca `evaluation_mismatch`; idempotente pelo `sha256`.
- 🟡 Premissa do plan: integridade só por SHA-256 + recálculo da avaliação + replay opcional; sem HMAC e sem PIN de instrutor no MVP. O SHA-256 deteta corrupção e edição, não prova autoria.

```json
{
  "format_version": 1, "kind": "challenge",
  "created_at": "2026-10-18T10:00:00Z",
  "producer": {"app_version": "1.0.0", "install_id": "8f0c2b7e-0d1a-4c55-9a43-1b2f3e4d5c6a", "nickname": "prof_marcos"},
  "payload": {"scenario": {"scenario_id": "challenge-400whp-e27", "kind": "challenge"}},
  "sha256": "<64 hex>",
  "hmac_sha256": null
}
```

## 6. CSV de notas do instrutor

Fonte: `_reversa_sdd/sdd/training-scenarios.md#8-design-e-interface` ("CSV de notas (`gradesCsv.ts`)"), RF-25, RF-26.

- 🟡 Gerado no navegador por `frontend/src/features/scenarios/gradesCsv.ts` (função pura), sem endpoint REST.
- 🟡 UTF-8 sem BOM. Padrão pt-BR: separador `;` e vírgula decimal. Opção RFC 4180: separador `,` e ponto decimal.
- 🟡 Colunas fixas, nesta ordem:

```text
nickname;station;scenario_id;attempt_id;submission;passed;total_score;evaluation_mismatch;replay_status;package_sha256;imported_at
```

- 🟡 Depois, 1 coluna `score_<criterion_id>` por critério do cenário filtrado, na ordem de `ChallengeCriteria.criteria`.
- 🟡 1 linha por tentativa importada (última submissão).
- 🟡 `station` = 4 primeiros hex de `producer.install_id`, para separar nicknames iguais de estações diferentes (ex.: `joao (a1b2)` na tabela).
- 🟡 `passed`: `true`/`false`. `total_score` e `score_*`: 1 casa decimal. `replay_status` ∈ `not_run|running|verified|mismatch|incompatible_version`. `imported_at` em ISO 8601 UTC.
- 🟡 Proteção contra injeção de fórmulas: toda célula que começa por `=`, `+`, `-`, `@`, tabulação ou retorno de carro recebe o prefixo `'` (ex.: `'=HYPERLINK(1)`).
- 🟡 Valores com o separador, aspas ou quebra de linha vão entre aspas duplas, com aspas internas duplicadas (RFC 4180).

## 7. Versionamento e compatibilidade

Fonte: `_reversa_sdd/sdd/platform-foundation.md#9-modelo-de-dados` ("Constantes de versão", regra de compatibilidade), RF-21.

| Artefacto | Campo de versão | Valor atual | Onde aparece | Código ao recusar |
|---|---|---|---|---|
| 🟡 API REST | prefixo | `v1` | `/api/v1/`, `VersionInfo.api_version` | — (rota inexistente: `ROUTE_NOT_FOUND`) |
| 🟡 Envelope WebSocket | `v` | `1` | `WsEnvelope.v`, `VersionInfo.ws_envelope_version` | envelope descartado pelo cliente |
| 🟡 DataLog | `header.format_version` + magic `SIMLOG1` | `1` | JSON, `.simlog.gz`, `VersionInfo.datalog_format_version` | 422 `LOG_FORMAT_UNSUPPORTED` |
| 🟡 SignedPackage | `format_version` | `1` | pacote, `VersionInfo.package_format_version` | 422 `PACKAGE_FORMAT_UNSUPPORTED` |
| 🟡 Catálogo | `catalog_version` (SemVer) + `data_version` por veículo | `1.0.0` / `1` | `manifest.json`, `VehicleListResponse` | `CATALOG_INVALID` (arranque) |
| 🟡 Benchmark | `benchmark_id` | `reference-benchmark-baseline-v1` | curvas de referência | — |
| 🟡 Descritor de perfil de ECU | `descriptor_version` (SemVer) | `1.0.0` | `EcuProfileSummary` | — |
| 🟡 Calibração | `version` (inteiro por calibração, ≤ 1000) | — | `Calibration` | 409 `CALIBRATION_VERSION_LIMIT` |
| 🟡 Snapshot da física | `schema_version` | — | blob de `snapshot()` | `PHYSICS_SNAPSHOT_INVALID` |
| 🟡 Laudo forense | `generator_version` (SemVer) | — | `ForensicReport` | — |
| 🟡 Avaliador | `evaluator_version` (SemVer) | `1.0.0` | `Evaluation` | — |
| 🟡 Aplicação | `app_version` (SemVer) | `0.1.0` | `VersionInfo`, `PackageProducer` | 409 `REPLAY_VERSION_INCOMPATIBLE` (replay) |
| 🟡 Catálogo de erros | `error_catalog_sha256` | — | `VersionInfo` | — |

Regras:

1. 🟡 Leitores aceitam `format_version` ≤ ao valor atual e recusam valores superiores com o código do componente dono.
2. 🟡 Mudar a semântica de um campo exige incrementar o inteiro de versão do formato.
3. 🟡 As constantes ficam em `simremap.core.versions` (`API_VERSION`, `WS_ENVELOPE_VERSION`, `PACKAGE_FORMAT_VERSION`, `DATALOG_FORMAT_VERSION`). Um teste de contrato compara-as com `GET /api/v1/version`; mudar uma constante sem atualizar o `CHANGELOG` de formatos faz o teste falhar.
4. 🟡 Alterar dados do catálogo exige `tools/rehash.py`; alterar uma curva de referência exige nova versão do catálogo, senão o arranque falha.
5. 🟡 O replay de uma tentativa importada só corre com `producer.app_version` igual à versão local.

### 7.1 Regras canónicas de hash (resumo)

| Artefacto | Entrada | Serialização | Floats | Fonte |
|---|---|---|---|---|
| 🟡 Ficheiro do catálogo | bytes do ficheiro | — | — | `vehicle-catalog.md` RF-25 |
| 🟡 `catalog_sha256`, `data_sha256` | modelos do catálogo | chaves ordenadas, compacto, UTF-8 | `repr` | `vehicle-catalog.md` RF-24 |
| 🟡 `benchmark_sha256` | `[{path, sha256}]` das curvas no manifesto, ordenado por `path` | chaves ordenadas, compacto | — | D-FF-02 |
| 🟡 `content_hash` (calibração) | `{vehicle_id, profile_id, fuel_model, tables, strategies, profile_params}` | `sort_keys`, `(",", ":")`, `ensure_ascii=False` | 6 casas | `ecu-core.md#9-modelo-de-dados` |
| 🟡 `setup_hash` | `BaseSetup` | `sort_keys`, `(",", ":")` | 6 casas | `ecu-profiles.md#9-modelo-de-dados` |
| 🟡 `curve_sha256` | curva bruta da puxada | chaves ordenadas, `(",", ":")` | 6 casas | `dyno-bench.md#9-modelo-de-dados` |
| 🟡 `DataLog.sha256` | cabeçalho canónico + colunas binárias | `sort_keys`, `(",", ":")`, `ensure_ascii=False` | cabeçalho 6 casas; colunas binárias | `telemetry-datalogger.md` RF-16 |
| 🟡 `report_sha256` | `ForensicReport` sem este campo | JSON canónico | — | `knock-and-failure-model.md#9-modelo-de-dados` |
| 🟡 `scenario_sha256`, `evaluation_sha256`, `SignedPackage.sha256` | ver seção 5 | JCS (RFC 8785) | ECMAScript | `training-scenarios.md#8-design-e-interface` |

## 8. Divergências resolvidas

| ID | Divergência | Specs envolvidas | Decisão | Confiança |
|---|---|---|---|---|
| D-FF-01 | Nome do benchmark e campos de curva. | revisão R1 (`prd.md`), `vehicle-catalog` RF-29 | Nome exibido `Reference Benchmark Baseline v1`; `benchmark_id = "reference-benchmark-baseline-v1"` em cada curva e na resposta; `benchmark_sha256` na resposta. | 🟡 |
| D-FF-02 | `benchmark_sha256` "calculado sobre os arquivos de curva no `manifest.json`" sem algoritmo exato. | `vehicle-catalog` RF-29 | SHA-256 do JSON canónico da lista `[{path, sha256}]` das curvas do manifesto, ordenada por `path`. | 🟡 |
| D-FF-03 | Canais do CSV com nomes antigos de knock e pulso. | revisão R1 vs exemplo de cabeçalho da telemetria | Colunas `knock_sensor_v_cyl<k> (V)`, `knock_intensity_cyl<k> (-)`, `lambda_measured (-)` e `injector_pw_ms_cyl<k> (ms)`. | 🟡 |
| D-FF-04 | Calibração exportada sem formato próprio. | `ecu-core` §8 e §9 | O ficheiro é o JSON de `Calibration` do `GET`, sem campos de UI; import por `POST /api/v1/calibrations` com `source = payload` e recálculo do `content_hash`. | 🟡 |
| D-FF-05 | Separador do CSV do log (`,`) vs CSV de notas (`;` com vírgula decimal). | `telemetry-datalogger` §8 (OQ-06) vs `training-scenarios` §8 | Mantidos os dois padrões, cada um definido pelo dono; o separador `;` no log fica em aberto (🔴 OQ-06). | 🟡 |
| D-FF-06 | Integridade dos pacotes: HMAC/assinatura e PIN em aberto. | `training-scenarios` OQ-02, `requirements.md#10-lacunas` | Premissa: só SHA-256 + recálculo + replay, `hmac_sha256 = null`, sem PIN. | 🟡 |
| D-FF-07 | Regras de float diferentes entre hashes (`repr` no catálogo, 6 casas em calibração/curva/log, ECMAScript no JCS). | `vehicle-catalog`, `ecu-core`, `dyno-bench`, `telemetry-datalogger`, `training-scenarios` | Mantidas por artefacto e documentadas na seção 7.1; nenhum hash reutiliza a regra de outro. | 🟡 |
| D-FF-08 | Código de recusa de formato futuro por dono. | `platform-foundation` §9 | `LOG_FORMAT_UNSUPPORTED` (DataLog) e `PACKAGE_FORMAT_UNSUPPORTED` (pacote), ambos 422. | 🟡 |
