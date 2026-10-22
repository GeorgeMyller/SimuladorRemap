# Spec: knock-and-failure-model

**Versão:** 1.1
**Status:** Rascunho
**Autor:** reversa-spec-sdd
**Data:** 2026-10-18
**Reviewers:** N/A
**Sprint:** 2 (componente 2 do sprint; posição 5 da ordem aprovada)

---

## 1. Resumo

🟡 O componente `knock-and-failure-model` (pacote `backend/src/simremap/damage/`) transforma cada `CombustionEvent` e cada `EngineState` produzidos pela física em detonação, pré-ignição, acumulação de dano por componente e falhas mecânicas determinísticas.
🟡 Ele calcula a integral de Livengood-Wu com o atraso de autoignição de Douaud-Eyzat sobre a zona não queimada, classifica a intensidade de knock, gera o sinal de knock sintético por cilindro para a ECU e o espectro para o espectrograma, mantém a saúde (`ComponentHealth` 0..1) de pistões, bielas, válvulas, junta/cabeçote, turbina e bronzinas, bloqueia o motor após uma falha catastrófica e produz o laudo forense (`ForensicReport`) com a cadeia causal, os sinais de aviso antecipados e recomendações didáticas para as 3 personas.

---

## 2. Contexto e Motivação

**Problema:**
🟡 Num carro real, um avanço exagerado ou um lambda pobre em alta carga quebra pistões, bielas e turbinas em segundos, e o aluno perde o motor sem entender a causa. Os editores de ECU atuais não simulam knock, EGT nem dano. Os jogos punem erros de forma arbitrária, sem explicar a termodinâmica da quebra. O simulador precisa de um modelo de dano que puna o erro certo, na hora certa, pela razão física certa, e que explique a causa num laudo.

**Evidências:**
- 🟡 PRD seção 4 ("Falhas mecânicas e diagnóstico"): modos de falha detonação/knock, pré-ignição, excesso de EGT, quebra de biela, furo de pistão e derretimento da turbina; laudo forense com a causa termodinâmica; restauração do motor após a quebra.
- 🟡 PRD seção 4 ("Motor físico"): limiar de detonação em função de octanagem, IAT e pressão no cilindro; pré-ignição.
- 🟡 PRD seção 7: o `hatch-20t-gdi` tem limite da biela de série de aproximadamente 420 N·m e limite de EGT de 950 °C.
- 🟡 PRD seção 8 (risco "o modelo pune erros de forma incoerente"): a mitigação exige testes de cenário determinísticos por modo de falha e um laudo ligado às variáveis que provocaram o dano.
- 🟡 PRD seção 9 (critério de aceite do Lucas): boost e avanço exagerados no hatch geram knock severo, uma falha mecânica e um laudo com a causa; o acerto corrigido gera ganho sem knock e com EGT dentro do limite.
- 🟡 Critério de aprovação do Prof. Marcos: integridade de 100 % dos componentes internos e margem de segurança de knock.

**Por que agora:**
🟡 O Sprint 1 entregou `engine-physics-core`, que expõe os ganchos `CombustionEvent` (p(θ), T_u(θ), x_b(θ), força de pico na biela) e o método `lock(reason)`. O `dyno-bench` (Sprint 2) exige `damage.step` para arrancar o laço (sem ele devolve 503 `DAMAGE_MODEL_UNAVAILABLE`). A fatia mínima do PRD ("1 carro + perfil OEM + dyno + falhas de knock/EGT") depende deste componente.

---

## 3. Goals (Objetivos)

- [ ] 🟡 G-01: Na jornada do Lucas (`hatch-20t-gdi`, `oem-stage`, E27, `seed` 42, boost alvo 280 kPa abs e avanço base +8° em toda a tabela), 100 % das 20 execuções determinísticas registram knock da classe `severe` e terminam com 1 `FailureEvent` catastrófico antes do fim da varredura.
- [ ] 🟡 G-02: Com o acerto corrigido do Apêndice D (λ 0,80 em alta carga, −3° nos cilindros com knock, boost 230 kPa abs), 100 % das 20 execuções terminam sem knock acima da classe `light`, sem falha e com todos os componentes com saúde ≥ 0,999 (integridade 100 %).
- [ ] 🟡 G-03: `damage.step` custa em média ≤ 0,05 ms e P99 ≤ 0,3 ms por tick a 1000 Hz no hardware de referência (4 núcleos, 8 GB, sem GPU dedicada).
- [ ] 🟡 G-04: O laudo forense fica disponível em ≤ 500 ms (P95) após o tick da falha, com cadeia causal de 3 a 12 elos e ≥ 1 sinal de aviso antecipado com antecedência ≥ 1,0 s na jornada do Lucas.
- [ ] 🟡 G-05: A mesma `seed`, o mesmo `sim_hz`, a mesma calibração e a mesma sequência de comandos produzem o mesmo `damage_digest` SHA-256 e o mesmo `report_sha256` em 100 % das execuções.

**Métricas de sucesso:**
| Métrica | Baseline atual | Target | Prazo |
|---------|---------------|--------|-------|
| 🟡 Execuções da jornada do Lucas que terminam em falha catastrófica com laudo | 0 % (sem modelo) | 100 % | 2026-11-01 (fim do Sprint 2) |
| 🟡 Execuções do acerto corrigido com integridade 100 % | 0 % | 100 % | 2026-11-01 |
| 🟡 Custo médio de `damage.step` por tick a 1000 Hz | não medido | ≤ 0,05 ms | 2026-11-01 |
| 🟡 Tempo até o laudo disponível (P95) | não existe | ≤ 500 ms | 2026-11-01 |
| 🟡 Testes de cenário determinísticos por modo de falha (6 modos) | 0 | 6 de 6 a verde no CI | 2026-11-01 |

---

## 4. Non-Goals (Fora do Escopo)

- 🟡 NG-01: O sistema não recalcula a combustão nem a pressão no cilindro; consome os vetores do `CombustionEvent` da física. O efeito de uma pré-ignição sobre a pressão é estimado pelo dano (Apêndice B.4), sem realimentar o solver de ciclo nesta versão.
- 🟡 NG-02: O sistema não implementa química cinética detalhada (mecanismos de reação, cool flame em dois estágios); usa só a correlação de Douaud-Eyzat de um estágio.
- 🟡 NG-03: O sistema não simula acústica 3D da câmara nem o sinal bruto do acelerómetro em kHz amostrado a 40 kHz; o sinal de knock é um valor integrado por ciclo e o espectro é sintético (Apêndice B.6).
- 🟡 NG-04: O sistema não modela desgaste de longo prazo (milhares de horas), corrosão, consumo de óleo nem fadiga de alto ciclo de componentes externos (embreagem, câmbio, semieixos).
- 🟡 NG-05: O sistema não decide a aprovação de tentativas; o `training-scenarios` lê `EngineHealth` e `FailureEvent` e aplica os seus critérios.
- 🟡 NG-06: O sistema não desenha a autópsia nem o espectrograma; o `dyno-cockpit-ui` consome `ForensicReport` e o canal `knock_spectrum`.
- 🟡 NG-07: O sistema não gera texto por modelo de linguagem; os textos do laudo vêm de modelos parametrizados versionados, para manter o determinismo e funcionar offline.
- 🟡 NG-08: O sistema não oferece restauração parcial por componente nem "peças de reposição" com especificação diferente; a restauração devolve o motor de série inteiro.

---

## 5. Usuários e Personas

**Usuário primário:** 🟡 Lucas (aluno de remap OEM, iniciante). Exagera boost e avanço no `hatch-20t-gdi`, vê o motor quebrar e precisa de um laudo em linguagem simples que diga o que corrigir (lambda mais rico, menos avanço nos cilindros com knock).

**Usuário secundário:** 🟡 Rodrigo (preparador intermediário) mapeia a ignição até o MBT monitorando o espectrograma e a margem de knock; precisa de números (graus, kPa, λ, N·m) e das tabelas afetadas. 🟡 Prof. Marcos (instrutor) provoca falhas de propósito (pré-ignição por IAT alta e avanço excessivo), mostra os sinais anteriores à quebra e usa o modo "dano desligado" para demonstrar knock ao vivo sem destruir o motor. 🟡 Consumidores técnicos: `dyno-bench` (laço e abortos), `ecu-core` (via `SensorReadings.knock_sensor_v`), `telemetry-datalogger` (eventos e canais), `dyno-cockpit-ui` (autópsia), `training-scenarios` (integridade).

**Jornada atual (sem a feature):**
1. 🟡 O aluno altera o mapa num editor offline e não recebe nenhuma resposta de knock ou de dano.
2. 🟡 O erro só aparece no carro real, com prejuízo alto e sem diagnóstico da causa.
3. 🟡 O instrutor não consegue mostrar a cadeia de eventos que antecede a quebra.

**Jornada futura (com a feature):**
1. 🟡 O aluno executa a puxada; o sistema detecta knock por cilindro a cada ciclo e a ECU retarda o avanço.
2. 🟡 Com o erro mantido, o dano acumula, o sistema emite avisos e, ao atingir o limite, quebra o componente e bloqueia o motor.
3. 🟡 O aluno abre o laudo, vê a cadeia causal, os sinais 3 s antes e a recomendação; restaura o motor e corrige o mapa.
4. 🟡 O instrutor demonstra o mesmo fenómeno com dano desligado e compara laudos de quase-falha.

---

## 6. Requisitos Funcionais

### 6.1 Requisitos Principais

