# Contrato interno: barramento do laço de simulação

> Feature: `001-simulador-remap` · Fase: plan · Gerado em 2026-10-18 (modo autônomo, greenfield)
> Confidência: 🟢 CONFIRMADO, 🟡 INFERIDO (padrão: specs planejadas), 🔴 LACUNA / DÚVIDA
> Escopo: contrato Python entre `physics`, `ecu`, `profiles`, `damage`, `telemetry` e `dyno` dentro do worker do laço. Não é API de rede.
> Orquestrador: `dyno-bench` (`SimTask`). Host: `platform-foundation` (`SimWorkerHost`).
> Delta: componente-novo.

## 1. Ordem por tick

Fonte: `_reversa_sdd/sdd/dyno-bench.md#6-requisitos-funcionais` (RF-03); `_reversa_sdd/sdd/engine-physics-core.md#6-requisitos-funcionais` (6.2 Fluxo principal); `_reversa_sdd/sdd/ecu-profiles.md#8-design-e-interface` ("Integração no laço"); `_reversa_sdd/sdd/knock-and-failure-model.md#8-design-e-interface`; `_reversa_sdd/sdd/telemetry-datalogger.md#6-requisitos-funcionais` (6.2 passo 4).

🟡 A ordem obrigatória é **sensors → ecu → physics → damage → telemetry**, com `dt = 1 / sim_hz` fixo. Um teste com stubs instrumentados regista as 5 chamadas em 10 000 ticks, sem inversão.

```python
# simremap/dyno/runner.py — SimTask.tick(), executado só no worker
def tick(self) -> None:
    k = self.tick_index
    dt = self.dt                                            # 1 / sim_hz, constante
    # 1. sensors: lê o estado do tick k-1 e o sinal de knock do último ciclo
    sensors = self.physics.read_sensors(self.damage.knock_signal())
    # 2. ecu: perfil (adaptador) + runtime genérico
    ecu = self.ecu.step(sensors, dt)                        # ProfiledEcu.step
    commands = ecu.commands
    if self.probe is not None:                              # só puxadas de sonda (ProbeOverrides)
        commands = apply_probe(commands, self.probe)        # + ignition_offset_deg após a arbitragem
    # (orquestração do dyno-bench, custo próprio ≤ 50 µs: controladores e DynoLoad)
    load = self.rig.load_for_tick(self.last_state, self.run)
    # 3. physics
    state = self.physics.step(commands, load, dt)
    # 4. damage (pode chamar physics.lock no mesmo tick)
    damage = self.damage.step(state, dt, ecu.status)
    # 5. telemetry: 1 amostra no log + acumulador da janela do frame
    self.sampler.on_tick(TickRecord(k, k / self.sim_hz, sensors, commands, ecu, state, damage, load))
    self.run.advance(state, damage)                         # máquina de estados da puxada
    self.last_state = state
    self.tick_index = k + 1
```

- 🟡 `read_sensors` do tick k usa o `KnockSignal` produzido pelo `damage.step` do tick k−1 (último ciclo de cada cilindro).
- 🟡 Falha catastrófica no tick k: `DamageModel.step` marca `engine_locked = True` e chama `PhysicsEngine.lock(mode)` no mesmo tick; a física não produz combustão no tick k+1; o `dyno-bench` passa a puxada a `engine_failed` com `ended_at_tick = k + 1` (`dyno-bench.md` RF-14; `knock-and-failure-model.md` RF-19).
- 🟡 Sonda (`ProbeOverrides`): `ignition_offset_deg` soma-se a `ActuatorCommands.ignition_advance_deg` depois da arbitragem da ECU; `knock_control_open_loop = true` fixa o retardo de knock em 0°; `damage_enabled = false` (`dyno-bench.md` RF-26; `training-scenarios.md#8-design-e-interface`).
- 🟡 Troca de calibração: o comando `apply_calibration` entra na fronteira de tick, antes do passo 1; nenhum tick mistura duas versões (`ecu-core.md` RF-27).
- 🟡 Sessão sem puxada: o laço corre na mesma ordem (motor em marcha lenta ou parado) e o sampler emite frames com `run_id = null`; o log só grava entre `arming` e o estado terminal.

## 2. Orçamento de tempo por estágio (1000 Hz, `dt` = 1 ms)

Fonte: `engine-physics-core.md#7-requisitos-não-funcionais` (RNF-01, G-02); `ecu-core.md#7-requisitos-não-funcionais` (RNF-01, G-01); `ecu-profiles.md#3-goals-objetivos` (G-07); `knock-and-failure-model.md#7-requisitos-não-funcionais` (RNF-01); `telemetry-datalogger.md#7-requisitos-não-funcionais` (RNF-01); `dyno-bench.md#7-requisitos-não-funcionais` (RNF-01).

| Estágio | Chamada | Média | P95/P99 | Máximo | Medição |
|---|---|---|---|---|---|
| 🟡 sensors + physics | `read_sensors` + `step` | **≤ 0,5 ms** | P99 ≤ 2,0 ms | — | `pytest-benchmark`, `muscle-v8-sc` 7500 rpm WOT, 1 núcleo |
| 🟡 ecu (runtime) | `EcuRuntime.step` | — | **P99 ≤ 0,1 ms** | ≤ 0,5 ms | 100 000 ticks, 8 cilindros, todas as estratégias |
| 🟡 ecu (adaptador de perfil) | `ProfiledEcu` sem o runtime | — | P99 ≤ 0,02 ms | — | idem |
| 🟡 damage | `DamageModel.step` | ≤ 0,05 ms | P99 ≤ 0,3 ms | — | V8 7500 rpm |
| 🟡 telemetry | `TelemetrySampler.on_tick` | — | P95 ≤ 60 µs | — | 8 cilindros |
| 🟡 dyno (orquestração) | controladores, `DynoLoad`, máquina de estados | — | P95 ≤ 50 µs | — | — |
| 🟡 **Soma das médias** | — | ≈ 0,73 ms | — | — | margem ≈ 0,27 ms para filas e GC |

