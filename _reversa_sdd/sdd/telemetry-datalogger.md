# Spec: telemetry-datalogger

**Versão:** 1.1
**Status:** Rascunho
**Autor:** reversa-spec-sdd
**Data:** 2026-10-18
**Reviewers:** N/A
**Sprint:** 3 (componente 7)

---

## 1. Resumo

🟡 O `telemetry-datalogger` transporta o estado do laço físico até a UI e grava o log completo de cada puxada. Ele publica o WebSocket `/ws/v1/sessions/{session_id}/telemetry` com envelope `WsEnvelope`, decima a taxa do laço (100–1000 Hz) para 30–60 FPS (padrão 50), aplica subscrição de canais e backpressure sem nunca bloquear o worker físico. Ele grava o `DataLog` canónico à taxa total do laço, com hash SHA-256 determinístico, export JSON/CSV, import validado, comparação por bins de RPM e dados do espectrograma de knock. É a base de dados que Lucas, Rodrigo e Prof. Marcos usam para entender a causa do ganho ou da quebra.

---

## 2. Contexto e Motivação

**Problema:**
🟡 Os softwares oficiais de ECU editam tabelas offline e não dão resposta de wideband, knock ou EGT em tempo real (PRD §1). O laço físico corre até 1000 Hz num processo separado; enviar cada tick ao navegador satura o WebSocket e a UI, e perder o log completo impede a autópsia e a avaliação objetiva do instrutor.

**Evidências:**
- 🟡 PRD §3 (métricas): taxa de frames de telemetria enviados à UI entre 30 e 60 FPS no MVP.
- 🟡 PRD §4 (Telemetria): streaming em tempo real, datalogger, espectrograma de knock, pressão no cilindro, gauges e exportação/importação de datalogs em JSON/CSV.
- 🟡 PRD §8 (riscos): a banda do WebSocket a 60 FPS com dezenas de canais degrada a UI; mitigação: agregar e subamostrar no servidor e enviar só os canais visíveis.
- 🟡 PRD §8 (riscos): pacotes de telemetria exportados e importados com hash SHA-256 no JSON para avaliação sem rede.
- 🟡 PRD §9 (critério Prof. Marcos): exportar os logs antes vs. depois; critério de desempenho: loop ≥ 100 Hz e UI ≥ 30 FPS no hardware de referência.

**Por que agora:**
🟡 No Sprint 3 o `dyno-bench`, o `ecu-core` e o `knock-and-failure-model` (Sprint 2) já produzem `EngineState`, `EcuStatus`, `DamageState` e `run.state`. O `dyno-cockpit-ui` (Sprint 3) e o `ecu-tuning-ui` (Sprint 4) dependem deste WebSocket e dos endpoints de log para desenhar curvas, cursor de operação e comparação antes vs. depois.

---

## 3. Goals (Objetivos)

- [ ] 🟡 G-01: Entregar frames `telemetry.frame` à UI a 50 FPS (configurável 30–60) com desvio ≤ 2 % da taxa nominal em 60 s de `sweep_pull`, sem reduzir o laço físico abaixo de 99 % de `sim_hz`.
- [ ] 🟡 G-02: Gravar 100 % dos ticks de cada puxada no `DataLog` (taxa total do laço), com hash SHA-256 idêntico em 10 de 10 repetições com a mesma `seed`, `sim_hz`, calibração e comandos.
- [ ] 🟡 G-03: Manter a latência tick→envio do frame ≤ 40 ms (p95) e a banda média ≤ 150 kB/s por conexão com a subscrição completa da cockpit.
- [ ] 🟡 G-04: Exportar, importar e comparar logs com 0 divergência de hash na volta export JSON → import (round-trip) e comparação de duas puxadas de 15 s em < 500 ms.

**Métricas de sucesso:**
| Métrica | Baseline atual | Target | Prazo |
|---------|---------------|--------|-------|
| 🟡 Taxa de frames na UI | inexistente | 30–60 FPS (padrão 50, desvio ≤ 2 %) | Sprint 3 (2026-11-08) |
| 🟡 Laço físico com 2 clientes WS lentos | inexistente | ≥ 99 % de `sim_hz` | Sprint 3 |
| 🟡 Latência tick→envio (p95) | inexistente | ≤ 40 ms | Sprint 3 |
| 🟡 Reprodutibilidade do hash do log | inexistente | 100 % (10/10) | Sprint 3 |
| 🟡 Round-trip export/import JSON | inexistente | 0 divergências de SHA-256 | Sprint 3 |
| 🟡 Tamanho comprimido de 15 s a 1000 Hz | inexistente | ≤ 3 MB | Sprint 3 |

---

## 4. Non-Goals (Fora do Escopo)

- 🟡 NG-01: O componente não calcula física, dano nem estratégia de ECU; ele só lê `EngineState`, `SensorReadings`, `ActuatorCommands`, `EcuStatus`, `EcuEvent`, `DamageState` e `FailureEvent` dos componentes donos.
- 🟡 NG-02: O componente não desenha gráficos nem toca áudio; o desenho, a interpolação visual e o som pertencem ao `dyno-cockpit-ui` e ao `ecu-tuning-ui`.
- 🟡 NG-03: O componente não define a máquina de estados da puxada nem calcula a curva corrigida (SAE J1349/DIN 70020); isso pertence ao `dyno-bench`, que publica `run.state` por este transporte.
- 🟡 NG-04: O componente não importa logs de ECUs reais (MoTeC `.ld`, FTManager, NSP, WinOLS) nem CSV de terceiros no MVP; o import aceita só o `DataLog` JSON do próprio simulador.
- 🟡 NG-05: O componente não assina nem empacota cenários (`SignedPackage`); isso pertence ao `training-scenarios`, que embute o `DataLog` e o seu `sha256`.
- 🟡 NG-06: O componente não faz streaming entre máquinas, multi-utilizador remoto nem autenticação; o WebSocket serve só a mesma origem do container local.
- 🟡 NG-07: O componente não replica frames perdidos por backpressure; o histórico completo vem do `DataLog` via REST.

---

## 5. Usuários e Personas

**Usuário primário:** 🟡 Lucas (aluno, remap OEM) e Rodrigo (preparador, standalone), através da cockpit e do editor de tabelas. Lucas precisa ver knock, lambda e EGT ao vivo e ler o log da quebra; Rodrigo precisa do espectrograma de knock, da pressão no cilindro e do log à taxa total para mapear o MBT cilindro a cilindro.

**Usuário secundário:** 🟡 Prof. Marcos (instrutor), que exporta e importa logs entre estações sem rede e compara as puxadas antes vs. depois de cada aluno. Os desenvolvedores do `dyno-cockpit-ui`, `ecu-tuning-ui` e `training-scenarios` consomem os contratos `WsEnvelope`, `TelemetryFrame`, `DataLog` e `LogComparison`.

**Jornada atual (sem a feature):**
1. 🟡 O usuário executa a puxada e só vê a curva final do `DynoRun`, sem lambda, knock ou EGT por cilindro ao longo do tempo.
2. 🟡 O motor quebra e o usuário não tem o log tick a tick para ligar a causa (avanço, boost, mistura) ao efeito.
3. 🟡 O instrutor não tem um arquivo verificável para comparar as puxadas de um aluno em outra estação.

**Jornada futura (com a feature):**
1. 🟡 O usuário abre a cockpit, que subscreve só os canais dos painéis visíveis e recebe frames a 50 FPS.
2. 🟡 Durante a puxada, o usuário vê `event.knock`, `event.limiter` e `event.failure` em tempo real, com o espectrograma mostrando o pico na ressonância do cilindro.
3. 🟡 No fim, o usuário revê o log completo, exporta em CSV com unidades e compara a puxada base com a nova por bins de 100 rpm.
4. 🟡 O instrutor importa o log JSON de um aluno, o sistema valida o SHA-256 e mostra a comparação.

---

## 6. Requisitos Funcionais

### 6.1 Requisitos Principais

