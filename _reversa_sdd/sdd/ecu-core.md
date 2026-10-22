# Spec: ecu-core

**Versão:** 1.1
**Status:** Rascunho
**Autor:** reversa-spec-sdd
**Data:** 2026-10-18
**Reviewers:** N/A
**Sprint:** 2 (componente 5 na ordem aprovada)

---

## 1. Resumo

🟡 O ecu-core é o runtime genérico de ECU do SimuladorRemap, independente do perfil ativo. Ele define as tabelas 2D/3D com interpolação bilinear, a entidade versionada `Calibration`, as estratégias de controle (combustível speed-density, lambda, malha fechada, ignição, knock, boost, limitadores, two-step, antilag, powershift, overrun, failsafe) e a arbitragem determinística entre elas. A cada tick do laço de simulação, ele converte `SensorReadings` em `ActuatorCommands` em no máximo 0,1 ms. Os perfis (`oem-stage`, `ft-pro`, `m1-race`, `ht-elite`) são configurações e adaptadores sobre este núcleo, definidos na spec ecu-profiles.

---

## 2. Contexto e Motivação

**Problema:**
🟡 Os alunos e preparadores não têm onde observar o efeito causal de uma tabela de ECU no motor. Os editores oficiais só editam tabelas offline e não executam a lógica da ECU contra um motor simulado. Sem um runtime de ECU fiel, o dinamômetro virtual não reage a VE, lambda, avanço, boost, cortes e overrun como reage um carro real.

**Evidências:**
- 🟡 O PRD (seção 4, bloco ECU) exige VE, lambda alvo, avanço 3D, correções por cilindro, compensações por temperatura, malha fechada wideband, boost PID e por marcha, limitador, two-step, antilag, powershift e overrun.
- 🟡 Os critérios de aceite do PRD para Lucas e Rodrigo dependem de estratégias que provocam knock, EGT alta e falhas mecânicas quando mal calibradas, e ganho de potência quando bem calibradas.
- 🟡 A métrica de desempenho do PRD exige laço físico ≥ 100 Hz (alvo 1000 Hz) no hardware de referência, o que impõe um orçamento de CPU por tick para a ECU.

**Por que agora:**
🟡 O ecu-core está no Sprint 2. O dyno-bench e o knock-and-failure-model do mesmo sprint precisam de comandos de atuador reais para validar puxadas. Os perfis (Sprint 3) e a ecu-tuning-ui (Sprint 4) dependem dos contratos `Table3D`, `Calibration` e `StrategyConfig` definidos aqui.

---

## 3. Goals (Objetivos)

- [ ] 🟡 G-01: O sistema deve executar `EcuRuntime.step()` com p99 ≤ 0,1 ms por tick a 1000 Hz, para motores de até 8 cilindros, no hardware de referência (CPU 4 núcleos, 8 GB, sem GPU).
- [ ] 🟡 G-02: O sistema deve produzir comandos bit a bit idênticos (SHA-256 do log canónico) para a mesma calibração, `seed`, `sim_hz` e sequência de sensores, em 100 % das execuções repetidas.
- [ ] 🟡 G-03: O sistema deve calcular o pulso de injeção speed-density com erro < 0,5 % face à equação de referência do RF-06, em 100 % dos casos de teste.
- [ ] 🟡 G-04: O sistema deve rejeitar 100 % das tabelas com eixo não estritamente crescente, dimensão > 32×32 ou valor fora dos limites do tipo de tabela.
- [ ] 🟡 G-05: O sistema deve resolver os conflitos entre estratégias pela ordem documentada (failsafe > limitador > two-step/antilag/powershift > overrun > normal) em 100 % dos testes de arbitragem.
- [ ] 🟡 G-06: O usuário deve poder desfazer qualquer edição de tabela restaurando uma versão anterior, com 0 % de perda de histórico.

**Métricas de sucesso:**
| Métrica | Baseline atual | Target | Prazo |
|---------|---------------|--------|-------|
| 🟡 Tempo p99 de `step()` a 1000 Hz (4 e 8 cilindros) | inexistente | ≤ 0,1 ms | fim do Sprint 2 |
| 🟡 Cobertura de testes do pacote `simremap.ecu` | 0 % | ≥ 85 % | fim do Sprint 2 |
| 🟡 Testes de arbitragem e de estratégias aprovados | 0 | 100 % dos casos do Apêndice | fim do Sprint 2 |
| 🟡 Latência p95 de `PATCH .../tables/{table_id}` com 256 células (SQLite) | inexistente | < 100 ms | fim do Sprint 2 |
| 🟡 Latência entre `POST .../sessions/{session_id}/calibration` e a aplicação no laço | inexistente | ≤ 1 tick + 50 ms | fim do Sprint 2 |

---

## 4. Non-Goals (Fora do Escopo)

- 🟡 NG-01: O ecu-core não lê nem grava arquivos binários proprietários (.bin OEM bruto, .ftm, .m1) nem se liga a ECUs reais por USB/CAN/OBD2 (PRD, seção 5).
- 🟡 NG-02: O ecu-core não define a experiência de cada perfil (terminologia, layout, lógica por torque do OEM, wizard de mapa base, `BaseSetup`). Esses itens pertencem à spec ecu-profiles.
- 🟡 NG-03: O ecu-core não modela injeção direta com múltiplos eventos por ciclo nem o ângulo de início de injeção (SOI). O comando é um pulso por cilindro por ciclo.
- 🟡 NG-04: O ecu-core não implementa controle de marcha lenta em malha fechada, controle de tração, controle de transmissão nem sensor flex-fuel. A rotação no dinamômetro é imposta pelo dyno-bench.
- 🟡 NG-05: O ecu-core não aplica nenhuma conclusão de LTFT ao VE de forma automática. A transferência de trims para a tabela de VE fica para versões posteriores ao MVP.
- 🟡 NG-06: O ecu-core não calcula a física de combustão, knock real ou dano. Ele só lê `SensorReadings` (incluindo a intensidade de knock medida) e emite `ActuatorCommands`.
- 🟡 NG-07: O ecu-core não renderiza o editor de tabelas. A interface pertence à ecu-tuning-ui.

---

## 5. Usuários e Personas

**Usuário primário:** 🟡 Rodrigo, preparador intermediário em transição para standalone. Ele edita VE, lambda alvo, avanço 3D, PID de boost, two-step, powershift e failsafe, e espera que cada estratégia reaja no dinamômetro como numa ECU real.

**Usuário secundário:** 🟡 Lucas, aluno de remap OEM, que altera boost, avanço por cilindro, lambda em alta carga e overrun (pops & bangs). 🟡 Prof. Marcos, instrutor, que altera tabelas ao vivo entre puxadas para demonstrar causa e efeito à turma.

**Jornada atual (sem a feature):**
1. 🟡 O usuário edita tabelas num software offline sem motor simulado.
2. 🟡 O usuário não vê o efeito de um corte, de um atraso de ignição ou de um PID de boost mal ajustado.
3. 🟡 O usuário só descobre o erro num carro real, com risco de quebrar o motor.

**Jornada futura (com a feature):**
1. 🟡 O usuário cria ou clona uma calibração e edita células de tabelas 3D.
2. 🟡 O usuário aplica a calibração na sessão entre puxadas, ou ajusta ao vivo as tabelas marcadas como live-tunable.
3. 🟡 O sistema executa as estratégias a cada tick e o motor simulado responde com ganho, knock, EGT alta ou corte coerentes com a calibração.
4. 🟡 O usuário restaura uma versão anterior se a alteração piorar o resultado (Lucas, passo 4 da jornada; Rodrigo, passos 3 a 6).

---

## 6. Requisitos Funcionais

### 6.1 Requisitos Principais

