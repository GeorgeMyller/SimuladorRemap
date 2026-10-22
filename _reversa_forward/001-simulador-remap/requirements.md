# Requirements: Simulador Completo de Remap Automotivo em Dinamômetro

> Identificador: `001-simulador-remap`
> Data: `2026-10-18`
> Pasta da extração reversa: `_reversa_sdd/` (projeto greenfield: PRD, personas, ideation e 11 specs SDD)
> Confidência: 🟢 CONFIRMADO, 🟡 INFERIDO, 🔴 LACUNA / DÚVIDA
> Nota de confidência: todas as fontes são specs planejadas, sem código. Por isso, os itens usam 🟡. O selo 🔴 marca só lacunas reais.

## 1. Resumo executivo

🟡 A feature entrega o MVP integrado do SimuladorRemap: um dinamômetro virtual com motor termodinâmico 0D/1D, 4 veículos, 4 perfis genéricos de ECU, falhas mecânicas com laudo forense, telemetria em tempo real e cenários de treino avaliáveis.
🟡 O público é o aluno de remap (Lucas), o preparador em transição para standalone (Rodrigo) e o instrutor de escola técnica (Prof. Marcos).
🟡 O problema resolvido é a falta de um ambiente seguro e barato para treinar calibração sem carro, sem dinamômetro físico e sem risco de quebrar motores reais.
🟡 O MVP dura 4 semanas, em 4 sprints de 1 semana, na ordem de implementação 9 → 1 → 3 → 4 → 2 → 5 → 6 → 7 → 11 → 10 → 8.
🟡 Este documento integra as 11 specs. Ele não substitui as specs: cada requisito aponta para a RF dona.

### 1.1 Glossário mínimo

| Termo | Definição |
|-------|-----------|
| ECU | Unidade de controle eletrônico do motor (Engine Control Unit). |
| OEM | Fabricante original (Original Equipment Manufacturer); "ECU OEM" é a ECU de série. |
| Standalone | ECU programável que substitui a ECU OEM. |
| Remap / calibração | Conjunto versionado de tabelas e estratégias da ECU. |
| Puxada | Execução de medição no dinamômetro (baseline, varredura, carga estacionária ou série). |
| whp | Potência medida na roda (wheel horsepower). |
| VE | Eficiência volumétrica (volumetric efficiency). |
| Lambda | Razão entre a mistura ar/combustível real e a estequiométrica (λ = 1 é estequiométrico). |
| EGT | Temperatura dos gases de escape (exhaust gas temperature). |
| Knock / detonação | Autoignição da mistura não queimada, que gera oscilação de pressão e dano. |
| MBT | Avanço mínimo para o melhor torque (Minimum spark advance for Best Torque). |
| Laudo forense | Relatório da causa termodinâmica de uma falha mecânica. |
| PII | Dado pessoal identificável (Personally Identifiable Information). |
| WS | Canal WebSocket de telemetria. |
| `seq` | Número de sequência de cada envelope enviado pelo servidor no WS. |
| FPS | Quadros por segundo enviados ou desenhados. |
| Hz | Frequência do laço físico, em ticks por segundo. |
| SHA-256 | Função de hash usada para determinismo e integridade. |
| Pacote | Arquivo JSON de desafio ou de tentativa, com SHA-256 do JSON canônico. |

### 1.2 Escopo por sprint

| Sprint | Componentes (ordem) | Fatia entregue |
|--------|---------------------|----------------|
| 1 | `platform-foundation` (9), `engine-physics-core` (1), `vehicle-catalog` (3) | Container local, erros padronizados, laço físico isolado, física determinística, catálogo com `hatch-20t-gdi` validado. |
| 2 | `dyno-bench` (4), `knock-and-failure-model` (2), `ecu-core` (5) | Sessões e 4 tipos de puxada, knock, dano, 6 modos de falha, laudo, runtime de ECU com estratégias e arbitragem. |
| 3 | `ecu-profiles` (6), `telemetry-datalogger` (7), `dyno-cockpit-ui` (11) | 4 perfis genéricos, swap standalone, WS de telemetria, datalog com hash, tela da bancada. |
| 4 | `ecu-tuning-ui` (10), `training-scenarios` (8) | Editor de ECU no navegador, perfis locais, cenários, avaliação objetiva, pacotes, painel do instrutor; validação dos 3 veículos restantes. |

🟡 A fatia segue a mitigação de escopo do PRD: primeiro 1 carro, o perfil OEM, o dinamômetro e as falhas de knock/EGT; depois o restante.

### 1.3 Fora do escopo

- 🟡 Condução em pista ou estrada e física de pneus/suspensão fora do rolo.
- 🟡 Multijogador síncrono em tempo real.
- 🟡 Conexão física (USB/CAN/OBD2) a ECUs ou veículos reais.
- 🟡 Leitura ou gravação de binários proprietários ou criptografados de ECU.
- 🟡 Motores diesel, rotativos, elétricos ou híbridos.
- 🟡 Aplicação nativa para celular ou tablet.
- 🟡 Marcas registradas, logotipos ou código proprietário de fabricantes de ECU.
- 🟡 Licenças de software proprietário.
- 🟡 Autenticação, contas, deploy em nuvem e telemetria de uso externa.

## 2. Contexto a partir do legado