| ID | Requisito | Prioridade | Critério de Aceite |
|----|-----------|-----------|-------------------|
| RF-01 | 🟡 O sistema deve expor o WebSocket `/ws/v1/sessions/{session_id}/telemetry` (mesma origem), aceitar até 4 conexões por sessão e fechar com código 4404 quando a sessão não existe e 4429 acima do limite. | Must | Teste: conexão a sessão inexistente fecha com 4404 e `reason = SESSION_NOT_FOUND`; a 5.ª conexão simultânea fecha com 4429 e `reason = WS_TOO_MANY_CONNECTIONS`. |
| RF-02 | 🟡 O sistema deve serializar toda mensagem servidor→cliente como `WsEnvelope` `{v: 1, type, seq, t_sim_s, payload}` com `type` ∈ {`telemetry.frame`, `run.state`, `event.knock`, `event.failure`, `event.limiter`, `error`}. | Must | Teste de contrato valida 10 000 mensagens contra o JSON Schema do `WsEnvelope`; 0 mensagens com `v` ≠ 1 ou `type` fora da lista. |
| RF-03 | 🟡 O sistema deve atribuir `seq` a partir de um contador único por sessão (começa em 0 na criação da sessão, incremento de 1 por envelope publicado a todas as conexões, partilhado entre todos os tipos), antes de qualquer filtro ou descarte por conexão. | Must | Teste: com 1 cliente sem perdas, os `seq` recebidos formam a sequência contígua n, n+1, …; com descarte forçado de 5 frames, o cliente observa exatamente 5 saltos de 1. |
| RF-04 | 🟡 O sistema deve publicar o catálogo de canais `TelemetryChannel` da seção 9 (nome, unidade, agregação, decimais, fonte), expandindo os canais por cilindro como `<base>_cyl<k>` para k = 1..n_cyl do veículo, e expô-lo em `GET /api/v1/telemetry/channels?vehicle_id=`. | Must | Para `hatch-20t-gdi` (4 cilindros) o catálogo contém `lambda_cyl1`..`lambda_cyl4` e nenhum `lambda_cyl5`; para `muscle-v8-sc` contém `egt_c_cyl1`..`egt_c_cyl8`; `vehicle_id` inexistente devolve 404 `VEHICLE_NOT_FOUND`. |
| RF-05 | 🟡 O sistema deve decimar os ticks do laço para frames de UI com a regra de fronteira `frame_index(k) = floor(k · fps / sim_hz)`, emitindo 1 frame quando o índice muda, com `fps` ∈ [30, 60] (padrão `Settings.ws_fps` = 50). | Must | Com `sim_hz` = 1000 e `fps` = 50, 60 s simulados geram 3000 ± 1 frames; com `sim_hz` = 300 e `fps` = 60, cada frame agrega 5 ticks; `fps` = 25 na subscrição devolve `error` `WS_FPS_OUT_OF_RANGE`. |
| RF-06 | 🟡 O sistema deve agregar os ticks da janela de cada frame pela regra do canal: `last` (valor do último tick), `max` (máximo da janela: knock, retardo, pressão de pico, EGT, duty de bico), `min` (saúde de componentes), `any` (flags `fuel_cut`, `ign_cut`) e `sum` (contagem de `overrun_afterfire`). | Must | Teste unitário: janela de 20 ticks com `knock_intensity_cyl2` = 0 em 19 ticks e 0,8 em 1 tick publica 0,8; `rpm` publica o valor do 20.º tick; `fuel_cut` = 1 se qualquer tick tiver corte. |
| RF-07 | 🟡 O sistema deve aceitar `control.subscribe` `{channels: list[ str ], fps?: int, spectrum?: bool, pressure_trace?: {cylinder: int}}` e enviar em `telemetry.frame` só os canais subscritos a partir do frame seguinte; eventos e `run.state` vão a todas as conexões sem filtro. | Must | Após subscrever `rpm` e `torque_nm`, o próximo frame contém exatamente essas 2 chaves em `channels`; canal desconhecido gera `error` `WS_UNKNOWN_CHANNEL` com a lista inválida e os canais válidos ficam ativos. |
| RF-08 | 🟡 O sistema deve aplicar backpressure por conexão com fila de frames limitada a 8 itens e política "descartar o mais antigo", e fila de eventos limitada a 256 itens, sem que o envio bloqueie o worker físico nem o produtor de frames. | Must | Teste com cliente que não lê durante 10 s: o worker mantém ≥ 99 % de `sim_hz`; a memória da conexão fica ≤ 2 MB; ao retomar a leitura, o 1.º frame recebido tem `t_sim_s` a ≤ 200 ms do tempo atual. |
| RF-09 | 🟡 O sistema deve nunca descartar `run.state` nem `event.failure`; ao encher a fila de eventos, deve descartar o `event.knock` mais antigo e incluir `dropped_events` no próximo `telemetry.frame`. | Must | Teste com 300 `event.knock` enfileirados e cliente parado: ao retomar, 100 % dos `run.state` e `event.failure` chegam; `dropped_events` ≥ 44. |
| RF-10 | 🟡 O sistema deve suportar reconexão com resume pela query `?resume_from_seq=<n>`: reenviar o snapshot atual de `run.state` e os envelopes de evento com `seq` > n ainda no buffer de replay (últimos 10 s ou 512 eventos), sem reenviar frames antigos. | Must | Teste: queda de 3 s com 2 `event.knock` emitidos nesse intervalo; ao reconectar com `resume_from_seq`, os 2 eventos chegam com o `seq` original antes do 1.º frame novo; gap fora do buffer gera `error` `WS_RESUME_GAP` com `oldest_available_seq`. |
| RF-11 | 🟡 O sistema deve publicar `event.knock` por cilindro quando a intensidade do ciclo exceder o limiar de deteção da ECU, com `cylinder`, `intensity`, `retard_deg`, `rpm`, `p_max_bar` e `run_id`, limitado a 1 evento por cilindro por ciclo do motor. | Must | Ciclo com knock nos cilindros 2 e 3 gera 2 eventos com o mesmo `t_sim_s`; a 6000 rpm durante 1 s com knock contínuo num cilindro geram-se ≤ 50 eventos desse cilindro. |
| RF-12 | 🟡 O sistema deve publicar `event.limiter` a cada transição de estado de limitador (`rev_limiter` soft/hard, `two_step`, `overboost_cut`, `antilag_protect`) a partir de `EcuEvent` e `EcuStatus.limiter_state`, com `active` (bool) e `kind`. | Must | Ao atingir o hard de 7000 rpm, chega 1 `event.limiter` `{kind: rev_limiter, phase: hard, active: true}` com o mesmo `t_sim_s` do `EcuEvent` `limiter_hit`; ao liberar, chega 1 com `active: false`. |
| RF-13 | 🟡 O sistema deve publicar `event.failure` com o `FailureEvent` completo do `knock-and-failure-model` no mesmo tick da falha e gravar o evento no `DataLog`. | Must | Teste com `rod_failure` forçado: o `event.failure` chega com `catastrophic: true` e `failure_mode = rod_failure` antes do `run.state` = `engine_failed`. |
| RF-14 | 🟡 O sistema deve gravar o `DataLog` de cada `DynoRun` à taxa total do laço (1 amostra por tick, todos os canais escalares do catálogo), de `arming` até o estado terminal, com segmentos por puxada em `multi_pull`. | Must | Puxada `sweep_pull` de 15,000 s a 1000 Hz gera exatamente 15 000 amostras por canal entre os ticks de início e fim; `multi_pull` de 3 puxadas gera 3 segmentos com `start_index` < `end_index`. |
| RF-15 | 🟡 O sistema deve persistir o log em `/data/logs/{run_id}.simlog.gz` (colunar float32 little-endian, gzip nível 6) e registar a linha `datalog` no banco com `sha256`, `n_samples`, `sim_hz` e `compressed_bytes`. | Must | Após `run.state` terminal, o arquivo existe em ≤ 2 s e o registo `datalog` tem `sha256` igual ao recalculado a partir do arquivo; 15 s a 1000 Hz ocupa ≤ 3 MB. |
| RF-16 | 🟡 O sistema deve calcular o hash canónico do log como SHA-256 do cabeçalho canónico (JSON com chaves ordenadas, separadores `,` e `:`, sem campos voláteis) concatenado às colunas float32 little-endian na ordem do catálogo. | Must | 10 execuções com a mesma `seed`, `sim_hz`, calibração e comandos produzem o mesmo `sha256`; mudar 1 bit de 1 amostra muda o `sha256`; `created_at` e `log_id` não alteram o hash. |
| RF-17 | 🟡 O usuário deve poder exportar o log por `GET /api/v1/runs/{run_id}/log?format=json` (o `DataLog` com `sha256`) ou `format=csv` (cabeçalho `nome (unidade)` por coluna), com `Content-Disposition` `run-<run_id>.json` ou `.csv`. | Must | O CSV de 15 000 amostras tem 15 001 linhas e o cabeçalho começa por `t_sim_s (s),tick (-),rpm (rpm)`; `format=xml` devolve 422 `VALIDATION_FAILED`; puxada em curso devolve 409 `LOG_NOT_READY`. |
| RF-18 | 🟡 O usuário deve poder importar um `DataLog` JSON por `POST /api/v1/logs/import` (até 64 MB, gzip aceite via `Content-Encoding`), com validação do schema, do `format_version` e do SHA-256 recalculado. | Must | Log exportado e reimportado devolve 201 com o mesmo `sha256`; 1 amostra alterada devolve 422 `LOG_HASH_MISMATCH`; `format_version` = 2 devolve 422 `LOG_FORMAT_UNSUPPORTED`; 65 MB devolve 413 `PAYLOAD_TOO_LARGE`. |
| RF-19 | 🟡 O usuário deve poder comparar dois logs por `POST /api/v1/logs/compare`, que alinha as amostras de puxada por RPM em bins de 100 rpm e devolve `LogComparison` com deltas B − A de torque, potência, whp, lambda e EGT por bin e os resumos de pico. | Must | Dois logs idênticos devolvem deltas 0,0 em todos os bins; log B com torque +10 N·m constante devolve `delta_torque_nm` = 10,0 ± 0,05 em todos os bins comuns; sem bins comuns devolve 422 `LOG_COMPARE_NO_OVERLAP`. |
| RF-20 | 🟡 O sistema deve gerar o espectro do sensor de knock por frame (FFT com janela de Hann, N = 1024, fs = 51 200 Hz, 256 bins de 0 a 20 kHz em dB) quando `spectrum = true`, com a frequência de ressonância de Draper do veículo em `resonance_hz`. | Should | Para `hatch-20t-gdi` (B = 82,5 mm) com knock no cilindro 1 o bin de maior magnitude fica a ≤ 160 Hz de `resonance_hz[0]`; sem knock, nenhum bin ultrapassa o ruído de fundo + 6 dB. |
| RF-21 | 🟡 O sistema deve enviar o traço de pressão de 1 cilindro escolhido (`crank_deg` e `p_bar` do último `CombustionEvent`) a no máximo 10 Hz quando `pressure_trace` estiver subscrito. | Should | Com `pressure_trace = {cylinder: 2}` a 50 FPS, ≤ 10 frames por segundo trazem `cyl_pressure_trace`, todos com `cylinder = 2` e `len(crank_deg) == len(p_bar)`. |
| RF-22 | 🟡 O sistema deve aceitar `control.throttle` `{throttle_pct: 0..100}` e `control.ping` `{nonce}` do cliente, encaminhar o throttle ao `dyno-bench` pela fila de comandos do worker e responder com `error` `THROTTLE_LOCKED_BY_RUN` quando o `dyno-bench` recusar. | Must | `control.throttle` = 50 em `idle` altera `throttle_pct` do frame seguinte em ≤ 100 ms; em `running` chega `error` `THROTTLE_LOCKED_BY_RUN`; `control.ping` reinicia o timeout de inatividade de 30 s. |
| RF-23 | 🟡 O sistema deve incluir em cada `telemetry.frame` o objeto `stats` com `fps_actual`, `dropped_frames`, `dropped_events`, `real_time_factor` e `tick`. | Should | Com cliente lento forçado, `dropped_frames` cresce monotonicamente; `real_time_factor` fica entre 0,99 e 1,01 com o laço em tempo real. |
| RF-24 | 🟡 O sistema deve rejeitar mensagens do cliente com JSON inválido, `type` desconhecido ou acima de 16 kB com `error` `WS_MESSAGE_INVALID`, e fechar a conexão com 1008 após 20 mensagens inválidas em 10 s. | Must | 1 mensagem malformada gera 1 `error` e a conexão continua; 21 mensagens malformadas em 10 s fecham com 1008. |
| RF-25 | 🟡 O sistema deve atribuir a cada envelope enviado pelo servidor, de qualquer `type` (incluindo `error`), o valor `seq` = último `seq` da sessão + 1, sem nunca reutilizar um valor. | Must | Teste: 1 subscrição inválida entre 2 frames gera a sequência `seq` n, n+1 (`error`), n+2 (frame); 0 valores repetidos em 10 000 envelopes com 50 erros injetados. |

