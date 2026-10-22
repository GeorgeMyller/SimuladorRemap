# Spec: dyno-bench

**Versão:** 1.1
**Status:** Rascunho
**Autor:** reversa-spec-sdd
**Data:** 2026-10-18
**Reviewers:** N/A
**Sprint:** 2 (componente 4 da ordem aprovada)

---

## 1. Resumo

🟡 O componente `dyno-bench` implementa o dinamômetro virtual de rolo do SimuladorRemap: inércia do rolo, absorvedor por correntes de Foucault, modo bancada, sessões de simulação e os quatro tipos de puxada (`baseline_pull`, `sweep_pull`, `steady_state_hold`, `multi_pull`).
🟡 O componente orquestra o laço de simulação na ordem do contrato (sensors → ecu → physics → damage → telemetry), mede torque e potência pela aceleração do rolo, aplica a correção SAE J1349 ou DIN 70020 e persiste cada puxada com um resumo auditável.

---

## 2. Contexto e Motivação

**Problema:**
🟡 O aluno e o preparador não têm acesso a um dinamômetro de rolo. Uma hora de rolo físico custa caro e um erro de calibração quebra o motor real. Sem uma bancada virtual não existe puxada base, não existe curva antes vs. depois e não existe repetibilidade térmica para validar um mapa.

**Evidências:**
- 🟡 O PRD (seção 4, "Dinamômetro virtual") exige puxada base, varredura, carga estacionária e várias puxadas seguidas, com curvas de whp, torque, lambda e EGT.
- 🟡 O critério de aceite "Física" do PRD exige desvio < 5 % face às curvas de referência, e o hatch de referência tem 220 whp / 350 N·m de série.
- 🟡 As jornadas de Lucas (passo 1 e 6), Rodrigo (passos 3, 4 e 6) e Prof. Marcos (passos 2 e 4) dependem do dinamômetro.

**Por que agora:**
🟡 O Sprint 1 entrega `engine-physics-core` e `vehicle-catalog` com o `hatch-20t-gdi` validado. O Sprint 2 precisa do dinamômetro para fechar o laço com a ECU (`ecu-core`) e com o modelo de dano (`knock-and-failure-model`). Sem o `dyno-bench` nenhum outro componente é demonstrável ponta a ponta.

---

## 3. Goals (Objetivos)

- 🟡 G-01: A puxada base do `hatch-20t-gdi` com a calibração de série reproduz 220 whp ± 5 % (209 a 231 whp) e 350 N·m ± 5 % (332,5 a 367,5 N·m) de torque no motor, com correção SAE J1349 em condições padrão.
- 🟡 G-02: O laço orquestrado mantém fator de tempo real ≥ 1,0 a `sim_hz` = 100 no hardware de referência e alvo ≥ 1,0 a `sim_hz` = 1000.
- 🟡 G-03: Duas execuções com a mesma `seed`, o mesmo `sim_hz`, a mesma calibração e o mesmo `DynoRunRequest` produzem curvas com hash SHA-256 idêntico (100 % das execuções).
- 🟡 G-04: A `sweep_pull` mantém o erro de rastreio da rampa ≤ 50 rpm (P95) a 300 rpm/s em 4ª marcha, enquanto o motor tiver torque suficiente.
- 🟡 G-05: Uma `multi_pull` de 3 puxadas com 60 s de arrefecimento e ventilador ligado tem dispersão do pico de whp ≤ 3 %.

**Métricas de sucesso:**

| Métrica | Baseline atual | Target | Prazo |
|---------|---------------|--------|-------|
| 🟡 Desvio do pico de whp do hatch face à referência | inexistente | < 5 % | 2026-11-15 |
| 🟡 Desvio por ponto de RPM da curva de torque face à `ReferenceCurve` | inexistente | < 5 % em ≥ 95 % dos pontos | 2026-11-15 |
| 🟡 Fator de tempo real a 100 Hz no hardware de referência | inexistente | ≥ 1,0 | 2026-11-01 |
| 🟡 Latência entre `POST .../runs` e o estado `arming` | inexistente | < 200 ms | 2026-11-01 |
| 🟡 Reprodutibilidade por hash da curva | inexistente | 100 % | 2026-11-01 |

---

## 4. Non-Goals (Fora do Escopo)

- 🟡 NG-01: O componente não modela patinagem do pneu no rolo, aderência, pressão de pneu nem dinâmica de suspensão; o acoplamento roda-rolo é rígido (alinha com o não-objetivo do PRD de física de pneus).
- 🟡 NG-02: O componente não implementa dinamômetro de motor de bancada com eixo acoplado direto ao virabrequim nem dinamômetro hidráulico; só existe rolo inercial com absorvedor por correntes de Foucault.
- 🟡 NG-03: O componente não suporta mais de uma sessão ativa por container no MVP com o valor padrão; multiusuário síncrono fica fora do escopo (PRD).
- 🟡 NG-04: O componente não renderiza a bancada animada nem os gráficos; isso pertence a `dyno-cockpit-ui`.
- 🟡 NG-05: O componente não define o formato do datalog nem o transporte WebSocket; isso pertence a `telemetry-datalogger`. O `dyno-bench` só publica estados e amostras no barramento interno.
- 🟡 NG-06: O componente não calcula dano, knock nem laudo forense; consome `DamageState` e `FailureEvent` de `knock-and-failure-model`.
- 🟡 NG-07: O componente não aplica correção de perdas por coastdown (medição de perdas parasitas do rolo por desaceleração livre) no MVP.

---

## 5. Usuários e Personas

**Usuário primário:** 🟡 Lucas (iniciante em calibração OEM) faz a puxada base, a puxada exagerada e a puxada final de validação do Stage 1/Stage 2 no `hatch-20t-gdi`.

**Usuário secundário:** 🟡 Rodrigo (preparador intermediário) usa `steady_state_hold` para mapear células de VE e de ignição e `multi_pull` para provar repetibilidade térmica. 🟡 Prof. Marcos (instrutor) usa o modo instrutor (proteção do operador) para demonstrar knock ao vivo sem destruir o motor e compara puxadas antes vs. depois.

**Jornada atual (sem a feature):**
1. 🟡 O usuário estuda a teoria do remap sem carro nem rolo.
2. 🟡 O usuário edita tabelas em softwares offline sem resposta de potência, lambda ou EGT.
3. 🟡 O usuário só descobre o efeito real do mapa num carro de cliente, com risco de quebra.

**Jornada futura (com a feature):**
1. 🟡 O usuário cria uma sessão com veículo, calibração, perfil de ECU, `seed` e condições ambiente.
2. 🟡 O usuário executa uma puxada base e recebe curvas corrigidas de whp, torque, lambda e EGT com resumo.
3. 🟡 O usuário altera a calibração, executa nova puxada e compara com a base; o sistema aborta a puxada em falha catastrófica e indica o laudo.
4. 🟡 O usuário repete puxadas com arrefecimento e verifica a repetibilidade térmica.

---

## 6. Requisitos Funcionais

