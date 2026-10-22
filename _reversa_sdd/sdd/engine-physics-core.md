# Spec: engine-physics-core

**Versão:** 1.1
**Status:** Rascunho
**Autor:** reversa-spec-sdd
**Data:** 2026-10-18
**Reviewers:** N/A
**Sprint:** 1 (componente 1 da ordem aprovada 9 → 1 → 3 → 4 → 2 → 5 → 6 → 7 → 11 → 10 → 8)

---

## 1. Resumo

🟡 O `engine-physics-core` é o modelo termodinâmico 0D/1D de um motor ciclo Otto (aspirado, turbo e supercharged) que corre em tempo real, com passo fixo determinístico de 100 a 1000 Hz (padrão 1000 Hz). Recebe os comandos dos atuadores emitidos pela ECU simulada (`ActuatorCommands`) e a carga do dinamômetro (`DynoLoad`), e devolve o estado físico do motor (`EngineState`) e as leituras dos sensores (`SensorReadings`). O componente é a base de todas as outras specs: o dinamômetro, o modelo de dano, a ECU e a telemetria consomem os seus contratos.

🟡 O pacote vive em `backend/src/simremap/physics/`. Não expõe endpoints REST próprios: é uma biblioteca Python pura (NumPy permitido) chamada pelo worker de simulação do `dyno-bench`.

---

## 2. Contexto e Motivação

**Problema:**
🟡 O PRD exige que a resposta do motor a cada alteração de calibração seja fisicamente coerente: o ganho de potência deve vir de mais massa de ar, de mistura correta e de avanço próximo do MBT; o dano deve vir de pressão de pico excessiva, de autoignição da zona não queimada ou de EGT alta. Um modelo de "tabelas mágicas" não permite ao aluno entender a causa do resultado. Sem um modelo físico com VE "verdadeira" independente da tabela da ECU, o acerto de VE do Rodrigo não tem significado: a tabela da ECU deve tentar adivinhar uma realidade física que existe fora dela.

**Evidências:**
- 🟡 PRD seção 3: desvio < 5 % de torque, potência, lambda e EGT face às curvas de referência; laço ≥ 100 Hz (alvo 1000 Hz) no hardware de referência (4 núcleos, 8 GB, sem GPU dedicada).
- 🟡 PRD seção 8 (riscos): o laço em Python pode não atingir 100–1000 Hz; o modelo pode punir erros de forma incoerente. A mitigação pedida é passo fixo separado do I/O, vetorização e benchmark desde o primeiro componente.
- 🟡 PRD seção 9 (critério "Física"): varredura completa com a calibração de referência ⇒ curvas com desvio < 5 %.

**Por que agora:**
🟡 Este é o componente 1 do Sprint 1. O `dyno-bench`, o `knock-and-failure-model` e o `ecu-core` (Sprint 2) dependem dos contratos `SensorReadings`, `ActuatorCommands`, `EngineState` e `PhysicsConfig` definidos aqui.

---

## 3. Goals (Objetivos)

- 🟡 G-01: O sistema deve simular o `hatch-20t-gdi` com a calibração de referência com desvio < 5 % por ponto de RPM em torque, potência, lambda e EGT face às `ReferenceCurve` do catálogo (Sprint 1); os restantes 3 veículos atingem a mesma meta até o Sprint 4.
- 🟡 G-02: O sistema deve executar o passo `step()` em tempo médio ≤ 0,5 ms e p99 ≤ 2,0 ms a 1000 Hz no hardware de referência, medido com `pytest-benchmark`.
- 🟡 G-03: O sistema deve produzir resultados bit a bit idênticos (hash SHA-256 igual) para a mesma `seed`, `sim_hz`, veículo, combustível e sequência de comandos, em 100 % das execuções na mesma plataforma.
- 🟡 G-04: O sistema deve fazer o MBT emergir do modelo: no ponto de torque máximo de uma varredura de avanço, o ângulo de pressão de pico fica entre 12° e 18° ATDC.
- 🟡 G-05: O sistema deve expor os ganchos (pressão de pico, temperatura da zona não queimada, histórico angular) que o modelo de dano precisa para aplicar Livengood-Wu, sem que o modelo de dano recalcule a combustão.

**Métricas de sucesso:**
| Métrica | Baseline atual | Target | Prazo |
|---------|---------------|--------|-------|
| 🟡 Desvio máximo de torque/potência vs referência (`hatch-20t-gdi`) | inexistente | < 5 % por ponto | 2026-10-25 (fim do Sprint 1) |
| 🟡 Desvio máximo de lambda e EGT vs referência (`hatch-20t-gdi`) | inexistente | < 5 % por ponto | 2026-10-25 |
| 🟡 Tempo médio por tick a 1000 Hz (V8, 7500 rpm, WOT) | inexistente | ≤ 0,5 ms | 2026-10-25 |
| 🟡 Reprodutibilidade por hash em 20 execuções repetidas | inexistente | 100 % | 2026-10-25 |
| 🟡 Desvio dos 4 veículos vs referência | inexistente | < 5 % por ponto | 2026-11-15 (fim do Sprint 4) |

---

## 4. Non-Goals (Fora do Escopo)

- 🟡 NG-01: O sistema não modela CFD nem escoamento 1D completo por ondas (método das características) nos coletores; o coletor é 0D (filling & emptying) e os efeitos de sintonia entram na curva de VE física.
- 🟡 NG-02: O sistema não calcula a detonação, a pré-ignição nem a acumulação de dano; isso pertence ao `knock-and-failure-model`. A física só fornece os ganchos (histórico de pressão e de temperatura).
- 🟡 NG-03: O sistema não modela motores diesel, Wankel, elétricos nem híbridos (PRD seção 5).
- 🟡 NG-04: O sistema não modela pneus, suspensão, aerodinâmica nem a condução em pista; a carga externa chega apenas pelo `DynoLoad` do dinamômetro.
- 🟡 NG-05: O sistema não implementa estratégias de ECU (malha fechada, PID de boost, limitadores, two-step, overrun); recebe só os comandos finais por cilindro já calculados pela ECU.
- 🟡 NG-06: O sistema não modela química detalhada (emissões NOx/CO/HC) além da fração de combustível não queimado necessária para o balanço de energia de escape e para os pops & bangs.
- 🟡 NG-07: O sistema não garante determinismo bit a bit entre plataformas diferentes (CPU/SO/versão de NumPy distintas); a garantia vale na mesma imagem Docker.

---

## 5. Usuários e Personas

**Usuário primário:** 🟡 Os componentes internos (`dyno-bench`, `ecu-core`, `knock-and-failure-model`, `telemetry-datalogger`) consomem a biblioteca. Os desenvolvedores desses componentes são os utilizadores diretos da API Python.

**Usuário secundário:** 🟡 As personas do PRD sentem o modelo pelos resultados:
- 🟡 **Lucas:** precisa de que o aumento exagerado de boost e de avanço gere pressão de pico e temperatura da zona não queimada coerentes, para o knock aparecer pela razão certa.
- 🟡 **Rodrigo:** precisa de uma VE física "verdadeira" que a tabela de VE da ECU tenta adivinhar; o erro da tabela ⇒ lambda real ≠ lambda alvo, visível na wideband com atraso real.
- 🟡 **Prof. Marcos:** precisa de equações explícitas e de pressão no cilindro por ângulo para demonstrar a relação entre avanço, MBT e EGT.

**Jornada atual (sem a feature):**
1. 🟡 O aluno lê a teoria (Heywood) sem ver o efeito de uma alteração.
2. 🟡 Os simuladores existentes respondem com curvas pré-gravadas, sem pressão no cilindro nem VE física.

**Jornada futura (com a feature):**
1. 🟡 O aluno altera a VE, o lambda alvo ou o avanço na ECU simulada.
2. 🟡 O motor responde com lambda real, torque, EGT e pressão no cilindro calculados a partir da física.
3. 🟡 O modelo de dano lê os ganchos e decide se há knock ou falha, com causa rastreável.

---

