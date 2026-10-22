# Spec: ecu-profiles

**Versão:** 1.1
**Status:** Rascunho
**Autor:** reversa-spec-sdd
**Data:** 2026-10-18
**Reviewers:** N/A
**Sprint:** 3 (componente 6 na ordem aprovada)

---

## 1. Resumo

🟡 O ecu-profiles define os 4 perfis de ECU do SimuladorRemap como configurações e adaptadores sobre o ecu-core: `oem-stage` ("OEM-Stage", lógica por torque e carga), `ft-pro`, `m1-race` e `ht-elite` (standalone com VE, lambda e ignição diretas). Ele publica o `EcuProfileDescriptor` de cada perfil (tabelas, eixos padrão, estratégias suportadas, terminologia, unidades e navegação da UI), a `BaseSetup` standalone (roda fônica, fase, PMS, bicos, combustível, sensores, wideband, proteções), o fluxo de swap OEM → standalone com checklist e mapa base gerado por assistente, e o adaptador de hardware que transforma erros de configuração em sintomas físicos coerentes (PMS errado ⇒ avanço real deslocado ⇒ knock; bico errado ⇒ lambda errado). Os perfis reproduzem a experiência mental das ECUs reais sem marcas, logotipos nem código proprietário.

---

## 2. Contexto e Motivação

**Problema:**
🟡 O ecu-core executa estratégias genéricas e não sabe como cada família de ECU organiza a calibração. Uma ECU OEM moderna não tem uma tabela de VE editada pelo preparador: ela converte o pedido de torque do pedal em carga, ar, combustível e ignição, e o remap altera os mapas de limitação de torque, eficiência de ignição e pressão alvo do turbo. Uma ECU standalone, ao contrário, exige que o preparador declare o hardware (roda fônica, bicos, sensores) e construa VE, lambda e ignição do zero. Sem esta camada, Lucas não treina um Stage 1 realista e Rodrigo não treina o swap, e um erro de configuração base não produz consequência física.

**Evidências:**
- 🟡 PRD, seção 4 (bloco ECU): perfil OEM genérico com lógica por torque e carga, perfis standalone FT-Pro, M1-Race e HT-Elite, swap OEM → standalone e configuração base (roda fônica, bicos, combustível, sensores MAP/IAT/ECT, engine failsafe).
- 🟡 PRD, seção 9 (critério de aceite do Rodrigo): trocar para um perfil standalone, configurar a base, construir VE/lambda/ignição e ativar two-step e boost por marcha, com várias puxadas sem falha.
- 🟡 PRD, seções 5 e 6: proibição de marcas registradas, logotipos e código proprietário de FuelTech, MoTeC, Haltech ou de fabricantes de ECUs OEM; nomes genéricos aprovados.
- 🟡 ecu-core, NG-02 e Apêndice G: a lógica por torque do OEM, o `BaseSetup` e o assistente de mapa base foram delegados a esta spec por meio de `ProfileHooks`.
- 🟡 ecu-tuning-ui, RF-01, RF-02, RF-15 e OQ-01: a UI monta a navegação só a partir do `EcuProfileDescriptor` e segue um assistente de 6 passos no swap.

**Por que agora:**
🟡 O ecu-core (Sprint 2) já expõe `Calibration`, `Table3D`, `StrategyConfig` e `ProfileHooks` com um hook nulo. O Sprint 3 precisa dos perfis reais para o cenário Stage 1 OEM e para o swap standalone, e a ecu-tuning-ui (Sprint 4) depende do descritor e dos endpoints de swap e de base-setup definidos aqui.

---

## 3. Goals (Objetivos)

- [ ] 🟡 G-01: O sistema deve servir os 4 descritores de perfil com p95 < 30 ms e 100 % dos itens de navegação apontando para tabelas ou estratégias suportadas pelo perfil.
- [ ] 🟡 G-02: O sistema deve recusar a partida do motor em 100 % das sessões standalone sem setup mínimo válido (roda fônica, bicos, combustível e sensor MAP).
- [ ] 🟡 G-03: O sistema deve traduzir cada erro de configuração base num sintoma físico com erro ≤ 2 % face à equação de referência do Apêndice D (avanço real, lambda real, MAP lido).
- [ ] 🟡 G-04: O sistema deve gerar o mapa base standalone por assistente em ≤ 300 ms (p95) para tabelas 16×16, com duty de bico estimado ≤ 85 % no ponto de carga máxima ou um aviso explícito.
- [ ] 🟡 G-05: O sistema deve fazer o perfil `oem-stage` limitar o torque entregue a ≤ 105 % do `torque_limit` vigente em 100 % dos pontos de uma varredura WOT.
- [ ] 🟡 G-06: O sistema deve manter 0 ocorrências de marcas registradas nos descritores, nas mensagens de erro e nas strings servidas pela API, sem exceções.
- [ ] 🟡 G-07: O sistema deve acrescentar ≤ 0,02 ms (p99) por tick ao `EcuRuntime.step()` com o adaptador de hardware ativo, a 1000 Hz e 8 cilindros.

**Métricas de sucesso:**
| Métrica | Baseline atual | Target | Prazo |
|---------|---------------|--------|-------|
| 🟡 Latência p95 de `GET /api/v1/ecu-profiles/{profile_id}` | inexistente | < 30 ms | fim do Sprint 3 |
| 🟡 Latência p95 de `POST .../ecu/swap` e `PUT .../ecu/base-setup` com mapa base | inexistente | < 400 ms | fim do Sprint 3 |
| 🟡 Casos de sintoma físico do Apêndice D aprovados | 0 | 100 % (S-01 a S-10) | fim do Sprint 3 |
| 🟡 Cobertura de testes do pacote `simremap.profiles` | 0 % | ≥ 85 % | fim do Sprint 3 |
| 🟡 Jornada do Rodrigo (Apêndice F) automatizada em E2E de backend | inexistente | 100 % dos 9 passos aprovados | fim do Sprint 3 |
| 🟡 Strings com marca registrada detectadas pelo teste de conformidade | inexistente | 0 | fim do Sprint 3 |

---

## 4. Non-Goals (Fora do Escopo)

- 🟡 NG-01: O ecu-profiles não reproduz menus, ícones, nomes de telas, cores, formatos de arquivo nem algoritmos proprietários das ECUs reais; só reproduz a lógica funcional pública (pedido de torque, VE, lambda alvo, funções de arrancada) com nomes genéricos (PRD, seções 5 e 6).
- 🟡 NG-02: O ecu-profiles não converte uma calibração entre perfis (ex.: VE do `ht-elite` para ms do `ft-pro`, ou mapas OEM para standalone). Cada swap gera um mapa base novo pelo assistente.
- 🟡 NG-03: O ecu-profiles não simula a instalação elétrica do swap (chicote, pinagem, relés, alimentação) nem falhas elétricas intermitentes; o swap é uma troca lógica de ECU.
- 🟡 NG-04: O ecu-profiles não implementa estratégias novas de controle; ele só configura, restringe e alimenta as estratégias do ecu-core e acrescenta o caminho de torque do OEM pelos hooks.
- 🟡 NG-05: O ecu-profiles não modela imobilizador, comunicação CAN com outros módulos, diagnóstico OBD2 nem códigos de falha DTC.
- 🟡 NG-06: O ecu-profiles não renderiza o assistente nem a navegação; a interface pertence à ecu-tuning-ui.
- 🟡 NG-07: O ecu-profiles não vende nem simula licenças reais; o "pacote race" do `m1-race` é só uma opção de configuração gratuita que libera estratégias.

---

## 5. Usuários e Personas

**Usuário primário:** 🟡 Rodrigo, preparador intermediário em transição para standalone. Ele troca a ECU OEM do `classic-20t-swap` (ou do `coupe-30t-i6`) por um perfil standalone, declara a base (roda fônica 60-2, bicos, E100, MAP de 4 bar, wideband), gera o mapa base e ativa two-step e boost por marcha (jornada, passos 1 a 6).

**Usuário secundário:** 🟡 Lucas, aluno de remap OEM, que no `hatch-20t-gdi` com o perfil `oem-stage` altera limitação de torque, pressão alvo do turbo, ignição e overrun (jornada, passos 2, 4 e 5). 🟡 Prof. Marcos, instrutor, que usa defeitos ocultos de hardware (ex.: sensor de rotação deslocado 8°) para mostrar à turma como um setup errado vira knock.

**Jornada atual (sem a feature):**
1. 🟡 O usuário só encontra perfis genéricos sem lógica própria: um OEM sem caminho de torque, onde aumentar o boost sempre dá potência.
2. 🟡 O usuário não tem configuração base: o motor standalone funciona com qualquer valor de bico ou de roda fônica.
3. 🟡 O usuário não aprende o efeito de um PMS mal calibrado nem de um bico declarado errado, porque nada acontece no motor.

**Jornada futura (com a feature):**
1. 🟡 Lucas faz o Stage 1 no `oem-stage`: percebe que subir só a pressão alvo não passa do limite de torque e que o remap correto mexe em `torque_limit`, `oem_pressure_target` e ignição.
2. 🟡 Rodrigo pede o swap, segue o checklist, mede o PMS com a lâmpada de ponto virtual e gera o mapa base pelo assistente.
3. 🟡 O sistema recusa a partida enquanto o setup mínimo estiver incompleto e, com o setup completo, o motor funciona e responde ao mapa.
4. 🟡 Um erro de setup gera um sintoma físico no dinamômetro (knock, lambda pobre, overboost) que o usuário diagnostica no datalogger.

---

## 6. Requisitos Funcionais

### 6.1 Requisitos Principais