### 6.1 Requisitos Principais

| ID | Requisito | Prioridade | Critério de Aceite |
|----|-----------|-----------|-------------------|
| RF-01 | 🟡 O sistema deve criar uma `SimulationSession` via `POST /api/v1/sessions` com `vehicle_id`, `calibration_id`, `profile_id`, `seed`, `sim_hz`, `ambient`, `correction_standard`, `operator_protection` e `damage_enabled`. | Must | Request válido devolve 201 com `session_id` e `state = ready`; `vehicle_id` inexistente devolve 404 `VEHICLE_NOT_FOUND`; `sim_hz` fora de 100..1000 devolve 422 `VALIDATION_ERROR`. |
| RF-02 | 🟡 O sistema deve limitar o número de sessões ativas por container ao valor `SIMREMAP_MAX_ACTIVE_SESSIONS` (padrão 1). | Must | Com 1 sessão ativa e limite 1, um novo `POST /api/v1/sessions` devolve 409 `SIM_CAPACITY_EXCEEDED`; após `DELETE`, o próximo `POST` devolve 201. |
| RF-03 | 🟡 O sistema deve orquestrar cada tick na ordem sensors → ecu → physics → damage → telemetry, com `dt = 1 / sim_hz` fixo. | Must | Teste com stubs instrumentados regista a sequência exata das 5 chamadas em 10 000 ticks consecutivos, sem inversão. |
| RF-04 | 🟡 O sistema deve modelar o rolo com inércia `J_roll`, raio `r_roll`, perdas `T_loss = c0 + c1·ω_roll` e absorvedor de Foucault com atraso de 1ª ordem e capacidade dependente da velocidade. | Must | Com motor desligado, ω_roll inicial 50 rad/s e absorvedor a 0, a desaceleração medida coincide com `−T_loss/J_roll` com erro < 1 %. |
| RF-05 | 🟡 O sistema deve calcular o torque e a potência na roda pela inércia e aceleração do rolo, `P_roll = (J_roll·α_roll + T_abs + T_loss)·ω_roll`, e derivar o torque estimado no motor por `T_eng = T_wheel / (G·η_drv)`. | Must | Teste com aceleração constante sintética de 20 rad/s² e T_abs conhecido devolve P_roll com erro < 0,5 % face ao cálculo analítico. |
| RF-06 | 🟡 O sistema deve executar `baseline_pull` como puxada inercial pura (absorvedor desligado durante `running`), em plena carga, da `start_rpm` à `end_rpm`, e marcar a primeira puxada base concluída da sessão como `baseline_run_id`. | Must | Após uma `baseline_pull` concluída, `GET /api/v1/sessions/{session_id}` devolve `baseline_run_id` igual ao `run_id`; T_abs registado = 0 N·m em 100 % dos ticks de `running`. |
| RF-07 | 🟡 O sistema deve executar `sweep_pull` com taxa de rampa configurável em rpm/s (50 a 1000, padrão 300), marcha configurável (padrão 4ª) e controle PID do absorvedor sobre o erro entre RPM medida e RPM de referência `rpm_ref(t) = start_rpm + rate·t`. | Must | No `hatch-20t-gdi` de série, a 300 rpm/s em 4ª, o erro de rastreio P95 ≤ 50 rpm entre 2500 e 6000 rpm. |
| RF-08 | 🟡 O sistema deve executar `steady_state_hold` sobre uma lista de 1 a 64 células (rpm, carga alvo), segurando cada célula com PID de RPM no absorvedor e PID de carga no pedal, e devolver um ponto médio por célula sobre o último 1,0 s estável. | Must | Cada célula estabiliza com |erro de RPM| < 25 rpm e |erro de MAP| < 3 kPa durante 0,5 s antes da janela de média; célula que não estabiliza em `cell_timeout_s` (padrão 10 s) recebe `stable = false`. |
| RF-09 | 🟡 O sistema deve executar `multi_pull` com N puxadas (2 a 10, padrão 3) do tipo `sweep_pull` ou `baseline_pull`, separadas por intervalo de arrefecimento configurável (0 a 600 s, padrão 60 s) em marcha lenta e ventilador ligado. | Must | Um `multi_pull` com N = 3 gera 3 entradas em `pulls` com curvas próprias e um campo `repeatability.peak_whp_spread_pct`. |
| RF-10 | 🟡 O sistema deve aplicar a correção de potência SAE J1349, DIN 70020 ou nenhuma, a partir das condições ambiente da sessão, e guardar os valores observados e corrigidos. | Must | Com T = 25 °C, p = 99 kPa seco e humidade 0 %, o fator SAE = 1,000 ± 0,001; com T = 20 °C e p = 101,3 kPa, o fator DIN = 1,000 ± 0,001. |
| RF-11 | 🟡 O sistema deve suavizar a curva por média móvel centrada sobre pontos agregados em intervalos de 25 rpm, com janela configurável de 1 a 11 pontos ímpares (padrão 5), mantendo a curva bruta disponível. | Must | `smoothing_window = 1` devolve curva suavizada idêntica à bruta; janela par devolve 422 `VALIDATION_ERROR`. |
| RF-12 | 🟡 O sistema deve reportar potência na roda (whp) e potência estimada no virabrequim, `P_crank = P_wheel / η_drv`, com `η_drv` lido de `VehicleSpec.drivetrain_efficiency`. | Must | Para `η_drv = 0,85` e P_wheel = 164,1 kW, `power_crank_kw` = 193,1 kW ± 0,1. |
| RF-13 | 🟡 O sistema deve conduzir cada puxada pela máquina de estados `idle → arming → running → coastdown → completed`, com saídas terminais `aborted` e `engine_failed`, e publicar cada transição como evento `run.state`. | Must | Teste de transições rejeita qualquer transição fora da tabela da seção 8 e emite exatamente 1 evento `run.state` por transição. |
| RF-14 | 🟡 O sistema deve abortar a puxada para `engine_failed` no tick seguinte a um `FailureEvent` com `catastrophic = true`. | Must | Um `FailureEvent` catastrófico injetado no tick k gera `state = engine_failed` com `ended_at_tick = k + 1` e `abort_reason = catastrophic_failure`. |
| RF-15 | 🟡 O sistema deve abortar a puxada para `aborted` quando a EGT pré-turbina ultrapassar `MechanicalLimits.egt_limit_c + egt_abort_margin_c` (padrão 0 °C) durante ≥ 0,5 s contínuos e `egt_abort_enabled = true` (padrão true). | Must | Com limite 950 °C, EGT 960 °C por 0,6 s gera `aborted` com `abort_reason = egt_limit`; EGT 960 °C por 0,4 s não aborta. |
| RF-16 | 🟡 O sistema deve abortar a puxada por knock severo apenas com `operator_protection = true` (modo instrutor), quando a classe de knock `severe` ocorrer em ≥ 3 ciclos consecutivos de qualquer cilindro. | Should | Com proteção ligada, 3 ciclos severos consecutivos geram `aborted` com `abort_reason = severe_knock_protection`; com proteção desligada, a puxada continua. |
| RF-17 | 🟡 O usuário deve poder abortar uma puxada ativa via `POST /api/v1/sessions/{session_id}/runs/{run_id}/abort`. | Must | Abort em `running` devolve 200 com `state = aborted`, `abort_reason = user_abort`; abort de puxada terminal devolve 409 `RUN_NOT_ACTIVE`. |
| RF-18 | 🟡 O sistema deve persistir cada `DynoRun` com resumo: pico de whp e rpm do pico, pico de torque no motor e rpm, lambda mínimo e máximo em plena carga, EGT máxima, fator de correção, eventos e estado final. | Must | `GET /api/v1/runs/{run_id}` após reinício do container devolve o mesmo `summary` gravado antes do reinício. |
| RF-19 | 🟡 O sistema deve preservar o estado térmico (ECT, óleo, IAT, intercooler, turbo) entre puxadas da mesma sessão e aplicar o efeito do ventilador de arrefecimento ao intercooler e ao radiador. | Must | Em `multi_pull` com arrefecimento 0 s e ventilador desligado, a IAT no início da 3ª puxada é ≥ 5 °C acima da IAT no início da 1ª. |
| RF-20 | 🟡 O sistema deve recusar novas puxadas com 409 `ENGINE_DESTROYED` enquanto `DamageState.engine_locked = true`. | Must | Após `engine_failed`, `POST .../runs` devolve 409 `ENGINE_DESTROYED`; após `POST .../engine/restore`, devolve 202. |
| RF-21 | 🟡 O sistema deve recusar uma segunda puxada simultânea na mesma sessão com 409 `RUN_IN_PROGRESS`. | Must | Dois `POST .../runs` seguidos sem fim da 1ª: o 2º devolve 409. |
| RF-22 | 🟡 O usuário deve poder encerrar a sessão via `DELETE /api/v1/sessions/{session_id}`, que aborta a puxada ativa, para o worker e liberta o slot. | Must | `DELETE` com puxada ativa devolve 204, a puxada fica `aborted` com `abort_reason = session_closed` e o worker termina em < 1 s. |
| RF-23 | 🟡 O sistema deve gerar `seed` inteira aleatória quando o request não a enviar e devolvê-la na resposta, para permitir repetição. | Should | `POST /api/v1/sessions` sem `seed` devolve `seed` ∈ 0..2^63−1 e uma 2ª sessão com essa `seed` reproduz o hash da curva. |
| RF-24 | 🟡 O sistema deve aceitar `control.throttle` (WebSocket, dono `telemetry-datalogger`) só nos estados `idle` da sessão, e ignorá-lo com evento `error` durante `arming`, `running` e `coastdown`. | Should | `control.throttle` = 50 % em `running` não altera `pedal_pct` e gera envelope `error` com `code = THROTTLE_LOCKED_BY_RUN`. |
| RF-25 | 🟡 O sistema deve aceitar em `SessionCreateRequest` os campos `fuel_id` (validado contra os combustíveis permitidos do veículo), `physics_faults` (lista de `PhysicsFault`, máximo 8, repassada a `PhysicsConfig.faults`) e `attempt_id`. | Must | `fuel_id` fora da lista do veículo devolve 409 `FUEL_NOT_ALLOWED`; sessão com 1 `fuel_pump_weak` gera `PhysicsConfig.faults` com 1 item; sem os campos, a sessão usa o combustível de série e `faults = []`. |
| RF-26 | 🟡 O sistema deve aceitar `ProbeOverrides` em `DynoRunRequest.probe` só para puxadas de sonda abertas pelo `training-scenarios`, aplicando `ignition_offset_deg` depois da arbitragem da ECU, `knock_control_open_loop` e `damage_enabled = false`. | Must | Puxada de sonda com `ignition_offset_deg = 2` mostra avanço efetivo 2° acima do comandado pela ECU em 100 % dos ticks; pedido com `probe` sem `attempt_id` na sessão devolve 422 `PROBE_NOT_ALLOWED`. |

