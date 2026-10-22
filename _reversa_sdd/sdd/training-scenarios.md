# Spec: training-scenarios

**Versão:** 1.1
**Status:** Rascunho
**Autor:** reversa-spec-sdd
**Data:** 2026-10-18
**Reviewers:** N/A
**Sprint:** 4 (componente 8, último da ordem aprovada)

---

## 1. Resumo

🟡 O componente `training-scenarios` transforma o simulador numa ferramenta de ensino avaliável: perfis locais de aluno e de instrutor (`PlayerProfile`, só nickname), cenários de treino com objetivos, restrições, dicas progressivas e defeitos ocultos (`Scenario`, `HiddenDefect`), tentativas (`Attempt`) ligadas a sessões do dinamômetro e uma avaliação determinística e objetiva (`Evaluation`) por critérios (`ChallengeCriteria`).
🟡 O componente também troca desafios e tentativas entre estações sem rede por pacotes JSON com SHA-256 do JSON canónico RFC 8785 (`SignedPackage`), deteta adulteração, recalcula a avaliação na estação do instrutor e entrega a UI `frontend/src/features/scenarios/` (lista, briefing, progresso, resultado e painel do instrutor com tabela da turma e export CSV de notas).

---

## 2. Contexto e Motivação

**Problema:**
🟡 O Prof. Marcos dá aulas para turmas de 20 a 50 alunos com um único dinamômetro físico, ou nenhum no EAD. Sem cenários padronizados e critérios objetivos, ele não consegue dar prática avaliável a toda a turma. Lucas e Rodrigo também não têm uma meta clara que diga "o acerto está aprovado e seguro".

**Evidências:**
- 🟡 O PRD (seção 4, "Treino e avaliação") exige os 3 cenários base (Stage 1 OEM, Stage 2 com pops & bangs, swap standalone até o limite seguro de knock), desafios do instrutor com defeitos ocultos e metas com limites, critérios objetivos de aprovação, perfis locais só com nickname e pacotes exportáveis com hash SHA-256 no JSON.
- 🟡 O PRD (seção 3) fixa a métrica "taxa de conclusão dos cenários de treino ≥ 80 %" das sessões iniciadas que terminam aprovadas.
- 🟡 O PRD (seção 8, risco de turma sem rede) define a mitigação: um container Docker local-first por estação/aluno e pacotes com hash SHA-256 para o instrutor avaliar sem rede.
- 🟡 O critério de aceite do Prof. Marcos (PRD seção 9) exige aprovação só por critérios objetivos (meta, margem de knock, integridade de 100 % dos componentes) e export de logs antes vs. depois.

**Por que agora:**
🟡 O Sprint 4 já tem o laço completo: `dyno-bench` e `knock-and-failure-model` (Sprint 2), `telemetry-datalogger` e `dyno-cockpit-ui` (Sprint 3) e `ecu-tuning-ui` (Sprint 4). O `training-scenarios` é o último componente da ordem aprovada e o único que mede a métrica de conclusão do PRD.

---

## 3. Goals (Objetivos)

- 🟡 G-01: A mesma tentativa (mesmos `DynoRun`, `EvaluationTrace` e `ChallengeCriteria`) produz `Evaluation` com `evaluation_sha256` idêntico em 100 % das 20 repetições, na estação do aluno e na do instrutor.
- 🟡 G-02: Os 3 cenários base (`stage1-oem`, `stage2-pops-bangs`, `standalone-swap`) têm cada um uma calibração de solução de referência que é aprovada, e a calibração inicial de cada um é reprovada (teste de aceite no CI).
- 🟡 G-03: A taxa de conclusão dos cenários base é ≥ 80 % (tentativas iniciadas que terminam aprovadas), medida pelos eventos locais `scenario_event`.
- 🟡 G-04: 100 % dos pacotes com 1 byte alterado no `payload` são rejeitados com 422 `PACKAGE_HASH_MISMATCH`, num teste de mutação com 1000 alterações aleatórias semeadas.
- 🟡 G-05: O instrutor importa os pacotes de uma turma de 50 alunos (≤ 8 MiB cada) e vê a tabela de avaliação completa em ≤ 120 s no hardware de referência.

**Métricas de sucesso:**

| Métrica | Baseline atual | Target | Prazo |
|---------|---------------|--------|-------|
| 🟡 Taxa de conclusão dos cenários base | inexistente | ≥ 80 % | 2027-01-18 (3 meses) |
| 🟡 Reprodutibilidade da avaliação por hash | inexistente | 100 % | 2026-11-15 |
| 🟡 Deteção de adulteração do `payload` | inexistente | 100 % | 2026-11-15 |
| 🟡 Tempo de avaliação de uma submissão com sonda de knock | inexistente | ≤ 60 s (P95) | 2026-11-15 |
| 🟡 Tempo de importação de 50 pacotes de tentativa | inexistente | ≤ 120 s | 2026-11-15 |

---

## 4. Non-Goals (Fora do Escopo)

- 🟡 NG-01: O componente não implementa autenticação, contas, senhas nem sincronização de perfis entre estações; a troca de perfil é local e sem senha, e o `role` não é um controle de segurança (PRD e `platform-foundation` NG-01).
- 🟡 NG-02: O componente não autentica a autoria dos pacotes por criptografia no MVP; o SHA-256 deteta corrupção e alteração ingénua, e a autenticação por HMAC ou assinatura fica em aberto (OQ-02).
- 🟡 NG-03: O componente não faz multijogador síncrono, ranking online nem envio de pacotes por rede; a troca é por ficheiro (USB, pasta partilhada ou ambiente de aula).
- 🟡 NG-04: O componente não usa avaliação subjetiva, IA nem correção manual da nota; o instrutor só vê, filtra e exporta resultados calculados pelos critérios.
- 🟡 NG-05: O componente não calcula física, dano, knock nem curvas; consome `DynoRun` (`dyno-bench`), `DamageState` e `FailureEvent` (`knock-and-failure-model`), `DataLog` (`telemetry-datalogger`) e `Calibration` (`ecu-core`).
- 🟡 NG-06: O componente não oferece editor visual de cenários com mapas e tabelas; o instrutor cria desafios por formulário de critérios a partir de uma calibração existente, ou por importação de JSON.
- 🟡 NG-07: O componente não esconde criptograficamente o `HiddenDefect` do aluno; o sigilo é pedagógico (a UI não o mostra), e quem abre o ficheiro JSON consegue lê-lo.

---

## 5. Usuários e Personas

**Usuário primário:** 🟡 Prof. Marcos (instrutor) cria desafios com metas e defeitos ocultos, exporta-os para a turma, importa os pacotes de tentativa de 20 a 50 alunos, vê a tabela de avaliação com evidências e exporta as notas em CSV.

**Usuário secundário:** 🟡 Lucas (aluno OEM) executa `stage1-oem` e `stage2-pops-bangs` e recebe o resultado por critério com evidências. 🟡 Rodrigo (preparador) executa `standalone-swap` e prova repetibilidade térmica e margem de knock ≥ 2°.

**Jornada atual (sem a feature):**
1. 🟡 O instrutor demonstra no único dinamômetro e os alunos só observam.
2. 🟡 O instrutor avalia por impressão, sem critério comum nem evidência ligada a puxadas.
3. 🟡 O aluno não sabe quando um acerto está "aprovado e seguro".

**Jornada futura (com a feature):**
1. 🟡 O usuário cria um perfil local (nickname e papel) e escolhe um cenário na lista.
2. 🟡 O usuário lê o briefing (veículo, combustível, metas e limites), inicia a tentativa e o sistema faz a puxada base automática.
3. 🟡 O usuário calibra na `ecu-tuning-ui`, faz puxadas na `dyno-cockpit-ui` e acompanha o progresso por critério; pode revelar dicas progressivas.
4. 🟡 O usuário submete; o sistema avalia e mostra aprovado/reprovado, pontuação por critério e evidências ligadas a puxadas e logs.
5. 🟡 O aluno exporta o pacote da tentativa; o instrutor importa os pacotes da turma, vê a tabela e exporta o CSV.

---

## 6. Requisitos Funcionais

### 6.1 Requisitos Principais