| ID | Requisito | Prioridade | Critério de Aceite |
|----|-----------|-----------|-------------------|
| RF-01 | 🟡 O sistema deve registar os 4 perfis `oem-stage`, `ft-pro`, `m1-race` e `ht-elite` num registo imutável carregado no arranque, cada um com `EcuProfileDescriptor`, `ProfileHooks` e versão semântica `descriptor_version`. | Must | `GET /api/v1/ecu-profiles` devolve 200 com exatamente 4 itens, na ordem `oem-stage`, `ft-pro`, `m1-race`, `ht-elite`; um descritor inválido no arranque impede o boot com `PROFILE_REGISTRY_INVALID` no log. |
| RF-02 | 🟡 O usuário deve poder ler o descritor completo por `GET /api/v1/ecu-profiles/{profile_id}`, com `vehicle_id` opcional para receber os eixos padrão reescalados ao veículo (RPM até o limite mecânico, MAP até a pressão máxima do turbo/compressor). | Must | Sem `vehicle_id`, o eixo RPM do `ft-pro` é `500..8000` em 16 pontos; com `vehicle_id = classic-20t-swap` o último ponto iguala `MechanicalLimits.rev_limit_rpm` arredondado a 100 rpm; `profile_id` inexistente devolve 404 `ECU_PROFILE_NOT_FOUND`. |
| RF-03 | 🟡 O sistema deve incluir no descritor os campos exigidos pela ecu-tuning-ui (`navigation`, `live_tunable_table_ids`, `load_axis_channel`, `accent_color`) e validar no arranque que cada `NavItem.target_id` existe nas tabelas ou estratégias suportadas do perfil. | Must | Teste de registo: os 4 descritores têm `navigation` não vazio; um `NavItem` com `target_id = "antilag"` no `oem-stage` faz o teste falhar com `NAV_TARGET_NOT_SUPPORTED`. |
| RF-04 | 🟡 O sistema deve aplicar a matriz de suporte do Apêndice B por meio de `ProfileHooks.supported_strategies()` e `validate_calibration()`, recusando estratégias e tabelas fora do perfil. | Must | Calibração `oem-stage` com `two_step` devolve 422 `STRATEGY_NOT_SUPPORTED_BY_PROFILE`; calibração `ft-pro` com tabela `torque_limit` devolve 422 `TABLE_NOT_SUPPORTED_BY_PROFILE`; `m1-race` com pacote `base` e `antilag` devolve 422 `STRATEGY_REQUIRES_PACKAGE`. |
| RF-05 | 🟡 O sistema deve executar no `oem-stage` o caminho de torque: pedido `torque_request(rpm, pedal)` limitado por `torque_limit(rpm)`, `torque_limit_gear(gear)` e pelas proteções ativas, somado ao `friction_torque(rpm, ect)` para obter o torque indicado desejado (Apêndice C). | Must | Com `torque_request` = 400 N·m, `torque_limit` = 350 N·m, limite da marcha 4 = 380 N·m e atrito 30 N·m, o torque indicado desejado é 380 N·m ± 0,1 e `oem_torque_limiter_active = "torque_limit"`. |
| RF-06 | 🟡 O sistema deve converter no `oem-stage` o torque indicado desejado em carga alvo `load_target_pct` pela inversão monotónica de `torque_optimal(rpm, load)` corrigida por `ignition_efficiency`, e a carga em massa de ar alvo `m_air_target = load/100 · m_ref` com `m_ref = ρ_ref · V_cyl`. | Must | Na tabela de teste do Apêndice C, torque desejado 250 N·m a 3000 rpm com eficiência 1,0 dá `load_target_pct` = 125,0 ± 0,5; `torque_optimal` não crescente numa coluna devolve 422 `OEM_TORQUE_MODEL_NOT_MONOTONIC`. |
| RF-07 | 🟡 O sistema deve derivar no `oem-stage` a pressão alvo do coletor por `oem_pressure_target(rpm, load_target)`, entregá-la ao controle de boost do ecu-core como alvo e comandar a borboleta por PI sobre o MAP quando a pressão alvo for menor que `baro − 5 kPa`. | Must | Com pressão alvo 220 kPa, o alvo de boost publicado em `EcuStatus.boost_target_kpa` é 220 kPa e `throttle_pct` = 100 %; com pressão alvo 60 kPa e baro 101 kPa, o MAP estabiliza a 60 ± 3 kPa em ≤ 1 s com wastegate a 0 %. |
| RF-08 | 🟡 O sistema deve estimar no `oem-stage` a carga real pelo modelo de enchimento da própria ECU (tabela `ve` de série, não exposta na navegação do Stage) e usá-la para a massa de combustível (`fuel_model.mode = profile_air_model`, hook `air_charge_mg`). | Must | Com `ve` igual à VE física do catálogo e lambda alvo 1,00, o lambda real fica em 1,00 ± 0,02; com MAP 200 kPa e IAT 40 °C no `hatch-20t-gdi`, `air_charge_mg` iguala a equação speed-density do ecu-core (RF-06 do ecu-core) com erro < 0,5 %. |
| RF-09 | 🟡 O sistema deve aplicar no `oem-stage` a intervenção rápida de torque por ignição: quando o torque possível com o ar real exceder o desejado em mais de 2 %, atrasar a ignição até `η_ign = torque_desejado / torque_optimal(rpm, load_real)`, com atraso máximo de 20°. | Must | Com pressão alvo escalada +20 % e `torque_limit` inalterado, o torque de freio medido fica ≤ 105 % do `torque_limit` em 100 % dos pontos WOT de 2500 a 6000 rpm, o canal `oem_torque_ign_retard_deg` > 0 e a EGT sobe face à puxada base. |
| RF-10 | 🟡 O sistema deve aplicar no `oem-stage` a proteção de componentes: com a flag `component_protection` ativa, o lambda alvo efetivo é `min(lambda_target, lambda_component_protection(egt_c))`. | Must | Com EGT 920 °C e `lambda_component_protection(920)` = 0,82, o lambda alvo efetivo é 0,82 mesmo com `lambda_target` = 0,90; com a flag desligada, o alvo efetivo é 0,90. |
| RF-11 | 🟡 O sistema deve suportar as flags de proteção OEM `torque_monitoring`, `component_protection`, `knock_protection`, `overboost_protection` e `checksum_check` em `Calibration.profile_params`, todas ativas por padrão. | Must | Com `torque_monitoring` ativo e torque estimado > 110 % do `torque_limit` por 0,5 s, o sistema entra em modo de emergência (torque limitado a 50 % do `torque_limit`, boost cortado) e emite `oem_limp_mode`; com `knock_protection = false`, a estratégia `knock_control` fica desativada e o evento `oem_protection_disabled` é emitido 1 vez por aplicação. |
| RF-12 | 🟡 O sistema deve simular o checksum de calibração OEM: `oem_checksum = crc32(content_hash + ":oem-stage")` em 8 dígitos hexadecimais, guardado em `metadata.extra.oem_checksum`, verificado a cada aplicação na sessão. | Must | Aplicar uma versão com checksum desatualizado e `checksum_check = true` devolve 422 `OEM_CHECKSUM_INVALID` com `stored` e `expected` no `detail`; com `profile_options.auto_fix_checksum = true` a aplicação é aceite e emite `oem_checksum_corrected`; com `checksum_check = false` não há verificação. |
| RF-13 | 🟡 O sistema deve manter fixa a `BaseSetup` do `oem-stage` (igual ao hardware de série do veículo) e recusar edição por `PUT .../ecu/base-setup`. | Must | `PUT .../ecu/base-setup` numa sessão `oem-stage` devolve 409 `BASE_SETUP_NOT_EDITABLE_OEM`; `GET .../ecu/base-setup` devolve a base de série com `editable = false`. |
| RF-14 | 🟡 O sistema deve configurar o `ft-pro` com injeção principal MAP × RPM em ms (`fuel_model.mode = direct_pulse_ms`) ou em VE (`speed_density_ve`) por escolha do usuário, setup guiado obrigatório, funções de arrancada (two-step, powershift, antilag por botão, boost por marcha) e sugestão de E100 no assistente. | Must | O descritor `ft-pro` tem a secção "Funções de arrancada" com `two_step`, `powershift`, `antilag` e `boost_control`; trocar o modo de injeção gera nova versão com `inj_base_ms` derivado do VE pela equação do Apêndice E com erro < 1 %; `antilag.activation = "rolling"` devolve 422 `STRATEGY_OPTION_NOT_SUPPORTED`. |
| RF-15 | 🟡 O sistema deve configurar o `m1-race` com navegação por canais e funções, eficiência (VE) com lambda alvo, temperatura de carga combinada (`charge_temp_blend` padrão 0,25), modelo físico do bico (vazão vs pressão diferencial e adição de pulso curto) e o "pacote race" que libera two-step, antilag e powershift. | Must | Com pacote `base`, o descritor omite a secção de competição e a calibração com `two_step` devolve 422 `STRATEGY_REQUIRES_PACKAGE`; com pulso de 1,0 ms e `short_pulse_adder` de +0,08 ms a 1,0 ms, o pulso comandado ao físico é aumentado em 0,08 ms ± 0,001. |
| RF-16 | 🟡 O sistema deve configurar o `ht-elite` com VE e lambda alvo, assistente de mapa base em destaque, correções de combustível e ignição por cilindro até 8 cilindros, e antilag por botão ou em rolamento (rolling antilag). | Must | O descritor `ht-elite` lista `fuel_trim_cyl` e `ignition_trim_cyl` para os cilindros 1 a `n_cyl`; `antilag.activation = "rolling"` é aceite; o assistente é o primeiro item da navegação. |
| RF-17 | 🟡 O usuário deve poder trocar a ECU por `POST /api/v1/sessions/{session_id}/ecu/swap` com `SwapRequest`: o sistema guarda o snapshot da calibração OEM, muda o perfil da sessão e passa ao estado `awaiting_base_setup`. | Must | Swap `oem-stage` → `ft-pro` fora de puxada devolve 200 com `ecu_state = awaiting_base_setup`, `oem_snapshot` preenchido e checklist com os 6 itens obrigatórios em `missing`; swap com puxada ativa devolve 409 `RUN_IN_PROGRESS`; swap para o perfil atual devolve 422 `SWAP_TARGET_INVALID`. |
| RF-18 | 🟡 O usuário deve poder voltar ao OEM (swap para `oem-stage`) ou trocar entre perfis standalone: o OEM restaura o snapshot e a base de série; entre standalone, a `BaseSetup` é mantida e um mapa base novo é gerado se o setup estiver completo. | Must | Swap `ft-pro` → `oem-stage` repõe a calibração do snapshot com o mesmo `content_hash` e `ecu_state = oem`; swap `ft-pro` → `ht-elite` com setup completo devolve `ecu_state = standalone_ready` e uma calibração nova com `metadata.source = "wizard"`. |
| RF-19 | 🟡 O usuário deve poder gravar a `BaseSetup` por `PUT /api/v1/sessions/{session_id}/ecu/base-setup`, parcial ou completa, com controlo otimista por `base_version`; o sistema valida a estrutura, devolve o checklist do Apêndice A e cria uma versão imutável da base. | Must | PUT só com roda fônica válida devolve 200, `ecu_state = awaiting_base_setup` e 5 obrigatórios em `missing`; PUT com `base_version` antiga devolve 409 `BASE_SETUP_VERSION_CONFLICT`; bico com vazão 0 devolve 422 `BASE_SETUP_INVALID` com `field = injectors.flow_cc_min`. |
| RF-20 | 🟡 O sistema deve impedir a partida sem setup mínimo válido (roda fônica, bicos, combustível e sensor MAP em `ok`) e sem calibração aplicada: o adaptador corta faísca e injeção em todos os cilindros e o guard de sessão recusa puxadas. | Must | Em `awaiting_base_setup`, `POST .../runs` devolve 409 `ECU_SETUP_INCOMPLETE` com a lista de itens pendentes; em 10 000 ticks o adaptador emite `fuel_cut` e `spark_cut` verdadeiros para todos os cilindros e o motor fica parado (`EngineState.stalled = true` em ≤ 2 s). |
| RF-21 | 🟡 O sistema deve gerar o mapa base standalone por assistente a partir de cilindrada, número de cilindros, taxa de compressão, aspiração, bicos, combustível, pressão máxima alvo e limite de rotação (fórmulas do Apêndice E), criando a calibração pelo serviço do ecu-core com `metadata.source = "wizard"`. | Must | Para o `classic-20t-swap` com E100 e MAP máximo 250 kPa, a calibração gerada tem `ve`, `lambda_target`, `ignition_base` e `inj_dead_time` 16×16 ou 2D válidos, o avanço a 4000 rpm e 200 kPa é 12,2° ± 0,1 e `estimated_peak_duty_pct` é devolvido; duty > 85 % gera o aviso `INJECTOR_UNDERSIZED`. |
| RF-22 | 🟡 O sistema deve transformar as leituras de sensores vistas pela ECU standalone conforme a configuração declarada versus o hardware real: escala do MAP, curva NTC de IAT/ECT e escala da wideband (Apêndice D). | Must | Sensor MAP real 20–400 kPa declarado como 20–250 kPa: com MAP real 200 kPa a ECU lê 128,9 ± 0,5 kPa (caso S-05); com escalas iguais a leitura é idêntica bit a bit. |
| RF-23 | 🟡 O sistema deve deslocar o avanço real pelo erro de PMS (`real = comandado + (tdc_offset_real − tdc_offset_configurado)`), oferecer a trava de ponto (`timing_lock_deg`) com leitura da lâmpada de ponto virtual e cortar a faísca quando o erro absoluto for > 30°. | Must | Erro de +8°: `EngineState.ignition_advance_deg` = comandado + 8,0 ± 0,01 (caso S-01); com `timing_lock_deg = 10` e erro +8°, o canal `timing_light_deg` mostra 18,0; erro de 35° faz o motor não arrancar e emite `tdc_offset_out_of_range`. |
| RF-24 | 🟡 O sistema deve recusar sincronismo quando a roda fônica declarada difere da real, quando o modo sequencial exige sensor de fase ausente e quando a borda de fase está a 360°, e marcar falha de ignição nos cilindros com ordem de ignição divergente. | Must | Roda declarada 36-1 com roda real 60-2: `sync_ok = false`, cortes totais e evento `trigger_sync_lost` (S-02); ordem real 1-3-4-2 declarada 1-2-4-3: os cilindros 2 e 3 recebem `spark_cut` com injeção ativa e `pop_event` no físico (S-03). |
| RF-25 | 🟡 O sistema deve calcular o pulso de injeção da ECU com a vazão e o dead time declarados na `BaseSetup`, enquanto o físico usa o `InjectorSpec` real, de modo que o lambda real siga `λ_real = λ_alvo · Q_declarada / Q_real` em malha aberta. | Must | Bico real 1000 cc/min declarado 1250 cc/min, λ alvo 0,85, malha fechada desligada, pulso ≥ 5 ms: `lambda_cyl` = 1,0625 ± 2 % (S-06); com malha fechada ligada, o trim satura em +25 % e emite `closed_loop_limit`. |
| RF-26 | 🟡 O sistema deve calcular o combustível da ECU com o AFR estequiométrico e a densidade do combustível declarado, enquanto o físico usa o combustível real do tanque. | Must | E27 declarado (13,2) com E100 no tanque (9,0) e λ alvo 0,85: `lambda_cyl` = 1,247 ± 2 % e o checklist mostra `fuel.type` em `warning` com `FUEL_MISMATCH_SUSPECTED` após 3 s de STFT no limite (S-07). |
| RF-27 | 🟡 O sistema deve converter os limites de proteção da `BaseSetup` em estratégias do ecu-core (`failsafe`, `rev_limiter`, `boost_control.overboost_kpa`) na calibração gerada ou numa nova versão quando os limites mudam. | Must | Base com EGT máxima 900 °C, rotação de corte 7200 rpm e overboost 260 kPa produz `failsafe.rules.egt_high.threshold = 900`, `rev_limiter.hard_rpm = 7200` e `boost_control.overboost_kpa = 260`; alterar só os limites cria 1 versão com `change_summary` "base-setup vN: limites". |
| RF-28 | 🟡 O sistema deve publicar por tick um `ProfileStatus` (estado do setup, sincronismo, avanço real vs comandado, leitura da lâmpada de ponto, canais do caminho de torque OEM) e eventos `ProfileEvent` para o telemetry-datalogger. | Must | O frame de telemetria contém `profile.sync_ok`, `profile.ign_real_minus_cmd_deg` e, no `oem-stage`, `oem_torque_request_nm`, `oem_load_target_pct` e `oem_torque_limiter_active`; cada evento tem o mesmo `t_sim_s` do tick que o originou. |
| RF-29 | 🟡 O sistema deve aceitar sobreposições de hardware real (`HardwareOverride`) vindas do training-scenarios para defeitos ocultos (PMS deslocado, roda fônica trocada, bico de vazão diferente, sensor MAP de outra escala). | Should | Cenário com `tdc_offset_shift_deg = 8` produz o mesmo resultado do caso S-01 sem nenhuma diferença visível na `BaseSetup` ou na ficha de instalação. |
| RF-30 | 🟡 O usuário deve poder ler a base atual e o checklist por `GET /api/v1/sessions/{session_id}/ecu/base-setup`, junto com a ficha de instalação do hardware visível (tipo de roda fônica, presença de sensor de fase, etiqueta do bico, combustível no tanque, faixa do sensor MAP, PMS nominal do manual). | Must | `GET` no estado `awaiting_base_setup` devolve 200 com `checklist`, `hardware_sheet` e `base_setup = null`; o PMS real nunca aparece na resposta (só o nominal). |
| RF-31 | 🟡 O sistema deve permitir completar a jornada do Rodrigo (Apêndice F) do swap à validação em `multi_pull`, sem falha mecânica e com a meta de potência atingida. | Must | Teste E2E de backend com `seed = 42`: os 9 passos do Apêndice F passam; o `multi_pull` de 3 puxadas tem `peak_whp_spread_pct` ≤ 2 % e nenhum `FailureEvent`. |