- 🟡 Mínimo de aceite: tempo real a 100 Hz em 100 % dos veículos (`dt` = 10 ms). Alvo: 1000 Hz.
- 🟡 Estouro de orçamento não altera resultados: o worker conta `overrun_ticks`, publica `real_time_factor < 1,0` e emite `worker.overrun` (máximo 1/s). O `EcuRuntime` conta estouros > 0,5 ms e emite `budget_overrun` a cada 1000 (`ecu-core.md` EC-12).
- 🟡 `realtime_factor < 0,5` durante 5 s gera aviso `realtime_degraded`, sem alterar a física (`dyno-bench.md` EC-03).
- 🔴 O cumprimento de 1000 Hz no modo `process` com telemetria a 50 FPS decide-se por benchmark no Sprint 1 (`platform-foundation.md` OQ-01; `engine-physics-core.md` OQ-01).

## 3. Pontos de integração (assinaturas Python)

Convenção: as listas por cilindro têm comprimento exato `n_cyl`, índice 0 = cilindro 1. No hot path usam-se `dataclass(slots=True)` com listas de float; os modelos Pydantic da seção 4 são as formas de fronteira (testes, snapshots decimados, serialização). Fonte: `ecu-core.md#9-modelo-de-dados` (nota sobre `EcuStatus`); `ecu-profiles.md#9-modelo-de-dados` ("Saídas por tick").

### 3.1 `PhysicsEngine` (dono: engine-physics-core)

Fonte: `_reversa_sdd/sdd/engine-physics-core.md#8-design-e-interface` ("API Python pública", "Ordem interna do `step()`").

```python
class PhysicsEngine:
    def __init__(self, config: PhysicsConfig, vehicle: VehicleSpec, fuel: FuelSpec) -> None: ...
    def read_sensors(self, knock_signal: KnockSignal | None = None) -> SensorReadings: ...
    def step(self, commands: ActuatorCommands, dyno_load: DynoLoad, dt: float) -> EngineState: ...
    def lock(self, reason: str) -> None: ...            # chamado pelo DamageModel; reason = FailureMode
    def reset_mechanical(self) -> None: ...             # após POST .../engine/restore; 0 rpm, temperaturas do ambiente
    def set_fuel(self, fuel: FuelSpec) -> None: ...     # só com rpm == 0
    def snapshot(self) -> bytes: ...                    # cabeçalho JSON canónico + float64 LE; sem pickle
    def restore(self, blob: bytes) -> None: ...
    def state_digest(self) -> str: ...                  # SHA-256 hex do estado canónico

class PhysicsError(Exception):
    code: str   # PHYSICS_CONFIG_INVALID | PHYSICS_DT_MISMATCH | ACTUATOR_COMMAND_INVALID
                # PHYSICS_NUMERIC_DIVERGENCE | PHYSICS_FUEL_CHANGE_WHILE_RUNNING | PHYSICS_SNAPSHOT_INVALID
    detail: str
```

- 🟡 `step` valida `commands` antes de alterar estado: lista com tamanho errado ou valor fora do limite levanta `ACTUATOR_COMMAND_INVALID`, o tick não avança e o digest fica igual.
- 🟡 `dt` diferente de `1/sim_hz` (tolerância 1e-12 s) levanta `PHYSICS_DT_MISMATCH`.
- 🟡 Ordem interna: validar → atuadores com dinâmica (borboleta τ 30 ms, VVT 150°/s, wastegate τ 50 ms) → volumes de gás e turbo por Heun em subpassos `h = dt/ceil(dt/1 ms)` → avanço de θ e eventos de combustão por ordem de ângulo → torque, rotação, temperaturas, EGT.
- 🟡 Motor bloqueado: `step` aceita comandos, ignora injeção e ignição e devolve `locked = True` até `reset_mechanical()`.

### 3.2 `EcuRuntime` (dono: ecu-core)

Fonte: `_reversa_sdd/sdd/ecu-core.md#6-requisitos-funcionais` (6.2 passo 7, RF-27 a RF-30), Apêndice D ("Pipeline do `step()`"), Apêndice G (`ProfileHooks`).

```python
@dataclass(slots=True)
class EcuStepResult:
    commands: ActuatorCommands
    status: EcuStatus
    events: list[EcuEvent]                     # 0..n por tick

class EcuRuntime:
    def __init__(self, compiled: CompiledCalibration, hooks: ProfileHooks,
                 hardware: EcuHardwareConfig) -> None: ...
    def step(self, sensors: SensorReadings, dt: float) -> EcuStepResult: ...
    def swap_calibration(self, compiled: CompiledCalibration, mode: Literal["full", "live_tables"]) -> None: ...
    def set_knock_open_loop(self, enabled: bool) -> None: ...   # só sondas (ProbeOverrides)

class ProfileHooks(Protocol):
    profile_id: str
    def supported_strategies(self) -> frozenset[str]: ...
    def validate_calibration(self, cal: Calibration, options: dict[str, bool]) -> list[tuple[str, str]]: ...
    def air_charge_mg(self, sensors: object, compiled: object) -> float | None: ...
    def adjust_requests(self, sensors: object, requests: object) -> None: ...   # sem alocação
```