| ID | Requisito | Prioridade | Critério de Aceite |
|----|-----------|-----------|-------------------|
| 🟡 RF-01 | 🟡 O sistema deve criar `PlayerProfile` via `POST /api/v1/profiles` com `nickname` (regex `^[-_0-9A-Za-z]{3,24}$`, único por estação sem distinção de maiúsculas) e `role` (`student` ou `instructor`), sem nenhum outro campo pessoal. | Must | Request válido devolve 201 com `profile_id` UUID4; nickname repetido com outra caixa devolve 409 `NICKNAME_TAKEN`; nickname com espaço ou `@` devolve 422 `VALIDATION_ERROR`; o 101º perfil devolve 409 `PROFILE_LIMIT_REACHED`. |
| 🟡 RF-02 | 🟡 O usuário deve poder trocar de perfil localmente sem senha, e o sistema deve identificar o perfil ativo pelo cabeçalho `X-Player-Profile-Id` em todos os endpoints de tentativa, cenário de instrutor e pacote. | Must | `GET /api/v1/profiles` devolve todos os perfis da estação; endpoint de tentativa sem o cabeçalho devolve 400 `PLAYER_PROFILE_REQUIRED`; cabeçalho com UUID inexistente devolve 404 `PLAYER_PROFILE_NOT_FOUND`. |
| 🟡 RF-03 | 🟡 O sistema deve restringir ao `role = instructor` a criação de cenários, a importação de pacotes de tentativa, o replay e a leitura do `HiddenDefect` antes da submissão. | Must | Perfil `student` em `POST /api/v1/scenarios` devolve 403 `INSTRUCTOR_ROLE_REQUIRED`; `GET /api/v1/scenarios/{scenario_id}` como aluno devolve `hidden_defect = null` e `has_hidden_defect = true`. |
| 🟡 RF-04 | 🟡 O sistema deve carregar no arranque os cenários base `stage1-oem`, `stage2-pops-bangs` e `standalone-swap` a partir de JSON embutido no pacote, de forma idempotente, marcados `builtin = true` e só leitura. | Must | Dois arranques seguidos mantêm 3 linhas `builtin`; `GET /api/v1/scenarios?kind=base` devolve os 3 IDs; o `scenario_sha256` de cada um é igual ao valor fixado no teste. |
| 🟡 RF-05 | 🟡 O sistema deve permitir ao instrutor criar desafios via `POST /api/v1/scenarios` com veículo, perfil ECU inicial, calibração inicial (de série ou embutida), combustível, ambiente, objetivos, restrições, `ChallengeCriteria`, `HiddenDefect` opcional e até 5 dicas. | Must | Desafio "400 whp com gasolina comum e EGT ≤ 900 °C" no `coupe-30t-i6` devolve 201; `scenario_id` existente devolve 409 `SCENARIO_ALREADY_EXISTS`; `vehicle_id` inexistente devolve 404 `VEHICLE_NOT_FOUND`. |
| 🟡 RF-06 | 🟡 O sistema deve tratar cada `Scenario` como imutável e calcular `scenario_sha256` como SHA-256 do JCS (RFC 8785) do conteúdo avaliável (tudo menos `created_at`, `builtin`, `origin` e estatísticas). | Must | Qualquer `PUT`/`PATCH` em cenário devolve 405; alterar 1 limiar num JSON de cenário muda o `scenario_sha256`; reordenar chaves não o muda. |
| 🟡 RF-07 | 🟡 O usuário deve poder iniciar uma tentativa via `POST /api/v1/scenarios/{scenario_id}/attempts`; o sistema deve clonar a calibração inicial, criar a `SimulationSession` com veículo, perfil, combustível, ambiente, `seed` e falhas físicas do defeito oculto, e executar uma `baseline_pull` automática. | Must | Resposta 201 com `state = preparing`, `session_id` e `calibration_id`; após a puxada base, `state = in_progress` e `baseline_run_id` preenchido; o `content_hash` da calibração clonada é igual ao `initial_calibration.content_hash` do cenário. |
| 🟡 RF-08 | 🟡 O sistema deve converter o `HiddenDefect` em `PhysicsFault` da `engine-physics-core`: `fuel_pump_weak` → `fuel_pump_weak`, `injector_clogged` → `injector_clogged`, `iat_sensor_bias` → `sensor_bias` no canal `iat_c`, `wastegate_stuck` → `wastegate_stuck` (tipo oficial da `engine-physics-core` desde a revisão R1). | Must | Tentativa do desafio com bomba fraca de 90 L/h gera `PhysicsConfig.faults` com 1 item `fuel_pump_weak` e `fuel_pump_max_lph = 90`; a sessão sem defeito tem `faults = []`. |
| 🟡 RF-09 | 🟡 O sistema deve classificar cada `DynoRun` da sessão da tentativa como puxada válida só quando todas as regras de validade da seção 8 forem verdadeiras e gravar o motivo de cada recusa. | Must | Uma puxada `completed` com calibração alterada a meio (dois `calibration_hash`) fica `valid = false` com `invalid_reason = calibration_changed_during_run`; uma `aborted` fica `invalid_reason = run_not_completed`. |
| 🟡 RF-10 | 🟡 O usuário deve poder submeter a tentativa via `POST /api/v1/attempts/{attempt_id}/submit` com `calibration_id`, lista opcional de `run_ids` de evidência e `declared_defect` opcional; o sistema deve congelar a calibração e avaliar em segundo plano. | Must | Resposta 202 com `submission_index` e `evaluation_status = pending`; submissão além de `max_submissions` (padrão 5) devolve 409 `SUBMISSION_LIMIT_REACHED`; tentativa terminal devolve 409 `ATTEMPT_NOT_IN_PROGRESS`. |
| 🟡 RF-11 | 🟡 O sistema deve avaliar cada critério de `ChallengeCriteria` de forma determinística a partir só de `RunSummary`, `EvaluationTrace`, `DamageState` final das puxadas, calibração congelada e resultado da sonda de knock, com as fórmulas da seção 8. | Must | A mesma entrada gera o mesmo `evaluation_sha256` em 20 repetições; nenhum `time.time()`, `random` ou leitura de relógio entra no cálculo (teste com relógio congelado e relógio avançado dá o mesmo hash). |
| 🟡 RF-12 | 🟡 O sistema deve devolver `Evaluation` via `GET /api/v1/attempts/{attempt_id}/evaluation` com `passed`, `total_score` 0–100, um `CriterionResult` por critério (medido, limiar, comparador, aprovado, pontuação, peso) e evidências ligadas a `run_id`, `log_id`, canal, `t_sim_s` e rpm. | Must | Para uma puxada com EGT máxima 962 °C a 6100 rpm e limite 950 °C, o critério `max_egt_c` tem `passed = false`, `measured = 962.0` e 1 evidência com `channel = egt_collector_c` e `rpm = 6100`. |
| 🟡 RF-13 | 🟡 O sistema deve aprovar a submissão só quando todos os critérios com `mandatory = true` passarem; a pontuação total não decide a aprovação. | Must | Submissão com 6 critérios aprovados e 1 obrigatório reprovado tem `passed = false` mesmo com `total_score` = 95,0. |
| 🟡 RF-14 | 🟡 O sistema deve medir a margem de knock por sonda determinística: repetir sem UI a primeira puxada de evidência com a mesma `seed`, avanço somado de `min_knock_margin_deg` em todos os cilindros, controle de knock em malha aberta e `damage_enabled = false`, e aprovar se nenhum ciclo tiver knock. | Must | Calibração de referência do `standalone-swap` passa com margem 2°; a mesma calibração com +3° em `ignition_base` falha o critério com evidência do primeiro ciclo com knock (cilindro, rpm, `t_sim_s`). |
| 🟡 RF-15 | 🟡 O sistema deve oferecer dicas progressivas com regras de desbloqueio (`after_failed_submissions`, `after_sim_time_s`, `after_event`) e revelar a próxima via `POST /api/v1/attempts/{attempt_id}/hints`, gravando cada revelação. | Should | Dica 2 com `after_failed_submissions = 1` devolve 409 `HINT_LOCKED` antes da 1ª reprovação e 200 depois; após a última dica, 409 `HINTS_EXHAUSTED`; `hints_revealed` aparece na `Evaluation` sem alterar `passed`. |
| 🟡 RF-16 | 🟡 O sistema deve registar localmente os eventos `attempt_started`, `baseline_completed`, `run_classified`, `hint_revealed`, `attempt_submitted`, `attempt_passed`, `attempt_failed`, `attempt_abandoned` e `package_exported` na tabela `scenario_event`. | Must | Uma tentativa aprovada na 2ª submissão gera exatamente 1 `attempt_started`, 2 `attempt_submitted`, 1 `attempt_failed` e 1 `attempt_passed`; nenhum evento contém `nickname`. |
| 🟡 RF-17 | 🟡 O sistema deve calcular a taxa de conclusão por cenário via `GET /api/v1/scenarios/{scenario_id}/stats` como `100 · tentativas com attempt_passed / tentativas com attempt_started`, com filtro de intervalo de datas. | Must | Com 10 tentativas iniciadas e 8 aprovadas, a resposta tem `completion_rate_pct = 80.0`, `started = 10` e `passed = 8`. |
| 🟡 RF-18 | 🟡 O usuário deve poder exportar um desafio (`kind = challenge`) ou uma tentativa (`kind = attempt`) via `POST /api/v1/packages/export` como `SignedPackage` com `sha256` = SHA-256 hex do JCS de `{format_version, kind, payload}`. | Must | O ficheiro exportado tem `sha256` igual ao recálculo independente com a biblioteca `rfc8785`; o nome segue `simremap-<kind>-<id>-<8 primeiros hex>.simremap.json`. |
| 🟡 RF-19 | 🟡 O sistema deve importar pacotes via `POST /api/v1/packages/import`, recalcular o hash e rejeitar com `ProblemDetail` e `code` estável qualquer pacote com hash inválido, formato superior ao suportado, schema inválido ou JSON não canonicalizável. | Must | Pacote com 1 dígito alterado num limiar devolve 422 `PACKAGE_HASH_MISMATCH`; `format_version = 2` devolve 422 `PACKAGE_FORMAT_UNSUPPORTED`; ficheiro truncado devolve 422 `PACKAGE_MALFORMED`; nada é gravado em nenhum dos três casos. |
| 🟡 RF-20 | 🟡 O sistema deve, ao importar um pacote de tentativa na estação do instrutor, verificar que o `scenario_sha256` do pacote é igual ao do cenário local e recalcular a avaliação a partir das evidências embutidas. | Must | Pacote cujo cenário embutido teve o limite de EGT mudado de 900 para 990 °C (com hash do pacote recalculado) devolve 409 `SCENARIO_VERSION_MISMATCH`; avaliação declarada diferente da recalculada grava `evaluation_mismatch = true` e usa a recalculada. |
| 🟡 RF-21 | 🟡 O sistema deve tornar a importação idempotente pela `sha256` do pacote. | Must | Importar o mesmo ficheiro 2 vezes devolve 201 e depois 200 com `already_imported = true`; a tabela da turma mantém 1 linha. |
| 🟡 RF-22 | 🟡 O usuário com papel de instrutor deve poder pedir replay de uma tentativa importada via `POST /api/v1/attempts/{attempt_id}/replay`, que re-executa cada puxada de evidência sem UI e compara o `curve_sha256`. | Should | Tentativa honesta fica `replay_status = verified`; tentativa com curva editada fica `replay_status = mismatch` com o `run_id` divergente; `producer.app_version` diferente do local devolve 409 `REPLAY_VERSION_INCOMPATIBLE`. |
| 🟡 RF-23 | 🟡 O sistema deve expor `GET /api/v1/attempts` com filtros `scenario_id`, `origin` (`local`, `imported`) e `profile_id`, paginação por cursor (padrão 50, máximo 200) e a última avaliação de cada tentativa. | Must | Com 50 tentativas importadas, `GET /api/v1/attempts?origin=imported&scenario_id=x&limit=50` devolve 50 itens em < 300 ms (P95) e `next_cursor = null`. |
| 🟡 RF-24 | 🟡 O sistema deve apresentar a UI `frontend/src/features/scenarios/` com seletor de perfil, lista de cenários, briefing, painel de progresso por critério, painel de dicas e resultado com evidências clicáveis. | Must | Teste Playwright: criar perfil, abrir `stage1-oem`, iniciar, ver a puxada base no progresso, submeter e ver o resultado por critério em ≤ 5 cliques após o briefing. |
| 🟡 RF-25 | 🟡 O sistema deve apresentar o painel do instrutor com importação múltipla de 20 a 50 ficheiros (até 2 uploads em paralelo), estado por ficheiro com o `code` de recusa, tabela de avaliação ordenável e filtrável, e export CSV de notas gerado no navegador. | Must | Teste com 50 ficheiros (2 adulterados) mostra 48 importados e 2 recusados com `PACKAGE_HASH_MISMATCH`; o CSV tem 1 cabeçalho + 48 linhas e abre sem erro como CSV com separador `;`. |
| 🟡 RF-26 | 🟡 O sistema deve proteger o CSV contra injeção de fórmulas, prefixando com `'` toda célula que comece por `=`, `+`, `-`, `@`, tabulação ou retorno de carro. | Must | Um `scenario_title` igual a `=HYPERLINK(1)` sai no CSV como `'=HYPERLINK(1)`. |
| 🟡 RF-27 | 🟡 O sistema deve marcar a tentativa como `abandoned` quando o usuário iniciar nova tentativa do mesmo cenário com o mesmo perfil ou pedir abandono, e encerrar a sessão do dinamômetro associada. | Should | Nova tentativa do mesmo cenário devolve 201 e a anterior fica `abandoned` com evento `attempt_abandoned`; a sessão anterior recebe `DELETE` e devolve 404 depois. |

