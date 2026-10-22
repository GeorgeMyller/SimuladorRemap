# Personas e Jornadas

> Selo 🟡 PLANEJADO em todos os itens.

## Persona 1: Lucas, aluno de preparação e entusiasta de remap OEM
- **Perfil:** 🟡 Estudante de cursos de tuning. Quer aprender Stage 1, Stage 2 e pops & bangs em ECUs originais (OEM). Não tem carro próprio nem acesso a dinamômetro.
- **Contexto:** 🟡 Estuda em casa, no computador, as aulas teóricas de remap: mapas de torque, lambda alvo, avanço de ignição e controle de wastegate. Fica bloqueado porque não consegue testar o efeito real das alterações nem ver o motor no dinamômetro.
- **Nível técnico:** 🟡 Iniciante em calibração prática. Conhece a teoria básica (AFR/lambda, ponto de ignição, pressão de turbo). Nunca operou um dinamômetro real nem diagnosticou knock num datalogger.
- **Dor principal:** 🟡 Não tem onde treinar com segurança. Um erro de mistura (lambda pobre) ou de avanço (detonação) num carro real quebra o motor e causa um prejuízo alto.
- **Objetivo final:** 🟡 Ganhar segurança técnica e um portfólio prático de acertos bem-sucedidos. Assim, começa a trabalhar numa oficina de remap sem quebrar o motor do primeiro cliente.

### Jornada principal
1. 🟡 Fazer a puxada base (baseline pull) de um carro turbo OEM (ex.: hot hatch 2.0 TSI) e registrar as curvas originais de potência, torque, AFR e EGT.
2. 🟡 Editar na ECU OEM a pressão alvo de boost e o avanço de ignição, de forma exagerada.
3. 🟡 Executar nova puxada, receber o alerta de knock severo e ver o motor quebrar (pistão furado, biela torta), com laudo forense da causa termodinâmica.
4. 🟡 Restaurar o motor, analisar o datalogger da quebra, enriquecer o lambda em alta carga e reduzir o avanço nos cilindros críticos.
5. 🟡 Configurar a estratégia de overrun (atraso de ignição e corte de injeção atrasado) para pops & bangs seguros, com controle da EGT da turbina.
6. 🟡 Validar na puxada final um ganho estável de +65 whp, sem knock e com EGT dentro do limite térmico.

---

## Persona 2: Rodrigo, preparador intermediário em transição para ECU standalone
- **Perfil:** 🟡 Mecânico e preparador de oficina. Já faz remaps básicos por OBD. Precisa dominar a troca da ECU original por injeções programáveis (estilo FuelTech, MoTeC, Haltech) para projetos de pista e de rua forte.
- **Contexto:** 🟡 Está na oficina planejando projetos turbo forjados ou aspirados de alta rotação. Precisa treinar o acerto do zero antes de ligar o carro real do cliente no rolo: mapa base de VE, malha fechada com sonda wideband, compensações por temperatura, two-step/antilag e proteções de motor.
- **Nível técnico:** 🟡 Intermediário a avançado em mecânica automotiva. Intermediário em eletrônica e calibração. Tem receio de errar configurações avançadas de ECU standalone: tabelas 3D de VE, controle PID de boost e cortes de segurança.
- **Dor principal:** 🟡 Errar a configuração de uma ECU standalone no carro do cliente quebra um motor caro. O tempo de dinamômetro para aprender também custa caro.
- **Objetivo final:** 🟡 Dominar o fluxo completo de instalação lógica e de calibração fina de ECUs programáveis. Assim, ele oferece projetos de alta potência lucrativos e confiáveis.

### Jornada principal
1. 🟡 Escolher um carro de projeto (ex.: coupé 6 cilindros turbo ou 4 cilindros forjado) e trocar a ECU OEM por uma ECU standalone (perfil estilo FuelTech FT600, MoTeC M1 ou Haltech Elite).
2. 🟡 Configurar os parâmetros vitais da ECU: roda fônica, bicos injetores, combustível (etanol, gasolina, Podium), sensores MAP/IAT/ECT e limites de proteção (engine failsafe).
3. 🟡 Construir o mapa de VE e a tabela de lambda alvo, com carga estacionária (steady-state hold), varredura (sweep pull) e correção em malha fechada.
4. 🟡 Mapear célula por célula a tabela 3D de avanço até o MBT (Minimum Spark Advance for Best Torque), monitorando o espectrograma de knock e a pressão no cilindro.
5. 🟡 Ativar os recursos de competição: two-step (launch control com atraso de ponto e enriquecimento), powershift e controle eletrônico de boost por marcha.
6. 🟡 Validar o mapa completo em várias puxadas seguidas, com repetibilidade térmica, sem falha mecânica e com a meta de potência máxima atingida.

---

## Persona 3: Prof. Marcos, instrutor de escola técnica de tuning e engenharia automotiva
- **Perfil:** 🟡 Professor de cursos presenciais e online de preparação de motores e injeção eletrônica. Precisa avaliar os alunos em cenários práticos padronizados.
- **Contexto:** 🟡 Dá aulas para turmas de 20 a 50 alunos. Tem apenas um dinamômetro físico, ou nenhum para os alunos EAD. Não pode deixar cada aluno errar e quebrar um motor real para aprender o limite físico da termodinâmica.
- **Nível técnico:** 🟡 Avançado em termodinâmica de motores de combustão interna, dinâmica veicular e estratégias de gerenciamento eletrônico (OEM e motorsport).
- **Dor principal:** 🟡 Não consegue dar prática real e avaliável a toda a turma: o dinamômetro é único e quebrar motores tem um custo proibitivo.
- **Objetivo final:** 🟡 Ensinar com rigor científico a relação entre calibração eletrônica e física do motor. Avaliar os alunos com desafios práticos reproduzíveis e telemetria detalhada.

### Jornada principal
1. 🟡 Selecionar um cenário de desafio (ex.: defeito oculto na bomba de combustível, ou 400 whp com gasolina comum sem passar dos 900 °C de EGT).
2. 🟡 Demonstrar ao vivo como cada tabela (injeção, ignição, comando variável, wastegate) altera em tempo real a combustão e os gráficos do dinamômetro.
3. 🟡 Provocar uma falha catastrófica (ex.: pré-ignição por IAT alta e avanço excessivo) e mostrar no datalogger e na autópsia mecânica os sinais anteriores à quebra.
4. 🟡 Exportar e comparar os logs de telemetria (curvas sobrepostas antes vs. depois) para comprovar o ganho de eficiência e de segurança.
5. 🟡 Validar a aprovação do aluno pelos critérios objetivos do simulador: meta de torque/potência, margem de segurança de knock e integridade de 100 % dos componentes internos.

---
Gerado por reversa-researcher em 2026-10-18T00:23:13+01:00
Fonte: ideation.md