- 🟡 Pipeline obrigatório do `step()`: (1) validar sensores e substituir falhas; (2) eixos de carga; (3) massa de ar e lambda alvo; (4) compensações, malha fechada, trims, pulso e duty; (5) avanço e knock control; (6) alvo e duty de boost; (7) pedidos de failsafe, limitador, two-step, antilag, powershift, overrun e `adjust_requests`; (8) arbitragem, clamps, escrita de `ActuatorCommands`, `EcuStatus` e `EcuEvent`.
- 🟡 Arbitragem: failsafe (1) > limitador (2) > two-step/antilag/powershift (3) > overrun (4) > normal (5).
- 🟡 `CompiledCalibration` usa listas Python e `bisect`, sem Pydantic nem alocação por tick.
- 🟡 `EcuHardwareConfig` (vazão, `ref_pressure_kpa`, dead time, AFR estequiométrico, densidade, `n_cyl`, cilindrada) é entregue na compilação; vem da `BaseSetup` (standalone) ou do catálogo (OEM). Fonte: `ecu-profiles.md#9-modelo-de-dados` (OQ-01).

### 3.3 `ProfiledEcu` (dono: ecu-profiles)

Fonte: `_reversa_sdd/sdd/ecu-profiles.md#8-design-e-interface` ("Integração no laço"), `#9-modelo-de-dados` (`ProfileStatus`, `ProfileEvent`).

```python
@dataclass(slots=True)
class ProfiledEcuStepResult(EcuStepResult):
    profile_status: ProfileStatus
    profile_events: list[ProfileEvent]

class ProfiledEcu:
    def __init__(self, runtime: EcuRuntime, adapter: HardwareAdapter,
                 hardware: VehicleEcuHardware, override: HardwareOverride | None) -> None: ...
    def step(self, sensors: SensorReadings, dt: float) -> ProfiledEcuStepResult: ...
    # (1) sensor_view = adapter.transform_sensors(sensors)      escalas declaradas, sincronismo
    # (2) result = runtime.step(sensor_view, dt)                hooks do perfil
    # (3) adapter.transform_commands(result.commands)           offset de PMS, ordem de ignição,
    #                                                           cortes sem sincronismo, pulso curto m1-race

class ProfileSessionGuard(Protocol):
    def can_start_run(self, session_id: str) -> list[str]: ...  # itens pendentes; vazio = pode arrancar
```

- 🟡 `EcuStatus` guarda os valores **comandados**; o `ActuatorCommands` entregue à física leva os valores **reais** após o adaptador.
- 🟡 Em `awaiting_base_setup`, o adaptador corta faísca e injeção em todos os cilindros; o guard devolve itens pendentes e o `dyno-bench` responde 409 `ECU_SETUP_INCOMPLETE`.

### 3.4 `DamageModel` (dono: knock-and-failure-model)

Fonte: `_reversa_sdd/sdd/knock-and-failure-model.md#8-design-e-interface` ("API Python pública", "Ordem interna de `step()`").

```python
class DamageModel:
    def __init__(self, config: DamageConfig, vehicle: VehicleSpec, fuel: FuelSpec,
                 seed: int, damage_enabled: bool = True) -> None: ...
    def knock_signal(self) -> KnockSignal: ...          # último ciclo de cada cilindro
    def step(self, state: EngineState, dt: float,
             ecu_status: EcuStatus | None = None) -> DamageState: ...
    def spectrum_frame(self, t_sim_s: float) -> KnockSpectrumFrame: ...   # à taxa de frames, só com spectrum ativo
    def freeze_trace(self) -> DamageTraceSnapshot: ...  # cópia imutável do buffer de 30 s
    def restore(self) -> None: ...                      # saúde 1,0; a física é reposta pelo worker
    def set_fuel(self, fuel: FuelSpec) -> None: ...     # só com motor parado
    def snapshot(self) -> bytes: ...
    def load_snapshot(self, blob: bytes) -> None: ...
    def damage_digest(self) -> str: ...
```

- 🟡 Ordem interna: validar `dt` e listas → se `engine_locked`, devolver estado congelado sem sorteios → por `CombustionEvent` (ordem `t_sim_s`, cilindro): knock, sinal, pré-ignição/LSPI, dano por ciclo → grandezas contínuas → clamp de `health`, mapeamento de falhas, bloqueio, buffer.
- 🟡 `build_forensic_report(...)` é função pura, corre numa thread do pool da API, nunca no tick.
- 🟡 `event.knock` sai com classe ≥ `light` e no máximo 10 eventos/s por cilindro; `event.failure` sai a cada `FailureEvent`.

### 3.5 `TelemetrySampler` (dono: telemetry-datalogger)

Fonte: `_reversa_sdd/sdd/telemetry-datalogger.md#6-requisitos-funcionais` (6.2 passos 4 a 7, RF-05, RF-06, RF-14 a RF-16), `#8-design-e-interface` ("Decimação e agregação"). A spec não fixa a assinatura; a forma abaixo é decisão do plan (D-BUS-06).

```python
@dataclass(slots=True)
class TickRecord:
    tick: int
    t_sim_s: float
    sensors: SensorReadings
    commands: ActuatorCommands                  # valores reais entregues à física
    ecu: ProfiledEcuStepResult                  # status, events, profile_status, profile_events
    state: EngineState
    damage: DamageState
    load: DynoLoad

class TelemetrySampler:
    def __init__(self, channels: list[TelemetryChannel], sim_hz: int, fps: int,
                 vehicle: VehicleSpec, fuel: FuelSpec) -> None: ...
    def on_tick(self, rec: TickRecord) -> None: ...          # grava 1 amostra (se log aberto) e acumula a janela
    def set_fps(self, fps: int) -> None: ...                  # aplicado na fronteira de frame seguinte
    def set_spectrum(self, enabled: bool) -> None: ...
    def set_pressure_trace(self, cylinder: int | None) -> None: ...
    def open_log(self, run_id: str, header: DataLogHeaderSeed) -> None: ...   # em arming
    def mark_pull(self, pull_index: int, state: str) -> None: ...             # segmentos de multi_pull
    def close_log(self, terminal_state: str) -> DataLogArtifact: ...          # colunas + sha256
    def drain(self) -> list[bytes]: ...                       # frames e eventos serializados, já decimados
```