## 6. Requisitos Funcionais

### 6.1 Requisitos Principais

| ID | Requisito | Prioridade | Critério de Aceite |
|----|-----------|-----------|-------------------|
| RF-01 | 🟡 O sistema deve aceitar um `PhysicsConfig` validado com `sim_hz` ∈ [100, 1000] (padrão 1000), `seed` inteiro ≥ 0 e `dt = 1 / sim_hz` fixo. | Must | `PhysicsConfig(sim_hz=99)` e `sim_hz=1001` levantam `ValidationError`; `step()` com `dt` diferente de `1/sim_hz` (tolerância 1e-12 s) levanta `PhysicsError(code="PHYSICS_DT_MISMATCH")`. |
| RF-02 | 🟡 O sistema deve avançar o ângulo de cambota por tick com `Δθ = 6 · rpm · dt` (graus) e disparar um evento de combustão por cilindro ao cruzar o ângulo de IVC desse cilindro, segundo a ordem de ignição do `EngineSpec`. | Must | A 6000 rpm durante 1,0 s simulado num motor de 4 cilindros o sistema regista exatamente 200 eventos ± 1, na ordem de ignição declarada. |
| RF-03 | 🟡 O sistema deve resolver o ciclo fechado de cada evento (IVC → EVO) com resolução angular de 1° de cambota e distribuir o trabalho do ciclo pelo tick com média móvel dos últimos `n_cyl` eventos. | Must | O torque indicado médio em regime permanente varia < 1 % entre ticks a 3000 rpm; o vetor de pressão do evento tem `(θ_EVO − θ_IVC) + 1` pontos. |
| RF-04 | 🟡 O sistema deve integrar o coletor de admissão (e o volume de boost, quando sobrealimentado) com o modelo filling & emptying descrito no Apêndice A.2. | Must | Em degrau de borboleta 10 % → 100 % a 3000 rpm aspirado, o `map_kpa` atinge 90 % do valor final entre 30 ms e 150 ms; a massa no coletor conserva-se com erro < 0,1 % em 60 s de regime. |
| RF-05 | 🟡 O sistema deve calcular a massa de ar aprisionada por cilindro com a VE física `VE_true(rpm, map, vvt)` do catálogo e as correções de gás residual, independentemente da tabela de VE da ECU. | Must | Com a tabela da ECU igual à VE física e lambda alvo 1,00, o lambda real fica em 1,00 ± 0,01; com a tabela da ECU 10 % acima da VE física, o lambda real fica em 0,91 ± 0,01. |
| RF-06 | 🟡 O sistema deve calcular a massa de combustível injetada a partir do pulso, da vazão estática do bico, da raiz da pressão diferencial e do dead time interpolado pela tensão da bateria (Apêndice A.3). | Must | Para bico de 550 cm³/min a 300 kPa, Δp 300 kPa, pulso 10,0 ms, dead time 1,0 ms e ρ 745 kg/m³, a massa vale 61,5 mg ± 0,5 %; pulso ≤ dead time produz massa 0. |
| RF-07 | 🟡 O sistema deve aplicar o modelo de wall-wetting tau-X de Aquino aos motores de injeção indireta quando `wall_wetting_enabled` está ativo, e desligá-lo por padrão em GDI. | Should | Em degrau de pulso +20 % a 2000 rpm PFI com ECT 20 °C, o lambda real empobrece transitoriamente ≥ 3 % e regressa ao regime em ≤ 1,0 s; com a flag desligada não há transiente. |
| RF-08 | 🟡 O sistema deve calcular o lambda real por cilindro `λ = m_air / (m_fuel · AFR_st)` e o lambda do coletor ponderado por massa, usando o `FuelSpec` ativo. | Must | Com m_air 500 mg, m_fuel 37,88 mg e E27 (AFR_st 13,2) o lambda vale 1,000 ± 0,002. |
| RF-09 | 🟡 O sistema deve modelar a fração queimada com Wiebe (a = 5, m = 2) e duração de combustão função de lambda, RPM, combustível e fração residual (Apêndice A.4). | Must | `x_b(θ0 + Δθ) ≥ 0,993`; a duração a λ 1,3 é ≥ 15 % maior que a λ 0,9 no mesmo RPM; E100 queima ≥ 8 % mais curto que E0 no mesmo ponto. |
| RF-10 | 🟡 O sistema deve calcular a pressão no cilindro com modelo de zona única, γ(T) variável e transferência de calor de Woschni (Apêndice A.5). | Must | Ciclo motorizado (sem combustão) a 2000 rpm: pressão de pico entre 0,80 e 1,00 de `p_ivc · r_c^1,30`; o balanço de energia fecha com erro ≤ 2 %. |
| RF-11 | 🟡 O sistema deve calcular IMEP bruto, PMEP, FMEP (Chen-Flynn), torque de freio, potência na cambota e potência na roda com as perdas de transmissão do veículo (Apêndice A.6). | Must | Para valores de entrada de teste fixos, o torque calculado coincide com a fórmula do Apêndice A.6 com erro < 0,1 %; `wheel_power_kw = power_kw · η_drv − P_fixa`. |
| RF-12 | 🟡 O sistema deve fazer o MBT emergir do faseamento da combustão, sem tabela de MBT explícita. | Must | Varredura de avanço de 0° a 45° BTDC (passo 1°) no `hatch-20t-gdi` a 3000 rpm WOT, λ 0,85, dano desligado: o máximo de torque ocorre com `theta_pmax_deg_atdc` ∈ [12, 18]. |
| RF-13 | 🟡 O sistema deve calcular a EGT por cilindro e do coletor por balanço de energia de escape, incluindo a pós-combustão do combustível não queimado (Apêndice A.7). | Must | Atrasar o avanço 10° a partir do MBT eleva a EGT de regime ≥ 40 °C; λ 0,80 reduz a EGT ≥ 30 °C face a λ 0,90 no mesmo ponto. |
| RF-14 | 🟡 O sistema deve modelar o turbo com inércia do eixo, mapas simplificados de compressor e turbina, wastegate por duty e intercooler com eficiência ε (Apêndice A.8). | Must | No `hatch-20t-gdi`, WOT a 2000 rpm em 3ª, o boost atinge 90 % do alvo em 0,8–2,5 s; duty 0 % mantém o boost na pressão de mola ± 5 kPa. |
| RF-15 | 🟡 O sistema deve modelar o supercharger de deslocamento positivo (Roots ou twin-screw) com relação de polia, eficiência adiabática, válvula de bypass e perda parasita (Apêndice A.9). | Must | No `muscle-v8-sc` a 6000 rpm WOT a perda parasita fica entre 40 kW e 80 kW; com bypass aberto a perda cai ≥ 80 %. |
| RF-16 | 🟡 O sistema deve suportar os combustíveis `e27`, `e100`, `podium` e `e0` lidos do catálogo (PCI, AFR estequiométrico, RON/MON, calor de vaporização, densidade, coeficientes de velocidade de chama). | Must | Trocar o combustível de `e27` para `e100` com o mesmo pulso empobrece o lambda real na razão (13,2 · 745)/(9,0 · 789) = 1,385 ± 1 %. |
| RF-17 | 🟡 O sistema deve gerar `SensorReadings` com ruído gaussiano semeado por canal e atraso de 1ª ordem (wideband τ 0,1 s mais atraso de transporte; termopar EGT τ configurável 0,5–1,5 s, padrão 1,0 s). | Must | Em degrau de lambda real 1,00 → 0,85, a wideband atinge 63 % do degrau em 0,1 s ± 10 % mais o atraso de transporte; o desvio-padrão do ruído medido em 10 000 amostras fica a ± 10 % do σ configurado. |
| RF-18 | 🟡 O sistema deve expor, para cada evento de combustão, um `CombustionEvent` com p(θ), T_u(θ) e x_b(θ) desde a faísca até o fim da combustão, a pressão de pico, a temperatura máxima da zona não queimada e a força de pico na biela. | Must | Cada `EngineState` contém a lista dos eventos ocorridos no tick; os vetores têm o mesmo comprimento; a integral de Livengood-Wu calculada pelo teste sobre o histórico reproduz o valor de referência com erro < 0,5 %. |
| RF-19 | 🟡 O sistema deve aceitar um comando de bloqueio do motor (`lock(reason)`) vindo do modelo de dano e, no tick seguinte, suprimir a combustão e levar o RPM a 0 em ≤ 0,5 s simulados. | Must | Após `lock("rod_failure")`, nenhum evento de combustão é produzido e `rpm == 0` em ≤ 0,5 s; `reset_mechanical()` restaura o motor a 0 rpm com temperaturas do ambiente. |
| RF-20 | 🟡 O sistema deve ser determinístico: o mesmo `PhysicsConfig`, veículo, combustível e sequência de `ActuatorCommands`/`DynoLoad` produzem o mesmo `state_digest()` SHA-256 em cada tick. | Must | 20 execuções de 30 s simulados a 1000 Hz produzem 20 digests finais idênticos; o código do pacote não chama `time.time()`, `random` nem `numpy.random` sem o `Generator` semeado (verificado por teste de lint `ruff` com regra banida). |
| RF-21 | 🟡 O sistema deve modelar a dinâmica rotacional `(J_eng + J_load) · dω/dt = T_b − T_load` com a carga e a inércia refletidas do `DynoLoad`. | Must | Com T_load = 0, J total 0,25 kg·m² e T_b constante 100 N·m, o RPM sobe 3820 rpm/s ± 1 %. |
| RF-22 | 🟡 O sistema deve aplicar os cortes de combustível e de ignição por cilindro e modelar o combustível não queimado enviado ao escape (energia de pós-combustão e evento de pop). | Must | Corte de ignição com injeção ativa num cilindro gera `afterfire_energy_j > 0` e `pop_event = True` nesse evento; corte de combustível gera λ do cilindro = +∞ representado por `None` e EGT descendente. |
| RF-23 | 🟡 O sistema deve aceitar falhas físicas injetadas (`PhysicsFault`) para os defeitos ocultos dos cenários: bomba de combustível fraca, bico obstruído, fuga de boost, viés de sensor e wastegate presa (`wastegate_stuck`, abertura fixa `stuck_position_pct` que ignora `wastegate_duty_pct`). | Should | `fuel_pump_weak` com teto 60 L/h reduz a pressão de rail quando a vazão pedida o excede e empobrece o lambda real ≥ 5 % a plena carga no `hatch-20t-gdi`.; `wastegate_stuck` com `stuck_position_pct = 0` produz sobreboost (MAP ≥ 1,15 × alvo da ECU a plena carga) e com 100 % mantém o boost ≤ pressão de mola + 10 kPa, para qualquer duty comandado. |
| RF-24 | 🟡 O sistema deve calcular as temperaturas lumpadas de líquido de arrefecimento, de pistão e de ponto quente (vela/válvula) com constantes de 1ª ordem, para a repetibilidade térmica entre puxadas. | Should | 5 puxadas WOT seguidas sem pausa elevam a IAT de regime ≥ 5 °C (heat soak); 120 s em marcha lenta reduzem a IAT de volta para ± 2 °C do valor inicial. |
| RF-25 | 🟡 O sistema deve permitir `snapshot()` e `restore(snapshot)` do estado completo (incluindo o estado do gerador de ruído). | Should | `restore(snapshot())` seguido de N ticks produz o mesmo digest que a continuação sem snapshot. |
| RF-26 | 🟡 O sistema deve publicar em `SensorReadings`, por cilindro, a tensão do sensor de knock `knock_sensor_v` (0,0 a 5,0 V) e o índice normalizado `knock_intensity` (0,0 a 1,0) derivado dela pela fórmula do Apêndice A.10. | Must | Teste: com `KnockSignal.intensity` = 0 e ruído desligado, `knock_sensor_v` = 0,05 V e `knock_intensity` = 0,0; com `intensity` = 10, `knock_sensor_v` = 5,0 V (saturado) e `knock_intensity` = 1,0; nenhum valor fora dos intervalos em 10⁶ ticks com ruído. |