### 6.2 Fluxo Principal (Happy Path)

1. 🟡 O usuário (Lucas) cria o perfil `lucas_turbo` com `role = student`; a UI guarda o `profile_id` em `localStorage` (`simremap.activeProfileId`) e envia `X-Player-Profile-Id` em cada pedido.
2. 🟡 O usuário abre `stage1-oem` na lista; o sistema mostra o briefing: `hatch-20t-gdi`, perfil `oem-stage`, gasolina comum E27, meta +40 whp sobre a puxada base, knock retard ≤ 3°, EGT pré-turbina ≤ 950 °C, integridade 100 %, 2 puxadas válidas com dispersão ≤ 3 %.
3. 🟡 O usuário clica "Iniciar"; o sistema cria o `Attempt` (`preparing`), clona a calibração de série, cria a sessão no `dyno-bench` e executa `baseline_pull` 2000 → 6300 rpm em 4ª.
4. 🟡 O sistema grava `baseline_run_id` e `baseline_peak_whp` (≈ 220 whp) e passa a tentativa a `in_progress`.
5. 🟡 O usuário edita boost e avanço na `ecu-tuning-ui`, faz `sweep_pull` na `dyno-cockpit-ui` e o sistema classifica cada puxada (válida ou não, com motivo) no painel de progresso.
6. 🟡 O painel de progresso mostra os valores provisórios por critério (ex.: Δwhp +43,2, EGT máx. 938 °C, knock retard máx. 1,5°) com estado "cumpre" ou "não cumpre".
7. 🟡 O usuário submete com a calibração atual; o sistema congela a versão, avalia em ≤ 5 s (sem sonda neste cenário) e grava `Evaluation` com `passed = true` e `total_score = 100.0`.
8. 🟡 O usuário vê o resultado com evidências clicáveis (abrem a puxada na cockpit e o log no `t_sim_s` indicado) e exporta o pacote da tentativa.
9. 🟡 O Prof. Marcos importa o pacote no painel do instrutor; o sistema valida o hash, confere o `scenario_sha256`, recalcula a avaliação e mostra a linha na tabela da turma.

### 6.3 Fluxos Alternativos

**Fluxo Alternativo A — Reprovação e dica (Lucas):**
1. 🟡 O usuário submete com EGT máxima de 962 °C.
2. 🟡 O sistema reprova `max_egt_c` com evidência e desbloqueia a dica com `after_failed_submissions = 1` ("Enriqueça o lambda alvo acima de 5000 rpm").
3. 🟡 O usuário revela a dica, corrige e submete de novo; a 2ª submissão é aprovada.

**Fluxo Alternativo B — Quebra durante a tentativa:**
1. 🟡 Uma puxada termina `engine_failed`; o sistema classifica-a `invalid_reason = engine_failed` e mostra o link do laudo forense.
2. 🟡 O usuário restaura o motor (`POST /api/v1/sessions/{session_id}/engine/restore`) e continua; a contagem `engine_restores` sobe e fica visível na avaliação, sem reprovar por si.

**Fluxo Alternativo C — Desafio com defeito oculto (Prof. Marcos):**
1. 🟡 O instrutor cria `challenge-bomba-fraca` (hatch, +40 whp, `HiddenDefect` `fuel_pump_weak` 90 L/h, `require_defect_diagnosis = true`) e exporta o pacote `challenge`.
2. 🟡 O aluno importa o pacote, inicia a tentativa e vê lambda a empobrecer acima de 5000 rpm no log.
3. 🟡 O aluno submete com `declared_defect = fuel_pump_weak`; o critério `defect_diagnosis` passa e a avaliação revela o defeito ao aluno.

**Fluxo Alternativo D — Pacote adulterado:**
1. 🟡 O instrutor importa um ficheiro cujo `payload` foi editado à mão.
2. 🟡 O sistema recalcula o JCS, obtém hash diferente e devolve 422 `PACKAGE_HASH_MISMATCH` com `expected_sha256` e `actual_sha256` no `ProblemDetail`; nada é gravado.

**Fluxo Alternativo E — Swap standalone com sonda de knock (Rodrigo):**
1. 🟡 O usuário troca para `ft-pro` via `POST /api/v1/sessions/{session_id}/ecu/swap`, configura a base e mapeia VE, lambda e ignição.
2. 🟡 O usuário executa `multi_pull` com 3 puxadas e submete.
3. 🟡 O sistema executa a sonda de knock com +2° e aprova `min_knock_margin_deg`; a avaliação termina em ≤ 60 s.

---

## 7. Requisitos Não-Funcionais

| ID | Requisito | Valor alvo | Observação |
|----|-----------|-----------|------------|
| 🟡 RNF-01 | 🟡 Tempo de avaliação | ≤ 5 s (P95) sem sonda com até 10 puxadas de evidência; ≤ 60 s (P95) com sonda | 🟡 Hardware de referência; a sonda corre no `SimWorkerHost` sem UI e sem esperar o tempo real. |
| 🟡 RNF-02 | 🟡 Determinismo da avaliação | `evaluation_sha256` idêntico em 100 % das repetições e entre estações com a mesma imagem | 🟡 Arredondamentos fixos (seção 8) e cálculo sem relógio. |
| 🟡 RNF-03 | 🟡 Importação de turma | ≤ 2,4 s por pacote de 8 MiB (P95), ≤ 120 s para 50 pacotes com 2 uploads paralelos | 🟡 Validação de hash em streaming não é exigida; o pacote cabe em memória. |
| 🟡 RNF-04 | 🟡 Tamanho do pacote | Pacote de tentativa ≤ 8 MiB com `EvaluationTrace` a 100 Hz; ≤ 64 MiB com `DataLog` completo opcional | 🟡 Rota de importação com `body_limit(64 MiB)` (`platform-foundation` RF-23). |
| 🟡 RNF-05 | 🟡 Latência de API | P95 < 150 ms em `GET /api/v1/scenarios`, `GET /api/v1/attempts/{attempt_id}` e `GET /api/v1/attempts/{attempt_id}/evaluation` | 🟡 SQLite local. |
| 🟡 RNF-06 | 🟡 UI | Tabela da turma com 50 linhas e 12 colunas ordena em ≤ 100 ms; rota `/scenarios` interativa em ≤ 2,0 s | 🟡 Chromium ≥ 120 e Firefox ≥ 120, ≥ 1366×768. |
| 🟡 RNF-07 | 🟡 Acessibilidade | WCAG 2.1 AA, 0 violações axe-core A/AA nas 6 telas | 🟡 Aprovado/reprovado com texto e ícone, nunca só cor. |
| 🟡 RNF-08 | 🟡 Qualidade | Cobertura ≥ 85 % em `simremap.scenarios`, ≥ 80 % em `features/scenarios/`; `mypy --strict`, `ruff` e `bandit` sem erros | 🟡 Convenção do projeto. |

---

## 8. Design e Interface

**Componentes afetados:**
- 🟡 `backend/src/simremap/scenarios/` (novo): `contracts.py` (Pydantic), `profiles.py`, `catalog.py` (carga dos cenários embutidos), `builtin/*.json` (3 cenários base), `attempts.py` (ciclo de vida), `validity.py` (classificação de puxadas), `evaluator.py` (critérios e pontuação), `probe.py` (sonda de knock), `trace.py` (`EvaluationTrace`), `packages.py` (JCS, hash, export/import), `replay.py`, `events.py`, `repository.py`.
- 🟡 `backend/src/simremap/api/routers/profiles.py`, `scenarios.py`, `attempts.py`, `packages.py` (novos).
- 🟡 `backend/src/simremap/db/models/scenarios.py` + migração Alembic `NNNN_scenarios_base`.
- 🟡 `frontend/src/features/scenarios/` (novo): `ProfilePicker`, `ProfileCreateDialog`, `ScenarioList`, `ScenarioBriefing`, `AttemptProgressPanel` (painel lateral sobre a cockpit), `HintPanel`, `EvaluationResult`, `EvidenceLink`, `InstructorPanel`, `ChallengeForm`, `PackageImportQueue`, `ClassGradeTable`, `gradesCsv.ts` (função pura).
- 🟡 Dependências novas: biblioteca `rfc8785` (PyPI, Apache-2.0, open-source) para JCS no backend; no frontend nenhum hash é calculado.

**Ciclo de vida da tentativa:**

| Estado | Entrada | Saída permitida | Regra de saída |
|--------|---------|-----------------|----------------|
| 🟡 `preparing` | `POST .../attempts` aceite | `in_progress`, `failed_to_start` | Puxada base `completed` ⇒ `in_progress`; base `aborted`/`engine_failed` ou timeout de 120 s ⇒ `failed_to_start`. |
| 🟡 `in_progress` | Base concluída ou avaliação reprovada com submissões restantes | `evaluating`, `abandoned`, `expired` | Submit ⇒ `evaluating`; `time_limit_min` atingido (relógio de parede, fora do cálculo) ⇒ `expired`. |
| 🟡 `evaluating` | Submit aceite | `passed`, `in_progress`, `failed_final` | Aprovado ⇒ `passed`; reprovado com submissões restantes ⇒ `in_progress`; reprovado na última ⇒ `failed_final`. |
| 🟡 `passed`, `failed_final`, `abandoned`, `expired`, `failed_to_start` | Ver acima | nenhuma | Terminais; a sessão do dinamômetro recebe `DELETE`. |