- 🟡 Fronteira de frame: `floor(k · fps / sim_hz)`; agregações `last`, `max`, `min`, `any`, `sum` por canal.
- 🟡 Gravação colunar em NumPy pré-alocado por blocos de 1 s; sem objetos Pydantic por tick. Acima de 300 s, `truncated = true` e só eventos continuam.
- 🟡 O ficheiro `.simlog.gz` é escrito fora do tick (thread do host), em ≤ 2 s após o estado terminal.

### 3.6 `SimTask` e comandos do worker (dono: platform-foundation / dyno-bench)

Fonte: `_reversa_sdd/sdd/platform-foundation.md#8-design-e-interface` ("Contrato do worker do laço físico").

```python
class SimTask(Protocol):                 # implementado por dyno-bench
    def setup(self, init_payload: bytes) -> None: ...
    def handle_command(self, command: dict[str, object]) -> None: ...
    def tick(self) -> None: ...                       # um passo dt = 1 / sim_hz
    def drain_outputs(self) -> list[bytes]: ...
    def teardown(self) -> None: ...
```

| Comando (`command["type"]`) | Origem | Efeito | Confirmação |
|---|---|---|---|
| 🟡 `run.start` | `POST .../runs` | Valida guard, abre puxada em `arming`, `sampler.open_log` | saída `run.state` |
| 🟡 `run.abort` | `POST .../abort`, `DELETE` sessão | Puxada `aborted`, coastdown físico sem pontos | saída `run.state` |
| 🟡 `calibration.apply` | `POST .../calibration`, `PUT .../base-setup` | `EcuRuntime.swap_calibration` na fronteira de tick | saída `ack` com `applied_t_sim_s` em ≤ 100 ms, senão 504 |
| 🟡 `ecu.swap` | `POST .../ecu/swap` | Troca `ProfiledEcu` (motor parado ou cortes totais) | saída `ack` |
| 🟡 `engine.restore` | `POST .../engine/restore` | `DamageModel.restore` + `PhysicsEngine.reset_mechanical` | saída `ack` |
| 🟡 `operator.throttle` | `control.throttle` (WS) | Muda `pedal_pct` só em `idle` | `error` `THROTTLE_LOCKED_BY_RUN` se recusado |
| 🟡 `telemetry.config` | `control.subscribe` (WS) | `set_fps`, `set_spectrum`, `set_pressure_trace` | — |
| 🟡 `stop` | shutdown, `DELETE` | `teardown`; join em ≤ 5 s | — |

- 🟡 Saídas (`drain_outputs`): envelopes já serializados (`telemetry.frame`, `run.state`, `event.*`), `ack`, `log` (máx. 50 linhas/s), `run.result` (`DynoRun` final) e `datalog.closed`. Os tipos de comando e de saída são decisão do plan (D-BUS-07).

## 4. Modelos do barramento (campos e unidades)

Convenção: `model_config = ConfigDict(frozen=True, extra="forbid")`. Nomes normalizados pela revisão R1 e pelo brief do plan (seção 7).

### 4.1 `DynoLoad` (dono: dyno-bench)

Fonte: `_reversa_sdd/sdd/dyno-bench.md#9-modelo-de-dados`.

```python
class DynoLoad(BaseModel):                  # dyno → physics, a cada tick
    reflected_inertia_kg_m2: float          # J_refl no virabrequim (kg·m²)
    load_torque_crank_nm: float             # T_load_crank ≥ 0 (N·m)
    gear: int                               # 0 = neutro
    wheel_to_crank_ratio: float             # G / k (-)
    pedal_pct: float                        # 0..100 (%), entrada do operador da bancada
    fan_air_speed_m_s: float                # m/s
    ambient: AmbientConditions              # temperature_c, pressure_kpa, relative_humidity (0..1)
    vehicle_speed_kmh: float = 0.0          # velocidade do rolo (km/h)          — D-BUS-03
    clutch_pressed: bool = False            # entradas de condutor para a ECU     — D-BUS-03
    launch_switch: bool = False
    shift_request: bool = False
    antilag_switch: bool = False
```

### 4.2 `SensorReadings` (dono: engine-physics-core)

Fonte: `_reversa_sdd/sdd/engine-physics-core.md#9-modelo-de-dados`, RF-17, RF-26, Apêndice A.10; campos consumidos pela ECU em `ecu-core.md` Apêndice F.

```python
class SensorReadings(BaseModel):
    t_sim_s: float                          # s, ≥ 0
    tick: int                               # ≥ 0
    rpm: float                              # rev/min
    crank_angle_deg: float                  # 0 ≤ θ < 720; 0 = PMS de compressão do cil. 1
    cam_intake_deg: float                   # ° de cambota, posição real do VVT de admissão
    cam_exhaust_deg: float
    map_kpa: float                          # kPa absoluta
    baro_kpa: float                         # kPa absoluta
    boost_pre_throttle_kpa: float           # kPa absoluta, antes da borboleta
    iat_c: float                            # °C
    ect_c: float                            # °C
    oil_temp_c: float                       # °C
    tps_pct: float                          # 0..100 %
    lambda_measured: float                  # wideband saturada 0,5–2,0 (-)
    egt_c: list[float]                      # °C por cilindro (termopar, τ 0,5–1,5 s)
    egt_collector_c: float                  # °C pré-turbina
    fuel_pressure_kpa: float                # kPa, rail (diferencial)
    battery_v: float                        # 6,0–16,0 V
    knock_sensor_v: list[float]             # por cilindro, 0,0–5,0 V
    knock_intensity: list[float]            # por cilindro, 0,0–1,0 (derivado de knock_sensor_v)
    turbo_rpm: float | None = None          # rev/min; None sem turbo
    wastegate_position_pct: float | None = None   # 0..100 %
    # Entradas exigidas pela ECU (D-BUS-03), copiadas do DynoLoad do tick anterior ou calculadas pela física
    pedal_pct: float = 0.0                  # 0..100 %
    gear: int = 0                           # 0 = neutro
    vehicle_speed_kmh: float = 0.0          # km/h
    oil_pressure_kpa: float = 0.0           # kPa (🔴 modelo físico simplificado a definir)
    clutch_pressed: bool = False
    launch_switch: bool = False
    shift_request: bool = False
    antilag_switch: bool = False
    sync_ok: bool = True                    # o adaptador do perfil recalcula o sincronismo
```