| ID | Requisito | Prioridade | Critério de Aceite |
|----|-----------|-----------|-------------------|
| RF-01 | 🟡 O sistema deve validar `Axis` com 2 a 32 pontos finitos e estritamente crescentes, e rejeitar o resto com `TABLE_AXIS_NOT_MONOTONIC` ou `TABLE_SIZE_EXCEEDED`. | Must | Eixo `(500, 1000, 1000)` retorna 422 `TABLE_AXIS_NOT_MONOTONIC`; eixo com 33 pontos retorna 422 `TABLE_SIZE_EXCEEDED`; eixo com `NaN` retorna 422 `TABLE_VALUE_NOT_FINITE`. |
| RF-02 | 🟡 O sistema deve validar `Table2D` e `Table3D` contra o formato (linhas = pontos de y, colunas = pontos de x), a unidade e os limites mín/máx do tipo de tabela (Apêndice A). | Must | Tabela `ve` com célula 151 % retorna 422 `TABLE_VALUE_OUT_OF_RANGE` com `row`/`col` no `detail`; matriz 16×15 com eixo x de 16 pontos retorna 422 `TABLE_SHAPE_MISMATCH`; unidade diferente da prevista retorna 422 `TABLE_UNIT_MISMATCH`. |
| RF-03 | 🟡 O sistema deve interpolar `Table2D` de forma linear e `Table3D` de forma bilinear, com clamp nas bordas dos eixos (sem extrapolação). | Must | Na tabela de teste do Apêndice B, o ponto (x = 2250, y = 75) devolve o valor analítico com erro < 1e-9; pontos fora dos eixos devolvem o valor da borda mais próxima. |
| RF-04 | 🟡 O sistema deve persistir `Calibration` com `calibration_id`, `vehicle_id`, `profile_id`, `version`, `parent_version`, `fuel_model`, tabelas, estratégias, metadados e `content_hash` SHA-256 do conteúdo canónico. | Must | Duas calibrações com o mesmo conteúdo e metadados diferentes têm o mesmo `content_hash`; alterar uma célula muda o `content_hash`. |
| RF-05 | 🟡 O sistema deve criar uma nova versão imutável a cada `PUT` ou `PATCH` aceite e permitir restaurar qualquer versão anterior como nova versão (undo por versões). | Must | Após 3 PATCH e 1 PUT com `revert_to_version = 1`, a calibração tem 5 versões e o `content_hash` da versão 5 é igual ao da versão 1. |
| RF-06 | 🟡 O sistema deve calcular o combustível em modo `speed_density_ve` por `m_air = (VE/100)·(MAP·1000)·V_cyl/(R·T_charge)`, `m_fuel = m_air/(λ_alvo·AFR_st)` e `PW = m_fuel_corr/q_inj + t_dead(V_bat)`. | Must | Para VE 90 %, MAP 200 kPa, V_cyl 0,000496 m³, IAT 40 °C, λ 0,80, AFR 13,2, bico 550 cc/min, ρ 0,745 g/cc e dead time 0,9 ms, com ΔP do bico igual a 300 kPa, o pulso fica em 14,67 ms ± 0,5 %. |
| RF-07 | 🟡 O sistema deve suportar os modos de combustível `speed_density_ve`, `direct_pulse_ms` e `profile_air_model` (massa de ar fornecida pelo hook do perfil). | Must | Em `direct_pulse_ms`, o pulso é o valor da tabela `inj_base_ms` × correções + dead time; em `profile_air_model`, a massa de ar vem de `ProfileHooks.air_charge_mg()`. |
| RF-08 | 🟡 O sistema deve aplicar a tabela 3D de lambda alvo e as compensações de combustível por ECT, IAT, aceleração (enriquecimento por dTPS/dt com decaimento) e partida (pulso de cranking e enriquecimento pós-partida). | Must | Com dTPS/dt = 500 %/s, o enriquecimento segue a tabela `accel_enrich` e decai com τ = 0,2 s (63 % de queda em 0,2 s ± 1 tick); com RPM < 400 o pulso vem de `cranking_fuel`. |
| RF-09 | 🟡 O sistema deve executar a malha fechada wideband com controlador PI, trim limitado a ±25 %, anti-windup e ativação por ECT, RPM, MAP, tempo após partida e sensor válido. | Must | Com bico real 10 % menor que o configurado e malha ativa, o lambda medido converge a ±1 % do alvo em ≤ 3 s; o trim nunca excede ±25 %; com ECT < 60 °C o trim fica em 0. |
| RF-10 | 🟡 O sistema deve manter trims de longo prazo (LTFT) opcionais por célula de uma grade RPM × MAP de 8×8, limitados a ±15 %, quando `ClosedLoopConfig.ltft_enabled = true`. | Should | Com STFT estável em +8 % por 10 s numa célula, o LTFT dessa célula sobe a 0,5 %/s até absorver o desvio; com `ltft_enabled = false` o LTFT fica em 0. |
| RF-11 | 🟡 O sistema deve calcular o avanço final por cilindro como base 3D + trim do cilindro + correção IAT + correção ECT − retardo de knock do cilindro, com override de estratégia e clamp em −20 a 60 °BTDC. | Must | Base 25°, trim do cilindro 3 = −2°, IAT +0°, ECT −1°, retardo 3° ⇒ cilindro 3 recebe 19,0°; cilindros sem trim recebem 21,0° se tiverem o mesmo retardo. |
| RF-12 | 🟡 O sistema deve aplicar trims de combustível por cilindro (−25 % a +25 %) como fator multiplicativo do pulso. | Must | Trim +4 % no cilindro 2 aumenta a massa de combustível desse cilindro em 4,0 % ± 0,1 % face aos outros. |
| RF-13 | 🟡 O sistema deve executar o knock control por cilindro: retardo de `retard_step_deg` por evento acima do limiar, até `max_retard_deg`, com recuperação de `recovery_deg_per_s` após `recovery_hold_s` sem knock. | Must | Com passo 2°, máximo 8°, 5 eventos seguidos no cilindro 4, o retardo do cilindro 4 fica em 8° e os outros em 0°; 0,5 s após o último evento o retardo cai 1 °/s. |
| RF-14 | 🟡 O sistema deve executar o controle de boost com duty base 3D em malha aberta e PID em malha fechada sobre `map_kpa`, com alvo 3D limitado pelo teto por marcha. | Must | Com alvo 200 kPa e PID ativo, o MAP simulado estabiliza a ±5 kPa em ≤ 1,5 s sem overshoot > 15 kPa no cenário de referência do Apêndice B; na 2.ª marcha o alvo fica limitado ao teto `boost_target_gear` da marcha 2. |
| RF-15 | 🟡 O sistema deve cortar o boost quando `map_kpa` exceder `overboost_kpa` por ≥ `overboost_time_s`, com o modo de corte configurado e rearme com histerese. | Must | MAP 245 kPa com limite 240 kPa por 0,1 s ativa `overboost_cut` e emite evento `overboost_cut`; o corte só se desliga com MAP < 230 kPa (histerese 10 kPa). |
| RF-16 | 🟡 O sistema deve implementar o limitador de rotação com modos `fuel_cut`, `spark_cut`, `rolling_cut`, fase soft (retardo progressivo e corte parcial) e fase hard (corte total), com histerese. | Must | Com hard 7000 rpm, janela soft 200 rpm e histerese 100 rpm, a 6900 rpm o retardo extra é 50 % de `soft_retard_max_deg`; a 7000 rpm todos os cilindros são cortados; o corte libera abaixo de 6900 rpm. |
| RF-17 | 🟡 O sistema deve implementar o two-step/launch control: limite em `target_rpm`, ignição absoluta `ign_advance_deg`, lambda `lambda_target`, padrão de corte e tempo máximo ativo. | Must | Com embraiagem pressionada, TPS 100 % e alvo 4000 rpm, a rotação fica a 4000 ± 100 rpm, o avanço comandado é o valor configurado e o lambda alvo passa a 0,85; após `max_active_s` o two-step desativa e emite evento. |
| RF-18 | 🟡 O sistema deve implementar o antilag com atraso de ignição, enriquecimento, abertura de ar e limites de EGT, tempo contínuo e cooldown. | Must | Com antilag ativo, o comando `antilag_air_pct` = valor configurado; quando EGT ≥ `egt_max_c` ou o tempo contínuo ≥ `max_active_s`, o antilag desliga e só rearma após `cooldown_s`. |
| RF-19 | 🟡 O sistema deve implementar o powershift: ao detetar a troca (borda de `shift_request` ou de embraiagem com TPS ≥ `min_tps_pct`), cortar ignição ou combustível por `cut_time_ms` e retomar com rampa de avanço. | Must | Com corte de 120 ms a 1000 Hz, exatamente 120 ticks têm corte ativo; uma nova borda só é aceite após a liberação do sinal. |
| RF-20 | 🟡 O sistema deve implementar o overrun em dois modos: corte de combustível em desaceleração (DFCO) e pops & bangs (corte de injeção atrasado, janela de RPM e TPS, atraso de ignição, enriquecimento, duração e intensidade). | Must | Em pops ativo, entre a liberação do pedal e `fuel_cut_delay_s` o avanço comandado é `ign_advance_deg` e o lambda alvo é `lambda_target`; após o atraso há corte de injeção; fora da janela de RPM vale o DFCO normal. |
| RF-21 | 🟡 O sistema deve proteger turbina e catalisador no overrun: suspender o modo pops quando `egt_c` ≥ `egt_turbine_max_c` e, com `catalyst_present = true`, limitar intensidade e duração. | Must | Com EGT 960 °C e limite 950 °C, o pops desativa no mesmo tick e emite `overrun_protect`; com catalisador presente, intensidade efetiva ≤ `catalyst_max_intensity_pct` e duração ≤ `catalyst_max_duration_s`. |
| RF-22 | 🟡 O sistema deve executar o failsafe com regras de EGT, lambda pobre em carga, ECT, pressão de óleo, sobrevelocidade e falha de sensor, cada uma com limiar, tempo de confirmação, ação e liberação. | Must | Lambda medido > alvo + 0,10 com MAP ≥ 150 kPa por 0,3 s aplica `boost_cut`; EGT > limite por 0,5 s reduz o alvo de boost em 30 kPa; RPM > `overspeed_rpm` aplica `fuel_cut` no mesmo tick. |
| RF-23 | 🟡 O sistema deve arbitrar as estratégias pela ordem failsafe (1) > limitador (2) > two-step/antilag/powershift (3) > overrun (4) > normal (5), com as regras de combinação do RF-24. | Must | Com failsafe `fuel_cut` e two-step ativos no mesmo tick, `EcuStatus.arbitration_winner = "failsafe"` e o two-step fica inibido. |
| RF-24 | 🟡 O sistema deve combinar os pedidos: máscaras de corte por OU lógico, override de ignição do nível de maior prioridade (empate: o menor avanço), lambda alvo mais rico entre os pedidos de proteção, teto de boost pelo mínimo dos tetos. | Must | Os 8 casos de arbitragem do Apêndice C (C-01 a C-08) produzem os comandos esperados. |
| RF-25 | 🟡 O usuário deve poder listar, criar, ler e substituir calibrações por `GET/POST /api/v1/calibrations` e `GET/PUT /api/v1/calibrations/{calibration_id}` com controlo otimista por `base_version`. | Must | `PUT` com `base_version` desatualizada retorna 409 `CALIBRATION_VERSION_CONFLICT`; `GET ?version=2` retorna a versão 2. |
| RF-26 | 🟡 O usuário deve poder editar células e eixos de uma tabela por `PATCH /api/v1/calibrations/{calibration_id}/tables/{table_id}` com operações `set`, `add` e `scale`, até 1024 células por pedido. | Must | PATCH `add` +2,0 em 4 células cria nova versão com os 4 valores alterados e os outros iguais; 1025 células retornam 422 `PATCH_TOO_LARGE`. |
| RF-27 | 🟡 O usuário deve poder aplicar uma versão de calibração a uma sessão por `POST /api/v1/sessions/{session_id}/calibration`, de forma atómica numa fronteira de tick. | Must | Fora de puxada, a calibração inteira entra em vigor num único tick (`applied_t_sim_s` no response); nenhum tick usa mistura de duas versões. |
| RF-28 | 🟡 O sistema deve aceitar durante uma puxada só alterações em tabelas com `live_tunable = true`, sem alteração de eixos nem de estratégias. | Must | Durante puxada, aplicar versão que altera `boost_duty_base` (não live) retorna 409 `TABLE_NOT_LIVE_TUNABLE` com a lista de tabelas; alterar só células de `ve` é aceite. |
| RF-29 | 🟡 O sistema deve expor hooks de perfil (`ProfileHooks`) para validar a calibração, fornecer a massa de ar, ajustar pedidos antes da arbitragem e listar estratégias suportadas. | Must | Uma calibração `oem-stage` com `two_step` ativo retorna 422 `STRATEGY_NOT_SUPPORTED_BY_PROFILE` via hook `supported_strategies()`. |
| RF-30 | 🟡 O sistema deve publicar a cada tick um `EcuStatus` e uma lista de `EcuEvent` (limitador, failsafe, knock, overboost, duty de bico alto, limite de malha fechada) para o telemetry-datalogger. | Must | Ao bater no limitador hard, o tick contém 1 evento `limiter_hit` e o telemetry pode emitir `event.limiter` com o mesmo `t_sim_s`. |
| RF-31 | 🟡 O sistema deve emitir o comando de alvo do comando variável (admissão e escape) a partir das tabelas 3D `cam_intake_target` e `cam_exhaust_target`, quando presentes. | Could | Com a tabela presente, `ActuatorCommands.cam_intake_target_deg` iguala a interpolação da tabela; sem a tabela, o campo vale 0. ⚠️ ABERTO: modelo físico do comando variável (OQ-03). |
| RF-32 | 🟡 O sistema deve incluir `Calibration.profile_params` (dicionário de até 64 chaves com valores `float`, `bool` ou `str`) no cálculo do `content_hash`. | Must | Duas calibrações iguais exceto em `profile_params.torque_monitoring` têm `content_hash` diferentes; reordenar as chaves não altera o hash. |
| RF-33 | 🟡 O sistema deve publicar em cada `EcuStatus` os campos `load_pct` (carga relativa, %) e `torque_request_nm` (N·m no perfil `oem-stage`, nulo nos perfis standalone). | Must | Com o perfil `oem-stage` a plena carga, `torque_request_nm` iguala a interpolação da tabela `torque_request`; com `ft-pro`, `torque_request_nm` é nulo e `load_pct` está em 0–300. |