| Fonte | Trecho relevante | Confidência |
|-------|------------------|-------------|
| `_reversa_sdd/prd.md#1-problema` | Treino de remap exige carro, dinamômetro e risco financeiro; ferramentas atuais não simulam o motor. | 🟡 |
| `_reversa_sdd/prd.md#3-métricas-de-sucesso` | Desvio < 5 %, conclusão ≥ 80 %, laço ≥ 100 Hz, telemetria 30–60 FPS, hardware de referência. | 🟡 |
| `_reversa_sdd/prd.md#4-escopo-in` | 4 carros, motor 0D/1D, falhas, dinamômetro, 4 perfis de ECU, telemetria, treino, plataforma local-first. | 🟡 |
| `_reversa_sdd/prd.md#5-não-objetivos-out` | Lista dos não-objetivos usada na seção 1.3. | 🟡 |
| `_reversa_sdd/prd.md#6-restrições` | MVP em 4 sprints, custo zero de licenças, zero PII, nomes genéricos de ECU. | 🟡 |
| `_reversa_sdd/prd.md#decisões-de-integração-revisão-r1` | Sinal de knock, nomes de campos, códigos de erro, `seq`, prefixo `/api/v1/`, `OEM-Stage`, benchmark canônico. | 🟡 |
| `_reversa_sdd/prd.md#7-dependências-externas` | `Reference Benchmark Baseline v1` com os datasets dos 4 veículos. | 🟡 |
| `_reversa_sdd/prd.md#8-riscos` | Desempenho do laço, dados de validação, coerência das falhas, banda do WS, turmas sem rede. | 🟡 |
| `_reversa_sdd/prd.md#9-critérios-de-aceite-alto-nível` | Critérios de Lucas, Rodrigo, Prof. Marcos, física e desempenho. | 🟡 |
| `_reversa_sdd/personas.md#persona-1-lucas` | Jornada Stage 1 / Stage 2 com quebra, laudo, correção e +65 whp. | 🟡 |
| `_reversa_sdd/personas.md#persona-2-rodrigo` | Jornada de swap standalone até a validação em várias puxadas. | 🟡 |
| `_reversa_sdd/personas.md#persona-3-prof-marcos` | Jornada de desafio, demonstração, falha provocada e avaliação objetiva. | 🟡 |
| `_reversa_sdd/ideation.md#premissas-a-validar` | Física em tempo real, interfaces sem infração, telemetria explicativa. | 🟡 |
| `_reversa_sdd/sdd/platform-foundation.md#6.1-requisitos-principais` | Container, ProblemDetail, catálogo de erros, worker isolado, filas limitadas, zero PII, portões de qualidade. | 🟡 |
| `_reversa_sdd/sdd/engine-physics-core.md#6.1-requisitos-principais` | Motor 0D/1D de passo fixo 100–1000 Hz, MBT emergente, EGT, turbo/compressor, `lock()`, digest determinístico, `knock_sensor_v`/`knock_intensity`. | 🟡 |
| `_reversa_sdd/sdd/vehicle-catalog.md#6.1-requisitos-principais` | 4 veículos canônicos, limites mecânicos, curvas de referência, `compare_to_reference`, benchmark `reference-benchmark-baseline-v1`. | 🟡 |
| `_reversa_sdd/sdd/dyno-bench.md#6.1-requisitos-principais` | Sessões, limite de capacidade, ordem do tick, 4 tipos de puxada, abortos, `ENGINE_DESTROYED`. | 🟡 |
| `_reversa_sdd/sdd/knock-and-failure-model.md#6.1-requisitos-principais` | Livengood-Wu, classes de knock, saúde por componente, 6 modos de falha, bloqueio, laudo com cadeia causal. | 🟡 |
| `_reversa_sdd/sdd/ecu-core.md#6.1-requisitos-principais` | Tabelas 2D/3D, calibração versionada, estratégias, arbitragem, aplicação atômica, live tuning. | 🟡 |
| `_reversa_sdd/sdd/ecu-profiles.md#6.1-requisitos-principais` | `oem-stage`, `ft-pro`, `m1-race`, `ht-elite`; swap; `BaseSetup`; sintomas físicos de erro de configuração; jornada do Rodrigo. | 🟡 |
| `_reversa_sdd/sdd/telemetry-datalogger.md#6.1-requisitos-principais` | WS com envelope v1, `seq` único, decimação, backpressure, datalog com hash, export/import/compare. | 🟡 |
| `_reversa_sdd/sdd/dyno-cockpit-ui.md#6.1-requisitos-principais` | Gráficos, gauges, espectrograma, animação, eventos, autópsia, datalogger, som e acessibilidade. | 🟡 |
| `_reversa_sdd/sdd/ecu-tuning-ui.md#6.1-requisitos-principais` | Workspace por perfil, editor até 32×32, operações de seleção, versões, wizard de swap, avisos didáticos. | 🟡 |
| `_reversa_sdd/sdd/training-scenarios.md#6.1-requisitos-principais` | Perfis com nickname, cenários base, defeitos ocultos, avaliação determinística, pacotes com SHA-256, painel do instrutor. | 🟡 |
| `_reversa_sdd/sdd/<componente>.md#14-open-questions` | Questões abertas herdadas, tratadas na seção 10. | 🟡 |

## 3. Personas e cenários de uso

| Persona | Objetivo | Cenário-chave |
|---------|----------|---------------|
| 🟡 Lucas, aluno de preparação (iniciante) | Ganhar segurança técnica em Stage 1, Stage 2 e pops & bangs em ECU OEM. | No `hatch-20t-gdi` com `OEM-Stage`, exagera boost e avanço, quebra o motor, lê o laudo, restaura, corrige e valida +65 whp sem knock. |
| 🟡 Rodrigo, preparador intermediário | Dominar o swap OEM → standalone e a calibração do zero. | No `classic-20t-swap` com E100, troca para `FT-Pro`, configura a base, constrói VE/lambda/ignição, ativa two-step e boost por marcha, e valida 3 puxadas seguidas. |
| 🟡 Prof. Marcos, instrutor | Dar prática avaliável a turmas de 20 a 50 alunos sem rede. | Cria o desafio "400 whp, gasolina comum, EGT ≤ 900 °C", distribui o pacote, importa as tentativas e aprova só por critérios objetivos. |

🟡 Frequência de uso: Lucas e Rodrigo usam o simulador em sessões individuais em casa ou na oficina. O Prof. Marcos usa uma estação por aluno, em aula, com troca de pacotes por arquivo.

## 4. Regras de negócio novas ou alteradas

1. **RN-01:** Uma falha mecânica catastrófica bloqueia o motor no mesmo tick. A puxada termina em `engine_failed` no tick seguinte. Novas puxadas recebem 409 `ENGINE_DESTROYED` até a restauração explícita do motor. 🟡
   - Origem: `_reversa_sdd/sdd/knock-and-failure-model.md#RF-19`, `_reversa_sdd/sdd/dyno-bench.md#RF-14`, `_reversa_sdd/sdd/dyno-bench.md#RF-20`, `_reversa_sdd/sdd/engine-physics-core.md#RF-19`
   - Tipo: nova
2. **RN-02:** A aprovação de uma tentativa depende só de critérios objetivos e obrigatórios (meta de potência ou torque, margem de knock, EGT, lambda, integridade de 100 %, puxadas válidas). A pontuação total não decide a aprovação. Nenhum relógio ou sorteio entra no cálculo. 🟡
   - Origem: `_reversa_sdd/prd.md#9-critérios-de-aceite-alto-nível`, `_reversa_sdd/sdd/training-scenarios.md#RF-11`, `_reversa_sdd/sdd/training-scenarios.md#RF-13`
   - Tipo: nova
3. **RN-03:** O sistema não coleta PII. O único dado do usuário é o nickname (3 a 24 caracteres `[-_0-9A-Za-z]`). Logs e eventos usam identificadores, nunca o nickname nem o IP. O container não faz conexões de rede de saída. 🟡
   - Origem: `_reversa_sdd/prd.md#6-restrições`, `_reversa_sdd/sdd/platform-foundation.md#RF-20`, `_reversa_sdd/sdd/training-scenarios.md#RF-01`
   - Tipo: nova
4. **RN-04:** Os perfis de ECU usam só os nomes genéricos `OEM-Stage`, `FT-Pro`, `M1-Race` e `HT-Elite` (ids `oem-stage`, `ft-pro`, `m1-race`, `ht-elite`). Textos exibidos, descritores e mensagens têm 0 ocorrências da lista de bloqueio de marcas. 🟡
   - Origem: `_reversa_sdd/prd.md#decisões-de-integração-revisão-r1`, `_reversa_sdd/sdd/ecu-profiles.md#RF-01`, `_reversa_sdd/sdd/vehicle-catalog.md#RF-07`
   - Tipo: nova
5. **RN-05:** O benchmark canônico de precisão é `Reference Benchmark Baseline v1` (`benchmark_id = reference-benchmark-baseline-v1`). O desvio máximo por ponto de RPM fica < 5 % em torque, potência, lambda e EGT (EGT medida em °C). Qualquer mudança de curva exige nova versão do benchmark. 🟡
   - Origem: `_reversa_sdd/prd.md#7-dependências-externas`, `_reversa_sdd/sdd/vehicle-catalog.md#RF-29`, `_reversa_sdd/sdd/engine-physics-core.md#14-open-questions` (OQ-02, OQ-03)
   - Tipo: nova
6. **RN-06:** Todo envelope do servidor no WS, incluindo `error`, recebe `seq` = último `seq` da sessão + 1. O `seq` nunca se repete. A perda de frames mede-se por `frame_index`, não por `seq`. 🟡
   - Origem: `_reversa_sdd/prd.md#decisões-de-integração-revisão-r1`, `_reversa_sdd/sdd/telemetry-datalogger.md#RF-03`, `_reversa_sdd/sdd/telemetry-datalogger.md#RF-25`, `_reversa_sdd/sdd/dyno-cockpit-ui.md#RF-04`
   - Tipo: nova