| ID | Requisito | Prioridade | Critério de Aceite |
|----|-----------|-----------|-------------------|
| RF-01 | 🟡 O sistema deve calcular, para cada `CombustionEvent` sem misfire, o atraso de autoignição da zona não queimada por Douaud-Eyzat `τ(θ) = 17,68 · (ON/100)^3,402 · p_atm(θ)^(−1,7) · exp(3800 / T_u(θ))` (ms), com `p_atm = pressure_kpa / 101,325` e `ON = (RON + MON)/2` do combustível do evento. | Must | Para p = 6079,5 kPa (60 atm), T_u = 900 K e ON 88, o teste obtém τ = 0,740 ms ± 0,5 %; evento com `misfire = True` não gera cálculo e devolve intensidade 0. |
| RF-02 | 🟡 O sistema deve integrar Livengood-Wu `I_LW(θ) = Σ Δt_deg / τ(θ)`, com `Δt_deg = 1000 / (6 · rpm)` ms por grau, desde o primeiro ponto do evento (faísca) e declarar knock quando `I_LW ≥ 1` num ângulo `θ_k` com `x_b(θ_k) < x_b,end = 0,98`. | Must | Vetores sintéticos com τ constante de 0,4 ms a 3000 rpm (Δt_deg 0,0556 ms) atingem `I_LW ≥ 1` no 8.º ponto (I_LW 1,111); se esse ponto tiver `x_b ≥ 0,98`, o resultado é "sem knock"; a integral do teste bate com a de referência com erro < 0,5 %. |
| RF-03 | 🟡 O sistema deve calcular a intensidade de knock do ciclo como amplitude máxima de oscilação de pressão `MAPO_kpa = c_mapo · (1 − x_b(θ_k)) · p(θ_k)`, `c_mapo = 0,5`, a intensidade adimensional `I = MAPO_kpa / 100` (bar), a fração auto-ignitada `f_ai = 1 − x_b(θ_k)` e a energia `E_k = f_ai · Q_disp` (J). | Must | Com x_b(θ_k) 0,80 e p(θ_k) 8000 kPa, o teste obtém MAPO 800 kPa, I 8,0 e f_ai 0,20; sem knock, I = 0 e E_k = 0. |
| RF-04 | 🟡 O sistema deve classificar cada ciclo em `none` (I < 0,3), `light` (0,3 ≤ I < 1,0), `moderate` (1,0 ≤ I < 3,0) e `severe` (I ≥ 3,0) e expor a classe em `KnockObservation`. | Must | Teste de fronteira: I = 0,29 → `none`; 0,30 → `light`; 1,00 → `moderate`; 3,00 → `severe`. |
| RF-05 | 🟡 O sistema deve gerar por cilindro o sinal de knock sintético para a ECU `KnockSignal.intensity_i = g_i · I_w,i + b(rpm) · ε_i`, onde `I_w,i` é a intensidade só se `θ_k` cair na janela entre `knock_window_start_deg_atdc` e `knock_window_end_deg_atdc` (padrão −5° a 60° ATDC), `g_i` é o ganho do cilindro, `b(rpm) = 0,05 + 0,10 · (rpm/7000)²` e `ε_i` é lognormal semeado (μ 0, σ 0,25), retido até o próximo evento do cilindro. | Must | Com ruído desligado, I 4,0, `g_3` 1,0 e θ_k 20° ATDC, o cilindro 3 recebe 4,0 + b(rpm); com θ_k 70° ATDC recebe só b(rpm); com a mesma `seed`, 10 000 eventos geram a mesma sequência de valores em 2 execuções. |
| RF-06 | 🟡 O sistema deve produzir, a cada frame de telemetria (padrão 50 Hz), o espectro sintético `knock_spectrum` com 256 bins de 0 a 20 kHz por cilindro agregado (máximo), com picos nas frequências de ressonância de Draper `f_mn = α_mn · c / (π · B)` (modos 1,0 / 2,0 / 0,1) e piso de ruído dependente de RPM (Apêndice B.6). | Must | Para B 82,5 mm, γ_b 1,28 e T_b 2500 K o modo 1,0 fica em 6,80 kHz ± 0,05 kHz; um ciclo `severe` gera o bin de maior potência a ± 1 bin (78,125 Hz) de f_10; sem knock, nenhum bin excede o piso em mais de 6 dB. |
| RF-07 | 🟡 O sistema deve avaliar a pré-ignição por ponto quente em cada ciclo com probabilidade `p_pi = min(0,3; p0 · exp((T_hs − T_thr,fuel)/ΔT_s) · f_iat · f_load)` só quando `T_hs ≥ T_thr,fuel − 60 °C`, com sorteio do gerador semeado do dano (Apêndice B.4). | Must | Com T_hs = T_thr − 61 °C, 10 000 ciclos geram 0 pré-ignições; com T_hs = T_thr + 30 °C, IAT 40 °C e MAP 200 kPa, a taxa observada em 100 000 ciclos fica a ± 10 % de `p0 · e²`; a mesma `seed` gera os mesmos ciclos de pré-ignição. |
| RF-08 | 🟡 O sistema deve avaliar a pré-ignição de baixa rotação (LSPI) só em motores GDI, com 1200 ≤ rpm ≤ 3000 e `imep_gross_kpa ≥ 1500`, com probabilidade por ciclo `p_lspi = min(2·10⁻³; 1·10⁻⁴ · (1 + (IMEP − 1500)/300)² · f_iat)`. | Must | Em PFI a taxa é 0 em qualquer ponto; no `hatch-20t-gdi` a 2500 rpm e IMEP 2100 kPa com IAT 40 °C a taxa em 200 000 ciclos fica a ± 10 % de 9·10⁻⁴; a 3100 rpm a taxa é 0. |
| RF-09 | 🟡 O sistema deve tratar cada pré-ignição (por ponto quente ou LSPI) como ciclo de "mega-knock" com pressão estimada `p_pi = p_max · (1 + 0,035 · (θ_pi − advance))`, `θ_pi` 35° BTDC (ponto quente) ou 40° BTDC (LSPI), `I = 0,25 · p_pi / 100`, força na biela escalada por `p_pi / p_max`, e multiplicar por 3 a probabilidade de pré-ignição desse cilindro nos 10 ciclos seguintes (runaway). | Must | Com p_max 9000 kPa e avanço 15°, o teste obtém p_pi 15 300 kPa e I 38,25; os 10 ciclos seguintes usam 3 × a probabilidade base do cilindro e o 11.º volta ao valor base. |
| RF-10 | 🟡 O sistema deve manter um `ComponentHealth` por componente com `health` ∈ [0, 1] (1 = intacto) para `piston:i`, `rod:i` e `valves:i` por cilindro, `head_gasket`, `bearings` e `turbo:turbine` (só em veículos com turbo), inicializados em 1,0 e nunca crescentes fora da restauração. | Must | O `hatch-20t-gdi` gera 15 componentes (4 × 3 + 3); o `muscle-v8-sc` gera 26 (8 × 3 + 2) sem `turbo:turbine`; nenhum teste de propriedade encontra `health` a subir entre ticks sem restauração. |
| RF-11 | 🟡 O sistema deve aplicar dano por knock por ciclo `ΔD = c_k · max(0, I − I_safe) · (E_k / 100 J)` ao `piston:i`, com `c_k = 1,5·10⁻⁴`, `I_safe = 1,0`, e 30 % desse valor ao `head_gasket`, e somar à temperatura efetiva do pistão `ΔT_knock` de 1ª ordem com alvo 25 °C · I (I > 1) e τ 1,5 s. | Must | Ciclo com I 0,9 gera ΔD = 0; ciclo com I 8,0 e E_k 387 J gera ΔD 4,06·10⁻³ ± 1 % no pistão e 1,22·10⁻³ na junta; knock `severe` contínuo de I 8 e E_k 387 J a 6000 rpm num cilindro leva o pistão de 1,0 a 0 em 4,9 s ± 10 %. |
| RF-12 | 🟡 O sistema deve aplicar dano térmico por Larson-Miller simplificado com regra de Robinson `dD/dt = 1 / t_r(T)`, `t_r(T) = 10^(LMP_ref / T_K − C)` h, `C = 20`, `LMP_ref = T_lim,K · (C + log10(t_ref_h))`, só quando a temperatura excede o limite: pistão (T efetiva vs. `max_piston_temp_c`, t_ref 300 s), válvulas (EGT do cilindro vs. `egt_limit_c + 50 °C`, t_ref 180 s) e turbina (EGT pré-turbina vs. `egt_limit_c`, t_ref 120 s). | Must | No `hatch-20t-gdi` (limite 950 °C), EGT pré-turbina constante de 1000 °C leva `turbo:turbine` a 0 em 22,5 s ± 10 %; EGT de 950 °C ou menos durante 600 s mantém `health` = 1,0 exatamente; 951 °C produz dano > 0. |
| RF-13 | 🟡 O sistema deve somar à temperatura efetiva do pistão o aumento térmico por lambda pobre em alta carga `ΔT_lean = k_lean · max(0, λ − 0,88)` com `k_lean = 600 °C`, só quando `map_kpa ≥ 150` e λ do cilindro não é `None`. | Must | Com MAP 220 kPa e λ 0,95 o teste obtém ΔT_lean 42 °C; com MAP 140 kPa ou λ 0,85 obtém 0. |
| RF-14 | 🟡 O sistema deve aplicar sobrecarga de biela por ciclo com razão `r_i = max(torque_nm / rod_torque_limit_nm, rod_force_peak_n,i / F_lim_n)`, com `F_lim_n = 1000 · max_rod_load_kn`,: para r_i < 1 sem dano; para 1 ≤ r_i < 1,30, `ΔD = 0,002 · (1 + 20 · (r_i − 1)) · w_i`; para r_i ≥ 1,30 falha imediata; `w_i` ∈ [0,9; 1,1] é sorteado uma vez por sessão do gerador semeado. | Must | No `hatch-20t-gdi` (limite 420 N·m), 410 N·m durante 60 s mantêm todas as bielas em 1,0; 430 N·m a 5000 rpm (força abaixo do limite) quebram a biela de maior `w_i` em (8,13 / w_max) s ± 2 %, sempre o mesmo cilindro para a mesma `seed`; 550 N·m quebram no 1.º ciclo. |
| RF-15 | 🟡 O sistema deve aplicar o dano por sobre-rotação: acima de `valve_float_rpm`, `ΔD = 0,004 · (rpm − valve_float_rpm)/100` por ciclo em `valves:i`; com `rpm ≥ 1,08 · valve_float_rpm`, contato válvula-pistão imediato; acima de `max_rpm`, `dD/dt = 0,4 · (rpm/max_rpm − 1)` por segundo em `bearings`. | Must | A `valve_float_rpm` + 200 rpm o teste obtém ΔD 0,008 por ciclo; a 1,08 · `valve_float_rpm` gera `piston_failure` com mecanismo `valve_piston_contact` no ciclo; abaixo de `valve_float_rpm` e de `max_rpm` não há dano. |
| RF-16 | 🟡 O sistema deve aplicar o dano por sobre-rotação da turbina `dD/dt = 1,0 · (N_t / turbo_max_rpm − 1)` por segundo quando `turbo_rpm > turbo_max_rpm` e falha imediata (`turbo_meltdown`, mecanismo `turbo_overspeed_burst`) com `N_t ≥ 1,12 · turbo_max_rpm`. | Must | A 1,05 · `turbo_max_rpm` durante 10 s a saúde da turbina cai 0,50 ± 1 %; a 1,12 · `turbo_max_rpm` a falha ocorre no tick. |
| RF-17 | 🟡 O sistema deve aplicar à junta/cabeçote o dano por pressão de pico `ΔD = 0,01 · (p_max / p_lim_kpa − 1)` por ciclo, com `p_lim_kpa = 100 · max_cylinder_pressure_bar`, quando `p_max` excede o limite, somado ao dano por knock do RF-11. | Should | Com limite 12 000 kPa e p_max 13 200 kPa o teste obtém ΔD 0,001 por ciclo; com 11 900 kPa obtém 0. |
| RF-18 | 🟡 O sistema deve converter a saúde em falha com o mapeamento canónico do Apêndice B.8 e emitir `FailureEvent` com `tick`, `t_sim_s`, `cylinder`, `mode` (um dos 6 `FailureMode`), `mechanism`, `component_id`, `catastrophic` e as variáveis causais do instante. | Must | Cada um dos 6 modos tem 1 teste de cenário determinístico que gera exatamente 1 `FailureEvent` catastrófico com o `mode` esperado; `health` ≤ 0,50 gera 1 `FailureEvent` não catastrófico de aviso por componente (sem repetição). |
| RF-19 | 🟡 O sistema deve, após um `FailureEvent` catastrófico, marcar `DamageState.engine_locked = True`, chamar `PhysicsEngine.lock(mode)` no mesmo tick e congelar a saúde até a restauração. | Must | Após a falha no tick k, `engine_locked` é `True` no `DamageState` do tick k, a física não produz combustão no tick k + 1 e `GET .../engine/health` devolve `engine_locked = true`. |
| RF-20 | 🟡 O usuário deve poder consultar a saúde do motor com `GET /api/v1/sessions/{session_id}/engine/health`, recebendo `EngineHealth` com os componentes, `min_health`, `integrity_pct`, `intact`, `engine_locked`, falhas da sessão e `restore_count`. | Must | Sessão nova devolve 200 com 15 componentes em 1,0, `integrity_pct` 100,0 e `intact = true` no hatch; sessão inexistente devolve 404 `SESSION_NOT_FOUND`. |
| RF-21 | 🟡 O usuário deve poder restaurar o motor com `POST /api/v1/sessions/{session_id}/engine/restore`, que repõe todas as saúdes em 1,0, limpa `engine_locked`, zera os estados de knock e de runaway, incrementa `restore_count` e chama `PhysicsEngine.reset_mechanical()`. | Must | Após a restauração a resposta é 200 com `intact = true` e `restore_count` + 1; `POST .../runs` volta a devolver 202; restaurar com puxada ativa devolve 409 `RUN_IN_PROGRESS`. |
| RF-22 | 🟡 O sistema deve construir o `ForensicReport` a partir de um buffer circular de 30 s simulados (`DamageTraceRecord` por ciclo e por tick decimado a 100 Hz), fora do tick do laço, e persisti-lo com `report_sha256`. | Must | O laudo existe em ≤ 500 ms (P95) após a falha; o JSON canónico do laudo tem ≤ 64 KB; duas execuções iguais geram o mesmo `report_sha256`. |
| RF-23 | 🟡 O sistema deve montar a cadeia causal ordenada por `t_sim_s` crescente a partir do modelo de cadeia do mecanismo (Apêndice C.1), incluindo só os elos com evidência no buffer (variável acima do limiar), com 3 a 12 elos e o último elo igual à falha. | Must | No laudo da jornada do Lucas a cadeia contém, em ordem, boost acima da base, knock `moderate`, retardo de knock saturado, knock `severe` e a falha do componente; nenhum elo tem `t_sim_s` maior que o da falha. |
| RF-24 | 🟡 O sistema deve detetar sinais de aviso antecipados pelas regras do Apêndice C.2 (retardo de knock crescente, primeiro knock `moderate`, retardo saturado, EGT próxima do limite, lambda pobre em carga, torque perto do limite da biela, saúde < 0,75, turbina perto da rotação máxima, IAT alta) e calcular `lead_time_s = t_falha − t_sinal`. | Must | Num cenário com retardo de knock a subir ≥ 2° em 1 s, 3,0 s antes da falha, o laudo contém o aviso `knock_retard_rising` com `lead_time_s` 3,0 ± 0,02. |
| RF-25 | 🟡 O sistema deve gerar recomendações didáticas pelas regras do Apêndice C.3, com ação, tabela da ECU afetada (`lambda_target`, `ignition_trim_cyl`, `ignition_base`, `boost_target`, `torque_request`), cilindros, faixa numérica e justificativa. | Must | O laudo da jornada do Lucas contém as recomendações `R-KNOCK-01` (retirar 2–4° em `ignition_trim_cyl` nos cilindros com knock) e `R-LAMBDA-01` (λ 0,78–0,82 em `lambda_target` com MAP ≥ 150 kPa). |
| RF-26 | 🟡 O sistema deve gerar o texto do laudo para as 3 audiências `beginner` (Lucas), `intermediate` (Rodrigo) e `instructor` (Prof. Marcos) a partir de modelos versionados em pt-BR (Apêndice C.4), e o usuário deve poder filtrar com `?audience=`. | Must | `audience=beginner` devolve só o texto `beginner`, sem fórmulas; `audience=instructor` inclui os valores de `I_LW`, `θ_k` e MAPO e ≥ 2 perguntas didáticas; valor inválido devolve 422 `VALIDATION_FAILED`. |
| RF-27 | 🟡 O usuário deve poder obter o laudo com `GET /api/v1/runs/{run_id}/forensic-report`, com 200 quando pronto, 409 `FORENSIC_REPORT_PENDING` e cabeçalho `Retry-After: 1` durante a geração, e 404 `FORENSIC_REPORT_NOT_FOUND` para puxadas sem falha nem quase-falha. | Must | Após `engine_failed`, a primeira consulta em ≤ 500 ms devolve 200; uma puxada `completed` sem eventos devolve 404 `FORENSIC_REPORT_NOT_FOUND`; `run_id` inexistente devolve 404 `RUN_NOT_FOUND`. |
| RF-28 | 🟡 O sistema deve publicar `event.knock` (classe ≥ `light`, no máximo 10 por segundo por cilindro) e `event.failure` (cada `FailureEvent`) no barramento do `telemetry-datalogger` com o `t_sim_s` do ciclo. | Must | Knock `severe` em todos os ciclos de um cilindro a 6000 rpm gera 10 `event.knock` por segundo e não 50; cada `FailureEvent` gera exatamente 1 `event.failure`. |
| RF-29 | 🟡 O sistema deve suportar o modo "dano desligado" (`SimulationSession.damage_enabled = false`): o knock, o sinal e o espectro são calculados, o dano acumula só em `virtual_health`, os eventos levam `simulated_only = true`, o motor nunca bloqueia e uma falha virtual gera laudo do tipo `near_miss`. | Could | Com `damage_enabled = false` e a calibração do Lucas, `health` fica em 1,0, `virtual_health` do componente chega a 0, a puxada termina `completed` e o laudo `near_miss` existe com `simulated_only = true`. |
| RF-30 | 🟡 O sistema deve gerar laudo `near_miss` quando o `dyno-bench` aborta a puxada por `severe_knock_protection` (modo instrutor), com a mesma estrutura da cadeia causal e sem `FailureEvent` catastrófico. | Should | Puxada abortada por `severe_knock_protection` devolve 200 no `forensic-report` com `report_kind = near_miss` e `failure_event = null`. |
| RF-31 | 🟡 O sistema deve comparar no laudo a calibração da puxada com falha e a da puxada base da sessão (`baseline_run_id`) nas tabelas `boost_target`, `ignition_base`, `lambda_target` e `ignition_trim_cyl`, reportando o maior delta por tabela na região visitada (rpm × carga). | Should | Na jornada do Lucas o laudo reporta `boost_target` +100 kPa ± 1 kPa e `ignition_base` +8,0° ± 0,1°; sessão sem puxada base devolve `calibration_diff = null`. |
| RF-32 | 🟡 O sistema deve ser determinístico: todos os sorteios usam `numpy.random.Generator(PCG64)` de substreams `SeedSequence(seed).spawn` próprios do dano (pré-ignição, LSPI, ruído de knock, pesos de biela, espectro), em ordem fixa por evento, e expor `damage_digest()` SHA-256. | Must | 20 execuções de 30 s a 1000 Hz da jornada do Lucas geram 20 `damage_digest` iguais; alterar a taxa de frames da UI não altera o digest; o código do pacote não chama `random` nem `time.time()` (regra `ruff` banida). |