**Regras de validade de uma puxada (todas obrigatórias):**
- 🟡 V-01: `DynoRun.state = completed` (senão `run_not_completed` ou `engine_failed`).
- 🟡 V-02: `run_type` ∈ `constraints.allowed_run_types` (padrão `sweep_pull`, `baseline_pull`, `multi_pull`; puxadas de `multi_pull` contam uma a uma).
- 🟡 V-03: um único `calibration_hash` durante toda a puxada, igual ao `content_hash` da calibração submetida (senão `calibration_changed_during_run` ou `calibration_not_submitted`).
- 🟡 V-04: combustível, ambiente, `correction_standard` e `seed` da sessão iguais aos do cenário e da tentativa.
- 🟡 V-05: `damage_enabled = true` e falhas físicas da sessão iguais às derivadas do `HiddenDefect`.
- 🟡 V-06: `end_rpm` ≥ `criteria.min_end_rpm` (padrão: `rev_limit_rpm − 500` do veículo) e marcha = `constraints.gear` (padrão 4ª).
- 🟡 V-07: `profile_id` da sessão no momento da puxada ∈ `constraints.allowed_final_profiles` (vazio = qualquer).
- 🟡 Puxadas de evidência = `run_ids` do submit (padrão: as últimas `required_valid_pulls` puxadas válidas com o hash submetido). Puxadas inválidas na lista são ignoradas e listadas em `ignored_runs`.

**Medidas usadas pelo avaliador (de cada puxada de evidência `r`):**
- 🟡 `whp_r = RunSummary.peak_whp` (corrigido pela norma do cenário), arredondado a 0,1 whp; meta usa `min_r whp_r` (todas as puxadas têm de cumprir).
- 🟡 `torque_r = RunSummary.peak_torque_engine_nm`, arredondado a 0,1 N·m; meta usa `min_r torque_r`.
- 🟡 `Δwhp = min_r whp_r − baseline_peak_whp`.
- 🟡 `knock_retard_max = max_r max_t knock_retard_max_deg(t)`, arredondado a 0,01°.
- 🟡 `egt_max = max_r max_t egt_collector_c(t)` em toda a puxada (arranque, `running` e `coastdown`), arredondado a 0,1 °C.
- 🟡 `egt_overrun_max = max` de `egt_collector_c` nas amostras com `overrun_active = true`.
- 🟡 `pops_r = Σ pop_events` nas amostras com `overrun_active = true` do `coastdown` da puxada `r`.
- 🟡 `lambda_wot_max` e `lambda_wot_min`: máximo e mínimo de `lambda_measured` nas amostras com `pedal_pct ≥ 90` e `rpm ≥ criteria.lambda_window_min_rpm` (padrão 3000).
- 🟡 `integrity = min_r min_c ComponentHealth.health_pct` no fim de cada puxada; passa só com 100,0 e 0 `FailureEvent` nas puxadas de evidência.
- 🟡 `spread_pct = 100 · (max_r whp_r − min_r whp_r) / mean_r whp_r`, arredondado a 0,01 % (mesma fórmula do `dyno-bench`).
- 🟡 `n_valid` = número de puxadas de evidência válidas.

**Pontuação por critério (0–100, arredondada a 0,1 com `ROUND_HALF_EVEN` via `Decimal`):**
- 🟡 Comparador `ge` (meta mínima T): `s = 100` se `m ≥ T`, senão `s = max(0, 100 · m / T)`.
- 🟡 Comparador `le` (limite máximo T, banda B): `s = 100` se `m ≤ T`, senão `s = max(0, 100 · (1 − (m − T) / B))`; bandas padrão: EGT 50 °C, knock retard 3°, dispersão 3 %, lambda 0,05.
- 🟡 Booleano (diagnóstico, perfil final, tabelas bloqueadas): `s = 100` ou `0`.
- 🟡 Integridade: `s = integrity` (ex.: 92,5), aprovado só com 100,0.
- 🟡 Contagem de puxadas: `s = 100 · min(1, n_valid / N)`.
- 🟡 Total: `total_score = Σ w_i · s_i / Σ w_i` (pesos padrão 1,0; meta de potência 2,0).

**Sonda de margem de knock (RF-14):**
- 🟡 Entrada: `DynoRunRequest` da primeira puxada de evidência, mesma `seed`, `sim_hz`, ambiente, falhas e calibração congelada.
- 🟡 Overrides só da sonda (`ProbeOverrides`, contrato oficial do `dyno-bench` desde a revisão R1): `ignition_offset_deg = min_knock_margin_deg` somado a `ActuatorCommands.ignition_advance_deg` depois da arbitragem da ECU; `knock_control_open_loop = true` (retardo de knock fixo em 0°); `damage_enabled = false`.
- 🟡 Aprovação: 0 ciclos com knock (integral de Livengood-Wu `∫ dt/τ < 1` em todos os ciclos, classe `none` do `knock-and-failure-model`) entre `start_rpm` e `end_rpm`.
- 🟡 Evidência na falha: primeiro ciclo com knock (`cylinder`, `rpm`, `t_sim_s`, intensidade).

**Defeitos ocultos (mapeamento para `PhysicsFault`):**

| `HiddenDefect.kind` | Parâmetros e faixa | `PhysicsFault` gerado | Sintoma esperado |
|---|---|---|---|
| 🟡 `fuel_pump_weak` | `fuel_pump_max_lph` 60–250 | `kind = fuel_pump_weak` | Queda de `fuel_pressure_kpa` e lambda pobre em alta carga. |
| 🟡 `injector_clogged` | `cylinder` 1–8, `injector_flow_factor` 0,50–0,95 | `kind = injector_clogged` | EGT e lambda do cilindro afetado acima dos restantes. |
| 🟡 `iat_sensor_bias` | `sensor_bias` −30 a +30 °C | `kind = sensor_bias`, `sensor_channel = iat_c` | Correções de ignição e combustível por IAT erradas. |
| 🟡 `wastegate_stuck` | `stuck_position_pct` 0–100 | `kind = wastegate_stuck` (oficial, revisão R1) | Boost que não responde ao duty (sobreboost com 0 %, falta de boost com 100 %). |

**Cenários base (valores embutidos em `builtin/*.json`):**

| Campo | `stage1-oem` | `stage2-pops-bangs` | `standalone-swap` |
|---|---|---|---|
| 🟡 Veículo / perfil inicial | `hatch-20t-gdi` / `oem-stage` | `hatch-20t-gdi` / `oem-stage` | `classic-20t-swap` / `oem-stage` |
| 🟡 Combustível | gasolina comum E27 | gasolina comum E27 | etanol E100 |
| 🟡 Meta de potência | Δwhp ≥ +40 | Δwhp ≥ +65 | whp ≥ 300 (⚠️ ABERTO: OQ-06) |
| 🟡 Knock | retard máx. ≤ 3° | retard máx. ≤ 3° | margem ≥ 2° pela sonda |
| 🟡 EGT pré-turbina | ≤ 950 °C | ≤ 950 °C e ≤ 950 °C no overrun | ≤ 950 °C |
| 🟡 Lambda em plena carga (≥ 3000 rpm) | 0,75 a 0,90 | 0,75 a 0,90 | 0,75 a 0,88 |
| 🟡 Pops & bangs | não exigido | ≥ 5 `pop_events` no coastdown de cada puxada | não exigido |
| 🟡 Integridade | 100 % | 100 % | 100 % |
| 🟡 Puxadas válidas / dispersão | 2 / ≤ 3 % | 2 / ≤ 3 % | 3 em `multi_pull` / ≤ 3 % |
| 🟡 Perfil final permitido | `oem-stage` | `oem-stage` | `ft-pro`, `m1-race`, `ht-elite` |
| 🟡 Dicas | 3 | 4 | 5 |

🟡 Exemplo de desafio do instrutor: `challenge-400whp-e27` no `coupe-30t-i6`, gasolina comum, `min_whp = 400`, `max_egt_c = 900`, knock retard ≤ 3°, integridade 100 %, 3 puxadas válidas com dispersão ≤ 3 %.

**Pacote `SignedPackage`:**
- 🟡 `sha256 = hex(SHA-256(JCS({"format_version": v, "kind": k, "payload": p})))`, com JCS conforme RFC 8785 (ordenação de chaves por unidades UTF-16, números no formato ECMAScript, sem espaços).
- 🟡 Valores `NaN` ou `Infinity` tornam o pacote não canonicalizável: export devolve 422 `PACKAGE_NOT_CANONICALIZABLE`; import idem.
- 🟡 Payload `challenge`: `Scenario` completo (inclui `hidden_defect`) e calibração inicial embutida.
- 🟡 Payload `attempt`: `Scenario` com `scenario_sha256`, `Attempt`, calibração congelada completa, `DynoRun` das puxadas base e de evidência (resumo + curva bruta + `curve_sha256`), `EvaluationTrace` por puxada, resultado da sonda, `Evaluation` declarada e, se `include_full_logs = true`, os `DataLog` completos.
- 🟡 `producer`: `app_version`, `install_id` (UUID4 local de `app_meta`, sem relação com pessoa) e `nickname`.

**`EvaluationTrace` (100 Hz, agregação fixa por janela de 10 ms de `t_sim_s`):** 🟡 colunas `t_sim_s` (início da janela), `rpm` (média), `pedal_pct` (média), `egt_collector_c` (máx.), `lambda_measured` (mín. e máx.), `knock_retard_max_deg` (máx.), `pop_events` (soma), `overrun_active` (OU lógico), `health_min_pct` (mín.), `phase` (`arming`, `running`, `coastdown`). 🟡 O avaliador usa só esta tabela e o `RunSummary`, o que garante o mesmo resultado no aluno e no instrutor.

**Endpoints REST (caminhos completos sob o prefixo `/api/v1/`, erros `application/problem+json` com `code`):**