### 6.2 Fluxo Principal (Happy Path)

🟡 Swap OEM → `ft-pro` no `classic-20t-swap` (Rodrigo):

1. 🟡 O usuário cria a sessão com `vehicle_id = classic-20t-swap` e `profile_id = oem-stage` (dyno-bench) e abre o assistente de swap na ecu-tuning-ui.
2. 🟡 O usuário envia `POST /api/v1/sessions/{session_id}/ecu/swap` com `target_profile_id = ft-pro` e `confirm_snapshot = true`.
3. 🟡 O sistema verifica que não há puxada ativa, grava o snapshot da calibração OEM, muda o perfil da sessão, instala o `ProfiledEcu` em modo sem partida e devolve 200 com `ecu_state = awaiting_base_setup`, checklist e ficha de instalação.
4. 🟡 O usuário preenche os 6 passos do assistente (roda fônica, bicos, combustível, sensores, proteções, revisão) e envia `PUT .../ecu/base-setup` com `generate_base_map = true` e `wizard` (MAP máximo 250 kPa, corte 7200 rpm).
5. 🟡 O sistema valida a base, cria a versão 1 da base, gera o mapa base pelo Apêndice E, cria a calibração pelo ecu-core, aplica-a à sessão na fronteira de tick e devolve `ecu_state = standalone_ready`, `calibration_id`, `estimated_peak_duty_pct` e avisos.
6. 🟡 O usuário ativa `timing_lock_deg = 10`, mede o ponto com a lâmpada virtual em marcha lenta e confirma que `timing_light_deg` = 10,0 (PMS correto).
7. 🟡 O usuário constrói VE e lambda com `steady_state_hold`, ajusta a ignição até o MBT e ativa two-step e boost por marcha (ecu-core e ecu-tuning-ui).
8. 🟡 Resultado: o `multi_pull` mostra repetibilidade térmica, nenhuma falha e a meta de potência, cumprindo o critério de aceite do Rodrigo (PRD, seção 9).

### 6.3 Fluxos Alternativos

**Fluxo Alternativo A — Stage 1 OEM (Lucas):**
1. 🟡 O usuário clona a calibração de série `oem-stage` do `hatch-20t-gdi` e escala `oem_pressure_target` em +15 %.
2. 🟡 O sistema aplica e a puxada mostra torque preso ao `torque_limit` com atraso de intervenção > 0° (RF-09).
3. 🟡 O usuário sobe `torque_limit` e `torque_request` no pedal alto em +18 %, corrige o checksum e aplica.
4. 🟡 O sistema aceita a versão, a puxada mostra ganho de torque sem atraso de intervenção e o caminho de torque fica visível nos canais `oem_*`.

**Fluxo Alternativo B — Setup incompleto:**
1. 🟡 O usuário envia `PUT .../ecu/base-setup` sem bicos e tenta iniciar uma puxada.
2. 🟡 O sistema mantém `awaiting_base_setup`, o motor não arranca e `POST .../runs` devolve 409 `ECU_SETUP_INCOMPLETE` com `pending = ["injectors.flow", "injectors.dead_time", "base_map"]`.

**Fluxo Alternativo C — PMS errado (defeito oculto do Prof. Marcos):**
1. 🟡 O cenário aplica `tdc_offset_shift_deg = 8` e o aluno usa o PMS nominal da ficha.
2. 🟡 O sistema adianta o avanço real em 8°; numa puxada com avanço comandado no limite, o knock-and-failure-model detecta knock e o datalogger mostra `profile.ign_real_minus_cmd_deg = 8`.
3. 🟡 O aluno usa a trava de ponto, lê 18° na lâmpada com 10° comandados, corrige o offset em +8° e o knock desaparece.

**Fluxo Alternativo D — Voltar ao OEM:**
1. 🟡 O usuário envia swap com `target_profile_id = oem-stage`.
2. 🟡 O sistema repõe o snapshot (mesmo `content_hash`), a base de série e `ecu_state = oem`; a calibração standalone fica guardada para um swap futuro.

---

## 7. Requisitos Não-Funcionais

| ID | Requisito | Valor alvo | Observação |
|----|-----------|-----------|------------|
| 🟡 RNF-01 | Performance do adaptador no laço | ≤ 0,02 ms p99 por tick acrescentados ao `step()` (1000 Hz, 8 cilindros); caminho de torque OEM ≤ 0,03 ms p99 | 🟡 `pytest-benchmark` com 100 000 ticks; sem alocação por tick, sem Pydantic no hot path (dataclasses com slots e listas pré-alocadas). |
| 🟡 RNF-02 | Latência da API | p95 < 30 ms em `GET /api/v1/ecu-profiles*`; p95 < 200 ms em swap sem mapa base; p95 < 400 ms em `PUT /api/v1/sessions/{session_id}/ecu/base-setup` com mapa base 16×16 | 🟡 SQLite local, hardware de referência (4 núcleos, 8 GB). |
| 🟡 RNF-03 | Determinismo | 100 % de igualdade de SHA-256 do log em 10 execuções com a mesma `seed`, base, calibração e overrides | 🟡 Assistente e adaptador são funções puras; nenhum uso de `random` ou de relógio. |
| 🟡 RNF-04 | Qualidade | Cobertura ≥ 85 % em `simremap.profiles`; `mypy --strict`, `ruff` e `bandit` sem achados médios ou altos | 🟡 Testes de propriedade (hypothesis) para a inversão de torque e as transformações de sensor. |
| 🟡 RNF-05 | Conformidade de marcas | 0 ocorrências da lista de bloqueio em descritores, mensagens e OpenAPI | 🟡 Teste `test_brand_compliance.py` no CI (Apêndice G). |
| 🟡 RNF-06 | Memória | ≤ 2 MB por sessão para descritor, base e estado do adaptador | 🟡 Os descritores são partilhados entre sessões (imutáveis). |