### 6.2 Fluxo Principal (Happy Path)

1. 🟡 O `dyno-bench` cria `PhysicsEngine(config: PhysicsConfig, vehicle: VehicleSpec, fuel: FuelSpec)`; o sistema valida a configuração, pré-calcula a geometria (V(θ), dV/dθ, área de parede por grau) e inicializa o gerador `numpy.random.Generator(PCG64(seed))`.
2. 🟡 No início do tick k, o worker chama `engine.read_sensors(knock_signal)`; o sistema devolve `SensorReadings` do estado atual com ruído semeado e filtros de 1ª ordem.
3. 🟡 O `ecu-core` calcula `ActuatorCommands` a partir dos sensores e devolve-os ao worker.
4. 🟡 O worker chama `engine.step(commands, dyno_load, dt)`; o sistema valida os comandos, integra coletor, turbo/supercharger e eixo, avança o ângulo, resolve os eventos de combustão que cruzam o IVC no tick e calcula torque, potência e EGT.
5. 🟡 O sistema devolve `EngineState` com os `CombustionEvent` do tick; o `knock-and-failure-model` lê os ganchos e devolve `DamageState`.
6. 🟡 A telemetria amostra o `EngineState`; o worker repete o tick k+1 até o fim da puxada.
7. 🟡 Resultado: uma puxada de varredura produz curvas de torque, potência, lambda e EGT reprodutíveis por hash e dentro de 5 % da referência com a calibração OEM.

### 6.3 Fluxos Alternativos

**Fluxo Alternativo A — Falha catastrófica:**
1. 🟡 O modelo de dano emite `FailureEvent` e chama `engine.lock(reason)`.
2. 🟡 No tick seguinte o sistema suprime a combustão, aplica torque de travamento e leva o RPM a 0 em ≤ 0,5 s; `EngineState.locked = True`.
3. 🟡 Após `POST /api/v1/sessions/{session_id}/engine/restore` (dono: dano), o worker chama `engine.reset_mechanical()`.

**Fluxo Alternativo B — Tick acima do orçamento:**
1. 🟡 O worker mede o tempo de parede do tick; o sistema continua determinístico porque o tempo simulado não depende do tempo de parede.
2. 🟡 O worker reporta `real_time_factor < 1,0` em `run.state`; a física nunca salta ticks nem altera `dt`.

**Fluxo Alternativo C — Motor sem sobrealimentação ativa:**
1. 🟡 Com `forced_induction = None` no veículo, o sistema ignora `wastegate_duty_pct`, `bypass_open` e `antilag_air_pct` e usa a pressão ambiente a montante da borboleta.

---

## 7. Requisitos Não-Funcionais

| ID | Requisito | Valor alvo | Observação |
|----|-----------|-----------|------------|
| RNF-01 | 🟡 Desempenho por tick | média ≤ 0,5 ms e p99 ≤ 2,0 ms a 1000 Hz; mínimo absoluto de aceite: tempo real a 100 Hz em 100 % dos veículos | 🟡 `pytest-benchmark` em `backend/tests/physics/bench/test_bench_step.py`, cenário pior caso `muscle-v8-sc` a 7500 rpm WOT (500 eventos/s), 1 núcleo do hardware de referência; falha de CI se a média > 0,5 ms |
| RNF-02 | 🟡 Precisão vs referência | < 5 % por ponto de RPM em torque, potência, lambda e EGT (EGT em °C) | 🟡 Teste `test_reference_curves.py` com varredura de 2000 rpm até a rotação máxima, passo 250 rpm, calibração de referência do catálogo |
| RNF-03 | 🟡 Determinismo | 100 % de digests SHA-256 idênticos em 20 execuções na mesma imagem Docker | 🟡 Serialização canónica float64 little-endian em ordem fixa de campos |
| RNF-04 | 🟡 Conservação numérica | energia do ciclo fecha com erro ≤ 2 %; massa do coletor ≤ 0,1 % em 60 s | 🟡 Teste de propriedade com `hypothesis` em 200 pontos de operação |
| RNF-05 | 🟡 Memória | ≤ 150 MB por instância de `PhysicsEngine`, incluindo a cache de ciclos | 🟡 Medido com `tracemalloc` após 300 s simulados |
| RNF-06 | 🟡 Qualidade de código | cobertura ≥ 85 % do pacote `physics/`; `mypy --strict` e `ruff` sem erros; `bandit` sem achados médios | 🟡 Gate de CI do platform-foundation |
| RNF-07 | 🟡 Arranque | construção de `PhysicsEngine` ≤ 200 ms | 🟡 Inclui pré-cálculo de geometria |