7. **RN-07:** Todo erro HTTP usa o formato ProblemDetail (RFC 7807) com `code` estável de um catálogo único, sem duplicados. Os códigos de integração são canônicos: `ECU_PROFILE_NOT_FOUND` (perfil de ECU inexistente) e `SIM_CAPACITY_EXCEEDED` (limite de sessões). 🟡
   - Origem: `_reversa_sdd/prd.md#decisões-de-integração-revisão-r1`, `_reversa_sdd/sdd/platform-foundation.md#RF-05`, `_reversa_sdd/sdd/platform-foundation.md#RF-06`
   - Tipo: nova
8. **RN-08:** Os nomes de campo de integração são canônicos em todas as specs: `lambda_measured`, `injector_pw_ms`, `knock_sensor_v` (0,0–5,0 V) e `knock_intensity` (0,0–1,0). A ECU consome `knock_intensity`. A telemetria transmite os dois sinais de knock. 🟡
   - Origem: `_reversa_sdd/prd.md#decisões-de-integração-revisão-r1`, `_reversa_sdd/sdd/engine-physics-core.md#RF-26`
   - Tipo: nova
9. **RN-09:** Todos os endpoints REST usam o prefixo `/api/v1/` e os WebSockets usam `/ws/v1/`. O catálogo consolidado de endpoints pertence ao `platform-foundation`. 🟡
   - Origem: `_reversa_sdd/prd.md#decisões-de-integração-revisão-r1`, `_reversa_sdd/sdd/platform-foundation.md#RF-03`
   - Tipo: nova
10. **RN-10:** A mesma `seed`, o mesmo veículo, a mesma calibração e a mesma sequência de comandos produzem o mesmo hash SHA-256 na física, no dano, no datalog e na avaliação, na mesma imagem de container. 🟡
    - Origem: `_reversa_sdd/sdd/engine-physics-core.md#RF-20`, `_reversa_sdd/sdd/knock-and-failure-model.md#RF-32`, `_reversa_sdd/sdd/telemetry-datalogger.md#RF-16`, `_reversa_sdd/sdd/training-scenarios.md#RF-11`
    - Tipo: nova
11. **RN-11:** Cada estação executa um container próprio. Cada container aceita 1 sessão de simulação ativa por padrão. Acima do limite, a criação de sessão recebe 409 `SIM_CAPACITY_EXCEEDED`. 🟡
    - Origem: `_reversa_sdd/prd.md#8-riscos`, `_reversa_sdd/sdd/dyno-bench.md#RF-02`
    - Tipo: nova
12. **RN-12:** Cada alteração aceita de calibração cria uma versão imutável com `content_hash`. A aplicação a uma sessão é atômica numa fronteira de tick. Durante uma puxada, só tabelas `live_tunable` aceitam alteração. 🟡
    - Origem: `_reversa_sdd/sdd/ecu-core.md#RF-05`, `_reversa_sdd/sdd/ecu-core.md#RF-27`, `_reversa_sdd/sdd/ecu-core.md#RF-28`
    - Tipo: nova
13. **RN-13:** Pacotes de desafio e de tentativa levam SHA-256 do JSON canônico. Um pacote com hash inválido, formato não suportado ou schema inválido é recusado e nada é gravado. A estação do instrutor recalcula a avaliação a partir das evidências. 🟡
    - Origem: `_reversa_sdd/prd.md#8-riscos`, `_reversa_sdd/sdd/training-scenarios.md#RF-19`, `_reversa_sdd/sdd/training-scenarios.md#RF-20`
    - Tipo: nova
14. **RN-14:** O defeito oculto de um desafio fica invisível ao perfil `student` até a submissão. O sistema converte o defeito em falha física injetada na sessão. 🟡
    - Origem: `_reversa_sdd/sdd/training-scenarios.md#RF-03`, `_reversa_sdd/sdd/training-scenarios.md#RF-08`
    - Tipo: nova
15. **RN-15:** "Integridade de 100 %" significa saúde mínima de todos os componentes ≥ 0,999 no fim de cada puxada de evidência. 🟡
    - Origem: `_reversa_sdd/sdd/knock-and-failure-model.md#3-goals-objetivos` (G-02), `_reversa_sdd/sdd/knock-and-failure-model.md#14-open-questions` (OQ-05, decisão atual)
    - Tipo: nova
16. **RN-16:** Um veículo com estado `draft` no catálogo não abre sessão (409 `VEHICLE_NOT_VALIDATED`), exceto com a flag de desenvolvimento ativa. 🟡
    - Origem: `_reversa_sdd/sdd/vehicle-catalog.md#RF-23`
    - Tipo: nova
17. **RN-17:** A ECU arbitra as estratégias por prioridade fixa: failsafe > limitador > two-step/antilag/powershift > overrun > normal. 🟡
    - Origem: `_reversa_sdd/sdd/ecu-core.md#RF-23`, `_reversa_sdd/sdd/ecu-core.md#RF-24`
    - Tipo: nova
18. **RN-18:** Uma ECU standalone sem setup mínimo válido (roda fônica, bicos, combustível e sensor MAP) não dá partida. Puxadas recebem 409 `ECU_SETUP_INCOMPLETE`. 🟡
    - Origem: `_reversa_sdd/sdd/ecu-profiles.md#RF-20`
    - Tipo: nova

## 5. Requisitos Funcionais

### 5.1 Plataforma (Sprint 1)

| ID | Requisito | Prioridade | Critério de aceite | Confidência |
|----|-----------|------------|--------------------|-------------|
| RF-01 | O sistema sobe completo numa estação, sem rede, com um único comando de container. | Must | Com imagem construída e volume vazio, `GET /api/v1/health` devolve `ok` em ≤ 60 s; o teste de fumo sem rede passa. Ver `platform-foundation` RF-07, RF-17, RNF-02, RNF-06. | 🟡 |
| RF-02 | O sistema responde a todo erro HTTP com ProblemDetail e `code` do catálogo único (RN-07). | Must | Teste parametrizado sobre 404, 405, 413, 415, 422 e 500 valida o schema; registro duplicado de `code` falha o arranque. Ver `platform-foundation` RF-05, RF-06. | 🟡 |
| RF-03 | O sistema executa o laço físico fora do event loop de I/O e troca dados só por filas limitadas. | Must | Com 1 sessão a 1000 Hz, `GET /api/v1/health` tem P95 < 50 ms; um consumidor parado 10 s mantém o laço a ≥ 99 % de `sim_hz`. Ver `platform-foundation` RF-11, RF-12. | 🟡 |
| RF-04 | O sistema expõe as versões da API e dos formatos de arquivo. | Must | `GET /api/v1/version` devolve `api_version = v1`, `package_format_version = 1` e `datalog_format_version = 1`. Ver `platform-foundation` RF-08, RF-21. | 🟡 |

### 5.2 Física e catálogo (Sprint 1)