### 6.2 Fluxo Principal (Happy Path)

1. 🟡 O `dyno-bench` cria a sessão e constrói `DamageModel(config, vehicle, fuel, seed, damage_enabled)`; o sistema cria os 15 `ComponentHealth` do `hatch-20t-gdi` em 1,0, sorteia os pesos de biela `w_i` e regista a sessão em `engine_health`.
2. 🟡 A cada tick o worker chama `engine.read_sensors(damage.knock_signal())`; a física converte o sinal em `knock_sensor_v` (0,0–5,0 V) e no índice normalizado `knock_intensity` (0,0–1,0); a ECU lê `knock_intensity` e calcula o retardo de knock.
3. 🟡 Após `physics.step`, o worker chama `damage.step(engine_state, dt, ecu_status)`; o sistema processa cada `CombustionEvent` do tick (Livengood-Wu, classe, sinal, pré-ignição, LSPI, biela, válvulas, junta) e as grandezas contínuas (Larson-Miller do pistão, válvulas e turbina; sobre-rotação; turbina).
4. 🟡 O sistema devolve `DamageState` com saúdes, observações de knock e `new_failures`; o worker publica `event.knock` e `event.failure` pelo `telemetry-datalogger`.
5. 🟡 Na jornada do Lucas, o knock passa de `moderate` a `severe`, o retardo da ECU satura, o pistão do cilindro mais crítico chega a 0 e o sistema emite `FailureEvent` catastrófico `piston_failure` (ou `rod_failure`, se a sobrecarga vencer antes), chama `engine.lock()` e marca `engine_locked`.
6. 🟡 O `dyno-bench` passa a puxada para `engine_failed` no tick seguinte e grava `forensic_report_url`; o sistema congela o buffer de 30 s e gera o `ForensicReport` fora do laço, em ≤ 500 ms.
7. 🟡 O usuário abre `GET /api/v1/runs/{run_id}/forensic-report?audience=beginner` e lê a causa, os avisos e as recomendações.
8. 🟡 O usuário chama `POST /api/v1/sessions/{session_id}/engine/restore`, corrige o mapa e repete a puxada; o resultado final é uma puxada sem knock acima de `light`, sem falha e com `intact = true`.

### 6.3 Fluxos Alternativos

**Fluxo Alternativo A — Pré-ignição provocada pelo instrutor:**
1. 🟡 O Prof. Marcos eleva a IAT (intercooler com ε baixo na física) e o avanço; o ponto quente passa de `T_thr,fuel`.
2. 🟡 O sistema sorteia uma pré-ignição, entra em runaway nos 10 ciclos seguintes e, se `p_pi ≥ 1,3 · p_lim_kpa`, emite `FailureEvent` catastrófico `pre_ignition` no cilindro.
3. 🟡 O laudo mostra os avisos `iat_high` e `hot_spot_near_threshold` com antecedência e a recomendação `R-PI-01`.

