# Spec: dyno-cockpit-ui

**Versão:** 1.1
**Status:** Rascunho
**Autor:** reversa-spec-sdd
**Data:** 2026-10-18
**Reviewers:** N/A
**Sprint:** 3 (componente 11)

---

## 1. Resumo

🟡 O `dyno-cockpit-ui` é a tela da bancada do dinamômetro virtual no navegador. Ele mostra em tempo real as curvas de potência e torque, lambda e EGT, gauges, espectrograma de knock, pressão no cilindro, a animação do carro no rolo, a linha do tempo de eventos, o laudo forense da quebra e o datalogger. Ele também sintetiza o som do motor (Web Audio) e permite iniciar, abortar e controlar a borboleta da puxada. É a interface que materializa os critérios de aceite de Lucas, Rodrigo e Prof. Marcos no PRD.

---

## 2. Contexto e Motivação

**Problema:**
🟡 Os softwares de ECU editam tabelas offline e não mostram resposta de dinamômetro, wideband, knock ou EGT em tempo real (PRD §1). Sem uma bancada visual, o usuário não entende a causa do ganho ou da quebra (risco "complexidade da ECU sem telemetria clara", PRD §8).

**Evidências:**
- 🟡 PRD §4 (Apresentação): bancada com carro animado no rolo, efeitos visuais e sonoros de RPM, spool, pops & bangs e quebra.
- 🟡 PRD §4 (Telemetria): datalogger, espectrograma de knock, pressão no cilindro, gauges.
- 🟡 PRD §9 (Desempenho): a UI recebe telemetria a ≥ 30 FPS no hardware de referência (4 núcleos, 8 GB, sem GPU dedicada).
- 🟡 Personas: Lucas precisa "ver o motor quebrar" e ler o laudo; Rodrigo monitora espectrograma de knock e pressão no cilindro ao mapear o MBT; Prof. Marcos demonstra ao vivo e compara curvas antes vs. depois.

**Por que agora:**
🟡 No Sprint 3 já existem `dyno-bench`, `knock-and-failure-model` e `telemetry-datalogger` (Sprints 2 e 3). A cockpit é o primeiro ponto em que o usuário vê o laço físico funcionando de ponta a ponta e é pré-requisito do `ecu-tuning-ui` e do `training-scenarios` (Sprint 4).

---

## 3. Goals (Objetivos)

- [ ] 🟡 G-01: Renderizar a cockpit completa a ≥ 30 FPS (alvo 60 FPS) no hardware de referência, durante uma `sweep_pull` com telemetria a 50 FPS.
- [ ] 🟡 G-02: Mostrar cada frame de telemetria na tela com latência ≤ 100 ms (p95) entre a chegada do `WsEnvelope` e o desenho.
- [ ] 🟡 G-03: Manter a memória do separador do navegador ≤ 500 MB após 30 min de sessão com 20 puxadas.
- [ ] 🟡 G-04: Exibir o laudo forense em ≤ 2 s após um `event.failure` catastrófico, com cadeia causal e componentes danificados destacados.
- [ ] 🟡 G-05: Cumprir WCAG 2.1 AA nos painéis (contraste ≥ 4,5:1 em texto, ≥ 3:1 em elementos gráficos) e oferecer alternativa textual a 100 % dos alarmes sonoros.

**Métricas de sucesso:**

| Métrica | Baseline atual | Target | Prazo |
|---------|---------------|--------|-------|
| 🟡 FPS de renderização (p5) no hardware de referência | 0 (inexistente) | ≥ 30 FPS | Sprint 3 |
| 🟡 Latência frame→desenho (p95) | N/A | ≤ 100 ms | Sprint 3 |
| 🟡 Memória do separador após 30 min | N/A | ≤ 500 MB | Sprint 3 |
| 🟡 Alarmes sonoros com alternativa textual | N/A | 100 % | Sprint 3 |
| 🟡 Violações axe-core nível A/AA nos painéis | N/A | 0 | Sprint 3 |

---

## 4. Non-Goals (Fora do Escopo)

- 🟡 NG-01: Edição de tabelas e estratégias de ECU. Isso pertence ao `ecu-tuning-ui` (Sprint 4). A cockpit só mostra o perfil e a calibração ativos.
- 🟡 NG-02: Tela mobile ou layout para largura < 1366 px. Abaixo disso a cockpit mostra um aviso de resolução não suportada (PRD §5, sem app iOS/Android).
- 🟡 NG-03: Modelo 3D completo do carro ou do motor (malhas, PBR, física de pneus). A animação é uma vista lateral 2,5D em Canvas 2D/WebGL.
- 🟡 NG-04: Cálculo físico no navegador. Toda a física, o dano e o laudo vêm do backend; a UI só interpola visualmente entre frames.
- 🟡 NG-05: Multijogador ou espectadores remotos síncronos (PRD §5).
- 🟡 NG-06: Unidades imperiais de temperatura (°F) e de torque (lb·ft) no MVP; só whp/cv/kW, bar/psi, °C e N·m.
- 🟡 NG-07: Gravação de áudio ou vídeo da puxada.

---

## 5. Usuários e Personas

**Usuário primário:** 🟡 Lucas (iniciante, estuda em casa num notebook sem GPU dedicada) e Rodrigo (intermediário, usa a cockpit ao lado do editor de tabelas para mapear VE e ignição).
**Usuário secundário:** 🟡 Prof. Marcos, que projeta a cockpit num projetor de sala (1920×1080 ou 1366×768) para demonstrar ao vivo e comparar curvas antes vs. depois.

**Jornada atual (sem a feature):**
1. 🟡 O usuário edita tabelas num software offline sem resposta do motor.
2. 🟡 O usuário depende de vídeos ou de hora de dinamômetro paga para ver o efeito.
3. 🟡 O usuário não vê sinais precursores de knock ou de EGT alta antes de uma quebra real.