### 6.2 Fluxo Principal (Happy Path)

1. 🟡 O usuário envia `POST /api/v1/sessions` com `vehicle_id = hatch-20t-gdi`, `profile_id = oem-stage`, sem `calibration_id` (usa a calibração de série do catálogo), `sim_hz = 1000` e ambiente padrão SAE.
2. 🟡 O sistema valida o veículo no catálogo, carrega a calibração, inicializa o estado térmico quente (ECT 90 °C, óleo 95 °C), cria o worker do laço em `idle` e devolve 201 com `SimulationSession`.
3. 🟡 O usuário envia `POST /api/v1/sessions/{session_id}/runs` com `run_type = baseline_pull`, 4ª marcha, 2000 → 6300 rpm.
4. 🟡 O sistema devolve 202 com `DynoRun` em `arming`, engata a marcha, segura 2000 rpm ± 25 rpm durante 1,0 s com o absorvedor e passa a `running`.
5. 🟡 O sistema aplica pedal 100 %, solta o absorvedor (puxada inercial), mede α_roll a cada tick, agrega pontos a cada 25 rpm e publica `telemetry.frame` via `telemetry-datalogger`.
6. 🟡 Ao atingir `end_rpm`, o sistema passa a `coastdown`, aplica pedal 0 % e frenagem PID até `idle_rpm + 200`, e em seguida passa a `completed`.
7. 🟡 O sistema aplica a correção SAE, suaviza a curva, calcula o resumo, grava o `DynoRun` e define `baseline_run_id` na sessão.
8. 🟡 O usuário consulta `GET /api/v1/runs/{run_id}` e recebe pico de 220 whp ± 5 % e 350 N·m ± 5 %.

### 6.3 Fluxos Alternativos

**Fluxo Alternativo A — Falha catastrófica (jornada do Lucas):**
1. 🟡 O usuário aplica uma calibração com boost e avanço exagerados e inicia `sweep_pull`.
2. 🟡 O `knock-and-failure-model` emite `FailureEvent` catastrófico no tick k.
3. 🟡 O sistema passa a puxada para `engine_failed` no tick k + 1, corta pedal, grava `failure_event_id` no resumo e devolve o link `forensic_report_url = /api/v1/runs/{run_id}/forensic-report`.
4. 🟡 Novas puxadas devolvem 409 `ENGINE_DESTROYED` até o usuário restaurar o motor.

**Fluxo Alternativo B — Mapeamento por células (jornada do Rodrigo):**
1. 🟡 O usuário envia `steady_state_hold` com 16 células (rpm × MAP alvo).
2. 🟡 O sistema percorre as células na ordem enviada, estabiliza cada uma e devolve um `DynoCurvePoint` médio por célula com `stable` e `cell_index`.
3. 🟡 O sistema aborta por EGT se a regra do RF-15 disparar; as células já medidas ficam gravadas.