---

## 8. Design e Interface

**Componentes afetados:**
- 🟡 `backend/src/simremap/profiles/` (novo): `contracts.py` (todos os modelos da seção 9), `registry.py` (4 perfis), `descriptors/` (um módulo por perfil), `hooks/oem_stage.py` (caminho de torque, flags, checksum), `hooks/standalone.py` (base comum de `ft-pro`, `m1-race`, `ht-elite`), `hardware.py` (`VehicleEcuHardware`, ficha de instalação, overrides), `adapter.py` (`ProfiledEcu`, transformações de sensor e atuador), `setup.py` (validação e checklist), `wizard.py` (mapa base), `swap.py` (máquina de estados), `data/hardware/*.json` (hardware real por veículo).
- 🟡 `backend/src/simremap/api/routers/ecu_profiles.py` e `api/routers/session_ecu.py`.
- 🟡 `backend/src/simremap/db/models/profiles.py` e migração Alembic.
- 🟡 Consumidores: ecu-core (hooks, compilação), dyno-bench (guard de partida e troca de perfil da sessão), telemetry-datalogger (`ProfileStatus`, `ProfileEvent`), ecu-tuning-ui (descritor, assistente), training-scenarios (`HardwareOverride`), dyno-cockpit-ui (nome do perfil).

**Integração no laço (passo 2 da ordem por tick):**
🟡 O dyno-bench chama `ProfiledEcu.step(sensors, dt)`, que executa: (1) `sensor_view = adapter.transform_sensors(sensors)` (escalas declaradas, sincronismo); (2) `commands = EcuRuntime.step(sensor_view, dt)` com os hooks do perfil; (3) `adapter.transform_commands(commands)` (offset de PMS, ordem de ignição, cortes sem sincronismo, adição de pulso curto do `m1-race`). O `EcuStatus` guarda os valores comandados; o `ActuatorCommands` entregue ao físico leva os valores reais.

**Comportamento esperado (API REST):**

| Método e caminho | Request | Response | Erros (`code`) |
|---|---|---|---|
| 🟡 `GET /api/v1/ecu-profiles` | sem corpo | 200 lista de `EcuProfileSummary` | 500 `PROFILE_REGISTRY_INVALID` (só se o registo falhar após o boot) |
| 🟡 `GET /api/v1/ecu-profiles/{profile_id}?vehicle_id=` | `vehicle_id` opcional | 200 `EcuProfileDescriptor` | 404 `ECU_PROFILE_NOT_FOUND`, 404 `VEHICLE_NOT_FOUND` |
| 🟡 `POST /api/v1/sessions/{session_id}/ecu/swap` | `SwapRequest` | 200 `SwapResult` | 404 `SESSION_NOT_FOUND`, 404 `ECU_PROFILE_NOT_FOUND`, 409 `RUN_IN_PROGRESS`, 409 `SESSION_CLOSED`, 422 `SWAP_TARGET_INVALID`, 422 `SWAP_CONFIRMATION_REQUIRED`, 422 `SWAP_NOT_SUPPORTED_FOR_VEHICLE`, 503 `STORAGE_UNAVAILABLE` |
| 🟡 `PUT /api/v1/sessions/{session_id}/ecu/base-setup` | `BaseSetupUpdate` | 200 `BaseSetupResult` | 404 `SESSION_NOT_FOUND`, 409 `BASE_SETUP_NOT_EDITABLE_OEM`, 409 `BASE_SETUP_VERSION_CONFLICT`, 409 `RUN_IN_PROGRESS`, 422 `BASE_SETUP_INVALID`, 422 `WIZARD_INPUT_INVALID`, 422 `TABLE_*` (do ecu-core), 504 `CALIBRATION_APPLY_TIMEOUT` |
| 🟡 `GET /api/v1/sessions/{session_id}/ecu/base-setup` | sem corpo | 200 `BaseSetupResult` (sem calibração gerada) | 404 `SESSION_NOT_FOUND` |

🟡 Todos os erros usam `application/problem+json` (`ProblemDetail`) com `code` estável; erros de campo da base incluem `detail.field` (caminho com pontos, ex.: `trigger.missing_teeth`) e `detail.reason`.

**Exemplo de `SwapRequest` e resposta:**

```json
{ "target_profile_id": "ft-pro", "confirm_snapshot": true, "feature_package": "race", "prefill_from_hardware_sheet": false }
```

```json
{
  "session_id": "s-7f3a", "previous_profile_id": "oem-stage", "profile_id": "ft-pro",
  "ecu_state": "awaiting_base_setup",
  "oem_snapshot": { "calibration_id": "c-91", "version": 4, "content_hash": "ab12...ef" },
  "base_setup_version": null, "calibration_id": null,
  "checklist": { "items": [ { "id": "trigger.wheel", "required": true, "status": "missing" } ], "minimum_valid": false },
  "hardware_sheet": { "trigger_wheel": "60-2", "phase_sensor_present": false, "injector_label_cc_min": 1000, "tank_fuel_id": "e100", "map_sensor_label_kpa": [ 20, 400 ], "tdc_offset_nominal_deg": 90.0 }
}
```

**Estados da sessão de ECU (máquina de estados):**

| Estado | Entrada | Saídas | Motor |
|---|---|---|---|
| 🟡 `oem` | Sessão criada com `oem-stage` ou swap de volta ao OEM | `awaiting_base_setup` (swap para standalone) | Arranca com a calibração aplicada |
| 🟡 `awaiting_base_setup` | Swap para standalone sem setup mínimo ou sem calibração | `standalone_ready` (PUT com mínimo `ok` e calibração aplicada), `oem` (swap de volta) | Não arranca (cortes totais) |
| 🟡 `standalone_ready` | PUT de base completo com mapa base aplicado | `awaiting_base_setup` (PUT que invalida um item obrigatório), `oem`, `standalone_ready` noutro perfil standalone | Arranca; sintomas físicos conforme os erros de setup |

**Estados da UI (contrato para a ecu-tuning-ui):**
- 🟡 Estado vazio: `base_setup = null` e checklist com todos os obrigatórios em `missing`; a UI abre o passo 1 do assistente.
- 🟡 Estado de carregamento: entre o PUT e o response, a sessão mantém o estado anterior (sem estado intermédio visível).
- 🟡 Estado de erro: `BASE_SETUP_INVALID` com `detail.field` permite destacar o campo do passo correspondente.
- 🟡 Estado de sucesso: `ecu_state = standalone_ready`, `calibration_id` e avisos não bloqueantes (ex.: `INJECTOR_UNDERSIZED`).

---

## 9. Modelo de Dados

**Contratos Pydantic v2 (pacote `simremap.profiles`):**