**Fluxo Alternativo B — Dano desligado (demonstração):**
1. 🟡 A sessão tem `damage_enabled = false`; o sistema calcula tudo e acumula só `virtual_health`.
2. 🟡 Uma falha virtual gera `FailureEvent` com `simulated_only = true` e `catastrophic = false`; o motor não bloqueia.
3. 🟡 No fim da puxada, o laudo `near_miss` fica disponível para a turma.

**Fluxo Alternativo C — Aborto por proteção do operador:**
1. 🟡 Com `operator_protection = true`, o `dyno-bench` aborta após 3 ciclos `severe` consecutivos; o sistema gera laudo `near_miss` com a saúde real da sessão.

**Fluxo Alternativo D — LSPI no GDI:**
1. 🟡 Em `steady_state_hold` a 2000 rpm e MAP 230 kPa no `hatch-20t-gdi`, o sistema sorteia um evento LSPI; o laudo indica mecanismo `lspi` e a recomendação `R-LSPI-01` (limitar a carga abaixo de 3000 rpm).

**Fluxo Alternativo E — Falha antes do fim do arming:**
1. 🟡 Uma falha durante `arming` ou `coastdown` segue o mesmo bloqueio; o laudo usa as janelas disponíveis (mínimo 0,5 s) e marca `buffer_truncated = true`.

---

## 7. Requisitos Não-Funcionais

| ID | Requisito | Valor alvo | Observação |
|----|-----------|-----------|------------|
| RNF-01 | 🟡 Performance do laço | `damage.step` média ≤ 0,05 ms e P99 ≤ 0,3 ms por tick a 1000 Hz (V8 a 7500 rpm, 8 cilindros) | Vetorização NumPy de τ e da integral por evento; `pytest-benchmark` no CI. |
| RNF-02 | 🟡 Latência do laudo | Geração P95 ≤ 500 ms; `GET .../forensic-report` P95 ≤ 100 ms com laudo persistido | Construção numa thread do pool do API, nunca no tick. |
| RNF-03 | 🟡 Determinismo | 100 % de digests idênticos em 20 execuções; independente de `fps` da UI | Substreams próprios; o espectro tem substream separado. |
| RNF-04 | 🟡 Memória | Buffer circular ≤ 16 MB por sessão (30 s, 8 cilindros, 7500 rpm) | Arrays NumPy pré-alocados; sem alocação por tick. |
| RNF-05 | 🟡 Qualidade | Cobertura ≥ 85 % no pacote `damage`; `mypy --strict`, `ruff` e `bandit` sem erros | Convenção da plataforma. |
| RNF-06 | 🟡 Tamanho | Laudo JSON ≤ 64 KB; `EngineHealth` ≤ 8 KB | Traço de Livengood-Wu limitado a 2 s e 200 pontos. |
| RNF-07 | 🟡 Exatidão numérica | τ e `I_LW` com erro relativo ≤ 0,5 % face à implementação de referência em float64 | Testes de propriedade com `hypothesis`. |

---

## 8. Design e Interface

**Componentes afetados:**
- 🟡 `backend/src/simremap/damage/` (novo): `config.py`, `contracts.py`, `model.py` (`DamageModel`), `knock.py` (Douaud-Eyzat, Livengood-Wu, MAPO), `signal.py` (sinal e janela), `spectrum.py` (Draper), `preignition.py` (ponto quente e LSPI), `thermal.py` (Larson-Miller), `mechanical.py` (biela, válvulas, bronzinas, turbina, junta), `failure.py` (mapeamento e eventos), `trace.py` (buffer circular), `forensic/` (`chain.py`, `warnings.py`, `recommend.py`, `texts/` com modelos pt-BR), `digest.py`, `errors.py`, `service.py`.
- 🟡 `backend/src/simremap/api/routers/damage.py` (novo): os 3 endpoints, tag OpenAPI `damage`.
- 🟡 `backend/src/simremap/db/` (migração nova): tabelas `engine_health`, `failure_event`, `forensic_report`.
- 🟡 Consumidores sem alteração de contrato: `dyno-bench` (laço), `telemetry-datalogger` (eventos e canal `knock_spectrum`), `dyno-cockpit-ui` (`EngineAutopsyView`, `KnockSpectrogram`).

**API Python pública (no worker):**

```python
class DamageModel:
    def __init__(self, config: DamageConfig, vehicle: VehicleSpec, fuel: FuelSpec,
                 seed: int, damage_enabled: bool = True) -> None: ...
    def knock_signal(self) -> KnockSignal: ...          # último ciclo de cada cilindro (RF-05)
    def step(self, state: EngineState, dt: float,
             ecu_status: EcuStatus | None = None) -> DamageState: ...
    def spectrum_frame(self, t_sim_s: float) -> KnockSpectrumFrame: ...   # chamado à taxa de frames
    def freeze_trace(self) -> DamageTraceSnapshot: ...  # cópia imutável do buffer de 30 s
    def restore(self) -> None: ...                      # RF-21 (a física é reposta pelo worker)
    def set_fuel(self, fuel: FuelSpec) -> None: ...     # só com motor parado
    def snapshot(self) -> bytes: ...
    def load_snapshot(self, blob: bytes) -> None: ...
    def damage_digest(self) -> str: ...                 # SHA-256 hex do estado canónico

def build_forensic_report(trace: DamageTraceSnapshot, run: DynoRun,
                          baseline: DynoRun | None, calibration_diff: CalibrationDiff | None,
                          kind: ReportKind) -> ForensicReport: ...   # pura, sem I/O
```

**Ordem interna de `step()` (determinística):**
1. 🟡 Validar `dt == 1 / sim_hz` (tolerância 1e-12 s) e o comprimento das listas por cilindro.
2. 🟡 Se `engine_locked`, devolver o estado congelado sem sorteios.
3. 🟡 Para cada `CombustionEvent` do tick, em ordem de `t_sim_s` e de cilindro: knock (RF-01 a RF-04), sinal (RF-05), pré-ignição e LSPI (RF-07 a RF-09, com sorteios em ordem fixa: ponto quente, depois LSPI), dano por ciclo (RF-11, RF-14, RF-15, RF-17).
4. 🟡 Grandezas contínuas por `dt`: temperatura efetiva do pistão, Larson-Miller (RF-12), lean (RF-13), bronzinas (RF-15), turbina (RF-16).
5. 🟡 Clamp de `health` em [0, 1], mapeamento de falhas (RF-18), bloqueio (RF-19), escrita no buffer.

**Endpoints REST (caminhos completos sob o prefixo `/api/v1/`, erros `application/problem+json`):**

| Método e caminho | Request | Resposta | Erros |
|------------------|---------|----------|-------|
| 🟡 `GET /api/v1/sessions/{session_id}/engine/health` | query `include_failures` (bool, padrão true) | 200 `EngineHealth` | 404 `SESSION_NOT_FOUND`, 503 `SIM_WORKER_UNAVAILABLE` |
| 🟡 `POST /api/v1/sessions/{session_id}/engine/restore` | `EngineRestoreRequest` (corpo opcional) | 200 `EngineHealth` | 404 `SESSION_NOT_FOUND`, 409 `RUN_IN_PROGRESS`, 409 `SESSION_CLOSED`, 503 `SIM_WORKER_UNAVAILABLE` |
| 🟡 `GET /api/v1/runs/{run_id}/forensic-report` | query `audience` (`beginner`, `intermediate`, `instructor`, `all`; padrão `all`) | 200 `ForensicReport` | 404 `RUN_NOT_FOUND`, 404 `FORENSIC_REPORT_NOT_FOUND`, 409 `FORENSIC_REPORT_PENDING` (com `Retry-After: 1`), 422 `VALIDATION_FAILED` |

🟡 Códigos registrados por este componente em `register_error`: `FORENSIC_REPORT_NOT_FOUND` (404), `FORENSIC_REPORT_PENDING` (409), `DAMAGE_CONFIG_INVALID` (422), `DAMAGE_MODEL_UNAVAILABLE` (503), `DAMAGE_DT_MISMATCH` (500), `DAMAGE_SNAPSHOT_INVALID` (422). Os códigos `SESSION_NOT_FOUND`, `RUN_NOT_FOUND`, `RUN_IN_PROGRESS`, `SESSION_CLOSED` e `ENGINE_DESTROYED` pertencem ao `dyno-bench` e são reutilizados com o mesmo status.

**Payloads WebSocket (envelope `WsEnvelope` v1, publicados pelo `telemetry-datalogger`):**

```json
{ "v": 1, "type": "event.knock", "seq": 1842, "t_sim_s": 12.403,
  "payload": { "cylinder": 3, "knock_class": "severe", "intensity": 6.4,
               "mapo_kpa": 640.0, "theta_onset_deg_atdc": 14.0, "rpm": 5480.0,
               "retard_deg": 8.0, "simulated_only": false } }
{ "v": 1, "type": "event.failure", "seq": 1907, "t_sim_s": 13.118,
  "payload": { "failure_event_id": "01JAB...", "mode": "piston_failure",
               "mechanism": "knock_erosion", "component_id": "piston:3", "cylinder": 3,
               "catastrophic": true, "simulated_only": false,
               "causal_variables": { "knock_signal_raw": 7.9, "piston_temp_eff_c": 371.0 } } }
```

🟡 `retard_deg` vem do `EcuStatus.knock_retard_deg` do mesmo tick, juntado pelo `telemetry-datalogger`. O canal `knock_spectrum` (256 floats em dB, 0–20 kHz) e os canais `knock_sensor_v` e `knock_intensity` (listas por cilindro, publicados pela física) seguem no `telemetry.frame` só quando subscritos.

**Estados da UI (contrato para `dyno-cockpit-ui`):**
- 🟡 Estado vazio: `EngineHealth` com todos os componentes em 1,0 e `failures = []`; a autópsia mostra "motor íntegro".
- 🟡 Estado de carregamento: `FORENSIC_REPORT_PENDING` com `Retry-After: 1`; a UI mostra "gerando laudo".
- 🟡 Estado de erro: 404 `FORENSIC_REPORT_NOT_FOUND` ou falha de rede; a UI mostra o `FailureEvent` bruto recebido por `event.failure`.
- 🟡 Estado de sucesso: `ForensicReport` com `damaged_components` destacáveis por `component_id` (`piston:3`, `rod:2`, `valves:1`, `head_gasket`, `bearings`, `turbo:turbine`), o que responde à OQ-04 do `dyno-cockpit-ui`.

---

## 9. Modelo de Dados

🟡 Contratos Pydantic v2 em `damage/contracts.py` com `model_config = ConfigDict(frozen=True, extra="forbid")`. Listas por cilindro têm comprimento exato `n_cyl`, índice 0 = cilindro 1. Temperaturas na API em °C; internamente em K.