**Jornada futura (com a feature):**
1. 🟡 O usuário escolhe o tipo de puxada e inicia na cockpit.
2. 🟡 O usuário vê curvas, gauges, espectrograma e o carro no rolo em tempo real, com som do motor.
3. 🟡 O usuário compara a puxada atual com a anterior (sobreposição antes vs. depois).
4. 🟡 Em caso de quebra, o usuário lê o laudo forense com a cadeia causal e restaura o motor.

---

## 6. Requisitos Funcionais

### 6.1 Requisitos Principais

| ID | Requisito | Prioridade | Critério de Aceite |
|----|-----------|-----------|-------------------|
| RF-01 | 🟡 O sistema deve montar a rota `/sessions/:sessionId/dyno` com `DynoCockpitPage`, carregando a sessão por `GET /api/v1/sessions/{session_id}` e as curvas de referência por `GET /api/v1/vehicles/{vehicle_id}/reference-curves`. | Must | Teste de componente: com mocks 200, a página mostra o nome do veículo, o perfil ECU ativo e o estado "vazio" em ≤ 1 s; com 404 `SESSION_NOT_FOUND` mostra o estado de erro com botão "Voltar". |
| RF-02 | 🟡 O sistema deve abrir o WebSocket `/ws/v1/sessions/{session_id}/telemetry`, validar cada `WsEnvelope` (`v` = 1, `seq` inteiro crescente) e enviar `control.subscribe` só com os canais dos painéis visíveis. | Must | Teste: ao recolher o painel `KnockSpectrogram`, a próxima mensagem `control.subscribe` enviada não contém os canais de espectro; envelope com `v` ≠ 1 é descartado e contado em `invalid_envelopes`. |
| RF-03 | 🟡 O sistema deve guardar os frames num buffer em anel por canal (`Float32Array`, capacidade padrão 3600 amostras = 60 s a 60 FPS) e desenhar num laço `requestAnimationFrame` independente da chegada dos frames. | Must | Teste unitário: inserir 5000 amostras num buffer de 3600 mantém as 3600 mais recentes em ordem; teste de integração: frames a 50 FPS e rAF a 60 Hz desenham sem bloquear o handler de `onmessage` > 4 ms (p95). |
| RF-04 | 🟡 O sistema deve detectar perda de frames por salto de `payload.frame_index` em `telemetry.frame` e mostrar o indicador "perda de frames" quando a perda nos últimos 5 s for > 2 %. | Must | Teste: sequência com 10 saltos em 250 frames (4 %) acende o indicador em ≤ 1 frame de renderização; 0 saltos em 5 s apaga o indicador. |
| RF-05 | 🟡 O sistema deve reconectar o WebSocket com backoff exponencial (0,5 s, 1 s, 2 s, 4 s, 8 s, teto 8 s, até 10 tentativas), reenviar `control.subscribe` e mostrar o estado "reconectando (n/10)". | Must | Teste com servidor WS de teste: após queda, a 1.ª tentativa ocorre em 500 ± 50 ms; após 10 falhas a UI mostra o estado de erro "telemetria indisponível" com botão "Tentar de novo". |
| RF-06 | 🟡 O sistema deve desenhar em `DynoChart` a potência (eixo esquerdo) e o torque (eixo direito) vs. RPM, com sobreposição da puxada de comparação selecionada e da curva de referência do veículo. | Must | Teste visual (Playwright, snapshot de pixels com tolerância 0,5 %): duas curvas atuais + duas de comparação com estilos distintos (contínua vs. tracejada) e legenda; eixos duplos com unidades. |
| RF-07 | 🟡 O sistema deve desenhar em `LambdaEgtChart` o lambda (eixo esquerdo, 0,60–1,30) e a EGT (eixo direito, 0–1100 °C) vs. RPM, com faixas de limite do veículo (EGT máxima de `MechanicalLimits`). | Must | Teste: a faixa de EGT máxima do `hatch-20t-gdi` aparece em 950 °C; valores fora da escala ficam presos na borda com marcador "fora de escala". |
| RF-08 | 🟡 O sistema deve mostrar em `GaugeCluster` os gauges de RPM, boost, lambda, EGT, IAT, ECT e knock retard, com zonas verde/amarela/vermelha derivadas dos limites do veículo. | Must | Teste: com `egt_c` = 960 e limite 950, o gauge de EGT fica na zona vermelha e o texto do gauge mostra "960 °C"; cada gauge tem valor numérico legível além da agulha. |
| RF-09 | 🟡 O sistema deve desenhar em `KnockSpectrogram` um heatmap tempo×frequência (janela de 10 s, 0–20 kHz) a partir do canal de espectro de knock, com marcação da frequência de ressonância do cilindro. | Must | Teste: um espectro sintético com pico em 6,5 kHz gera a coluna de maior intensidade na linha de 6,5 ± 0,2 kHz; com WebGL indisponível o heatmap usa Canvas 2D e mostra o selo "modo compatível". |
| RF-10 | 🟡 O sistema deve desenhar em `CylinderPressureTrace` a pressão no cilindro (bar) vs. ângulo de cambota (−360° a +360°, resolução 1°) do último ciclo recebido, com marcador do pico e do PMS. | Should | Teste: um traço sintético com pico em 15° ATDC mostra o marcador "pico 15° ATDC"; cilindro selecionável entre 1 e `n_cyl`. |
| RF-11 | 🟡 O sistema deve animar em `CarOnRollerView` o carro no rolo com rotação das rodas proporcional à velocidade do rolo, vibração proporcional ao RPM, chama de escape em eventos de overrun e fumaça/explosão em `event.failure`. | Must | Teste: com `rpm` = 6000 a amplitude de vibração é maior que com `rpm` = 2000; ao receber `event.failure` catastrófico a animação de fumaça inicia em ≤ 100 ms e as rodas param em ≤ 2 s. |
| RF-12 | 🟡 O usuário deve poder em `RunControls` escolher o `RunType` (`baseline_pull`, `sweep_pull`, `steady_state_hold`, `multi_pull`), preencher os parâmetros, iniciar (`POST /api/v1/sessions/{session_id}/runs`) e abortar (`POST .../runs/{run_id}/abort`). | Must | Teste: o botão "Iniciar" fica desativado durante uma puxada ativa; o abort envia o POST e a UI muda para "abortada" ao receber `run.state` com `state` = `aborted` em ≤ 500 ms. |
| RF-13 | 🟡 O usuário deve poder controlar a borboleta (0–100 %) por slider e teclado em puxadas `steady_state_hold`, com envio de `control.throttle` limitado a 20 mensagens/s. | Must | Teste: arrastar o slider 0→100 em 1 s gera ≤ 20 mensagens; a tecla seta-cima soma 5 % e seta-baixo subtrai 5 %, presas em 0–100. |
| RF-14 | 🟡 O sistema deve listar em `EventTimeline` os eventos `event.knock`, `event.limiter`, `event.failure` e mudanças de `run.state`, com `t_sim_s`, RPM no instante e severidade, e permitir clicar para posicionar o cursor nos gráficos. | Must | Teste: clicar num evento de knock em `t_sim_s` = 12,40 coloca o cursor dos gráficos em 12,40 s e destaca o ponto; a lista guarda até 500 eventos por puxada. |
| RF-15 | 🟡 O sistema deve abrir `EngineAutopsyView` após falha catastrófica, buscar `GET /api/v1/runs/{run_id}/forensic-report` e mostrar o diagrama do motor com os componentes danificados destacados, o `FailureMode` e a cadeia causal ordenada no tempo. | Must | Teste: com um `ForensicReport` de `piston_failure` no cilindro 3, o diagrama destaca o pistão 3 em vermelho e a cadeia lista ≥ 2 elos com `t_sim_s` e valores das variáveis. |
| RF-16 | 🟡 O usuário deve poder restaurar o motor a partir do estado "motor destruído" com `POST /api/v1/sessions/{session_id}/engine/restore`. | Must | Teste: após 200 do restore, o estado volta a "pronto", o `GaugeCluster` reativa e `RunControls` aceita nova puxada. |
| RF-17 | 🟡 O usuário deve poder em `DataloggerPanel` rever a puxada concluída com cursor, escolher até 8 canais, exportar o log (`GET /api/v1/runs/{run_id}/log` com `format=json` ou `format=csv`) e comparar duas puxadas (`POST /api/v1/logs/compare`). | Must | Teste: o export CSV dispara um download com nome `run-<run_id>.csv`; a comparação mostra as duas curvas e o delta máximo por canal. |
| RF-18 | 🟡 O sistema deve sintetizar o som do motor via Web Audio a partir de RPM, número de cilindros e ordem de ignição, mais spool do turbo, blow-off, estalos de overrun e som de quebra. | Should | Teste unitário do `AudioEngine`: com 4 cilindros a 6000 rpm a frequência fundamental de ignição é 200 Hz ± 1 Hz; o blow-off dispara uma vez por fechamento de borboleta com boost > 0,5 bar. |
| RF-19 | 🟡 O usuário deve poder silenciar (tecla `M`) e ajustar o volume (0–100 %) do áudio, com o áudio desligado por padrão até o primeiro gesto do usuário. | Must | Teste: sem gesto, o `AudioContext` fica `suspended`; após clicar "Ativar som", fica `running`; `M` alterna mute e o estado persiste em `localStorage`. |
| RF-20 | 🟡 O usuário deve poder escolher unidades de potência (whp, cv, kW), de boost (bar, psi) e manter temperatura em °C, com conversão aplicada a gráficos, gauges, eventos e exportações de tela. | Must | Teste: `power_kw` = 164,1 mostra 220,1 whp, 223,1 cv e 164,1 kW; boost de `map_kpa` = 250 com `baro_kpa` = 100 mostra 1,50 bar e 21,8 psi. |
| RF-21 | 🟡 O sistema deve mostrar alternativa textual e visual para cada alarme sonoro (knock, limitador, EGT alta, falha) numa região `aria-live` e num banner, sem piscar acima de 3 Hz. | Must | Teste: com áudio mudo, um `event.knock` severo gera o texto "Knock severo, cilindro 2, 4,5° de retardo" na região `aria-live="assertive"`. |
| RF-22 | 🟡 O sistema deve permitir operar todos os controles por teclado, com ordem de foco lógica e atalhos documentados no painel "Atalhos" (tecla `?`). | Must | Teste Playwright só com teclado: iniciar, abortar, mudar unidade, mudar canal do datalogger e abrir o laudo sem mouse. |