---

## 8. Design e Interface

**Componentes afetados:**
- 🟡 `backend/src/simremap/physics/` (novo): `config.py`, `contracts.py`, `engine.py`, `geometry.py`, `manifold.py`, `fuel.py`, `combustion.py`, `cycle_solver.py`, `friction.py`, `exhaust.py`, `turbo.py`, `supercharger.py`, `thermal.py`, `sensors.py`, `faults.py`, `digest.py`.
- 🟡 `backend/tests/physics/` (novo): testes unitários, de propriedade, de referência e benchmark.
- 🟡 Sem endpoints REST nem payloads WebSocket próprios; o `telemetry-datalogger` publica os canais derivados de `EngineState`.

**API Python pública (comportamento esperado):**

```python
class PhysicsEngine:
    def __init__(self, config: PhysicsConfig, vehicle: VehicleSpec, fuel: FuelSpec) -> None: ...
    def read_sensors(self, knock_signal: KnockSignal | None = None) -> SensorReadings: ...
    def step(self, commands: ActuatorCommands, dyno_load: DynoLoad, dt: float) -> EngineState: ...
    def lock(self, reason: str) -> None: ...            # chamado pelo modelo de dano
    def reset_mechanical(self) -> None: ...             # restauração após quebra
    def set_fuel(self, fuel: FuelSpec) -> None: ...     # só com rpm == 0
    def snapshot(self) -> bytes: ...
    def restore(self, blob: bytes) -> None: ...
    def state_digest(self) -> str: ...                  # SHA-256 hex do estado canónico

class PhysicsError(Exception):
    code: str   # PHYSICS_CONFIG_INVALID | PHYSICS_DT_MISMATCH | ACTUATOR_COMMAND_INVALID
                # PHYSICS_NUMERIC_DIVERGENCE | PHYSICS_FUEL_CHANGE_WHILE_RUNNING | PHYSICS_SNAPSHOT_INVALID
    detail: str
```

🟡 Quando um `PhysicsError` atravessa a API (via endpoints do `dyno-bench`), o handler do `core` converte-o em `application/problem+json` com o mesmo `code`: `PHYSICS_CONFIG_INVALID`, `ACTUATOR_COMMAND_INVALID` → HTTP 422; `PHYSICS_NUMERIC_DIVERGENCE` → HTTP 500 com a puxada abortada; `PHYSICS_FUEL_CHANGE_WHILE_RUNNING` → HTTP 409.

**Ordem interna do `step()` (determinística):**
1. 🟡 Validar `commands` (comprimento das listas = `n_cyl`, limites) e `dt`.
2. 🟡 Atualizar atuadores com dinâmica própria: borboleta (τ 30 ms), VVT (taxa máx. 150°/s), wastegate (τ 50 ms).
3. 🟡 Integrar com Heun os volumes de gás (boost, coletor de admissão, coletor de escape) e o eixo do turbo, em subpassos `h = dt / k`, `k = ceil(dt / 1 ms)`.
4. 🟡 Avançar `θ` e resolver, por ordem de ângulo, cada evento cujo IVC caia no intervalo do tick.
5. 🟡 Atualizar torque médio, dinâmica rotacional, temperaturas lumpadas e EGT; montar `EngineState`.

**Estados da UI:**
- 🟡 Estado vazio: não se aplica (biblioteca sem UI); o `dyno-cockpit-ui` mostra "motor parado" quando `rpm == 0` e `locked == False`.
- 🟡 Estado de carregamento: não se aplica; a construção ≤ 200 ms acontece na criação da sessão.
- 🟡 Estado de erro: `PhysicsError` com `code` estável propagado ao `dyno-bench`, que publica `run.state` com `state = "aborted"`.
- 🟡 Estado de sucesso: `EngineState` por tick.

---

## 9. Modelo de Dados

🟡 Contratos Pydantic v2 (`model_config = ConfigDict(frozen=True, extra="forbid")`) em `physics/contracts.py`. Os contratos não são persistidos em base de dados pela física; o `telemetry-datalogger` e o `dyno-bench` persistem as suas projeções. Listas por cilindro têm comprimento exato `n_cyl`, índice 0 = cilindro 1.