### 6.2 Fluxo Principal (Happy Path)

1. 🟡 O usuário cria uma calibração com `POST /api/v1/calibrations` (`source = "clone"` da calibração de referência do veículo e perfil).
2. 🟡 O sistema valida eixos, formatos, unidades, limites e estratégias suportadas pelo perfil, grava a versão 1 e devolve 201 com `content_hash`.
3. 🟡 O usuário edita 12 células da tabela `ignition_base` com `PATCH .../tables/ignition_base` (`base_version = 1`).
4. 🟡 O sistema grava a versão 2 e devolve a tabela atualizada e o novo `content_hash`.
5. 🟡 O usuário aplica a versão 2 à sessão com `POST /api/v1/sessions/{session_id}/calibration` fora de puxada.
6. 🟡 O sistema compila a calibração (`CompiledCalibration`), enfileira-a para o worker físico e troca a referência na fronteira do tick seguinte, devolvendo `applied_t_sim_s`.
7. 🟡 O dyno-bench inicia uma puxada; a cada tick, o worker chama `EcuRuntime.step(sensors, dt)`, que executa o pipeline do Apêndice D e devolve `ActuatorCommands`, `EcuStatus` e eventos.
8. 🟡 Resultado: a puxada reflete a versão 2, o datalog regista o `content_hash` aplicado, e o usuário compara a curva com a puxada anterior.

### 6.3 Fluxos Alternativos

**Fluxo Alternativo A — Ajuste ao vivo durante a puxada (Prof. Marcos):**
1. 🟡 O usuário altera células de `ve` (live-tunable) com PATCH e aplica a nova versão durante um `steady_state_hold`.
2. 🟡 O sistema verifica que só tabelas live-tunable mudaram e que os eixos são iguais, e troca a referência das tabelas na fronteira do tick seguinte, sem reiniciar integradores de PI/PID nem o retardo de knock.

**Fluxo Alternativo B — Undo por versões:**
1. 🟡 O usuário pede `PUT /api/v1/calibrations/{calibration_id}` com `revert_to_version = 3` e `base_version = 7`.
2. 🟡 O sistema cria a versão 8 com o conteúdo da versão 3 (`parent_version = 7`, `metadata.source = "revert"`) e preserva as versões 4 a 7.

**Fluxo Alternativo C — Proteção em puxada (Lucas):**
1. 🟡 Durante a puxada, o lambda medido fica > alvo + 0,10 com MAP ≥ 150 kPa por 0,3 s.
2. 🟡 O sistema aplica `boost_cut` (duty da wastegate 0 %), emite `failsafe_trip` e mantém o corte até a condição ficar falsa por `release_s`.

**Fluxo Alternativo D — Aplicação recusada durante puxada:**
1. 🟡 O usuário aplica uma versão que altera a estratégia `rev_limiter` durante a puxada.
2. 🟡 O sistema devolve 409 `TABLE_NOT_LIVE_TUNABLE` com `detail` listando `strategies.rev_limiter`, sem alterar a calibração ativa.

---

## 7. Requisitos Não-Funcionais

| ID | Requisito | Valor alvo | Observação |
|----|-----------|-----------|------------|
| 🟡 RNF-01 | Performance do tick | p99 ≤ 0,1 ms e máximo ≤ 0,5 ms por `step()` a 1000 Hz, 8 cilindros, todas as estratégias ativas | 🟡 Medido com `pytest-benchmark` em 100 000 ticks no hardware de referência. O hot path usa `CompiledCalibration` com listas Python de floats e `bisect`, sem objetos Pydantic nem alocação por tick. |
| 🟡 RNF-02 | Determinismo | 100 % de igualdade do SHA-256 do log em 10 execuções repetidas | 🟡 Sem `time.time()`, sem `random`; o padrão de rolling cut usa contador de ciclo. Todas as constantes de tempo usam `t_sim_s` e `dt`. |
| 🟡 RNF-03 | Latência da API | p95 < 50 ms em `GET` de calibração; p95 < 100 ms em `PATCH` de 256 células; p95 < 150 ms em `POST/PUT` de calibração com 64 tabelas 32×32 | 🟡 SQLite local; payload máximo 2 MB por calibração. |
| 🟡 RNF-04 | Qualidade | Cobertura ≥ 85 % em `simremap.ecu`; `mypy --strict` e `ruff` sem erros; `bandit` sem achados médios ou altos | 🟡 Testes de propriedade (hypothesis) para interpolação e arbitragem. |
| 🟡 RNF-05 | Capacidade | Até 128 tabelas por calibração, 1000 versões por calibração, 500 calibrações por instalação | 🟡 Acima de 1000 versões, o sistema devolve 409 `CALIBRATION_VERSION_LIMIT` e pede clonagem. |
| 🟡 RNF-06 | Memória | ≤ 20 MB por `EcuRuntime` ativo incluindo `CompiledCalibration` e estado | 🟡 Garante folga no container com 8 GB e 1 sessão por estação. |

---

## 8. Design e Interface

**Componentes afetados:**
- 🟡 `backend/src/simremap/ecu/` — `tables.py` (Axis, Table2D, Table3D, interpolação), `calibration.py` (Calibration, hash canónico, versões), `strategies/` (um módulo por estratégia), `arbitration.py`, `runtime.py` (`EcuRuntime`, `CompiledCalibration`, `ProfileHooks`), `limits.py` (Apêndice A).
- 🟡 `backend/src/simremap/api/routers/calibrations.py` e `api/routers/session_calibration.py`.
- 🟡 `backend/src/simremap/db/models/calibration.py` e migração Alembic.
- 🟡 Consumidores: dyno-bench (laço), ecu-profiles (hooks), telemetry-datalogger (`EcuStatus`, `EcuEvent`), ecu-tuning-ui (API REST), training-scenarios (`content_hash`).

**Comportamento esperado (API REST):**

| Método e caminho | Request | Response | Erros (`code`) |
|---|---|---|---|
| 🟡 `GET /api/v1/calibrations?vehicle_id=&profile_id=&limit=50&offset=0` | query opcional; `limit` 1–200 | 200 `CalibrationPage` (`items`: lista de `CalibrationSummary`, `total`) | 422 `VALIDATION_ERROR` |
| 🟡 `POST /api/v1/calibrations` | `CalibrationCreate` | 201 `Calibration` + header `Location` | 404 `VEHICLE_NOT_FOUND`, 404 `ECU_PROFILE_NOT_FOUND`, 404 `CALIBRATION_NOT_FOUND` (clone), 422 `TABLE_*`, 422 `STRATEGY_NOT_SUPPORTED_BY_PROFILE`, 503 `STORAGE_UNAVAILABLE` |
| 🟡 `GET /api/v1/calibrations/{calibration_id}?version=` | `version` opcional (padrão: última); `include=versions` lista o histórico | 200 `Calibration` (+ `versions`: lista de `CalibrationVersionInfo`, se pedido) | 404 `CALIBRATION_NOT_FOUND`, 404 `CALIBRATION_VERSION_NOT_FOUND` |
| 🟡 `PUT /api/v1/calibrations/{calibration_id}` | `CalibrationReplace` (conteúdo completo + `base_version`) ou `{ "base_version": n, "revert_to_version": m }` | 200 `Calibration` (nova versão) | 409 `CALIBRATION_VERSION_CONFLICT`, 409 `CALIBRATION_VERSION_LIMIT`, 422 `TABLE_*`, 422 `CALIBRATION_PROFILE_IMMUTABLE` |
| 🟡 `PATCH /api/v1/calibrations/{calibration_id}/tables/{table_id}` | `TablePatch` | 200 `TablePatchResult` (`version`, `content_hash`, `table`) | 404 `TABLE_NOT_FOUND`, 409 `CALIBRATION_VERSION_CONFLICT`, 422 `TABLE_VALUE_OUT_OF_RANGE`, 422 `TABLE_AXIS_NOT_MONOTONIC`, 422 `PATCH_TOO_LARGE`, 422 `PATCH_CELL_OUT_OF_BOUNDS` |
| 🟡 `POST /api/v1/sessions/{session_id}/calibration` | `ApplyCalibrationRequest` | 200 `ApplyCalibrationResult` | 404 `SESSION_NOT_FOUND`, 404 `CALIBRATION_NOT_FOUND`, 409 `TABLE_NOT_LIVE_TUNABLE`, 422 `CALIBRATION_PROFILE_MISMATCH`, 422 `CALIBRATION_VEHICLE_MISMATCH`, 422 (códigos do hook do perfil, ex.: `OEM_CHECKSUM_INVALID`), 504 `CALIBRATION_APPLY_TIMEOUT` |