| Método e caminho | Request | Resposta | Erros |
|------------------|---------|----------|-------|
| 🟡 `GET /api/v1/profiles` | — | 200 `list[ PlayerProfile ]` | — |
| 🟡 `POST /api/v1/profiles` | `PlayerProfileCreate` | 201 `PlayerProfile` | 409 `NICKNAME_TAKEN`, 409 `PROFILE_LIMIT_REACHED`, 422 `VALIDATION_ERROR` |
| 🟡 `GET /api/v1/scenarios?kind=` | query `kind` (`base` ou `challenge`, opcional) | 200 `list[ ScenarioSummary ]` | 422 `VALIDATION_ERROR` |
| 🟡 `GET /api/v1/scenarios/{scenario_id}` | cabeçalho `X-Player-Profile-Id` opcional | 200 `Scenario` (defeito redigido para aluno) | 404 `SCENARIO_NOT_FOUND` |
| 🟡 `POST /api/v1/scenarios` | `ScenarioCreate` | 201 `Scenario` | 403 `INSTRUCTOR_ROLE_REQUIRED`, 404 `VEHICLE_NOT_FOUND`, 404 `CALIBRATION_NOT_FOUND`, 409 `SCENARIO_ALREADY_EXISTS`, 422 `SCENARIO_INVALID` |
| 🟡 `GET /api/v1/scenarios/{scenario_id}/stats?from=&to=` | datas ISO 8601 | 200 `ScenarioStats` | 404 `SCENARIO_NOT_FOUND` |
| 🟡 `POST /api/v1/scenarios/{scenario_id}/attempts` | corpo vazio | 201 `Attempt` (`preparing`) | 400 `PLAYER_PROFILE_REQUIRED`, 404 `SCENARIO_NOT_FOUND`, 409 `SIM_CAPACITY_EXCEEDED` (do `dyno-bench`), 422 `SCENARIO_CALIBRATION_HASH_MISMATCH` |
| 🟡 `GET /api/v1/attempts?scenario_id=&origin=&profile_id=&cursor=&limit=` | — | 200 `AttemptPage` | 422 `VALIDATION_ERROR` |
| 🟡 `GET /api/v1/attempts/{attempt_id}` | — | 200 `Attempt` (com `runs` classificadas e progresso) | 404 `ATTEMPT_NOT_FOUND` |
| 🟡 `POST /api/v1/attempts/{attempt_id}/hints` | corpo vazio | 200 `HintReveal` | 403 `ATTEMPT_NOT_OWNED`, 409 `HINT_LOCKED`, 409 `HINTS_EXHAUSTED` |
| 🟡 `POST /api/v1/attempts/{attempt_id}/abandon` | corpo vazio | 200 `Attempt` | 403 `ATTEMPT_NOT_OWNED`, 409 `ATTEMPT_NOT_IN_PROGRESS` |
| 🟡 `POST /api/v1/attempts/{attempt_id}/submit` | `SubmitRequest` | 202 `SubmitAccepted` | 403 `ATTEMPT_NOT_OWNED`, 409 `ATTEMPT_NOT_IN_PROGRESS`, 409 `SUBMISSION_LIMIT_REACHED`, 409 `RUN_IN_PROGRESS`, 422 `CALIBRATION_NOT_IN_ATTEMPT` |
| 🟡 `GET /api/v1/attempts/{attempt_id}/evaluation?submission=` | — | 200 `Evaluation` (ou `status = pending`) | 404 `ATTEMPT_NOT_FOUND`, 404 `EVALUATION_NOT_FOUND` |
| 🟡 `POST /api/v1/attempts/{attempt_id}/replay` | corpo vazio | 202 `ReplayAccepted` | 403 `INSTRUCTOR_ROLE_REQUIRED`, 409 `REPLAY_VERSION_INCOMPATIBLE`, 409 `SIM_CAPACITY_EXCEEDED` |
| 🟡 `POST /api/v1/packages/export` | `PackageExportRequest` | 200 `SignedPackage` com `Content-Disposition: attachment` | 404 `SCENARIO_NOT_FOUND`, 404 `ATTEMPT_NOT_FOUND`, 409 `ATTEMPT_NOT_EVALUATED`, 422 `PACKAGE_NOT_CANONICALIZABLE` |
| 🟡 `POST /api/v1/packages/import` | `SignedPackage` (JSON, ≤ 64 MiB) | 201 `PackageImportResult` (200 se já importado) | 403 `INSTRUCTOR_ROLE_REQUIRED` (kind `attempt`), 409 `SCENARIO_VERSION_MISMATCH`, 404 `SCENARIO_NOT_FOUND`, 413 `PAYLOAD_TOO_LARGE`, 422 `PACKAGE_HASH_MISMATCH`, 422 `PACKAGE_FORMAT_UNSUPPORTED`, 422 `PACKAGE_MALFORMED`, 422 `PACKAGE_SCHEMA_INVALID`, 422 `PACKAGE_NOT_CANONICALIZABLE` |

**Telas da UI (`frontend/src/features/scenarios/`, rotas do SPA):**
- 🟡 `/profiles`: `ProfilePicker` com cartões de nickname e papel; botão "Novo perfil"; troca imediata sem senha; o instrutor tem um selo "Instrutor".
- 🟡 `/scenarios`: `ScenarioList` com filtro base/desafio, veículo, combustível, selo "defeito oculto" (sem revelar qual) e a última avaliação do perfil ativo.
- 🟡 `/scenarios/:scenarioId`: `ScenarioBriefing` com objetivos, tabela de critérios (limiar e unidade), restrições, combustível, ambiente e botão "Iniciar tentativa".
- 🟡 `AttemptProgressPanel` (painel lateral de 320 px sobre `/sessions/:sessionId/dyno` e `/sessions/:sessionId/ecu`): checklist por critério com valor provisório, puxadas classificadas com motivo de invalidade, contador de submissões e botão "Submeter".
- 🟡 `/attempts/:attemptId/result`: `EvaluationResult` com selo aprovado/reprovado, `total_score`, tabela por critério e `EvidenceLink` (abre a puxada na cockpit e o log no `t_sim_s`), defeito revelado e botão "Exportar pacote".
- 🟡 `/instructor`: `InstructorPanel` com abas "Desafios" (`ChallengeForm`, export) e "Turma" (`PackageImportQueue` com arrastar-e-largar de até 50 ficheiros, estado por ficheiro, `ClassGradeTable` ordenável por qualquer coluna e filtrável por cenário e aprovado, botão "Exportar CSV").
- 🟡 Estado vazio: lista sem tentativas mostra "Ainda sem tentativas"; turma sem pacotes mostra a área de importação.
- 🟡 Estado de carregamento: esqueleto de cartões; avaliação `pending` mostra barra de progresso indeterminada e o texto "Sonda de knock em execução" quando aplicável.
- 🟡 Estado de erro: `ProblemDetail` com `title`, `detail` e `code`; na fila de importação cada ficheiro recusado mostra o `code`.
- 🟡 Estado de sucesso: selo verde com ícone e texto "Aprovado"; reprovado com ícone e texto "Reprovado".

**CSV de notas (`gradesCsv.ts`):** 🟡 UTF-8 sem BOM, separador `;`, vírgula decimal (padrão pt-BR) com opção RFC 4180 (`,` e ponto decimal); colunas fixas `nickname;station;scenario_id;attempt_id;submission;passed;total_score;evaluation_mismatch;replay_status;package_sha256;imported_at`, seguidas de uma coluna `score_<criterion_id>` por critério do cenário filtrado; uma linha por tentativa importada (última submissão).

---

## 9. Modelo de Dados

**Contratos Pydantic v2 (`simremap.scenarios.contracts`):**