```python
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field

Pct = Annotated[ float, Field(ge=0.0, le=100.0) ]

class SensorNoiseConfig(BaseModel):
    map_sigma_kpa: float = Field(0.3, ge=0.0)
    iat_sigma_c: float = Field(0.2, ge=0.0)
    ect_sigma_c: float = Field(0.2, ge=0.0)
    lambda_sigma: float = Field(0.005, ge=0.0)
    egt_sigma_c: float = Field(3.0, ge=0.0)
    rpm_sigma: float = Field(2.0, ge=0.0)
    tps_sigma_pct: float = Field(0.1, ge=0.0)

class PhysicsFault(BaseModel):
    kind: Literal["fuel_pump_weak", "injector_clogged", "boost_leak", "sensor_bias", "wastegate_stuck"]
    cylinder: int | None = Field(None, ge=1, le=8)          # para injector_clogged
    fuel_pump_max_lph: float | None = Field(None, gt=0.0)   # fuel_pump_weak
    injector_flow_factor: float | None = Field(None, gt=0.0, le=1.0)
    leak_area_mm2: float | None = Field(None, gt=0.0)       # boost_leak
    sensor_channel: str | None = None                        # sensor_bias
    sensor_bias: float | None = None                         # unidade do canal
    stuck_position_pct: float | None = Field(None, ge=0.0, le=100.0)  # wastegate_stuck: abertura fixa da válvula
    start_t_sim_s: float = Field(0.0, ge=0.0)

class PhysicsConfig(BaseModel):
    sim_hz: int = Field(1000, ge=100, le=1000)
    seed: int = Field(0, ge=0, le=2**63 - 1)
    crank_resolution_deg: Literal[1.0] = 1.0
    ambient_pressure_kpa: float = Field(101.325, ge=60.0, le=110.0)
    ambient_temp_c: float = Field(25.0, ge=-20.0, le=50.0)
    wall_wetting_enabled: bool | None = None   # None = ligado em PFI, desligado em GDI
    noise_enabled: bool = True
    noise: SensorNoiseConfig = SensorNoiseConfig()
    wideband_tau_s: float = Field(0.1, ge=0.02, le=0.5)
    egt_thermocouple_tau_s: float = Field(1.0, ge=0.5, le=1.5)
    wiebe_a: float = Field(5.0, gt=0.0)
    wiebe_m: float = Field(2.0, ge=0.0)
    cycle_cache_size: int = Field(4096, ge=0, le=65536)   # 0 desliga a cache
    faults: list[ PhysicsFault ] = Field(default_factory=list, max_length=8)

    @property
    def dt(self) -> float:
        return 1.0 / self.sim_hz

class KnockSignal(BaseModel):
    """Entrada vinda do knock-and-failure-model (último ciclo de cada cilindro)."""
    intensity: list[ Annotated[ float, Field(ge=0.0) ] ]   # adimensional, 0 = sem knock

class SensorReadings(BaseModel):
    t_sim_s: float = Field(ge=0.0)
    tick: int = Field(ge=0)
    rpm: float = Field(ge=0.0)
    crank_angle_deg: float = Field(ge=0.0, lt=720.0)     # 0 = TDC compressão cil. 1
    cam_intake_deg: float                                  # posição real do VVT de admissão
    cam_exhaust_deg: float
    map_kpa: float = Field(ge=0.0)                         # absoluta
    baro_kpa: float = Field(ge=0.0)
    boost_pre_throttle_kpa: float = Field(ge=0.0)         # absoluta, antes da borboleta
    iat_c: float
    ect_c: float
    oil_temp_c: float
    tps_pct: Pct
    lambda_measured: float = Field(ge=0.5, le=2.0)               # wideband saturada 0,5–2,0
    egt_c: list[ float ]                                     # termopar por cilindro
    egt_collector_c: float                                 # pré-turbina
    fuel_pressure_kpa: float = Field(ge=0.0)               # rail (diferencial)
    battery_v: float = Field(ge=6.0, le=16.0)
    knock_sensor_v: list[ Annotated[ float, Field(ge=0.0, le=5.0) ] ]   # por cilindro, 0,0–5,0 V
    knock_intensity: list[ Annotated[ float, Field(ge=0.0, le=1.0) ] ]  # por cilindro, índice normalizado derivado de knock_sensor_v
    turbo_rpm: float | None = None                         # None se aspirado/supercharger
    wastegate_position_pct: Pct | None = None

class ActuatorCommands(BaseModel):
    t_sim_s: float = Field(ge=0.0)
    injector_pw_ms: list[ Annotated[ float, Field(ge=0.0, le=50.0) ] ]
    injection_end_deg_btdc: list[ Annotated[ float, Field(ge=-360.0, le=720.0) ] ] | None = None
    ignition_advance_deg: list[ Annotated[ float, Field(ge=-30.0, le=60.0) ] ]  # BTDC, + = avanço
    fuel_cut: list[ bool ]
    spark_cut: list[ bool ]
    throttle_pct: Pct                                       # alvo da borboleta eletrónica
    wastegate_duty_pct: Pct = 0.0
    vvt_intake_target_deg: float = 0.0
    vvt_exhaust_target_deg: float = 0.0
    bypass_open: bool = False                               # BOV (turbo) ou bypass (supercharger)
    antilag_air_pct: Pct = 0.0                              # válvula de ar do antilag
    fuel_pump_duty_pct: Pct = 100.0

class CombustionEvent(BaseModel):
    cylinder: int = Field(ge=1, le=8)
    t_sim_s: float
    rpm: float
    theta_start_deg: float                     # ângulo do primeiro ponto (faísca), ATDC negativo
    pressure_kpa: list[ float ]                   # 1 ponto por grau, faísca → fim de combustão
    t_unburned_k: list[ float ]
    burned_fraction: list[ float ]
    p_max_kpa: float
    theta_pmax_deg_atdc: float
    t_unburned_max_k: float
    rod_force_peak_n: float
    imep_gross_kpa: float
    lambda_real: float | None                   # None em corte de combustível
    fuel_octane_ron: float
    fuel_octane_mon: float
    misfire: bool
    afterfire_energy_j: float = Field(ge=0.0)
    pop_event: bool

class EngineState(BaseModel):
    t_sim_s: float
    tick: int
    rpm: float
    crank_angle_deg: float
    locked: bool
    stalled: bool
    map_kpa: float
    boost_pre_throttle_kpa: float
    exhaust_manifold_kpa: float
    t_manifold_c: float
    t_intercooler_out_c: float | None
    ve_true: list[ float ]
    m_air_mg: list[ float ]
    m_fuel_mg: list[ float ]
    lambda_cyl: list[ float | None ]
    lambda_collector: float | None
    ignition_advance_deg: list[ float ]
    burn_duration_deg: list[ float ]
    p_max_kpa: list[ float ]
    theta_pmax_deg_atdc: list[ float ]
    t_unburned_max_k: list[ float ]
    rod_force_peak_n: list[ float ]
    piston_temp_c: list[ float ]
    hot_spot_temp_c: list[ float ]
    egt_c: list[ float ]                        # gás real (sem atraso de termopar)
    egt_collector_c: float
    imep_gross_kpa: float
    pmep_kpa: float
    fmep_kpa: float
    torque_indicated_nm: float
    torque_nm: float                          # freio, na cambota
    power_kw: float
    wheel_power_kw: float
    whp: float
    fuel_flow_g_s: float
    bsfc_g_kwh: float | None
    thermal_efficiency: float
    turbo_rpm: float | None
    compressor_pressure_ratio: float | None
    compressor_efficiency: float | None
    surge_margin: float | None                # < 0 = surge
    wastegate_position_pct: float | None
    supercharger_rpm: float | None
    supercharger_power_kw: float | None
    ect_c: float
    iat_c: float
    events: list["CombustionEvent"]           # eventos ocorridos neste tick (0..n)
    real_time_factor: float | None = None     # preenchido pelo worker
```

**Migrações necessárias:** 🟡 Não. A física não cria tabelas SQL.

---

## 10. Integrações e Dependências

| Dependência | Tipo | Impacto se indisponível |
|-------------|------|------------------------|
| 🟡 `vehicle-catalog` (`VehicleSpec`, `EngineSpec`, `TurboSpec`, `SuperchargerSpec`, `InjectorSpec`, `FuelSpec`, `true_ve`) | Obrigatória | 🟡 Sem catálogo válido o `PhysicsEngine` não é construído; `PHYSICS_CONFIG_INVALID` |
| 🟡 `dyno-bench` (`DynoLoad`: `load_torque_nm` na cambota e `reflected_inertia_kgm2`) | Obrigatória em runtime | 🟡 Sem `DynoLoad` o worker não chama `step()`; testes usam `DynoLoad` sintético |
| 🟡 `ecu-core` (`ActuatorCommands`) | Obrigatória em runtime (Sprint 2) | 🟡 No Sprint 1 os testes usam `ReferenceCommandSchedule` do catálogo (comandos de malha aberta por RPM) |
| 🟡 `knock-and-failure-model` (`KnockSignal`, `lock()`) | Opcional | 🟡 Sem modelo de dano, `knock_sensor_v` fica no ruído de fundo e o motor nunca bloqueia |
| 🟡 NumPy ≥ 2.0 | Obrigatória | 🟡 Sem fallback; dependência fixada no `uv.lock` |
| 🟡 `pytest-benchmark`, `hypothesis` | Obrigatória (dev) | 🟡 Sem elas o CI não valida RNF-01 e RNF-04 |
| 🟡 Literatura aberta (Heywood; Woschni; Chen-Flynn; Aquino; Metghalchi-Keck) | Referência | 🟡 Coeficientes marcados "inferido, a validar" no Apêndice |

---

## 11. Edge Cases e Tratamento de Erros