**Fluxo Alternativo C — Modo instrutor (jornada do Prof. Marcos):**
1. 🟡 O instrutor cria a sessão com `operator_protection = true`.
2. 🟡 Na puxada com knock severo, o sistema aborta pela regra do RF-16 antes da falha catastrófica e grava o evento.

**Fluxo Alternativo D — Várias puxadas:**
1. 🟡 O usuário envia `multi_pull` com N = 3 e `cooldown_s = 60`.
2. 🟡 Entre puxadas o sistema mantém marcha lenta, ventilador a `fan_air_speed_m_s`, e publica `run.state` com `phase = cooldown` e `pull_index`.
3. 🟡 Uma falha em qualquer puxada termina o `multi_pull` inteiro com o estado dessa puxada.

---

## 7. Requisitos Não-Funcionais

| ID | Requisito | Valor alvo | Observação |
|----|-----------|-----------|------------|
| RNF-01 | 🟡 Desempenho do laço | Fator de tempo real ≥ 1,0 a 100 Hz (obrigatório) e ≥ 1,0 a 1000 Hz (alvo), média por puxada | 🟡 Hardware de referência: 4 núcleos, 8 GB, sem GPU. O custo próprio do `dyno-bench` por tick é ≤ 50 µs (P95). |
| RNF-02 | 🟡 Latência de API | P95 < 100 ms para `GET /api/v1/runs/{run_id}` com curva de até 400 pontos; < 200 ms para `POST .../runs` | 🟡 Medido com SQLite local. |
| RNF-03 | 🟡 Determinismo | Hash SHA-256 da curva bruta canónica idêntico em 100 % das repetições | 🟡 Sem `time.time()` nem `random` sem seed no laço. |
| RNF-04 | 🟡 Memória | ≤ 256 MB adicionais por sessão ativa | 🟡 Curva agregada em memória; log completo é do `telemetry-datalogger`. |
| RNF-05 | 🟡 Qualidade | Cobertura ≥ 85 % no pacote `simremap.dyno`; `mypy --strict` e `ruff` sem erros | 🟡 Convenção do projeto. |
| RNF-06 | 🟡 Isolamento | O worker do laço não bloqueia o event loop asyncio: P99 de `GET /api/v1/health` < 50 ms durante uma puxada a 1000 Hz | 🟡 Worker em thread/processo dedicado. |

---

## 8. Design e Interface

**Componentes afetados:**
- 🟡 `backend/src/simremap/dyno/` (novo): `session.py` (gestor de sessões e slots), `runner.py` (worker do laço), `rig.py` (rolo + absorvedor), `controllers.py` (PID de RPM, PID de carga, rampa), `runs.py` (máquina de estados por `RunType`), `correction.py` (SAE/DIN), `curve.py` (agregação, suavização, resumo), `repository.py` (persistência).
- 🟡 `backend/src/simremap/api/routers/sessions.py` e `runs.py` (novos).
- 🟡 `backend/src/simremap/db/models/dyno.py` + migração Alembic.
- 🟡 Consumidores: `dyno-cockpit-ui` (REST + WS), `training-scenarios` (cria sessões e lê `DynoRun`), `knock-and-failure-model` (lê `session_id`, `run_id` e flags).

**Comportamento esperado (backend, sem UI própria):**

🟡 Modelo do rolo e acoplamento com a física. O acoplamento roda-rolo é rígido. Com `G = gear_ratio(gear) · final_drive`, `k = r_tire / r_roll`:
- 🟡 `ω_roll = ω_crank · k / G` (rad/s).
- 🟡 Inércia refletida no virabrequim: `J_refl = (J_roll · k² + J_drv_wheel) / G²` (kg·m²), sendo `J_drv_wheel` a inércia de rodas, semieixos e diferencial vista na roda (`VehicleSpec.driveline_inertia_kg_m2`).
- 🟡 Carga refletida no virabrequim: `T_load_crank = (T_abs + T_loss) · k / G` (N·m).
- 🟡 A física integra `α_crank = (η_drv · T_brake − T_load_crank) / (J_eng + J_refl)`; o `dyno-bench` entrega `J_refl` e `T_load_crank` em `DynoLoad` a cada tick.
- 🟡 Perdas do rolo: `T_loss = c0 + c1·ω_roll`, padrão `c0 = 2,0 N·m`, `c1 = 0,05 N·m·s/rad`.
- 🟡 Absorvedor de Foucault: `dT_abs/dt = (T_cmd − T_abs) / τ_abs`, `τ_abs = 0,05 s`; capacidade `T_max(ω) = T_cap · (1 − exp(−ω_roll/ω_c))`, `T_cap = 3000 N·m`, `ω_c = 10 rad/s`; potência máxima absorvida 600 kW; `T_cmd` ∈ 0..T_max (o absorvedor não motoriza).
- 🟡 Rolo padrão: `J_roll = 300 kg·m²`, `r_roll = 0,6096 m` (rolo de 24 polegadas).

🟡 Medição (como um dinamômetro inercial real):
- 🟡 `α_roll` por diferença central sobre janela de 21 ticks (configurável, ímpar, 5..101).
- 🟡 `F_roll = (J_roll·α_roll + T_abs + T_loss) / r_roll` (N); `P_wheel = F_roll · ω_roll · r_roll` (W).
- 🟡 `T_wheel = P_wheel / ω_wheel`; `T_eng = T_wheel / (G · η_drv)`; `P_crank = P_wheel / η_drv`.
- 🟡 Conversões: `whp = P_wheel_kw / 0,7457`; cv = kW / 0,7355.

🟡 Correção de potência (aplicada a potência e torque, fator constante por puxada porque o ambiente da sessão é fixo):
- 🟡 Pressão de vapor (Magnus): `p_sat = 0,61094 · exp(17,625·T_c / (T_c + 243,04))` kPa; `p_v = RH · p_sat`; pressão seca `p_d = p_baro − p_v`.
- 🟡 SAE J1349: `CF = 1,18 · (99 / p_d) · sqrt((T_c + 273,15) / 298,15) − 0,18`.
- 🟡 DIN 70020: `CF = (101,325 / p_baro) · sqrt((T_c + 273,15) / 293,15)`.
- 🟡 `none`: `CF = 1,0`. O fator é limitado a 0,90..1,10; fora disso a puxada grava `correction_out_of_range = true` e aplica o valor limitado.

🟡 Controladores:
- 🟡 PID de RPM no absorvedor: `T_cmd = Kp·e + Ki·∫e dt + Kd·de/dt`, `e = rpm_meas − rpm_ref`, anti-windup por clamping, padrão `Kp = 2,0 N·m/rpm`, `Ki = 4,0 N·m/(rpm·s)`, `Kd = 0,02 N·m·s/rpm`, sobrescrevíveis em `DynoRigConfig`.
- 🟡 PID de carga no pedal (só `steady_state_hold`): alvo em `map_kpa` ou `pedal_pct` fixo; padrão `Kp = 0,5 %/kPa`, `Ki = 2,0 %/(kPa·s)`, saída 0..100 %.
- 🟡 Rampa da `sweep_pull`: `rpm_ref(t) = start_rpm + rate · (t − t_running)`; se o absorvedor ficar em 0 N·m durante > 0,5 s e o erro passar de −100 rpm, o sistema grava evento `ramp_not_sustained` e continua.

