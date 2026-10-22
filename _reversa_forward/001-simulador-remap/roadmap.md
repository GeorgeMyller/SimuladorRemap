# Roadmap: Simulador Completo de Remap Automotivo em Dinamômetro

> Identificador: `001-simulador-remap`
> Data: `2026-10-18`
> Requirements: `_reversa_forward/001-simulador-remap/requirements.md`
> Confidência: 🟢 CONFIRMADO, 🟡 INFERIDO, 🔴 LACUNA
> Nota: projeto greenfield. O "legado" é vazio; a âncora são `_reversa_sdd/prd.md` e as 11 specs `_reversa_sdd/sdd/*.md`. Todo item usa 🟡 por padrão, porque as fontes são specs planejadas. O selo 🔴 marca lacunas e benchmarks pendentes.

> ⚠️ **Aviso visível:** o `requirements.md` tem 3 marcadores `[DÚVIDA]` sem resposta (seção 10.1). O plan adota as propostas registradas lá como premissas 🟡 (seção 4). Rode `/reversa-clarify` para confirmar ou corrigir antes do Sprint 4.

## 1. Resumo da abordagem

🟡 O SimuladorRemap é um monólito modular em Python 3.12: uma aplicação FastAPI com 11 pacotes de domínio em `backend/src/simremap/{core,physics,damage,catalog,dyno,ecu,profiles,telemetry,scenarios,api,db}`.
🟡 A SPA React 18 + TypeScript + Vite é construída no Dockerfile e servida como estático pelo próprio FastAPI, com fallback SPA.
🟡 Cada estação executa um container próprio, local-first, sem rede de saída, publicado em `127.0.0.1:8000` e com SQLite em volume.
🟡 O laço físico de passo fixo (100–1000 Hz) corre num worker isolado do event loop asyncio: processo dedicado por sessão (padrão) com fallback para thread, decidido por benchmark no Sprint 1.
🟡 O worker conversa com o event loop só por filas limitadas; a saída tem uma faixa crítica sem descarte e uma faixa de frames com descarte do mais antigo.
🟡 A ordem de implementação é 9 → 1 → 3 → 4 → 2 → 5 → 6 → 7 → 11 → 10 → 8, em 4 sprints de 1 semana: Sprint 1 de 2026-10-19 a 2026-10-25, Sprint 2 de 2026-10-26 a 2026-11-01, Sprint 3 de 2026-11-02 a 2026-11-08 e Sprint 4 de 2026-11-09 a 2026-11-15.
🟡 Cada sprint fecha com uma demo verificável e com `make check` verde; os componentes entram atrás de feature flags.
🟡 O determinismo (mesma `seed` ⇒ mesmo SHA-256) é um contrato transversal; o desvio < 5 % contra `Reference Benchmark Baseline v1` é medido desde o Sprint 1 no `hatch-20t-gdi`.

## 2. Princípios aplicados

🟡 n/a: o projeto não tem `.reversa/principles.md`. A tabela aplica princípios derivados do PRD (`_reversa_sdd/prd.md#6-restrições`) como princípios de trabalho. Eles não substituem um `principles.md` futuro (trabalho de `/reversa-principles`).

| Princípio | Como a feature se relaciona | Status |
|-----------|------------------------------|--------|
| I. Zero PII | O único dado do usuário é o nickname; logs sem IP nem nickname; teste de varredura de campos em modelos e contratos (`platform-foundation` RF-20, `training-scenarios` RF-01). | respeita |
| II. Local-first | Um container por estação, sem conexões de saída, sem autenticação nem nuvem; a troca entre estações usa pacotes JSON com SHA-256 (`platform-foundation` NG-02, NG-04; `training-scenarios` RF-18). | respeita |
| III. Stack 100 % open-source e custo zero | Todas as dependências são open-source (FastAPI, NumPy, SQLite, React, uPlot, three.js, `rfc8785`); sem amostras de áudio licenciadas (`dyno-cockpit-ui` decisões). | respeita |
| IV. Nomes genéricos, sem marcas | Perfis `OEM-Stage`, `FT-Pro`, `M1-Race`, `HT-Elite`; lista de bloqueio testada no CI (`ecu-profiles` Apêndice G; `vehicle-catalog` RF-07). | respeita |
| V. Determinismo verificável | Tempo só por contagem de ticks; RNG semeado por canal; hashes SHA-256 da física, do dano, do datalog e da avaliação (`engine-physics-core` RF-20; `telemetry-datalogger` RNF-07; `training-scenarios` RF-11). | respeita |

## 3. Decisões técnicas