- 🟡 Sinal de knock (Apêndice A.10): `knock_sensor_v = clip(0,05 V + 1,5 V · KnockSignal.intensity + ruído(σ 0,02 V); 0,0; 5,0)`; `knock_intensity = clip((knock_sensor_v − 0,05) / (5,0 − 0,05); 0,0; 1,0)`. A ECU consome só `knock_intensity`; a telemetria publica os dois.
- 🟡 A ECU usa `egt_collector_c` nas regras de failsafe de EGT; `egt_c` por cilindro serve à telemetria e aos trims (D-BUS-04).
- 🟡 Wideband: atraso de transporte `0,02 s + 2 · 60 / rpm`, τ 0,1 s, σ 0,005, saturação [0,5; 2,0].

### 4.3 `ActuatorCommands` (dono: engine-physics-core)

Fonte: `_reversa_sdd/sdd/engine-physics-core.md#9-modelo-de-dados`. Nomes da física adotados (D-BUS-01).

```python
class ActuatorCommands(BaseModel):
    t_sim_s: float                          # s
    injector_pw_ms: list[float]             # ms por cilindro, 0–50
    injection_end_deg_btdc: list[float] | None = None   # ° BTDC, −360..720
    ignition_advance_deg: list[float]       # ° BTDC por cilindro, −30..60 (+ = avanço)
    fuel_cut: list[bool]                    # por cilindro
    spark_cut: list[bool]                   # por cilindro
    throttle_pct: float                     # 0..100 %, alvo da borboleta eletrónica
    wastegate_duty_pct: float = 0.0         # 0..100 %
    vvt_intake_target_deg: float = 0.0      # ° de cambota
    vvt_exhaust_target_deg: float = 0.0
    bypass_open: bool = False               # BOV (turbo) ou bypass (supercharger)
    antilag_air_pct: float = 0.0            # 0..100 %
    fuel_pump_duty_pct: float = 100.0       # 0..100 %
```

| Nome no `ecu-core` (Apêndice F) | Nome adotado (física) |
|---|---|
| 🟡 `ign_advance_deg` | `ignition_advance_deg` |
| 🟡 `throttle_target_pct` | `throttle_pct` |
| 🟡 `cam_intake_target_deg` | `vvt_intake_target_deg` |
| 🟡 `cam_exhaust_target_deg` | `vvt_exhaust_target_deg` |

- 🟡 As tabelas da ECU `cam_intake_target` e `cam_exhaust_target` mantêm o nome (são `TableKind`); só os campos do comando mudam.

### 4.4 `EngineState` (dono: engine-physics-core)

Fonte: `_reversa_sdd/sdd/engine-physics-core.md#9-modelo-de-dados`, RF-11, RF-18.

```python
class EngineState(BaseModel):
    t_sim_s: float; tick: int
    rpm: float                              # rev/min
    crank_angle_deg: float                  # °
    locked: bool; stalled: bool
    map_kpa: float; boost_pre_throttle_kpa: float; exhaust_manifold_kpa: float   # kPa abs
    t_manifold_c: float; t_intercooler_out_c: float | None                        # °C
    ve_true: list[float]                    # fração (-)
    m_air_mg: list[float]; m_fuel_mg: list[float]                                  # mg por ciclo
    lambda_cyl: list[float | None]          # None em corte de combustível
    lambda_collector: float | None
    ignition_advance_deg: list[float]       # ° BTDC efetivo
    burn_duration_deg: list[float]          # °
    p_max_kpa: list[float]                  # kPa abs
    theta_pmax_deg_atdc: list[float]        # ° ATDC
    t_unburned_max_k: list[float]           # K
    rod_force_peak_n: list[float]           # N
    piston_temp_c: list[float]; hot_spot_temp_c: list[float]                       # °C
    egt_c: list[float]; egt_collector_c: float                                     # °C (gás real, sem termopar)
    imep_gross_kpa: float; pmep_kpa: float; fmep_kpa: float                        # kPa
    torque_indicated_nm: float; torque_nm: float                                   # N·m (freio, cambota)
    power_kw: float; wheel_power_kw: float; whp: float                             # kW, kW, hp (0,7457 kW)
    fuel_flow_g_s: float; bsfc_g_kwh: float | None; thermal_efficiency: float
    turbo_rpm: float | None; compressor_pressure_ratio: float | None
    compressor_efficiency: float | None; surge_margin: float | None               # < 0 = surge
    wastegate_position_pct: float | None
    supercharger_rpm: float | None; supercharger_power_kw: float | None
    ect_c: float; iat_c: float
    events: list[CombustionEvent]           # eventos do tick (0..n)
    real_time_factor: float | None = None   # preenchido pelo worker
```

- 🟡 `CombustionEvent`: `cylinder`, `t_sim_s`, `rpm`, `theta_start_deg`, `pressure_kpa` (1 ponto por grau), `t_unburned_k`, `burned_fraction`, `p_max_kpa`, `theta_pmax_deg_atdc`, `t_unburned_max_k`, `rod_force_peak_n`, `imep_gross_kpa`, `lambda_real` (None em corte), `fuel_octane_ron`, `fuel_octane_mon`, `misfire`, `afterfire_energy_j`, `pop_event`.