```python
from enum import StrEnum
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field

Health = Annotated[ float, Field(ge=0.0, le=1.0) ]

class FailureMode(StrEnum):
    KNOCK_DAMAGE = "knock_damage"
    PRE_IGNITION = "pre_ignition"
    EGT_OVERTEMP = "egt_overtemp"
    ROD_FAILURE = "rod_failure"
    PISTON_FAILURE = "piston_failure"
    TURBO_MELTDOWN = "turbo_meltdown"

class FailureMechanism(StrEnum):
    KNOCK_EROSION = "knock_erosion"            # furo/erosão da coroa por knock
    RING_LAND_CRACK = "ring_land_crack"        # aviso de knock_damage
    HEAD_GASKET_BREACH = "head_gasket_breach"
    PISTON_THERMAL_MELT = "piston_thermal_melt"
    VALVE_PISTON_CONTACT = "valve_piston_contact"
    EXHAUST_VALVE_BURN = "exhaust_valve_burn"
    ROD_OVERLOAD = "rod_overload"
    ROD_INSTANT_BEND = "rod_instant_bend"
    BEARING_SPIN = "bearing_spin"
    HOT_SPOT_PREIGNITION = "hot_spot_preignition"
    LSPI = "lspi"
    TURBINE_CREEP = "turbine_creep"
    TURBO_OVERSPEED_BURST = "turbo_overspeed_burst"

class KnockClass(StrEnum):
    NONE = "none"; LIGHT = "light"; MODERATE = "moderate"; SEVERE = "severe"

ComponentKind = Literal["piston", "rod", "valves", "head_gasket", "bearings", "turbine"]

class ComponentHealth(BaseModel):
    component_id: str = Field(pattern=r"^(piston|rod|valves):[1-8]$|^head_gasket$|^bearings$|^turbo:turbine$")
    kind: ComponentKind
    cylinder: int | None = Field(None, ge=1, le=8)
    health: Health = 1.0
    virtual_health: Health = 1.0          # modo dano desligado (RF-29)
    damage_by_cause: dict[ str, float ] = Field(default_factory=dict)  # "knock", "thermal", "overload", "overrev", "preignition", "pressure"
    failed: bool = False
    first_damage_t_sim_s: float | None = None

class KnockObservation(BaseModel):
    cylinder: int = Field(ge=1, le=8)
    t_sim_s: float = Field(ge=0.0)
    rpm: float = Field(ge=0.0)
    lw_integral_end: float = Field(ge=0.0)          # I_LW no fim da combustão
    theta_onset_deg_atdc: float | None              # θ_k; None sem knock
    burned_fraction_onset: float | None = Field(None, ge=0.0, le=1.0)
    autoignited_fraction: float = Field(ge=0.0, le=1.0)
    mapo_kpa: float = Field(ge=0.0)
    intensity: float = Field(ge=0.0)                # bar de MAPO
    knock_energy_j: float = Field(ge=0.0)
    knock_class: KnockClass
    in_sensor_window: bool
    preignition: Literal["none", "hot_spot", "lspi"] = "none"
    p_preignition_kpa: float | None = None

class KnockSignal(BaseModel):                       # dono do campo: engine-physics-core (entrada de read_sensors)
    intensity: list[ Annotated[ float, Field(ge=0.0) ] ]   # sinal bruto (escala de MAPO); a física deriva knock_sensor_v e knock_intensity

class FailureEvent(BaseModel):
    failure_event_id: str                            # ULID
    session_id: str
    run_id: str | None                               # None fora de puxada
    tick: int = Field(ge=0)
    t_sim_s: float = Field(ge=0.0)
    cylinder: int | None = Field(None, ge=1, le=8)
    component_id: str
    mode: FailureMode
    mechanism: FailureMechanism
    catastrophic: bool
    simulated_only: bool = False                     # dano desligado
    health_after: Health
    causal_variables: dict[ str, float ]             # ex.: knock_signal_raw, knock_intensity, piston_temp_eff_c, torque_nm, rod_load_ratio, egt_collector_c, turbo_rpm_ratio, lambda, map_kpa, iat_c, ignition_advance_deg, knock_retard_deg

class DamageState(BaseModel):
    t_sim_s: float
    tick: int
    damage_enabled: bool
    engine_locked: bool
    components: list[ ComponentHealth ]
    knock_last: list[ KnockObservation | None ]      # por cilindro, último ciclo
    knock_signal: KnockSignal
    piston_temp_eff_c: list[ float ]
    new_failures: list[ FailureEvent ]               # eventos do tick (0..n)
    damage_digest: str | None = None                 # só no fim de puxada

class EngineHealth(BaseModel):                       # resposta de /engine/health e /engine/restore
    session_id: str
    vehicle_id: str
    t_sim_s: float
    damage_enabled: bool
    engine_locked: bool
    components: list[ ComponentHealth ]
    min_health: Health
    integrity_pct: float = Field(ge=0.0, le=100.0)  # floor(1000 · min_health) / 10
    intact: bool                                     # min_health ≥ 0,999
    failures: list[ FailureEvent ] = Field(default_factory=list)
    restore_count: int = Field(0, ge=0)
    last_forensic_report_url: str | None = None

class EngineRestoreRequest(BaseModel):
    note: str | None = Field(None, max_length=120)   # texto livre técnico, sem PII

Audience = Literal["beginner", "intermediate", "instructor"]
ReportKind = Literal["failure", "near_miss"]

class CausalLink(BaseModel):
    order: int = Field(ge=1)
    t_sim_s: float
    kind: Literal["calibration", "operating_point", "combustion", "ecu_response",
                  "damage", "warning", "failure"]
    cylinder: int | None = None
    variable: str                                    # nome de canal ou de campo
    value: float
    threshold: float | None = None
    unit: str
    description: str = Field(max_length=240)

class TimeWindow(BaseModel):
    name: Literal["before", "warning", "collapse"]   # (t_f−10 a t_f−3), (t_f−3 a t_f−0,5), (t_f−0,5 a t_f)
    t_start_s: float
    t_end_s: float
    stats: dict[ str, "ChannelStats" ]

class ChannelStats(BaseModel):
    min: float; max: float; mean: float; unit: str

class EarlyWarning(BaseModel):
    signal: Literal["knock_retard_rising", "first_moderate_knock", "knock_retard_saturated",
                    "egt_near_limit", "lean_under_load", "rod_torque_near_limit",
                    "component_health_low", "turbo_speed_near_limit", "iat_high",
                    "hot_spot_near_threshold"]
    t_sim_s: float
    lead_time_s: float = Field(ge=0.0)
    cylinder: int | None = None
    value: float
    threshold: float
    unit: str

class Recommendation(BaseModel):
    rule_id: str = Field(pattern=r"^R-[A-Z]+-[0-9]{2}$")
    action: str = Field(max_length=200)
    table_id: Literal["lambda_target", "ignition_base", "ignition_trim_cyl", "boost_target",
                      "boost_target_gear", "torque_request", "rev_limiter", "none"]
    cylinders: list[ int ] = Field(default_factory=list)
    value_min: float | None = None
    value_max: float | None = None
    unit: str
    region: str | None = None                        # ex.: "rpm 3000–6500, MAP ≥ 150 kPa"
    rationale: str = Field(max_length=300)

class NarrativeText(BaseModel):
    title: str = Field(max_length=80)
    summary: str = Field(max_length=280)
    explanation: str = Field(max_length=1200)
    questions: list[ str ] = Field(default_factory=list, max_length=5)  # só instructor

class TableDelta(BaseModel):
    table_id: str; max_delta: float; unit: str; at_rpm: float; at_load: float

class CalibrationDiff(BaseModel):
    baseline_run_id: str
    baseline_calibration_hash: str
    deltas: list[ TableDelta ]

class LwTracePoint(BaseModel):
    t_sim_s: float; cylinder: int; lw_integral_end: float
    theta_onset_deg_atdc: float | None; intensity: float

class ForensicReport(BaseModel):
    report_id: str                                   # ULID
    report_kind: ReportKind
    run_id: str
    session_id: str
    vehicle_id: str
    fuel_id: str
    calibration_hash: str
    seed: int
    sim_hz: int
    failure_event: FailureEvent | None               # None em near_miss sem falha virtual
    primary_mode: FailureMode | None
    damaged_components: list[ ComponentHealth ]      # health ou virtual_health < 1
    causal_chain: list[ CausalLink ] = Field(min_length=1, max_length=12)
    time_windows: list[ TimeWindow ]
    early_warnings: list[ EarlyWarning ]
    recommendations: list[ Recommendation ] = Field(max_length=8)
    texts: dict[ str, NarrativeText ]                # chaves: valores de Audience
    calibration_diff: CalibrationDiff | None = None
    lw_trace: list[ LwTracePoint ] = Field(default_factory=list, max_length=200)
    buffer_truncated: bool = False
    simulated_only: bool = False
    generator_version: str                           # SemVer dos modelos de texto e regras
    report_sha256: str                               # do JSON canónico sem este campo
    created_at: str                                  # ISO 8601 UTC (fora do laço)

class DamageConfig(BaseModel):
    c_mapo: float = Field(0.5, gt=0.0, le=2.0)
    xb_end: float = Field(0.98, ge=0.9, le=0.999)
    knock_window_start_deg_atdc: float = Field(-5.0, ge=-30.0, le=30.0)
    knock_window_end_deg_atdc: float = Field(60.0, ge=10.0, le=90.0)
    knock_sensor_gain: list[ float ] | None = None   # None = 0,85 nos cilindros das pontas, 1,0 nos centrais
    knock_noise_sigma: float = Field(0.25, ge=0.0, le=1.0)
    i_safe: float = Field(1.0, ge=0.0)
    c_knock: float = Field(1.5e-4, ge=0.0)
    k_lean_c: float = Field(600.0, ge=0.0)
    lambda_lean_ref: float = Field(0.88, ge=0.7, le=1.0)
    lean_map_min_kpa: float = Field(150.0, ge=100.0)
    lm_constant: float = Field(20.0, gt=0.0)
    piston_t_ref_s: float = Field(300.0, gt=0.0)
    valve_t_ref_s: float = Field(180.0, gt=0.0)
    turbine_t_ref_s: float = Field(120.0, gt=0.0)
    valve_egt_margin_c: float = Field(50.0, ge=0.0)
    rod_instant_ratio: float = Field(1.30, gt=1.0)
    rod_weight_range: tuple[ float, float ] = (0.9, 1.1)
    preignition_p0: float = Field(1.0e-3, ge=0.0, le=0.1)
    preignition_dt_scale_c: float = Field(15.0, gt=0.0)
    preignition_threshold_c: dict[ str, float ] = Field(default_factory=lambda: {
        "e27": 820.0, "e0": 800.0, "podium": 860.0, "e100": 840.0})   # inferido, OQ-02
    lspi_enabled: bool = True
    burned_gas_temp_k: float = Field(2500.0, ge=1500.0, le=3200.0)
    burned_gas_gamma: float = Field(1.28, ge=1.2, le=1.35)
    trace_window_s: float = Field(30.0, ge=10.0, le=60.0)
    warning_health_threshold: float = Field(0.50, gt=0.0, lt=1.0)
```