| ID | Decisão | Justificativa | Alternativas descartadas | Confidência |
|----|---------|----------------|--------------------------|-------------|
| D-01 | Monólito modular FastAPI num único processo de API, com 1 pacote Python por componente e registro único de routers (`simremap.api.registry.ROUTERS`). | Prazo de 4 semanas, 1 estação por container e contratos em processo; o `platform-foundation` já fixa o layout (`_reversa_sdd/sdd/platform-foundation.md#RF-01`, `#RF-03`). | Microsserviços por componente; containers separados para API e worker; plugins carregados dinamicamente. | 🟡 |
| D-02 | Frontend SPA React 18 + TypeScript strict + Vite + Tailwind, construído no estágio Node 20 do Dockerfile e servido pelo FastAPI (`SIMREMAP_STATIC_DIR`) com fallback SPA. | Sem SSR; um único processo a servir API e UI; mesma origem elimina CORS em prod (`platform-foundation` NG-05, RF-15). | Next.js com SSR; servidor Node separado; Create React App. | 🟡 |
| D-03 | Um container por estação, imagem única `linux/amd64` e `linux/arm64`, com `compose.yaml` + `compose.dev.yaml` + `compose.staging.yaml` + `compose.prod.yaml`; porta `127.0.0.1:8000`. | Paridade dev/staging/prod do PRD; a spec fixa os nomes `compose*.yaml` e prevalece sobre o `docker-compose.yml` genérico do brief (`platform-foundation` RF-17). | `docker-compose.yml` único; imagem só `amd64`; publicação em `0.0.0.0`. | 🟡 |
| D-04 | Worker do laço em processo dedicado por sessão (`worker_mode = process`, `spawn`) como padrão, com fallback `thread` escolhido por benchmark no Sprint 1 (até 2026-10-24). Critério: modo `process` mantém 1000 Hz com telemetria a 50 FPS, `GET /api/v1/health` P95 < 50 ms e lag do event loop P99 < 20 ms no hardware de referência; se falhar e o modo `thread` passar, o padrão vira `thread`. | Isola o GIL do I/O asyncio (risco 1 do PRD) e isola falhas por sessão; a decisão final fica medida, não opinada (`platform-foundation` RF-11, OQ-01; `engine-physics-core` OQ-01). | Laço no event loop; `asyncio` com `sleep(0)`; subinterpreters; Python free-threaded 3.13t (experimental). | 🔴 |
| D-05 | Saída do worker em duas faixas: faixa crítica limitada sem descarte (`run.state`, `event.failure`, `worker.crashed`, respostas de comando) e faixa de dados com descarte do mais antigo (`telemetry.frame`, `event.knock`, `log`). Se a faixa crítica encher, o worker para a sessão e emite `SIM_WORKER_UNAVAILABLE`. | Concilia `platform-foundation` RF-12 (fila de saída de 256 com descarte do mais antigo) com `telemetry-datalogger` RF-09 (nunca descartar `run.state` nem `event.failure`). | Fila única com descarte do mais antigo; fila única sem limite; bloquear o worker quando a fila encher. | 🟡 |
| D-06 | Física em Python + NumPy 2, sem numba nem Cython no MVP; cache LRU de ciclos com entradas quantizadas. Gatilho de reavaliação: média > 0,5 ms ou p99 > 2,0 ms no `muscle-v8-sc` a 7500 rpm em `backend/tests/physics/bench/test_bench_step.py`. | Mantém a stack do PRD e a imagem ≤ 450 MB; a quantização preserva o hash com e sem acerto na cache (`engine-physics-core` decisões, OQ-01). | numba JIT; Cython; extensão Rust (PyO3); PyPy. | 🟡 |
| D-07 | Tempo de simulação só por contagem de ticks (`t_sim_s = tick_index / sim_hz`); RNG `numpy.random.Generator(PCG64)` com `SeedSequence.spawn` por canal em ordem fixa; proibição de `time.*` e `random` dentro de `physics`, `damage`, `ecu`, `dyno` e `telemetry`, imposta por regra `ruff` de API banida e por teste de import. | Determinismo por hash é contrato de 4 specs (`engine-physics-core` RF-20; `knock-and-failure-model` RF-32; `telemetry-datalogger` RF-16; `training-scenarios` RF-11). | `random` global; relógio de parede no cálculo; RNG único partilhado entre canais. | 🟡 |
| D-08 | Determinismo garantido só na mesma imagem e arquitetura; os digests de referência dos testes são versionados por arquitetura (`amd64` normativo, `arm64` informativo); BLAS/OpenMP fixados em 1 thread no worker. | Diferenças de libm e de SIMD entre `x86-64` e `ARM64` mudam o último bit (`engine-physics-core` OQ-04, NG-07). | Determinismo entre plataformas com aritmética de ponto fixo; arredondamento agressivo antes de cada hash. | 🟡 |
| D-09 | SQLite (WAL, `foreign_keys=ON`, `busy_timeout=5000`) como banco padrão em `/data/simremap.db`; PostgreSQL 16 opcional por `DATABASE_URL`; matriz de testes em PostgreSQL só no Sprint 4. | Uma estação, um usuário, zero administração; o PostgreSQL fica para staging (`platform-foundation` RF-10, OQ-04). | PostgreSQL obrigatório; DuckDB; arquivos JSON sem banco. | 🟡 |
| D-10 | Cadeia Alembic linear única (`alembic heads` = 1), nomes `NNNN_<componente>_<descricao>`, `render_as_batch=True` para SQLite e cópia de segurança antes de cada `upgrade`. O nome `telemetry_0001_datalog` da spec vira `0006_telemetry_datalog`. | A convenção do dono (`platform-foundation` seção 9) prevalece sobre o nome local da `telemetry-datalogger` seção 9. | Ramos por componente com `depends_on`; `create_all` sem migrações; numeração por componente. | 🟡 |
| D-11 | Hash dos pacotes de desafio e de tentativa: SHA-256 hex do JCS (RFC 8785) de `{format_version, kind, payload}`, com a biblioteca `rfc8785`; os hashes internos (`content_hash`, `setup_hash`, `curve_sha256`, cabeçalho do datalog) mantêm `json.dumps(sort_keys=True, separators=(",", ":"))` com floats a 6 casas. | JCS é norma independente de linguagem e permite recálculo externo pelo instrutor; os hashes internos já têm dono e teste (`training-scenarios` RF-06, RF-18; `ecu-core` seção 9). | `json.dumps(sort_keys=True)` também nos pacotes; HMAC-SHA256; assinatura Ed25519. | 🟡 |
| D-12 | Datalog colunar `float32` + gzip, com SHA-256 sobre os bytes binários canônicos e export JSON por `repr(float(np.float32(v)))`. | Round-trip exato mantém o hash após export → import; gzip é da biblioteca padrão (`telemetry-datalogger` decisões). | JSON por amostra; Parquet; zstd; HDF5. | 🟡 |
| D-13 | Erro de validação único `VALIDATION_FAILED` (422), dono `platform-foundation`; as specs que citam `VALIDATION_ERROR` (`dyno-bench`, `ecu-core`, `training-scenarios`, `vehicle-catalog`) usam o código do dono. | Catálogo de erros único com verificação de duplicados no arranque (`platform-foundation` RF-06; `requirements.md` 10.2). | Manter os dois códigos; `VALIDATION_ERROR` como canônico. | 🟡 |
| D-14 | Puxada simultânea na mesma sessão = 409 `RUN_IN_PROGRESS` (dono `dyno-bench`); `RUN_ALREADY_ACTIVE` da `dyno-cockpit-ui` deixa de existir. | O dono do recurso define o código (`dyno-bench` seção 8; `dyno-cockpit-ui` OQ-03). | `RUN_ALREADY_ACTIVE`; 423 Locked. | 🟡 |
| D-15 | Concorrência de calibração usa os nomes do `ecu-core`: `base_version`, 409 `CALIBRATION_VERSION_CONFLICT` e 409 `TABLE_NOT_LIVE_TUNABLE`; a `ecu-tuning-ui` troca `base_revision`, `CALIBRATION_REVISION_CONFLICT` e `TABLE_LOCKED_DURING_RUN`. | O `ecu-core` é dono do recurso `Calibration` (`ecu-core` RF-25, RF-28; `ecu-tuning-ui` OQ-03). | Nomes da `ecu-tuning-ui`; ETag/If-Match HTTP. | 🟡 |
| D-16 | Perfil de jogador inexistente = 404 `PLAYER_PROFILE_NOT_FOUND`; `ECU_PROFILE_NOT_FOUND` fica reservado ao perfil de ECU. | Revisão R1 reserva o código de ECU (`_reversa_sdd/prd.md#decisões-de-integração-revisão-r1`; `training-scenarios` RF-02 já corrigido). | Reutilizar `ECU_PROFILE_NOT_FOUND`; `RESOURCE_NOT_FOUND` genérico. | 🟡 |
| D-17 | Taxa de `event.knock` limitada a 10 eventos/s por cilindro, aplicada no produtor (`damage`) e verificada na telemetria. | Vale o limite mais restritivo entre `knock-and-failure-model` RF-28 e `telemetry-datalogger` RF-11 (≤ 50/s). | 1 evento por ciclo; sem limite com descarte só na fila. | 🟡 |
| D-18 | `ActuatorCommands` usa os nomes da `engine-physics-core` (dona do contrato): `ignition_advance_deg`, `throttle_pct`, `vvt_intake_target_deg`, `vvt_exhaust_target_deg`; os nomes `ign_advance_deg` (comando), `throttle_target_pct` e `cam_*_target_deg` do `ecu-core` RF-31 passam a mapear para eles. Campos de configuração de estratégia (`TwoStepConfig.ign_advance_deg`) ficam como estão. | O dono do contrato do barramento define os nomes; evita adaptador por tick (`engine-physics-core` seção 9). | Nomes do `ecu-core`; aliases Pydantic nos dois sentidos. | 🟡 |
| D-19 | Todo envelope do servidor no WS (incluindo `error`) recebe `seq` = último `seq` da sessão + 1, atribuído antes do descarte; a perda mede-se por `frame_index`; envelope `v = 1`, sem novos tipos. | Revisão R1; deduplicação por `seq` na cockpit nunca descarta erros (`telemetry-datalogger` RF-03, RF-25; `dyno-cockpit-ui` RF-04). | `seq` por conexão; `error` sem `seq`; tipos `pong`/`resumed`. | 🟡 |
| D-20 | Nomes de integração canônicos: `lambda_measured`, `injector_pw_ms`, `knock_sensor_v` (0,0–5,0 V) e `knock_intensity` (0,0–1,0); a ECU consome só `knock_intensity`; a telemetria transmite os dois. | Revisão R1 (`_reversa_sdd/prd.md#decisões-de-integração-revisão-r1`; `engine-physics-core` RF-26, Apêndice A.10). | Só tensão; só índice normalizado; nomes livres por spec. | 🟡 |
| D-21 | Limites estruturais do catálogo: `max_rod_load_kn`, `max_cylinder_pressure_bar`, `max_piston_temp_c`, `valve_float_rpm` (e `turbo_max_rpm`); o `damage` converte para N e kPa internamente. | Revisão R1; nomes únicos para catálogo e dano (`vehicle-catalog` decisões; `knock-and-failure-model` OQ-01). | Campos em kPa e N no catálogo; campos opcionais. | 🟡 |
| D-22 | Gráficos de linha com uPlot (Canvas 2D); espectrograma de knock em WebGL com fallback Canvas 2D; carro no rolo em Canvas 2D 2,5D; three.js só num chunk lazy para a superfície 3D do editor. | Hardware sem GPU dedicada e 60 FPS de alvo (`dyno-cockpit-ui` decisões; `ecu-tuning-ui` decisões). | Recharts/SVG; Chart.js; ECharts; Three.js para a cockpit inteira. | 🟡 |
| D-23 | Som do motor sintetizado por Web Audio a partir de RPM, cilindros e ordem de ignição; desligado por padrão até um gesto do usuário. | Sem licenças de áudio e compatível com a política de autoplay (`dyno-cockpit-ui` RF-18, RF-19). | Amostras gravadas; síntese granular com arquivos; áudio ligado ao abrir. | 🟡 |
| D-24 | Tipos e schemas zod do frontend gerados do OpenAPI por `orval`, com teste de paridade no `make check`. | Fonte única nos modelos Pydantic (`ecu-tuning-ui` decisões). | Tipos escritos à mão; `openapi-typescript` sem validação em runtime. | 🟡 |
| D-25 | Layout de testes: `backend/tests/<pacote>/` por componente (como `backend/tests/physics/`), mais `backend/tests/contract/` (OpenAPI, catálogo de erros, versões), `backend/tests/integration/` e `backend/tests/e2e/` (jornadas). | Concilia o brief e `engine-physics-core` seção 8 (`tests/physics/`) com `platform-foundation` seção 8 (`tests/unit/integration/contract`); a cobertura por pacote continua medida por `simremap.<pacote>`. | Só `tests/unit|integration|contract`; testes junto do código. | 🟡 |
| D-26 | Novos alvos no `Makefile`: `make bench` (desempenho do laço e do event loop), `make accuracy` (desvio contra `Reference Benchmark Baseline v1` dos veículos validados) e `make e2e` (3 jornadas no backend e Playwright). Não entram em `make check` para manter ≤ 5 min. | Torna verificáveis os critérios de pronto de desempenho e precisão (`platform-foundation` G-04; `vehicle-catalog` RF-29). | Incluir tudo em `make check`; scripts soltos sem alvo. | 🟡 |
| D-27 | Entrega incremental por feature flags de configuração por componente (`ECU_STRATEGIES_ENABLED`, `ECU_PROFILES_ENABLED`, flag de telemetria e de cenários), com rollback por flag + `alembic downgrade`. | As specs já definem flags e rollback (`ecu-core` seção 12; `ecu-profiles` seção 12; `telemetry-datalogger` seção 12). | Branches longos por componente; entrega em big bang no Sprint 4. | 🟡 |
| D-28 | Laudo forense por regras e modelos de texto versionados, para 3 audiências, sem LLM. | Determinismo, offline e custo zero (`knock-and-failure-model` decisões, RF-22 a RF-27). | Texto gerado por LLM local; LLM remoto. | 🟡 |
| D-29 | Correção de potência SAE J1349 por padrão e DIN 70020 opcional, com fator constante por puxada calculado do ambiente da célula. | As normas usam as condições do ar ambiente, não a IAT pós-intercooler (`dyno-bench` decisões). | Correção por ponto com IAT; sem correção; ISO 1585. | 🟡 |
| D-30 | Precisão física medida pela função pura `compare_to_reference` contra `Reference Benchmark Baseline v1` (`benchmark_id = reference-benchmark-baseline-v1`), EGT em °C, varredura de 2000 rpm à rotação máxima com passo de 250 rpm; qualquer mudança de curva exige nova versão do benchmark. | RN-05 e `vehicle-catalog` RF-22, RF-29. | Desvio médio (RMS) em vez do máximo; EGT em K; validação visual. | 🟡 |
| D-31 | `max_active_sessions = 1` por container no MVP (limite 409 `SIM_CAPACITY_EXCEEDED`); 2 sessões ficam para depois do MVP. | Orçamento de CPU do laço a 1000 Hz no hardware de referência (`dyno-bench` RF-02, OQ-03; `platform-foundation` OQ-05). | 2 sessões em modo instrutor; sessões ilimitadas. | 🟡 |
| D-32 | Sem autenticação; porta só em `127.0.0.1`; CORS só para `localhost`/`127.0.0.1`; publicação em `0.0.0.0` exige `SIMREMAP_BIND_PUBLIC=true` explícito. | Local-first sem contas (`platform-foundation` NG-01, RF-16, OQ-03). | Autenticação por token local; publicação na rede local por padrão. | 🟡 |
| D-33 | Endpoints REST com prefixo `/api/v1/` e WebSocket com `/ws/v1/`; o registro recusa outro prefixo no arranque (`RouterPrefixError`); o catálogo consolidado de endpoints pertence ao `platform-foundation`. | Revisão R1; RN-09. | Versionamento por cabeçalho; prefixos livres por componente. | 🟡 |
| D-34 | Perfil OEM com nome exibido "OEM-Stage" e id `oem-stage`; teste de lista de bloqueio de marcas sobre descritores, mensagens de `ProblemDetail` e OpenAPI. | Revisão R1 e RN-04 (`ecu-profiles` Apêndice G). | Nome com referência a fabricante; revisão manual sem teste. | 🟡 |

