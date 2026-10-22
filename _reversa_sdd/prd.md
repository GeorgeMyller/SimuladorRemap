# PRD: SimuladorRemap

> Selo 🟡 PLANEJADO. Documento gerado a partir de ideation + personas.

**Versão:** 1.2
**Data:** 2026-10-18T00:25:39+01:00
**Autor:** reversa-drafter
**Status:** rascunho

---

## 1. Problema

🟡 Aprender calibração de ECU e remap na prática exige três recursos caros: um carro real, um dinamômetro de rolo ou de bancada (custo alto por hora de máquina) e a aceitação de risco financeiro extremo.

🟡 O risco principal é quebrar o motor (bielas, pistões, turbinas) por erro de mistura (lambda pobre) ou por avanço de ignição excessivo (detonação, pré-ignição).

🟡 As ferramentas atuais não fecham essa lacuna:
- Os softwares oficiais de ECU (FTManager, MoTeC i2/M1 Tune, NSP, WinOLS) editam tabelas offline, mas não simulam o motor nem dão resposta de dinamômetro, wideband, knock ou EGT em tempo real.
- Os jogos (Automation, BeamNG) não oferecem programação completa de ECU: malha fechada, tabelas 3D de VE e ignição, correções por cilindro, overrun, antilag e swap OEM → standalone.

### Quem sente
- 🟡 **Alunos de preparação e entusiastas de remap OEM:** sentem o problema ao estudar a teoria em casa, sem carro nem dinamômetro para testar o efeito das alterações.
- 🟡 **Preparadores intermediários:** sentem o problema antes de ligar o carro do cliente no rolo, quando precisam acertar do zero uma ECU standalone sem margem para erro.
- 🟡 **Instrutores de escolas técnicas:** sentem o problema ao dar aulas para turmas de 20 a 50 alunos com um único dinamômetro físico, ou nenhum no EAD.

---

## 2. Personas-alvo

🟡 Referência completa em [`personas.md`](./personas.md). Resumo:

- **Lucas, aluno de preparação e entusiasta de remap OEM:** 🟡 iniciante em calibração prática. Quer aprender Stage 1, Stage 2 e pops & bangs em ECU OEM. Dor: não tem onde treinar sem risco de quebrar um motor.
- **Rodrigo, preparador intermediário em transição para standalone:** 🟡 domina mecânica, é intermediário em calibração. Dor: errar a configuração de uma ECU standalone (VE 3D, PID de boost, cortes de segurança) no carro do cliente.
- **Prof. Marcos, instrutor de escola técnica:** 🟡 avançado em termodinâmica e gerenciamento eletrônico. Dor: não consegue dar prática real e avaliável a toda a turma.

---

## 3. Métricas de sucesso

🟡 As métricas vêm do `ideation.md` e das restrições técnicas indicadas na etapa drafter.

| Métrica | Unidade | Alvo | Prazo |
|---|---|---|---|
| 🟡 Desvio da curva de torque simulada face ao benchmark canônico `Reference Benchmark Baseline v1` | % (desvio máximo por ponto de RPM) | < 5 % | 🟡 3 meses após o início |
| 🟡 Desvio da curva de potência simulada face ao `Reference Benchmark Baseline v1` | % | < 5 % | 🟡 3 meses |
| 🟡 Desvio do lambda simulado face ao `Reference Benchmark Baseline v1` | % | < 5 % | 🟡 3 meses |
| 🟡 Desvio da EGT simulada face ao `Reference Benchmark Baseline v1` | % | < 5 % | 🟡 3 meses |
| 🟡 Taxa de conclusão dos cenários de treino (Stage 1 OEM, Stage 2 com pops & bangs, swap standalone até o limite seguro de knock) | % de sessões iniciadas que terminam aprovadas | ≥ 80 % | 🟡 3 meses |
| 🟡 Frequência do loop determinístico de simulação física | Hz | mínimo 100 Hz, alvo até 1000 Hz | 🟡 MVP |
| 🟡 Taxa de frames de telemetria enviados à UI | FPS | 30 a 60 FPS | 🟡 MVP |
| 🟡 Hardware de referência sem degradação das duas métricas acima | configuração | CPU 4 núcleos, 8 GB RAM, sem GPU dedicada | 🟡 MVP |