| Cenário | Trigger | Comportamento esperado |
|---------|---------|----------------------|
| 🟡 EC-01: Comando com listas de tamanho errado | `len(injector_pw_ms) != n_cyl` ou valor fora de limite | O sistema levanta `PhysicsError(code="ACTUATOR_COMMAND_INVALID")` antes de alterar qualquer estado; o tick não avança e o digest fica igual. |
| 🟡 EC-02: Divergência numérica | p < 0, T > 4000 K, NaN ou Inf em qualquer variável de estado | O sistema levanta `PhysicsError(code="PHYSICS_NUMERIC_DIVERGENCE")` com o nome da variável e o tick; o worker aborta a puxada; não há retry automático porque a repetição determinística reproduz a falha. |
| 🟡 EC-03: Tick acima do orçamento (timeout de tempo real) | tempo de parede do tick > dt | O sistema mantém o passo fixo e o resultado; o worker marca `real_time_factor < 1,0`; nenhum tick é saltado (degradação só no ritmo, nunca na física). |
| 🟡 EC-04: Pulso menor que o dead time | `injector_pw_ms` ≤ dead time interpolado | O sistema injeta massa 0 nesse cilindro, regista `misfire = True` e λ `None`; sem exceção. |
| 🟡 EC-05: Lambda fora da inflamabilidade | λ > 1,6 ou λ < 0,55 | O sistema marca `misfire = True`, não liberta calor no cilindro, envia a massa de combustível ao escape (energia de pós-combustão se houver O2 disponível) e segue. |
| 🟡 EC-06: RPM abaixo do mínimo | rpm < 300 com combustão ativa | O sistema marca `stalled = True`, leva o RPM a 0 e aguarda novo arranque pelo `DynoLoad` (motor de arranque simulado a 250 rpm). |
| 🟡 EC-07: Sobre-rotação | rpm > `MechanicalLimits.max_rpm` · 1,15 | O sistema satura o RPM nesse valor e continua; a decisão de dano (flutuação de válvulas) pertence ao modelo de dano. |
| 🟡 EC-08: Surge do compressor | vazão corrigida < linha de surge | O sistema marca `surge_margin < 0`, aplica oscilação de PR amortecida (amplitude 5 %, 8 Hz) determinística e não levanta exceção. |
| 🟡 EC-09: Catálogo indisponível ou dados inválidos | `true_ve` ausente, geometria incoerente ou combustível desconhecido | O sistema falha na construção com `PHYSICS_CONFIG_INVALID`; sem fallback para valores por omissão, porque um motor com dados inventados violaria a meta de 5 %. |
| 🟡 EC-10: Troca de combustível com motor em funcionamento | `set_fuel()` com rpm > 0 | O sistema levanta `PHYSICS_FUEL_CHANGE_WHILE_RUNNING` (HTTP 409 na API). |
| 🟡 EC-11: Snapshot corrompido ou de outra versão | hash ou `schema_version` do blob não coincide | O sistema levanta `PHYSICS_SNAPSHOT_INVALID` e mantém o estado atual intacto. |
| 🟡 EC-12: Cache de ciclos cheia | mais de `cycle_cache_size` chaves | O sistema remove a entrada menos usada (LRU); o resultado não muda porque o solver usa sempre as entradas quantizadas. |
| 🟡 EC-13: Motor bloqueado recebe comandos | `step()` após `lock()` | O sistema aceita os comandos, ignora injeção e ignição e devolve `locked = True` até `reset_mechanical()`. |

---

## 12. Segurança e Privacidade

- 🟡 **Autenticação:** não se aplica; biblioteca interna sem superfície de rede.
- 🟡 **Autorização:** não se aplica; o acesso passa pelos endpoints do `dyno-bench`.
- 🟡 **Dados sensíveis:** nenhum PII; o estado contém só variáveis físicas.
- 🟡 **Integridade:** `restore()` aceita apenas blobs produzidos por `snapshot()` com cabeçalho `schema_version` e SHA-256; não usa `pickle` (formato: cabeçalho JSON canónico + vetor float64 little-endian) para impedir execução de código ao importar.
- 🟡 **Auditoria:** o worker regista em log estruturado `seed`, `sim_hz`, `vehicle_id`, `fuel_id`, faults ativas e o digest final de cada puxada.

---

## 13. Plano de Rollout

- 🟡 **Estratégia:** entrega incremental no Sprint 1 com testes de referência do `hatch-20t-gdi` como gate; os 3 veículos restantes entram atrás da flag de catálogo `validation_status = "validated"` até o Sprint 4.
- 🟡 **Como reverter (rollback):** a imagem Docker anterior volta a ser usada (`docker compose` com a tag anterior); os coeficientes vivem nos dados versionados do catálogo, por isso uma correção de coeficiente reverte com o arquivo de dados.
- 🟡 **Monitoramento pós-deploy:** acompanhar no CI o tempo médio por tick (RNF-01), o desvio máximo por curva (RNF-02) e a contagem de `PHYSICS_NUMERIC_DIVERGENCE` nos logs das primeiras 48 h de uso em turma.

---

## 14. Open Questions

| # | Pergunta | Impacto | Dono | Prazo |
|---|---------|---------|------|-------|
| OQ-01 | 🟡 ⚠️ ABERTO: o orçamento de 0,5 ms por tick a 1000 Hz com o V8 a 7500 rpm exige compilação (numba ou Cython)? O PRD fixa Python/NumPy; a decisão atual é Python + NumPy + cache de ciclos quantizada. | Alto | George | 2026-10-22 |
| OQ-02 | 🟡 Resolvida na revisão R1 (2026-10-18): a meta de 5 % em torque, potência, lambda e EGT valida-se contra o benchmark canônico `Reference Benchmark Baseline v1` do `vehicle-catalog`. | Alto | George | 2026-10-24 |
| OQ-03 | 🟡 ⚠️ ABERTO: o desvio de EGT de 5 % mede-se em °C (decisão atual) ou em K? Em K a meta fica ≈ 30 % mais folgada. | Médio | George | 2026-10-24 |
| OQ-04 | 🟡 ⚠️ ABERTO: o determinismo deve valer entre plataformas (x86-64 vs ARM64)? Hoje vale só na mesma imagem Docker (NG-07). | Médio | George | 2026-11-05 |
| OQ-05 | 🟡 ⚠️ ABERTO: os coeficientes de velocidade laminar de chama de E100 e de Podium (Apêndice A.4) precisam de fonte aberta confirmada. | Baixo | George | 2026-11-05 |

---

## 15. Decisões Tomadas (Decision Log)

| Decisão | Alternativas consideradas | Racional |
|---------|--------------------------|---------|
| 🟡 Cálculo do ciclo fechado por evento de combustão (1°) e média móvel de `n_cyl` eventos para o torque no tick | 🟡 Integração angular contínua dentro de cada tick; modelo de valor médio puro | 🟡 Mantém a pressão no cilindro e o histórico para Livengood-Wu, desacopla o ciclo do tick e cabe no orçamento de 0,5 ms |
| 🟡 Entradas do solver de ciclo quantizadas (rpm 10 rpm, massa 0,2 %, λ 0,002, avanço 0,25°, T_ivc 1 K) com cache LRU | 🟡 Solver sem quantização; cache não determinística | 🟡 Com ou sem acerto na cache o resultado é idêntico, o que preserva o hash e reduz o custo em regime |
| 🟡 VE física `true_ve` vem do catálogo e é invisível à ECU | 🟡 Usar a tabela de VE da ECU como verdade | 🟡 A tabela da ECU deve tentar adivinhar o motor; o erro dela produz lambda real ≠ alvo, que é o aprendizado do Rodrigo |
| 🟡 Coletores 0D (filling & emptying) com volumes do catálogo | 🟡 Modelo 1D por ondas | 🟡 Custo compatível com 1000 Hz; NG-01 |
| 🟡 Ruído com `numpy.random.Generator(PCG64)` e um substream `SeedSequence.spawn` por canal, em ordem fixa | 🟡 `random` global; ruído sem semente | 🟡 Determinismo por hash (convenção do laço) |
| 🟡 Knock calculado pelo modelo de dano a partir do `CombustionEvent`; a física só converte a intensidade em `knock_sensor_v` | 🟡 Knock dentro da física | 🟡 Separação de responsabilidades da convenção; evita cálculo duplicado |
| 🟡 Falhas físicas injetáveis (`PhysicsFault`) na própria física | 🟡 Simular defeitos só na ECU | 🟡 Um defeito oculto de bomba de combustível tem de afetar a física real, não a leitura |

---

## Apêndice

### A.1 Geometria do cilindro

🟡 Variáveis: B diâmetro (m), S curso (m), a = S/2 raio da manivela (m), l comprimento da biela (m), r_c taxa de compressão, θ ângulo de cambota (rad, 0 = PMS de compressão).

- 🟡 `V_d,cyl = (π/4) · B² · S` (m³); `V_c = V_d,cyl / (r_c − 1)` (m³).
- 🟡 `V(θ) = V_c + (π/4) · B² · (l + a − a·cos θ − sqrt(l² − a²·sin² θ))` (m³).
- 🟡 `dV/dθ = (π/4) · B² · a · sin θ · (1 + a·cos θ / sqrt(l² − a²·sin² θ))` (m³/rad).
- 🟡 Área de parede: `A_w(θ) = 2 · (π/4) · B² · f_crown + π · B · (V(θ) − V_c) / ((π/4) · B²) + A_c`, `f_crown = 1,1`, `A_c` área da folga calculada com `V_c`.
- 🟡 Velocidade média do pistão: `S̄p = 2 · S · rpm / 60` (m/s).
- 🟡 Avanço angular por tick: `Δθ_deg = 6 · rpm · dt`; tempo por grau `dt_deg = 1 / (6 · rpm)` (s/°).