| ID | Requisito | Prioridade | Critério de aceite | Confidência |
|----|-----------|------------|--------------------|-------------|
| RF-05 | O sistema oferece os 4 veículos canônicos; só veículos validados abrem sessão (RN-16). | Must | Com `include_drafts=true`, `GET /api/v1/vehicles` devolve `hatch-20t-gdi`, `coupe-30t-i6`, `classic-20t-swap` e `muscle-v8-sc`; no fim do Sprint 1 só o hatch está validado; no fim do Sprint 4 os 4 estão validados. Ver `vehicle-catalog` RF-02, RF-14, RF-23. | 🟡 |
| RF-06 | O sistema mede o desvio da simulação contra `Reference Benchmark Baseline v1` (RN-05). | Must | Varredura de 2000 rpm até a rotação máxima, passo 250 rpm, com a calibração de referência: desvio máximo < 5 % por grandeza; comparação repetida dá `max_deviation_pct` idêntico bit a bit. Ver `vehicle-catalog` RF-22, RF-29; `engine-physics-core` RNF-02. | 🟡 |
| RF-07 | A física é determinística por digest (RN-10). | Must | 20 execuções de 30 s simulados a 1000 Hz produzem 20 digests finais iguais. Ver `engine-physics-core` RF-20. | 🟡 |
| RF-08 | A física responde de forma coerente aos atuadores da ECU. | Must | O MBT emerge com pico de pressão entre 12° e 18° ATDC; VE da ECU 10 % acima da VE física dá λ 0,91 ± 0,01; atraso de 10° desde o MBT eleva a EGT ≥ 40 °C. Ver `engine-physics-core` RF-05, RF-12, RF-13. | 🟡 |
| RF-09 | A física publica o sinal de knock por cilindro nos dois formatos canônicos (RN-08). | Must | Em 10⁶ ticks com ruído, nenhum `knock_sensor_v` sai de 0,0–5,0 V e nenhum `knock_intensity` sai de 0,0–1,0. Ver `engine-physics-core` RF-26. | 🟡 |

### 5.3 Dinamômetro, knock e falhas (Sprint 2)

| ID | Requisito | Prioridade | Critério de aceite | Confidência |
|----|-----------|------------|--------------------|-------------|
| RF-10 | O usuário cria e encerra sessões de simulação dentro do limite de capacidade (RN-11). | Must | Com 1 sessão ativa e limite 1, nova criação devolve 409 `SIM_CAPACITY_EXCEEDED`; após `DELETE`, a criação devolve 201. Ver `dyno-bench` RF-01, RF-02, RF-22. | 🟡 |
| RF-11 | O sistema orquestra cada tick na ordem sensors → ecu → physics → damage → telemetry. | Must | Stubs instrumentados registram a sequência exata em 10 000 ticks, sem inversão. Ver `dyno-bench` RF-03. | 🟡 |
| RF-12 | O usuário executa os 4 tipos de puxada: `baseline_pull`, `sweep_pull`, `steady_state_hold` e `multi_pull`. | Must | A primeira baseline concluída vira `baseline_run_id`; `multi_pull` com N = 3 devolve 3 curvas e `peak_whp_spread_pct`. Ver `dyno-bench` RF-06 a RF-09. | 🟡 |
| RF-13 | O sistema persiste cada puxada com resumo auditável. | Must | `GET /api/v1/runs/{run_id}` após reinício do container devolve o mesmo `summary`. Ver `dyno-bench` RF-18. | 🟡 |
| RF-14 | O sistema detecta e classifica knock, acumula dano por componente e gera os 6 modos de falha. | Must | Fronteiras I = 0,29/0,30/1,00/3,00 dão `none`/`light`/`moderate`/`severe`; cada modo tem 1 cenário determinístico com 1 falha catastrófica. Ver `knock-and-failure-model` RF-04, RF-10, RF-18. | 🟡 |
| RF-15 | O sistema bloqueia o motor após falha catastrófica e o usuário restaura o motor (RN-01). | Must | Falha no tick k: `engine_failed` com `ended_at_tick = k + 1`; nova puxada devolve 409 `ENGINE_DESTROYED`; após `POST .../engine/restore`, a puxada devolve 202. Ver `dyno-bench` RF-14, RF-20; `knock-and-failure-model` RF-19, RF-21. | 🟡 |
| RF-16 | O sistema gera o laudo forense com cadeia causal, avisos antecipados, recomendações e texto para 3 audiências. | Must | Laudo disponível em ≤ 500 ms (P95); cadeia com 3 a 12 elos terminada na falha; `audience=beginner` sem fórmulas. Ver `knock-and-failure-model` RF-22 a RF-27. | 🟡 |
| RF-17 | O sistema aborta a puxada por EGT acima do limite por ≥ 0,5 s contínuos. | Must | Limite 950 °C: EGT 960 °C por 0,6 s gera `aborted` com `egt_limit`; por 0,4 s não aborta. Ver `dyno-bench` RF-15. | 🟡 |

### 5.4 ECU e perfis (Sprints 2 e 3)

| ID | Requisito | Prioridade | Critério de aceite | Confidência |
|----|-----------|------------|--------------------|-------------|
| RF-18 | O usuário cria, lê, edita e reverte calibrações versionadas, com conflito otimista (RN-12). | Must | 3 PATCH e 1 PUT de reversão à versão 1 geram 5 versões, e a versão 5 tem o `content_hash` da versão 1; versão base desatualizada devolve 409. Ver `ecu-core` RF-04, RF-05, RF-25, RF-26. | 🟡 |
| RF-19 | O usuário aplica uma calibração à sessão de forma atômica; durante a puxada, só tabelas live-tunable mudam. | Must | Nenhum tick usa duas versões; alterar tabela não live-tunable em puxada devolve 409 com a lista das tabelas. Ver `ecu-core` RF-27, RF-28. | 🟡 |
| RF-20 | A ECU executa combustível, malha fechada, ignição por cilindro, knock control, boost, limitador, two-step, antilag, powershift, overrun e failsafe, com arbitragem (RN-17). | Must | Os 8 casos de arbitragem C-01 a C-08 produzem os comandos esperados; cada ECU `step()` tem p99 ≤ 0,1 ms. Ver `ecu-core` RF-06 a RF-24, RNF-01. | 🟡 |
| RF-21 | O sistema oferece os 4 perfis genéricos com descritor próprio (RN-04). | Must | `GET /api/v1/ecu-profiles` devolve 4 itens na ordem `oem-stage`, `ft-pro`, `m1-race`, `ht-elite`; perfil inexistente devolve 404 `ECU_PROFILE_NOT_FOUND`. Ver `ecu-profiles` RF-01, RF-02. | 🟡 |
| RF-22 | O perfil `OEM-Stage` limita o torque pelo caminho de torque e aplica as proteções OEM. | Must | Pressão alvo +20 % com `torque_limit` inalterado mantém o torque ≤ 105 % do limite de 2500 a 6000 rpm WOT; checksum desatualizado devolve 422 `OEM_CHECKSUM_INVALID`. Ver `ecu-profiles` RF-05 a RF-12. | 🟡 |
| RF-23 | O usuário troca a ECU OEM por standalone, preenche a `BaseSetup` e gera o mapa base por assistente (RN-18). | Must | Swap `oem-stage` → `ft-pro` devolve `awaiting_base_setup` com 6 itens pendentes; puxada antes do setup devolve 409 `ECU_SETUP_INCOMPLETE`; o assistente gera calibração com `metadata.source = wizard`. Ver `ecu-profiles` RF-17 a RF-21. | 🟡 |
| RF-24 | O sistema converte erros de configuração standalone em sintomas físicos coerentes. | Must | Erro de PMS +8° desloca o avanço real em +8,0°; bico declarado 1250 cc/min com real 1000 cc/min dá λ 1,0625 ± 2 % em malha aberta. Ver `ecu-profiles` RF-22 a RF-26. | 🟡 |