---

## 4. Escopo (in)

🟡 Itens derivados do brief, do `ideation.md`, das jornadas das personas e das respostas da etapa drafter.

**Catálogo de veículos (4 carros, ciclo Otto)**
- 🟡 Hatch 2.0 turbo, injeção direta, OEM moderno (cenário Stage 1 / Stage 2 OEM).
- 🟡 Sedã/coupé 6 cilindros em linha 3.0 turbo, preparado.
- 🟡 Hatch/sedã 1.8/2.0 4 cilindros turbo clássico, para swap standalone.
- 🟡 Esportivo V8 aspirado/supercharged.

**Motor físico**
- 🟡 Modelo termodinâmico 0D/1D: eficiência volumétrica, combustão e velocidade de chama, torque, lambda, EGT.
- 🟡 Modelo de sobrealimentação: energia de escape para turbo (spool), wastegate, supercharger.
- 🟡 Limiar de detonação em função de octanagem, IAT e pressão no cilindro; pré-ignição.
- 🟡 Combustíveis: gasolina comum, etanol e gasolina de competição (Podium).
- 🟡 Loop determinístico de 100 a 1000 Hz.

**Falhas mecânicas e diagnóstico**
- 🟡 Modos de falha: detonação/knock, pré-ignição, excesso de EGT, quebra de biela, furo de pistão, derretimento da turbina.
- 🟡 Laudo forense (autópsia mecânica) com a causa termodinâmica da quebra.
- 🟡 Restauração do motor após a quebra.

**Dinamômetro virtual**
- 🟡 Puxada base (baseline pull), varredura (sweep pull), carga estacionária (steady-state hold) e várias puxadas seguidas.
- 🟡 Curvas de potência (whp), torque, AFR/lambda e EGT; sobreposição antes vs. depois.

**ECU**
- 🟡 Perfil OEM genérico **"OEM-Stage"**, com lógica baseada em torque e carga.
- 🟡 Perfis standalone genéricos: **"FT-Pro"** (inspirado na lógica FuelTech FT600/FT550), **"M1-Race"** (inspirado na MoTeC M1) e **"HT-Elite"** (inspirado na Haltech Elite/Nexus).
- 🟡 Troca (swap) da ECU OEM por uma ECU standalone.
- 🟡 Configuração base standalone: roda fônica, bicos injetores, combustível, sensores MAP/IAT/ECT, proteções (engine failsafe).
- 🟡 Tabelas e estratégias: VE, lambda alvo, avanço de ignição 3D, correções por cilindro, compensações por temperatura, malha fechada com wideband, controle de boost (PID e por marcha), wastegate, comando variável, limitador de rotação, two-step/launch control, antilag, powershift, overrun (pops & bangs: corte de injeção atrasado e atraso de ignição).

**Telemetria**
- 🟡 Streaming de telemetria em tempo real para a UI.
- 🟡 Datalogger, espectrograma de knock, pressão no cilindro, gauges.
- 🟡 Exportação e importação de datalogs e cenários em JSON/CSV.

**Treino e avaliação**
- 🟡 Cenários de treino: Stage 1 OEM, Stage 2 com pops & bangs, swap standalone até o limite seguro de knock.
- 🟡 Desafios do instrutor, incluindo defeitos ocultos (ex.: bomba de combustível) e metas com limites (ex.: 400 whp com gasolina comum e EGT ≤ 900 °C).
- 🟡 Critérios objetivos de aprovação: meta de torque/potência, margem de segurança de knock, integridade de 100 % dos componentes internos.
- 🟡 Perfis locais de aluno e de instrutor (só nickname, sem PII).
- 🟡 Pacotes de desafio e de telemetria exportáveis e importáveis, com hash SHA-256 no JSON.