## 4. Premissas

| Premissa | Origem (`requirements.md` seção) | Risco se errada |
|----------|----------------------------------|-----------------|
| 🟡 [DÚVIDA] A meta do cenário `standalone-swap` é `min_whp = 300` absolutos no `classic-20t-swap` com E100, não um Δwhp sobre a base OEM. | 10.1 (`training-scenarios` OQ-06) | Médio: o JSON embutido e o E2E do Rodrigo (passo 9) mudam; a calibração de referência pode reprovar ou ficar fácil demais. |
| 🟡 [DÚVIDA] Os pacotes usam só SHA-256 do JCS + recálculo da avaliação + replay opcional, sem HMAC, sem assinatura e sem PIN de instrutor. | 10.1 (`training-scenarios` OQ-01, OQ-02) | Médio: um aluno pode forjar um pacote coerente; HMAC ou Ed25519 exige `format_version = 2` e novo fluxo de chaves. |
| 🟡 [DÚVIDA] A taxa de conclusão (≥ 80 %) conta só os 3 cenários base, com tentativas `abandoned` no denominador. | 10.1 (`training-scenarios` OQ-03) | Baixo: muda só a fórmula de `GET /api/v1/scenarios/{scenario_id}/stats` e o relatório da métrica. |
| 🟡 O modo do worker (`process` ou `thread`) sai do benchmark do Sprint 1; até lá o padrão é `process`. | 10.3 (`platform-foundation` OQ-01) | Alto: troca tardia de modo mexe em filas, serialização e testes de isolamento. |
| 🟡 O desvio de EGT mede-se em °C, não em K. | 10.3 / RN-05 (`engine-physics-core` OQ-03) | Médio: em K a meta fica ≈ 30 % mais folgada; a decisão muda o critério de pronto de precisão. |
| 🟡 "Integridade de 100 %" = saúde mínima de todos os componentes ≥ 0,999 no fim de cada puxada de evidência. | RN-15 (`knock-and-failure-model` OQ-05) | Médio: `health = 1,0` exato tornaria a jornada do Lucas quase impossível. |
| 🟡 Os limiares de ponto quente por combustível são calibrados em conjunto com `hot_spot_temp_c` da física no Sprint 2. | 10.3 (`knock-and-failure-model` OQ-02) | Alto: pré-ignição espúria ou ausente distorce os 6 modos de falha. |
| 🟡 A octanagem de Douaud-Eyzat é `ON = (RON + MON)/2`, também para etanol. | inferida (`knock-and-failure-model` OQ-03) | Médio: knock de E100 fora da faixa esperada na jornada do Rodrigo. |
| 🟡 O `classic-20t-swap` começa com `oem-stage` conservador, motor 8v sem VVT. | inferida (`vehicle-catalog` OQ-03, OQ-04) | Baixo: muda o passo 1 da jornada do Rodrigo e os dados do veículo. |
| 🟡 O `coupe-30t-i6` tem uma só variante (10,2:1, injeção direta). | inferida (`vehicle-catalog` OQ-01) | Baixo: o desafio `challenge-400whp-e27` pode exigir outra variante. |
| 🟡 A `baseline_pull` é inercial pura e é a base de comparação com a referência de 220 whp do hatch. | inferida (`dyno-bench` OQ-02) | Alto: se a referência for de rolo com carga, o desvio < 5 % do Sprint 1 fica enviesado. |
| 🟡 A sessão começa quente (ECT de regime) e não há aquecimento automático no MVP. | inferida (`dyno-bench` OQ-05) | Baixo: arming mais simples; o realismo do arranque a frio fica fora. |
| 🟡 O arrefecimento da `multi_pull` corre no tempo simulado com o padrão de 60 s; a aceleração até 10× fica atrás de flag, sem alterar o hash. | inferida (`dyno-bench` OQ-01) | Médio: a jornada do Rodrigo fica longa na demo se a aceleração não entrar. |
| 🟡 O LTFT reinicia a cada `POST /api/v1/sessions`. | inferida (`ecu-core` OQ-05) | Baixo: só afeta sessões longas. |
| 🟡 Tabelas live-tunable: VE, lambda alvo, ignição e trims; bloqueadas: eixos, base, failsafe e limitador. | inferida (`ecu-tuning-ui` OQ-04) | Médio: muda o caso negativo de RF-19 e o cadeado do editor. |
| 🟡 Os dados do `Reference Benchmark Baseline v1` são estimativas internas (`confidence = estimated`). | RN-05 (`vehicle-catalog` A.4, OQ-02) | Alto: o desvio < 5 % prova coerência com a referência interna, não com medições reais. |
| 🟡 O CSV de log usa vírgula como separador e ponto decimal; a variante pt-BR (`;` e vírgula decimal) fica fora do MVP. | inferida (`telemetry-datalogger` OQ-06) | Baixo: o Excel pt-BR abre o arquivo com colunas juntas. |
| 🟡 A UI formata números pela locale do navegador (pt-BR com vírgula); a API usa sempre ponto. | inferida (`ecu-tuning-ui` OQ-05) | Baixo: confusão de entrada no editor. |