### 4.5 `KnockSignal` (dono: engine-physics-core; produzido pelo knock-and-failure-model)

Fonte: `engine-physics-core.md#9-modelo-de-dados`; `knock-and-failure-model.md#9-modelo-de-dados`, RF-05.

```python
class KnockSignal(BaseModel):
    intensity: list[float]                  # por cilindro, ≥ 0, escala de MAPO em bar; 0 = sem knock
```

- 🟡 `intensity_i = g_i · I_w,i + b(rpm) · ε_i`; `I_w,i` só conta se `θ_k` cair na janela −5° a 60° ATDC; `g_i` = 0,85 nos cilindros das pontas e 1,0 nos centrais.

### 4.6 `DamageState` (dono: knock-and-failure-model)

Fonte: `_reversa_sdd/sdd/knock-and-failure-model.md#9-modelo-de-dados`.

```python
class DamageState(BaseModel):
    t_sim_s: float; tick: int
    damage_enabled: bool
    engine_locked: bool
    components: list[ComponentHealth]       # piston:i, rod:i, valves:i, head_gasket, bearings, turbo:turbine
    knock_last: list[KnockObservation | None]   # por cilindro, último ciclo
    knock_signal: KnockSignal
    piston_temp_eff_c: list[float]          # °C
    new_failures: list[FailureEvent]        # eventos do tick
    damage_digest: str | None = None        # só no fim de puxada

class ComponentHealth(BaseModel):
    component_id: str                       # ^(piston|rod|valves):[1-8]$|^head_gasket$|^bearings$|^turbo:turbine$
    kind: Literal["piston", "rod", "valves", "head_gasket", "bearings", "turbine"]
    cylinder: int | None
    health: float                           # 0..1 (1 = intacto)
    virtual_health: float                   # 0..1, modo dano desligado
    damage_by_cause: dict[str, float]       # knock, thermal, overload, overrev, preignition, pressure
    failed: bool
    first_damage_t_sim_s: float | None
```

- 🟡 `KnockObservation`: `cylinder`, `t_sim_s`, `rpm`, `lw_integral_end`, `theta_onset_deg_atdc`, `burned_fraction_onset`, `autoignited_fraction`, `mapo_kpa`, `intensity` (bar), `knock_energy_j` (J), `knock_class` (`none` < 0,3 ≤ `light` < 1,0 ≤ `moderate` < 3,0 ≤ `severe`), `in_sensor_window`, `preignition`, `p_preignition_kpa`.
- 🟡 Limites estruturais consumidos de `MechanicalLimits`: `max_rod_load_kn` (`F_lim_n = 1000 · max_rod_load_kn`), `max_cylinder_pressure_bar` (`p_lim_kpa = 100 · max_cylinder_pressure_bar`), `max_piston_temp_c`, `valve_float_rpm`, mais `rod_torque_limit_nm`, `egt_max_c`, `max_rpm`, `rev_limit_rpm`, `turbo_max_rpm`.

### 4.7 `EcuStatus` e `EcuEvent` (dono: ecu-core)

Fonte: `_reversa_sdd/sdd/ecu-core.md#9-modelo-de-dados`, RF-30, RF-33.

```python
class EcuStatus(BaseModel):                 # snapshot decimado; no laço: dataclass com slots
    t_sim_s: float
    lambda_target: float                    # (-)
    stft_pct: float; ltft_pct: float        # %
    closed_loop_active: bool
    fuel_mass_mg: list[float]               # mg por cilindro (comandado)
    injector_pw_ms: list[float]             # ms (comandado)
    inj_duty_pct: float                     # % = pw_ms / (120 000 / rpm) × 100
    ignition_advance_deg: list[float]       # ° BTDC comandado (D-BUS-01)
    knock_retard_deg: list[float]           # °
    boost_target_kpa: float                 # kPa abs
    wastegate_duty_pct: float               # %
    limiter_state: Literal["off", "soft", "hard"]
    active_strategies: list[str]
    arbitration_winner: str                 # failsafe | rev_limiter | two_step | ... | normal
    failsafe_actions: list[str]
    load_pct: float                         # % carga relativa
    torque_request_nm: float | None         # N·m; None nos perfis standalone
    calibration_hash: str                   # SHA-256 da calibração ativa

class EcuEvent(BaseModel):
    t_sim_s: float
    kind: Literal["limiter_hit", "failsafe_trip", "failsafe_release", "knock_retard",
                  "overboost_cut", "inj_duty_high", "closed_loop_limit", "two_step_timeout",
                  "antilag_protect", "overrun_protect", "sensor_fault", "budget_overrun"]
    cylinder: int | None = None
    value: float | None = None
    detail: str = ""
```

- 🟡 A tabela `knock_threshold` compara-se com `SensorReadings.knock_intensity` (0–1). O limite da tabela passa a 0,0–1,0 (D-BUS-05).
- 🟡 `ProfileStatus` e `ProfileEvent` (dono `ecu-profiles`) acompanham o `EcuStatus` no `TickRecord`; ver `ecu-profiles.md#9-modelo-de-dados`.

### 4.8 `PhysicsFault` (dono: engine-physics-core)

Fonte: `engine-physics-core.md#9-modelo-de-dados`, RF-23; mapeamento a partir de `HiddenDefect` em `training-scenarios.md#8-design-e-interface`.