```python
# Nota: os genéricos levam um espaço após o colchete por convenção de lint das specs; o código real segue o ruff format.
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from simremap.core.contracts import EntityId
from simremap.ecu.contracts import Axis, StrategyKind, TableKind


class EcuProfileId(StrEnum):
    OEM_STAGE = "oem-stage"
    FT_PRO = "ft-pro"
    M1_RACE = "m1-race"
    HT_ELITE = "ht-elite"


class ProfileFamily(StrEnum):
    OEM = "oem"
    STANDALONE = "standalone"


# --- Campos de navegação exigidos pela ecu-tuning-ui (OQ-01 da ecu-tuning-ui: aceite) ---
class NavItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str = Field(pattern=r"^[ a-z ][-_0-9a-z.]{1,63}$")
    label: str = Field(min_length=1, max_length=60)        # nome genérico, sem marcas
    kind: Literal["table", "strategy", "base_setup", "info"]
    target_id: str                                         # table_id, kind de StrategyConfig ou passo do assistente
    cylinder: int | None = Field(default=None, ge=1, le=12)  # itens por cilindro (trims)
    requires_package: Literal["race"] | None = None        # só m1-race


class NavSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str = Field(pattern=r"^[ a-z ][-_0-9a-z]{1,47}$")
    label: str = Field(min_length=1, max_length=60)
    items: list[ NavItem] = Field(min_length=1)


class TableSupport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: TableKind
    required: bool                                  # obrigatória na calibração do perfil
    default_x: Axis
    default_y: Axis | None = None                   # None para Table2D
    display_name: str = Field(max_length=60)        # terminologia do perfil
    per_cylinder: bool = False
    live_tunable: bool                              # sobrepõe o padrão do ecu-core (Apêndice A do ecu-core)


class StrategySupport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: StrategyKind
    level: Literal["supported", "package_race", "unsupported"]
    restricted_options: dict[ str, list[ str]] = Field(default_factory=dict)  # ex.: {"activation": ["switch"]}
    display_name: str = Field(max_length=60)


class DisplayUnits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    pressure: Literal["kpa_abs", "bar_rel", "psi_rel"] = "kpa_abs"
    mixture: Literal["lambda", "afr"] = "lambda"
    injection: Literal["ms", "ve_pct", "fuel_mass_mg"] = "ve_pct"
    temperature: Literal["c"] = "c"
    torque: Literal["nm"] = "nm"
    power: Literal["whp", "cv", "kw"] = "whp"


class EcuProfileSummary(BaseModel):
    profile_id: EcuProfileId
    name: str                    # nome genérico
    family: ProfileFamily
    inspiration: str             # texto genérico, sem marcas
    descriptor_version: str      # semver, ex.: "1.0.0"


class EcuProfileDescriptor(EcuProfileSummary):
    model_config = ConfigDict(frozen=True, extra="forbid")
    fuel_model_modes: list[ Literal["speed_density_ve", "direct_pulse_ms", "profile_air_model"]] = Field(min_length=1)
    default_fuel_model_mode: Literal["speed_density_ve", "direct_pulse_ms", "profile_air_model"]
    tables: list[ TableSupport] = Field(min_length=1)
    strategies: list[ StrategySupport]              # sempre as 9 kinds do ecu-core
    terminology: dict[ str, str]                     # chave canónica (table_id, kind, canal) → rótulo exibido
    display_units: DisplayUnits
    requires_base_setup: bool                       # False no oem-stage
    base_setup_steps: list[ Literal["trigger", "injectors", "fuel", "sensors", "protection", "review"]]
    feature_packages: list[ Literal["base", "race"]] = Field(default_factory=lambda: ["base"])
    # Campos da ecu-tuning-ui
    navigation: list[ NavSection] = Field(min_length=1)
    live_tunable_table_ids: list[ str] = Field(default_factory=list)
    load_axis_channel: Literal["map_kpa", "load_pct", "torque_request_nm", "throttle_pct"]
    accent_color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")   # acento neutro, sem cor de marca


# --- BaseSetup (standalone) ---
TriggerWheel = Literal["60-2", "36-1", "36-2", "24-1", "12-1", "4-0"]


class TriggerSetup(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    wheel: TriggerWheel
    tdc_offset_deg: float = Field(ge=0.0, lt=360.0)       # graus de cambota da falha ao PMS do cil. 1
    phase_sensor: Literal["none", "cam_hall"] = "none"
    phase_edge_deg: float = Field(default=0.0, ge=0.0, lt=720.0)
    injection_mode: Literal["sequential", "semi_sequential", "batch"] = "semi_sequential"
    ignition_mode: Literal["sequential", "wasted_spark"] = "wasted_spark"
    firing_order: list[ int] = Field(min_length=3, max_length=8)   # ex.: [1, 3, 4, 2]
    timing_lock_deg: float | None = Field(default=None, ge=-5.0, le=30.0)  # trava de ponto; None = desligada

    @model_validator(mode="after")
    def _check(self) -> "TriggerSetup":
        if sorted(self.firing_order) != list(range(1, len(self.firing_order) + 1)):
            raise ValueError("FIRING_ORDER_INVALID")
        if "sequential" in (self.injection_mode, self.ignition_mode) and self.phase_sensor == "none":
            raise ValueError("SEQUENTIAL_REQUIRES_PHASE_SENSOR")
        return self


class InjectorSetup(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    flow_cc_min: float = Field(gt=0.0, le=5000.0)          # vazão estática a ref_pressure_kpa
    ref_pressure_kpa: float = Field(default=300.0, ge=200.0, le=600.0)   # padrão 3 bar
    dead_time_v: list[ float] = Field(default=[8.0, 10.0, 12.0, 13.5, 14.5, 16.0], min_length=2, max_length=16)
    dead_time_ms: list[ float] = Field(min_length=2, max_length=16)       # mesmo tamanho de dead_time_v, 0..5 ms
    fuel_pressure_mode: Literal["fixed_rail", "map_referenced"] = "map_referenced"
    rail_pressure_kpa: float = Field(default=300.0, ge=200.0, le=800.0)
    # Modelo físico do bico (m1-race): vazão vs ΔP e adição de pulso curto
    flow_vs_dp_kpa: list[ float] | None = None
    flow_vs_dp_factor: list[ float] | None = None          # fator sobre flow_cc_min, 0,3..1,8
    short_pulse_ms: list[ float] | None = None
    short_pulse_adder_ms: list[ float] | None = None       # −0,3..0,3 ms

    @model_validator(mode="after")
    def _check(self) -> "InjectorSetup":
        if len(self.dead_time_ms) != len(self.dead_time_v):
            raise ValueError("DEAD_TIME_SHAPE_MISMATCH")
        if any(b <= a for a, b in zip(self.dead_time_v, self.dead_time_v[1:])):
            raise ValueError("TABLE_AXIS_NOT_MONOTONIC")
        if any(not 0.0 <= v <= 5.0 for v in self.dead_time_ms):
            raise ValueError("DEAD_TIME_OUT_OF_RANGE")
        return self


class FuelSetup(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    fuel_id: Literal["e0", "e27", "e100", "podium"]        # ids do vehicle-catalog (FuelSpec)
    afr_stoich: float = Field(ge=8.0, le=15.5)             # preenchido do FuelSpec; editável para erro didático
    density_g_cc: float = Field(ge=0.68, le=0.82)


class MapSensorSetup(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    min_kpa: float = Field(ge=0.0, le=50.0)                # leitura a 0,5 V
    max_kpa: float = Field(ge=100.0, le=700.0)             # leitura a 4,5 V


class NtcSensorSetup(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    curve: Literal["ntc_a", "ntc_b", "ntc_c"] = "ntc_a"    # curvas genéricas (Apêndice D)


class WidebandSetup(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    lambda_at_0v: float = Field(default=0.5, ge=0.4, le=1.0)
    lambda_at_5v: float = Field(default=1.5, ge=1.0, le=2.5)


class SensorSetup(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    map: MapSensorSetup | None = None
    iat: NtcSensorSetup = NtcSensorSetup()
    ect: NtcSensorSetup = NtcSensorSetup()
    wideband: WidebandSetup | None = None                  # None = malha fechada indisponível


class ProtectionLimits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    rev_limit_rpm: float = Field(default=7000.0, ge=2000.0, le=12000.0)
    overspeed_rpm: float = Field(default=7500.0, ge=2000.0, le=13000.0)
    overboost_kpa: float = Field(default=260.0, ge=100.0, le=500.0)
    egt_max_c: float = Field(default=950.0, ge=600.0, le=1100.0)
    ect_max_c: float = Field(default=110.0, ge=80.0, le=130.0)
    oil_pressure_min_kpa: float = Field(default=100.0, ge=0.0, le=600.0)
    lean_delta_lambda: float = Field(default=0.10, ge=0.03, le=0.30)

    @model_validator(mode="after")
    def _check(self) -> "ProtectionLimits":
        if self.overspeed_rpm <= self.rev_limit_rpm:
            raise ValueError("OVERSPEED_BELOW_REV_LIMIT")
        return self


class BaseSetup(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    trigger: TriggerSetup | None = None
    injectors: InjectorSetup | None = None
    fuel: FuelSetup | None = None
    sensors: SensorSetup = SensorSetup()
    protection: ProtectionLimits = ProtectionLimits()
    feature_package: Literal["base", "race"] = "base"     # só relevante no m1-race


class ChecklistItem(BaseModel):
    id: Literal["trigger.wheel", "trigger.tdc_offset", "trigger.phase", "trigger.firing_order",
                "injectors.flow", "injectors.dead_time", "fuel.type", "sensors.map",
                "sensors.iat", "sensors.ect", "sensors.wideband", "protection.limits", "base_map"]
    required: bool
    status: Literal["ok", "missing", "invalid", "warning"]
    code: str | None = None          # ex.: "FUEL_MISMATCH_SUSPECTED", "INJECTOR_UNDERSIZED"
    message: str = ""                # pt-BR, genérico


class SetupChecklist(BaseModel):
    items: list[ ChecklistItem]
    minimum_valid: bool              # trigger.wheel, injectors.flow, injectors.dead_time, fuel.type e sensors.map em ok ou warning


class WizardInputs(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    max_map_kpa: float = Field(default=200.0, ge=100.0, le=450.0)
    rev_limit_rpm: float | None = None                     # None = protection.rev_limit_rpm
    idle_rpm: float = Field(default=900.0, ge=600.0, le=1500.0)
    grid: Literal[12, 16, 20] = 16
    fuel_model_mode: Literal["speed_density_ve", "direct_pulse_ms"] | None = None  # None = padrão do perfil


class OemSnapshot(BaseModel):
    calibration_id: EntityId
    version: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class HardwareSheet(BaseModel):
    """O que um mecânico vê no carro; nunca contém o PMS real."""
    trigger_wheel: TriggerWheel
    phase_sensor_present: bool
    firing_order: list[ int]
    injector_label_cc_min: float
    tank_fuel_id: Literal["e0", "e27", "e100", "podium"]
    map_sensor_label_kpa: tuple[ float, float]
    tdc_offset_nominal_deg: float
    n_cyl: int
    displacement_cc: float


class SwapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_profile_id: EcuProfileId
    confirm_snapshot: bool                                 # deve ser True ao sair do oem-stage
    feature_package: Literal["base", "race"] = "base"
    prefill_from_hardware_sheet: bool = False              # pré-preenche roda, ordem, bico, combustível e MAP
    request_id: str | None = Field(default=None, max_length=64)  # idempotência


class SwapResult(BaseModel):
    session_id: EntityId
    previous_profile_id: EcuProfileId
    profile_id: EcuProfileId
    ecu_state: Literal["oem", "awaiting_base_setup", "standalone_ready"]
    oem_snapshot: OemSnapshot | None
    base_setup_version: int | None
    calibration_id: EntityId | None
    checklist: SetupChecklist
    hardware_sheet: HardwareSheet


class BaseSetupUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_version: int | None = Field(default=None, ge=1)  # None só na primeira gravação
    base_setup: BaseSetup
    generate_base_map: bool = False
    wizard: WizardInputs | None = None
    apply_limits_to_calibration: bool = True


class BaseSetupResult(BaseModel):
    session_id: EntityId
    profile_id: EcuProfileId
    editable: bool
    ecu_state: Literal["oem", "awaiting_base_setup", "standalone_ready"]
    base_setup_version: int | None
    base_setup: BaseSetup | None
    setup_hash: str | None           # SHA-256 do JSON canónico da base
    checklist: SetupChecklist
    hardware_sheet: HardwareSheet
    calibration_id: EntityId | None = None
    calibration_version: int | None = None
    estimated_peak_duty_pct: float | None = None
    warnings: list[ str] = Field(default_factory=list)


# --- Hardware real e defeitos ocultos ---
class VehicleEcuHardware(BaseModel):
    """Verdade física por veículo (data/hardware/<vehicle_id>.json); o bico e o combustível vêm do vehicle-catalog."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    vehicle_id: EntityId
    trigger_wheel: TriggerWheel
    tdc_offset_true_deg: float = Field(ge=0.0, lt=360.0)
    tdc_offset_nominal_deg: float = Field(ge=0.0, lt=360.0)
    phase_sensor_present: bool
    phase_edge_true_deg: float = Field(ge=0.0, lt=720.0)
    firing_order: list[ int]
    map_sensor_kpa: tuple[ float, float]
    iat_curve: Literal["ntc_a", "ntc_b", "ntc_c"] = "ntc_a"
    ect_curve: Literal["ntc_a", "ntc_b", "ntc_c"] = "ntc_a"
    wideband_true: tuple[ float, float] = (0.5, 1.5)
    swap_supported: bool = True


class HardwareOverride(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    tdc_offset_shift_deg: float = Field(default=0.0, ge=-40.0, le=40.0)
    trigger_wheel: TriggerWheel | None = None
    injector_flow_cc_min: float | None = Field(default=None, gt=0.0)
    map_sensor_kpa: tuple[ float, float] | None = None
    tank_fuel_id: Literal["e0", "e27", "e100", "podium"] | None = None


# --- Flags OEM (em Calibration.profile_params, definido no ecu-core, revisão R1) ---
class OemProtectionFlags(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    torque_monitoring: bool = True
    component_protection: bool = True
    knock_protection: bool = True
    overboost_protection: bool = True
    checksum_check: bool = True


# --- Saídas por tick (snapshot decimado; no laço usa-se dataclass com slots) ---
class ProfileStatus(BaseModel):
    t_sim_s: float
    profile_id: EcuProfileId
    ecu_state: Literal["oem", "awaiting_base_setup", "standalone_ready"]
    sync_ok: bool
    ign_cmd_deg: list[ float]
    ign_real_minus_cmd_deg: float
    timing_light_deg: float | None
    map_read_kpa: float
    lambda_read: float | None
    # Caminho de torque (só oem-stage; None nos outros perfis)
    oem_torque_request_nm: float | None = None
    oem_torque_desired_ind_nm: float | None = None
    oem_torque_limiter_active: Literal["none", "torque_limit", "gear", "limp", "protection"] | None = None
    oem_load_target_pct: float | None = None
    oem_load_actual_pct: float | None = None
    oem_pressure_target_kpa: float | None = None
    oem_torque_ign_retard_deg: float | None = None
    oem_limp_mode: bool | None = None


class ProfileEvent(BaseModel):
    t_sim_s: float
    kind: Literal["trigger_sync_lost", "trigger_sync_ok", "tdc_offset_out_of_range", "firing_order_misfire",
                  "no_start_setup_incomplete", "oem_limp_mode", "oem_protection_disabled",
                  "oem_checksum_corrected", "fuel_mismatch_suspected", "injector_undersized"]
    cylinder: int | None = None
    value: float | None = None
    detail: str = ""
```