### 5.5 Telemetria e cockpit (Sprint 3)

| ID | Requisito | Prioridade | Critério de aceite | Confidência |
|----|-----------|------------|--------------------|-------------|
| RF-25 | O sistema transmite telemetria por WS com envelope v1, `seq` único (RN-06) e decimação para 30–60 FPS. | Must | Com 1000 Hz e 50 FPS, 60 s geram 3000 ± 1 frames; 1 erro entre 2 frames dá `seq` n, n+1, n+2; 0 repetições em 10 000 envelopes. Ver `telemetry-datalogger` RF-02, RF-03, RF-05, RF-25. | 🟡 |
| RF-26 | O sistema aplica backpressure por conexão sem bloquear o laço e nunca descarta `run.state` nem `event.failure`. | Must | Cliente parado 10 s: laço ≥ 99 % de `sim_hz`; 100 % dos `run.state` e `event.failure` chegam ao retomar. Ver `telemetry-datalogger` RF-08, RF-09. | 🟡 |
| RF-27 | O sistema grava o datalog à taxa total com SHA-256 e permite exportar, importar e comparar logs. | Must | 15 s a 1000 Hz geram 15 000 amostras por canal; export e reimport mantêm o `sha256`; 1 amostra alterada devolve 422 `LOG_HASH_MISMATCH`. Ver `telemetry-datalogger` RF-14 a RF-19. | 🟡 |
| RF-28 | A cockpit mostra potência/torque, lambda/EGT, gauges, espectrograma de knock, linha do tempo de eventos e sobreposição com referência e com puxada anterior. | Must | Gauge de EGT 960 °C com limite 950 °C fica vermelho com texto "960 °C"; clique num evento posiciona o cursor no `t_sim_s`. Ver `dyno-cockpit-ui` RF-06 a RF-09, RF-14. | 🟡 |
| RF-29 | A cockpit abre a autópsia após falha catastrófica e permite restaurar o motor. | Must | Laudo de `piston_failure` no cilindro 3 destaca o pistão 3 e lista ≥ 2 elos; após restore, `RunControls` aceita nova puxada. Ver `dyno-cockpit-ui` RF-15, RF-16. | 🟡 |
| RF-30 | O usuário inicia e aborta puxadas na cockpit, e a UI reconecta o WS após queda. | Must | Abort mostra "abortada" em ≤ 500 ms após `run.state`; a 1.ª reconexão ocorre em 500 ± 50 ms; após 10 falhas aparece "telemetria indisponível". Ver `dyno-cockpit-ui` RF-05, RF-12. | 🟡 |

### 5.6 Software de ECU no navegador (Sprint 4)

| ID | Requisito | Prioridade | Critério de aceite | Confidência |
|----|-----------|------------|--------------------|-------------|
| RF-31 | O usuário edita tabelas até 32×32 num workspace gerado do descritor do perfil ativo. | Must | O mesmo componente gera 4 árvores de navegação a partir dos 4 descritores; `+5 %` em 20 resulta 21; 10 edições em 200 ms geram 1 PATCH. Ver `ecu-tuning-ui` RF-01 a RF-13. | 🟡 |
| RF-32 | O usuário segue o assistente de swap, consulta versões com diff e vê o estado live-tune e os avisos didáticos. | Must | Os 6 passos do assistente deixam o motor em marcha lenta com `ft-pro`; tabela bloqueada em puxada mostra cadeado; avanço 4° acima do MBT estimado gera aviso W-01 sem bloquear a gravação. Ver `ecu-tuning-ui` RF-15 a RF-19. | 🟡 |

### 5.7 Treino e avaliação (Sprint 4)

| ID | Requisito | Prioridade | Critério de aceite | Confidência |
|----|-----------|------------|--------------------|-------------|
| RF-33 | O usuário cria perfis locais só com nickname e papel (`student` ou `instructor`) (RN-03). | Must | Nickname com espaço ou `@` devolve 422; nickname repetido com outra caixa devolve 409 `NICKNAME_TAKEN`; aluno em `POST /api/v1/scenarios` devolve 403. Ver `training-scenarios` RF-01 a RF-03. | 🟡 |
| RF-34 | O sistema carrega os 3 cenários base e o instrutor cria desafios com defeito oculto (RN-14). | Must | `GET /api/v1/scenarios?kind=base` devolve `stage1-oem`, `stage2-pops-bangs` e `standalone-swap`; aluno vê `hidden_defect = null`; bomba fraca de 90 L/h vira 1 falha física `fuel_pump_weak`. Ver `training-scenarios` RF-04, RF-05, RF-08. | 🟡 |
| RF-35 | O usuário inicia uma tentativa com baseline automática e o sistema classifica as puxadas válidas. | Must | A tentativa passa a `in_progress` com `baseline_run_id`; puxada com calibração alterada a meio fica `valid = false`. Ver `training-scenarios` RF-07, RF-09. | 🟡 |
| RF-36 | O sistema avalia a submissão de forma determinística e objetiva, com sonda de margem de knock (RN-02). | Must | Mesma entrada dá o mesmo `evaluation_sha256` em 20 repetições; 1 critério obrigatório reprovado dá `passed = false` com `total_score` 95. Ver `training-scenarios` RF-11 a RF-14. | 🟡 |
| RF-37 | O usuário exporta e importa pacotes de desafio e de tentativa com SHA-256 (RN-13). | Must | Pacote com 1 dígito alterado devolve 422 `PACKAGE_HASH_MISMATCH` sem gravar nada; a 2.ª importação do mesmo arquivo devolve `already_imported = true`. Ver `training-scenarios` RF-18 a RF-21. | 🟡 |
| RF-38 | O instrutor importa 20 a 50 pacotes e exporta as notas em CSV protegido contra fórmulas. | Must | 50 arquivos com 2 adulterados mostram 48 importados e 2 recusados; o CSV tem 1 cabeçalho + 48 linhas; `=HYPERLINK(1)` sai como `'=HYPERLINK(1)`. Ver `training-scenarios` RF-25, RF-26. | 🟡 |
| RF-39 | O sistema calcula a taxa de conclusão por cenário. | Must | Com 10 tentativas iniciadas e 8 aprovadas, `completion_rate_pct = 80.0`. Ver `training-scenarios` RF-16, RF-17. | 🟡 |

### 5.8 Jornadas ponta a ponta (integração final)

| ID | Requisito | Prioridade | Critério de aceite | Confidência |
|----|-----------|------------|--------------------|-------------|
| RF-40 | O sistema permite completar a jornada do Lucas, da baseline à puxada final segura. | Must | Com `seed` 42, boost 280 kPa abs e avanço +8°, 20 de 20 execuções terminam em knock `severe` e falha catastrófica; com o acerto corrigido (λ 0,80, −3° nos cilindros com knock, boost 230 kPa abs), 20 de 20 terminam sem knock acima de `light` e com integridade 100 %; o cenário `stage2-pops-bangs` aprova com Δwhp ≥ +65 e EGT ≤ 950 °C. Ver `knock-and-failure-model` G-01, G-02; `training-scenarios` cenários base. | 🟡 |
| RF-41 | O sistema permite completar a jornada do Rodrigo, do swap à validação em `multi_pull`. | Must | Teste E2E com `seed` 42: os 9 passos passam; o `multi_pull` de 3 puxadas tem `peak_whp_spread_pct` ≤ 2 % e nenhuma falha; a meta de potência segue a premissa da seção 10. Ver `ecu-profiles` RF-31. | 🟡 |
| RF-42 | O sistema permite completar a jornada do Prof. Marcos, do desafio à avaliação da turma. | Must | O desafio `challenge-400whp-e27` no `coupe-30t-i6` é exportado, a tentativa do aluno é importada, a avaliação é recalculada e os logs antes/depois são exportados e comparados. Ver `training-scenarios` RF-05, RF-20; `telemetry-datalogger` RF-17, RF-19. | 🟡 |