```python
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Nickname = Annotated[ str, Field(pattern=r"^[-_0-9A-Za-z]{3,24}$") ]
Slug = Annotated[ str, Field(pattern=r"^[0-9a-z][-0-9a-z]{2,63}$") ]
Sha256Hex = Annotated[ str, Field(pattern=r"^[0-9a-f]{64}$") ]

class Role(StrEnum):
    STUDENT = "student"; INSTRUCTOR = "instructor"

class PlayerProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nickname: Nickname
    role: Role = Role.STUDENT

class PlayerProfile(PlayerProfileCreate):
    profile_id: str                        # UUID4
    created_at: datetime                   # UTC, relógio de parede

class DefectKind(StrEnum):
    FUEL_PUMP_WEAK = "fuel_pump_weak"; INJECTOR_CLOGGED = "injector_clogged"
    IAT_SENSOR_BIAS = "iat_sensor_bias"; WASTEGATE_STUCK = "wastegate_stuck"

class HiddenDefect(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: DefectKind
    fuel_pump_max_lph: float | None = Field(None, ge=60, le=250)
    cylinder: int | None = Field(None, ge=1, le=8)
    injector_flow_factor: float | None = Field(None, ge=0.50, le=0.95)
    sensor_bias_c: float | None = Field(None, ge=-30, le=30)
    stuck_position_pct: float | None = Field(None, ge=0, le=100)
    start_t_sim_s: float = Field(0.0, ge=0)

    @model_validator(mode="after")
    def _params(self) -> "HiddenDefect":
        required = {"fuel_pump_weak": ("fuel_pump_max_lph",),
                    "injector_clogged": ("cylinder", "injector_flow_factor"),
                    "iat_sensor_bias": ("sensor_bias_c",),
                    "wastegate_stuck": ("stuck_position_pct",)}
        for name in required[ self.kind.value ]:
            if getattr(self, name) is None:
                raise ValueError(f"{name} obrigatório para {self.kind.value}")
        return self

class InitialCalibration(BaseModel):
    source: Literal["vehicle_stock", "embedded"]
    payload: dict[ str, Any ] | None = None    # Calibration sem metadados (embedded)
    content_hash: Sha256Hex                     # hash canónico do ecu-core

class HintUnlock(BaseModel):
    after_failed_submissions: int | None = Field(None, ge=1, le=5)
    after_sim_time_s: float | None = Field(None, ge=0, le=36000)
    after_event: Literal["knock_retard", "engine_failed", "egt_limit", "invalid_run"] | None = None

class Hint(BaseModel):
    order: int = Field(ge=1, le=5)
    text: str = Field(min_length=1, max_length=500)
    unlock: HintUnlock = HintUnlock()           # tudo None ⇒ livre

class ScenarioConstraints(BaseModel):
    allowed_run_types: list[ Literal["baseline_pull", "sweep_pull", "multi_pull"] ] = \
        ["baseline_pull", "sweep_pull", "multi_pull"]
    gear: int = Field(4, ge=1, le=10)
    allowed_final_profiles: list[ str ] = Field(default_factory=list)   # EcuProfileId
    swap_allowed: bool = False
    locked_table_ids: list[ str ] = Field(default_factory=list)
    max_submissions: int = Field(5, ge=1, le=20)
    time_limit_min: int | None = Field(None, ge=10, le=600)
    operator_protection: bool = False

class CriterionKind(StrEnum):
    MIN_WHP = "min_whp"; MIN_DELTA_WHP = "min_delta_whp"; MIN_TORQUE_NM = "min_torque_nm"
    MAX_KNOCK_RETARD_DEG = "max_knock_retard_deg"; MIN_KNOCK_MARGIN_DEG = "min_knock_margin_deg"
    INTEGRITY = "integrity"; MAX_EGT_C = "max_egt_c"; MAX_EGT_OVERRUN_C = "max_egt_overrun_c"
    LAMBDA_WOT_MAX = "lambda_wot_max"; LAMBDA_WOT_MIN = "lambda_wot_min"
    MIN_POP_EVENTS = "min_pop_events"; VALID_PULLS = "valid_pulls"
    MAX_SPREAD_PCT = "max_spread_pct"; FINAL_PROFILE = "final_profile"
    LOCKED_TABLES = "locked_tables"; DEFECT_DIAGNOSIS = "defect_diagnosis"

class Criterion(BaseModel):
    criterion_id: Slug
    kind: CriterionKind
    comparator: Literal["ge", "le", "bool"]
    threshold: float | None = None             # unidade do kind (whp, N·m, °, °C, λ, %, contagem)
    band: float | None = Field(None, gt=0)     # só "le"; None ⇒ banda padrão
    weight: float = Field(1.0, gt=0, le=10)
    mandatory: bool = True

class ChallengeCriteria(BaseModel):
    criteria: list[ Criterion ] = Field(min_length=1, max_length=20)
    required_valid_pulls: int = Field(2, ge=1, le=10)
    min_end_rpm: float | None = Field(None, ge=1500, le=12000)
    lambda_window_min_rpm: float = Field(3000, ge=1000, le=10000)
    require_defect_diagnosis: bool = False

class Scenario(BaseModel):
    scenario_id: Slug
    kind: Literal["base", "challenge"]
    title: str = Field(min_length=3, max_length=80)
    briefing: str = Field(max_length=4000)
    vehicle_id: str
    initial_profile_id: str = "oem-stage"
    initial_calibration: InitialCalibration
    fuel_id: str                                # FuelSpec do vehicle-catalog
    ambient: dict[ str, float ]                 # AmbientConditions do dyno-bench
    correction_standard: Literal["sae_j1349", "din_70020", "none"] = "sae_j1349"
    seed: int | None = Field(None, ge=0, le=2**63 - 1)   # None ⇒ derivada do attempt_id
    objectives: list[ str ] = Field(min_length=1, max_length=10)
    constraints: ScenarioConstraints = ScenarioConstraints()
    criteria: ChallengeCriteria
    hidden_defect: HiddenDefect | None = None
    hints: list[ Hint ] = Field(default_factory=list, max_length=5)
    author_nickname: Nickname | None = None
    scenario_sha256: Sha256Hex | None = None    # calculado pelo servidor
    builtin: bool = False
    origin: Literal["builtin", "local", "imported"] = "local"
    created_at: datetime | None = None

class AttemptState(StrEnum):
    PREPARING = "preparing"; IN_PROGRESS = "in_progress"; EVALUATING = "evaluating"
    PASSED = "passed"; FAILED_FINAL = "failed_final"; ABANDONED = "abandoned"
    EXPIRED = "expired"; FAILED_TO_START = "failed_to_start"

class AttemptRun(BaseModel):
    run_id: str
    run_type: str
    pull_index: int | None = None
    valid: bool
    invalid_reason: str | None = None
    calibration_hash: str | None = None
    peak_whp: float | None = None

class Attempt(BaseModel):
    attempt_id: str                             # UUID4
    scenario_id: Slug
    scenario_sha256: Sha256Hex
    profile_id: str
    nickname: Nickname
    origin: Literal["local", "imported"] = "local"
    state: AttemptState
    session_id: str | None = None
    calibration_id: str
    seed: int
    baseline_run_id: str | None = None
    baseline_peak_whp: float | None = None
    runs: list[ AttemptRun ] = Field(default_factory=list)
    submissions: int = Field(0, ge=0)
    hints_revealed: list[ int ] = Field(default_factory=list)
    engine_restores: int = Field(0, ge=0)
    started_at: datetime

class SubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    calibration_id: str
    run_ids: list[ str ] | None = Field(None, max_length=10)
    declared_defect: DefectKind | Literal["none"] | None = None

class Evidence(BaseModel):
    run_id: str
    log_id: str | None = None
    channel: str                                # ex.: egt_collector_c
    t_sim_s: float | None = None
    rpm: float | None = None
    cylinder: int | None = None
    value: float | None = None
    url: str                                    # /api/v1/runs/{run_id}/log?format=json

class CriterionResult(BaseModel):
    criterion_id: Slug
    kind: CriterionKind
    comparator: Literal["ge", "le", "bool"]
    measured: float | None
    threshold: float | None
    passed: bool
    score: float = Field(ge=0, le=100)
    weight: float
    mandatory: bool
    evidence: list[ Evidence ] = Field(default_factory=list, max_length=10)

class Evaluation(BaseModel):
    evaluation_id: str
    attempt_id: str
    submission_index: int = Field(ge=1)
    status: Literal["pending", "completed", "error"]
    evaluator_version: str                      # SemVer do avaliador, ex.: "1.0.0"
    passed: bool | None = None
    total_score: float | None = Field(None, ge=0, le=100)
    results: list[ CriterionResult ] = Field(default_factory=list)
    evidence_run_ids: list[ str ] = Field(default_factory=list)
    ignored_runs: list[ str ] = Field(default_factory=list)
    calibration_content_hash: Sha256Hex | None = None
    probe_run_sha256: Sha256Hex | None = None
    hints_revealed: list[ int ] = Field(default_factory=list)
    revealed_defect: HiddenDefect | None = None
    evaluation_sha256: Sha256Hex | None = None  # JCS sem evaluation_id e created_at
    created_at: datetime | None = None

class PackageProducer(BaseModel):
    app_version: str
    install_id: str
    nickname: Nickname | None = None

class SignedPackage(BaseModel):
    format_version: int = Field(1, ge=1)        # PACKAGE_FORMAT_VERSION
    kind: Literal["challenge", "attempt"]
    created_at: datetime                        # fora do hash
    producer: PackageProducer                   # fora do hash
    payload: dict[ str, Any ]
    sha256: Sha256Hex
    hmac_sha256: str | None = None              # reservado (OQ-02); ignorado no MVP

class PackageExportRequest(BaseModel):
    kind: Literal["challenge", "attempt"]
    scenario_id: Slug | None = None             # kind challenge
    attempt_id: str | None = None               # kind attempt
    include_full_logs: bool = False

class PackageImportResult(BaseModel):
    package_sha256: Sha256Hex
    kind: Literal["challenge", "attempt"]
    scenario_id: Slug
    attempt_id: str | None = None
    already_imported: bool = False
    evaluation_mismatch: bool = False
    recomputed_evaluation: Evaluation | None = None

class ScenarioCreate(BaseModel):              # Scenario sem campos calculados pelo servidor
    model_config = ConfigDict(extra="forbid")
    scenario: Scenario
    initial_calibration_id: str | None = None   # se dado, o servidor embute a calibração

class ScenarioSummary(BaseModel):
    scenario_id: Slug; kind: Literal["base", "challenge"]; title: str
    vehicle_id: str; fuel_id: str; has_hidden_defect: bool; available: bool = True
    last_evaluation_passed: bool | None = None  # do perfil indicado no cabeçalho

class AttemptPage(BaseModel):
    items: list[ Attempt ]; next_cursor: str | None = None

class HintReveal(BaseModel):
    order: int; text: str; remaining: int

class SubmitAccepted(BaseModel):
    attempt_id: str; submission_index: int; evaluation_status: Literal["pending"] = "pending"

class ReplayAccepted(BaseModel):
    attempt_id: str; replay_status: Literal["running"] = "running"; runs_to_replay: int

class ScenarioStats(BaseModel):
    scenario_id: Slug
    started: int; passed: int; failed_final: int; abandoned: int
    completion_rate_pct: float | None           # None se started = 0
    median_submissions_to_pass: float | None
```

🟡 Regras adicionais: `threshold` obrigatório para `ge` e `le`; `kind = defect_diagnosis` só com `hidden_defect` presente; `min_knock_margin_deg` entre 0,5 e 6°; `allowed_final_profiles` só com IDs de `EcuProfileId`; `seed` derivada = `int(sha256(attempt_id)[:15], 16)`; violações devolvem 422 `SCENARIO_INVALID` com o campo em `detail`.

**Entidades persistidas (SQLModel):**

```text
player_profile {
  id: String(36) PK                // UUID4
  nickname: String(24)             // UNIQUE (lower(nickname))
  role: String(16)                 // student | instructor
  created_at: DateTime(tz)
}
scenario {
  id: String(64) PK                // slug
  kind: String(16); builtin: bool; origin: String(16)
  scenario_sha256: String(64)      // INDEX
  content_json: JSON               // Scenario completo
  created_at: DateTime(tz)
}
attempt {
  id: String(36) PK
  scenario_id: String(64) FK -> scenario
  profile_id: String(36) FK -> player_profile | None   // None quando importada
  nickname: String(24); origin: String(16); state: String(24)
  session_id: String(36) | None; calibration_id: String(64); seed: BigInteger
  baseline_run_id: String(36) | None; baseline_peak_whp: Float | None
  submissions: int; hints_revealed_json: JSON; engine_restores: int
  producer_install_id: String(36) | None; package_sha256: String(64) | None  // UNIQUE quando importada
  replay_status: String(24)        // not_run | running | verified | mismatch | incompatible_version
  started_at: DateTime(tz); updated_at: DateTime(tz)
  INDEX (scenario_id, origin, started_at)
}
attempt_run {
  attempt_id: String(36) FK -> attempt; run_id: String(36); pull_index: int | None
  valid: bool; invalid_reason: String(48) | None; calibration_hash: String(64) | None
  trace_json: JSON                 // EvaluationTrace 100 Hz (≤ 6000 linhas)
  PK (attempt_id, run_id, pull_index)
}
evaluation {
  id: String(36) PK; attempt_id: String(36) FK -> attempt; submission_index: int
  status: String(16); passed: bool | None; total_score: Float | None
  result_json: JSON; evaluation_sha256: String(64) | None; evaluation_mismatch: bool
  created_at: DateTime(tz)
  UNIQUE (attempt_id, submission_index)
}
scenario_event {
  id: String(36) PK; kind: String(32); scenario_id: String(64); attempt_id: String(36)
  data_json: JSON                  // sem nickname
  created_at: DateTime(tz)         // INDEX (scenario_id, kind, created_at)
}
imported_package {
  sha256: String(64) PK; kind: String(16); scenario_id: String(64)
  attempt_id: String(36) | None; size_bytes: int; imported_at: DateTime(tz)
}
```