🟡 Máquina de estados da puxada:

| Estado | Entrada | Saída permitida | Regra de saída |
|--------|---------|-----------------|----------------|
| 🟡 `idle` | Sessão criada ou puxada anterior terminada | `arming` | `POST .../runs` aceite. |
| 🟡 `arming` | Request aceite | `running`, `aborted`, `engine_failed` | RPM em `start_rpm ± 25` durante 1,0 s; timeout 10 s ⇒ `aborted` (`arming_timeout`). |
| 🟡 `running` | Arming estável | `coastdown`, `aborted`, `engine_failed` | `end_rpm` atingida, última célula medida ou limitador de rotação ativo por > 0,3 s. |
| 🟡 `coastdown` | Fim do `running` | `completed`, `engine_failed` | RPM ≤ `idle_rpm + 200`; timeout 15 s ⇒ `completed` com evento `coastdown_timeout`. |
| 🟡 `completed` | Coastdown terminado | nenhuma | Terminal. |
| 🟡 `aborted` | Abort do usuário, EGT, proteção, sessão fechada, timeout | nenhuma | Terminal; o sistema executa coastdown físico sem gravar pontos. |
| 🟡 `engine_failed` | `FailureEvent` catastrófico | nenhuma | Terminal; motor bloqueado. |

🟡 Payload do evento `run.state` (transporte e envelope `WsEnvelope` do `telemetry-datalogger`):

```json
{
  "v": 1, "type": "run.state", "seq": 1842, "t_sim_s": 37.412,
  "payload": {
    "session_id": "c3f1a2", "run_id": "r-01J9Z", "run_type": "multi_pull",
    "state": "running", "previous_state": "arming", "phase": "pull",
    "pull_index": 1, "pull_count": 3, "abort_reason": null,
    "progress_pct": 12.5, "rpm": 2010.0
  }
}
```

**Endpoints REST (caminhos completos sob o prefixo `/api/v1/`, erros `application/problem+json` com `code`):**

| Método e caminho | Request | Resposta | Erros |
|------------------|---------|----------|-------|
| 🟡 `POST /api/v1/sessions` | `SessionCreateRequest` | 201 `SimulationSession` | 404 `VEHICLE_NOT_FOUND`, 404 `CALIBRATION_NOT_FOUND`, 404 `ECU_PROFILE_NOT_FOUND`, 409 `SIM_CAPACITY_EXCEEDED`, 422 `VALIDATION_ERROR`, 422 `CALIBRATION_VEHICLE_MISMATCH` |
| 🟡 `GET /api/v1/sessions/{session_id}` | — | 200 `SimulationSession` (inclui `active_run_id`, `baseline_run_id`, `engine_locked`, `realtime_factor`) | 404 `SESSION_NOT_FOUND` |
| 🟡 `DELETE /api/v1/sessions/{session_id}` | — | 204 | 404 `SESSION_NOT_FOUND` |
| 🟡 `POST /api/v1/sessions/{session_id}/runs` | `DynoRunRequest` | 202 `DynoRun` (estado `arming`) | 404 `SESSION_NOT_FOUND`, 409 `RUN_IN_PROGRESS`, 409 `ENGINE_DESTROYED`, 409 `SESSION_CLOSED`, 422 `VALIDATION_ERROR`, 422 `RPM_RANGE_INVALID`, 422 `GEAR_NOT_AVAILABLE` |
| 🟡 `POST /api/v1/sessions/{session_id}/runs/{run_id}/abort` | corpo vazio | 200 `DynoRun` (estado `aborted`) | 404 `RUN_NOT_FOUND`, 409 `RUN_NOT_ACTIVE` |
| 🟡 `GET /api/v1/runs/{run_id}?include_curve=true&curve=smoothed` | query `include_curve` (bool, padrão true), `curve` (`raw` ou `smoothed`, padrão `smoothed`) | 200 `DynoRun` | 404 `RUN_NOT_FOUND` |

**Estados da UI (contrato para `dyno-cockpit-ui`):**
- 🟡 Estado vazio: sessão sem puxadas, `baseline_run_id = null`; a UI convida a fazer a puxada base.
- 🟡 Estado de carregamento: `arming` e `coastdown` expostos via `run.state` com `progress_pct`.
- 🟡 Estado de erro: `aborted` e `engine_failed` com `abort_reason` e, no 2º caso, `forensic_report_url`.
- 🟡 Estado de sucesso: `completed` com `summary` e curva suavizada.

---

## 9. Modelo de Dados

**Contratos Pydantic v2 (`simremap.dyno.contracts`):**