## 5. Delta arquitetural

🟡 Greenfield: todos os componentes são `componente-novo`. A origem é a spec SDD de cada componente (não há `architecture.md`).

| Componente | Arquivo de origem no legado | Tipo de mudança | Resumo |
|------------|------------------------------|-----------------|--------|
| platform-foundation (9) | `_reversa_sdd/sdd/platform-foundation.md` | componente-novo | Factory FastAPI, `Settings`, ProblemDetail e catálogo de erros, Alembic, `SimWorkerHost`, logging JSON, Docker e `make check`. |
| engine-physics-core (1) | `_reversa_sdd/sdd/engine-physics-core.md` | componente-novo | Motor 0D/1D de passo fixo (Wiebe, Woschni, Chen-Flynn, coletores filling & emptying, turbo e supercharger), sensores com ruído semeado e digest. |
| vehicle-catalog (3) | `_reversa_sdd/sdd/vehicle-catalog.md` | componente-novo | 4 veículos e 4 combustíveis em JSON com manifesto SHA-256, limites mecânicos, curvas do benchmark v1 e `compare_to_reference`. |
| dyno-bench (4) | `_reversa_sdd/sdd/dyno-bench.md` | componente-novo | Sessões, ordem do tick, rolo inercial, 4 tipos de puxada, abortos, correção SAE J1349/DIN 70020 e `SimTask`. |
| knock-and-failure-model (2) | `_reversa_sdd/sdd/knock-and-failure-model.md` | componente-novo | Livengood-Wu + Douaud-Eyzat, classes de knock, saúde por componente, 6 modos de falha, bloqueio do motor e laudo forense. |
| ecu-core (5) | `_reversa_sdd/sdd/ecu-core.md` | componente-novo | Tabelas 2D/3D, `Calibration` versionada, estratégias, arbitragem por prioridade e aplicação atômica com live tuning. |
| ecu-profiles (6) | `_reversa_sdd/sdd/ecu-profiles.md` | componente-novo | Perfis `oem-stage`, `ft-pro`, `m1-race`, `ht-elite`, swap, `BaseSetup`, assistente e sintomas físicos de erro de configuração. |
| telemetry-datalogger (7) | `_reversa_sdd/sdd/telemetry-datalogger.md` | componente-novo | WS `/ws/v1/sessions/{session_id}/telemetry`, decimação, backpressure, datalog com SHA-256, export/import/compare. |
| dyno-cockpit-ui (11) | `_reversa_sdd/sdd/dyno-cockpit-ui.md` | componente-novo | Tela da bancada: gráficos, gauges, espectrograma, animação, eventos, autópsia, datalogger e som. |
| ecu-tuning-ui (10) | `_reversa_sdd/sdd/ecu-tuning-ui.md` | componente-novo | Workspace por descritor, editor até 32×32, versões com diff, assistente de swap e avisos didáticos. |
| training-scenarios (8) | `_reversa_sdd/sdd/training-scenarios.md` | componente-novo | Perfis com nickname, cenários base, desafios com defeito oculto, avaliação determinística, pacotes JCS e painel do instrutor. |
| Barramento do laço (interno) | `_reversa_sdd/sdd/engine-physics-core.md#9`, `dyno-bench.md#9` | contrato-novo | `SensorReadings` → ECU → `ActuatorCommands` → física (`DynoLoad`) → `EngineState` → dano (`DamageState`) → telemetria, na ordem fixa do tick. |
| Filas worker ↔ event loop (interno) | `_reversa_sdd/sdd/platform-foundation.md#RF-12` | contrato-novo | Comandos (64, sem descarte, `SIM_WORKER_BUSY`) e saída em duas faixas (D-05). |
| WebSocket de telemetria | `_reversa_sdd/sdd/telemetry-datalogger.md#8` | contrato-novo | `WsEnvelope` v1 com `seq` único por sessão, subscrição, `control.*`, decimação 30–60 FPS. |
| API REST `/api/v1/` | `_reversa_sdd/sdd/platform-foundation.md#8` (catálogo consolidado) | contrato-novo | Endpoints dos 9 componentes de backend com ProblemDetail e catálogo único de `code`. |
| Formatos de arquivo | `_reversa_sdd/sdd/telemetry-datalogger.md#9`, `training-scenarios.md#9`, `vehicle-catalog.md#9` | contrato-novo | Datalog (`datalog_format_version = 1`), pacote `SignedPackage` (`package_format_version = 1`), CSV de notas e de log, dados do catálogo. |