### 6.2 Fluxo Principal (Happy Path)

1. 🟡 O usuário abre a cockpit; o sistema aceita o WebSocket `/ws/v1/sessions/{session_id}/telemetry`, envia o snapshot `run.state` atual e passa a emitir frames com o conjunto padrão de canais (`rpm`, `map_kpa`, `lambda`, `torque_nm`, `power_kw`).
2. 🟡 O cliente envia `control.subscribe` com os canais dos painéis visíveis, `fps = 50` e `spectrum = true`; o sistema confirma aplicando a subscrição a partir do frame seguinte.
3. 🟡 O usuário inicia a puxada pelo REST do `dyno-bench`; o sistema publica `run.state` = `arming` e o datalogger abre o buffer colunar da puxada no worker.
4. 🟡 A cada tick, o worker entrega `EngineState`, `SensorReadings`, `ActuatorCommands`, `EcuStatus`, `EcuEvent`, `DamageState` e `DynoLoad` ao `TelemetrySampler`, que grava 1 amostra no log e atualiza o acumulador da janela do frame.
5. 🟡 Na fronteira de frame, o sistema fecha a janela, aplica as agregações por canal, calcula o espectro e publica o `telemetry.frame` na fila de saída do worker; o event loop filtra por subscrição e envia a cada conexão.
6. 🟡 Quando a ECU deteta knock ou bate no limitador, o sistema publica `event.knock` e `event.limiter` com o `t_sim_s` do tick de origem.
7. 🟡 O `dyno-bench` publica `run.state` = `completed`; o sistema fecha o log, calcula o SHA-256, grava `/data/logs/{run_id}.simlog.gz` e regista a linha `datalog`.
8. 🟡 O usuário exporta o log em CSV e compara com a puxada base por `POST /api/v1/logs/compare`.
9. 🟡 Resultado: o usuário vê as curvas e os eventos ao vivo, tem o log completo e verificável por SHA-256 e a comparação por bins de 100 rpm.

### 6.3 Fluxos Alternativos

**Fluxo Alternativo A — Reconexão com resume:**
1. 🟡 A conexão cai durante a puxada; o cliente reconecta com `?resume_from_seq=<último seq aceito>`.
2. 🟡 O sistema envia o `run.state` atual, reenvia os eventos com `seq` maior que o pedido ainda no buffer de replay e retoma os frames ao vivo; a subscrição anterior não é restaurada e o cliente reenvia `control.subscribe`.
3. 🟡 Se o `seq` pedido for anterior ao buffer, o sistema envia `error` `WS_RESUME_GAP` com `oldest_available_seq` e continua ao vivo; o log no servidor fica íntegro.

**Fluxo Alternativo B — Falha catastrófica durante a puxada:**
1. 🟡 O `knock-and-failure-model` emite `FailureEvent` catastrófico (ex.: `piston_failure`).
2. 🟡 O sistema publica `event.failure` no mesmo tick, grava o evento no log e continua a gravar até o `run.state` = `engine_failed`.
3. 🟡 O log fica disponível para export e para o `ForensicReport`, com `terminal_state = engine_failed`.

**Fluxo Alternativo C — Import e comparação pelo instrutor:**
1. 🟡 Prof. Marcos importa o JSON de um aluno; o sistema valida schema, versão e SHA-256 e devolve 201 com `log_id` prefixado `imp-`.
2. 🟡 O instrutor compara o log importado com o log base; o sistema devolve `LogComparison` com `vehicle_mismatch = false` e os deltas por bin.

**Fluxo Alternativo D — Cliente lento:**
1. 🟡 O navegador processa frames abaixo de 50 FPS; a fila da conexão enche.
2. 🟡 O sistema descarta o frame mais antigo da conexão, mantém os eventos e o cliente vê saltos de `seq`; o worker e as outras conexões não são afetados.

---

## 7. Requisitos Não-Funcionais

| ID | Requisito | Valor alvo | Observação |
|----|-----------|-----------|------------|
| RNF-01 | 🟡 Custo do sampler no worker | ≤ 60 µs por tick (p95) a 1000 Hz com 8 cilindros | 🟡 Medido com `pytest-benchmark`; gravação colunar em `numpy` pré-alocado por blocos de 1 s; sem alocação de objetos Pydantic por tick. |
| RNF-02 | 🟡 Latência tick→envio | ≤ 40 ms (p95), ≤ 80 ms (p99) | 🟡 Do fim da janela do frame no worker até `send_text` no event loop, com 1 sessão e 2 conexões. |
| RNF-03 | 🟡 Banda por conexão | ≤ 150 kB/s com a subscrição completa da cockpit e espectro a 50 FPS | 🟡 JSON compacto; floats arredondados aos decimais do catálogo; espectro em dB com 1 casa decimal. |
| RNF-04 | 🟡 Isolamento do laço | ≥ 99 % de `sim_hz` com 4 conexões, 2 delas sem leitura durante 60 s | 🟡 Herdado de RF-12 da `platform-foundation`: filas limitadas, descarte do mais antigo, nenhum `await` dentro do worker. |
| RNF-05 | 🟡 Memória do log em curso | ≤ 120 MB por puxada (duração máxima gravada 300 s a 1000 Hz, ≤ 100 canais float32) | 🟡 Acima de 300 s o log marca `truncated = true` e para de gravar amostras, mantendo eventos. |
| RNF-06 | 🟡 Tempo de export e compare | Export CSV de 15 s a 1000 Hz ≤ 1,5 s; compare de 2 logs de 15 s ≤ 500 ms | 🟡 Export em streaming (`StreamingResponse`), sem montar o CSV inteiro em memória. |
| RNF-07 | 🟡 Determinismo | 100 % de hashes iguais entre execuções e entre SQLite/PostgreSQL | 🟡 O hash depende só do arquivo de log e do cabeçalho canónico, nunca do banco. |
| RNF-08 | 🟡 Cobertura de testes | ≥ 85 % no pacote `simremap.telemetry` | 🟡 Portão do CI da fundação (pytest-cov, mypy --strict, ruff, bandit). |