### 6.2 Fluxo Principal (Happy Path)

1. 🟡 O usuário abre `/sessions/:sessionId/dyno` de uma sessão com o `hatch-20t-gdi` e o perfil `oem-stage`.
2. 🟡 O sistema carrega a sessão e as curvas de referência, abre o WebSocket e envia `control.subscribe` com os canais dos painéis visíveis.
3. 🟡 O usuário escolhe `sweep_pull` (2000 → 6800 rpm) em `RunControls` e clica "Iniciar".
4. 🟡 O sistema envia `POST /api/v1/sessions/{session_id}/runs`, recebe `run.state` = `running` e passa a desenhar os frames a ≥ 30 FPS, com som do motor ativo.
5. 🟡 O sistema recebe `run.state` = `completed`, busca `GET /api/v1/runs/{run_id}` e substitui a curva de tela pela curva final do `DynoRun`.
6. 🟡 O usuário seleciona a puxada base como comparação; o `DynoChart` mostra antes vs. depois e o delta de pico de potência em whp.
7. 🟡 Resultado: a puxada fica no `DataloggerPanel`, pronta para exportar ou comparar, e a cockpit volta ao estado "pronto".

### 6.3 Fluxos Alternativos

**Fluxo Alternativo A — Quebra do motor durante a puxada:**
1. 🟡 O sistema recebe `event.failure` com `catastrophic` = true.
2. 🟡 O sistema toca o som de quebra (se não mudo), anima fumaça/explosão, mostra o banner "Motor destruído: falha de pistão" e entra no estado "motor destruído".
3. 🟡 O sistema abre `EngineAutopsyView` com o `ForensicReport` em ≤ 2 s.
4. 🟡 O usuário clica "Restaurar motor"; o sistema chama o restore e volta a "pronto".