## 6. Delta no modelo de dados

- Resumo das mudanças: 🟡 schema novo em SQLite/PostgreSQL com 19 tabelas em 7 revisões Alembic: `app_meta` (fundação); `simulation_session` e `dyno_run` (dyno-bench); `engine_health`, `failure_event` e `forensic_report` (dano); `calibration`, `calibration_version` e `session_calibration` (ecu-core); `ecu_session_state` e `ecu_base_setup_version` (ecu-profiles); `datalog` (telemetria, com binários em `/data/logs`); `player_profile`, `scenario`, `attempt`, `attempt_run`, `evaluation`, `scenario_event` e `imported_package` (cenários). O catálogo de veículos e os descritores de perfil são arquivos versionados no pacote, não tabelas. A física não persiste nada.
- Detalhe completo em: `_reversa_forward/001-simulador-remap/data-model.md` (substitui o `data-delta.md` do template, a pedido do usuário).

## 7. Delta de contratos externos

🟡 A pasta `contracts/` substitui o `interfaces/` do template, a pedido do usuário.

| Contrato | Tipo | Arquivo de detalhe |
|----------|------|--------------------|
| API REST `/api/v1/` (todos os endpoints, ProblemDetail, catálogo de `code`) | HTTP | `_reversa_forward/001-simulador-remap/contracts/rest-api.md` |
| Telemetria em tempo real `/ws/v1/sessions/{session_id}/telemetry` | WebSocket | `_reversa_forward/001-simulador-remap/contracts/websocket-telemetry.md` |
| Barramento do laço e filas worker ↔ event loop | fila (interno, em processo/multiprocessing) | `_reversa_forward/001-simulador-remap/contracts/simulation-bus.md` |
| Datalog, pacotes `SignedPackage`, CSV e dados do catálogo | arquivo | `_reversa_forward/001-simulador-remap/contracts/file-formats.md` |