```python
class PhysicsFault(BaseModel):
    kind: Literal["fuel_pump_weak", "injector_clogged", "boost_leak", "sensor_bias", "wastegate_stuck"]
    cylinder: int | None = None             # 1..8, injector_clogged
    fuel_pump_max_lph: float | None = None  # L/h, fuel_pump_weak
    injector_flow_factor: float | None = None   # 0..1, injector_clogged
    leak_area_mm2: float | None = None      # mm², boost_leak
    sensor_channel: str | None = None       # nome do campo de SensorReadings, sensor_bias
    sensor_bias: float | None = None        # unidade do canal
    stuck_position_pct: float | None = None # 0..100 %, wastegate_stuck (ignora wastegate_duty_pct)
    start_t_sim_s: float = 0.0              # s
```

| `HiddenDefect.kind` | `PhysicsFault` |
|---|---|
| 🟡 `fuel_pump_weak` | `kind = fuel_pump_weak`, `fuel_pump_max_lph` 60–250 |
| 🟡 `injector_clogged` | `kind = injector_clogged`, `cylinder`, `injector_flow_factor` 0,50–0,95 |
| 🟡 `iat_sensor_bias` | `kind = sensor_bias`, `sensor_channel = "iat_c"`, `sensor_bias` = `sensor_bias_c` (−30..30 °C) |
| 🟡 `wastegate_stuck` | `kind = wastegate_stuck`, `stuck_position_pct` 0–100 |

- 🟡 Máximo 8 falhas por sessão (`SessionCreateRequest.physics_faults` → `PhysicsConfig.faults`).

### 4.9 `ProbeOverrides` (dono: dyno-bench)

Fonte: `_reversa_sdd/sdd/dyno-bench.md#9-modelo-de-dados`, RF-26.

```python
class ProbeOverrides(BaseModel):            # só puxadas de sonda sem UI (training-scenarios)
    ignition_offset_deg: float = 0.0        # −10..10 °, somado a ActuatorCommands.ignition_advance_deg após a arbitragem
    knock_control_open_loop: bool = False   # True ⇒ retardo de knock fixo em 0°
    damage_enabled: bool = False            # sondas nunca danificam o motor
```

- 🟡 `probe` numa sessão sem `attempt_id`: 422 `PROBE_NOT_ALLOWED`; a puxada não arranca.

## 5. Determinismo

Fonte: `engine-physics-core.md` RF-20, RF-25, `#15-decisões-tomadas-decision-log`; `knock-and-failure-model.md` RF-32, RNF-03; `dyno-bench.md` RF-23, RNF-03; `telemetry-datalogger.md` RF-16, RNF-07; `platform-foundation.md#8-design-e-interface` ("Ritmo").

- 🟡 Tempo: `t_sim_s = tick_index / sim_hz`. O relógio de parede (`time.perf_counter`) só cadencia o tempo real e mede `overrun_ticks`; nunca entra no cálculo.
- 🟡 Proibido no código do laço: `time.time()`, `random`, `numpy.random` sem `Generator` semeado. Um teste de lint `ruff` com regra banida verifica os pacotes `physics`, `damage`, `ecu`, `profiles`, `dyno`, `telemetry`.
- 🟡 Semente: `SimulationSession.seed` (0..2^63−1). Omitida no pedido, o servidor gera-a e devolve-a. Na tentativa sem `seed` no cenário: `int(sha256(attempt_id)[:15], 16)`.
- 🟡 Árvore de substreams (D-BUS-02), todos com `numpy.random.Generator(PCG64(...))`:

| `spawn_key` | Componente | Filhos (ordem fixa de `spawn`) |
|---|---|---|
| 🟡 `(0,)` | physics | 1 por canal de ruído de sensor: `map`, `iat`, `ect`, `lambda`, `egt`, `rpm`, `tps`, `knock` |
| 🟡 `(1,)` | damage | `preignition`, `lspi`, `knock_noise`, `rod_weights`, `spectrum` |
| 🟡 `(2,)` | reservado (telemetria) | sem uso no MVP (o espectro vem do substream `spectrum` do dano) |

  Construção: `SeedSequence(seed, spawn_key=(i,)).spawn(n)`. Os sorteios do dano seguem ordem fixa por evento: ponto quente, depois LSPI.
- 🟡 Independência da UI: a `fps`, a subscrição e o número de conexões não alteram nenhum digest nem hash.
- 🟡 Digests e hashes verificáveis:

| Artefacto | Função | Regra canónica | Fonte |
|---|---|---|---|
| 🟡 Estado da física | `PhysicsEngine.state_digest()` | SHA-256 do estado canónico | `engine-physics-core.md` RF-20 |
| 🟡 Estado do dano | `DamageModel.damage_digest()` | SHA-256 do estado canónico | `knock-and-failure-model.md` RF-32 |
| 🟡 Curva da puxada | `DynoRun.curve_sha256` | JSON da curva bruta, chaves ordenadas, floats a 6 casas, separadores `(",", ":")` | `dyno-bench.md#9-modelo-de-dados` |
| 🟡 Log da puxada | `DataLog.sha256` | cabeçalho canónico + `t_sim_s` float64 LE + colunas float32 LE | `telemetry-datalogger.md` RF-16 |
| 🟡 Calibração | `Calibration.content_hash` | `{vehicle_id, profile_id, fuel_model, tables, strategies, profile_params}`, floats a 6 casas | `ecu-core.md#9-modelo-de-dados` |

  O detalhe dos formatos está em `contracts/file-formats.md`.
- 🟡 Critério: 20 execuções de 30 s simulados a 1000 Hz com a mesma `seed`, `sim_hz`, calibração e comandos produzem 20 `state_digest`, `damage_digest`, `curve_sha256` e `DataLog.sha256` idênticos.
- 🔴 Determinismo garantido só na mesma imagem e arquitetura; entre `amd64` e `arm64` fica fora do MVP (`engine-physics-core.md` OQ-04).

## 6. Isolamento do worker

Fonte: `_reversa_sdd/sdd/platform-foundation.md#8-design-e-interface` ("Contrato do worker do laço físico"), RF-11, RF-12, EC-04 a EC-07, EC-12.