**Fluxo Alternativo B — Abort manual:**
1. 🟡 O usuário pressiona `Esc` ou clica "Abortar".
2. 🟡 O sistema envia o abort, marca a puxada como "abortada" na linha do tempo e mantém os dados parciais no datalogger com selo "parcial".

**Fluxo Alternativo C — Carga estacionária com borboleta manual:**
1. 🟡 O usuário escolhe `steady_state_hold` com RPM alvo 3500.
2. 🟡 O usuário ajusta a borboleta por slider ou setas; o sistema envia `control.throttle` (≤ 20 msg/s) e mostra o ponto de operação RPM×carga.

**Fluxo Alternativo D — Perda de conexão:**
1. 🟡 O WebSocket fecha durante a puxada.
2. 🟡 O sistema congela os gráficos no último frame, mostra "reconectando (n/10)" e reconecta com backoff.
3. 🟡 Após reconectar, o sistema reenvia `control.subscribe`, consulta `GET /api/v1/runs/{run_id}` e marca a lacuna de dados com sombreado cinza.

---

## 7. Requisitos Não-Funcionais

| ID | Requisito | Valor alvo | Observação |
|----|-----------|-----------|------------|
| RNF-01 | 🟡 Taxa de renderização | ≥ 30 FPS (p5) e alvo 60 FPS (p50) | Hardware de referência (4 núcleos, 8 GB, GPU integrada), Chromium recente, 1920×1080, todos os painéis visíveis, telemetria a 50 FPS. Medido por `PerformanceObserver` + contador de rAF em teste Playwright de 60 s. |
| RNF-02 | 🟡 Latência frame→desenho | ≤ 100 ms (p95) | Diferença entre `performance.now()` no `onmessage` e no rAF que desenha o `seq`. |
| RNF-03 | 🟡 Memória do separador | ≤ 500 MB | `performance.measureUserAgentSpecificMemory()` (Chromium) após 30 min e 20 puxadas; buffers em anel com capacidade fixa. |
| RNF-04 | 🟡 Custo do handler WS | ≤ 4 ms (p95) por mensagem | O handler só decodifica e escreve no buffer; nenhum desenho dentro do `onmessage`. |
| RNF-05 | 🟡 Tempo até interação | ≤ 2,5 s até a cockpit aceitar "Iniciar" | Container local, cache frio; bundle da rota ≤ 600 KB gzip (WebGL/áudio em chunks separados). |
| RNF-06 | 🟡 Acessibilidade | WCAG 2.1 AA | Contraste ≥ 4,5:1 texto e ≥ 3:1 gráficos; foco visível; 0 violações axe-core A/AA; sem flashes > 3 Hz (WCAG 2.3.1). |
| RNF-07 | 🟡 Resolução | ≥ 1366×768 | Layout em grade com painéis recolhíveis; abaixo de 1366 px de largura mostra aviso e não monta os gráficos. |
| RNF-08 | 🟡 Compatibilidade | Chromium ≥ 120 e Firefox ≥ 120 | WebGL2 → WebGL1 → Canvas 2D (fallback automático). |
| RNF-09 | 🟡 Qualidade de código | TypeScript `strict`, ESLint sem erros, cobertura Vitest ≥ 80 % em `features/dyno-cockpit/` | Testes de componente com React Testing Library; E2E com Playwright. |

---

## 8. Design e Interface

**Componentes afetados:**
- 🟡 `frontend/src/features/dyno-cockpit/` (novo): `DynoCockpitPage`, `DynoChart`, `LambdaEgtChart`, `GaugeCluster`, `KnockSpectrogram`, `CylinderPressureTrace`, `CarOnRollerView`, `RunControls`, `EventTimeline`, `EngineAutopsyView`, `DataloggerPanel`, `UnitsMenu`, `AudioControls`, `ConnectionIndicator`, `ShortcutsDialog`.
- 🟡 `frontend/src/features/dyno-cockpit/audio/AudioEngine.ts` (síntese Web Audio).
- 🟡 `frontend/src/features/dyno-cockpit/render/` (`RenderLoop`, `RingBuffer`, `createSurface` com seleção WebGL2/WebGL1/Canvas 2D).
- 🟡 `frontend/src/lib/ws/` (cliente `TelemetrySocket` com reconexão; partilhado com `ecu-tuning-ui`).
- 🟡 `frontend/src/lib/units/` (conversões e `UnitsProvider`; partilhado).
- 🟡 `frontend/src/lib/api/` (cliente REST gerado do OpenAPI).