```python
from enum import StrEnum
from typing import Literal
from pydantic import BaseModel, Field, model_validator

class RunType(StrEnum):
    BASELINE_PULL = "baseline_pull"
    SWEEP_PULL = "sweep_pull"
    STEADY_STATE_HOLD = "steady_state_hold"
    MULTI_PULL = "multi_pull"

class RunState(StrEnum):
    IDLE = "idle"; ARMING = "arming"; RUNNING = "running"; COASTDOWN = "coastdown"
    COMPLETED = "completed"; ABORTED = "aborted"; ENGINE_FAILED = "engine_failed"

class AbortReason(StrEnum):
    USER_ABORT = "user_abort"; EGT_LIMIT = "egt_limit"
    SEVERE_KNOCK_PROTECTION = "severe_knock_protection"
    CATASTROPHIC_FAILURE = "catastrophic_failure"; ARMING_TIMEOUT = "arming_timeout"
    SESSION_CLOSED = "session_closed"; RUN_TIMEOUT = "run_timeout"
    INTERNAL_ERROR = "internal_error"

class CorrectionStandard(StrEnum):
    SAE_J1349 = "sae_j1349"; DIN_70020 = "din_70020"; NONE = "none"

class AmbientConditions(BaseModel):
    temperature_c: float = Field(25.0, ge=-20, le=50)
    pressure_kpa: float = Field(99.0, ge=60, le=110)   # barométrica absoluta
    relative_humidity: float = Field(0.0, ge=0, le=1)  # fração 0..1

class DynoRigConfig(BaseModel):
    roller_inertia_kg_m2: float = Field(300.0, gt=10, le=5000)
    roller_radius_m: float = Field(0.6096, gt=0.1, le=1.0)
    loss_c0_nm: float = Field(2.0, ge=0)
    loss_c1_nm_s_rad: float = Field(0.05, ge=0)
    absorber_tau_s: float = Field(0.05, gt=0, le=1)
    absorber_cap_nm: float = Field(3000.0, gt=0)
    absorber_omega_c_rad_s: float = Field(10.0, gt=0)
    absorber_max_power_kw: float = Field(600.0, gt=0)
    rpm_pid: tuple["float", "float", "float"] = (2.0, 4.0, 0.02)       # Kp, Ki, Kd
    load_pid: tuple["float", "float", "float"] = (0.5, 2.0, 0.0)
    accel_window_ticks: int = Field(21, ge=5, le=101)  # ímpar
    fan_air_speed_m_s: float = Field(12.0, ge=0, le=30)

class SessionCreateRequest(BaseModel):
    vehicle_id: str
    calibration_id: str | None = None        # None ⇒ VehicleSpec.stock_calibration_id
    profile_id: str = "oem-stage"           # EcuProfileId
    seed: int | None = Field(None, ge=0, le=2**63 - 1)
    sim_hz: int = Field(1000, ge=100, le=1000)
    ambient: AmbientConditions = AmbientConditions()
    correction_standard: CorrectionStandard = CorrectionStandard.SAE_J1349
    rig: DynoRigConfig = DynoRigConfig()
    operator_protection: bool = False        # modo instrutor (RF-16)
    egt_abort_enabled: bool = True
    damage_enabled: bool = True              # consumido por knock-and-failure-model
    fuel_id: str | None = None               # FuelId do vehicle-catalog; None ⇒ combustível de série do veículo
    physics_faults: list[ PhysicsFault ] = Field(default_factory=list, max_length=8)  # defeitos ocultos (engine-physics-core)
    attempt_id: str | None = None            # tentativa de training-scenarios que abriu a sessão

class ProbeOverrides(BaseModel):            # só puxadas de sonda sem UI (training-scenarios)
    ignition_offset_deg: float = Field(0.0, ge=-10.0, le=10.0)   # somado a ActuatorCommands.ignition_advance_deg após a arbitragem da ECU
    knock_control_open_loop: bool = False    # True ⇒ retardo de knock fixo em 0°
    damage_enabled: bool = False             # sondas nunca danificam o motor

class SimulationSession(SessionCreateRequest):
    session_id: str
    seed: int
    state: Literal["ready", "running", "engine_locked", "closed"]
    active_run_id: str | None = None
    baseline_run_id: str | None = None
    engine_locked: bool = False
    realtime_factor: float | None = None
    t_sim_s: float = 0.0
    created_at: str                           # ISO 8601 UTC (wall clock fora do laço)

class SteadyStateCell(BaseModel):
    rpm: float = Field(ge=500, le=12000)
    map_kpa: float | None = Field(None, ge=20, le=400)
    pedal_pct: float | None = Field(None, ge=0, le=100)
    hold_s: float = Field(3.0, ge=1.0, le=30.0)

    @model_validator(mode="after")
    def one_load_target(self) -> "SteadyStateCell":
        if (self.map_kpa is None) == (self.pedal_pct is None):
            raise ValueError("exatamente um de map_kpa ou pedal_pct")
        return self

class DynoRunRequest(BaseModel):
    run_type: RunType
    gear: int = Field(4, ge=1, le=10)
    start_rpm: float = Field(2000.0, ge=1000, le=10000)
    end_rpm: float | None = Field(None, ge=1500, le=12000)  # None ⇒ rev_limit − 200
    pedal_pct: float = Field(100.0, ge=0, le=100)
    ramp_rate_rpm_s: float = Field(300.0, ge=50, le=1000)
    cells: list["SteadyStateCell"] = Field(default_factory=list, max_length=64)
    cell_timeout_s: float = Field(10.0, ge=2, le=60)
    pull_count: int = Field(3, ge=2, le=10)
    pull_type: Literal["sweep_pull", "baseline_pull"] = "sweep_pull"
    cooldown_s: float = Field(60.0, ge=0, le=600)
    fan_on: bool = True
    smoothing_window: int = Field(5, ge=1, le=11)   # ímpar
    label: str | None = Field(None, max_length=80)
    probe: ProbeOverrides | None = None              # só puxadas de sonda do training-scenarios (RF-26)

class DynoLoad(BaseModel):            # dyno → physics, a cada tick
    reflected_inertia_kg_m2: float    # J_refl no virabrequim
    load_torque_crank_nm: float       # T_load_crank ≥ 0
    gear: int                         # 0 = neutro
    wheel_to_crank_ratio: float       # G / k
    pedal_pct: float                  # 0..100, entrada do operador da bancada
    fan_air_speed_m_s: float
    ambient: AmbientConditions

class DynoCurvePoint(BaseModel):
    rpm: float
    t_sim_s: float
    power_wheel_kw: float; power_wheel_kw_corr: float
    power_crank_kw: float; power_crank_kw_corr: float
    torque_wheel_nm: float
    torque_engine_nm: float; torque_engine_nm_corr: float
    lambda_: float = Field(alias="lambda")
    afr: float
    egt_c: float                      # pré-turbina
    map_kpa: float; iat_c: float; ect_c: float; oil_c: float
    ignition_deg_btdc: float
    knock_retard_max_deg: float
    cell_index: int | None = None     # só steady_state_hold
    stable: bool | None = None

class RunSummary(BaseModel):
    peak_whp: float; peak_whp_rpm: float
    peak_power_crank_kw: float
    peak_torque_engine_nm: float; peak_torque_rpm: float
    lambda_min: float; lambda_max: float          # pedal ≥ 90 %
    egt_max_c: float; iat_max_c: float
    correction_factor: float; correction_out_of_range: bool
    knock_events: int; event_codes: list[str]
    failure_event_id: str | None = None
    forensic_report_url: str | None = None

class PullResult(BaseModel):
    pull_index: int; state: RunState
    summary: "RunSummary"; curve: list["DynoCurvePoint"]

class DynoRun(BaseModel):
    run_id: str; session_id: str
    run_type: RunType; request: "DynoRunRequest"
    state: RunState; abort_reason: AbortReason | None = None
    started_at_tick: int; ended_at_tick: int | None = None
    calibration_id: str; calibration_hash: str     # SHA-256 da calibração aplicada
    seed: int; sim_hz: int
    summary: RunSummary | None = None
    curve: list["DynoCurvePoint"] = Field(default_factory=list)
    pulls: list["PullResult"] = Field(default_factory=list)  # só multi_pull
    repeatability: dict["str", "float"] | None = None           # peak_whp_spread_pct, peak_torque_spread_pct
    curve_sha256: str | None = None
```

🟡 Regras de validação adicionais: `end_rpm > start_rpm + 500` (senão 422 `RPM_RANGE_INVALID`); `gear` ≤ número de marchas do veículo (senão 422 `GEAR_NOT_AVAILABLE`); `cells` obrigatório e não vazio só para `steady_state_hold`; `smoothing_window` e `accel_window_ticks` ímpares; `end_rpm` limitado ao `rev_limit_rpm` de `MechanicalLimits`.

🟡 Dispersão de repetibilidade: `peak_whp_spread_pct = 100 · (max − min) / mean` sobre os picos das puxadas concluídas.

🟡 Hash canónico da curva: SHA-256 do JSON da curva bruta com chaves ordenadas, floats arredondados a 6 casas decimais, separadores `(",", ":")`.