---

## 8. Design e Interface

**Componentes afetados:**
- 🟡 `backend/src/simremap/telemetry/`: `channels.py` (catálogo), `sampler.py` (`TelemetrySampler` no worker), `decimator.py`, `spectrum.py` (FFT e Draper), `datalog.py` (escrita, leitura, hash), `compare.py`, `broadcaster.py` (event loop, filas por conexão, resume), `contracts.py`.
- 🟡 `backend/src/simremap/api/routers/telemetry.py`: WS e endpoints REST; `backend/src/simremap/db/models/datalog.py` + migração Alembic.
- 🟡 Consumidores: `frontend/src/lib/ws/` (`TelemetrySocket` do `dyno-cockpit-ui`, partilhado com `ecu-tuning-ui`), `features/dyno-cockpit/DataloggerPanel`.

**Endpoints REST (caminhos completos sob o prefixo `/api/v1/`, erros `application/problem+json` com `code`):**

| Método e caminho | Request | Resposta | Erros |
|------------------|---------|----------|-------|
| 🟡 `GET /api/v1/telemetry/channels?vehicle_id=` | query `vehicle_id` obrigatório | 200 `list[ TelemetryChannel ]` expandido para o veículo | 404 `VEHICLE_NOT_FOUND`, 422 `VALIDATION_FAILED` |
| 🟡 `GET /api/v1/runs/{run_id}/log?format=json` | query `format` (`json` padrão ou `csv`), `channels` opcional (lista separada por vírgula, só CSV), `decimate` opcional (inteiro 1–100, só CSV) | 200 `application/json` (`DataLog`) ou `text/csv; charset=utf-8`, cabeçalho `X-Log-Sha256` | 404 `RUN_NOT_FOUND`, 404 `LOG_NOT_FOUND`, 409 `LOG_NOT_READY`, 422 `VALIDATION_FAILED`, 500 `LOG_CORRUPTED` |
| 🟡 `POST /api/v1/logs/import` | `application/json` com `DataLog` (≤ 64 MB, `Content-Encoding: gzip` opcional) | 201 `DataLogSummary` (`log_id`, `sha256`, `n_samples`, `vehicle_id`, `source = imported`) | 413 `PAYLOAD_TOO_LARGE`, 415 `UNSUPPORTED_MEDIA_TYPE`, 422 `LOG_SCHEMA_INVALID`, 422 `LOG_FORMAT_UNSUPPORTED`, 422 `LOG_HASH_MISMATCH`, 409 `LOG_ALREADY_IMPORTED`, 507 `STORAGE_FULL` |
| 🟡 `POST /api/v1/logs/compare` | `LogCompareRequest` | 200 `LogComparison` | 404 `LOG_NOT_FOUND`, 409 `LOG_NOT_READY`, 422 `LOG_COMPARE_NO_OVERLAP`, 422 `VALIDATION_FAILED` |

- 🟡 `LOG_ALREADY_IMPORTED` (409) devolve no `detail` o `log_id` existente com o mesmo `sha256`; o cliente pode usar esse `log_id` direto.
- 🟡 O CSV usa vírgula como separador, ponto decimal, `\n` como fim de linha, valores ausentes como campo vazio e flags como `0`/`1`; a 1.ª linha é o cabeçalho `nome (unidade)` e a seguir vem uma linha por amostra. Eventos não entram no CSV.

**WebSocket `/ws/v1/sessions/{session_id}/telemetry`:**
- 🟡 Query opcional: `resume_from_seq` (int ≥ 0). Sem subscrição explícita, o conjunto padrão é `rpm`, `map_kpa`, `lambda`, `torque_nm`, `power_kw`, sem espectro e sem traço.
- 🟡 Códigos de fecho: 1000 (sessão apagada), 1008 (abuso de mensagens inválidas), 1011 (erro interno), 4404 (`SESSION_NOT_FOUND`), 4408 (inatividade: 30 s sem leitura nem `control.ping`), 4429 (`WS_TOO_MANY_CONNECTIONS`).
- 🟡 O servidor envia ping do protocolo WebSocket a cada 15 s; `control.ping` só reinicia o timeout de inatividade e não tem resposta.
- 🟡 Todo envelope enviado pelo servidor, incluindo `error` local a 1 conexão (subscrição inválida, resume, rate limit), incrementa o contador da sessão (`seq` + 1) e nunca reutiliza um `seq` anterior (revisão R1). Por isso o `seq` serve para ordenação, deduplicação e resume; a perda de frames mede-se por salto de `payload.frame_index` nos envelopes `telemetry.frame`, nunca por salto de `seq`.

Exemplo `telemetry.frame`:

```json
{
  "v": 1, "type": "telemetry.frame", "seq": 18421, "t_sim_s": 37.420,
  "payload": {
    "session_id": "c3f1a2", "run_id": "r-01J9Z", "frame_index": 1871,
    "window_ticks": 20,
    "channels": {"rpm": 5012.0, "map_kpa": 231.4, "boost_bar": 1.32, "lambda": 0.82,
                 "knock_intensity_cyl3": 0.41, "egt_c": 884.0, "fuel_cut": 0},
    "knock_spectrum": {"bins_hz": [0.0, 78.125], "magnitude_db": [-62.1, -61.8],
                       "resonance_hz": [6720.0, 11147.0, 13987.0, 15334.0], "sensor": "block"},
    "cyl_pressure_trace": null,
    "stats": {"fps_actual": 50.0, "dropped_frames": 0, "dropped_events": 0,
              "real_time_factor": 1.0, "tick": 37420}
  }
}
```

🟡 `bins_hz` tem sempre 256 valores (o exemplo mostra 2 por brevidade de leitura); os clientes podem guardar `bins_hz` da 1.ª mensagem, já que ele não muda numa sessão.

Exemplo `event.knock`, `event.limiter` e `error`:

```json
{"v": 1, "type": "event.knock", "seq": 18422, "t_sim_s": 37.4213,
 "payload": {"run_id": "r-01J9Z", "cylinder": 3, "intensity": 0.41, "retard_deg": 2.0,
             "rpm": 5012.0, "p_max_bar": 118.6, "threshold": 0.15}}
{"v": 1, "type": "event.limiter", "seq": 19010, "t_sim_s": 41.002,
 "payload": {"run_id": "r-01J9Z", "kind": "rev_limiter", "phase": "hard", "active": true, "rpm": 7004.0}}
{"v": 1, "type": "error", "seq": 19011, "t_sim_s": 41.002,
 "payload": {"code": "WS_UNKNOWN_CHANNEL", "title": "Canal desconhecido",
             "detail": "egt_c_cyl9", "fatal": false}}
```

🟡 `event.failure` transporta o `FailureEvent` do `knock-and-failure-model` sem alteração de campos, mais `run_id`. `run.state` transporta o payload definido pelo `dyno-bench` sem alteração.

**Decimação e agregação (comportamento verificável):**
- 🟡 Fronteira: o tick k (contado desde o início da sessão) pertence ao frame `floor(k · fps / sim_hz)`; quando o índice do tick k+1 difere, o frame fecha. Com razão inteira (1000/50 = 20) cada frame tem 20 ticks; com razão não inteira (300/60 = 5, 1000/60 ≈ 16,67) as janelas alternam 16 e 17 ticks, sem deriva.
- 🟡 A `fps` é um parâmetro da sessão (padrão `Settings.ws_fps` = 50): todas as conexões da sessão recebem o mesmo fluxo de frames, e um `control.subscribe` com `fps` diferente altera a taxa da sessão a partir da fronteira de frame seguinte (último pedido vence). Assim cada conexão recebe todos os frames publicados e o salto de `frame_index` mede só perda real.
- 🟡 Agregações: `last` = valor do último tick da janela; `max` e `min` = extremos da janela ignorando `null`; `any` = 1 se algum tick tem a flag, senão 0; `sum` = soma da janela. Canal ausente em toda a janela é omitido de `channels` (não é enviado como 0).
- 🟡 Arredondamento só na serialização WS (decimais do catálogo); o log grava o float32 sem arredondar.

**Espectrograma de knock (dados, não desenho):**
- 🟡 Sinal sintético do sensor de bloco por frame: `s(t) = ruído_fundo(t) + Σ_cil Σ_modo A_cil · w_modo · exp(−t'/τ_d) · sin(2π f_modo t')`, com t' = tempo desde o início do knock do ciclo, `A_cil` proporcional à intensidade de knock do ciclo, τ_d = 1,0 ms (inferido, a validar), pesos dos modos w = (1,0; 0,5; 0,35; 0,25) e ruído gaussiano semeado com `seed`, `tick` e `cylinder` (σ = 0,02 V, inferido).
- 🟡 Ressonância de Draper: `f_mn = C · ρ_mn · c / (π · B)`, com B = diâmetro do cilindro (m, de `EngineSpec`), c = √(γ · R · T) a velocidade do som no gás (γ = 1,3; R = 287 J/(kg·K); T = 2400 K por padrão, inferido), ρ_mn = (1,841; 3,054; 3,832; 4,201) para os modos (1,0), (2,0), (0,1) e (3,0), e C = 1,0 (fator de correção empírico, 0,8–1,2). Para B = 82,5 mm: c ≈ 946 m/s, f_10 ≈ 6,72 kHz, f_20 ≈ 11,15 kHz, f_01 ≈ 13,99 kHz e f_30 ≈ 15,33 kHz.
- 🟡 FFT: fs = 51 200 Hz, N = 1024 amostras (20 ms, coerente com a janela de 50 FPS), janela de Hann, magnitude em dB re 1 V, redução para 256 bins de 0 a 20 kHz (largura 78,125 Hz) por média de potência dos bins da FFT.
- 🟡 O espectro só é calculado quando pelo menos 1 conexão tem `spectrum = true`; o log não grava o espectro, só as intensidades por cilindro (o espectro pode ser regenerado a partir do log e da `seed`).