- 🟡 (a) O event loop asyncio nunca chama `SimTask.tick`.
- 🟡 (b) O worker nunca importa `fastapi` nem toca no banco. O `VehicleSpec` e o `FuelSpec` chegam serializados (`model_dump_json`) em `setup`; o worker nunca lê ficheiros do catálogo.
- 🟡 (c) Comunicação só por `multiprocessing.Queue` limitadas (modo `process`, padrão, `start_method = spawn`) ou `queue.Queue` limitadas (modo `thread`, só testes). Ponte para asyncio por `loop.run_in_executor` numa thread leitora dedicada.
- 🟡 (d) Fila de saída (256): descarta o item mais antigo quando cheia e conta `dropped_outputs`. O worker nunca bloqueia.
- 🟡 (e) Fila de comandos (64): nunca descarta; cheia, `send()` devolve 503 `SIM_WORKER_BUSY` sem bloquear o event loop.
- 🟡 Canal de controlo dedicado (64) para `run.state`, `event.failure` e fecho de log, sem descarte (`telemetry-datalogger.md` EC-03).
- 🟡 Heartbeat a cada 0,5 s; ausência por 2 s marca a sessão como falhada (`worker.crashed`), sem restart automático.
- 🟡 Paragem: `stop` + join com timeout de 5 s; depois o processo é terminado. Shutdown do container em ≤ 10 s.
- 🟡 Capacidade: `max_active_sessions` padrão 1, máximo 2; 1 processo filho por sessão. Memória adicional ≤ 256 MB por sessão.
- 🟡 Logs do worker seguem pela fila de saída com tipo `log` (máximo 50 linhas/s; excedente em `log_dropped`).
- 🟡 Exceção não tratada no tick: puxada `aborted` com `internal_error`, envelope `error` `SIM_INTERNAL_ERROR`, sessão volta a `ready`; NaN detetado ⇒ mesmo caminho.

## 7. Divergências resolvidas

| ID | Divergência | Specs envolvidas | Decisão | Confiança |
|---|---|---|---|---|
| D-BUS-01 | Nomes em `ActuatorCommands`: `ign_advance_deg`, `throttle_target_pct`, `cam_*_target_deg` vs `ignition_advance_deg`, `throttle_pct`, `vvt_*_target_deg`. | `ecu-core` Apêndice F vs `engine-physics-core` §9 | Adotados os nomes da `engine-physics-core` (dona do contrato). `EcuStatus.ign_advance_deg` passa a `ignition_advance_deg` pela mesma regra de terminologia. | 🟡 |
| D-BUS-02 | Física e dano derivavam substreams de `SeedSequence(seed).spawn` sem separar componentes, o que gera filhos idênticos nos dois. | `engine-physics-core` §15 vs `knock-and-failure-model` RF-32 | Árvore com `spawn_key` por componente: physics `(0,)`, damage `(1,)`, reservado `(2,)`. | 🟡 |
| D-BUS-03 | A ECU lê `pedal_pct`, `gear`, `vehicle_speed_kmh`, `oil_pressure_kpa`, `clutch_pressed`, `launch_switch`, `shift_request`, `antilag_switch` e `sync_ok`, ausentes no `SensorReadings` da física. | `ecu-core` Apêndice F vs `engine-physics-core` §9 | Campos acrescentados ao `SensorReadings` com padrão seguro. Entradas de condutor e velocidade passam pelo `DynoLoad`. `oil_pressure_kpa` exige modelo simplificado na física (🔴 a definir). | 🟡 / 🔴 |
| D-BUS-04 | `egt_c` escalar na ECU vs lista por cilindro na física. | `ecu-core` Apêndice F vs `engine-physics-core` §9 | O failsafe de EGT usa `egt_collector_c` (pré-turbina); `egt_c` fica por cilindro. | 🟡 |
| D-BUS-05 | `knock_threshold` com limite 0–10 vs entrada da ECU `knock_intensity` 0–1. | `ecu-core` Apêndice A vs revisão R1 | Limite da tabela `knock_threshold` passa a 0,0–1,0, na escala de `knock_intensity`. | 🟡 |
| D-BUS-06 | `TelemetrySampler` sem assinatura definida. | `telemetry-datalogger` §8 | Assinatura da seção 3.5, com `TickRecord` único por tick. | 🟡 |
| D-BUS-07 | Tipos de comando e de saída do worker não definidos. | `platform-foundation` §8 (`SimTask.handle_command`) | Tabela da seção 3.6. | 🟡 |
| D-BUS-08 | Nomes de campo do `DynoLoad` citados pela física (`load_torque_nm`, `reflected_inertia_kgm2`) vs dono (`load_torque_crank_nm`, `reflected_inertia_kg_m2`). | `engine-physics-core` §10 vs `dyno-bench` §9 | Adotados os nomes do `dyno-bench` (dono do `DynoLoad`). | 🟡 |
| D-BUS-09 | `EcuRuntime.step` devolve "comandos, status e eventos" sem tipo. | `ecu-core` 6.2 passo 7 | Tipo `EcuStepResult` (dataclass com slots); `ProfiledEcuStepResult` acrescenta `profile_status` e `profile_events`. | 🟡 |
| D-BUS-10 | Gerador do espectro de knock duplicado (dano e telemetria). | `knock-and-failure-model` RF-06 vs `telemetry-datalogger` RF-20 | Um só gerador, `DamageModel.spectrum_frame`, com o substream `spectrum` do dano (ver `contracts/websocket-telemetry.md` D-WS-08). | 🟡 |
| D-BUS-11 | Sinal de knock e nomes de lambda e pulso. | revisão R1 (`prd.md`) | `knock_sensor_v` (0–5 V) + `knock_intensity` (0–1) em `SensorReadings`; `lambda_measured`; `injector_pw_ms`. | 🟡 |