## 8. Plano de migração

🟡 Não há dados legados. O plano cria o schema por revisões Alembic lineares, na ordem dos sprints, com `downgrade` testado em cada uma.

1. Sprint 1 (2026-10-19..25): criar `0001_foundation_base` (`app_meta`); ativar `SIMREMAP_DB_AUTO_MIGRATE=true`, a cópia de segurança de `/data/simremap.db` antes de cada `upgrade` pendente e o teste `test_single_alembic_head`. `engine-physics-core` e `vehicle-catalog` não criam migração.
2. Sprint 2 (2026-10-26..11-01), na ordem 4 → 2 → 5: criar `0002_dyno_sessions_runs` (`simulation_session`, `dyno_run`); depois `0003_damage_health_reports` (`engine_health`, `failure_event`, `forensic_report`, com FKs para as tabelas do dyno); depois `0004_ecu_calibrations` (`calibration`, `calibration_version`, `session_calibration`, índices em `(vehicle_id, profile_id)` e `content_hash`).
3. Sprint 3 (2026-11-02..08), na ordem 6 → 7: criar `0005_profiles_session_state` (`ecu_session_state`, `ecu_base_setup_version`, índice em `setup_hash`); depois `0006_telemetry_datalog` (`datalog`, índices em `run_id`, `vehicle_id` e `sha256` único; arquivos binários em `/data/logs`). A `dyno-cockpit-ui` não cria migração.
4. Sprint 4 (2026-11-09..15): criar `0007_scenarios_base` (7 tabelas de cenários); os 3 cenários base entram por carga idempotente no arranque, não pela migração. A `ecu-tuning-ui` não cria migração.
5. Em cada revisão: executar `alembic downgrade base` + `alembic upgrade head` em SQLite (todo sprint) e em PostgreSQL 16 (Sprint 4); confirmar `alembic heads` = 1 e `GET /api/v1/version` com `alembic_head` igual à última revisão.
6. Rollback de release: parar o container, executar `docker compose run --rm app alembic downgrade <revisão anterior>`, iniciar a tag anterior; a cópia em `/data/backup/` mantém as 3 últimas versões.