🟡 **Integração com o ecu-core (revisão R1):** `Calibration.profile_params: dict[ str, float | bool | str]` (incluído no `content_hash`) já existe no `ecu-core` e guarda as flags OEM e o `fuel_model_mode` escolhido. Fica pedido (OQ-01) um parâmetro `EcuHardwareConfig` (vazão, `ref_pressure_kpa`, dead time, AFR estequiométrico, densidade, `n_cyl`, cilindrada) entregue na compilação, preenchido pelo perfil a partir da `BaseSetup` (standalone) ou do catálogo (OEM).

🟡 **Hash da base:** `setup_hash = sha256(json.dumps(base_setup.model_dump(mode="json"), sort_keys=True, separators=(",", ":")))`, com floats arredondados a 6 casas. A calibração gerada guarda `metadata.extra.base_setup_hash`.

**Entidades persistidas (SQLModel):**

```
ecu_session_state {
  session_id: str (PK, FK lógica para SimulationSession)
  profile_id: str
  ecu_state: str                  // oem | awaiting_base_setup | standalone_ready
  feature_package: str            // base | race
  oem_snapshot_calibration_id: str | null
  oem_snapshot_version: int | null
  standalone_calibration_id: str | null
  latest_base_setup_version: int | null
  hardware_override_json: text | null   // vindo do training-scenarios; nunca exposto na API
  updated_at: datetime
}
ecu_base_setup_version {
  session_id: str (PK composta)
  version: int (PK composta)
  profile_id: str
  payload_json: text              // BaseSetup
  setup_hash: str (índice)
  created_at: datetime
}
```

**Migrações necessárias:** 🟡 Sim. Uma migração Alembic cria as 2 tabelas com índice em `setup_hash`. Sem impacto em dados existentes (componente novo). Os descritores e o hardware real são ficheiros versionados no pacote, não tabelas.

---

## 10. Integrações e Dependências

| Dependência | Tipo | Impacto se indisponível |
|-------------|------|------------------------|
| 🟡 ecu-core (`Calibration`, `Table3D`, `StrategyConfig`, `ProfileHooks`, `EcuRuntime`, serviço de criação e aplicação de calibração) | Obrigatória | Sem o core não há perfis; os testes usam o `EcuRuntime` real com calibrações de fixture. |
| 🟡 vehicle-catalog (`VehicleSpec`, `EngineSpec.displacement_cc`, `n_cyl`, `compression_ratio`, `InjectorSpec`, `FuelSpec`, `MechanicalLimits`, `stock_calibration_id`) | Obrigatória | Sem veículo, `GET ...?vehicle_id=` devolve 404 `VEHICLE_NOT_FOUND` e o swap devolve 404 `SESSION_NOT_FOUND` para sessões órfãs. |
| 🟡 dyno-bench (`SimulationSession`, troca de `profile_id`, worker do laço, estado de puxada) | Obrigatória | O dyno-bench chama `ProfileSessionGuard.can_start_run(session_id)` antes de aceitar `POST .../runs` (ver OQ-02). |
| 🟡 engine-physics-core (`SensorReadings`, `ActuatorCommands`, `EngineState`) | Obrigatória | O adaptador lê e escreve os campos `map_kpa`, `iat_c`, `ect_c`, `lambda_measured`, `injector_pw_ms`, `ignition_advance_deg`, `fuel_cut`, `spark_cut`, `throttle_pct`. |
| 🟡 telemetry-datalogger (`ProfileStatus`, `ProfileEvent`) | Opcional | Sem consumidor, os snapshots são descartados (fila de 256 itens, descarte do mais antigo); o laço não bloqueia. |
| 🟡 training-scenarios (`HardwareOverride` dos defeitos ocultos) | Opcional | Sem cenário, o hardware real é o ficheiro do veículo sem overrides. |
| 🟡 platform-foundation (`ProblemDetail`, BD, config) | Obrigatória | Sem BD, swap e base-setup devolvem 503 `STORAGE_UNAVAILABLE` com `Retry-After: 2`; o laço continua com o estado em memória. |

---

## 11. Edge Cases e Tratamento de Erros

| Cenário | Trigger | Comportamento esperado |
|---------|---------|----------------------|
| 🟡 EC-01: Swap durante puxada | `POST .../ecu/swap` com `active_run_id` não nulo | 409 `RUN_IN_PROGRESS`; perfil, calibração e estado ficam iguais. |
| 🟡 EC-02: Swap sem confirmação | `confirm_snapshot = false` a partir do `oem-stage` | 422 `SWAP_CONFIRMATION_REQUIRED`; nada é gravado. |
| 🟡 EC-03: Swap repetido (retry do cliente) | Mesmo `request_id` em 2 pedidos | O segundo devolve o mesmo `SwapResult` do primeiro, sem novo snapshot (idempotência por 10 min). |
| 🟡 EC-04: Falha de BD a meio do swap | Erro de I/O depois do snapshot e antes da troca de perfil | Transação única com rollback; 503 `STORAGE_UNAVAILABLE` com `Retry-After: 2`; a sessão continua no perfil anterior e o retry é seguro. |
| 🟡 EC-05: Timeout ao aplicar o mapa base | O worker não confirma a troca em 100 ms | 504 `CALIBRATION_APPLY_TIMEOUT`; a base e a calibração ficam gravadas; o estado fica `awaiting_base_setup` com o item `base_map` em `invalid`; o usuário repete com `POST .../calibration` (ecu-core). |
| 🟡 EC-06: Setup mínimo removido depois de pronto | PUT que apaga `injectors` em `standalone_ready` | Estado volta a `awaiting_base_setup`; o motor para no tick seguinte (cortes totais) e emite `no_start_setup_incomplete`. |
| 🟡 EC-07: Erro de PMS extremo | `abs(tdc_offset_real − tdc_offset_configurado) > 30°` | Fallback de segurança: faísca cortada em todos os cilindros, motor não arranca, evento `tdc_offset_out_of_range` com o valor do erro só em modo instrutor. |
| 🟡 EC-08: Sequencial sem sensor de fase real | Base declara `cam_hall` com sequencial e o veículo não tem sensor de fase | `sync_ok = false`, motor não arranca e evento `trigger_sync_lost` com `detail = "phase_signal_missing"`; com semissequencial e `wasted_spark` o motor funciona. |
| 🟡 EC-09: Borda de fase errada em 360° | `phase_edge_deg` deslocado 360° do real em modo sequencial | A faísca cai no PMS de escape: falha de ignição em todos os cilindros, motor não arranca; sem sintoma em modo `wasted_spark`. |
| 🟡 EC-10: Bico subdimensionado | Duty estimado > 85 % no assistente ou duty real > 100 % | Aviso `INJECTOR_UNDERSIZED` no checklist; em funcionamento o ecu-core limita o pulso a 100 % e o motor empobrece (consequência física, `inj_duty_high`). |
| 🟡 EC-11: Wideband ausente | `sensors.wideband = null` | Malha fechada indisponível (fallback para malha aberta); item `sensors.wideband` em `warning`; `closed_loop.enabled = true` na calibração devolve aviso, não erro. |
| 🟡 EC-12: MAP acima da faixa declarada | MAP real > `max_kpa` declarado | A leitura satura em `max_kpa`; o ecu-core recebe o valor saturado e o failsafe `sensor_fault` só dispara se a leitura sair de 5–600 kPa. |
| 🟡 EC-13: Veículo sem suporte a swap | Swap num veículo com `swap_supported = false` | 422 `SWAP_NOT_SUPPORTED_FOR_VEHICLE` (ex.: veículo sem ficheiro de hardware). |
| 🟡 EC-14: Ficheiro de hardware ausente ou inválido | `data/hardware/<vehicle_id>.json` falta no arranque | O registo marca o veículo com `swap_supported = false` e regista `HARDWARE_FILE_MISSING` no log; o perfil OEM continua disponível. |
| 🟡 EC-15: Checksum OEM inválido sem correção automática | Aplicar versão OEM editada com `checksum_check = true` e `auto_fix_checksum = false` | 422 `OEM_CHECKSUM_INVALID` com `stored` e `expected`; a calibração ativa não muda. |
| 🟡 EC-16: Inversão de torque fora da tabela | Torque desejado > máximo de `torque_optimal` na coluna de RPM | `load_target_pct` fica na borda superior do eixo (clamp) e `oem_torque_limiter_active = "protection"`; sem extrapolação. |
| 🟡 EC-17: Descritor indisponível para a UI | Erro interno ao serializar o descritor | 500 `PROFILE_REGISTRY_INVALID`; a cockpit mostra só o `profile_id` (fallback da dyno-cockpit-ui). |

---

## 12. Segurança e Privacidade

- 🟡 **Autenticação:** nenhuma no MVP (local-first, um container por estação), como as demais specs.
- 🟡 **Autorização:** o swap e a base só afetam a sessão indicada no caminho; os overrides de hardware do training-scenarios nunca são expostos pela API (a resposta mostra só a ficha nominal), para não revelar o defeito oculto ao aluno.
- 🟡 **Dados sensíveis:** nenhuma PII; a base e o estado de ECU são dados técnicos.
- 🟡 **Entrada não confiável:** todos os payloads passam por Pydantic com `extra="forbid"`, limites numéricos e tamanho máximo de 256 KB; os ficheiros de hardware e de descritores são carregados só do pacote (sem caminhos vindos do usuário).
- 🟡 **Conformidade de marcas:** lista de bloqueio verificada no CI (Apêndice G); textos de inspiração descrevem funções, nunca fabricantes.
- 🟡 **Auditoria:** cada versão de base guarda `setup_hash` e `created_at`; cada swap regista no log estruturado `session_id`, perfis de origem e destino e o `content_hash` do snapshot.

---

## 13. Plano de Rollout

- 🟡 **Estratégia:** entrega no Sprint 3 atrás da flag `ECU_PROFILES_ENABLED` (lista de perfis ativos). Ordem: registo e descritores → `oem-stage` com caminho de torque e checksum → `BaseSetup`, checklist e adaptador → assistente → `ft-pro` → `ht-elite` → `m1-race` com pacote race → jornada do Rodrigo em E2E.
- 🟡 **Como reverter (rollback):** remover um perfil da flag retira-o de `GET /api/v1/ecu-profiles` e recusa swaps para ele com 404; sessões existentes nesse perfil voltam ao snapshot OEM no próximo arranque; a migração Alembic tem `downgrade` que apaga as 2 tabelas.
- 🟡 **Monitoramento pós-deploy:** benchmark p99 do adaptador no CI (falha se > 0,02 ms), contagem de `ECU_SETUP_INCOMPLETE` e de `trigger_sync_lost` por sessão nos logs estruturados, teste de conformidade de marcas em cada commit.

---

## 14. Open Questions