## 6. Requisitos Não Funcionais

| Tipo | Requisito | Evidência ou justificativa | Confidência |
|------|-----------|----------------------------|-------------|
| Desempenho (laço) | Laço físico ≥ 100 Hz em tempo real como mínimo de aceite, alvo 1000 Hz (fator de tempo real ≥ 1,0). | `_reversa_sdd/prd.md#3-métricas-de-sucesso`; `dyno-bench` RNF-01 | 🟡 |
| Desempenho (orçamento por tick) | A 1000 Hz: física média ≤ 0,5 ms e p99 ≤ 2,0 ms; ECU p99 ≤ 0,1 ms; dano média ≤ 0,05 ms; amostrador de telemetria ≤ 60 µs p95; dinamômetro ≤ 50 µs p95. | `engine-physics-core` RNF-01; `ecu-core` RNF-01; `knock-and-failure-model` RNF-01; `telemetry-datalogger` RNF-01; `dyno-bench` RNF-01 | 🟡 |
| Desempenho (telemetria) | Telemetria à UI entre 30 e 60 FPS (padrão 50); latência tick→envio ≤ 40 ms p95; banda ≤ 150 kB/s por conexão. | `_reversa_sdd/prd.md#3-métricas-de-sucesso`; `telemetry-datalogger` RF-05, RNF-02, RNF-03 | 🟡 |
| Desempenho (UI) | Cockpit ≥ 30 FPS p5 e alvo 60 FPS p50; edição de célula ≤ 100 ms p95; tempo até interação ≤ 2,5 s. | `dyno-cockpit-ui` RNF-01, RNF-05; `ecu-tuning-ui` RNF-01, RNF-05 | 🟡 |
| Hardware de referência | As metas de desempenho valem numa máquina com CPU de 4 núcleos, 8 GB de RAM e sem GPU dedicada. | `_reversa_sdd/prd.md#6-restrições` | 🟡 |
| Precisão física | Desvio < 5 % por ponto de RPM contra `Reference Benchmark Baseline v1` em torque, potência, lambda e EGT (°C). | `_reversa_sdd/prd.md#3-métricas-de-sucesso`; `vehicle-catalog` RF-29 | 🟡 |
| Determinismo | 100 % de hashes SHA-256 iguais em execuções repetidas na mesma imagem (física, dano, datalog, avaliação). | `engine-physics-core` RNF-03; `telemetry-datalogger` RNF-07; `training-scenarios` RNF-02 | 🟡 |
| Qualidade | Cobertura de testes ≥ 85 % por pacote de domínio do backend e ≥ 80 % nas features de frontend; 0 erros de verificação estática de tipos estrita; 0 achados de segurança de severidade média ou alta. | `platform-foundation` RF-19, RNF-04; `dyno-cockpit-ui` RNF-09; `ecu-tuning-ui` RNF-08 | 🟡 |
| Implantação | Um container Docker por estação, com a mesma imagem em dev, staging e prod; imagem ≤ 450 MB; limite de 3 CPUs e 3 GB por container. | `_reversa_sdd/prd.md#6-restrições`; `platform-foundation` RF-17, RF-18, RNF-05 | 🟡 |
| Arranque | Health `ok` em ≤ 60 s com volume vazio e ≤ 15 s com volume migrado. | `platform-foundation` RNF-02 | 🟡 |
| Privacidade | 0 campos de PII em modelos, logs e exports; 0 conexões de rede de saída. | `_reversa_sdd/prd.md#6-restrições`; `platform-foundation` RNF-06 | 🟡 |
| Conformidade de marcas | 0 termos da lista de bloqueio em textos exibidos, descritores e documentação da API. | `vehicle-catalog` RNF-08; `ecu-profiles` RNF-05 | 🟡 |
| Latência do laudo | Laudo forense pronto em ≤ 500 ms P95 após a falha. | `knock-and-failure-model` RNF-02 | 🟡 |
| Avaliação | Avaliação ≤ 5 s P95 sem sonda e ≤ 60 s P95 com sonda; importação de 50 pacotes ≤ 120 s. | `training-scenarios` RNF-01, RNF-03 | 🟡 |
| Acessibilidade | WCAG 2.1 AA nas telas de cockpit, ECU e cenários; 0 violações A/AA na verificação automática; nenhum flash acima de 3 Hz. | `dyno-cockpit-ui` RNF-06; `ecu-tuning-ui` RNF-06; `training-scenarios` RNF-07 | 🟡 |
| Compatibilidade | Navegadores desktop baseados em Chromium ≥ 120 e Firefox ≥ 120; resolução ≥ 1366×768; imagem para `amd64` e `arm64`. | `platform-foundation` RNF-08; `dyno-cockpit-ui` RNF-07, RNF-08 | 🟡 |
| Observabilidade | Logs estruturados em JSON, uma linha por evento, com `request_id`, sem IP nem nickname. | `platform-foundation` RF-13, RF-14 | 🟡 |

## 7. Critérios de Aceitação