**Apresentação**
- 🟡 Bancada do dinamômetro com visualização animada do carro/motor no rolo.
- 🟡 Efeitos visuais e sonoros: RPM, spool do turbo, pops & bangs, explosão/quebra.
- 🟡 Editor de tabelas 2D/3D (incluindo tabelas 16x16).

**Plataforma**
- 🟡 Aplicação web para navegador desktop (Windows/macOS/Linux), local-first, empacotada em Docker. Um container por estação/aluno.
- 🟡 Persistência de carros, mapas, logs de puxadas e desafios.

---

## 5. Não-objetivos (out)

- 🟡 Condução do veículo em pista ou estrada, e física de pneus/suspensão fora do rolo do dinamômetro.
- 🟡 Multijogador síncrono em tempo real.
- 🟡 Ligação física (USB/CAN/OBD2) a ECUs ou veículos reais.
- 🟡 Leitura ou gravação de arquivos binários proprietários ou criptografados (.bin OEM bruto, .ftm, .m1).
- 🟡 Motores diesel, rotativos (Wankel), elétricos ou híbridos. O MVP cobre só o ciclo Otto aspirado, turbo e supercharged.
- 🟡 Aplicação nativa iOS/Android para telas pequenos.
- 🟡 Uso de marcas registradas, logotipos ou código proprietário de FuelTech, MoTeC, Haltech ou de fabricantes de ECUs OEM.
- 🟡 Licenças de software proprietário.

---

## 6. Restrições

| Tipo | Descrição |
|---|---|
| 🟡 Técnica (plataforma) | 🟡 Aplicação web para navegador desktop, empacotada em Docker com paridade total dev/staging/prod. Funciona local-first (offline, container ou servidor local). |
| 🟡 Técnica (backend) | 🟡 Python 3.12+ gerenciado só com `uv` e `pyproject.toml`. FastAPI (REST + WebSockets/asyncio). Pydantic v2 para contratos e mapas. SQLModel/SQLAlchemy async + Alembic. SQLite ou PostgreSQL. Redis opcional para cache de sessão. |
| 🟡 Técnica (qualidade) | 🟡 `ruff`, `mypy --strict`, `pytest` + `pytest-cov` e `bandit`. |
| 🟡 Técnica (frontend) | 🟡 React + TypeScript (Vite ou Next.js), Tailwind CSS. Gráficos de alta performance em Canvas/WebGL. |
| 🟡 Técnica (desempenho) | 🟡 Loop físico determinístico ≥ 100 Hz (alvo até 1000 Hz). Telemetria à UI a 30–60 FPS. Hardware de referência: CPU 4 núcleos, 8 GB RAM, sem GPU dedicada. |
| 🟡 Técnica (dados) | 🟡 Importação e exportação de cenários e datalogs em JSON/CSV. |
| 🟡 Compliance (marcas) | 🟡 Perfis de ECU com nomes genéricos (FT-Pro, M1-Race, HT-Elite, OEM-Stage). As funcionalidades são reais; marcas e código proprietário não são usados. |
| 🟡 Compliance (dados pessoais) | 🟡 Zero coleta de PII. Os perfis locais usam só um nickname ou identificador local, sem dados pessoais reais. Por isso, não há armazenamento de dados sensíveis sob LGPD/RGPD. A exportação de logs é puramente técnica (JSON/CSV). |
| 🟡 Prazo | 🟡 MVP em 4 semanas, divididas em 4 sprints de 1 semana. Escopo enxuto e modular. |
| 🟡 Orçamento | 🟡 Custo zero em licenças; stack 100 % open-source. |

### Decisões de integração (revisão R1, 2026-10-18)