| # | Pergunta | Impacto | Dono | Prazo |
|---|---------|---------|------|-------|
| 🟡 OQ-01 | Parcialmente resolvida na revisão R1 (2026-10-18): o `ecu-core` adota `Calibration.profile_params` dentro do `content_hash`. ⚠️ ABERTO: o `EcuHardwareConfig` na compilação continua por confirmar com o dono do `ecu-core`. | Alto | George | 2026-10-24 |
| 🟡 OQ-02 | O dyno-bench aceita chamar `ProfileSessionGuard.can_start_run()` e devolver 409 `ECU_SETUP_INCOMPLETE`, e expor `ecu_state` em `SimulationSession`? | Alto | George | 2026-10-24 |
| 🟡 OQ-03 | O combustível real do tanque é propriedade do veículo no catálogo ou da sessão? ⚠️ ABERTO: a proposta é `VehicleSpec.default_fuel_id` com override por `HardwareOverride.tank_fuel_id`. | Médio | George | 2026-10-25 |
| 🟡 OQ-04 | Resolvida na revisão R1 (2026-10-18): o nome exibido passa a "OEM-Stage" no PRD e em todas as specs; o id continua `oem-stage`. | Alto | George | 2026-11-08 |
| 🟡 OQ-05 | Resolvida na revisão R1 (2026-10-18): o código de perfil inexistente é `ECU_PROFILE_NOT_FOUND` em todas as specs. | Baixo | George | 2026-10-24 |
| 🟡 OQ-06 | Resolvida na revisão R1 (2026-10-18): todas as specs usam `lambda_measured` e `injector_pw_ms`; o adaptador não faz conversão de nomes. | Médio | George | 2026-10-24 |
| 🟡 OQ-07 | O `GET .../ecu/base-setup` (extensão do conjunto de endpoints das convenções) é aceite como endpoint deste componente? | Baixo | George | 2026-10-25 |

---

## 15. Decisões Tomadas (Decision Log)

| Decisão | Alternativas consideradas | Racional |
|---------|--------------------------|---------|
| 🟡 Perfis como descritor declarativo + hooks sobre um único `EcuRuntime` | Um runtime por perfil | Uma só base de estratégias testada; o perfil muda só tabelas, restrições, terminologia e o caminho de ar do OEM. |
| 🟡 O erro de setup vira sintoma por um adaptador entre ECU e físico (ECU usa a base declarada, físico usa o hardware real) | Penalidades artificiais ou mensagens de erro | O aluno vê a causa física real (avanço deslocado, lambda errado, MAP lido errado), como num carro, e o datalogger mostra a discrepância. |
| 🟡 PMS real escondido; a ficha mostra só o nominal e a lâmpada de ponto virtual permite medir | Mostrar o PMS real | Reproduz o procedimento real de calibração de PMS com trava de ponto e permite defeitos ocultos do instrutor. |
| 🟡 Caminho de torque OEM com inversão de `torque_optimal` e intervenção por ignição | OEM como standalone com tabela de boost | Ensina por que subir só a pressão alvo não dá ganho num OEM e que o remap mexe nos limites de torque. |
| 🟡 Swap sem conversão de mapas, com mapa base por assistente | Converter o mapa OEM em VE | A conversão real não existe (lógicas diferentes) e o PRD pede acerto do zero para Rodrigo. |
| 🟡 Checksum simulado por CRC32 sobre o `content_hash` | Sem checksum; checksum real de ECU | Ensina o passo de correção de checksum do remap sem nenhum algoritmo proprietário. |
| 🟡 Snapshot OEM imutável e volta ao OEM com o mesmo `content_hash` | Descartar a calibração OEM no swap | Permite comparar OEM vs standalone e desfazer o swap sem perda. |

---

## Apêndice

### A. Checklist do setup standalone

| Item | Obrigatório | Regra de `ok` | Sintoma se errado |
|---|---|---|---|
| 🟡 `trigger.wheel` | sim | roda declarada válida | Diferente da real: sem sincronismo, não arranca |
| 🟡 `trigger.tdc_offset` | não (padrão = nominal da ficha) | valor declarado | Avanço real deslocado; > 30°: não arranca |
| 🟡 `trigger.phase` | não | coerente com os modos | Sequencial sem fase real ou borda a 360°: não arranca |
| 🟡 `trigger.firing_order` | não (padrão = ficha) | permutação de 1..n_cyl | Cilindros divergentes falham e geram pops |
| 🟡 `injectors.flow` | sim | 0 < vazão ≤ 5000 cc/min | Lambda real proporcional ao erro (S-06) |
| 🟡 `injectors.dead_time` | sim | tabela monotónica válida | Erro maior em pulsos curtos e marcha lenta (S-08) |
| 🟡 `fuel.type` | sim | combustível declarado | AFR errado: lambda real deslocado (S-07) |
| 🟡 `sensors.map` | sim | faixa declarada | MAP lido escalado: combustível e boost errados (S-05) |
| 🟡 `sensors.iat`, `sensors.ect` | não (padrão `ntc_a`) | curva declarada | Temperatura lida deslocada (S-09) |
| 🟡 `sensors.wideband` | não | escala declarada | Lambda lido errado; malha fechada corrige para o alvo errado (S-10) |
| 🟡 `protection.limits` | não (padrões) | validação de `ProtectionLimits` | — |
| 🟡 `base_map` | sim para `standalone_ready` | calibração aplicada à sessão | Sem calibração: não arranca |

### B. Matriz de suporte de estratégias e funções por perfil

| Estratégia ou função | `oem-stage` | `ft-pro` | `m1-race` | `ht-elite` |
|---|---|---|---|---|
| 🟡 Modo de combustível | `profile_air_model` (caminho de torque) | `direct_pulse_ms` (padrão) ou `speed_density_ve` | `speed_density_ve` com `charge_temp_blend` 0,25 | `speed_density_ve` |
| 🟡 `closed_loop` | sim | sim | sim | sim |
| 🟡 `knock_control` | sim (flag `knock_protection`) | sim | sim | sim |
| 🟡 `boost_control` | sim, alvo vindo de `oem_pressure_target` | sim, com boost por marcha | sim, com boost por marcha | sim, com boost por marcha |
| 🟡 `rev_limiter` | sim | sim | sim | sim |
| 🟡 `two_step` | não | sim | pacote race | sim |
| 🟡 `antilag` | não | sim, só `activation = switch` | pacote race, `switch` ou `rolling` | sim, `switch` ou `rolling` |
| 🟡 `powershift` | não | sim | pacote race | sim |
| 🟡 `overrun` (DFCO e pops) | sim (Stage 2 de Lucas) | sim | sim | sim |
| 🟡 `failsafe` | sim (regras OEM fixas + flags) | sim (da `BaseSetup`) | sim (da `BaseSetup`) | sim (da `BaseSetup`) |
| 🟡 Trims por cilindro (`fuel_trim_cyl`, `ignition_trim_cyl`) | só ignição | sim | sim | sim, em destaque |
| 🟡 Tabelas de torque OEM (`torque_*`, `ignition_optimal`, `ignition_efficiency`, `oem_pressure_target`, `friction_torque`, `lambda_component_protection`) | sim | não | não | não |
| 🟡 Modelo físico do bico (vazão vs ΔP, pulso curto) | não | não | sim | não |
| 🟡 `BaseSetup` editável e assistente | não | sim, obrigatório | sim | sim, em destaque |

🟡 **Eixos padrão (sem `vehicle_id`):** RPM em 16 pontos `500, 1000, ..., 8000`; MAP em 16 pontos `20, 40, ..., 320` kPa; carga OEM em 16 pontos `10, 26, ..., 250` %; pedal em 16 pontos `0, 2, 5, 10, 15, 20, 25, 30, 40, 50, 60, 70, 80, 90, 95, 100` %; marcha `1..6`. Com `vehicle_id`, o último ponto de RPM passa a `rev_limit_rpm` arredondado a 100 rpm com passo uniforme e o MAP vai até `max(320, pressão máxima do TurboSpec ou SuperchargerSpec + 20)` kPa.

🟡 **Terminologia e navegação (resumo, nomes genéricos):**
- 🟡 `oem-stage`: secções "Pedido de torque", "Limitação de torque", "Ignição e eficiência", "Pressão alvo do turbo", "Mistura e proteção de componentes", "Overrun", "Proteções e checksum"; `load_axis_channel = load_pct`; unidades `bar_rel`, `lambda`; acento `#6B7A8F`.
- 🟡 `ft-pro`: secções "Configuração base (setup guiado)", "Injeção principal", "Ignição", "Funções de arrancada" (two-step, powershift, antilag, boost por marcha), "Correções", "Proteções"; `load_axis_channel = map_kpa`; unidades `bar_rel`, `lambda`, `ms`; acento `#7A6F5A`.
- 🟡 `m1-race`: secções "Canais", "Funções: combustível", "Funções: ignição", "Funções: sobrealimentação", "Funções: competição" (pacote race), "Modelo do bico", "Proteções"; rótulo "Eficiência do motor" para `ve`; `load_axis_channel = map_kpa`; unidades `kpa_abs`, `lambda`; acento `#5E6B5E`.
- 🟡 `ht-elite`: secções "Assistente de mapa base", "Combustível (VE e lambda alvo)", "Ignição", "Correções por cilindro", "Sobrealimentação e antilag", "Arrancada", "Proteções"; `load_axis_channel = map_kpa`; unidades `kpa_abs`, `afr`; acento `#6A5F73`.

🟡 **Textos de inspiração (servidos pela API):** `oem-stage`: "ECU original moderna com estrutura de torque: pedido do pedal, limitação, carga alvo, pressão alvo e eficiência de ignição"; `ft-pro`: "Injeção programável de arrancada: mapa MAP×RPM em ms ou VE, setup guiado, two-step, powershift, antilag, boost por marcha e foco em E100"; `m1-race`: "ECU de competição por canais e funções: eficiência e lambda alvo, modelo físico do bico e pacote race"; `ht-elite`: "ECU programável com VE e lambda alvo, assistente de mapa base, correções por cilindro e antilag com rolamento".

### C. Caminho de torque do `oem-stage`