```gherkin
# Cobre: RF-12, RF-14, RF-15, RF-16, RF-20, RF-22, RF-29, RF-40
Cenário: Jornada do Lucas, quebra por knock e acerto seguro no OEM-Stage
  Dado o hatch-20t-gdi com o perfil OEM-Stage, gasolina E27, seed 42 e a puxada base registrada
  Quando Lucas sobe o boost alvo para 280 kPa abs e soma 8° ao avanço base
  E executa uma sweep_pull
  Então o sistema registra knock da classe severe
  E emite uma falha catastrófica e termina a puxada em engine_failed
  E a cockpit abre a autópsia com a cadeia causal e as recomendações R-KNOCK-01 e R-LAMBDA-01
  Quando Lucas restaura o motor e aplica λ 0,80 em alta carga, −3° nos cilindros com knock, boost 230 kPa abs e overrun com proteção de EGT
  E executa a puxada final
  Então a puxada termina completed sem knock acima de light
  E a integridade fica em 100 % e a EGT fica ≤ 950 °C
  E o ganho sobre a baseline é ≥ +65 whp

# Cobre: RF-12, RF-20, RF-21, RF-23, RF-32, RF-41
Cenário: Jornada do Rodrigo, swap standalone até a validação térmica
  Dado o classic-20t-swap com a ECU OEM-Stage, etanol E100 e seed 42
  Quando Rodrigo troca a ECU para FT-Pro e completa a BaseSetup no assistente
  E constrói VE, lambda alvo e ignição, e ativa two-step e boost por marcha
  E executa uma multi_pull de 3 puxadas
  Então o motor funciona com o novo mapa
  E o peak_whp_spread_pct fica ≤ 2 %
  E nenhuma falha mecânica é registrada
  E a meta de potência do cenário standalone-swap é atingida

# Cobre: RF-34, RF-35, RF-36, RF-37, RF-38, RF-42, RF-27
Cenário: Jornada do Prof. Marcos, avaliação objetiva de um desafio
  Dado o desafio challenge-400whp-e27 no coupe-30t-i6 com min_whp 400, max_egt_c 900, knock retard ≤ 3° e integridade 100 %
  E o pacote do desafio importado na estação do aluno
  Quando o aluno submete o acerto e exporta o pacote da tentativa
  E o instrutor importa o pacote na estação dele
  Então o sistema recalcula a avaliação a partir das evidências
  E aprova só se todos os critérios obrigatórios passarem
  E o instrutor exporta e compara os logs antes e depois

# Cobre: RF-05, RF-06, RF-07, RF-08
Cenário: Física fiel ao benchmark canônico e determinística
  Dado um veículo validado do catálogo com a calibração de referência
  Quando o sistema executa uma varredura de 2000 rpm até a rotação máxima em passos de 250 rpm
  Então as curvas de torque, potência, lambda e EGT ficam com desvio < 5 % face ao Reference Benchmark Baseline v1
  E 20 execuções repetidas produzem o mesmo digest SHA-256

# Cobre: RF-03, RF-25, RF-28
Cenário: Desempenho no hardware de referência
  Dado uma máquina com 4 núcleos, 8 GB de RAM e sem GPU dedicada
  Quando uma puxada roda a 1000 Hz com a cockpit aberta e todos os painéis visíveis
  Então o laço físico mantém fator de tempo real ≥ 1,0 a pelo menos 100 Hz
  E a UI recebe telemetria a ≥ 30 FPS
  E GET /api/v1/health responde com P95 < 50 ms

# Cobre: RF-01, RF-04
Cenário: Arranque local sem rede
  Dado a imagem do container construída e um volume vazio
  Quando o operador sobe o container sem acesso à rede
  Então GET /api/v1/health devolve ok em ≤ 60 s
  E GET /api/v1/version devolve api_version v1

# Cobre: RF-02, RF-21 (caso negativo)
Cenário: Perfil de ECU inexistente
  Dado o sistema em funcionamento
  Quando o usuário pede GET /api/v1/ecu-profiles/nao-existe
  Então o sistema devolve 404 em formato ProblemDetail
  E o code é ECU_PROFILE_NOT_FOUND

# Cobre: RF-10 (caso negativo)
Cenário: Segunda sessão acima da capacidade
  Dado uma sessão ativa e o limite de 1 sessão por container
  Quando o usuário cria uma nova sessão
  Então o sistema devolve 409 com code SIM_CAPACITY_EXCEEDED

# Cobre: RF-15 (caso negativo)
Cenário: Puxada com motor destruído
  Dado uma sessão com engine_locked verdadeiro após falha catastrófica
  Quando o usuário pede uma nova puxada sem restaurar o motor
  Então o sistema devolve 409 com code ENGINE_DESTROYED
  E nenhuma combustão ocorre no laço

# Cobre: RF-37 (caso negativo)
Cenário: Pacote de tentativa adulterado
  Dado um pacote de tentativa com um limiar alterado e o hash original
  Quando o instrutor importa o pacote
  Então o sistema devolve 422 com code PACKAGE_HASH_MISMATCH
  E nada é gravado

# Cobre: RF-23 (caso negativo)
Cenário: Partida standalone sem setup mínimo
  Dado uma sessão em awaiting_base_setup após o swap para FT-Pro
  Quando o usuário pede uma puxada
  Então o sistema devolve 409 com code ECU_SETUP_INCOMPLETE e a lista de itens pendentes
  E o motor fica parado em ≤ 2 s

# Cobre: RF-19, RF-32 (caso negativo)
Cenário: Alteração de tabela bloqueada durante a puxada
  Dado uma puxada em running
  Quando o usuário aplica uma versão que altera uma tabela não live-tunable
  Então o sistema devolve 409 com a lista das tabelas bloqueadas
  E o editor mostra a tabela com cadeado e o texto "bloqueada durante a puxada"

# Cobre: RF-25
Cenário: seq contínuo com envelope de erro
  Dado um cliente WS conectado e sem perdas
  Quando o cliente envia uma subscrição inválida entre dois frames
  Então o cliente recebe seq n no frame, n+1 no error e n+2 no frame seguinte

# Cobre: RF-26 (caso negativo)
Cenário: Cliente WS lento não degrada o laço
  Dado um cliente WS que para de ler durante 10 s
  Quando a puxada continua
  Então o laço mantém ≥ 99 % de sim_hz
  E ao retomar o cliente recebe 100 % dos run.state e event.failure

# Cobre: RF-17
Cenário: Aborto por EGT acima do limite
  Dado o limite de EGT de 950 °C e o aborto por EGT ativo
  Quando a EGT pré-turbina fica em 960 °C durante 0,6 s
  Então a puxada termina aborted com abort_reason egt_limit

# Cobre: RF-09, RF-11
Cenário: Ordem do tick e sinal de knock canônico
  Dado uma sessão a 1000 Hz com stubs instrumentados
  Quando o laço executa 10 000 ticks
  Então cada tick segue a ordem sensors, ecu, physics, damage, telemetry
  E a ECU recebe knock_intensity entre 0,0 e 1,0 e a telemetria recebe knock_sensor_v entre 0,0 e 5,0 V

# Cobre: RF-18 (caso negativo)
Cenário: Conflito de versão de calibração
  Dado uma calibração na versão 3
  Quando o usuário grava uma alteração com versão base 2
  Então o sistema devolve 409 de conflito de versão
  E nenhuma versão nova é criada

# Cobre: RF-13, RF-27
Cenário: Datalog íntegro após reinício
  Dado uma sweep_pull de 15 s a 1000 Hz concluída
  Quando o container reinicia e o usuário exporta o log em JSON e o reimporta
  Então o resumo da puxada é igual ao gravado antes do reinício
  E o sha256 do log reimportado é igual ao original

# Cobre: RF-33 (caso negativo)
Cenário: Nickname com dado fora do padrão
  Dado o formulário de criação de perfil local
  Quando o usuário informa um nickname com "@"
  Então o sistema devolve 422
  E nenhum perfil é criado

# Cobre: RF-34, RF-36
Cenário: Defeito oculto invisível ao aluno
  Dado um desafio com bomba de combustível fraca de 90 L/h
  Quando um perfil student abre o desafio
  Então o campo hidden_defect vem nulo e has_hidden_defect vem verdadeiro
  E a sessão da tentativa recebe 1 falha física fuel_pump_weak

# Cobre: RF-39
Cenário: Taxa de conclusão de um cenário
  Dado 10 tentativas iniciadas e 8 aprovadas no cenário stage1-oem
  Quando o instrutor consulta as estatísticas do cenário
  Então completion_rate_pct é 80.0

# Cobre: RF-22
Cenário: Limite de torque do OEM-Stage com boost exagerado
  Dado o perfil OEM-Stage com torque_limit inalterado
  Quando o usuário aumenta a pressão alvo em 20 %
  Então o torque de freio fica ≤ 105 % do torque_limit de 2500 a 6000 rpm WOT
  E o canal de retardo de ignição por torque fica > 0

# Cobre: RF-24
Cenário: Erro de PMS vira sintoma físico
  Dado uma BaseSetup standalone com PMS configurado 8° fora do real
  Quando o motor funciona
  Então o avanço real fica 8,0° acima do comandado
  E o risco de knock aumenta de forma coerente

# Cobre: RF-31
Cenário: Operação de bloco no editor de tabela
  Dado uma tabela 16×16 aberta no workspace do perfil ativo
  Quando o usuário seleciona 4 células com valor 10 e aplica +2
  Então as 4 células passam a 12
  E o sistema grava a alteração num único PATCH após o debounce

# Cobre: RF-30
Cenário: Reconexão da telemetria
  Dado a cockpit conectada ao WS
  Quando a conexão cai
  Então a 1.ª tentativa de reconexão ocorre em 500 ± 50 ms
  E após 10 falhas a UI mostra "telemetria indisponível" com o botão "Tentar de novo"

# Cobre: RF-05 (caso negativo)
Cenário: Veículo em draft não abre sessão
  Dado o muscle-v8-sc em estado draft e a flag de drafts desligada
  Quando o usuário cria uma sessão com esse veículo
  Então o sistema devolve 409 com code VEHICLE_NOT_VALIDATED
```