**Entidades persistidas (SQLModel):**

```
simulation_session {
  session_id: str PK            // UUID4 hex
  vehicle_id: str               // FK lógica para o catálogo
  calibration_id: str
  profile_id: str
  seed: int
  sim_hz: int
  config_json: JSON             // ambient, rig, correction_standard, flags
  state: str                    // ready | running | engine_locked | closed
  baseline_run_id: str | None
  created_at: datetime UTC
  closed_at: datetime UTC | None
}
dyno_run {
  run_id: str PK                // ULID (ordenável)
  session_id: str FK -> simulation_session
  run_type: str
  state: str
  abort_reason: str | None
  request_json: JSON
  summary_json: JSON | None
  curve_raw_json: JSON          // ≤ 400 pontos agregados por puxada
  pulls_json: JSON | None
  calibration_hash: str
  curve_sha256: str | None
  started_at_tick: int
  ended_at_tick: int | None
  created_at: datetime UTC
  INDEX (session_id, created_at)
}
```

**Migrações necessárias:** 🟡 Sim. Uma migração Alembic cria `simulation_session` e `dyno_run`. Não há dados prévios a migrar. A curva suavizada não é persistida; é recalculada na leitura a partir da bruta e da janela do request.

---

## 10. Integrações e Dependências

| Dependência | Tipo | Impacto se indisponível |
|-------------|------|------------------------|
| 🟡 `engine-physics-core` (`SensorReadings`, `EngineState`, `physics.step`) | Obrigatória | Sem física não há puxada; `POST /api/v1/sessions` devolve 503 `PHYSICS_UNAVAILABLE`. |
| 🟡 `vehicle-catalog` (`VehicleSpec`, `MechanicalLimits`, `ReferenceCurve`, `drivetrain_efficiency`, `driveline_inertia_kg_m2`, relações de marcha, raio do pneu, `stock_calibration_id`) | Obrigatória | Sessão recusada com 404 `VEHICLE_NOT_FOUND`. |
| 🟡 `ecu-core` (`Calibration`, `ecu.step`) e `ecu-profiles` (`EcuProfileId`) | Obrigatória | Sessão recusada com 404 `CALIBRATION_NOT_FOUND` ou `ECU_PROFILE_NOT_FOUND`. |
| 🟡 `knock-and-failure-model` (`damage.step`, `DamageState`, `FailureEvent`) | Obrigatória | Sem modelo de dano o laço não arranca; erro 503 `DAMAGE_MODEL_UNAVAILABLE`. |
| 🟡 `telemetry-datalogger` (barramento de frames, `run.state`, log da puxada) | Obrigatória | Se o barramento falhar, a puxada continua e grava o resumo; o sistema emite aviso `telemetry_degraded` no `DynoRun`. |
| 🟡 `platform-foundation` (`ProblemDetail`, config, DB) | Obrigatória | Sem DB, `POST .../runs` devolve 503 `DATABASE_UNAVAILABLE`. |
| 🟡 SQLite/PostgreSQL via SQLModel async | Obrigatória | Retry de gravação 3 vezes com espera de 100, 200 e 400 ms; depois o `DynoRun` fica em memória com `persisted = false`. |
| 🟡 Redis | Opcional | Sem Redis, o estado da sessão fica só em memória do processo; nenhuma funcionalidade é perdida. |
| 🟡 NumPy | Obrigatória | Agregação e suavização vetorizadas. |

---

## 11. Edge Cases e Tratamento de Erros

| Cenário | Trigger | Comportamento esperado |
|---------|---------|----------------------|
| 🟡 EC-01: Limite de sessões atingido | `POST /api/v1/sessions` com sessão ativa e limite 1 | 409 `SIM_CAPACITY_EXCEEDED` com `detail` contendo o `session_id` ativo. |
| 🟡 EC-02: Motor bloqueado | `POST .../runs` com `engine_locked = true` | 409 `ENGINE_DESTROYED` com `detail` a indicar `POST /api/v1/sessions/{session_id}/engine/restore`. |
| 🟡 EC-03: Worker atrasado face ao tempo real | Custo do tick > `dt` no hardware | O laço continua determinístico em tempo simulado; `realtime_factor` < 1,0 é publicado; com `realtime_factor` < 0,5 durante 5 s o sistema emite aviso `realtime_degraded` (sem alterar resultados). |
| 🟡 EC-04: Falha de gravação na base de dados | Timeout ou erro de I/O ao gravar `DynoRun` | Retry 3 vezes (100/200/400 ms); persistindo a falha, o `DynoRun` fica em memória com `persisted = false` e o `GET` devolve-o enquanto a sessão existir. |
| 🟡 EC-05: Motor sem torque para a rampa | `sweep_pull` com taxa acima da capacidade do motor | Absorvedor em 0 N·m; evento `ramp_not_sustained`; a puxada continua até `end_rpm`; mais de 60 s em `running` ⇒ `aborted` com `abort_reason = run_timeout`. |
| 🟡 EC-06: Célula inatingível | `steady_state_hold` com MAP alvo acima do boost possível | Após `cell_timeout_s`, ponto gravado com `stable = false` e o sistema passa à célula seguinte. |
| 🟡 EC-07: Limitador de rotação antes do `end_rpm` | `end_rpm` acima do corte da calibração | Limitador ativo > 0,3 s ⇒ fim de `running` e passagem a `coastdown`; evento `rev_limiter_hit`. |
| 🟡 EC-08: Fator de correção fora da faixa | Ambiente extremo (ex.: 45 °C a 70 kPa) | Fator limitado a 0,90..1,10 e `correction_out_of_range = true`. |
| 🟡 EC-09: Calibração de outro veículo | `calibration_id` com `vehicle_id` diferente | 422 `CALIBRATION_VEHICLE_MISMATCH`. |
| 🟡 EC-10: Telemetria indisponível | Barramento de telemetria com falha ou consumidor WS desligado | A puxada continua; frames descartados; `DynoRun` com aviso `telemetry_degraded`. |
| 🟡 EC-11: Encerramento do container durante puxada | SIGTERM | O sistema aborta a puxada com `session_closed`, grava o estado em < 2 s e fecha a sessão. |
| 🟡 EC-12: Abort em puxada terminal | `POST .../abort` em `completed` | 409 `RUN_NOT_ACTIVE`. |
| 🟡 EC-13: Falha catastrófica durante o arrefecimento de `multi_pull` | `FailureEvent` em marcha lenta | O `multi_pull` termina em `engine_failed`; puxadas já concluídas ficam em `pulls`. |
| 🟡 EC-14: Exceção não tratada no worker | Erro de programação em qualquer passo do tick | Puxada em `aborted` com evento `internal_error`, envelope WS `error` com `code = SIM_INTERNAL_ERROR` e sessão em `ready`; o stack trace vai para o log do servidor. |
| 🟡 EC-15: Sonda fora de tentativa | `DynoRunRequest.probe` numa sessão sem `attempt_id` | 422 `PROBE_NOT_ALLOWED`; a puxada não arranca e a calibração fica intacta. |