- 🟡 `T_req = torque_request(rpm, pedal_pct)` (N·m).
- 🟡 `T_lim = min(T_req, torque_limit(rpm), torque_limit_gear(gear), T_prot)`, onde `T_prot` = 50 % de `torque_limit(rpm)` em modo de emergência e +∞ fora dele; `oem_torque_limiter_active` indica o termo vencedor.
- 🟡 `T_ind_des = T_lim + friction_torque(rpm, ect_c)`.
- 🟡 `Δ_base = ignition_optimal(rpm, load) − ign_base(rpm, load)`; `η_base = ignition_efficiency(Δ_base)`.
- 🟡 `load_target` resolve `torque_optimal(rpm, load) · η_base = T_ind_des` por bissecção na coluna interpolada em `rpm` (tolerância 0,01 %, máximo 30 iterações, pré-calculado em `CompiledCalibration` como tabela inversa 16×64 para o hot path).
- 🟡 `V_cyl = displacement_cc / n_cyl · 1e−6` m³; `ρ_ref = 101,325 kPa / (287,05 · 273,15 K) = 1,2922 kg/m³`; `m_ref = ρ_ref · V_cyl`; `m_air_target = load_target / 100 · m_ref`. Exemplo `hatch-20t-gdi`: `V_cyl = 0,000496 m³`, `m_ref = 640,9 mg`.
- 🟡 `p_target = oem_pressure_target(rpm, load_target)`; se `p_target ≥ baro − 5 kPa`, borboleta 100 % e alvo de boost = `p_target`; senão wastegate 0 % e PI de borboleta (`kp = 0,8 %/kPa`, `ki = 4,0 %/(kPa·s)`) sobre o MAP.
- 🟡 `load_actual = air_charge_mg(map, iat, ve) / m_ref · 100`, com a tabela `ve` de série da calibração OEM.
- 🟡 Intervenção: `T_poss = torque_optimal(rpm, load_actual) · η_base`; se `T_poss > 1,02 · T_ind_des`, `η_req = T_ind_des / torque_optimal(rpm, load_actual)`, `Δ_req = ignition_efficiency⁻¹(η_req)` e `ign_cmd = min(ign_base, ignition_optimal − Δ_req)` com `ign_base − ign_cmd ≤ 20°`.
- 🟡 Monitorização de torque: `T_est = T_poss_com_ign_cmd − friction_torque`; se `T_est > 1,10 · torque_limit(rpm)` por 0,5 s ⇒ modo de emergência até a próxima aplicação de calibração.
- 🟡 Tabela de teste (RF-06): `torque_optimal` a 3000 rpm com eixo de carga `(50, 100, 150)` % e valores `(100, 200, 300)` N·m; `T_ind_des = 250` N·m e `η_base = 1,0` ⇒ `load_target = 125,0` %.

### D. Sintomas físicos dos erros de setup (casos obrigatórios)

| Caso | Erro de setup | Equação | Resultado esperado |
|---|---|---|---|
| 🟡 S-01 | PMS declarado 8° abaixo do real | `ign_real = ign_cmd + (tdc_true − tdc_cfg)` | Avanço real +8,0°; com o avanço no limite, knock detectado pelo knock-and-failure-model |
| 🟡 S-02 | Roda 36-1 declarada, real 60-2 | sincronismo exige igualdade de roda | `sync_ok = false`, cortes totais, não arranca |
| 🟡 S-03 | Ordem 1-2-4-3 declarada, real 1-3-4-2 | cilindro com posição divergente recebe faísca fora do PMS | Cilindros 2 e 3 com `spark_cut` e injeção ativa: `pop_event` e perda de torque ≈ 50 % |
| 🟡 S-04 | Erro de PMS de 35° | `abs(erro) > 30°` | Não arranca, `tdc_offset_out_of_range` |
| 🟡 S-05 | MAP real 20–400 kPa declarado 20–250 kPa | `map_read = min_cfg + (p − min_real) · (max_cfg − min_cfg) / (max_real − min_real)` | A 200 kPa reais a ECU lê 128,9 kPa: mistura pobre e overboost real |
| 🟡 S-06 | Bico real 1000 cc/min declarado 1250 cc/min | `λ_real = λ_alvo · Q_cfg / Q_real` (malha aberta, pulso ≫ dead time) | λ alvo 0,85 ⇒ λ real 1,0625 |
| 🟡 S-07 | E27 declarado com E100 no tanque | `λ_real = λ_alvo · AFR_cfg / AFR_real` | λ alvo 0,85 ⇒ λ real 1,247 |
| 🟡 S-08 | Dead time declarado 0,3 ms abaixo do real | `Δm = q_inj · (t_dead_cfg − t_dead_real)` | Em pulso de 2,0 ms, o bico entrega 1,0 ms úteis em vez de 1,3 ms (77 %) ⇒ λ real = λ_alvo / 0,77 ± 2 % |
| 🟡 S-09 | IAT com curva `ntc_b` declarada e real `ntc_a` | `T_read = 1 / (1/T0 + ln(R/R0) / β_cfg)`, `R` calculado com `β_real` | Com `β_a = 3450 K`, `β_b = 3950 K`, `T0 = 298,15 K` e IAT real 60 °C, a ECU lê 55,1 ± 0,5 °C |
| 🟡 S-10 | Wideband real 0,5–1,5 declarada 0,68–1,36 | `λ_read = λ0_cfg + (λ − λ0_real) · (λ5_cfg − λ0_cfg) / (λ5_real − λ0_real)` | λ real 0,85 é lido como 0,918; com alvo 0,85 a malha fechada leva o λ real a 0,75 (trim de +13,3 %, dentro de ±25 %) |

🟡 Nota S-10: o λ lido 0,85 corresponde ao λ real `0,5 + (0,85 − 0,68) · 1,0 / 0,68 = 0,75`, com tolerância ± 2 %.

### E. Assistente de mapa base

- 🟡 Eixos: RPM de 500 a `rev_limit_rpm` com `grid` pontos uniformes; MAP de 20 kPa a `max_map_kpa + 20` kPa com `grid` pontos uniformes (aspirado: até 105 kPa).
- 🟡 VE base (%): `VE = VE_pk · f_rpm · f_map`, com `VE_pk = 85` (turbo e supercharged) ou 90 (aspirado); `f_rpm = 0,80 + 0,20 · (1 − ((rpm − rpm_pk)/rpm_pk)²)` limitado a 0,70..1,00, `rpm_pk = 0,6 · rev_limit_rpm`; `f_map = 0,55 + 0,45 · min(map/100, 1)`. O assistente erra de propósito face à VE física (tipicamente 5 a 15 %), para o usuário afinar.
- 🟡 Lambda alvo: 1,00 com MAP ≤ 70 kPa; interpolação linear até 0,90 a 100 kPa; acima de 100 kPa, 0,82 (E0, E27), 0,80 (Podium) ou 0,78 (E100) a `max_map_kpa`.
- 🟡 Ignição (°BTDC): `adv = 10 + 16 · min(rpm/4000, 1) − 0,12 · max(map − 60, 0) + c_fuel − 1,5 · max(cr − 9,0, 0)`, com `c_fuel` = 0 (E0, E27), +2 (Podium), +3 (E100); limitado a 5..35. Exemplo RF-21 (`cr = 8,5`, E100, 4000 rpm, 200 kPa): `26 − 16,8 + 3 = 12,2°`.
- 🟡 Dead time: copiado da `BaseSetup` para a tabela `inj_dead_time` do ecu-core.
- 🟡 Modo `direct_pulse_ms` (`ft-pro`): `inj_base_ms(rpm, map) = m_fuel / q_inj` calculado pela equação speed-density do ecu-core com o VE base, IAT 30 °C, o lambda alvo e o combustível declarado (sem dead time, que o core soma).
- 🟡 Duty estimado: `estimated_peak_duty_pct = PW(rpm_max, max_map) / (120000 / rpm_max) · 100`; > 85 % gera `INJECTOR_UNDERSIZED`.
- 🟡 Estratégias geradas: `rev_limiter.hard_rpm = protection.rev_limit_rpm`; `failsafe` das regras padrão do ecu-core com os limiares da base; `boost_control.overboost_kpa = protection.overboost_kpa`; `closed_loop.enabled = wideband ≠ null`; `two_step`, `antilag`, `powershift` e `overrun.pops_enabled` desligados.

### F. Jornada do Rodrigo como critério de aceite (E2E de backend, `seed = 42`)

| Passo | Ação | Verificação |
|---|---|---|
| 🟡 1 | Criar sessão `classic-20t-swap` em `oem-stage` | 201, `ecu_state = oem` |
| 🟡 2 | Swap para `ft-pro` com `confirm_snapshot = true` | 200, `awaiting_base_setup`, 6 obrigatórios em `missing`; `POST .../runs` devolve 409 `ECU_SETUP_INCOMPLETE` |
| 🟡 3 | PUT da base pela ficha (60-2, ordem 1-3-4-2, 1000 cc/min, E100, MAP 20–400, wideband padrão) com mapa base | 200, `standalone_ready`, calibração `wizard` aplicada |
| 🟡 4 | Trava de ponto a 10° em marcha lenta | `timing_light_deg` = 10,0 ± 0,1 |
| 🟡 5 | `steady_state_hold` de 16 células e correção do VE até erro de lambda ≤ 3 % | Lambda real dentro de ±3 % do alvo nas 16 células |
| 🟡 6 | Varredura de ignição célula a célula até o MBT sem knock severo | `theta_pmax_deg_atdc` ∈ (12, 18) nas células WOT e 0 eventos de knock severo |
| 🟡 7 | Ativar two-step a 4000 rpm e boost por marcha | Two-step segura 4000 ± 100 rpm; alvo da 2.ª marcha limitado pelo teto |
| 🟡 8 | `multi_pull` de 3 puxadas | `peak_whp_spread_pct` ≤ 2 %, 0 `FailureEvent` |
| 🟡 9 | Comparar com a meta do cenário `standalone-swap` | Potência de pico ≥ meta definida pelo cenário (training-scenarios) |

### G. Conformidade de marcas

- 🟡 Lista de bloqueio (sem distinção de maiúsculas, palavra inteira): "FuelTech", "FTManager", "FT600", "FT550", "MoTeC", "M1 Tune", "Haltech", "Nexus", "NSP", "WinOLS", "Bosch", "Continental", "Motronic", "Simos", "MED17", "MG1".
- 🟡 Sem exceções: o nome exibido do perfil `oem-stage` é "OEM-Stage" (revisão R1), que não contém nenhum termo da lista de bloqueio.
- 🟡 O teste percorre os 4 descritores, todas as mensagens de `ProblemDetail` do pacote e o OpenAPI gerado; qualquer ocorrência fora da exceção falha o CI.

### Referências
- 🟡 `_reversa_sdd/prd.md` (seções 4, 5, 6 e 9), `_reversa_sdd/personas.md` (jornadas de Lucas e Rodrigo).
- 🟡 Specs relacionadas: ecu-core (contratos, `ProfileHooks`, Apêndice A), ecu-tuning-ui (campos do descritor, assistente de 6 passos), engine-physics-core (`SensorReadings`, `ActuatorCommands`, massa injetada), dyno-bench (sessão, puxadas), knock-and-failure-model, training-scenarios, telemetry-datalogger.
- 🟡 Heywood, J. B. "Internal Combustion Engine Fundamentals" (enchimento, eficiência de ignição).

### Histórico de Revisões
| Versão | Data | Autor | Mudanças |
|--------|------|-------|---------|
| 🟡 1.0 | 2026-10-18 | reversa-spec-sdd | Criação inicial |
| 🟡 1.1 | 2026-10-18 | reversa-spec-sdd | Revisão R1 de consistência entre specs (decisões do usuário: knock, nomes de campo, códigos de erro, seq, campos de integração, prefixo /api/v1/, OEM-Stage, benchmark v1) |

---

## Relatório de avaliação (reversa-spec-sdd)

- 🟡 Score final: 100,0/100 (Excelente, pronta para implementação)
- 🟡 Iterações: 1 (scores: 100,0)
- 🟡 Breakdown: Completude 100 %, Testabilidade 100 %, Clareza 100 %, Escopo 100 %, Edge Cases 100 %
- 🟡 Gaps críticos remanescentes: nenhum
- 🟡 Sugestões remanescentes: nenhuma
- 🟡 Revisão R1 (2026-10-18): reavaliado após a revisão de consistência entre specs, score 100,0/100.