## 8. Prioridade MoSCoW

| Item | MoSCoW | Justificativa |
|------|--------|---------------|
| RF-01 a RF-04 (plataforma) | Must | Base de todos os componentes; Sprint 1. |
| RF-05 a RF-09 (física e catálogo) | Must | Sem física fiel não há treino válido; métrica principal do PRD. |
| RF-10 a RF-17 (dinamômetro e falhas) | Must | Materializam a punição coerente do erro e o laudo causal. |
| RF-18 a RF-24 (ECU e perfis) | Must | Núcleo da calibração OEM e standalone. |
| RF-25 a RF-30 (telemetria e cockpit) | Must | Telemetria explicativa é premissa do produto. |
| RF-31, RF-32 (software de ECU) | Must | Interface de edição usada nas 3 jornadas. |
| RF-33 a RF-39 (treino) | Must | Critério do Prof. Marcos e métrica de conclusão. |
| RF-40 a RF-42 (jornadas) | Must | Critérios de aceite do PRD. |
| Dicas progressivas e replay de tentativas (`training-scenarios` RF-15, RF-22) | Should | Melhoram o ensino e a auditoria; não bloqueiam a avaliação. |
| Som do motor e superfície 3D (`dyno-cockpit-ui` RF-18; `ecu-tuning-ui` RF-12) | Should | Imersão; existe alternativa textual e mapa 2D. |
| Proteção de knock do operador e laudo near-miss (`dyno-bench` RF-16; `knock-and-failure-model` RF-30) | Should | Útil em demonstração do instrutor. |
| Cache opcional e trims de longo prazo (`platform-foundation` RF-22; `ecu-core` RF-10) | Should | Otimizações sem impacto nos critérios de aceite. |
| Modo dano desligado, comando variável e exibição em AFR (`knock-and-failure-model` RF-29; `ecu-core` RF-31; `ecu-tuning-ui` RF-22) | Could | Didáticos; o comando variável depende de modelo físico em aberto. |
| Itens da seção 1.3 | Won't | Não-objetivos do PRD. |
| RNF de desempenho e de precisão | Must | Métricas de sucesso do PRD com valor de aceite mínimo. |
| RNF de acessibilidade e compatibilidade | Should | Qualidade de uso; verificados por testes automáticos. |

## 9. Esclarecimentos

> Nenhuma sessão de dúvidas registrada ainda. Rode `/reversa-clarify` quando houver `[DÚVIDA]` pendente.

## 10. Lacunas

### 10.1 Dúvidas sem resposta nas specs (não bloqueiam o fluxo; viram premissas no plan)

- 🔴 [DÚVIDA] Escopo: a meta de potência do cenário `standalone-swap` é 300 whp absolutos no `classic-20t-swap` com E100 ou um Δwhp sobre a base OEM? Premissa proposta: `min_whp = 300`. Fonte: `_reversa_sdd/sdd/training-scenarios.md#14-open-questions` (OQ-06).
- 🔴 [DÚVIDA] Segurança: o SHA-256 dos pacotes detecta corrupção, mas não prova autoria, e o papel de instrutor não tem PIN na mesma estação. O MVP adota HMAC/assinatura e PIN? Premissa proposta: só SHA-256 + recálculo da avaliação + replay opcional, sem PIN. Fonte: `_reversa_sdd/sdd/training-scenarios.md#14-open-questions` (OQ-01, OQ-02).
- 🔴 [DÚVIDA] Métrica: a taxa de conclusão ≥ 80 % do PRD conta só os cenários base ou também os desafios do instrutor? Tentativas `abandoned` entram no denominador? Premissa proposta: só cenários base, com abandonadas no denominador. Fonte: `_reversa_sdd/sdd/training-scenarios.md#14-open-questions` (OQ-03).

### 10.2 Inconsistências entre specs (normalizar no plan)

- 🔴 Código de validação divergente: `VALIDATION_ERROR` (`dyno-bench`, `ecu-core`, `training-scenarios`, `vehicle-catalog`) e `VALIDATION_FAILED` (`platform-foundation`, `knock-and-failure-model`, `telemetry-datalogger`). Premissa: adotar o código do `platform-foundation`, dono do catálogo (RN-07).
- 🔴 Puxada simultânea: `dyno-cockpit-ui` cita `RUN_ALREADY_ACTIVE`; o dono `dyno-bench` define `RUN_IN_PROGRESS`. Premissa: `RUN_IN_PROGRESS`.
- 🔴 Concorrência de calibração: `ecu-tuning-ui` usa `base_revision`, `CALIBRATION_REVISION_CONFLICT` e `TABLE_LOCKED_DURING_RUN`; o dono `ecu-core` usa `base_version`, `CALIBRATION_VERSION_CONFLICT` e `TABLE_NOT_LIVE_TUNABLE`. Premissa: adotar os nomes do `ecu-core`.
- 🔴 Perfil de jogador inexistente: `training-scenarios` RF-02 devolve `ECU_PROFILE_NOT_FOUND`, código reservado ao perfil de ECU pela revisão R1. Premissa: criar `PLAYER_PROFILE_NOT_FOUND` no catálogo.
- 🔴 Taxa de `event.knock`: `knock-and-failure-model` RF-28 limita a 10 eventos/s por cilindro; `telemetry-datalogger` RF-11 limita a 1 evento por ciclo (≤ 50/s a 6000 rpm). Premissa: vale o limite mais restritivo (10/s por cilindro).

### 10.3 Questões abertas herdadas (decisão por benchmark ou default da spec)

- 🔴 Modo do worker (`process` ou `thread`) para cumprir 1000 Hz com telemetria a 50 FPS: decidir por benchmark no Sprint 1 (`platform-foundation` OQ-01; `engine-physics-core` OQ-01).
- 🔴 Calibração conjunta dos limiares de ponto quente por combustível com a escala térmica da física (`knock-and-failure-model` OQ-02).
- 🔴 Determinismo só na mesma imagem e arquitetura; entre `amd64` e `arm64` fica fora do MVP (`engine-physics-core` OQ-04).

## 11. Histórico de alterações

| Data | Alteração | Autor |
|------|-----------|-------|
| 2026-10-18 | Versão inicial gerada por `/reversa-requirements` (modo autônomo, greenfield), a partir do PRD, das personas, do ideation e das 11 specs SDD | reversa |

## Pendências de Qualidade

- Q-018 (SoluçãoImplícita): o documento cita Docker, ProblemDetail (RFC 7807), WebSocket e nomes de endpoints. Motivo: são restrições explícitas do PRD e contratos de integração entre specs. A ocorrência é intencional e não deve ser removida.
- Q-017 (SoluçãoImplícita): os critérios de aceite citam endpoints e códigos de erro como identificadores verificáveis. O documento não descreve algoritmos de implementação.
- Q-011 e Q-019 (Cobertura/Princípios): não se aplicam. O projeto é greenfield, sem `domain.md` e sem `.reversa/principles.md`. As regras citam as specs SDD como origem.