- 🟡 **Sinal de knock:** a física publica `knock_sensor_v` (0,0–5,0 V) e o índice normalizado `knock_intensity` (0,0–1,0) derivado dele; a ECU consome `knock_intensity`; a telemetria transmite os dois.
- 🟡 **Nomes de campos:** `lambda_measured` e `injector_pw_ms` em todas as specs.
- 🟡 **Códigos de erro:** `ECU_PROFILE_NOT_FOUND` (perfil inexistente) e `SIM_CAPACITY_EXCEEDED` (limite de sessões).
- 🟡 **WebSocket:** todo envelope do servidor, incluindo `error`, recebe `seq` + 1; o `seq` nunca se repete.
- 🟡 **Endpoints:** todos os endpoints REST usam o prefixo `/api/v1/`, com catálogo consolidado na spec `platform-foundation`.
- 🟡 **Perfil OEM:** nome genérico `OEM-Stage`, sem referência a marcas registradas.
- 🟡 **Benchmark:** `Reference Benchmark Baseline v1` é a referência canônica do desvio < 5 %.


---

## 7. Dependências externas

- 🟡 **Dados de referência física:** literatura técnica aberta de motores de combustão interna (Heywood).
- 🟡 **Dados de validação:** os datasets base dos 4 veículos abaixo formam o benchmark canônico oficial do simulador, **`Reference Benchmark Baseline v1`**, usado para a verificação determinística do desvio < 5 %. Os perfis do simulador são inspirados nestas arquiteturas, sem uso de marcas.
  1. 🟡 **Hatch 2.0 turbo GDI OEM** (inspirado no EA888 Gen3 2.0 TSI): 1984 cc, 4 cilindros, taxa 9,6:1, turbo IS20, 220 whp / 350 Nm de série, limite da biela de série ~420 Nm, limite de EGT 950 °C.
  2. 🟡 **Coupé 6 cilindros em linha 3.0 turbo** (inspirado no B58 / 2JZ-GTE): 2998 cc, taxa 10,2:1 / 8,5:1, single turbo, 340 whp de série, internos forjados até 750 whp, limite de EGT 980 °C.
  3. 🟡 **Clássico 2.0 8v/16v turbo para swap standalone FT-Pro** (inspirado no AP 2.0 turbo / 4 cilindros forjado): 1984 cc, taxa 8,5:1, turbina .50/.63, bicos de alta vazão, etanol E100, 300 a 600 whp.
  4. 🟡 **Muscle V8 supercharged** (inspirado no Coyote/LS 5,0 L): 4951 cc, 8 cilindros em V, compressor Roots/twin-screw, 460 whp de série, até 800 whp.
- 🟡 **Ecossistema open-source:** Docker, Python/uv, FastAPI, Pydantic, SQLModel/SQLAlchemy, Alembic, React, Tailwind, bibliotecas de gráficos Canvas/WebGL.
- 🟡 **Redis:** opcional.
- 🟡 Nenhuma API ou serviço online obrigatório. O produto é local-first.

---

## 8. Riscos