**Migrações necessárias:** 🟡 Sim. A revisão `NNNN_scenarios_base` cria as 7 tabelas acima, encadeada linearmente após as revisões do Sprint 3. Os cenários base não ficam na migração; são carregados no arranque (RF-04).

---

## 10. Integrações e Dependências

| Dependência | Tipo | Impacto se indisponível |
|-------------|------|------------------------|
| 🟡 `dyno-bench` (`POST/DELETE /api/v1/sessions`, `POST .../runs`, `DynoRun`, `RunSummary`, `curve_sha256`) e campos oficiais `fuel_id`, `physics_faults`, `attempt_id`, `ProbeOverrides` (revisão R1) | Obrigatória | Sem sessão não há tentativa: `POST .../attempts` devolve 503 `SIM_WORKER_UNAVAILABLE` e a tentativa fica `failed_to_start`. |
| 🟡 `engine-physics-core` (`PhysicsFault`, tipo novo `wastegate_stuck`) | Obrigatória | Sem `wastegate_stuck`, o `POST /api/v1/scenarios` com esse defeito devolve 422 `SCENARIO_INVALID` (feature flag `SIMREMAP_FEATURE_DEFECT_WASTEGATE`). |
| 🟡 `knock-and-failure-model` (`DamageState`, `ComponentHealth.health_pct`, `FailureEvent`, classe de knock por ciclo) | Obrigatória | Sem dano, o critério `integrity` fica `status = error` e a avaliação inteira devolve `status = error` com `code = DAMAGE_MODEL_UNAVAILABLE`. |
| 🟡 `telemetry-datalogger` (`DataLog` com `egt_collector_c`, `lambda_measured`, `pedal_pct`, `knock_retard_max_deg`, `pop_events`, `overrun_active`, `health_min_pct`, `phase`) | Obrigatória | Sem log, o `EvaluationTrace` não é gerado, a puxada fica `invalid_reason = trace_unavailable` e o sistema faz retry da leitura 3 vezes (200, 400, 800 ms). |
| 🟡 `ecu-core` (`POST /api/v1/calibrations` clone/payload, `content_hash`, versões imutáveis) | Obrigatória | Sem calibração não há tentativa: 503 `CALIBRATION_SERVICE_UNAVAILABLE`. |
| 🟡 `ecu-profiles` (`EcuProfileId`, swap) | Obrigatória | Sem swap, o `standalone-swap` não é concluível; o cenário fica marcado `available = false` na lista. |
| 🟡 `vehicle-catalog` (`VehicleSpec`, `FuelSpec.fuel_id`, `MechanicalLimits.rev_limit_rpm`, `stock_calibration_id`) | Obrigatória | Cenário com veículo ausente devolve 404 `VEHICLE_NOT_FOUND` e não é carregado no arranque (log `scenarios.builtin_skipped`). |
| 🟡 `platform-foundation` (`ProblemDetail`, `register_error`, `body_limit`, `app_meta.install_id`, `PACKAGE_FORMAT_VERSION`, `SimWorkerHost`) | Obrigatória | Sem banco, endpoints devolvem 503 `DATABASE_UNAVAILABLE`. |
| 🟡 `dyno-cockpit-ui` e `ecu-tuning-ui` (rotas `/sessions/:sessionId/dyno` e `/ecu`, modo só leitura da calibração inicial) | Obrigatória (UI) | Sem cockpit, o painel de progresso abre em página própria `/attempts/:attemptId`. |
| 🟡 `rfc8785` (PyPI) | Obrigatória | Sem JCS não há pacotes; export/import devolvem 503 `PACKAGE_SERVICE_UNAVAILABLE`. |

---

## 11. Edge Cases e Tratamento de Erros

| Cenário | Trigger | Comportamento esperado |
|---------|---------|----------------------|
| 🟡 EC-01: Hash do pacote inválido | Um byte do `payload` alterado ou `sha256` editado | 422 `PACKAGE_HASH_MISMATCH` com `expected_sha256` e `actual_sha256`; nenhuma linha gravada; a fila da turma marca o ficheiro como recusado e continua com os restantes. |
| 🟡 EC-02: Pacote com hash recalculado e critérios alterados | Aluno muda o limiar de EGT e recalcula o SHA-256 | 409 `SCENARIO_VERSION_MISMATCH` porque o `scenario_sha256` difere do cenário local do instrutor; o painel mostra "cenário diferente do original". |
| 🟡 EC-03: Pacote com curvas forjadas e hash válido | Aluno edita `RunSummary` e recalcula hashes | A avaliação recalculada usa os dados forjados; o replay (RF-22) detecta `curve_sha256` diferente e grava `replay_status = mismatch`; a linha da turma recebe o aviso "replay divergente". |
| 🟡 EC-04: Falha de leitura do log na avaliação | `telemetry-datalogger` indisponível ou timeout de 2 s | Retry 3 vezes (200/400/800 ms); persistindo a falha, a avaliação fica `status = error` com `code = TRACE_UNAVAILABLE` e a submissão não conta para `max_submissions`. |
| 🟡 EC-05: Sonda de knock sem slot de sessão | Sessão interativa ativa ocupa o único slot | A sonda corre como tarefa sem UI da mesma sessão da tentativa; se a sessão estiver em puxada, o submit devolve 409 `RUN_IN_PROGRESS`. |
| 🟡 EC-06: Sonda termina com falha interna | Exceção no worker ou `SIM_INTERNAL_ERROR` | Avaliação `status = error` com `code = PROBE_FAILED`; sem fallback para aprovação; o usuário pode submeter de novo sem gastar submissão. |
| 🟡 EC-07: Formato futuro | `format_version` maior que `PACKAGE_FORMAT_VERSION` | 422 `PACKAGE_FORMAT_UNSUPPORTED` com a versão suportada no `detail`. |
| 🟡 EC-08: JSON com `NaN` ou `Infinity` | Exportação de puxada com valor não finito, ou ficheiro manual | 422 `PACKAGE_NOT_CANONICALIZABLE`; no export, o `detail` aponta o caminho JSON do valor. |
| 🟡 EC-09: Pacote acima do limite | Ficheiro > 64 MiB (logs completos de 10 puxadas) | 413 `PAYLOAD_TOO_LARGE` antes do parse; a UI sugere exportar sem `include_full_logs`. |
| 🟡 EC-10: Nicknames iguais de estações diferentes | Dois alunos `joao` na mesma turma | As duas linhas ficam separadas por `producer.install_id`; a tabela mostra `joao (a1b2)` com os 4 primeiros hex da estação. |
| 🟡 EC-11: Tentativa sem puxadas válidas | Submit sem nenhuma puxada válida com o hash submetido | Avaliação concluída com `passed = false`, critério `valid_pulls` com `measured = 0` e os motivos de invalidade em `ignored_runs`. |
| 🟡 EC-12: Calibração alterada depois do submit | Edição da calibração durante `evaluating` | A avaliação usa a versão congelada (`content_hash` gravado); a edição cria nova versão no `ecu-core` e não afeta o resultado. |
| 🟡 EC-13: Puxada base falha | `baseline_pull` termina `aborted` ou em timeout de 120 s | Tentativa `failed_to_start` com `code = BASELINE_FAILED`; nenhuma submissão gasta; o usuário pode iniciar nova tentativa. |
| 🟡 EC-14: Defeito oculto não suportado pela física | `wastegate_stuck` sem suporte na versão da `engine-physics-core` | `POST /api/v1/scenarios` devolve 422 `SCENARIO_INVALID`; import de desafio com esse defeito devolve 422 `PACKAGE_SCHEMA_INVALID` com `detail` "defeito não suportado". |
| 🟡 EC-15: Container encerrado durante a avaliação | SIGTERM com `evaluating` | No arranque seguinte, avaliações `pending` com mais de 5 min passam a `error` com `code = EVALUATION_INTERRUPTED` e a tentativa volta a `in_progress` sem gastar submissão. |
| 🟡 EC-16: Disco cheio ao importar | `STORAGE_FULL` do banco | 507 `STORAGE_FULL`; transação revertida; o pacote não fica marcado como importado. |

---

## 12. Segurança e Privacidade

- 🟡 **Autenticação:** nenhuma (NG-01). A troca de perfil é local e sem senha; o PIN opcional do instrutor fica em aberto (OQ-01).
- 🟡 **Autorização:** o `role` vem do perfil indicado em `X-Player-Profile-Id` e controla só a UI e as regras pedagógicas; não é um controle de segurança (alinhado com `platform-foundation`). Tentativas só aceitam submit, dicas e abandono do perfil dono (`ATTEMPT_NOT_OWNED`).
- 🟡 **Dados sensíveis:** zero PII. O nickname é a única informação do usuário, com regex sem espaços e sem `@`; os logs JSON usam `profile_id` e `attempt_id`, nunca o nickname (`platform-foundation` RF-13 e RF-20).
- 🟡 **Integridade dos pacotes:** o SHA-256 do JCS deteta corrupção e alteração ingénua; não autentica autoria, porque qualquer pessoa recalcula o hash. A defesa em camadas é: (1) `scenario_sha256` conferido contra o cenário local do instrutor, (2) avaliação recalculada na importação, (3) replay determinístico opcional. HMAC-SHA256 com segredo do instrutor ou assinatura Ed25519 ficam em OQ-02.
- 🟡 **Entrada não confiável:** pacotes são validados por schema Pydantic com `extra="forbid"` e limites de tamanho; nenhum `pickle`, `eval` nem caminho de ficheiro vindo do pacote; textos (título, briefing, dicas) são mostrados como texto, sem HTML.
- 🟡 **CSV:** proteção contra injeção de fórmulas (RF-26).
- 🟡 **Auditoria:** `scenario_event` e `imported_package` registam o ciclo de cada tentativa e cada importação com `sha256` e `size_bytes`.