**Estados expostos aos consumidores:**
- 🟡 Estado vazio: sessão sem puxada; frames continuam a sair (motor em marcha lenta ou parado) e `run_id = null`.
- 🟡 Estado de carregamento: log em gravação (`GET /api/v1/runs/{run_id}/log` devolve 409 `LOG_NOT_READY`).
- 🟡 Estado de erro: envelope `error` com `code`, `title`, `detail` e `fatal`; erros REST em `ProblemDetail`.
- 🟡 Estado de sucesso: log com `sha256`, disponível para export e comparação.

---

## 9. Modelo de Dados

🟡 Contratos Pydantic v2 em `simremap/telemetry/contracts.py`, `model_config = ConfigDict(frozen=True, extra="forbid")`. Índice de cilindro 1-based nos nomes de canal (`_cyl1` = cilindro 1); listas por cilindro dos contratos de física têm índice 0 = cilindro 1.

```python
from enum import StrEnum
from typing import Annotated, Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Aggregation(StrEnum):
    LAST = "last"; MAX = "max"; MIN = "min"; ANY = "any"; SUM = "sum"

class ChannelKind(StrEnum):
    SCALAR = "scalar"; FLAG = "flag"; PER_CYLINDER = "per_cylinder"

class TelemetryChannel(BaseModel):
    name: str = Field(pattern=r"^[ a-z ][ a-z0-9_ ]{1,47}$")   # nome expandido (ex.: egt_c_cyl3)
    base: str                                              # nome base (ex.: egt_c)
    cylinder: int | None = Field(None, ge=1, le=8)
    unit: str                                              # "rpm", "kPa", "bar", "-", "°BTDC", "°C", "N·m", "kW", "hp", "%"
    kind: ChannelKind
    aggregation: Aggregation
    decimals: int = Field(ge=0, le=4)                      # arredondamento só no WS
    min_value: float | None = None
    max_value: float | None = None
    source: str                                            # ex.: "EngineState.p_max_kpa/100"
    nullable: bool = False                                 # ex.: turbo_rpm em aspirado

class TelemetrySubscription(BaseModel):
    channels: list[ str ] = Field(min_length=1, max_length=128)
    fps: int = Field(50, ge=30, le=60)
    spectrum: bool = False
    pressure_trace: dict[ str, int ] | None = None        # {"cylinder": 1..n_cyl}

class KnockSpectrum(BaseModel):
    bins_hz: list[ float ] = Field(min_length=256, max_length=256)
    magnitude_db: list[ float ] = Field(min_length=256, max_length=256)
    resonance_hz: list[ float ] = Field(min_length=4, max_length=4)   # modos (1,0) (2,0) (0,1) (3,0)
    sensor: Literal["block"] = "block"

class PressureTrace(BaseModel):
    cylinder: int = Field(ge=1, le=8)
    crank_deg: list[ int ]                                 # ATDC, 1 ponto por grau
    p_bar: list[ float ]                                   # absoluta

class FrameStats(BaseModel):
    fps_actual: float
    dropped_frames: int = Field(ge=0)
    dropped_events: int = Field(ge=0)
    real_time_factor: float | None
    tick: int = Field(ge=0)

class TelemetryFrame(BaseModel):
    session_id: str
    run_id: str | None
    frame_index: int = Field(ge=0)
    window_ticks: int = Field(ge=1, le=34)
    channels: dict[ str, float | None ]                  # flags como 0/1
    knock_spectrum: KnockSpectrum | None = None
    cyl_pressure_trace: PressureTrace | None = None
    stats: FrameStats

WsType = Literal["telemetry.frame", "run.state", "event.knock",
                 "event.failure", "event.limiter", "error"]

class WsEnvelope(BaseModel):
    v: Literal[1] = 1
    type: WsType
    seq: int = Field(ge=0)            # contador único por sessão, partilhado por todos os tipos
    t_sim_s: float = Field(ge=0.0)    # do tick de origem
    payload: dict[ str, Any ]

ClientType = Literal["control.subscribe", "control.throttle", "control.ping"]

class WsClientMessage(BaseModel):
    v: Literal[1] = 1
    type: ClientType
    payload: dict[ str, Any ] = Field(default_factory=dict)   # ≤ 16 kB serializado

class KnockEventPayload(BaseModel):
    run_id: str | None
    cylinder: int = Field(ge=1, le=8)
    intensity: float = Field(ge=0.0)
    retard_deg: float = Field(ge=0.0)
    rpm: float
    p_max_bar: float
    threshold: float

class LimiterEventPayload(BaseModel):
    run_id: str | None
    kind: Literal["rev_limiter", "two_step", "overboost_cut", "antilag_protect", "overrun_protect"]
    phase: Literal["soft", "hard"] | None = None
    active: bool
    rpm: float

class WsErrorPayload(BaseModel):
    code: str = Field(pattern=r"^[ A-Z ][0-9A-Z_]{2,63}$")
    title: str
    detail: str = ""
    fatal: bool = False
    oldest_available_seq: int | None = None               # só WS_RESUME_GAP

class PullSegment(BaseModel):
    pull_index: int = Field(ge=1)
    start_index: int = Field(ge=0)        # índice de amostra inclusivo
    end_index: int = Field(ge=0)          # exclusivo
    state: str                            # RunState do dyno-bench ao fim da puxada

class LogEvent(BaseModel):
    index: int = Field(ge=0)              # índice da amostra do tick do evento
    type: Literal["event.knock", "event.failure", "event.limiter", "run.state"]
    payload: dict[ str, Any ]

class DataLogHeader(BaseModel):
    format_version: Literal[1] = 1        # DATALOG_FORMAT_VERSION da fundação
    run_id: str
    session_id: str
    vehicle_id: str
    profile_id: str
    calibration_hash: str                 # SHA-256 da calibração (ecu-core)
    fuel_id: str
    seed: int
    sim_hz: int = Field(ge=100, le=1000)
    start_tick: int = Field(ge=0)
    n_samples: int = Field(ge=0)
    channels: list[ TelemetryChannel ]    # ordem = ordem das colunas
    pulls: list[ PullSegment ]
    events: list[ LogEvent ]
    terminal_state: str                   # completed | aborted | engine_failed
    truncated: bool = False

class DataLog(BaseModel):
    header: DataLogHeader
    t_sim_s: list[ float ]                # len == n_samples
    data: dict[ str, list[ float | None ] ]   # chave = TelemetryChannel.name; null = ausente
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    # metadados voláteis, fora do hash:
    log_id: str | None = None
    created_at: str | None = None         # ISO-8601 UTC
    source: Literal["simulated", "imported"] = "simulated"

    @model_validator(mode="after")
    def _lengths(self) -> "DataLog":
        n = self.header.n_samples
        names = [ c.name for c in self.header.channels ]
        if len(self.t_sim_s) != n or list(self.data) != names or any(len(v) != n for v in self.data.values()):
            raise ValueError("LOG_SCHEMA_INVALID")
        return self

class DataLogSummary(BaseModel):
    log_id: str
    run_id: str | None
    vehicle_id: str
    sha256: str
    n_samples: int
    sim_hz: int
    source: Literal["simulated", "imported"]

class LogRef(BaseModel):
    run_id: str | None = None
    log_id: str | None = None             # um e só um dos dois

class LogCompareRequest(BaseModel):
    a: LogRef                             # referência (ex.: puxada base)
    b: LogRef                             # candidata
    bin_rpm: int = Field(100, ge=50, le=500)
    pull_index_a: int | None = None       # None = 1.ª puxada do log
    pull_index_b: int | None = None
    min_samples_per_bin: int = Field(5, ge=1, le=1000)

class ComparisonBin(BaseModel):
    rpm_bin: int                          # limite inferior do bin
    torque_nm_a: float; torque_nm_b: float; delta_torque_nm: float
    power_kw_a: float; power_kw_b: float; delta_power_kw: float
    whp_a: float; whp_b: float; delta_whp: float
    lambda_a: float | None; lambda_b: float | None; delta_lambda: float | None
    egt_c_a: float; egt_c_b: float; delta_egt_c: float
    knock_intensity_max_a: float; knock_intensity_max_b: float
    n_a: int; n_b: int

class LogComparison(BaseModel):
    a: DataLogSummary
    b: DataLogSummary
    bin_rpm: int
    vehicle_mismatch: bool
    bins: list[ ComparisonBin ]           # só bins comuns, ordem crescente de rpm
    peak_torque_nm_a: float; peak_torque_nm_b: float
    peak_whp_a: float; peak_whp_b: float
    delta_peak_whp_pct: float
    max_abs_delta: dict[ str, float ]     # por métrica: torque_nm, power_kw, whp, lambda, egt_c
    bins_only_in_a: int; bins_only_in_b: int
```