## 9. Riscos e mitigações

| Risco | Impacto | Probabilidade | Mitigação |
|-------|---------|---------------|-----------|
| 🔴 O laço em Python + NumPy não sustenta 1000 Hz (ou nem 100 Hz) com telemetria no hardware de referência. | alto | médio | Benchmark no dia 1 do Sprint 1 (`make bench`); cache de ciclos quantizada; mínimo de aceite 100 Hz; gatilho de reavaliação para numba documentado (D-06). |
| 🔴 O modo `process` com filas `multiprocessing` custa demais em serialização a 50 FPS. | alto | médio | Decimação no worker (50 itens/s, não 1000); benchmark comparativo `process` × `thread` até 2026-10-24 (D-04). |
| 🔴 O desvio < 5 % falha em lambda ou EGT para algum veículo. | alto | alto | Medir o hatch no Sprint 1 e os outros 3 a partir do Sprint 2 em paralelo; ajuste de coeficientes do catálogo por veículo; nova versão do benchmark só com justificativa. |
| As falhas mecânicas punem de forma incoerente (quebra sem causa ou erro grave sem consequência). | alto | médio | 1 cenário determinístico por modo de falha; fronteiras de knock testadas; laudo ligado às variáveis causais (`knock-and-failure-model` RF-18, RF-22). |
| O escopo de 11 componentes não cabe em 4 semanas. | alto | alto | Fatias por sprint com demo; flags por componente; itens Should/Could (som, 3D, dicas, replay) cortáveis sem afetar os critérios de aceite. |
| Perda de `run.state` ou `event.failure` por descarte na fila de saída do worker. | alto | médio | Faixa crítica sem descarte (D-05); teste com consumidor parado 10 s. |
| Divergência de nomes de campos e códigos entre specs reaparece na implementação. | médio | alto | Normalizações D-13 a D-21 nos contratos; teste de contrato OpenAPI × catálogo; zod gerado por `orval` (D-24). |
| Não determinismo por BLAS multithread, ordem de iteração ou plataforma. | médio | médio | 1 thread BLAS no worker; ordem fixa de substreams; digests por arquitetura (D-07, D-08); 20 execuções no CI. |
| Banda do WS acima de 150 kB/s com a cockpit completa e espectro a 50 FPS. | médio | médio | Subscrição por painel; arredondamento aos decimais do catálogo; espectro em dB com 1 casa; traço de pressão só se subscrito. |
| A cockpit fica abaixo de 30 FPS sem GPU dedicada. | médio | médio | uPlot em Canvas 2D; WebGL só no espectrograma com fallback; `requestAnimationFrame` desacoplado do `onmessage` (D-22). |
| Infração de marca ou trade dress em textos, descritores ou layout. | alto | baixo | Lista de bloqueio testada no CI (D-34); layout próprio; revisão antes da entrega. |
| Pacote de tentativa forjado por aluno (o SHA-256 não autentica autoria). | médio | baixo | Recálculo da avaliação na importação, conferência de `scenario_sha256` e replay opcional; HMAC/assinatura registrados como premissa (seção 4). |
| Container de 3 GB / 3 CPUs deixa pouca folga ao navegador na máquina de 8 GB. | médio | médio | Medir RSS em carga de 10 min no Sprint 3; ajustar limites no `compose.prod.yaml` (`platform-foundation` OQ-02). |
| SQLite com `database is locked` sob escrita concorrente (datalog + calibração). | médio | baixo | WAL, `busy_timeout=5000`, escrita do datalog no fim da puxada; teste com 100 pedidos concorrentes (`platform-foundation` RF-09). |

## 10. Critério de pronto

- [ ] Todas as ações do `actions.md` marcadas `[X]`
- [ ] `cross-check.md` (se executado) sem CRITICAL nem HIGH
- [ ] `regression-watch.md` gerado
- [ ] Re-extração reversa executada e sem regressão vermelha (recomendado, não obrigatório)
- [ ] Jornada do Lucas (RF-40) passa em E2E com `seed` 42: 20 de 20 execuções com boost 280 kPa abs e +8° terminam em knock `severe` e falha catastrófica; 20 de 20 com o acerto corrigido terminam sem knock acima de `light`, integridade 100 %, EGT ≤ 950 °C e Δwhp ≥ +65 em `stage2-pops-bangs`.
- [ ] Jornada do Rodrigo (RF-41) passa em E2E com `seed` 42: os 9 passos do Apêndice F de `ecu-profiles`, `multi_pull` de 3 puxadas com `peak_whp_spread_pct` ≤ 2 %, 0 falhas e potência ≥ 300 whp (premissa da seção 4).
- [ ] Jornada do Prof. Marcos (RF-42) passa em E2E: `challenge-400whp-e27` exportado, tentativa importada, avaliação recalculada com o mesmo `evaluation_sha256`, logs antes/depois exportados e comparados.
- [ ] Fim do Sprint 1 (2026-10-25): `hatch-20t-gdi` com desvio máximo < 5 % em torque, potência, lambda e EGT (°C) contra `Reference Benchmark Baseline v1` (`make accuracy`).
- [ ] Fim do Sprint 4 (2026-11-15): os 4 veículos validados com desvio < 5 % nas 4 grandezas e `max_deviation_pct` idêntico bit a bit em comparação repetida.
- [ ] Laço físico ≥ 100 Hz em tempo real (fator ≥ 1,0) no hardware de referência (4 núcleos, 8 GB, sem GPU dedicada), alvo 1000 Hz, com a cockpit aberta a ≥ 30 FPS e `GET /api/v1/health` P95 < 50 ms (`make bench`).
- [ ] 20 execuções de 30 s simulados a 1000 Hz produzem 20 digests iguais (física, dano, datalog e avaliação).
- [ ] Cobertura ≥ 85 % por pacote de domínio do backend e ≥ 80 % nas features de frontend.
- [ ] `make check` verde: `ruff`, `mypy --strict`, `bandit` sem achados médios/altos, `pytest`, cobertura por pacote, `eslint`, `tsc --noEmit`, `vitest`.
- [ ] Imagem ≤ 450 MB, health `ok` em ≤ 60 s com volume vazio e teste de fumo com `--network none` aprovado.
- [ ] 0 termos da lista de bloqueio de marcas e 0 campos de PII nos testes de varredura.