🟡 Todos os erros usam `application/problem+json` (`ProblemDetail`) com `code` estável; erros de célula incluem `detail` com `table_id`, `row`, `col`, `value`, `min`, `max`.

**Estados da UI (contrato para a ecu-tuning-ui):**
- 🟡 Estado vazio: `GET /api/v1/calibrations` com `total = 0` indica que o usuário deve clonar a calibração de referência.
- 🟡 Estado de carregamento: entre o `POST .../calibration` e o response, a calibração ativa continua a anterior (sem estado intermediário).
- 🟡 Estado de erro: o `ProblemDetail` com `row`/`col` permite destacar a célula inválida.
- 🟡 Estado de sucesso: o response traz `version`, `content_hash` e `applied_t_sim_s`.

---

## 9. Modelo de Dados

**Contratos Pydantic v2 (pacote `simremap.ecu`):**

```python
# Nota: os genéricos levam um espaço após o colchete por convenção de lint das specs; o código real segue o ruff format.
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from simremap.core.contracts import EntityId
from simremap.profiles.contracts import EcuProfileId


class EcuValidationError(ValueError):
    """Erro de domínio com code estável; o router converte em ProblemDetail 422."""

    def __init__(self, code: str, detail: dict[ str, object]) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


class AxisQuantity(StrEnum):
    RPM = "rpm"                      # rev/min
    MAP_KPA = "map_kpa"              # kPa absoluto
    TPS_PCT = "tps_pct"              # %
    PEDAL_PCT = "pedal_pct"          # %
    LOAD_PCT = "load_pct"            # % de enchimento relativo (perfil OEM)
    ECT_C = "ect_c"                  # °C
    IAT_C = "iat_c"                  # °C
    BATTERY_V = "battery_v"          # V
    GEAR = "gear"                    # 0 = neutro, 1..8
    EGT_C = "egt_c"                  # °C
    TPS_RATE_PCT_S = "tps_rate_pct_s"  # %/s
    IGN_DELTA_DEG = "ign_delta_deg"  # graus de atraso face ao ótimo
    BOOST_TARGET_KPA = "boost_target_kpa"  # kPa absoluto
    TORQUE_NM = "torque_nm"          # N·m


AXIS_UNITS: dict[ str, str] = {
    "rpm": "rev/min", "map_kpa": "kPa", "tps_pct": "%", "pedal_pct": "%",
    "load_pct": "%", "ect_c": "°C", "iat_c": "°C", "battery_v": "V", "gear": "-",
    "egt_c": "°C", "tps_rate_pct_s": "%/s", "ign_delta_deg": "°",
    "boost_target_kpa": "kPa", "torque_nm": "N·m",
}


class Axis(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    quantity: AxisQuantity
    values: list[ float] = Field(min_length=2)  # máximo 32, validado abaixo

    @model_validator(mode="after")
    def _check(self) -> "Axis":
        if len(self.values) > 32:
            raise EcuValidationError("TABLE_SIZE_EXCEEDED", {"points": len(self.values)})
        if any(v != v or v in (float("inf"), float("-inf")) for v in self.values):
            raise EcuValidationError("TABLE_VALUE_NOT_FINITE", {})
        if any(b <= a for a, b in zip(self.values, self.values[1:])):
            raise EcuValidationError("TABLE_AXIS_NOT_MONOTONIC", {"quantity": self.quantity})
        return self


class TableKind(StrEnum):
    # Standalone e comuns
    VE = "ve"
    INJ_BASE_MS = "inj_base_ms"
    LAMBDA_TARGET = "lambda_target"
    IGNITION_BASE = "ignition_base"
    IGNITION_TRIM_CYL = "ignition_trim_cyl"
    FUEL_TRIM_CYL = "fuel_trim_cyl"
    IGN_CORR_IAT = "ign_corr_iat"
    IGN_CORR_ECT = "ign_corr_ect"
    FUEL_CORR_ECT = "fuel_corr_ect"
    FUEL_CORR_IAT = "fuel_corr_iat"
    ACCEL_ENRICH = "accel_enrich"
    CRANKING_FUEL = "cranking_fuel"
    AFTERSTART_ENRICH = "afterstart_enrich"
    INJ_DEAD_TIME = "inj_dead_time"
    BOOST_TARGET = "boost_target"
    BOOST_TARGET_GEAR = "boost_target_gear"
    BOOST_DUTY_BASE = "boost_duty_base"
    KNOCK_THRESHOLD = "knock_threshold"
    OIL_PRESSURE_MIN = "oil_pressure_min"
    CAM_INTAKE_TARGET = "cam_intake_target"
    CAM_EXHAUST_TARGET = "cam_exhaust_target"
    # Perfil OEM (semântica definida na spec ecu-profiles)
    TORQUE_REQUEST = "torque_request"
    TORQUE_LIMIT = "torque_limit"
    TORQUE_LIMIT_GEAR = "torque_limit_gear"
    TORQUE_OPTIMAL = "torque_optimal"
    IGNITION_OPTIMAL = "ignition_optimal"
    IGNITION_EFFICIENCY = "ignition_efficiency"
    OEM_PRESSURE_TARGET = "oem_pressure_target"
    FRICTION_TORQUE = "friction_torque"
    LAMBDA_COMPONENT_PROTECTION = "lambda_component_protection"


class TableBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    table_id: str = Field(pattern=r"^[a-z][_0-9a-z]{1,47}$")
    kind: TableKind
    unit: str                      # deve igualar a unidade do kind no Apêndice A
    live_tunable: bool = False     # padrão por tipo no Apêndice A
    cylinder: int | None = Field(default=None, ge=1, le=12)  # só para *_trim_cyl
    description: str = Field(default="", max_length=200)
    decimals: int = Field(default=1, ge=0, le=4)  # casas decimais de exibição na ecu-tuning-ui


class Table2D(TableBase):
    dims: Literal[2] = 2
    x: Axis
    values: list[ float]            # len == len(x.values)


class Table3D(TableBase):
    dims: Literal[3] = 3
    x: Axis                        # colunas (normalmente rpm)
    y: Axis                        # linhas (normalmente map_kpa, tps_pct ou load_pct)
    values: list[ list[ float]]      # len == len(y.values); cada linha len == len(x.values)


AnyTable = Annotated[ Table2D | Table3D, Field(discriminator="dims")]


class StrategyKind(StrEnum):
    CLOSED_LOOP = "closed_loop"
    KNOCK_CONTROL = "knock_control"
    BOOST_CONTROL = "boost_control"
    REV_LIMITER = "rev_limiter"
    TWO_STEP = "two_step"
    ANTILAG = "antilag"
    POWERSHIFT = "powershift"
    OVERRUN = "overrun"
    FAILSAFE = "failsafe"


CutMode = Literal["fuel_cut", "spark_cut", "rolling_cut"]


class StrategyBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    enabled: bool = True


class ClosedLoopConfig(StrategyBase):
    kind: Literal["closed_loop"] = "closed_loop"
    kp: float = Field(default=0.5, ge=0.0, le=5.0)        # fração de trim por fração de erro
    ki_per_s: float = Field(default=2.0, ge=0.0, le=20.0)
    trim_limit_pct: float = Field(default=25.0, ge=0.0, le=25.0)
    min_ect_c: float = Field(default=60.0, ge=-40.0, le=120.0)
    rpm_min: float = Field(default=800.0, ge=0.0)
    rpm_max: float = Field(default=7500.0, le=12000.0)
    map_max_kpa: float = Field(default=400.0, le=500.0)
    delay_after_start_s: float = Field(default=10.0, ge=0.0, le=120.0)
    ltft_enabled: bool = False
    ltft_rate_pct_s: float = Field(default=0.5, ge=0.0, le=5.0)
    ltft_limit_pct: float = Field(default=15.0, ge=0.0, le=25.0)


class KnockControlConfig(StrategyBase):
    kind: Literal["knock_control"] = "knock_control"
    retard_step_deg: float = Field(default=2.0, gt=0.0, le=5.0)
    max_retard_deg: float = Field(default=8.0, gt=0.0, le=15.0)
    recovery_hold_s: float = Field(default=0.5, ge=0.0, le=10.0)
    recovery_deg_per_s: float = Field(default=1.0, gt=0.0, le=10.0)
    rpm_min: float = Field(default=1500.0, ge=0.0)
    map_min_kpa: float = Field(default=80.0, ge=0.0)
    boost_reduction_kpa_at_max: float = Field(default=20.0, ge=0.0, le=100.0)
    max_retard_hold_s: float = Field(default=2.0, ge=0.1, le=10.0)


class BoostControlConfig(StrategyBase):
    kind: Literal["boost_control"] = "boost_control"
    mode: Literal["open_loop", "closed_loop"] = "closed_loop"
    kp_pct_per_kpa: float = Field(default=0.4, ge=0.0, le=10.0)
    ki_pct_per_kpa_s: float = Field(default=0.8, ge=0.0, le=20.0)
    kd_pct_s_per_kpa: float = Field(default=0.02, ge=0.0, le=2.0)
    d_filter_tau_s: float = Field(default=0.05, gt=0.0, le=1.0)
    pid_activation_window_kpa: float = Field(default=20.0, ge=0.0, le=200.0)
    integrator_limit_pct: float = Field(default=30.0, ge=0.0, le=100.0)
    by_gear_enabled: bool = False
    overboost_kpa: float = Field(default=260.0, ge=100.0, le=500.0)
    overboost_time_s: float = Field(default=0.1, ge=0.0, le=2.0)
    overboost_hysteresis_kpa: float = Field(default=10.0, ge=0.0, le=50.0)
    overboost_cut_mode: Literal["wastegate_open", "fuel_cut", "spark_cut"] = "wastegate_open"


class RevLimiterConfig(StrategyBase):
    kind: Literal["rev_limiter"] = "rev_limiter"
    hard_rpm: float = Field(default=7000.0, ge=1000.0, le=12000.0)
    cut_mode: CutMode = "fuel_cut"
    soft_enabled: bool = True
    soft_window_rpm: float = Field(default=200.0, ge=0.0, le=1000.0)
    soft_retard_max_deg: float = Field(default=10.0, ge=0.0, le=30.0)
    hysteresis_rpm: float = Field(default=100.0, ge=10.0, le=500.0)


class TwoStepConfig(StrategyBase):
    kind: Literal["two_step"] = "two_step"
    target_rpm: float = Field(default=4000.0, ge=1500.0, le=9000.0)
    cut_mode: CutMode = "spark_cut"
    ign_advance_deg: float = Field(default=-5.0, ge=-20.0, le=30.0)   # absoluto, °BTDC
    lambda_target: float = Field(default=0.85, ge=0.65, le=1.0)
    activation: Literal["clutch", "launch_switch"] = "clutch"
    max_speed_kmh: float = Field(default=5.0, ge=0.0, le=50.0)
    min_tps_pct: float = Field(default=80.0, ge=0.0, le=100.0)
    max_active_s: float = Field(default=10.0, gt=0.0, le=60.0)
    release_ramp_s: float = Field(default=0.2, ge=0.0, le=2.0)


class AntilagConfig(StrategyBase):
    kind: Literal["antilag"] = "antilag"
    activation: Literal["switch", "rolling"] = "switch"   # rolling: ativo entre rpm_min e rpm_max com TPS baixo
    rpm_min: float = Field(default=3000.0, ge=1000.0)
    rpm_max: float = Field(default=7000.0, le=12000.0)
    max_tps_pct: float = Field(default=20.0, ge=0.0, le=100.0)
    ign_advance_deg: float = Field(default=-15.0, ge=-20.0, le=10.0)  # absoluto
    lambda_target: float = Field(default=0.80, ge=0.65, le=1.0)
    air_valve_pct: float = Field(default=15.0, ge=0.0, le=100.0)
    cut_mode: CutMode = "rolling_cut"
    cut_fraction: float = Field(default=0.25, ge=0.0, le=0.75)
    egt_max_c: float = Field(default=1000.0, ge=600.0, le=1150.0)
    max_active_s: float = Field(default=3.0, gt=0.0, le=30.0)
    cooldown_s: float = Field(default=5.0, ge=0.0, le=120.0)


class PowershiftConfig(StrategyBase):
    kind: Literal["powershift"] = "powershift"
    trigger: Literal["shift_request", "clutch"] = "shift_request"
    min_tps_pct: float = Field(default=80.0, ge=0.0, le=100.0)
    min_rpm: float = Field(default=3000.0, ge=0.0)
    cut_mode: Literal["fuel_cut", "spark_cut"] = "spark_cut"
    cut_time_ms: float = Field(default=120.0, ge=20.0, le=500.0)
    resume_retard_deg: float = Field(default=5.0, ge=0.0, le=20.0)
    resume_ramp_s: float = Field(default=0.15, ge=0.0, le=2.0)


class OverrunConfig(StrategyBase):
    kind: Literal["overrun"] = "overrun"
    dfco_enabled: bool = True
    dfco_tps_max_pct: float = Field(default=2.0, ge=0.0, le=10.0)
    dfco_rpm_min: float = Field(default=1500.0, ge=500.0)
    dfco_resume_rpm: float = Field(default=1200.0, ge=500.0)
    dfco_delay_s: float = Field(default=0.5, ge=0.0, le=5.0)
    pops_enabled: bool = False
    pops_rpm_min: float = Field(default=2500.0, ge=1000.0)
    pops_rpm_max: float = Field(default=6500.0, le=12000.0)
    pops_tps_max_pct: float = Field(default=5.0, ge=0.0, le=20.0)
    fuel_cut_delay_s: float = Field(default=1.5, ge=0.0, le=5.0)
    ign_advance_deg: float = Field(default=-15.0, ge=-20.0, le=10.0)  # absoluto
    lambda_target: float = Field(default=0.90, ge=0.70, le=1.10)
    intensity_pct: float = Field(default=60.0, ge=0.0, le=100.0)
    max_duration_s: float = Field(default=2.0, gt=0.0, le=5.0)
    egt_turbine_max_c: float = Field(default=950.0, ge=600.0, le=1100.0)
    catalyst_present: bool = True
    catalyst_max_intensity_pct: float = Field(default=30.0, ge=0.0, le=100.0)
    catalyst_max_duration_s: float = Field(default=0.5, ge=0.0, le=5.0)


FailsafeAction = Literal[
    "boost_reduce", "boost_cut", "rev_limit_reduce", "enrich", "ignition_retard", "fuel_cut"
]


class FailsafeRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    rule_id: Literal["egt_high", "egt_critical", "lean_under_load", "ect_high",
                     "oil_pressure_low", "overspeed", "sensor_fault"]
    enabled: bool = True
    threshold: float               # unidade por regra (Apêndice E)
    confirm_s: float = Field(ge=0.0, le=5.0)
    actions: list[ FailsafeAction] = Field(min_length=1)
    action_value: float = 0.0      # kPa para boost_reduce, rpm para rev_limit_reduce,
                                   # Δλ para enrich, graus para ignition_retard
    release_s: float = Field(default=2.0, ge=0.0, le=60.0)
    latch_until_stop: bool = False # true: só libera quando a RPM cai abaixo de 500


class FailsafeConfig(StrategyBase):
    kind: Literal["failsafe"] = "failsafe"
    rules: list[ FailsafeRule]      # padrões no Apêndice E
    overspeed_rpm: float = Field(default=7500.0, ge=1000.0, le=13000.0)


StrategyConfig = Annotated[
    ClosedLoopConfig | KnockControlConfig | BoostControlConfig | RevLimiterConfig
    | TwoStepConfig | AntilagConfig | PowershiftConfig | OverrunConfig | FailsafeConfig,
    Field(discriminator="kind"),
]


class FuelModelConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    mode: Literal["speed_density_ve", "direct_pulse_ms", "profile_air_model"] = "speed_density_ve"
    charge_temp_blend: float = Field(default=0.0, ge=0.0, le=1.0)  # T = IAT + k·(ECT − IAT)
    accel_enrich_tau_s: float = Field(default=0.2, gt=0.0, le=2.0)
    afterstart_decay_s: float = Field(default=15.0, gt=0.0, le=120.0)
    cranking_rpm: float = Field(default=400.0, ge=100.0, le=800.0)
    cranking_ign_deg: float = Field(default=10.0, ge=-5.0, le=20.0)
    inj_duty_warn_pct: float = Field(default=85.0, ge=50.0, le=100.0)


class CalibrationMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    author_nickname: str | None = Field(default=None, pattern=r"^[-_0-9A-Za-z]{3,24}$")
    notes: str = Field(default="", max_length=2000)
    source: Literal["user", "wizard", "oem_stock", "import", "clone", "revert", "reference"] = "user"
    change_summary: str = Field(default="", max_length=200)  # ex.: "ignition_base: 12 células"
    extra: dict[ str, str] = Field(default_factory=dict)       # chaves de perfil, ex.: "oem_checksum"


class Calibration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    calibration_id: EntityId
    vehicle_id: EntityId
    profile_id: EcuProfileId
    version: int = Field(ge=1)
    parent_version: int | None = Field(default=None, ge=1)
    fuel_model: FuelModelConfig
    tables: dict[ str, AnyTable] = Field(max_length=128)        # chave == table_id
    strategies: dict[ str, StrategyConfig]                      # chave == kind
    profile_params: dict[ str, float | bool | str] = Field(default_factory=dict, max_length=64)  # flags do perfil (ex.: proteções OEM, fuel_model_mode); entra no content_hash
    metadata: CalibrationMetadata
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime                                       # relógio de parede, fora do laço

    @model_validator(mode="after")
    def _keys(self) -> "Calibration":
        for key, table in self.tables.items():
            if key != table.table_id:
                raise EcuValidationError("TABLE_ID_MISMATCH", {"key": key})
        for key, strat in self.strategies.items():
            if key != strat.kind:
                raise EcuValidationError("STRATEGY_KIND_MISMATCH", {"key": key})
        return self


class CellEdit(BaseModel):
    row: int = Field(ge=0, le=31)   # 0 para Table2D
    col: int = Field(ge=0, le=31)
    value: float


class TablePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_version: int = Field(ge=1)
    op: Literal["set", "add", "scale"] = "set"   # add soma value; scale multiplica por value
    cells: list[ CellEdit] = Field(default_factory=list)  # máximo 1024, validado no router
    x_values: list[ float] | None = None          # substitui eixo x (mesmo número de pontos)
    y_values: list[ float] | None = None
    change_summary: str = Field(default="", max_length=200)


class CalibrationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vehicle_id: EntityId
    profile_id: EcuProfileId
    metadata: CalibrationMetadata
    source: Literal["clone", "payload", "reference"]
    clone_from_id: EntityId | None = None
    clone_from_version: int | None = None
    fuel_model: FuelModelConfig | None = None
    tables: dict[ str, AnyTable] | None = None
    strategies: dict[ str, StrategyConfig] | None = None


class ApplyCalibrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    calibration_id: EntityId
    version: int | None = None                  # padrão: última
    profile_options: dict[ str, bool] = Field(default_factory=dict)  # repassado ao hook do perfil


class ApplyCalibrationResult(BaseModel):
    session_id: EntityId
    calibration_id: EntityId
    version: int
    content_hash: str
    mode: Literal["full", "live_tables"]
    changed_tables: list[ str]
    applied_t_sim_s: float


class EcuEvent(BaseModel):
    t_sim_s: float
    kind: Literal["limiter_hit", "failsafe_trip", "failsafe_release", "knock_retard",
                  "overboost_cut", "inj_duty_high", "closed_loop_limit", "two_step_timeout",
                  "antilag_protect", "overrun_protect", "sensor_fault", "budget_overrun"]
    cylinder: int | None = None
    value: float | None = None
    detail: str = ""


class EcuStatus(BaseModel):  # snapshot decimado para telemetria; no laço usa-se dataclass com slots
    t_sim_s: float
    lambda_target: float
    stft_pct: float
    ltft_pct: float
    closed_loop_active: bool
    fuel_mass_mg: list[ float]          # por cilindro
    injector_pw_ms: list[ float]
    inj_duty_pct: float
    ign_advance_deg: list[ float]
    knock_retard_deg: list[ float]
    boost_target_kpa: float
    wastegate_duty_pct: float
    limiter_state: Literal["off", "soft", "hard"]
    active_strategies: list[ str]
    arbitration_winner: str            # "failsafe" | "rev_limiter" | "two_step" | ... | "normal"
    failsafe_actions: list[ str]
    load_pct: float                    # carga relativa calculada no tick (eixo do perfil OEM e canal do cursor da UI)
    torque_request_nm: float | None    # pedido de torque do pedal; None nos perfis standalone
    calibration_hash: str
```