🟡 **Contratos consumidos (donos em outras specs):** `CombustionEvent`, `EngineState`, `KnockSignal`, `PhysicsEngine.lock/reset_mechanical` (engine-physics-core); `VehicleSpec`, `EngineSpec` (`n_cyl`, `bore_mm`, `injection_type` ∈ {`gdi`, `pfi`}), `MechanicalLimits.turbo_max_rpm`, `FuelSpec` (`fuel_id`, RON, MON, PCI), `MechanicalLimits` (`max_rpm`, `rev_limit_rpm`, `egt_limit_c`, `rod_torque_limit_nm`, `max_rod_load_kn`, `max_cylinder_pressure_bar`, `max_piston_temp_c`, `valve_float_rpm`, `turbo_max_rpm`) (vehicle-catalog); internamente `F_lim_n = 1000 · max_rod_load_kn` e `p_lim_kpa = 100 · max_cylinder_pressure_bar`; `EcuStatus.knock_retard_deg`, `lambda_target`, `boost_target_kpa` (ecu-core); `SimulationSession.damage_enabled`, `operator_protection`, `baseline_run_id`, `DynoRun` (dyno-bench). Os limites estruturais estão publicados no `vehicle-catalog` (RF-28 dele, revisão R1).

**Entidades persistidas (SQLModel):**

```
engine_health {
  session_id: str PK FK -> simulation_session
  components_json: JSON          // list ComponentHealth
  engine_locked: bool
  restore_count: int
  rod_weights_json: JSON         // w_i sorteados (auditoria)
  updated_at_tick: int
  updated_at: datetime UTC
}
failure_event {
  failure_event_id: str PK       // ULID
  session_id: str FK -> simulation_session
  run_id: str FK -> dyno_run, nullable
  tick: int; t_sim_s: float
  cylinder: int | None
  component_id: str
  mode: str; mechanism: str
  catastrophic: bool; simulated_only: bool
  causal_json: JSON
  INDEX (session_id, t_sim_s)
}
forensic_report {
  report_id: str PK              // ULID
  run_id: str FK -> dyno_run, UNIQUE
  session_id: str FK -> simulation_session
  failure_event_id: str FK -> failure_event, nullable
  report_kind: str
  report_json: JSON              // ≤ 64 KB
  report_sha256: str
  generator_version: str
  created_at: datetime UTC
}
```

**Migrações necessárias:** 🟡 Sim. Uma migração Alembic do pacote `damage`, dependente das migrações do `dyno-bench`, cria as 3 tabelas. Não há dados prévios. `engine_health` é escrita no fim de cada puxada, em cada falha e em cada restauração (não por tick).

---

## 10. Integrações e Dependências

| Dependência | Tipo | Impacto se indisponível |
|-------------|------|------------------------|
| 🟡 `engine-physics-core` (`EngineState`, `CombustionEvent`, `KnockSignal`, `lock`, `reset_mechanical`) | Obrigatória | 🟡 Sem os ganchos não há knock nem dano; o `dyno-bench` devolve 503 `DAMAGE_MODEL_UNAVAILABLE`. |
| 🟡 `vehicle-catalog` (`EngineSpec`, `TurboSpec`, `FuelSpec`, `MechanicalLimits`) | Obrigatória | 🟡 Limite ausente ⇒ `DAMAGE_CONFIG_INVALID` na construção; sem valor padrão inventado para limites mecânicos. |
| 🟡 `ecu-core` (`EcuStatus`) | Opcional | 🟡 Sem `EcuStatus`, os avisos `knock_retard_*` e o `retard_deg` dos eventos ficam ausentes; o dano não muda. |
| 🟡 `dyno-bench` (laço, `SimulationSession`, `DynoRun`, estados `engine_failed` e `aborted`) | Obrigatória | 🟡 Sem orquestração, o modelo só corre em testes com `EngineState` sintético. |
| 🟡 `telemetry-datalogger` (barramento de eventos e canais) | Opcional em runtime | 🟡 Falha do barramento não altera o dano; o laudo usa o buffer próprio. |
| 🟡 `platform-foundation` (`ProblemDetail`, `register_error`, DB, worker) | Obrigatória | 🟡 Sem DB, o laudo fica em memória (máximo 20 por sessão) e o GET devolve 200 com `persisted = false` no cabeçalho `X-Simremap-Persisted`. |
| 🟡 `training-scenarios` (consumidor de `EngineHealth.intact` e `FailureEvent`) | Consumidor | 🟡 Sem impacto no dano. |
| 🟡 NumPy ≥ 2.0, `hypothesis`, `pytest-benchmark` | Obrigatória (runtime e dev) | 🟡 Sem fallback; fixadas no `uv.lock`. |
| 🟡 Literatura aberta: Livengood e Wu (1955), Douaud e Eyzat (1978), Draper (1938), Larson e Miller (1952), Heywood | Referência | 🟡 Coeficientes marcados como inferidos no Apêndice. |

---

## 11. Edge Cases e Tratamento de Erros

| Cenário | Trigger | Comportamento esperado |
|---------|---------|----------------------|
| 🟡 EC-01: Evento com misfire ou λ `None` | `misfire = True` ou corte de combustível | O sistema não calcula Livengood-Wu, regista `knock_class = none`, não aplica dano por knock nem lean e segue. |
| 🟡 EC-02: Vetores do evento incoerentes | comprimentos diferentes de `pressure_kpa`, `t_unburned_k`, `burned_fraction`, ou valor NaN/Inf | O sistema levanta `DamageError(code="DAMAGE_INPUT_INVALID")`, o worker aborta a puxada com `internal_error`; sem retry, porque a repetição determinística reproduz a falha. |
| 🟡 EC-03: `T_u` muito baixa ou pressão quase nula | T_u < 400 K ou p < 50 kPa | O sistema satura τ em 10⁶ ms (contribuição nula) para evitar overflow de `exp`; sem exceção. |
| 🟡 EC-04: Knock no último ponto do evento | `I_LW` atinge 1 com `x_b ≥ 0,98` | O sistema classifica "sem knock" (a zona não queimada já foi consumida pela chama). |
| 🟡 EC-05: Motor bloqueado recebe ticks | `step()` com `engine_locked = True` | O sistema devolve o `DamageState` congelado, não sorteia números e não emite eventos novos até a restauração. |
| 🟡 EC-06: Duas falhas no mesmo tick | dois componentes chegam a 0 no mesmo tick | O sistema emite os 2 `FailureEvent` em ordem de `component_id` canónica; o primeiro catastrófico é o `failure_event` do laudo; o motor bloqueia 1 vez. |
| 🟡 EC-07: Laudo pedido durante a geração (timeout do cliente) | `GET .../forensic-report` antes do fim | O sistema devolve 409 `FORENSIC_REPORT_PENDING` com `Retry-After: 1`; se a geração passar de 5 s, regista `forensic.timeout` e gera laudo mínimo (falha + 1 elo) como fallback. |
| 🟡 EC-08: Banco indisponível ao gravar laudo | `DATABASE_UNAVAILABLE` na escrita | O sistema faz retry 3 vezes (100, 200, 400 ms), depois mantém o laudo em memória e responde com `X-Simremap-Persisted: false`. |
| 🟡 EC-09: Restauração com puxada ativa | `POST .../engine/restore` com `active_run_id` não nulo | O sistema devolve 409 `RUN_IN_PROGRESS` e não altera nada. |
| 🟡 EC-10: Restauração com motor íntegro | restore com `intact = true` | O sistema devolve 200, repõe os estados de knock e incrementa `restore_count` (operação idempotente na saúde). |
| 🟡 EC-11: Limite mecânico ausente no catálogo | `rod_torque_limit_nm` ou `egt_limit_c` `None` | O sistema falha na construção com `DAMAGE_CONFIG_INVALID` e o `detail` indica o campo; sem fallback para valor inventado. |
| 🟡 EC-12: Veículo sem turbo | `forced_induction` ≠ turbo | O sistema não cria `turbo:turbine`, ignora RF-16 e o Larson-Miller da turbina, e nunca emite `turbo_meltdown`. |
| 🟡 EC-13: Worker indisponível | worker do laço morreu | `GET .../engine/health` devolve o último `engine_health` persistido com 200 e `t_sim_s` antigo; `POST .../engine/restore` devolve 503 `SIM_WORKER_UNAVAILABLE`. |
| 🟡 EC-14: Buffer menor que as janelas | falha com < 10 s de puxada | O sistema gera as janelas com o intervalo disponível, marca `buffer_truncated = true` e omite janelas com duração < 0,1 s. |
| 🟡 EC-15: Puxada sem `baseline_run_id` | primeira puxada da sessão falha | O sistema gera o laudo com `calibration_diff = null` e o elo `calibration` usa valores absolutos (boost alvo e avanço) face aos valores de série do catálogo. |
| 🟡 EC-16: Troca de combustível com motor em funcionamento | `set_fuel()` com rpm > 0 | O sistema levanta `DamageError(code="DAMAGE_FUEL_CHANGE_WHILE_RUNNING")` (HTTP 409 via `dyno-bench`). |
| 🟡 EC-17: Dano desligado e laudo pedido sem falha virtual | `damage_enabled = false`, sem `virtual_health` a 0 | O sistema devolve 404 `FORENSIC_REPORT_NOT_FOUND`, salvo aborto por proteção do operador (RF-30). |

---

## 12. Segurança e Privacidade

- 🟡 **Autenticação:** não se aplica; aplicação local-first num container por estação (decisão da `platform-foundation`).
- 🟡 **Autorização:** sem papéis neste componente; o `damage_enabled = false` é definido na criação da sessão pelo `dyno-bench`; o `training-scenarios` impõe `damage_enabled = true` nas tentativas avaliadas.
- 🟡 **Dados sensíveis:** zero PII; o campo `note` do restore aceita só texto técnico de até 120 caracteres e passa pelo teste de varredura de PII da fundação; nicknames não entram no laudo.
- 🟡 **Integridade:** `report_sha256` sobre o JSON canónico (chaves ordenadas, floats com 6 casas, separadores `(",", ":")`) permite ao instrutor verificar laudos exportados; `load_snapshot()` não usa `pickle` (cabeçalho JSON + float64 little-endian com SHA-256).
- 🟡 **Auditoria:** log JSON `damage.failure` com `session_id`, `run_id`, `mode`, `mechanism`, `component_id`, `tick`; log `damage.restore` com `restore_count`; sem IP.

---

## 13. Plano de Rollout