**Catálogo `TelemetryChannel` (nomes canónicos; `<k>` = 1..n_cyl):**

| Canal | Unidade | Agregação | Decimais | Fonte |
|-------|---------|-----------|----------|-------|
| 🟡 `rpm` | rpm | last | 0 | `EngineState.rpm` |
| 🟡 `map_kpa` | kPa (abs) | last | 1 | `SensorReadings.map_kpa` |
| 🟡 `baro_kpa` | kPa (abs) | last | 1 | `SensorReadings.baro_kpa` |
| 🟡 `boost_bar` | bar (rel) | last | 2 | `(map_kpa − baro_kpa) / 100` |
| 🟡 `lambda_cyl<k>` | – | last | 3 | `EngineState.lambda_cyl[ k−1 ]` (null em corte) |
| 🟡 `lambda` | – | last | 3 | média dos `lambda_cyl` não nulos (null se todos nulos) |
| 🟡 `lambda_measured` | – | last | 3 | `SensorReadings.lambda_measured` (sensor com atraso) |
| 🟡 `afr` | – | last | 2 | `lambda × afr_stoich` do `FuelSpec` (E27 13,2; E100 9,0; E0 14,7; Podium 14,4) |
| 🟡 `spark_deg_cyl<k>` | °BTDC | last | 1 | `ActuatorCommands.ignition_advance_deg[ k−1 ]` |
| 🟡 `knock_intensity_cyl<k>` | – (0,0–1,0) | max | 3 | `SensorReadings.knock_intensity[ k−1 ]` (índice normalizado derivado de `knock_sensor_v`) |
| 🟡 `knock_sensor_v_cyl<k>` | V (0,0–5,0) | max | 3 | `SensorReadings.knock_sensor_v[ k−1 ]` (tensão do sensor de knock) |
| 🟡 `knock_retard_deg` | ° | max | 1 | `max(EcuStatus.knock_retard_deg)` |
| 🟡 `knock_retard_deg_cyl<k>` | ° | max | 1 | `EcuStatus.knock_retard_deg[ k−1 ]` |
| 🟡 `cyl_pressure_peak_bar_cyl<k>` | bar (abs) | max | 1 | `EngineState.p_max_kpa[ k−1 ] / 100` |
| 🟡 `cyl_pressure_peak_bar` | bar (abs) | max | 1 | máximo entre cilindros |
| 🟡 `egt_c_cyl<k>` | °C | max | 0 | `SensorReadings.egt_c[ k−1 ]` (termopar) |
| 🟡 `egt_c` | °C | max | 0 | máximo de `egt_c_cyl<k>` (canal dos gauges) |
| 🟡 `egt_pre_turbo_c` | °C | max | 0 | `SensorReadings.egt_collector_c` |
| 🟡 `iat_c`, `ect_c`, `oil_temp_c` | °C | last | 1 | `SensorReadings` |
| 🟡 `turbo_rpm` | rpm | last | 0 | `SensorReadings.turbo_rpm` (nullable) |
| 🟡 `wastegate_duty_pct` | % | last | 1 | `ActuatorCommands.wastegate_duty_pct` |
| 🟡 `injector_duty_pct` | % | max | 1 | `EcuStatus.inj_duty_pct` (= pw_ms / (120 000 / rpm) × 100) |
| 🟡 `torque_nm` | N·m | last | 1 | `EngineState.torque_nm` (cambota) |
| 🟡 `power_kw` | kW | last | 2 | `EngineState.power_kw` |
| 🟡 `whp` | hp | last | 1 | `EngineState.whp` (roda, 1 hp = 0,7457 kW) |
| 🟡 `throttle_pct` | % | last | 1 | `SensorReadings.tps_pct` |
| 🟡 `load_pct` | % | last | 1 | carga do perfil OEM (`EcuStatus`, nullable fora do `oem-stage`) |
| 🟡 `torque_request_nm` | N·m | last | 1 | pedido de torque do perfil OEM (nullable) |
| 🟡 `lambda_target` | – | last | 3 | `EcuStatus.lambda_target` |
| 🟡 `boost_target_kpa` | kPa (abs) | last | 1 | `EcuStatus.boost_target_kpa` |
| 🟡 `fuel_cut` | flag | any | 0 | `any(ActuatorCommands.fuel_cut)` |
| 🟡 `ign_cut` | flag | any | 0 | `any(ActuatorCommands.spark_cut)` |
| 🟡 `overrun_afterfire` | contagem | sum | 0 | nº de `CombustionEvent.pop_event` na janela |
| 🟡 `roller_speed_kmh` | km/h | last | 1 | estado do rolo do `dyno-bench` |
| 🟡 `health_<componente>_pct` | % | min | 1 | `DamageState` por componente (pistão, biela, turbo, junta, válvulas; por cilindro quando aplicável) |
| 🟡 `health_min_pct` | % | min | 1 | menor saúde entre componentes |
| 🟡 `real_time_factor` | – | last | 3 | `EngineState.real_time_factor` |

🟡 Canais compostos (não escalares, fora do log): `knock_spectrum` (habilitado por `spectrum = true`) e `cyl_pressure_trace` (habilitado por `pressure_trace`). A cockpit subscreve-os pelos nomes que já usa; no `control.subscribe` os dois nomes em `channels` equivalem a `spectrum = true` e `pressure_trace = {cylinder: 1}`.

**Formato do arquivo `/data/logs/{run_id}.simlog.gz`:**
- 🟡 Conteúdo antes do gzip: `b"SIMLOG1\n"` + 4 bytes (uint32 LE, tamanho do cabeçalho) + cabeçalho canónico UTF-8 + coluna `t_sim_s` (float64 LE) + 1 coluna float32 LE por canal na ordem do cabeçalho (ausente = NaN quiet `0x7FC00000`) + 64 bytes do `sha256` em hexadecimal ASCII.
- 🟡 Cabeçalho canónico: `json.dumps(header.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)`; floats do cabeçalho (payloads de eventos) arredondados a 6 casas antes da serialização.
- 🟡 Hash: `sha256(cabeçalho_canónico_utf8 + t_sim_s_float64_le + Σ colunas_float32_le)`; `log_id`, `created_at` e `source` ficam fora do hash.
- 🟡 Conversão JSON: cada valor float32 é escrito com `repr(float(np.float32(v)))`, que faz round-trip exato para float32; NaN vira `null`. O import converte de volta para float32 e recalcula o hash, por isso o round-trip export → import preserva o `sha256`.

**Algoritmo de comparação (`POST /api/v1/logs/compare`):**
1. 🟡 O sistema seleciona o segmento de puxada (`pull_index`, padrão o 1.º) e só as amostras com `run.state` = `running` e derivada de `rpm` ≥ 0 (puxada ascendente).
2. 🟡 O sistema atribui cada amostra ao bin `floor(rpm / bin_rpm) · bin_rpm` e descarta bins com menos de `min_samples_per_bin` amostras.
3. 🟡 Por bin: média aritmética de `torque_nm`, `power_kw`, `whp` e `lambda`; média de `egt_c`; máximo de `knock_intensity_cyl<k>`.
4. 🟡 Deltas = B − A nos bins comuns; `delta_peak_whp_pct = (peak_whp_b − peak_whp_a) / peak_whp_a × 100`; `vehicle_mismatch = (vehicle_id_a ≠ vehicle_id_b)`, que gera resposta 200 com a flag e não erro.

**Entidade persistida (SQLModel `datalog`):**

```python
class DatalogRow(SQLModel, table=True):
    __tablename__ = "datalog"
    log_id: str = Field(primary_key=True)              # = run_id para logs simulados; "imp-" + 12 hex para importados
    run_id: str | None = Field(default=None, index=True)
    session_id: str | None = None
    vehicle_id: str = Field(index=True)
    sha256: str = Field(index=True, unique=True, max_length=64)
    format_version: int = 1
    sim_hz: int
    n_samples: int
    n_channels: int
    compressed_bytes: int
    path: str                                          # relativo a Settings.data_dir
    terminal_state: str
    truncated: bool = False
    source: str = "simulated"                         # simulated | imported
    created_at: datetime
```

**Migrações necessárias:** 🟡 Sim. Migração Alembic `telemetry_0001_datalog` cria a tabela `datalog` com índices em `run_id`, `vehicle_id` e `sha256` (único); sem alteração de tabelas de outros componentes.

---

## 10. Integrações e Dependências