🟡 **Campos calculados para a UI:** os responses de `GET` expõem, via `computed_field`, `min` e `max` de cada tabela (Apêndice A), e `unit` e `source_channel` de cada eixo (`AXIS_UNITS` e `quantity`, que é também o nome do canal de telemetria do cursor). Estes campos são só de leitura e ficam fora do hash.

🟡 **Hash canónico:** `content_hash = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False))`, onde `payload = {vehicle_id, profile_id, fuel_model, tables, strategies, profile_params}` com todos os floats arredondados a 6 casas decimais antes da serialização. Metadados, `version` e `created_at` ficam fora do hash.

🟡 **Contratos consumidos (donos em outras specs):** `SensorReadings` e `ActuatorCommands` (engine-physics-core), `VehicleSpec`/`EngineSpec`/`FuelSpec`/`MechanicalLimits` (vehicle-catalog), `BaseSetup`/`EcuProfileId` (ecu-profiles), `SimulationSession` (dyno-bench). Campos usados: ver Apêndice F. ⚠️ ABERTO: confirmar os nomes de campo do Apêndice F com engine-physics-core (OQ-01).

**Entidades persistidas (SQLModel):**

```
calibration {
  calibration_id: str (PK, UUID)
  vehicle_id: str (índice)
  profile_id: str (índice)
  name: str
  latest_version: int
  created_at: datetime
  updated_at: datetime
}
calibration_version {
  calibration_id: str (FK, PK composta)
  version: int (PK composta)
  parent_version: int | null
  content_hash: str (índice)
  payload_json: text        // Calibration completa sem calibration_id/version
  author_nickname: str | null
  source: str
  change_summary: str
  created_at: datetime
}
session_calibration {
  session_id: str (PK, FK lógica para SimulationSession)
  calibration_id: str
  version: int
  content_hash: str
  applied_t_sim_s: float
}
```