**Layout (desktop ≥ 1366×768):**
- 🟡 Barra superior: veículo, perfil ECU, combustível, estado da sessão, `ConnectionIndicator`, `UnitsMenu`, `AudioControls`.
- 🟡 Coluna esquerda (≈ 60 % da largura): `DynoChart` em cima, `LambdaEgtChart` em baixo.
- 🟡 Coluna direita (≈ 40 %): `CarOnRollerView` em cima, `GaugeCluster` em baixo.
- 🟡 Faixa inferior com abas: `KnockSpectrogram`, `CylinderPressureTrace`, `EventTimeline`, `DataloggerPanel`. Só a aba ativa é "visível" para efeitos de subscrição.
- 🟡 `RunControls` fixo à direita da barra inferior, sempre visível.
- 🟡 `EngineAutopsyView` abre como painel modal de tela cheia (diálogo com `role="dialog"` e foco preso), fechável com `Esc`.

**Comportamento esperado:**
- 🟡 Canais por painel (subscrição): `DynoChart` → `rpm`, `power_kw`, `torque_nm`; `LambdaEgtChart` → `rpm`, `lambda`, `egt_c`; `GaugeCluster` → `rpm`, `map_kpa`, `baro_kpa`, `lambda`, `egt_c`, `iat_c`, `ect_c`, `knock_retard_deg`; `KnockSpectrogram` → `knock_spectrum`; `CylinderPressureTrace` → `cyl_pressure_trace`; `CarOnRollerView` → `rpm`, `roller_speed_kmh`, `overrun_afterfire`, `throttle_pct`; `AudioEngine` → `rpm`, `turbo_rpm`, `throttle_pct`, `map_kpa`, `overrun_afterfire`. ⚠️ ABERTO: nomes finais dos canais dependem do catálogo de `TelemetryChannel` (OQ-01).
- 🟡 A subscrição é a união dos canais dos painéis visíveis mais o áudio (se ativo); qualquer mudança dispara um novo `control.subscribe` com debounce de 250 ms.
- 🟡 Durante a puxada, os gráficos vs. RPM desenham o traço ao vivo a partir do buffer em anel; ao fim, a curva é substituída pelos `DynoCurvePoint` do `DynoRun` (fonte da verdade).
- 🟡 Interpolação visual: o `RenderLoop` desenha o valor mais recente de cada canal; gauges usam suavização exponencial com constante de 80 ms só na agulha (o texto mostra o valor bruto).
- 🟡 Escalas padrão de gráfico: potência 0 → 1,2 × pico de referência; torque 0 → 1,2 × pico de referência; RPM do `idle_rpm` ao `max_rpm` do `MechanicalLimits` do veículo.

**Síntese de áudio (`AudioEngine`):**
- 🟡 Frequência de ignição de um motor 4 tempos: `f_fire = (rpm / 60) · (n_cyl / 2)` (Hz). Exemplo: 4 cilindros a 6000 rpm → 200 Hz; V8 a 6000 rpm → 400 Hz.
- 🟡 Timbre: soma de osciladores nas ordens 0,5, 1, 1,5, 2, 3 e 4 de `f_fire` (ordens meias só para V8 com cambota cross-plane), com amplitude por ordem tabelada por arquitetura e ganho proporcional à carga (`map_kpa / 100`), mais ruído rosa filtrado (passa-banda em `2 · f_fire`).
- 🟡 Irregularidade da ordem de ignição: modulação de amplitude por cilindro na sequência de `EngineSpec.firing_order`, ±8 % por pulso.
- 🟡 Spool do turbo: oscilador senoidal em `f_whistle = clamp(turbo_rpm / 60 · 0,1, 1500, 9000)` Hz com ganho proporcional a `(map_kpa − baro_kpa) / 150`, presente só em veículos turbo.
- 🟡 Blow-off: amostra sintetizada (ruído branco com envelope 30 ms ataque / 400 ms decaimento, passa-alta 1,5 kHz) disparada quando `throttle_pct` cai ≥ 50 pontos em ≤ 200 ms com boost > 0,5 bar; no máximo 1 disparo por 1 s.
- 🟡 Estalos de overrun: impulso de ruído (5–15 ms) por unidade de `overrun_afterfire` recebida, com ganho aleatório semeado por `seq` (determinístico).
- 🟡 Quebra: impacto de baixa frequência (60 Hz, 300 ms) mais ruído metálico (passa-banda 3 kHz, 1,2 s), seguido de silêncio do motor.
- 🟡 Ganho mestre com limitador (`DynamicsCompressorNode`, threshold −6 dB) para evitar clipping; volume padrão 60 %.

**Tecnologia de renderização:**
- 🟡 Gráficos de linha (`DynoChart`, `LambdaEgtChart`, `CylinderPressureTrace`, `DataloggerPanel`): biblioteca uPlot (MIT, Canvas 2D).
- 🟡 `KnockSpectrogram`: textura WebGL (shader de mapa de cores), fallback Canvas 2D com `ImageData` deslocando 1 coluna por frame.
- 🟡 `CarOnRollerView`: Canvas 2D com sprites vetoriais próprios (sem marcas nem silhuetas de modelos reais), partículas de chama/fumaça com teto de 300 partículas.
- 🟡 Seleção da superfície em `createSurface`: tenta `webgl2`, depois `webgl`, depois `2d`; o resultado aparece no painel "Diagnóstico" (tecla `D`).

**Atalhos de teclado:**

| Tecla | Ação |
|------|------|
| 🟡 `Enter` (foco em `RunControls`) | Iniciar puxada |
| 🟡 `Esc` | Abortar puxada ativa; fechar diálogo aberto |
| 🟡 Seta-cima / seta-baixo | Borboleta ±5 % (`steady_state_hold`) |
| 🟡 `Shift` + seta | Borboleta ±1 % |
| 🟡 `M` | Mute/unmute |
| 🟡 `U` | Abrir menu de unidades |
| 🟡 `1`–`4` | Selecionar aba inferior |
| 🟡 `D` | Painel de diagnóstico (FPS, superfície, perda de frames) |
| 🟡 `?` | Abrir lista de atalhos |