| Dependência | Tipo | Impacto se indisponível |
|-------------|------|------------------------|
| 🟡 `platform-foundation` (`SimWorkerHost`, filas limitadas, `Settings.ws_fps`, `data_dir`, catálogo de erros, `DATALOG_FORMAT_VERSION`) | Obrigatória | Sem worker não há telemetria; o WS fecha com 1011 e o REST de logs continua a servir logs gravados. |
| 🟡 `dyno-bench` (`SimTask` chama o sampler no passo 5 do tick; `run.state`; `DynoRun`; estado do rolo; throttle) | Obrigatória | Sem `dyno-bench` não há sessão nem puxada; o WS devolve 4404. |
| 🟡 `engine-physics-core` (`EngineState`, `SensorReadings`, `ActuatorCommands`, `CombustionEvent`) | Obrigatória | Sem eles não há canais; o sampler não é construído. |
| 🟡 `ecu-core` (`EcuStatus`, `EcuEvent`) | Opcional | Sem snapshot: `knock_retard_deg`, `lambda_target`, `load_pct` saem nulos e `event.limiter` não é emitido; o resto funciona. |
| 🟡 `knock-and-failure-model` (`KnockSignal`, `DamageState`, `FailureEvent`) | Opcional | Sem modelo: intensidades 0, saúde 100 % e nenhum `event.failure`. |
| 🟡 `vehicle-catalog` (`EngineSpec.bore_mm`, `n_cyl`, `FuelSpec.afr_stoich`) | Obrigatória | Sem diâmetro, `resonance_hz` sai vazio e o espectro é desligado com `error` não fatal `SPECTRUM_UNAVAILABLE`. |
| 🟡 Consumidores `dyno-cockpit-ui`, `ecu-tuning-ui`, `training-scenarios` | Consumidor | Sem consumidor WS a puxada e o log continuam. |
| 🟡 NumPy ≥ 2.0 (colunas e FFT), `gzip`/`hashlib` da biblioteca padrão | Obrigatória | Sem fallback; versão fixada no `uv.lock`. |

---

## 11. Edge Cases e Tratamento de Erros

| Cenário | Trigger | Comportamento esperado |
|---------|---------|----------------------|
| 🟡 EC-01: Cliente lento | Navegador consome < 50 FPS ou rede congestionada | Fila da conexão (8 frames) descarta o mais antigo; `stats.dropped_frames` cresce; eventos e `run.state` preservados; worker sem impacto (≥ 99 % de `sim_hz`). |
| 🟡 EC-02: Cliente parado | Nenhuma leitura nem `control.ping` por 30 s (timeout) | O sistema fecha com 4408; o cliente reconecta com resume; o log não é afetado. |
| 🟡 EC-03: Fila de saída do worker cheia | Event loop atrasado > 256 itens | Política "descartar o mais antigo" da fundação só para frames; `run.state`, `event.failure` e fecho de log seguem por canal de controlo dedicado sem descarte (capacidade 64, bloqueio proibido: se cheio, o worker marca `telemetry_degraded` no `DynoRun`). |
| 🟡 EC-04: Resume fora do buffer | `resume_from_seq` anterior ao evento mais antigo do buffer de replay | `error` não fatal `WS_RESUME_GAP` com `oldest_available_seq`; frames ao vivo continuam; o cliente obtém o histórico pelo REST do log no fim da puxada. |
| 🟡 EC-05: `resume_from_seq` no futuro | Valor maior que o `seq` atual (ex.: sessão recriada) | `error` não fatal `WS_RESUME_INVALID`; o sistema trata como conexão nova sem replay. |
| 🟡 EC-06: Subscrição inválida | Canal inexistente, `fps` fora de 30–60, cilindro do traço > n_cyl | `error` `WS_UNKNOWN_CHANNEL`, `WS_FPS_OUT_OF_RANGE` ou `WS_CYLINDER_OUT_OF_RANGE`; partes válidas aplicadas; conexão mantida. |
| 🟡 EC-07: Falha de escrita do log | Disco cheio ou permissão negada em `/data/logs` | Retry 3 vezes (0,2 s, 0,5 s, 1 s); depois `DynoRun` com aviso `log_write_failed`, log mantido em memória até 60 s para retry por export e `STORAGE_FULL` (507) no export se o retry falhar. |
| 🟡 EC-08: Arquivo de log corrompido | Gzip inválido ou hash recalculado ≠ `datalog.sha256` | Export devolve 500 `LOG_CORRUPTED`; log JSON `datalog.corrupted` com `run_id`; compare devolve o mesmo `code`. |
| 🟡 EC-09: Import com hash divergente | JSON editado à mão ou truncado | 422 `LOG_HASH_MISMATCH` com `expected` e `computed` no `detail`; nada é gravado. |
| 🟡 EC-10: Import de versão futura | `format_version` > 1 | 422 `LOG_FORMAT_UNSUPPORTED`, conforme a regra de compatibilidade da fundação. |
| 🟡 EC-11: Import duplicado | Mesmo `sha256` já existe | 409 `LOG_ALREADY_IMPORTED` com o `log_id` existente; nenhuma escrita. |
| 🟡 EC-12: Compare sem sobreposição | Faixas de RPM sem bin comum ou log `steady_state_hold` sem varrimento | 422 `LOG_COMPARE_NO_OVERLAP` com as faixas de cada log no `detail`. |
| 🟡 EC-13: Compare entre veículos diferentes | `vehicle_id` de A ≠ B | 200 com `vehicle_mismatch = true`; a UI mostra o aviso. |
| 🟡 EC-14: Puxada mais longa que 300 s | `steady_state_hold` longo | O sistema para de gravar amostras, marca `truncated = true` e continua a gravar eventos; WS sem alteração. |
| 🟡 EC-15: Sessão apagada com WS aberto | `DELETE /api/v1/sessions/{session_id}` | O sistema envia `run.state` final se havia puxada, fecha com 1000 e liberta buffers em ≤ 1 s. |
| 🟡 EC-16: Worker morre | Heartbeat ausente por 2 s (`worker.crashed`) | `error` fatal `SIM_WORKER_UNAVAILABLE`, fecho 1011; log parcial descartado (indisponível) e `GET /api/v1/runs/{run_id}/log` devolve 404 `LOG_NOT_FOUND`. |
| 🟡 EC-17: Valor não finito | NaN ou infinito vindo da física | O sampler grava NaN no log, envia `null` no frame e regista `telemetry.non_finite` com o canal (no máximo 1 log por canal por puxada). |
| 🟡 EC-18: Abuso de mensagens | > 20 mensagens inválidas em 10 s ou > 100 mensagens/s | `error` `WS_RATE_LIMITED`, depois fecho 1008. |
| 🟡 EC-19: Motor sem turbo | `muscle-v8-sc` ou aspirado | `turbo_rpm` e `wastegate_duty_pct` nulos (nullable); subscrição aceite sem erro. |

---

## 12. Segurança e Privacidade

- **Autenticação:** 🟡 Nenhuma no MVP (container local por estação, NG-06). O WebSocket valida o cabeçalho `Origin` contra a origem do servidor e fecha com 4403 (`WS_ORIGIN_FORBIDDEN`) em origem diferente.
- **Autorização:** 🟡 Qualquer cliente da estação acede às suas sessões; `session_id` e `run_id` são identificadores opacos (UUID/ULID) e não sequenciais.
- **Dados sensíveis:** 🟡 Logs não contêm PII: só IDs técnicos, `nickname` nunca entra no `DataLog`. O import valida tamanho (64 MB), profundidade JSON (≤ 32) e número de canais (≤ 256) antes de alocar memória, e grava só no diretório `data_dir/logs` com nome gerado pelo servidor (nunca caminho vindo do cliente).
- **Integridade:** 🟡 O SHA-256 garante integridade contra alteração acidental ou edição à mão; não é assinatura de autoria (a assinatura de pacotes pertence ao `training-scenarios`).
- **Auditoria:** 🟡 Logs JSON estruturados: `telemetry.ws.open`, `telemetry.ws.close` (código, duração, `dropped_frames`), `datalog.written` (`run_id`, `sha256`, bytes), `datalog.imported`, `datalog.compare`, sem IP do cliente.

---

## 13. Plano de Rollout

- **Estratégia:** 🟡 Entrega no Sprint 3 atrás da flag `SIMREMAP_FEATURE_TELEMETRY` (padrão ligada em dev e staging). Ordem interna: 1) catálogo + sampler + log + hash; 2) WS com decimação, subscrição e backpressure; 3) eventos e resume; 4) export, import e compare; 5) espectro e traço de pressão.
- **Como reverter (rollback):** 🟡 Desligar a flag remove o router WS e os endpoints de log; o `dyno-bench` continua a gravar `DynoRun` sem log (aviso `telemetry_degraded`). A migração `telemetry_0001_datalog` tem `downgrade` que apaga só a tabela `datalog`; os arquivos em `/data/logs` ficam intactos.
- **Monitoramento pós-deploy:** 🟡 Painel de diagnóstico da cockpit (FPS, perdas); métricas em log: `fps_actual` médio por conexão, `dropped_frames` por minuto, latência tick→envio p95, `real_time_factor` e tempo de escrita do log. Alerta de regressão no CI se o benchmark do sampler passar de 60 µs/tick.