### A.2 Coletores (filling & emptying)

🟡 Variáveis: p (kPa abs), T (K), V (m³), ṁ (kg/s), R_ar = 287,05 J/(kg·K), γ_ar = 1,40.

- 🟡 Coletor de admissão isotérmico: `dp_man/dt = (R_ar · T_man / V_man) · (ṁ_thr − ṁ_eng) / 1000` (kPa/s).
- 🟡 Vazão do motor: `ṁ_eng = Σ_cyl VE_true · ρ_man · V_d,cyl · rpm / 120` (kg/s), `ρ_man = 1000 · p_man / (R_ar · T_man)` (kg/m³).
- 🟡 Vazão pela borboleta (orifício compressível): `ṁ_thr = C_d · A(tps) · 1000 · p_up / sqrt(R_ar · T_up) · Ψ(p_man / p_up)`, com `C_d = 0,85`.
- 🟡 `Ψ(pr) = sqrt(2γ/(γ−1) · (pr^(2/γ) − pr^((γ+1)/γ)))` para `pr > 0,528`; `Ψ = sqrt(γ) · (2/(γ+1))^((γ+1)/(2(γ−1)))` para `pr ≤ 0,528` (escoamento bloqueado).
- 🟡 Área efetiva: `A(tps) = A_idle + (A_max − A_idle) · (1 − cos(π/2 · tps/100))`, `A_max = (π/4) · d_throttle²`, `A_idle = 0,004 · A_max`.
- 🟡 Volume de boost (turbo/supercharger): `dp_boost/dt = (R_ar · T_boost / V_boost) · (ṁ_comp − ṁ_thr − ṁ_bov − ṁ_leak) / 1000`.
- 🟡 Coletor de escape: `dp_exh/dt = (R_exh · T_exh / V_exh) · (ṁ_eng + ṁ_fuel + ṁ_antilag − ṁ_turb − ṁ_wg) / 1000`, `R_exh = 287 J/(kg·K)`.
- 🟡 VE física com residual: `VE_true = VE_map(rpm, map) · (1 + k_vvt · g_vvt(vvt, rpm)) · (r_c − (p_exh/p_man)^(1/γ)) / (r_c − 1)`, saturada em [0,20; 1,35]; `VE_map` e `k_vvt` vêm do catálogo.
- 🟡 Massa aprisionada: `m_air = VE_true · ρ_man · V_d,cyl` (kg).

### A.3 Combustível

- 🟡 Massa injetada: `m_inj = ρ_f · (Q_static / 60 · 10⁻⁶) · sqrt(Δp / Δp_ref) · max(0, PW − t_dead(V_bat, Δp)) / 1000` (kg), Q_static em cm³/min, PW e t_dead em ms.
- 🟡 Δp em PFI: `p_rail − p_man` (regulador referenciado ao MAP ⇒ constante); em GDI: `p_rail − p_cyl(θ_inj)` com `p_cyl` ≈ `p_man` durante a admissão.
- 🟡 `t_dead` interpolado linearmente na tabela `InjectorSpec.dead_time_ms` por tensão (V) e por pressão diferencial (kPa); fora da tabela usa o valor da borda.
- 🟡 Wall-wetting (Aquino), por evento k do cilindro: `m_evap = m_film,k · (1 − exp(−Δt_k / τ))`; `m_cyl = (1 − X) · m_inj + m_evap`; `m_film,k+1 = m_film,k − m_evap + X · m_inj`. Padrões PFI: `X = 0,25 · f_T`, `τ = 0,30 s · f_T`, `f_T = exp(0,02 · (90 − ECT_c))` saturado em [1; 4]. GDI: `X = 0,02`, `τ = 0,05 s`.
- 🟡 Arrefecimento evaporativo: `ΔT_evap = f_evap · m_fuel · h_fg / ((m_air + m_fuel) · c_p,mix)`, `f_evap = 1,0` (GDI) ou `0,5` (PFI), `c_p,mix = 1,10 kJ/(kg·K)`.
- 🟡 Lambda: `λ = m_air / (m_fuel · AFR_st)`; lambda do coletor `λ_col = Σ m_air / (AFR_st · Σ m_fuel)`.

### A.4 Combustão (Wiebe)

- 🟡 Fração queimada: `x_b(θ) = 1 − exp(−a · ((θ − θ0)/Δθ)^(m+1))`, `a = 5`, `m = 2`, para θ0 ≤ θ ≤ θ0 + Δθ.
- 🟡 Início: `θ0 = −advance + Δθ_id`, `Δθ_id = 4° · (rpm/3000)^0,5` (atraso de inflamação).
- 🟡 Duração: `Δθ = Δθ_ref · (rpm / rpm_ref)^0,37 · (S_L,ref / S_L)^0,5 · (1 + 2,2 · x_r)`, `Δθ_ref = 55°` e `rpm_ref = 3000` (padrão; o catálogo pode sobrepor por motor).
- 🟡 Velocidade laminar (Metghalchi-Keck): `S_L = S_L0 · (T_u/298)^α · (p/101,325)^β · (1 − 2,1 · x_r)`, `S_L0 = B_m + B_φ · (φ − φ_m)²`, `φ = 1/λ`, `α = 2,18 − 0,8 · (φ − 1)`, `β = −0,16 + 0,22 · (φ − 1)`. Gasolina: `B_m = 0,305 m/s`, `B_φ = −0,549 m/s`, `φ_m = 1,21`. Etanol (inferido, a validar): `B_m = 0,465`, `B_φ = −1,0`, `φ_m = 1,10`. Misturas: interpolação linear pela fração mássica de etanol.
- 🟡 Calor libertado: `dQ_c/dθ = η_c · Q_disp · dx_b/dθ`, `Q_disp = min(m_fuel, m_air / AFR_st) · PCI`, `η_c = 0,98` para 0,55 ≤ λ ≤ 1,6.
- 🟡 Combustível não queimado (λ < 1, misfire ou combustão após EVO) vai para o escape como energia química disponível para pós-combustão.

### A.5 Ciclo fechado (zona única) e Woschni

- 🟡 Equação de pressão: `dp/dθ = ((γ − 1)/V) · (dQ_c/dθ − dQ_w/dθ) − γ · (p/V) · dV/dθ` (integrada com Heun a 1°, IVC → EVO).
- 🟡 γ variável: `γ(T) = 1,392 − 8,13·10⁻⁵ · T` (T em K), saturado em [1,20; 1,40].
- 🟡 Temperatura: `T = p · V / (m · R_mix)`, `m = m_air + m_fuel + m_res`, `R_mix = 287 J/(kg·K)`.
- 🟡 Condições no IVC: `p_ivc = p_man`, `T_ivc = (m_air · T_man + m_res · T_res) / (m_air + m_res) − ΔT_evap`, `T_res = 1000 K`.
- 🟡 Woschni: `h = 3,26 · B^(−0,2) · p^0,8 · T^(−0,55) · w^0,8` (W/(m²·K); B em m, p em kPa, T em K).
- 🟡 Velocidade característica: `w = C1 · S̄p + C2 · (V_d,cyl · T_ivc / (p_ivc · V_ivc)) · (p − p_mot)`, `C1 = 2,28`, `C2 = 0` na compressão e `3,24·10⁻³ m/(s·K)` na combustão/expansão; `p_mot` = pressão motorizada (politrópica 1,30 a partir do IVC).
- 🟡 Calor para a parede: `dQ_w/dθ = h · A_w · (T − T_wall) · dt_deg`, `T_wall = ECT + 80 K`.
- 🟡 Temperatura da zona não queimada (gancho de Livengood-Wu): `T_u(θ) = T_ivc · (p(θ)/p_ivc)^((γ_u − 1)/γ_u)`, `γ_u = γ(T_u)` avaliado no passo anterior.
- 🟡 Força de pico na biela: `F_rod = (p_max − p_cárter) · (π/4) · B² − m_recip · a · ω² · (1 + a/l)`, `p_cárter = 100 kPa`.