| Risco | Impacto | Probabilidade | Mitigação proposta |
|---|---|---|---|
| 🟡 O loop físico em Python não chega a 100–1000 Hz no hardware de referência, com a telemetria simultânea | 🟡 alto | 🟡 média | 🟡 Separar o loop físico de passo fixo do loop de I/O asyncio. Vetorizar o cálculo. Medir com benchmark desde o primeiro componente. Fixar 100 Hz como mínimo de aceite. |
| 🟡 Os dados públicos não chegam para validar o desvio < 5 %, sobretudo de lambda e EGT (as folhas de dyno públicas raramente os trazem) | 🟡 alto | 🟡 alta | 🟡 Escolher cedo os motores de referência com dados completos. Separar a métrica por grandeza e documentar a fonte de cada curva. |
| 🟡 O modelo 0D/1D pune erros de forma incoerente (quebra sem causa clara ou erro grave sem consequência) | 🟡 alto | 🟡 média | 🟡 Testes de cenário determinísticos por modo de falha. Laudo forense ligado às variáveis que provocaram o dano. |
| 🟡 A interface ou os nomes dos perfis infringem marcas registradas ou trade dress | 🟡 alto | 🟡 baixa | 🟡 Nomes genéricos já definidos. Layout próprio, sem logotipos nem cópia visual. Revisão antes do lançamento. |
| 🟡 A complexidade da ECU sem telemetria clara impede o usuário de entender a causa do ganho ou da quebra | 🟡 alto | 🟡 média | 🟡 Datalogger, espectrograma de knock e autópsia com explicação causal. Medir pela taxa de conclusão dos cenários. |
| 🟡 O escopo (4 carros, 4 perfis de ECU, falhas, áudio, 3D) é grande para uma "entrega imediata" | 🟡 médio | 🟡 alta | 🟡 Entregar por fatias: primeiro 1 carro + perfil OEM + dyno + falhas de knock/EGT; depois os restantes. |
| 🟡 A largura de banda do WebSocket a 60 FPS com muitos canais degrada a UI | 🟡 médio | 🟡 média | 🟡 Agregar e subamostrar no servidor; enviar só os canais visíveis. |
| 🟡 Avaliação de turmas (20–50 alunos) sem infraestrutura de rede | 🟡 médio | 🟡 média | 🟡 Um container Docker local-first por estação/aluno. Pacotes de desafio e de telemetria exportados e importados com hash SHA-256 no JSON, para o instrutor avaliar sem rede. |

---

## 9. Critérios de aceite (alto nível)

- 🟡 **Lucas (OEM):** **Dado** o hatch 2.0 turbo com a ECU OEM e a puxada base registrada, **Quando** o usuário aumenta o boost e o avanço de forma exagerada e executa a puxada, **Então** o simulador registra knock severo, aplica uma falha mecânica e mostra um laudo com a causa. Depois do acerto corrigido (lambda mais rico, menos avanço, overrun seguro), a puxada final mostra o ganho de potência sem knock e com EGT dentro do limite.
- 🟡 **Rodrigo (standalone):** **Dado** um carro de projeto com a ECU OEM, **Quando** o usuário troca para um perfil standalone, configura a base, constrói VE/lambda/ignição e ativa two-step e boost por marcha, **Então** o motor funciona com o novo mapa e várias puxadas seguidas mostram repetibilidade térmica, nenhuma falha mecânica e a meta de potência atingida.
- 🟡 **Prof. Marcos (instrutor):** **Dado** um desafio com meta e limites definidos (ex.: 400 whp, gasolina comum, EGT ≤ 900 °C), **Quando** um aluno submete o seu acerto, **Então** o simulador avalia a aprovação só por critérios objetivos (meta, margem de knock, integridade de 100 % dos componentes) e permite exportar os logs antes vs. depois.
- 🟡 **Física:** **Dado** um motor do catálogo com a calibração de referência, **Quando** se executa uma varredura completa no dinamômetro, **Então** as curvas de torque, potência, lambda e EGT ficam com desvio < 5 % face ao `Reference Benchmark Baseline v1`, com resultado idêntico em execuções repetidas.
- 🟡 **Desempenho:** **Dado** o hardware de referência (4 núcleos, 8 GB, sem GPU dedicada), **Quando** uma puxada roda com a UI aberta, **Então** o loop físico mantém ≥ 100 Hz e a UI recebe telemetria a ≥ 30 FPS.

---

## Pendências de cobertura

- 🟡 Nenhuma. As 4 pendências da versão anterior (prazo, dados pessoais, motores de referência, implantação em turma) foram resolvidas pelo usuário na etapa spec-sdd.

---

Gerado por reversa-drafter em 2026-10-18T00:25:39+01:00
Fontes: ideation.md, personas.md
Atualizado em 2026-10-18T00:27:28+01:00: pendências de cobertura resolvidas (versão 1.1).