---

## 12. Segurança e Privacidade

- 🟡 **Autenticação:** nenhuma. A aplicação é local-first, um container por estação; a API escuta por padrão só em `127.0.0.1` (config de `platform-foundation`).
- 🟡 **Autorização:** sem papéis no `dyno-bench`. O campo `operator_protection` e o `damage_enabled = false` são aceites de qualquer cliente local; o `training-scenarios` impõe as suas regras de tentativa.
- 🟡 **Dados sensíveis:** nenhum PII. Sessões e puxadas guardam só dados técnicos e o `nickname` não é armazenado aqui.
- 🟡 **Auditoria:** cada transição de estado e cada abort fica no log estruturado (JSON) com `session_id`, `run_id`, `t_sim_s` e `abort_reason`.
- 🟡 **Entrada:** todos os limites numéricos são validados pelo Pydantic antes de chegar ao laço, o que impede valores que gerem divisão por zero ou NaN; NaN detetado no laço ⇒ EC-14.

---

## 13. Plano de Rollout

- 🟡 **Estratégia:** big bang dentro do Sprint 2, atrás da flag `SIMREMAP_FEATURE_DYNO=1` (padrão ligada em dev e staging, ligada em prod ao fechar o Sprint 2).
- 🟡 **Validação antes de ligar em prod:** teste de aceite G-01 no CI (puxada base do hatch, 220 whp / 350 N·m ± 5 %) e teste de determinismo G-03.
- 🟡 **Como reverter (rollback):** desligar a flag (routers devolvem 404) e reverter a migração Alembic com `alembic downgrade -1`; a imagem Docker anterior continua compatível.
- 🟡 **Monitoramento pós-deploy:** `realtime_factor` médio por puxada, taxa de `aborted` por `abort_reason`, P95 de `GET /api/v1/runs/{run_id}` e contagem de `persisted = false`.

---

## 14. Open Questions

| # | Pergunta | Impacto | Dono | Prazo |
|---|---------|---------|------|-------|
| OQ-01 | 🟡 O arrefecimento da `multi_pull` pode correr acelerado (até 10× o tempo real) para não fazer o usuário esperar 60 s por puxada, mantendo o determinismo? | Médio | George | 2026-10-25 |
| OQ-02 | 🟡 A referência de 220 whp do hatch é medida em rolo inercial (estilo Dynojet) ou em rolo com carga? A resposta define se `baseline_pull` inercial é a base de comparação do G-01. | Alto | George | 2026-10-25 |
| OQ-03 | 🟡 O limite padrão de sessões deve subir para 2 em modo instrutor (demonstração + comparação lado a lado)? | Baixo | George | 2026-11-08 |
| OQ-04 | 🟡 Os campos `drivetrain_efficiency`, `driveline_inertia_kg_m2` e `stock_calibration_id` em `VehicleSpec` precisam de confirmação pelo dono do `vehicle-catalog`. | Alto | George | 2026-10-22 |
| OQ-05 | 🟡 ⚠️ ABERTO: o arming deve exigir ECT ≥ 80 °C e executar aquecimento automático quando a sessão começar fria? No MVP a sessão começa quente. | Baixo | George | 2026-11-08 |

---

## 15. Decisões Tomadas (Decision Log)

| Decisão | Alternativas consideradas | Racional |
|---------|--------------------------|---------|
| 🟡 A física integra a velocidade do virabrequim com inércia e carga refletidas entregues pelo `DynoLoad` | Integrar o rolo no `dyno-bench` com dois graus de liberdade e mola de acoplamento | Acoplamento rígido (NG-01) torna um único grau de liberdade exato e mais barato por tick; evita rigidez numérica a 100 Hz. |
| 🟡 A potência é medida pela aceleração do rolo, como num rolo inercial real | Ler `EngineState.torque` diretamente | A medição pelo rolo reproduz o efeito das inércias do motor e da transmissão que as folhas de dyno reais mostram, e torna a curva comparável à `ReferenceCurve`. |
| 🟡 `baseline_pull` é inercial pura e `sweep_pull` usa rampa controlada | Um único tipo de puxada com parâmetros | Alinha com as quatro modalidades do PRD e com a prática de rolo (inercial vs. carga). |
| 🟡 Abort por knock severo só com `operator_protection = true` | Abort sempre ligado | A jornada do Lucas exige ver o motor quebrar; o instrutor liga a proteção para demonstrações. |
| 🟡 Fator de correção constante por puxada a partir do ambiente da sessão | Correção por ponto com IAT | As normas SAE J1349 e DIN 70020 usam as condições de entrada do ar ambiente da célula de teste, não a IAT após o intercooler. |
| 🟡 Curva persistida bruta (≤ 400 pontos agregados) e suavização na leitura | Persistir as duas | Menos armazenamento e janela de suavização alterável sem nova puxada. |
| 🟡 Uma sessão ativa por container por padrão | Várias sessões por processo | Um container por estação (PRD) e o orçamento de CPU do laço a 1000 Hz no hardware de referência. |

---

## Apêndice

### Referências
- 🟡 `_reversa_sdd/prd.md` (seções 4, 7 e 9) e `_reversa_sdd/personas.md`.
- 🟡 SAE J1349 (correção de potência), DIN 70020.
- 🟡 Heywood, *Internal Combustion Engine Fundamentals* (perdas e inércias).
- 🟡 Specs relacionadas: `engine-physics-core.md`, `vehicle-catalog.md`, `ecu-core.md`, `knock-and-failure-model.md`, `telemetry-datalogger.md`, `dyno-cockpit-ui.md`, `training-scenarios.md`.

### Exemplo de request `sweep_pull`

```json
{
  "run_type": "sweep_pull", "gear": 4, "start_rpm": 2000, "end_rpm": 6300,
  "pedal_pct": 100, "ramp_rate_rpm_s": 300, "smoothing_window": 5,
  "label": "stage1-boost-1.6bar"
}
```

### Histórico de Revisões
| Versão | Data | Autor | Mudanças |
|--------|------|-------|---------|
| 🟡 1.0 | 2026-10-18 | reversa-spec-sdd | Criação inicial |
| 🟡 1.1 | 2026-10-18 | reversa-spec-sdd | Revisão R1 de consistência entre specs (decisões do usuário: knock, nomes de campo, códigos de erro, seq, campos de integração, prefixo /api/v1/, OEM-Stage, benchmark v1) |

## Relatório de avaliação (reversa-spec-sdd)

- 🟡 Score final: 100,0/100 (⭐ Excelente)
- 🟡 Iterações: 1 (scores: 100)
- 🟡 Breakdown: Completude 100 %, Testabilidade 100 %, Clareza 100 %, Escopo 100 %, Edge Cases 100 %
- 🟡 Gaps críticos remanescentes: nenhum
- 🟡 Sugestões remanescentes: nenhuma
- 🟡 Revisão R1 (2026-10-18): reavaliado após a revisão de consistência entre specs, score 100,0/100.