### A.6 Trabalho, atrito e torque

- 🟡 IMEP bruto: `IMEP_g = (∮_{IVC}^{EVO} p dV) / V_d,cyl` (kPa).
- 🟡 Perda de bombagem: `PMEP = p_exh − p_man` (kPa; negativo = ganho com boost acima da contrapressão).
- 🟡 Chen-Flynn: `FMEP = C_cf + A_cf · p_max + B_cf · S̄p + Q_cf · S̄p²` (bar internamente, convertido para kPa), padrões inferidos `C_cf = 0,25 bar`, `A_cf = 0,005`, `B_cf = 0,09 bar·s/m`, `Q_cf = 0,0009 bar·s²/m²`, com sobreposição pelo catálogo.
- 🟡 Torque de freio: `T_b = (IMEP_g − PMEP − FMEP) · 1000 · V_d / (4π) − P_sc · 1000 / ω` (N·m), V_d total em m³, P_sc em kW.
- 🟡 Potência: `P = T_b · ω / 1000` (kW), `ω = 2π · rpm / 60`.
- 🟡 Potência na roda: `P_wheel = P · η_drv − P_fixa` (kW); `whp = P_wheel / 0,7457`.

### A.7 Escape e EGT

- 🟡 Temperatura no EVO pela solução do ciclo; expansão de blowdown: `T_bd = T_evo · (p_exh / p_evo)^((γ − 1)/γ)`.
- 🟡 Pós-combustão: `ΔT_ab = η_ab · Q_quim,esc / (m_exh · c_p,exh)`, `η_ab = 0,6` se houver O2 disponível (λ_col > 1 ou ar do antilag), senão 0; `c_p,exh = 1,20 kJ/(kg·K)`.
- 🟡 Perda na porta: `T_port = T_wall,port + (T_bd + ΔT_ab − T_wall,port) · ε_port`, `ε_port = 0,92`.
- 🟡 EGT do coletor: média ponderada por massa com inércia térmica de 1ª ordem `τ_col = 0,3 s`; o termopar aplica `τ = egt_thermocouple_tau_s`.
- 🟡 Verificação: `Q_fuel = W_i + Q_w + H_exh` com erro ≤ 2 % por ciclo (RNF-04).

### A.8 Turbo

- 🟡 Eixo: `J · ω_t · dω_t/dt = P_turb − P_comp − P_fric`, `P_fric = k_f · ω_t²`.
- 🟡 Compressor: `P_comp = ṁ_c · c_p,ar · T_01 · (PR^((γ−1)/γ) − 1) / η_c`; saída `T_02 = T_01 · (1 + (PR^((γ−1)/γ) − 1)/η_c)`.
- 🟡 Mapa simplificado: linha de velocidade elíptica `ṁ_corr = ṁ_choke(N) · sqrt(1 − ((PR − 1)/(PR_0(N) − 1))²)`, `PR_0(N) = 1 + (PR_design − 1) · (N_corr/N_design)²`, `ṁ_choke(N) = ṁ_choke,max · (N_corr/N_max)^0,8`; eficiência `η_c = η_max · (1 − k1 · ((ṁ_corr − ṁ_pk)/ṁ_range)² − k2 · ((N_corr − N_pk)/N_max)²)` saturada em [0,45; η_max]; o catálogo pode fornecer mapa tabelado que substitui a forma paramétrica.
- 🟡 Turbina como bocal: `ṁ_t = A_t,eff · 1000 · p_03 / sqrt(R_exh · T_03) · Ψ(p_04/p_03)`; `P_turb = ṁ_t · c_p,exh · T_03 · η_t · (1 − (p_04/p_03)^((γ_e−1)/γ_e))`, `γ_e = 1,33`, `η_t` tabelado por PR_t.
- 🟡 Wastegate: `p_act = p_boost · (1 − duty/100)` (relativa); `x_wg = clip((p_act − p_spring)/Δp_full, 0, 1)` com 1ª ordem τ 50 ms; `A_wg = A_wg,max · x_wg`.
- 🟡 Intercooler: `T_ic,out = T_02 − ε · (T_02 − T_amb)`, `ε` do catálogo (padrão 0,75); `Δp_ic = k_ic · ṁ_c²` (kPa).

### A.9 Supercharger (deslocamento positivo)

- 🟡 Rotação: `N_sc = rpm · pulley_ratio`.
- 🟡 Vazão: `ṁ_sc = ρ_in · V_disp,rev · N_sc / 60 · η_v`, `η_v = 1 − k_leak · (PR − 1) · N_ref / N_sc`, saturado em [0,5; 0,98].
- 🟡 Saída: `T_out = T_in · (1 + (PR^((γ−1)/γ) − 1)/η_ad)`; `η_ad` tabelado por PR e tipo (Roots ≈ 0,55; twin-screw ≈ 0,70, inferidos).
- 🟡 Perda parasita: `P_sc = ṁ_sc · c_p,ar · (T_out − T_in) / η_mech` (kW), `η_mech = 0,90`; com bypass aberto `PR → 1,02`.
- 🟡 Posição da borboleta: com `EngineSpec.throttle_location = "pre_compressor"` (padrão do `muscle-v8-sc`) a borboleta alimenta o compressor, o coletor de admissão recebe `ṁ_sc` e o volume de boost coincide com o coletor; com `"post_compressor"` vale o arranjo do Apêndice A.2.

### A.10 Sensores

- 🟡 Filtro de 1ª ordem discreto: `y_k = y_{k−1} + (1 − exp(−dt/τ)) · (x_k − y_{k−1})`.
- 🟡 Wideband: atraso de transporte `t_tr = 0,02 s + 2 · 60 / rpm` aplicado por fila circular de ticks, depois τ = 0,1 s, depois ruído σ = 0,005, saturação [0,5; 2,0].
- 🟡 Knock: `knock_sensor_v = clip(0,05 V + 1,5 V · intensity + ruído(σ 0,02 V); 0,0 V; 5,0 V)`, com `intensity` vindo de `KnockSignal.intensity`.
- 🟡 Índice normalizado (revisão R1): `knock_intensity = clip((knock_sensor_v − 0,05 V) / (5,0 V − 0,05 V); 0,0; 1,0)`, calculado por cilindro no mesmo tick. O barramento físico publica os dois campos; o `ecu-core` consome só `knock_intensity`.

### A.11 Combustíveis (valores lidos do catálogo; resumo para os testes)

| Combustível | AFR_st | PCI (MJ/kg) | RON / MON | h_fg (kJ/kg) | ρ (kg/m³) |
|---|---|---|---|---|---|
| 🟡 `e27` (gasolina comum BR) | 13,2 | 38,7 | 94 / 82 (inferido) | 512 | 745 |
| 🟡 `e100` (etanol) | 9,0 | 26,8 | 109 / 90 (inferido) | 920 | 789 |
| 🟡 `podium` (competição, E0) | 14,4 | 42,9 | 102 / 88 (inferido) | 340 | 755 |
| 🟡 `e0` (gasolina pura) | 14,7 | 43,4 | 95 / 85 | 350 | 740 |

### Referências
- 🟡 Heywood, J. B. Internal Combustion Engine Fundamentals (Wiebe, γ(T), single-zone, MBT).
- 🟡 Woschni (1967), correlação de transferência de calor; Chen e Flynn (1965), modelo de atrito.
- 🟡 Aquino (1981), modelo tau-X de filme de combustível; Metghalchi e Keck (1982), velocidade laminar.
- 🟡 `_reversa_sdd/prd.md` seções 3, 4, 7, 8 e 9; `/tmp/simremap-conventions.md` seções 3, 4, 5 e 9.

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