- 🟡 **Estratégia:** entrega incremental no Sprint 2 atrás da configuração `DAMAGE_FEATURES` (lista): `knock` → `signal` → `thermal` → `mechanical` → `preignition` → `forensic` → `spectrum` → `damage_off`. O gate de saída é a suíte de cenário dos 6 modos e a jornada do Lucas (G-01 e G-02) a verde no `hatch-20t-gdi`; os outros 3 veículos entram no Sprint 4 com os limites validados do catálogo.
- 🟡 **Como reverter (rollback):** os coeficientes vivem em `DamageConfig` versionado; reverter um coeficiente é reverter o arquivo de configuração. Uma falha grave volta à imagem Docker anterior; a migração tem `downgrade` que remove as 3 tabelas sem afetar `dyno_run`.
- 🟡 **Monitoramento pós-deploy:** contagem de `damage.failure` por modo por puxada nas primeiras 48 h em turma, tempo de geração do laudo (P95) e fração de puxadas com laudo `buffer_truncated`; um modo com > 50 % das falhas sem cadeia de ≥ 3 elos indica regra a rever.

---

## 14. Open Questions

| # | Pergunta | Impacto | Dono | Prazo |
|---|---------|---------|------|-------|
| OQ-01 | 🟡 Resolvida na revisão R1 (2026-10-18): o `vehicle-catalog` publica `max_rod_load_kn`, `max_cylinder_pressure_bar`, `max_piston_temp_c`, `valve_float_rpm` e `turbo_max_rpm`; esta spec converte para N e kPa internamente. | Alto | George | 2026-10-24 |
| OQ-02 | 🟡 ⚠️ ABERTO: os limiares de ponto quente por combustível (e27 820 °C, e0 800 °C, podium 860 °C, e100 840 °C) são coerentes com a escala de `hot_spot_temp_c` da física? Precisam de calibração conjunta. | Alto | George | 2026-10-25 |
| OQ-03 | 🟡 ⚠️ ABERTO: `ON = (RON + MON)/2` é a octanagem certa para Douaud-Eyzat com etanol? A alternativa é RON com correção de sensibilidade. | Médio | George | 2026-10-25 |
| OQ-04 | 🟡 ⚠️ ABERTO: a física já inclui o efeito de lambda pobre em `piston_temp_c`? Se sim, `k_lean_c` passa a 0 para não contar duas vezes (RF-13). | Médio | George | 2026-10-24 |
| OQ-05 | 🟡 ⚠️ ABERTO: "integridade de 100 %" significa `min_health ≥ 0,999` (decisão atual) ou `health = 1,0` exato? O `training-scenarios` deve adotar o mesmo critério. | Médio | George | 2026-10-28 |
| OQ-06 | 🟡 ⚠️ ABERTO: a pré-ignição deve realimentar o solver de ciclo da física (pressão real do ciclo) numa versão futura, em vez da estimativa `p_pi` do RF-09? | Baixo | George | 2026-11-08 |
| OQ-07 | 🟡 Resolvida na revisão R1 (2026-10-18): o `SensorReadings` traz `knock_sensor_v` (0,0–5,0 V) e `knock_intensity` (0,0–1,0, derivado); o `ecu-core` consome `knock_intensity` e a telemetria transmite os dois. | Médio | George | 2026-10-24 |

---

## 15. Decisões Tomadas (Decision Log)

| Decisão | Alternativas consideradas | Racional |
|---------|--------------------------|---------|
| 🟡 Integral de Livengood-Wu a partir da faísca (primeiro ponto do `CombustionEvent`) | 🟡 Integrar desde o IVC | 🟡 A física só exporta vetores da faísca ao fim da combustão; antes da faísca T_u é baixa e a contribuição medida nos testes é < 2 % da integral. |
| 🟡 Intensidade = MAPO em bar com `MAPO = c_mapo · (1 − x_b,k) · p_k` | 🟡 Intensidade pela energia pura; modelo acústico | 🟡 MAPO é a métrica usada em bancada real, cabe na escala 0–10 da tabela `knock_threshold` do `ecu-core` e é barata. |
| 🟡 Limite mecânico sem dispersão; a `seed` decide só os pesos `w_i` (qual biela quebra e quando) | 🟡 Sortear a resistência de cada biela | 🟡 Garante "410 N·m nunca quebra, 430 N·m sempre quebra" no hatch (~420 N·m do PRD) e mantém a falha determinística por `seed`. |
| 🟡 Dano térmico zero abaixo do limite; Larson-Miller só acima | 🟡 Larson-Miller contínuo | 🟡 Torna a integridade 100 % alcançável com acerto correto e coerente com o limite de EGT 950 °C do PRD. |
| 🟡 Pré-ignição estimada no dano (`p_pi`) e não na física | 🟡 Realimentar o solver de ciclo | 🟡 Mantém NG-02 da física e o orçamento de 0,5 ms; o ganho didático vem do evento e do laudo (OQ-06). |
| 🟡 Laudo por regras e modelos de texto versionados | 🟡 Texto gerado por LLM | 🟡 Determinismo por hash, funcionamento offline e custo zero (PRD). |
| 🟡 Restauração não ressemeia os geradores | 🟡 Ressemear na restauração | 🟡 A restauração é um comando da sequência; o determinismo fica garantido pela sequência de comandos. |
| 🟡 Overspeed da turbina mapeado para `turbo_meltdown` com mecanismo próprio | 🟡 Novo `FailureMode` | 🟡 A convenção fixa 6 modos canónicos; o campo `mechanism` dá a granularidade. |

---

## Apêndice

### A. Equações de knock (unidades)

- 🟡 Pressão em atm: `p_atm = p_kpa / 101,325`. Temperatura da zona não queimada `T_u` (K) do `CombustionEvent.t_unburned_k`.
- 🟡 Douaud-Eyzat: `τ = 17,68 · (ON/100)^3,402 · p_atm^(−1,7) · exp(3800 / T_u)` (ms); `ON = (RON + MON)/2` (E27 88, E0 90, Podium 95, E100 99,5 com os valores do catálogo).
- 🟡 Tempo por grau: `Δt_deg = 1000 / (6 · rpm)` ms (a 6000 rpm, 0,0278 ms).
- 🟡 Livengood-Wu: `I_LW(θ_j) = Σ_{i ≤ j} Δt_deg / τ(θ_i)`; knock se existe j com `I_LW(θ_j) ≥ 1` e `x_b(θ_j) < 0,98`; `θ_k` = primeiro j (ATDC, negativo antes do PMS).
- 🟡 MAPO: `MAPO_kpa = c_mapo · (1 − x_b(θ_k)) · p(θ_k)`; `I = MAPO_kpa / 100`.
- 🟡 Energia auto-ignitada: `E_k = (1 − x_b(θ_k)) · Q_disp`, `Q_disp = η_c · min(m_fuel, m_air/AFR_st) · PCI` (J), com massas do `EngineState` do cilindro.
- 🟡 Exemplo de verificação: p 6079,5 kPa (60 atm), T_u 900 K, ON 88 ⇒ τ ≈ 0,740 ms; a 6000 rpm a integral cresce 0,0375 por grau.

### B. Modelo de dano e falha

**B.1 Temperatura efetiva do pistão:** 🟡 `T_p,eff = piston_temp_c + ΔT_knock + ΔT_lean`; `ΔT_knock` de 1ª ordem `y_k = y_{k−1} + (1 − exp(−dt/1,5)) · (25 · max(0, I_last − 1) − y_{k−1})` (°C) com `I_last` do último ciclo do cilindro; `ΔT_lean = 600 · max(0, λ − 0,88)` com MAP ≥ 150 kPa.

**B.2 Larson-Miller (Robinson):** 🟡 `LMP_ref = T_lim,K · (20 + log10(t_ref_s / 3600))`; `t_r(T) = 3600 · 10^(LMP_ref / T_K − 20)` s; `ΔD = dt / t_r(T)` se `T > T_lim`, senão 0. Turbina do hatch: T_lim 1223,15 K, t_ref 120 s ⇒ LMP_ref 22 656; a 1000 °C, t_r ≈ 22,5 s.

**B.3 Biela:** 🟡 `r_i = max(torque_nm / rod_torque_limit_nm, F_i / F_lim_n)` com `F_i` do evento (escalada por `p_pi/p_max` em pré-ignição); `w_i ~ U(0,9; 1,1)` sorteado na construção (substream `rod_weights`). Bronzinas recebem 25 % do ΔD de biela de cada ciclo, além do termo de sobre-rotação.

**B.4 Pré-ignição:** 🟡 `p_pi_base = p0 · exp((T_hs − T_thr,fuel)/15) · f_iat · f_load`, `f_iat = clip(exp((IAT − 40)/20); 0,5; 4)`, `f_load = (map_kpa/200)²`, `p0 = 10⁻³`, ativo se `T_hs ≥ T_thr − 60`; runaway ×3 por 10 ciclos; pressão estimada `p_pi = p_max · (1 + 0,035 · (θ_pi − advance))`; dano no pistão por evento `ΔD = 0,15 · p_pi / p_lim_kpa`; falha `pre_ignition` catastrófica se `p_pi ≥ 1,3 · p_lim_kpa`.

**B.5 LSPI:** 🟡 só `injection_type = gdi`, 1200 ≤ rpm ≤ 3000, `imep_gross_kpa ≥ 1500`; `p = min(2·10⁻³; 10⁻⁴ · (1 + (IMEP − 1500)/300)² · f_iat)`; `θ_pi = 40°` BTDC; mesmas consequências de B.4 com mecanismo `lspi`.

**B.6 Sinal e espectro (Draper):** 🟡 velocidade do som `c = sqrt(γ_b · 287 · T_b)` (m/s); `f_mn = α_mn · c / (π · B)` com `α_10 = 1,841`, `α_20 = 3,054`, `α_01 = 3,832`, B em m. Espectro em dB: `S(f) = 10 · log10(N0(f) + Σ_m A_m · I_max · exp(−(f − f_m)² / (2 · 300²)))`, `A_10 = 1,0`, `A_20 = 0,4`, `A_01 = 0,25`, `N0(f) = b(rpm) · (1 + 2000/(f + 200)) · ε_f` (ε_f lognormal σ 0,2, substream `spectrum`), `I_max` = máxima intensidade dos ciclos do frame. Hatch (B 82,5 mm, T_b 2500 K): f_10 ≈ 6,80 kHz, f_20 ≈ 11,3 kHz, f_01 ≈ 14,2 kHz.

**B.7 Sobre-rotação e turbina:** 🟡 válvulas `ΔD = 0,004 · (rpm − valve_float_rpm)/100` por ciclo; contato válvula-pistão a `1,08 · valve_float_rpm`; bronzinas `dD/dt = 0,4 · (rpm/max_rpm − 1)`; turbina `dD/dt = (N_t/turbo_max_rpm − 1)` por segundo, burst a 1,12.