**Migrações necessárias:** 🟡 Sim. Uma migração Alembic cria as 3 tabelas com índices em `(vehicle_id, profile_id)` e `content_hash`. Sem impacto em dados existentes (componente novo).

---

## 10. Integrações e Dependências

| Dependência | Tipo | Impacto se indisponível |
|-------------|------|------------------------|
| 🟡 engine-physics-core (`SensorReadings`, `ActuatorCommands`, ordem do laço) | Obrigatória | Sem os contratos, o `step()` não compila; os testes do ecu-core usam um gerador de sensores sintético do próprio pacote. |
| 🟡 vehicle-catalog (`VehicleSpec`, `EngineSpec.displacement_cc`, `n_cyl`, `FuelSpec.afr_stoich`, `density_g_cc`, `MechanicalLimits`) | Obrigatória | Sem veículo, `POST /api/v1/calibrations` devolve 404 `VEHICLE_NOT_FOUND`. |
| 🟡 ecu-profiles (`ProfileHooks`, `BaseSetup`, calibração de referência) | Obrigatória | No Sprint 2 o core usa um hook nulo (`NullProfileHooks`) com todas as estratégias suportadas e modo `speed_density_ve`. |
| 🟡 dyno-bench (`SimulationSession`, estado de puxada, worker do laço) | Obrigatória | Sem sessão, `POST .../calibration` devolve 404 `SESSION_NOT_FOUND`. O estado "em puxada" decide o modo `live_tables`. |
| 🟡 telemetry-datalogger (consumo de `EcuStatus`/`EcuEvent`) | Opcional | Sem consumidor, o runtime descarta os snapshots sem bloquear o laço (fila limitada a 256 itens, descarte do mais antigo). |
| 🟡 platform-foundation (`ProblemDetail`, config, sessão de BD) | Obrigatória | Sem BD, a API devolve 503 `STORAGE_UNAVAILABLE`; o laço continua com a calibração já compilada. |
| 🟡 Biblioteca padrão (`bisect`, `hashlib`, `json`) e NumPy (só na compilação) | Obrigatória | NumPy indisponível impede o build da imagem; o hot path não depende de NumPy. |

---

## 11. Edge Cases e Tratamento de Erros

| Cenário | Trigger | Comportamento esperado |
|---------|---------|----------------------|
| 🟡 EC-01: Eixo não monotónico | PATCH com `x_values` `(1000, 900, ...)` | 422 `TABLE_AXIS_NOT_MONOTONIC`; nenhuma versão é criada; a versão anterior continua a última. |
| 🟡 EC-02: Valor não finito ou fora do limite | Célula `NaN`, `inf` ou `ve = 200` | 422 `TABLE_VALUE_NOT_FINITE` ou `TABLE_VALUE_OUT_OF_RANGE` com `row`, `col`, `min`, `max`; nada é gravado. |
| 🟡 EC-03: Conflito de versão | Dois clientes fazem PATCH com o mesmo `base_version` | O primeiro cria a versão n+1; o segundo recebe 409 `CALIBRATION_VERSION_CONFLICT` com `latest_version`; o cliente deve reler e repetir (retry manual). |
| 🟡 EC-04: Sensor em falha | `SensorReadings.map_kpa` `NaN` ou fora de 5–600 kPa | O runtime usa o último valor válido por até 50 ms; depois usa 100 kPa, ativa a regra `sensor_fault` (`boost_cut` + limite de 3000 rpm) e emite `sensor_fault`. |
| 🟡 EC-05: Wideband indisponível | `lambda_measured` `None` ou sensor não aquecido | A malha fechada congela o trim em 0 % (fallback para malha aberta) e marca `closed_loop_active = false`; o LTFT não aprende. |
| 🟡 EC-06: Duty de bico > 100 % | Pulso exigido maior que o período do ciclo `120000/rpm` ms | O pulso é limitado a 100 % do período; o runtime emite `inj_duty_high` e o motor fica pobre (consequência física real). Acima de `inj_duty_warn_pct` emite aviso sem limitar. |
| 🟡 EC-07: Aplicação durante puxada com tabela não live | `POST .../calibration` que muda eixos, estratégias ou tabela `live_tunable = false` | 409 `TABLE_NOT_LIVE_TUNABLE` com lista de itens; a calibração ativa não muda. |
| 🟡 EC-08: Timeout do worker | O worker físico não confirma a troca em 100 ms (laço bloqueado ou parado) | 504 `CALIBRATION_APPLY_TIMEOUT`; o pedido pendente é cancelado para evitar aplicação tardia; nenhum tick usa a nova versão. |
| 🟡 EC-09: Banco de dados indisponível | Falha de I/O do SQLite/PostgreSQL | 503 `STORAGE_UNAVAILABLE` com header `Retry-After: 2`; o laço continua com a calibração em memória; nenhum dado parcial é gravado (transação única). |
| 🟡 EC-10: Estratégia não suportada pelo perfil | Calibração `oem-stage` com `antilag` | 422 `STRATEGY_NOT_SUPPORTED_BY_PROFILE` com `strategy` no `detail`. |
| 🟡 EC-11: Perfil ou veículo diferente da sessão | Aplicar calibração `ft-pro` numa sessão com perfil `oem-stage` | 422 `CALIBRATION_PROFILE_MISMATCH` (ou `CALIBRATION_VEHICLE_MISMATCH`). |
| 🟡 EC-12: Estouro de orçamento de CPU | `step()` > 0,5 ms | O tempo de simulação não depende do relógio e por isso o determinismo é mantido; o runtime conta o estouro e emite `budget_overrun` a cada 1000 estouros para o diagnóstico. |
| 🟡 EC-13: Configuração incoerente de estratégia | `two_step.target_rpm ≥ rev_limiter.hard_rpm` ou `overrun.pops_rpm_min ≥ pops_rpm_max` | 422 `STRATEGY_CONFIG_INVALID` com os campos em conflito. |
| 🟡 EC-14: Limite de versões | 1001.ª versão | 409 `CALIBRATION_VERSION_LIMIT`; o usuário deve clonar a calibração. |
| 🟡 EC-15: Divisão por temperatura inválida | IAT < −40 °C ou > 150 °C | A temperatura é limitada a −40..150 °C antes da equação; `sensor_fault` é emitido se a leitura persistir por 50 ms. |