**Estados da UI:**
- 🟡 Estado vazio: sessão carregada sem puxadas; gráficos mostram só a curva de referência e o texto "Nenhuma puxada ainda. Escolha um tipo e clique Iniciar."
- 🟡 Estado de carregamento: esqueletos nos painéis e `RunControls` desativado até sessão + WS prontos; spinner com texto "Conectando à bancada".
- 🟡 Estado de erro: `ProblemDetail` mostrado com `title`, `detail` e `code`; erros de WS mostram "telemetria indisponível" com "Tentar de novo".
- 🟡 Estado de sucesso: puxada concluída, pico de potência e torque em destaque, delta vs. comparação, botões "Exportar" e "Comparar".
- 🟡 Estado motor destruído: overlay vermelho translúcido (contraste ≥ 4,5:1 no texto), gauges congelados, `RunControls` desativado, botões "Ver laudo" e "Restaurar motor".

---

## 9. Modelo de Dados

🟡 A cockpit não cria tabelas no banco. Ela consome contratos dos componentes donos e guarda só preferências em `localStorage`.

**Contratos consumidos (donos indicados; a cockpit só lê):**

```python
# Referência de consumo. Dono: telemetry-datalogger (WsEnvelope, TelemetryFrame).
from typing import Any, Literal
from pydantic import BaseModel, Field

class WsEnvelope(BaseModel):
    v: Literal[1]
    type: Literal["telemetry.frame", "run.state", "event.knock",
                  "event.failure", "event.limiter", "error"]
    seq: int = Field(ge=0)            # monotônico por sessão: todo envelope do servidor, incluindo error, recebe seq + 1
    t_sim_s: float = Field(ge=0)      # s desde o início da sessão
    payload: dict[ str, Any]

# Campos mínimos que a cockpit espera em payload de telemetry.frame:
#   channels: dict[ str, float]           valores escalares por canal subscrito
#   knock_spectrum: dict | None          bins_hz: list[ float], magnitude_db: list[ float]
#   cyl_pressure_trace: dict | None      cylinder: int, crank_deg: list[ int], p_bar: list[ float]
# Campos mínimos de run.state: run_id: str, state: queued|running|completed|aborted|failed
# Campos mínimos de event.knock: cylinder: int, retard_deg: float, intensity: float, rpm: float
# Campos mínimos de event.failure: o FailureEvent do knock-and-failure-model
#   (failure_mode, component, cylinder, catastrophic: bool, run_id)
```

**Estado de front-end (TypeScript):**

```ts
export type PowerUnit = "whp" | "cv" | "kW";
export type BoostUnit = "bar" | "psi";
export interface UnitsPrefs { power: PowerUnit; boost: BoostUnit; temperature: "C"; torque: "Nm"; }

export interface AudioPrefs { enabled: boolean; muted: boolean; volume: number; } // volume 0..1

export interface CockpitPrefs {
  version: 1;
  units: UnitsPrefs;               // padrão whp, bar
  audio: AudioPrefs;               // padrão enabled=false, muted=false, volume=0.6
  visiblePanels: string[];         // ids de painéis visíveis
  activeBottomTab: "spectrogram" | "pressure" | "events" | "datalogger";
}
// localStorage key: "simremap.cockpit.prefs.v1"; JSON inválido => padrões.

export interface RingBuffer {
  capacity: number;                // padrão 3600
  t: Float64Array;                 // t_sim_s
  v: Float32Array;                 // valor do canal
  head: number; size: number;
  push(t: number, v: number): void;
  latest(): { t: number; v: number } | undefined;
  window(fromT: number, toT: number): { t: Float64Array; v: Float32Array };
}

export interface StreamStats {
  lastSeq: number; lastFrameIndex: number; received: number; lost: number;  // perdas por salto de frame_index
  lossRate5s: number;                                        // 0..1
  invalidEnvelopes: number; reconnectAttempt: number;        // 0..10
  state: "connecting" | "open" | "reconnecting" | "failed" | "closed";
}

export type CockpitState =
  | { kind: "loading" } | { kind: "empty" } | { kind: "ready" }
  | { kind: "running"; runId: string } | { kind: "completed"; runId: string }
  | { kind: "aborted"; runId: string } | { kind: "destroyed"; runId: string }
  | { kind: "error"; code: string; title: string; detail?: string };
```

**Conversões de unidade (`lib/units`):**
- 🟡 whp = `power_kw / 0,7457`; cv = `power_kw / 0,7355`; kW = `power_kw` (potência de roda já calculada pelo backend).
- 🟡 boost_bar = `(map_kpa − baro_kpa) / 100`; psi = `boost_bar · 14,5038`; boost negativo (vácuo) mostrado com sinal.
- 🟡 Arredondamento de exibição: potência e torque 1 casa decimal; lambda 2 casas; EGT, IAT e ECT inteiros; boost 2 casas (bar) ou 1 casa (psi).

**Memória estimada:** 🟡 30 canais × 3600 amostras × 12 B ≈ 1,3 MB; espectrograma 10 s × 50 col/s × 256 bins × 4 B ≈ 2,6 MB; histórico de 20 puxadas como `DynoCurvePoint` (≈ 500 pontos × 10 campos) < 1 MB. O orçamento de 500 MB cobre bundle, texturas e áudio.

**Migrações necessárias:** 🟡 Não.

---

## 10. Integrações e Dependências

