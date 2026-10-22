# Ideation, SimuladorRemap

> Selo 🟡 PLANEJADO em todos os itens, sujeito a validação.

## Brief original
Criar um simulador e plataforma de treinamento de remap automotivo em dinamômetro com física termodinâmica e mecânica real. O sistema deve conter múltiplas opções de carros, permitir leitura e edição completa de parâmetros de ECU OEM e substituição por ECUs programáveis standalone (FuelTech, MoTeC, Haltech). O usuário deve ajustar mapas de injeção (VE/lambda), tabelas de ignição (avanço de ponto), controle de boost, limitadores de rotação, two-step e pops & bangs (overrun fuel cut/ignition retard). O motor deve responder com ganho real de potência e torque ou sofrer falhas mecânicas catastróficas (detonação/knock, pré-ignição, excesso de EGT, quebra de biela/pistão, derretimento de turbina) se calibrado incorretamente.

## Problema
🟡 Aprender calibração de ECU e remap na prática exige três recursos caros: um carro real, um dinamômetro de rolo ou de bancada (custo alto por hora de máquina) e a aceitação de risco financeiro extremo.
🟡 O risco principal é quebrar o motor (bielas, pistões, turbinas) por erro de mistura (lambda pobre) ou por avanço de ignição excessivo (detonação, pré-ignição).
🟡 Quem sente o problema: alunos de engenharia automotiva, entusiastas e preparadores iniciantes.
🟡 Quando sente: no momento em que precisam treinar antes de mexer em carros reais e não têm um ambiente seguro para isso.

## Valor entregue
🟡 O usuário calibra mapas reais de ECU (OEM e programáveis no estilo FuelTech, MoTeC e Haltech) num dinamômetro virtual com física termodinâmica 1D/0D precisa.
🟡 Com isso, extrai potência real, configura pops & bangs, two-step e controle de boost, ou vive quebras mecânicas realistas sem custo financeiro.

## Alternativas existentes
🟡 **Softwares oficiais de ECU (FTManager, MoTeC i2/M1 Tune, NSP, WinOLS):** têm modo offline para editar tabelas. Não chegam porque não simulam o motor em funcionamento. Também não dão resposta de dinamômetro, sonda wideband, knock ou EGT em tempo real.
🟡 **Jogos (Automation, BeamNG):** focam em construção genérica de motor ou em condução. Não chegam porque não oferecem:
- programação completa de malha fechada;
- tabelas 3D de VE e de ignição;
- correções por cilindro;
- estratégias de overrun (pops & bangs) e antilag;
- troca de ECU OEM por standalone.

## Público-alvo (bruto)
🟡 Estudantes de preparação automotiva, tuners iniciantes e intermediários, escolas técnicas de tuning e entusiastas de performance. O objetivo comum é dominar o remap de ECUs OEM e o acerto de injeções programáveis.

## Métricas de sucesso
🟡 **Precisão da física:** desvio máximo < 5 % nas curvas de torque, potência, lambda e EGT, comparadas com motores reais documentados em dinamômetro. Alvo: < 5 %, em 3 meses.
🟡 **Taxa de conclusão dos cenários de treino:** ≥ 80 % de conclusão. Cenários citados:
- Stage 1 OEM;
- Stage 2 com pops & bangs;
- swap de ECU standalone, com acerto do zero até o limite seguro de knock.

## Premissas a validar
🟡 **(a) Física em tempo real:** o modelo físico-matemático corre em tempo real no navegador ou no desktop, sem lag. O modelo inclui eficiência volumétrica, velocidade de chama, limiar de detonação (octanagem, IAT, pressão no cilindro) e energia de escape para o turbo. Mesmo assim, o modelo pune erros reais de acerto com danos mecânicos coerentes.
🟡 **(b) Interfaces sem infração:** a interface reproduz a experiência mental e técnica da FuelTech, da MoTeC, da Haltech e do remap OEM. Não infringe marcas registradas nem usa código proprietário. A solução prevista são arquiteturas inspiradas ou perfis equivalentes.
🟡 **(c) Telemetria explicativa:** a complexidade de uma ECU real vem acompanhada de telemetria clara (datalogger, diagnóstico de quebra). Assim, o usuário entende exatamente por que o motor quebrou ou ganhou potência.

## Notas
🟡 Fidelidade física declarada: modelo termodinâmico 1D/0D.
🟡 Plataforma de execução em aberto: "navegador/desktop". A escolha fica para o PRD e para as specs.
🟡 Fonte dos dados de referência para a métrica de < 5 %: literatura técnica aberta de motores de combustão interna (Heywood) e folhas públicas de dinamômetro de referência, para validar a física 0D/1D. (Resolvido na etapa researcher.)
🟡 Catálogo inicial do MVP: 4 carros que cobrem as arquiteturas clássicas de tuning. (Resolvido na etapa researcher.)
1. Hatch 2.0 turbo, injeção direta, OEM moderno.
2. Sedã/coupé 6 cilindros em linha 3.0 turbo, preparado.
3. Hatch/sedã 1.8/2.0 4 cilindros turbo clássico, para swap FuelTech.
4. Esportivo V8 aspirado/supercharged.
🟡 Os três cenários de treino citados (Stage 1 OEM, Stage 2 com pops & bangs, swap standalone) são candidatos naturais ao MVP.
🟡 Modos de falha a modelar, segundo o brief: detonação/knock, pré-ignição, excesso de EGT, quebra de biela ou pistão, derretimento da turbina.

---
Gerado por reversa-ideator em 2026-10-18T00:21:42+01:00
Fonte: newproject-brief.md