---

## 14. Open Questions

| # | Pergunta | Impacto | Dono | Prazo |
|---|---------|---------|------|-------|
| OQ-01 | 🟡 Resolvida na revisão R1 (2026-10-18): a telemetria lê `knock_sensor_v` e `knock_intensity` do `SensorReadings`; os ids de componente de `DamageState` são `piston:i`, `rod:i`, `valves:i`, `head_gasket`, `bearings` e `turbo:turbine` (knock-and-failure-model). | Alto | George | 2026-10-25 |
| OQ-02 | 🟡 Resolvida na revisão R1 (2026-10-18): o `EcuStatus` do `ecu-core` passa a incluir `load_pct` e `torque_request_nm`. | Médio | George | 2026-10-25 |
| OQ-03 | 🟡 Os valores inferidos do espectro (T = 2400 K, C = 1,0, τ_d = 1,0 ms, σ do ruído) precisam de validação contra literatura aberta antes do Sprint 4? ⚠️ ABERTO | Médio | George | 2026-11-01 |
| OQ-04 | 🟡 O `dyno-bench` expõe o estado do rolo (`roller_speed_kmh`) no `DynoLoad` ou num snapshot próprio? ⚠️ ABERTO | Baixo | George | 2026-10-25 |
| OQ-05 | 🟡 Resolvida na revisão R1 (2026-10-18): `GET /api/v1/telemetry/channels` entra no catálogo consolidado de endpoints da `platform-foundation` (dono: telemetry-datalogger). | Baixo | George | 2026-10-22 |
| OQ-06 | 🟡 O CSV deve ter opção de separador `;` e vírgula decimal para Excel em pt-BR? ⚠️ ABERTO | Baixo | George | 2026-11-08 |
| OQ-07 | 🟡 Resolvida na revisão R1 (2026-10-18): todo envelope do servidor, incluindo `error`, recebe `seq` + 1; a EC-03 da cockpit não descarta erros e a perda mede-se por `frame_index`. | Médio | George | 2026-10-25 |

---

## 15. Decisões Tomadas (Decision Log)

| Decisão | Alternativas consideradas | Racional |
|---------|--------------------------|---------|
| 🟡 Decimação e agregação no worker; filtro por subscrição no event loop | Enviar cada tick ao event loop e decimar lá | 🟡 Reduz o tráfego worker→loop de 1000 para 50 itens/s; o filtro por conexão é barato e fica perto do socket. |
| 🟡 `seq` único por sessão, atribuído antes do descarte | `seq` por conexão | 🟡 Permite resume entre conexões e deteção de perda real; compatível com a cockpit, que reinicia a referência a cada conexão. |
| 🟡 Resume reenvia só eventos e `run.state`, nunca frames | Replay de frames | 🟡 Frames antigos não têm valor ao vivo e custam banda; o histórico completo vem do `DataLog` (NG-07). |
| 🟡 Agregação `max` para knock, EGT, pressão de pico, retardo e duty; `min` para saúde; `any` para flags | Último valor em todos os canais | 🟡 Um pico de knock de 1 tick não pode desaparecer na decimação; é o sinal que Lucas e Rodrigo precisam ver. |
| 🟡 Log colunar float32 + gzip, hash sobre bytes binários canónicos | JSON por amostra; Parquet; zstd | 🟡 float32 dá 7 dígitos (suficiente para sensores) e hash estável; gzip é da biblioteca padrão e open-source; Parquet e zstd acrescentam dependências. |
| 🟡 Conversão JSON por `repr(float(np.float32(v)))` | Arredondar a 6 casas | 🟡 Round-trip exato garante o mesmo SHA-256 após export → import (G-04). |
| 🟡 `fps` única por sessão (último `control.subscribe` vence) | `fps` por conexão com acumuladores separados | 🟡 Com `frame_index` único por sessão, fluxos de taxa diferente gerariam saltos falsos de `frame_index` nas outras conexões. |
| 🟡 `seq` monotônico da sessão para todo envelope do servidor, incluindo `error` (revisão R1) | `error` reutiliza o último `seq` | 🟡 Garante que a deduplicação por `seq` da cockpit (EC-03) nunca descarta uma mensagem de erro. |
| 🟡 Nenhum tipo novo de envelope (sem `pong`, sem `resumed`) | Acrescentar tipos ao `WsEnvelope` | 🟡 Mantém compatível o `Literal` de tipos já usado pela cockpit; o keepalive usa ping do protocolo WebSocket. |
| 🟡 Espectro sintético por modos de Draper a partir da intensidade de knock | FFT da pressão do cilindro simulada | 🟡 A física resolve 1° de cambota (sem conteúdo a 6–15 kHz); o modelo sintético é determinístico e barato. |

---

## Apêndice

### Referências
- 🟡 `_reversa_sdd/prd.md` (§3 métricas, §4 Telemetria, §8 riscos, §9 critérios de aceite).
- 🟡 `_reversa_sdd/personas.md` (Lucas, Rodrigo, Prof. Marcos).
- 🟡 Specs relacionadas: `platform-foundation.md` (worker, filas, erros, `DATALOG_FORMAT_VERSION`), `engine-physics-core.md` (`EngineState`, `SensorReadings`, `CombustionEvent`), `dyno-bench.md` (`run.state`, `DynoRun`, `THROTTLE_LOCKED_BY_RUN`), `ecu-core.md` (`EcuStatus`, `EcuEvent`), `dyno-cockpit-ui.md` e `ecu-tuning-ui.md` (consumidores).
- 🟡 Draper, C. S. (1938), "Pressure waves accompanying detonation in the internal combustion engine", J. Aeronautical Sciences (modos acústicos de cilindro, ρ_mn).
- 🟡 Heywood, J. B., "Internal Combustion Engine Fundamentals" (knock e velocidade do som no gás queimado).

### Catálogo de `code` de erro do componente

| Code | Status / canal | Quando |
|------|----------------|--------|
| 🟡 `LOG_NOT_FOUND` | 404 | Log inexistente ou descartado por falha do worker. |
| 🟡 `LOG_NOT_READY` | 409 | Puxada ainda em gravação. |
| 🟡 `LOG_CORRUPTED` | 500 | Gzip inválido ou hash divergente no disco. |
| 🟡 `LOG_SCHEMA_INVALID` | 422 | `DataLog` fora do schema, comprimentos inconsistentes, canal fora do catálogo. |
| 🟡 `LOG_FORMAT_UNSUPPORTED` | 422 | `format_version` > 1. |
| 🟡 `LOG_HASH_MISMATCH` | 422 | SHA-256 recalculado ≠ declarado. |
| 🟡 `LOG_ALREADY_IMPORTED` | 409 | `sha256` já existe. |
| 🟡 `LOG_COMPARE_NO_OVERLAP` | 422 | Nenhum bin de RPM comum. |
| 🟡 `SESSION_NOT_FOUND` | WS 4404 | Sessão inexistente (code do `dyno-bench`). |
| 🟡 `WS_TOO_MANY_CONNECTIONS` | WS 4429 | Mais de 4 conexões por sessão. |
| 🟡 `WS_ORIGIN_FORBIDDEN` | WS 4403 | `Origin` diferente da origem do servidor. |
| 🟡 `WS_MESSAGE_INVALID` | envelope `error` | JSON inválido, `type` desconhecido ou > 16 kB. |
| 🟡 `WS_UNKNOWN_CHANNEL` | envelope `error` | Canal fora do catálogo do veículo. |
| 🟡 `WS_FPS_OUT_OF_RANGE` | envelope `error` | `fps` fora de 30–60. |
| 🟡 `WS_CYLINDER_OUT_OF_RANGE` | envelope `error` | Cilindro do traço > n_cyl. |
| 🟡 `WS_RESUME_GAP` | envelope `error` | `resume_from_seq` anterior ao buffer de replay. |
| 🟡 `WS_RESUME_INVALID` | envelope `error` | `resume_from_seq` maior que o `seq` atual. |
| 🟡 `WS_RATE_LIMITED` | envelope `error` + 1008 | Abuso de mensagens. |
| 🟡 `SPECTRUM_UNAVAILABLE` | envelope `error` | Veículo sem `bore_mm`. |

### Exemplo de cabeçalho CSV

```
t_sim_s (s),tick (-),rpm (rpm),map_kpa (kPa),boost_bar (bar),lambda (-),lambda_cyl1 (-),spark_deg_cyl1 (°BTDC),knock_intensity_cyl1 (-),egt_c_cyl1 (°C),torque_nm (N·m),power_kw (kW),whp (hp),fuel_cut (flag)
```

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
- 🟡 Sugestões remanescentes: resolver OQ-01, OQ-02 e OQ-07 com os donos de `knock-and-failure-model`, `ecu-core` e `dyno-cockpit-ui` antes da implementação
- 🟡 Revisão R1 (2026-10-18): reavaliado após a revisão de consistência entre specs, score 100,0/100.