## 11. Histórico de alterações

| Data | Alteração | Autor |
|------|-----------|-------|
| 2026-10-18 | Versão inicial gerada por `/reversa-plan` (modo autônomo, greenfield), com normalizações entre specs D-13 a D-21 e premissas das 3 `[DÚVIDA]` | reversa |

## Fatias por sprint

### Sprint 1 (2026-10-19 a 2026-10-25): platform-foundation (9), engine-physics-core (1), vehicle-catalog (3)

- Entrega: monorepo, `create_app`, `Settings`, ProblemDetail e catálogo de erros, `0001_foundation_base`, `SimWorkerHost` nos modos `process` e `thread`, logging JSON, Dockerfile e `compose*.yaml`, `make check`, `make bench`, `make accuracy`.
- Entrega: física completa (enchimento, Wiebe, ciclo de zona única com Woschni, Chen-Flynn, EGT, turbo, supercharger, sensores, `knock_sensor_v`/`knock_intensity`, digest).
- Entrega: catálogo com os 4 veículos em `draft` e o `hatch-20t-gdi` em `validated`; `compare_to_reference` e benchmark v1.
- Decisão do sprint: modo do worker fechado por benchmark até 2026-10-24 (D-04).
- Critério de demo: `docker compose -f compose.yaml -f compose.prod.yaml up -d` com `--network none` responde `ok` em ≤ 60 s; uma varredura headless do hatch a 1000 Hz mostra desvio < 5 % nas 4 grandezas; 20 digests iguais; `GET /api/v1/health` P95 < 50 ms com o worker ativo; `make check` verde.

### Sprint 2 (2026-10-26 a 2026-11-01): dyno-bench (4), knock-and-failure-model (2), ecu-core (5)

- Entrega: sessões com limite 1, ordem do tick, rolo inercial, `baseline_pull`, `sweep_pull`, `steady_state_hold`, `multi_pull`, abortos por EGT, correção SAE J1349/DIN 70020; migração `0002`.
- Entrega: Livengood-Wu, classes de knock, saúde por componente, 6 modos de falha, bloqueio `ENGINE_DESTROYED`, restauração, laudo para 3 audiências; migração `0003`.
- Entrega: tabelas e interpolação, `Calibration` versionada, estratégias atrás de `ECU_STRATEGIES_ENABLED`, arbitragem C-01 a C-08, aplicação atômica e live tuning; migração `0004`.
- Critério de demo: por REST, o hatch faz baseline; a mesma sessão com boost 280 kPa abs e +8° termina em `engine_failed` com laudo (R-KNOCK-01 e R-LAMBDA-01); nova puxada devolve 409 `ENGINE_DESTROYED`; após restauração e acerto corrigido a puxada termina `completed` sem knock acima de `light`.

### Sprint 3 (2026-11-02 a 2026-11-08): ecu-profiles (6), telemetry-datalogger (7), dyno-cockpit-ui (11)

- Entrega: 4 perfis com descritores, caminho de torque e checksum do `oem-stage`, swap, `BaseSetup`, assistente, sintomas físicos; migração `0005`; E2E de backend do Rodrigo.
- Entrega: WS v1 com `seq` único, decimação 30–60 FPS, backpressure em duas faixas, datalog com SHA-256, export/import/compare; migração `0006`.
- Entrega: cockpit com gráficos, gauges, espectrograma, eventos, autópsia, datalogger, reconexão e som (Should).
- Critério de demo: no navegador, uma puxada do hatch mostra curvas ao vivo a ≥ 30 FPS e sobreposição com a referência; uma quebra abre a autópsia; o log exportado e reimportado mantém o `sha256`; o E2E de backend do Rodrigo passa os 9 passos.

### Sprint 4 (2026-11-09 a 2026-11-15): ecu-tuning-ui (10), training-scenarios (8), validação dos 3 veículos restantes

- Entrega: workspace por descritor, editor até 32×32, operações de bloco, versões com diff, assistente de swap de 6 passos, avisos W-01.
- Entrega: perfis com nickname, 3 cenários base, desafios com defeito oculto, avaliação determinística com sonda, pacotes JCS, painel do instrutor e CSV de notas; migração `0007`.
- Entrega: `coupe-30t-i6`, `classic-20t-swap` e `muscle-v8-sc` em `validated`; matriz de migrações em PostgreSQL 16.
- Critério de demo: as 3 jornadas (Lucas, Rodrigo, Prof. Marcos) passam ponta a ponta no navegador e em `make e2e`; `make accuracy` aprova os 4 veículos; importação de 50 pacotes com 2 adulterados mostra 48 importados e 2 recusados; todos os itens da seção 10 marcados.