**B.8 Mapeamento componente → modo (health 0, salvo indicação):**

| Componente / condição | `FailureMode` | `mechanism` | Catastrófico |
|---|---|---|---|
| 🟡 `piston:i` com maior parcela `knock` | `piston_failure` | `knock_erosion` | sim |
| 🟡 `piston:i` com maior parcela `thermal` | `piston_failure` | `piston_thermal_melt` | sim |
| 🟡 contato válvula-pistão (B.7) | `piston_failure` | `valve_piston_contact` | sim |
| 🟡 `piston:i` com health ≤ 0,50 e parcela `knock` | `knock_damage` | `ring_land_crack` | não (aviso) |
| 🟡 `head_gasket` | `knock_damage` | `head_gasket_breach` | sim |
| 🟡 `valves:i` com maior parcela `thermal` | `egt_overtemp` | `exhaust_valve_burn` | sim |
| 🟡 `valves:i` com maior parcela `overrev` | `piston_failure` | `valve_piston_contact` | sim |
| 🟡 `rod:i` (B.3) ou r_i ≥ 1,30 | `rod_failure` | `rod_overload` / `rod_instant_bend` | sim |
| 🟡 `bearings` | `rod_failure` | `bearing_spin` | sim |
| 🟡 pré-ignição com `p_pi ≥ 1,3 ·` limite | `pre_ignition` | `hot_spot_preignition` / `lspi` | sim |
| 🟡 `turbo:turbine` térmico | `turbo_meltdown` | `turbine_creep` | sim |
| 🟡 turbina a 1,12 · `turbo_max_rpm` | `turbo_meltdown` | `turbo_overspeed_burst` | sim |
| 🟡 qualquer componente com health ≤ 0,50 (1.ª vez) | modo do componente | mecanismo dominante | não (aviso) |

### C. Laudo forense

**C.1 Modelos de cadeia por mecanismo (elos candidatos, ordem por tempo):** 🟡 `knock_erosion`: `calibration` (boost alvo ou avanço acima da base) → `operating_point` (MAP máximo, IAT) → `combustion` (primeiro ciclo `moderate`, θ_k, I_LW) → `ecu_response` (retardo saturado) → `combustion` (primeiro `severe`) → `damage` (pistão < 0,75, < 0,50) → `failure`. 🟡 `rod_overload`: `calibration` (`torque_request`/boost) → `operating_point` (torque > limite) → `damage` (biela < 0,50) → `failure`. 🟡 `turbine_creep`: `calibration` (avanço retardado ou lambda pobre) → `operating_point` (EGT > limite, duração) → `damage` → `failure`. 🟡 `hot_spot_preignition`/`lspi`: `operating_point` (IAT, carga, rpm) → `combustion` (ponto quente perto do limiar) → `combustion` (pré-ignição, runaway) → `failure`.

**C.2 Regras de aviso antecipado:**

| Sinal | Regra (primeira ocorrência no buffer) |
|---|---|
| 🟡 `knock_retard_rising` | `EcuStatus.knock_retard_deg` do cilindro sobe ≥ 2° numa janela de 1 s |
| 🟡 `first_moderate_knock` | primeiro ciclo com classe ≥ `moderate` |
| 🟡 `knock_retard_saturated` | retardo ≥ 8° (padrão `max_retard_deg` do `ecu-core`) durante ≥ 0,2 s |
| 🟡 `egt_near_limit` | EGT pré-turbina ≥ `egt_limit_c − 30 °C` |
| 🟡 `lean_under_load` | λ ≥ 0,90 com MAP ≥ 150 kPa durante ≥ 0,3 s |
| 🟡 `rod_torque_near_limit` | `torque_nm ≥ 0,95 · rod_torque_limit_nm` (399 N·m no hatch) |
| 🟡 `component_health_low` | qualquer health < 0,75 |
| 🟡 `turbo_speed_near_limit` | `turbo_rpm ≥ 0,95 · turbo_max_rpm` |
| 🟡 `iat_high` | IAT ≥ 60 °C com MAP ≥ 150 kPa |
| 🟡 `hot_spot_near_threshold` | `T_hs ≥ T_thr,fuel − 30 °C` |

**C.3 Regras de recomendação:**

| Regra | Condição | Ação |
|---|---|---|
| 🟡 `R-KNOCK-01` | knock ≥ `moderate` num cilindro | Retirar 2–4° em `ignition_trim_cyl` nos cilindros com knock, na região rpm × MAP dos ciclos com knock |
| 🟡 `R-KNOCK-02` | knock em ≥ 3 cilindros | Retirar 2–3° em `ignition_base` na mesma região |
| 🟡 `R-LAMBDA-01` | λ > 0,82 com MAP ≥ 150 kPa | Ajustar `lambda_target` para 0,78–0,82 com MAP ≥ 150 kPa |
| 🟡 `R-BOOST-01` | boost alvo > base + 50 kPa e knock ou EGT acima do limite | Reduzir `boost_target` em 20–40 kPa até eliminar o knock |
| 🟡 `R-ROD-01` | `rod_overload` ou aviso de torque | Limitar o torque a ≤ 0,90 · limite (378 N·m no hatch) em `torque_request` ou `boost_target` |
| 🟡 `R-EGT-01` | `turbine_creep` ou `exhaust_valve_burn` | Enriquecer λ para 0,78–0,82 e trazer o avanço para ≤ 4° do MBT |
| 🟡 `R-PI-01` | pré-ignição por ponto quente | Baixar IAT (intercooler), retirar 3–5° e reduzir a carga com IAT ≥ 60 °C |
| 🟡 `R-LSPI-01` | `lspi` | Limitar `boost_target` abaixo de 3000 rpm para IMEP < 1500 kPa |
| 🟡 `R-REV-01` | sobre-rotação | Baixar o limitador para ≤ `max_rpm − 200` |

**C.4 Texto por audiência:** 🟡 `beginner` (Lucas): frases curtas, sem fórmulas, causa em 1 frase, 2–3 ações numeradas com valores (ex.: "Ajuste o lambda para 0,78–0,82 em alta carga"). 🟡 `intermediate` (Rodrigo): valores por cilindro, tabelas da ECU, regiões rpm × MAP, avisos com antecedência. 🟡 `instructor` (Prof. Marcos): equações de Douaud-Eyzat e Livengood-Wu com os valores do ciclo crítico (`I_LW`, θ_k, MAPO, T_u máx.), traço `lw_trace` e 2–5 perguntas didáticas (ex.: "Por que o knock surgiu primeiro no cilindro 3?"). Os modelos ficam em `damage/forensic/texts/pt-BR/*.j2` com `generator_version` SemVer.

### D. Cenário de aceite (jornada do Lucas)

1. 🟡 Sessão: `hatch-20t-gdi`, `oem-stage`, combustível `e27`, `seed` 42, `sim_hz` 1000, SAE J1349, `damage_enabled = true`, `operator_protection = false`.
2. 🟡 Puxada base `baseline_pull` 4ª, 2000 → 6300 rpm: knock máximo `light`, `intact = true`.
3. 🟡 Calibração exagerada: `boost_target` = 280 kPa abs (série ≈ 180 kPa) e `ignition_base` +8° em todas as células; `sweep_pull` igual.
4. 🟡 Esperado: knock `severe` em ≥ 1 cilindro, retardo saturado, `FailureEvent` catastrófico (`piston_failure`/`knock_erosion` ou `rod_failure`/`rod_overload`), `engine_failed`, laudo com ≥ 3 elos, aviso com `lead_time_s ≥ 1,0` e as regras `R-KNOCK-01` e `R-LAMBDA-01`.
5. 🟡 Restaurar; aplicar λ 0,80 com MAP ≥ 150 kPa, −3° em `ignition_trim_cyl` nos cilindros com knock e boost 230 kPa abs; repetir: knock ≤ `light`, EGT pré-turbina ≤ 950 °C, torque ≤ 420 N·m, `intact = true`.

### E. Limites esperados do catálogo para o `hatch-20t-gdi`

| Campo | Valor | Fonte |
|---|---|---|
| 🟡 `rod_torque_limit_nm` | 420 | PRD seção 7 |
| 🟡 `egt_limit_c` | 950 | PRD seção 7 |
| 🟡 `max_rod_load_kn` | 52 (`F_lim_n` = 52 000 N) | vehicle-catalog (estimativa) |
| 🟡 `max_cylinder_pressure_bar` | 120 (`p_lim_kpa` = 12 000 kPa) | vehicle-catalog |
| 🟡 `max_piston_temp_c` | 330 | vehicle-catalog |
| 🟡 `valve_float_rpm` | 7200 | vehicle-catalog |
| 🟡 `MechanicalLimits.turbo_max_rpm` | 210 000 | vehicle-catalog |
| 🟡 `EngineSpec.bore_mm` | 82,5 | arquitetura EA888 de referência |

### Referências
- 🟡 Livengood, J. C.; Wu, P. C. (1955), correlação de autoignição; Douaud, A.; Eyzat, P. (1978), atraso de autoignição por octanagem.
- 🟡 Draper, C. S. (1938), modos acústicos da câmara; Larson, F. R.; Miller, J. (1952), parâmetro tempo-temperatura; Heywood, Internal Combustion Engine Fundamentals.
- 🟡 `_reversa_sdd/prd.md` seções 4, 7, 8 e 9; `_reversa_sdd/personas.md`; `/tmp/simremap-conventions.md` seções 4, 5, 6, 7 e 9; `engine-physics-core.md`, `dyno-bench.md`, `ecu-core.md`, `platform-foundation.md`, `dyno-cockpit-ui.md`.

### Histórico de Revisões
| Versão | Data | Autor | Mudanças |
|--------|------|-------|---------|
| 🟡 1.0 | 2026-10-18 | reversa-spec-sdd | Versão inicial |
| 🟡 1.1 | 2026-10-18 | reversa-spec-sdd | Revisão R1 de consistência entre specs (decisões do usuário: knock, nomes de campo, códigos de erro, seq, campos de integração, prefixo /api/v1/, OEM-Stage, benchmark v1) |

---

## Relatório de avaliação (reversa-spec-sdd)

- 🟡 Score final: 100,0/100 (Excelente, pronta para implementação)
- 🟡 Iterações: 2 (scores: 87,0 → 100,0)
- 🟡 Breakdown: Completude 100 %, Testabilidade 100 %, Clareza 100 %, Escopo 100 %, Edge Cases 100 %
- 🟡 Gaps críticos remanescentes: nenhum
- 🟡 Sugestões remanescentes: calibrar em conjunto com a física os limiares de ponto quente (OQ-02)
- 🟡 Revisão R1 (2026-10-18): reavaliado após a revisão de consistência entre specs, score 100,0/100.