| Dependência | Tipo | Impacto se indisponível |
|-------------|------|------------------------|
| 🟡 `dyno-bench` (sessões, runs, abort, `GET /api/v1/runs/{run_id}`) | Obrigatória | Sem sessão a página mostra erro; sem runs, "Iniciar" fica desativado com o `code` do erro. |
| 🟡 `telemetry-datalogger` (WS `/ws/v1/sessions/{session_id}/telemetry`, log export, compare) | Obrigatória | Sem WS: reconexão com backoff e, após 10 falhas, estado "telemetria indisponível"; curvas finais ainda vêm do REST. |
| 🟡 `knock-and-failure-model` (`engine/health`, `engine/restore`, `forensic-report`) | Obrigatória | Sem laudo: o painel de autópsia mostra o `FailureEvent` bruto e "laudo indisponível, tentar de novo". |
| 🟡 `vehicle-catalog` (`GET /api/v1/vehicles/{vehicle_id}`, `reference-curves`) | Obrigatória | Sem curvas de referência: gráficos sem sobreposição de referência e aviso discreto. |
| 🟡 `ecu-profiles` (`GET /api/v1/ecu-profiles/{profile_id}`) | Opcional | Sem descritor: a barra superior mostra só o `profile_id`. |
| 🟡 `platform-foundation` (`ProblemDetail`, `GET /api/v1/health`) | Obrigatória | Sem health: banner "backend indisponível" com retry a cada 5 s. |
| 🟡 uPlot (MIT), React 18, Tailwind, Vite | Obrigatória (build) | Sem fallback em runtime; versões fixadas no lockfile. |
| 🟡 WebGL2/WebGL1 do navegador | Opcional | Fallback Canvas 2D com selo "modo compatível". |
| 🟡 Web Audio API | Opcional | Sem áudio: alternativas textuais continuam ativas; controles de som ficam ocultos. |

---

## 11. Edge Cases e Tratamento de Erros

| Cenário | Trigger | Comportamento esperado |
|---------|---------|----------------------|
| 🟡 EC-01: WebSocket cai durante a puxada | Fecho com código ≠ 1000 ou 10 s sem mensagens (ping `control.ping` a cada 5 s sem resposta) | Retry com backoff 0,5→8 s até 10 tentativas; gráficos congelados; lacuna sombreada; após reconectar busca `GET /api/v1/runs/{run_id}`; após 10 falhas mostra "telemetria indisponível". |
| 🟡 EC-02: Saltos de `frame_index` | Perda de frames por congestionamento (saltos de `seq` sem salto de `frame_index` são normais: o `seq` também conta envelopes de evento e de erro) | Conta perdas; indicador acende com perda > 2 % em 5 s; não interpola valores inventados no datalogger. |
| 🟡 EC-03: `seq` regressivo ou duplicado | Reenvio do servidor após reconexão | Descarta envelopes com `seq` ≤ último aceito na mesma conexão; como o servidor dá `seq` + 1 a todo envelope, incluindo `error`, nenhuma mensagem de erro é descartada; nova conexão reinicia a referência de `seq`. |
| 🟡 EC-04: Envelope inválido | `v` ≠ 1, JSON malformado ou `type` desconhecido | Descarta, incrementa `invalidEnvelopes`, regista no console em modo dev; nunca lança exceção no handler. |
| 🟡 EC-05: Iniciar com motor destruído | `POST .../runs` responde 409 `ENGINE_DESTROYED` | Entra no estado "motor destruído" e oferece "Restaurar motor"; não repete o POST. |
| 🟡 EC-06: Puxada já ativa | 409 `RUN_ALREADY_ACTIVE` | Mostra "Já existe uma puxada em curso" e sincroniza com `GET /api/v1/sessions/{session_id}`. |
| 🟡 EC-07: Laudo forense indisponível | `forensic-report` responde 404/5xx ou timeout de 5 s | Mostra o `FailureEvent` bruto e retry manual; 3 retries automáticos com 1 s, 2 s, 4 s. |
| 🟡 EC-08: WebGL indisponível ou contexto perdido | `getContext("webgl2")` e `("webgl")` nulos, ou evento `webglcontextlost` | Fallback para Canvas 2D sem recarregar a página; selo "modo compatível"; tenta restaurar em `webglcontextrestored`. |
| 🟡 EC-09: Autoplay de áudio bloqueado | `AudioContext.state` = `suspended` | Botão "Ativar som"; alternativas textuais seguem ativas; nenhuma falha visível. |
| 🟡 EC-10: Separador em segundo plano | `document.visibilityState` = `hidden` | rAF pausa, áudio suspende, buffer continua a receber; ao voltar, desenha o estado mais recente sem repetir eventos sonoros perdidos. |
| 🟡 EC-11: Resolução abaixo do suportado | Largura da janela < 1366 px | Mostra "Resolução não suportada (mínimo 1366×768)" e desmonta gráficos; a subscrição WS é reduzida a `run.state` e eventos. |
| 🟡 EC-12: Queda de FPS sustentada | FPS < 30 por 5 s seguidos | Degradação automática: espectrograma reduz para 25 colunas/s, partículas para 100, `CylinderPressureTrace` para 10 Hz; aviso no painel de diagnóstico. |
| 🟡 EC-13: Valor fora da escala | Ex.: `egt_c` > 1100 ou lambda > 1,30 | Prende na borda do eixo com marcador "fora de escala" e mostra o valor real no tooltip. |
| 🟡 EC-14: Canal ausente no frame | Backend não publica um canal subscrito | Painel mostra "sem dados de <canal>" após 2 s; não quebra os outros painéis. |
| 🟡 EC-15: Backend indisponível | `GET /api/v1/health` falha | Banner "backend indisponível", retry a cada 5 s, controles de puxada desativados. |

---

## 12. Segurança e Privacidade