---

## 13. Plano de Rollout

- 🟡 **Estratégia:** big bang no Sprint 4 atrás da flag `SIMREMAP_FEATURE_SCENARIOS=1` (ligada em dev e staging; ligada em prod ao fechar o Sprint 4). A flag `SIMREMAP_FEATURE_DEFECT_WASTEGATE` fica ligada com a física, que suporta `wastegate_stuck` desde a revisão R1; desligá-la é o rollback do defeito.
- 🟡 **Validação antes de prod:** G-02 no CI (soluções de referência aprovam, calibrações iniciais reprovam), G-01 (20 repetições), G-04 (1000 mutações) e teste Playwright com 50 pacotes.
- 🟡 **Implantação em turma:** um container Docker por estação/aluno com a mesma tag de imagem (requisito do replay); o instrutor distribui o pacote `challenge` por ficheiro e recolhe os pacotes `attempt`.
- 🟡 **Como reverter (rollback):** desligar a flag (routers devolvem 404 e a UI esconde a rota `/scenarios`), executar `alembic downgrade -1` para remover as 7 tabelas, e reinstalar a tag anterior; pacotes exportados continuam legíveis por qualquer versão com `PACKAGE_FORMAT_VERSION = 1`.
- 🟡 **Monitoramento pós-deploy:** taxa de conclusão por cenário (`/stats`), contagem de `PACKAGE_HASH_MISMATCH` e `SCENARIO_VERSION_MISMATCH`, P95 do tempo de avaliação e avaliações em `error` por `code`.

---

## 14. Open Questions

| # | Pergunta | Impacto | Dono | Prazo |
|---|---------|---------|------|-------|
| 🟡 OQ-01 | ⚠️ ABERTO: o perfil de instrutor deve ter PIN opcional de 4 a 8 dígitos (hash `hashlib.scrypt` local) para impedir que alunos abram o painel do instrutor na mesma estação? | Médio | George | 2026-10-25 |
| 🟡 OQ-02 | ⚠️ ABERTO: o SHA-256 deteta corrupção e não autentica autoria. Adotar HMAC-SHA256 com segredo do instrutor (verificado só na estação do instrutor, para provar que o desafio embutido não mudou) ou assinatura Ed25519 (chave pública distribuída aos alunos)? | Alto | George | 2026-11-01 |
| 🟡 OQ-03 | ⚠️ ABERTO: a taxa de conclusão ≥ 80 % conta só tentativas dos cenários base ou também desafios do instrutor, e tentativas `abandoned` entram no denominador? (padrão desta spec: só base, abandonadas entram) | Alto | George | 2026-10-25 |
| 🟡 OQ-04 | 🟡 Resolvida na revisão R1 (2026-10-18): `wastegate_stuck` com `stuck_position_pct` é tipo oficial de `PhysicsFault` na `engine-physics-core`. | Alto | George | 2026-10-22 |
| 🟡 OQ-05 | 🟡 Resolvida na revisão R1 (2026-10-18): o `dyno-bench` define `fuel_id`, `physics_faults`, `attempt_id` e `ProbeOverrides` (RF-25 e RF-26 dele). | Alto | George | 2026-10-22 |
| 🟡 OQ-06 | ⚠️ ABERTO: a meta do `standalone-swap` é 300 whp no `classic-20t-swap` com E100 (início da faixa 300–600 whp do PRD) ou um Δwhp sobre a base OEM? | Médio | George | 2026-10-29 |
| 🟡 OQ-07 | 🟡 O `telemetry-datalogger` expõe os canais `pop_events`, `overrun_active`, `health_min_pct` e `phase` no `DataLog` à taxa total do laço? | Alto | George | 2026-10-22 |
| 🟡 OQ-08 | 🟡 O replay de 50 tentativas (≈ 150 puxadas) cabe numa aula ou deve ser amostral (ex.: 10 % das tentativas aprovadas)? | Baixo | George | 2026-11-08 |

---

## 15. Decisões Tomadas (Decision Log)

| Decisão | Alternativas consideradas | Racional |
|---------|--------------------------|---------|
| 🟡 Hash SHA-256 sobre JCS RFC 8785 de `{format_version, kind, payload}` | `json.dumps(sort_keys=True)` com arredondamento, como no `ecu-core` | JCS é norma independente de linguagem e de biblioteca; o instrutor ou um script externo recalcula o mesmo hash. Os hashes internos (`content_hash`, `curve_sha256`) continuam com a forma do dono e entram no payload como texto. |
| 🟡 SHA-256 regista integridade, não autoria; HMAC e Ed25519 ficam em OQ-02 | HMAC obrigatório no MVP | Um segredo simétrico na estação do aluno seria lido por ele; a combinação `scenario_sha256` + avaliação recalculada + replay cobre a fraude relevante sem gestão de chaves. |
| 🟡 Avaliação só a partir de `RunSummary` e `EvaluationTrace` a 100 Hz com agregação fixa | Avaliar sobre o `DataLog` completo | O trace cabe no pacote (≤ 8 MiB) e dá resultado idêntico no aluno e no instrutor; máximos e somas preservam os picos de EGT, knock e pops. |
| 🟡 Margem de knock medida por sonda com avanço + margem e controle de knock em malha aberta | Estimar margem pela integral de Livengood-Wu da puxada | A sonda é objetiva, determinística e corresponde à prática de oficina ("mais 2° e continua sem knock"); a estimativa por integral depende de extrapolação não linear. |
| 🟡 Meta de potência pelo mínimo dos picos das puxadas de evidência | Média ou melhor puxada | Exige que todas as puxadas cumpram e reforça a repetibilidade térmica (jornada do Rodrigo). |
| 🟡 Aprovação por critérios obrigatórios; pontuação só informativa | Nota de corte sobre a pontuação total | O PRD exige aprovação por critérios objetivos; um acerto com knock não pode passar por média. |
| 🟡 Dicas não alteram a aprovação nem a pontuação | Penalização por dica | Mantém a avaliação puramente técnica; o instrutor vê `hints_revealed` na tabela. |
| 🟡 Perfil ativo no cliente (`localStorage`) e cabeçalho `X-Player-Profile-Id` | Sessão de servidor com cookie | Local-first, sem autenticação e sem estado de login; trocar perfil é trocar o cabeçalho. |
| 🟡 Integridade só nas puxadas de evidência, com `engine_restores` informativo | Reprovar qualquer quebra na tentativa | A jornada do Lucas inclui quebrar e restaurar o motor para aprender; o critério avalia o acerto final. |
| 🟡 CSV gerado no navegador | Endpoint de CSV no servidor | Os dados já estão na tabela; evita endpoint extra e funciona offline. |

---

## Apêndice

### Referências
- 🟡 `_reversa_sdd/prd.md` (seções 3, 4, 8 e 9) e `_reversa_sdd/personas.md` (jornadas de Lucas, Rodrigo e Prof. Marcos).
- 🟡 RFC 8785 (JSON Canonicalization Scheme), FIPS 180-4 (SHA-256), RFC 4180 (CSV), RFC 7807 (Problem Details).
- 🟡 Specs relacionadas: `platform-foundation.md`, `engine-physics-core.md`, `dyno-bench.md`, `ecu-core.md`, `dyno-cockpit-ui.md`, `ecu-tuning-ui.md`, `knock-and-failure-model.md`, `telemetry-datalogger.md`, `ecu-profiles.md`, `vehicle-catalog.md`.

### Exemplo de `ChallengeCriteria` (`stage2-pops-bangs`)

```json
{
  "required_valid_pulls": 2, "lambda_window_min_rpm": 3000,
  "criteria": [
    {"criterion_id": "delta-whp", "kind": "min_delta_whp", "comparator": "ge", "threshold": 65, "weight": 2.0},
    {"criterion_id": "knock", "kind": "max_knock_retard_deg", "comparator": "le", "threshold": 3},
    {"criterion_id": "egt", "kind": "max_egt_c", "comparator": "le", "threshold": 950},
    {"criterion_id": "egt-overrun", "kind": "max_egt_overrun_c", "comparator": "le", "threshold": 950},
    {"criterion_id": "pops", "kind": "min_pop_events", "comparator": "ge", "threshold": 5},
    {"criterion_id": "integrity", "kind": "integrity", "comparator": "ge", "threshold": 100},
    {"criterion_id": "pulls", "kind": "valid_pulls", "comparator": "ge", "threshold": 2},
    {"criterion_id": "spread", "kind": "max_spread_pct", "comparator": "le", "threshold": 3}
  ]
}
```

### Exemplo de `SignedPackage` (cortado)

```json
{
  "format_version": 1, "kind": "challenge",
  "created_at": "2026-10-18T10:00:00Z",
  "producer": {"app_version": "1.0.0", "install_id": "8f0c2b7e-0d1a-4c55-9a43-1b2f3e4d5c6a", "nickname": "prof_marcos"},
  "payload": {"scenario": {"scenario_id": "challenge-400whp-e27", "kind": "challenge"}},
  "sha256": "3b1f…(64 hex)",
  "hmac_sha256": null
}
```

### Histórico de Revisões
| Versão | Data | Autor | Mudanças |
|--------|------|-------|---------|
| 🟡 1.0 | 2026-10-18 | reversa-spec-sdd | Criação inicial |
| 🟡 1.1 | 2026-10-18 | reversa-spec-sdd | Revisão R1 de consistência entre specs (decisões do usuário: knock, nomes de campo, códigos de erro, seq, campos de integração, prefixo /api/v1/, OEM-Stage, benchmark v1) |

## Relatório de avaliação (reversa-spec-sdd)

- 🟡 Score final: 100,0/100 (⭐ Excelente)
- 🟡 Iterações: 3 (scores: 91 → 100 → 100)
- 🟡 Breakdown: Completude 100 %, Testabilidade 100 %, Clareza 100 %, Escopo 100 %, Edge Cases 100 %
- 🟡 Gaps críticos remanescentes: nenhum
- 🟡 Sugestões remanescentes: nenhuma
- 🟡 Revisão R1 (2026-10-18): reavaliado após a revisão de consistência entre specs, score 100,0/100.