---

## 12. Segurança e Privacidade

- 🟡 **Autenticação:** nenhuma no MVP (local-first, um container por estação). A API escuta só na interface configurada pela platform-foundation.
- 🟡 **Autorização:** sem papéis no ecu-core; o `author_nickname` é informativo. A edição de cenários de instrutor é controlada pela training-scenarios.
- 🟡 **Dados sensíveis:** nenhuma PII; só `author_nickname` opcional (3–24 caracteres alfanuméricos). As calibrações são dados técnicos.
- 🟡 **Entrada não confiável:** todo o payload passa por Pydantic com `extra="forbid"`, limites numéricos e tamanho máximo de 2 MB; JSON é desserializado sem `eval`; nenhum código de calibração é executado.
- 🟡 **Auditoria:** cada versão grava `author_nickname`, `source`, `change_summary`, `content_hash` e `created_at`; o histórico é imutável.

---

## 13. Plano de Rollout

- 🟡 **Estratégia:** entrega incremental por feature flag de configuração `ECU_STRATEGIES_ENABLED` (lista). Ordem no Sprint 2: tabelas e interpolação → combustível e ignição → malha fechada e knock → boost e limitador → overrun e failsafe → two-step, antilag e powershift → arbitragem completa.
- 🟡 **Como reverter (rollback):** remover a estratégia da flag desativa-a no runtime (pedido nulo na arbitragem); a migração Alembic tem `downgrade` que apaga as 3 tabelas; calibrações podem ser exportadas antes por `GET`.
- 🟡 **Monitoramento pós-deploy:** benchmark p99 do `step()` no CI a cada commit (falha se > 0,1 ms), contagem de `budget_overrun` por sessão, taxa de 409/422 por código nos logs estruturados.

---

## 14. Open Questions

| # | Pergunta | Impacto | Dono | Prazo |
|---|---------|---------|------|-------|
| 🟡 OQ-01 | Parcialmente resolvida na revisão R1 (2026-10-18): `knock_intensity` (0,0–1,0), `lambda_measured` e `injector_pw_ms` ficam padronizados em todas as specs. ⚠️ ABERTO: confirmar com a engine-physics-core os restantes nomes do Apêndice F (ex.: `ign_advance_deg` vs. `ignition_advance_deg`, `throttle_target_pct` vs. `throttle_pct`). | Alto | George | 2026-10-24 |
| 🟡 OQ-02 | Quem é dono da calibração de referência por veículo e perfil (`source = "reference"`): vehicle-catalog ou ecu-profiles? | Médio | George | 2026-10-24 |
| 🟡 OQ-03 | O engine-physics-core modela o efeito do comando variável sobre o VE real? Sem isso, o RF-31 só emite o comando sem efeito. | Médio | George | 2026-10-31 |
| 🟡 OQ-04 | A convenção do duty da wastegate (0 % = pressão de mola, 100 % = wastegate fechada) está alinhada com o modelo de atuador da física? | Alto | George | 2026-10-24 |
| 🟡 OQ-05 | O LTFT deve ser persistido entre sessões ou reiniciado a cada `POST /api/v1/sessions`? A proposta é reiniciar. | Baixo | George | 2026-11-07 |

---

## 15. Decisões Tomadas (Decision Log)

| Decisão | Alternativas consideradas | Racional |
|---------|--------------------------|---------|
| 🟡 Compilar `Calibration` em `CompiledCalibration` (listas Python, `bisect`, dataclasses com slots) para o hot path | Pydantic no laço; NumPy por ponto | Pydantic e NumPy escalar custam microssegundos por acesso; o orçamento de 0,1 ms por tick exige acesso direto a listas. |
| 🟡 Versões imutáveis com undo por restauração (`revert_to_version`) | Pilha de undo em memória; edição destrutiva | Preserva o histórico para o instrutor e para o `content_hash` dos pacotes de desafio; sobrevive a reinícios. |
| 🟡 Clamp nas bordas, sem extrapolação | Extrapolação linear | Extrapolação gera VE ou avanço absurdos fora do mapa; ECUs reais usam clamp. |
| 🟡 Arbitragem em 5 níveis com cortes por OU lógico e menor avanço no empate | Uma estratégia vencedora exclusiva por tick | Um corte de proteção nunca é removido por uma estratégia de menor prioridade; o menor avanço é a escolha conservadora. |
| 🟡 Hash sobre conteúdo canónico sem metadados | Hash do payload inteiro | Duas calibrações equivalentes têm o mesmo hash, o que permite comparar acertos de alunos e restaurações. |
| 🟡 Overboost e falha de sensor no nível failsafe; knock control como offset sempre aplicado | Knock como estratégia arbitrada | O retardo de knock é proteção contínua e não deve ser anulado por overrides; overrides absolutos menores já são mais seguros. |

---

## Apêndice

### A. Limites e padrões por tipo de tabela

| Tipo (`kind`) | Dims | Eixos padrão (x × y) | Unidade | Mín | Máx | Live-tunable padrão |
|---|---|---|---|---|---|---|
| 🟡 `ve` | 3D | rpm × map_kpa | % | 0 | 150 | sim |
| 🟡 `inj_base_ms` | 3D | rpm × map_kpa | ms | 0 | 50 | sim |
| 🟡 `lambda_target` | 3D | rpm × map_kpa | λ | 0,65 | 1,30 | sim |
| 🟡 `ignition_base` | 3D | rpm × map_kpa | °BTDC | −20 | 60 | sim |
| 🟡 `ignition_trim_cyl` | 3D | rpm × map_kpa | ° | −15 | 15 | sim |
| 🟡 `fuel_trim_cyl` | 3D | rpm × map_kpa | % | −25 | 25 | sim |
| 🟡 `ign_corr_iat`, `ign_corr_ect` | 2D | iat_c / ect_c | ° | −15 | 10 | sim |
| 🟡 `fuel_corr_ect` | 2D | ect_c | % | −20 | 100 | não |
| 🟡 `fuel_corr_iat` | 2D | iat_c | % | −30 | 30 | não |
| 🟡 `accel_enrich` | 2D | tps_rate_pct_s | % | 0 | 200 | não |
| 🟡 `cranking_fuel` | 2D | ect_c | ms | 0 | 50 | não |
| 🟡 `afterstart_enrich` | 2D | ect_c | % | 0 | 100 | não |
| 🟡 `inj_dead_time` | 2D | battery_v | ms | 0 | 5 | não |
| 🟡 `boost_target` | 3D | rpm × tps_pct | kPa | 80 | 400 | sim |
| 🟡 `boost_target_gear` | 2D | gear | kPa | 80 | 400 | sim |
| 🟡 `boost_duty_base` | 3D | rpm × boost_target_kpa | % | 0 | 100 | não |
| 🟡 `knock_threshold` | 2D | rpm | adimensional | 0 | 10 | não |
| 🟡 `oil_pressure_min` | 2D | rpm | kPa | 0 | 1000 | não |
| 🟡 `cam_intake_target`, `cam_exhaust_target` | 3D | rpm × map_kpa | ° | −60 | 60 | sim |
| 🟡 `torque_request` | 3D | rpm × pedal_pct | N·m | 0 | 1500 | sim |
| 🟡 `torque_limit` | 2D | rpm | N·m | 0 | 1500 | sim |
| 🟡 `torque_limit_gear` | 2D | gear | N·m | 0 | 1500 | sim |
| 🟡 `torque_optimal` | 3D | rpm × load_pct | N·m | 0 | 1500 | não |
| 🟡 `ignition_optimal` | 3D | rpm × load_pct | °BTDC | −20 | 60 | sim |
| 🟡 `ignition_efficiency` | 2D | ign_delta_deg | adimensional | 0 | 1 | não |
| 🟡 `oem_pressure_target` | 3D | rpm × load_pct | kPa | 80 | 400 | sim |
| 🟡 `friction_torque` | 3D | rpm × ect_c | N·m | 0 | 300 | não |
| 🟡 `lambda_component_protection` | 2D | egt_c | λ | 0,65 | 1,30 | sim |

🟡 Dimensão padrão das tabelas 3D: 16×16; mínimo 2×2; máximo 32×32. Os eixos padrão concretos de cada perfil ficam no `EcuProfileDescriptor` (spec ecu-profiles).

### B. Equações e algoritmos de referência

🟡 **Interpolação 1D com clamp:** `x_c = min(max(x, x_0), x_{n−1})`; `i = bisect_right(xs, x_c) − 1` limitado a `0..n−2`; `f = (x_c − x_i)/(x_{i+1} − x_i)`; `v = v_i + f·(v_{i+1} − v_i)`.

🟡 **Interpolação bilinear:** com `f_x` nas colunas `j, j+1` e `f_y` nas linhas `i, i+1`: `v = (1−f_y)·((1−f_x)·z_{i,j} + f_x·z_{i,j+1}) + f_y·((1−f_x)·z_{i+1,j} + f_x·z_{i+1,j+1})`. Caso de teste: eixos x `(2000, 2500)`, y `(50, 100)`, z `((10, 20), (30, 40))`; em (2250, 75) o resultado é 25,0.