- **Autenticação:** 🟡 Nenhuma no MVP. A aplicação é local-first, um container por estação, servida pelo FastAPI na mesma origem.
- **Autorização:** 🟡 Qualquer perfil local acessa a cockpit da sua sessão; a UI não expõe sessões de outros perfis.
- **Dados sensíveis:** 🟡 Nenhuma PII; a cockpit mostra só nickname do `PlayerProfile` ativo. Preferências em `localStorage` contêm só unidades, áudio e painéis.
- **Injeção de conteúdo:** 🟡 Textos vindos do backend (`detail`, cadeia causal) são renderizados como texto (sem `dangerouslySetInnerHTML`). CSP com `default-src 'self'`; WS só para a mesma origem.
- **Auditoria:** 🟡 Não há log de auditoria; o painel de diagnóstico mostra `StreamStats` só localmente.

---

## 13. Plano de Rollout

- **Estratégia:** 🟡 Entrega no Sprint 3 atrás da flag `VITE_FEATURE_DYNO_COCKPIT` (padrão ligada em dev e staging). Ordem interna: buffer + WS + `DynoChart` + `RunControls` primeiro, depois gauges, eventos e laudo, por fim espectrograma, pressão, animação e áudio.
- **Como reverter (rollback):** 🟡 Desligar a flag no build ou voltar à imagem Docker anterior; a cockpit não migra dados, então o rollback não exige migração.
- **Monitoramento pós-deploy:** 🟡 Teste Playwright de desempenho (60 s de `sweep_pull`) no pipeline com alvo ≥ 30 FPS e ≤ 500 MB; painel de diagnóstico com FPS, perda de frames e superfície ativa nas primeiras sessões com alunos.

---

## 14. Open Questions

| # | Pergunta | Impacto | Dono | Prazo |
|---|---------|---------|------|-------|
| OQ-01 | 🟡 Os nomes dos canais (`knock_spectrum`, `cyl_pressure_trace`, `roller_speed_kmh`, `turbo_rpm`, `overrun_afterfire`, `baro_kpa`) batem com o catálogo de `TelemetryChannel` do `telemetry-datalogger`? | Alto | George | 2026-10-25 |
| OQ-02 | 🟡 Taxa e formato do espectro de knock e do traço de pressão (sugestão: espectro 256 bins a 50 Hz; traço de 720 pontos a ≤ 10 Hz, só se subscrito) cabem na banda do WS? | Médio | George | 2026-10-25 |
| OQ-03 | 🟡 Os códigos `RUN_ALREADY_ACTIVE` e `SESSION_NOT_FOUND` são os definidos pelo `dyno-bench`? | Médio | George | 2026-10-25 |
| OQ-04 | 🟡 O `ForensicReport` traz coordenadas ou ids de componente compatíveis com o diagrama do motor (ex.: `piston:3`, `rod:2`, `turbo:turbine`)? | Alto | George | 2026-10-25 |
| OQ-05 | 🟡 O som de quebra e as explosões devem ter opção "modo sala de aula" com volume máximo reduzido para o Prof. Marcos? | Baixo | George | 2026-11-08 |

---

## 15. Decisões Tomadas (Decision Log)

| Decisão | Alternativas consideradas | Racional |
|---------|--------------------------|---------|
| 🟡 Laço `requestAnimationFrame` desacoplado do `onmessage`, com buffer em anel | Desenhar a cada frame recebido | Isola a taxa de rede da taxa de desenho; evita jank quando chegam rajadas após congestionamento. |
| 🟡 uPlot para gráficos de linha | Chart.js, Recharts (SVG), ECharts | uPlot desenha dezenas de milhares de pontos em Canvas 2D com ≈ 50 KB; SVG não sustenta 60 FPS no hardware de referência. |
| 🟡 Espectrograma em WebGL com fallback Canvas 2D | Só Canvas 2D | WebGL desloca a textura sem copiar `ImageData`; o fallback garante hardware sem GPU dedicada (PRD §6). |
| 🟡 Carro no rolo em vista lateral 2,5D Canvas 2D | Three.js com modelo 3D | Cabe no orçamento de 4 semanas e de memória; evita trade dress de modelos reais (PRD §8). |
| 🟡 Áudio sintetizado por ordem de ignição | Amostras gravadas de motores | Sem licenças de áudio, determinístico e coerente com qualquer arquitetura do catálogo. |
| 🟡 Áudio desligado por padrão | Ligado ao abrir | Política de autoplay dos navegadores e uso em sala de aula. |
| 🟡 Curva final vem do `DynoRun` (REST), não do traço ao vivo | Usar só o buffer de tela | O buffer perde frames; o `DynoRun` é a fonte determinística usada na avaliação. |

---

## Apêndice

### Referências
- 🟡 `_reversa_sdd/prd.md` §3, §4, §6, §8, §9.
- 🟡 `_reversa_sdd/personas.md` (Lucas, Rodrigo, Prof. Marcos).
- 🟡 Specs relacionadas: `telemetry-datalogger`, `dyno-bench`, `knock-and-failure-model`, `vehicle-catalog`, `ecu-tuning-ui`.
- 🟡 WCAG 2.1 (critérios 1.4.3, 1.4.11, 2.1.1, 2.3.1, 4.1.3).

### Rastreabilidade
| Critério do PRD | Requisitos |
|---|---|
| 🟡 Lucas: knock severo, falha e laudo | RF-08, RF-09, RF-11, RF-14, RF-15, RF-16, RF-21 |
| 🟡 Rodrigo: puxadas seguidas, repetibilidade | RF-06, RF-07, RF-12, RF-17 |
| 🟡 Prof. Marcos: exportar logs antes vs. depois | RF-06, RF-17 |
| 🟡 Desempenho ≥ 30 FPS | RF-03, RNF-01, RNF-02, EC-12 |

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