🟡 **Speed-density:**
- `V_cyl = displacement_cc / n_cyl · 1e−6` (m³); `R = 287,05 J/(kg·K)`.
- `T_charge = IAT_K + k·(ECT_K − IAT_K)`, com `k = charge_temp_blend`.
- `m_air = (VE/100) · MAP_kPa · 1000 · V_cyl / (R · T_charge)` (kg por cilindro por ciclo).
- `m_fuel = m_air / (λ_alvo · AFR_st)`; `AFR_st` vem de `FuelSpec` (E27 ≈ 13,2; E100 ≈ 9,0; Podium ≈ 14,4; E0 ≈ 14,7).
- `m_fuel_corr = m_fuel · (1 + STFT + LTFT) · (1 + c_ECT) · (1 + c_IAT) · (1 + c_accel + c_afterstart) · (1 + trim_cyl)`.
- `q_inj = flow_cc_min · ρ_fuel_g_cc / 60000 · sqrt(ΔP_real / ΔP_ref)` (g/ms), com `ΔP_ref = 300 kPa`; `PW_ms = m_fuel_corr_g / q_inj + t_dead(V_bat)`.
- Exemplo do RF-06: `V_cyl = 0,000496 m³`; `m_air = 0,90·200 000·0,000496/(287,05·313,15) = 0,9932 g` por cilindro e ciclo; `m_fuel = 0,9932/(0,80·13,2) = 0,09405 g`; `q_inj = 550·0,745/60000 = 0,006829 g/ms`; `PW = 13,77 ms + 0,9 ms = 14,67 ms`.
- Duty: `duty_pct = PW_ms / (120000 / rpm) · 100`.

🟡 **Malha fechada PI:** `e = (λ_medido − λ_alvo) / λ_alvo`; `STFT = clamp(kp·e + I, ±trim_limit)`; `I += ki·e·dt` só quando `|kp·e + I| < trim_limit` (anti-windup por integração condicional).

🟡 **PID de boost:** `e = alvo_kPa − MAP_kPa`; termo D sobre a medida filtrada (`τ = d_filter_tau_s`); `duty = duty_base(rpm, alvo) + kp·e + I + D`, com `I` limitado a `±integrator_limit_pct` e duty a 0..100 %. O PID só integra quando `MAP ≥ alvo − pid_activation_window_kpa`. Convenção: 0 % = wastegate livre (pressão de mola), 100 % = wastegate fechada (OQ-04).

🟡 **Alvo de boost:** `alvo = boost_target(rpm, tps)`; com `by_gear_enabled`, `alvo = min(alvo, boost_target_gear(gear))`; depois `alvo = min(alvo, tetos de knock e failsafe)`.

🟡 **Limitador soft/hard:** `f = clamp((rpm − (hard − janela)) / janela, 0, 1)`; retardo extra `= f · soft_retard_max_deg`; em `rolling_cut`, fração de cilindros cortados `= f`, escolhidos por padrão rotativo determinístico `(contador_de_ciclo + k) mod n_cyl`; em `rpm ≥ hard` corte total até `rpm < hard − histerese`.

🟡 **Cenário de referência do PID (RF-14):** turbo do `hatch-20t-gdi`, degrau de TPS 0 → 100 % a 3500 rpm em `steady_state_hold`, alvo 200 kPa, ganhos padrão.

### C. Casos de arbitragem obrigatórios

| Caso | Estratégias ativas | Resultado esperado |
|---|---|---|
| 🟡 C-01 | failsafe `fuel_cut` + two-step | Corte total; two-step inibido; vencedor `failsafe`. |
| 🟡 C-02 | limitador hard + overrun pops | Corte total; pops inibido; vencedor `rev_limiter`. |
| 🟡 C-03 | two-step (−5°) + knock retard 3° no cil. 1 | Cil. 1 recebe min(−5°, base − 3°); vencedor `two_step`. |
| 🟡 C-04 | antilag + EGT ≥ `egt_max_c` | Antilag desliga no mesmo tick; evento `antilag_protect`. |
| 🟡 C-05 | failsafe `enrich` (Δλ −0,05) + two-step (λ 0,85) | λ alvo = min(0,85, λ_base − 0,05). |
| 🟡 C-06 | overboost + PID de boost | Duty 0 %; vencedor `failsafe`. |
| 🟡 C-07 | powershift + limitador soft | Corte do powershift OU corte parcial do limitador; avanço = menor dos dois. |
| 🟡 C-08 | overrun DFCO + failsafe `boost_reduce` | Corte de combustível do DFCO mantido; teto de boost reduzido. |

### D. Pipeline do `step()` (ordem obrigatória)

1. 🟡 Validar sensores e aplicar substituições de falha (EC-04, EC-15).
2. 🟡 Calcular eixos de carga (map_kpa, tps_pct ou load_pct do hook).
3. 🟡 Calcular massa de ar (modo do `fuel_model`) e lambda alvo base.
4. 🟡 Aplicar compensações, malha fechada e trims por cilindro; calcular pulso e duty.
5. 🟡 Calcular avanço base e correções; aplicar knock control.
6. 🟡 Calcular alvo e duty de boost.
7. 🟡 Avaliar pedidos de failsafe, limitador, two-step, antilag, powershift e overrun; chamar `ProfileHooks.adjust_requests()`.
8. 🟡 Arbitrar (RF-23, RF-24), aplicar clamps finais e escrever `ActuatorCommands`, `EcuStatus` e `EcuEvent`.

### E. Regras padrão de failsafe

| `rule_id` | Limiar padrão | Confirmação | Ação | Liberação |
|---|---|---|---|---|
| 🟡 `egt_high` | `MechanicalLimits.egt_max_c` (ex.: 950 °C no `hatch-20t-gdi`) | 0,5 s | `boost_reduce` 30 kPa + `enrich` Δλ −0,05 | 2 s abaixo do limiar − 20 °C |
| 🟡 `egt_critical` | `egt_max_c` + 30 °C | 0,2 s | `boost_cut` + `rev_limit_reduce` 4000 rpm | 5 s |
| 🟡 `lean_under_load` | λ_medido − λ_alvo > 0,10 com MAP ≥ 150 kPa | 0,3 s | `boost_cut` | 2 s |
| 🟡 `ect_high` | 110 °C | 1,0 s | `boost_reduce` 50 % do alvo + `rev_limit_reduce` 4500 rpm | 10 s abaixo de 105 °C |
| 🟡 `oil_pressure_low` | abaixo de `oil_pressure_min(rpm)` | 0,5 s | `fuel_cut` com `latch_until_stop` | RPM < 500 |
| 🟡 `overspeed` | `overspeed_rpm` | 0 s | `fuel_cut` | RPM < `overspeed_rpm` − 300 |
| 🟡 `sensor_fault` | sensor inválido por 50 ms | 0,05 s | `boost_cut` + `rev_limit_reduce` 3000 rpm | 2 s com sensor válido |

### F. Campos de sensores e atuadores usados pelo ecu-core

- 🟡 `SensorReadings`: `t_sim_s`, `rpm`, `map_kpa`, `baro_kpa`, `iat_c`, `ect_c`, `tps_pct`, `pedal_pct`, `lambda_measured` (float | None), `egt_c`, `knock_intensity` (lista por cilindro, adimensional 0,0–1,0, derivado de `knock_sensor_v` pela física; a ECU não lê a tensão), `battery_v`, `oil_pressure_kpa`, `fuel_pressure_kpa`, `gear`, `vehicle_speed_kmh`, `clutch_pressed`, `launch_switch`, `shift_request`, `antilag_switch`, `sync_ok`.
- 🟡 `ActuatorCommands`: `injector_pw_ms` (lista por cilindro), `ign_advance_deg` (lista por cilindro), `fuel_cut` e `spark_cut` (listas de bool por cilindro), `wastegate_duty_pct`, `throttle_target_pct`, `antilag_air_pct`, `cam_intake_target_deg`, `cam_exhaust_target_deg`.

### G. Contrato `ProfileHooks` (implementado pela spec ecu-profiles)

```python
# Nota: os genéricos levam um espaço após o colchete por convenção de lint das specs; o código real segue o ruff format.
from typing import Protocol


class ProfileHooks(Protocol):
    profile_id: str

    def supported_strategies(self) -> frozenset[ str]: ...
    def validate_calibration(self, cal: "Calibration", options: dict[ str, bool]) -> list[ tuple[ str, str]]:
        """Devolve pares (code, detail); lista vazia = válida."""
    def air_charge_mg(self, sensors: object, compiled: object) -> float | None:
        """Usado só em fuel_model.mode == profile_air_model; None = usar speed-density."""
    def adjust_requests(self, sensors: object, requests: object) -> None:
        """Pode alterar pedidos (ex.: teto de torque do OEM) antes da arbitragem; sem alocação."""
```

### Referências
- 🟡 `_reversa_sdd/prd.md` (seções 3, 4, 6 e 9), `_reversa_sdd/personas.md` (jornadas de Lucas, Rodrigo e Prof. Marcos).
- 🟡 Heywood, J. B. "Internal Combustion Engine Fundamentals" (speed-density e enchimento).
- 🟡 Specs relacionadas: engine-physics-core, vehicle-catalog, dyno-bench, ecu-profiles, telemetry-datalogger, ecu-tuning-ui.

### Histórico de Revisões
| Versão | Data | Autor | Mudanças |
|--------|------|-------|---------|
| 🟡 1.0 | 2026-10-18 | reversa-spec-sdd | Criação inicial |
| 🟡 1.1 | 2026-10-18 | reversa-spec-sdd | Revisão R1 de consistência entre specs (decisões do usuário: knock, nomes de campo, códigos de erro, seq, campos de integração, prefixo /api/v1/, OEM-Stage, benchmark v1) |

---

## Relatório de avaliação (reversa-spec-sdd)

- 🟡 Score final: 100,0/100 (Excelente, pronta para implementação)
- 🟡 Iterações: 2 (scores: 85,0 → 100,0)
- 🟡 Breakdown: Completude 100 %, Testabilidade 100 %, Clareza 100 %, Escopo 100 %, Edge Cases 100 %
- 🟡 Gaps críticos remanescentes: nenhum
- 🟡 Sugestões remanescentes: nenhuma
- 🟡 Revisão R1 (2026-10-18): reavaliado após a revisão de consistência entre specs, score 100,0/100.
