# Spec: ecu-tuning-ui

**Versão:** 1.1
**Status:** Rascunho
**Autor:** reversa-spec-sdd
**Data:** 2026-10-18
**Reviewers:** N/A
**Sprint:** 4 (componente 10)

---

## 1. Resumo

🟡 O `ecu-tuning-ui` é o software de ECU no navegador do SimuladorRemap. Ele mostra um espaço de trabalho com navegação própria para cada perfil (`oem-stage`, `ft-pro`, `m1-race`, `ht-elite`), editores de tabelas 2D/3D até 32×32, formulários de estratégias (boost, limitador, two-step, antilag, powershift, overrun, malha fechada, failsafe), o assistente de configuração base para swap standalone, o histórico de versões com diff célula a célula e avisos didáticos não bloqueantes. É onde Lucas faz o Stage 1/Stage 2 e onde Rodrigo constrói um mapa standalone do zero.

---

## 2. Contexto e Motivação

**Problema:**
🟡 Os softwares reais de ECU (FTManager, MoTeC M1 Tune, WinOLS) editam tabelas sem simular o motor (PRD §1). O simulador precisa de um editor com a mesma "experiência mental" desses softwares, sem trade dress, marcas ou código proprietário (PRD §6, premissa (b) do `ideation.md`).

**Evidências:**
- 🟡 PRD §4 (ECU): perfis OEM e standalone, swap, configuração base, tabelas VE, lambda alvo, ignição 3D, correções por cilindro, compensações, malha fechada, boost PID e por marcha, limitador, two-step, antilag, powershift, overrun.
- 🟡 PRD §4 (Apresentação): editor de tabelas 2D/3D, incluindo 16×16.
- 🟡 Jornada de Rodrigo (passos 2–5): base, VE/lambda, ignição célula a célula até o MBT, two-step, powershift e boost por marcha.
- 🟡 Jornada de Lucas (passos 2, 4 e 5): editar boost e avanço, enriquecer lambda, configurar overrun.
- 🟡 Risco PRD §8: complexidade da ECU sem feedback claro; mitigado por avisos didáticos e cursor de operação em tempo real.

**Por que agora:**
🟡 No Sprint 4 já existem `ecu-core` (Sprint 2), `ecu-profiles` e `dyno-cockpit-ui` (Sprint 3). O editor é o último elo para os critérios de aceite de Lucas e Rodrigo e é pré-requisito dos cenários de treino (`training-scenarios`).

---

## 3. Goals (Objetivos)

- [ ] 🟡 G-01: Refletir uma edição de célula na grade e no heatmap em ≤ 100 ms (p95) e confirmar no backend em ≤ 300 ms (p95) num container local.
- [ ] 🟡 G-02: Renderizar e rolar uma grade 32×32 com heatmap e cursor de operação a ≥ 60 FPS (p50) e ≥ 45 FPS (p5) no hardware de referência.
- [ ] 🟡 G-03: Oferecer as 4 navegações de perfil a partir do `EcuProfileDescriptor`, sem nenhum layout de perfil codificado à mão no front-end (0 condicionais por `profile_id` fora do mapeamento de ícones genéricos).
- [ ] 🟡 G-04: Suportar undo/redo de ≥ 50 passos por calibração aberta.
- [ ] 🟡 G-05: Cumprir WCAG 2.1 AA (0 violações axe-core A/AA) e permitir 100 % das operações de tabela por teclado.

**Métricas de sucesso:**

| Métrica | Baseline atual | Target | Prazo |
|---------|---------------|--------|-------|
| 🟡 Latência edição→pintura (p95) | N/A | ≤ 100 ms | Sprint 4 |
| 🟡 FPS da grade 32×32 com cursor (p50) | N/A | ≥ 60 FPS | Sprint 4 |
| 🟡 Passos de undo disponíveis | 0 | ≥ 50 | Sprint 4 |
| 🟡 Operações de tabela acessíveis por teclado | 0 % | 100 % | Sprint 4 |
| 🟡 Paridade de validação front/back (casos do conjunto de teste) | N/A | 100 % dos casos inválidos rejeitados nos dois lados | Sprint 4 |

---

## 4. Non-Goals (Fora do Escopo)

- 🟡 NG-01: Cópia visual, ícones, cores de marca ou nomes de menus de FuelTech, MoTeC, Haltech ou de fabricantes de ECUs OEM (PRD §5). Os perfis usam layout próprio e nomes genéricos.
- 🟡 NG-02: Leitura ou gravação de arquivos binários proprietários (`.bin` OEM bruto, `.ftm`, `.m1`) ou de checksums de ECU real (PRD §5).
- 🟡 NG-03: Ligação a ECU física por USB/CAN/OBD2 (PRD §5).
- 🟡 NG-04: Lógica de cálculo da ECU (interpolação em runtime, PID, malha fechada). Isso pertence ao `ecu-core`; a UI só edita e valida.
- 🟡 NG-05: Edição colaborativa simultânea da mesma calibração por dois usuários (PRD §5, sem multijogador).
- 🟡 NG-06: Tabelas maiores que 32×32 ou com mais de 2 eixos (4D).
- 🟡 NG-07: Autotune automático de VE ou de ignição; o usuário decide cada alteração (objetivo didático).
- 🟡 NG-08: Layout mobile ou largura < 1366 px.

---

## 5. Usuários e Personas

**Usuário primário:** 🟡 Rodrigo (intermediário, usa perfis standalone `ft-pro`, `m1-race` e `ht-elite`, mapeia VE e ignição célula a célula ao lado da cockpit) e Lucas (iniciante, usa `oem-stage`, altera boost, avanço, lambda e overrun).
**Usuário secundário:** 🟡 Prof. Marcos, que demonstra ao vivo em projetor como cada tabela altera a combustão e prepara a calibração inicial dos cenários.

**Jornada atual (sem a feature):**
1. 🟡 O usuário edita tabelas num software real em modo offline, sem resposta do motor.
2. 🟡 O usuário só descobre um erro de avanço ou de mistura no rolo real, com risco de quebrar o motor.
3. 🟡 O usuário não tem histórico de versões nem diff para comparar o mapa antes e depois.

**Jornada futura (com a feature):**
1. 🟡 O usuário abre o workspace do perfil ativo e navega pelas secções do descritor.
2. 🟡 O usuário edita tabelas com operações de bloco, vê o cursor de operação durante a puxada e recebe avisos didáticos.
3. 🟡 O usuário salva uma nova versão, aplica-a à sessão entre puxadas e compara com a versão anterior célula a célula.
4. 🟡 No swap, o usuário segue o assistente de base até o motor funcionar.

---

## 6. Requisitos Funcionais

### 6.1 Requisitos Principais

| ID | Requisito | Prioridade | Critério de Aceite |
|----|-----------|-----------|-------------------|
| RF-01 | 🟡 O sistema deve montar `EcuWorkspace` na rota `/sessions/:sessionId/ecu`, carregar o `EcuProfileDescriptor` do perfil ativo (`GET /api/v1/ecu-profiles/{profile_id}`) e a calibração ativa (`GET /api/v1/calibrations/{calibration_id}`). | Must | Teste de componente: com mocks 200 o workspace mostra o nome genérico do perfil e a primeira secção do descritor em ≤ 1,5 s; 404 mostra o estado de erro com o `code`. |
| RF-02 | 🟡 O sistema deve gerar a navegação de `ProfileNavigator` só a partir de `EcuProfileDescriptor.navigation` (árvore de secções e itens que apontam para `table_id` ou `strategy` id). | Must | Teste: o mesmo componente com os 4 descritores de fixture produz 4 árvores diferentes; um item novo no descritor aparece sem mudança de código. |
| RF-03 | 🟡 O sistema deve renderizar `TableEditor2D` e `TableEditor3D` (grade de valores) de 1×N até 32×32 com virtualização de linhas e colunas e cabeçalhos com os valores dos eixos e as unidades. | Must | Teste: uma tabela 32×32 monta ≤ 1200 nós DOM de célula ou usa Canvas; o cabeçalho mostra "rpm" e "kPa" com os breakpoints do `Axis`. |
| RF-04 | 🟡 O usuário deve poder selecionar uma célula, um retângulo (arrastar ou `Shift`+setas), linhas e colunas inteiras (clique no cabeçalho) e a tabela inteira (`Ctrl/Cmd+A`). | Must | Teste: `Shift`+seta-direita 3 vezes a partir de (2,2) seleciona (2,2)–(2,5); clique no cabeçalho da coluna 4 seleciona 16 células numa 16×16. |
| RF-05 | 🟡 O usuário deve poder aplicar à seleção: definir valor (`=`), somar/subtrair valor (`+`/`−`), multiplicar por percentagem (`*`, ex.: +5 %), interpolar linha, coluna ou bloco, e suavizar. | Must | Teste unitário das operações: `+2` em 4 células de 10 resulta 12; `+5 %` em 20 resulta 21; resultados presos aos limites `min`/`max` da tabela com aviso "valor limitado". |
| RF-06 | 🟡 O sistema deve interpolar linearmente pelos valores dos eixos (não pelos índices): linha/coluna entre as extremidades da seleção e bloco por interpolação bilinear a partir dos 4 cantos. | Must | Teste: eixo rpm 1000, 2000, 4000 com extremos 10 e 40 interpolam a célula do meio para 20 (não 25); bloco 3×3 com cantos 0, 10, 20, 30 dá o centro 15. |
| RF-07 | 🟡 O sistema deve suavizar a seleção com núcleo 3×3 `1 2 1 / 2 4 2 / 1 2 1` dividido por 16, com bordas replicadas e só células selecionadas alteradas. | Must | Teste: uma célula de pico 100 rodeada de 0 resulta 25 após 1 passagem; células fora da seleção ficam iguais bit a bit. |
| RF-08 | 🟡 O usuário deve poder copiar e colar a seleção em TSV compatível com planilhas (LibreOffice, Excel, Google Sheets), aceitando vírgula ou ponto decimal na colagem. | Must | Teste: copiar 2×3 gera `a\tb\tc\nd\te\tf`; colar "1,5\t2.5" grava 1,5 e 2,5; colagem maior que a tabela é cortada com aviso "n células ignoradas". |
| RF-09 | 🟡 O sistema deve manter undo/redo de ≥ 50 passos por calibração aberta (`Ctrl/Cmd+Z`, `Ctrl/Cmd+Shift+Z`), sendo cada operação de bloco ou colagem 1 passo. | Must | Teste: 60 edições seguidas permitem desfazer 50; a 51.ª tentativa fica desativada; refazer após nova edição é limpo. |
| RF-10 | 🟡 O sistema deve colorir as células com heatmap de escala contínua (min→max da tabela), mostrando sempre o valor numérico e usando paleta segura para daltonismo. | Must | Teste: o contraste do texto sobre cada cor da paleta é ≥ 4,5:1 (texto escuro ou claro escolhido por luminância); modo "sem cores" disponível. |
| RF-11 | 🟡 O sistema deve mostrar o cursor de operação em tempo real sobre a tabela, posicionado por interpolação bilinear em RPM × carga a partir da telemetria, com trilha dos últimos 2 s. | Must | Teste: com `rpm` = 3000 entre breakpoints 2000 e 4000 o cursor fica a 50 % entre as colunas; a trilha guarda ≤ 100 pontos e desaparece 2 s após o fim da puxada. |
| RF-12 | 🟡 O sistema deve mostrar `Table3DView` como superfície WebGL rotacionável (arrastar = orbitar, roda = zoom, duplo clique = repor) sincronizada com a seleção da grade, com fallback 2D (mapa de contorno) sem WebGL. | Should | Teste: selecionar a célula (5,7) destaca o vértice correspondente; com WebGL indisponível aparece o contorno 2D e o selo "modo compatível". |
| RF-13 | 🟡 O sistema deve gravar edições com `PATCH /api/v1/calibrations/{calibration_id}/tables/{table_id}` em lotes com debounce de 300 ms, com `base_revision` para concorrência otimista. | Must | Teste: 10 edições em 200 ms geram 1 PATCH; resposta 409 `CALIBRATION_REVISION_CONFLICT` abre o diálogo "recarregar ou sobrescrever". |
| RF-14 | 🟡 O usuário deve poder editar estratégias em `StrategyForms` (boost, limitador, two-step, antilag, powershift, overrun, malha fechada, failsafe) com validação zod gerada do OpenAPI, espelho dos modelos Pydantic `StrategyConfig`. | Must | Teste de paridade: o conjunto de 40 payloads de fixture (20 válidos, 20 inválidos) produz o mesmo veredito em zod e em Pydantic; erro mostrado junto ao campo. |
| RF-15 | 🟡 O usuário deve poder seguir `BaseSetupWizard` no swap: escolher perfil standalone (`POST /api/v1/sessions/{session_id}/ecu/swap`) e configurar roda fônica, bicos, combustível, sensores e failsafe (`PUT /api/v1/sessions/{session_id}/ecu/base-setup`). | Must | Teste E2E: completar os 6 passos com dados válidos deixa a sessão com o perfil `ft-pro` e o motor em marcha lenta na cockpit; voltar a um passo preserva os dados preenchidos. |
| RF-16 | 🟡 O usuário deve poder ver em `CalibrationVersions` a lista de versões, abrir o diff célula a célula entre duas versões (tabelas e estratégias) e reverter para uma versão anterior criando uma nova versão. | Must | Teste: duas versões que diferem em 3 células mostram "3 células alteradas" e destacam as 3 com valor antes → depois; reverter cria a versão N+1 com os valores da versão escolhida. |
| RF-17 | 🟡 O sistema deve mostrar em `LiveTuneIndicator`, durante uma puxada, quais tabelas são live-tunable e quais estão bloqueadas, e impedir a edição das bloqueadas até a puxada terminar. | Must | Teste: com `run.state` = `running`, uma tabela listada em `live_tunable_table_ids` aceita edição; outra mostra cadeado e o texto "bloqueada durante a puxada". |
| RF-18 | 🟡 O usuário deve poder aplicar a calibração gravada à sessão entre puxadas com `POST /api/v1/sessions/{session_id}/calibration` e ver a confirmação da revisão aplicada. | Must | Teste: após 200 a barra de estado mostra "revisão 7 aplicada"; durante a puxada o botão fica desativado exceto para alterações só em tabelas live-tunable. |
| RF-19 | 🟡 O sistema deve mostrar avisos didáticos não bloqueantes (W-01 a W-06 da secção 8) junto à célula ou campo, com explicação curta e link para a ajuda. | Must | Teste: avanço 4° acima do MBT estimado numa célula gera W-01 com ícone âmbar; gravar continua permitido. |
| RF-20 | 🟡 O sistema deve oferecer atalhos de teclado documentados num diálogo (tecla `?`) e navegação de célula por setas, `Tab`, `Home`, `End`, `PageUp`, `PageDown`. | Must | Teste Playwright só com teclado: selecionar bloco, somar 5 %, interpolar, desfazer e gravar sem mouse. |
| RF-21 | 🟡 O usuário deve poder editar correções por cilindro (trim de combustível ±25 % e de ignição ±10°) para cada cilindro do motor ativo. | Should | Teste: num motor de 6 cilindros aparecem 6 colunas; valor −11° é rejeitado com a mensagem de limite. |
| RF-22 | 🟡 O usuário deve poder trocar a unidade de exibição de lambda para AFR (lambda × AFR estequiométrico do combustível ativo) nas tabelas de lambda alvo. | Could | Teste: lambda 0,85 com E27 (13,2) mostra AFR 11,2; o valor gravado continua em lambda. |

### 6.2 Fluxo Principal (Happy Path)

1. 🟡 O usuário (Rodrigo) abre `/sessions/:sessionId/ecu` numa sessão com o `classic-20t-swap` e o perfil `ft-pro` já configurado.
2. 🟡 O sistema carrega o descritor e a calibração e mostra `ProfileNavigator` com as secções do perfil e a tabela VE aberta.
3. 🟡 O usuário seleciona um bloco de 4×4 células na zona de 4000–5000 rpm e 180–220 kPa e aplica `+3 %`.
4. 🟡 O sistema pinta o novo valor e o heatmap em ≤ 100 ms, regista 1 passo de undo e envia o PATCH em lote com `base_revision`.
5. 🟡 O sistema mostra o aviso W-02 numa célula com lambda alvo 0,92 a 210 kPa; o usuário corrige para 0,82 e o aviso desaparece.
6. 🟡 O usuário salva a versão "VE +3 % topo" e clica "Aplicar à sessão"; o sistema confirma a revisão aplicada.
7. 🟡 O usuário inicia a puxada na cockpit; a tabela VE mostra o cursor de operação com trilha e o `LiveTuneIndicator` indica as tabelas editáveis.
8. 🟡 Resultado: a nova versão fica no histórico, com diff disponível face à versão anterior.

### 6.3 Fluxos Alternativos

**Fluxo Alternativo A — Swap OEM → standalone com assistente:**
1. 🟡 O usuário clica "Trocar ECU" numa sessão `oem-stage` e escolhe `ht-elite`.
2. 🟡 O sistema chama o swap e abre `BaseSetupWizard` com 6 passos: roda fônica, bicos, combustível, sensores, failsafe, revisão.
3. 🟡 O sistema valida cada passo com zod antes de avançar e grava tudo no fim com o PUT de base-setup.
4. 🟡 O sistema abre o workspace do novo perfil com a calibração base gerada pelo `ecu-profiles`.

**Fluxo Alternativo B — Conflito de revisão:**
1. 🟡 O PATCH responde 409 `CALIBRATION_REVISION_CONFLICT` (outra aba gravou).
2. 🟡 O sistema mostra o diff entre a versão local e a do servidor e oferece "Recarregar" ou "Sobrescrever com as minhas alterações".

**Fluxo Alternativo C — Reverter versão (Lucas após a quebra):**
1. 🟡 O usuário abre `CalibrationVersions`, escolhe a versão antes da quebra e vê o diff.
2. 🟡 O usuário clica "Reverter"; o sistema cria nova versão com os valores escolhidos e oferece "Aplicar à sessão".

**Fluxo Alternativo D — Colagem de planilha:**
1. 🟡 O usuário copia uma grade 16×16 de uma planilha e cola com a célula (0,0) selecionada.
2. 🟡 O sistema valida números, limites e dimensões; células inválidas ficam marcadas e não são gravadas, com a contagem no aviso.

---

## 7. Requisitos Não-Funcionais

| ID | Requisito | Valor alvo | Observação |
|----|-----------|-----------|------------|
| RNF-01 | 🟡 Latência de edição | ≤ 100 ms (p95) da tecla à pintura; ≤ 300 ms (p95) até a confirmação do PATCH | Medido com `performance.mark` em teste Playwright no hardware de referência, container local. |
| RNF-02 | 🟡 FPS da grade | ≥ 60 FPS (p50), ≥ 45 FPS (p5) numa 32×32 com heatmap, cursor e trilha | Rolagem e cursor a 50 FPS de telemetria; grade em Canvas 2D com camada DOM só para a célula em edição. |
| RNF-03 | 🟡 Superfície 3D | ≥ 30 FPS a orbitar uma 32×32 | WebGL1/2 sem GPU dedicada; malha de 32×32 vértices; fallback 2D. |
| RNF-04 | 🟡 Memória | ≤ 300 MB no separador com 1 calibração (≈ 40 tabelas) e 50 passos de undo | Undo guarda deltas (células alteradas), não cópias de tabelas. |
| RNF-05 | 🟡 Tempo até interação | ≤ 2,5 s até editar a primeira célula | Bundle da rota ≤ 500 KB gzip; `Table3DView` em chunk separado carregado sob demanda. |
| RNF-06 | 🟡 Acessibilidade | WCAG 2.1 AA, 0 violações axe-core A/AA | Grade com `role="grid"`, `aria-rowindex`/`aria-colindex`, leitura "linha 3000 rpm, coluna 180 kPa, valor 92,5". |
| RNF-07 | 🟡 Compatibilidade | Chromium ≥ 120 e Firefox ≥ 120, ≥ 1366×768 | Clipboard API assíncrona com fallback para eventos `copy`/`paste`. |
| RNF-08 | 🟡 Qualidade | TypeScript `strict`, cobertura Vitest ≥ 85 % nas operações de tabela e ≥ 80 % em `features/ecu-tuning/` | Operações de tabela são funções puras cobertas por testes baseados em propriedades. |

---

## 8. Design e Interface

**Componentes afetados:**
- 🟡 `frontend/src/features/ecu-tuning/` (novo): `EcuWorkspace`, `ProfileNavigator`, `TableEditor2D`, `TableEditor3D`, `Table3DView`, `TableToolbar`, `OperationCursor`, `StrategyForms` (um formulário por subtipo de `StrategyConfig`), `BaseSetupWizard`, `CalibrationVersions`, `VersionDiff`, `LiveTuneIndicator`, `TuningWarnings`, `ShortcutsDialog`.
- 🟡 `frontend/src/features/ecu-tuning/ops/` (funções puras: `setValue`, `addValue`, `scalePct`, `interpolateLine`, `interpolateBlock`, `smooth`, `toTsv`, `parseTsv`, `diffCalibrations`).
- 🟡 `frontend/src/features/ecu-tuning/history/UndoStack.ts`.
- 🟡 `frontend/src/lib/api/generated/` (tipos e esquemas zod gerados do OpenAPI por `orval`).
- 🟡 `frontend/src/lib/ws/` (reutiliza o `TelemetrySocket` da cockpit para `rpm`, carga e `run.state`).

**Layout:**
- 🟡 Coluna esquerda (240–320 px, redimensionável): `ProfileNavigator` com a árvore do descritor e pesquisa por nome de tabela.
- 🟡 Área central: abas de tabelas/estratégias abertas; `TableToolbar` em cima da grade; `Table3DView` alternável (lado a lado ou abaixo).
- 🟡 Coluna direita recolhível: `TuningWarnings`, `LiveTuneIndicator`, propriedades da tabela (unidades, limites, eixos).
- 🟡 Barra inferior: revisão atual, estado de gravação ("gravado", "a gravar", "conflito"), botão "Aplicar à sessão", mini gauges de RPM, carga e lambda.
- 🟡 Diferenciação por perfil: ordem e agrupamento das secções, nomes genéricos dos menus e eixo de carga (ex.: `oem-stage` usa carga relativa/torque pedido; `ft-pro` usa MAP em kPa) vêm do descritor; a paleta da aplicação é a mesma para os 4 perfis, mudando só um acento de cor neutro por perfil.

**Operações de tabela (definição verificável):**
- 🟡 `setValue(sel, x)`: `v_ij ← clamp(x, min, max)`.
- 🟡 `addValue(sel, d)`: `v_ij ← clamp(v_ij + d, min, max)`.
- 🟡 `scalePct(sel, p)`: `v_ij ← clamp(v_ij · (1 + p/100), min, max)`.
- 🟡 `interpolateLine(sel)` em linha: para cada coluna j entre j0 e j1, `v_j = v_j0 + (v_j1 − v_j0) · (x_j − x_j0)/(x_j1 − x_j0)`, com `x` os breakpoints do eixo X; análogo em coluna com o eixo Y.
- 🟡 `interpolateBlock(sel)`: bilinear a partir dos 4 cantos `(i0,j0)`, `(i0,j1)`, `(i1,j0)`, `(i1,j1)` usando os breakpoints dos dois eixos.
- 🟡 `smooth(sel, passes = 1)`: convolução 3×3 normalizada por 16, bordas replicadas, aplicada só às células selecionadas (leitura sobre a tabela original de cada passagem).
- 🟡 Arredondamento: cada tabela declara `decimals` (ex.: VE 1 casa, ignição 1 casa, lambda 3 casas); o resultado é arredondado ao gravar, não durante a cadeia de operações.
- 🟡 Cada operação gera um `TableDelta` com as células e valores antes/depois, usado pelo undo, pelo PATCH e pelo diff.

**Cursor de operação:**
- 🟡 Entrada: canal do eixo X (normalmente `rpm`) e canal do eixo Y declarado no `Axis.source_channel` (ex.: `map_kpa`, `load_pct`, `throttle_pct`) a partir dos frames do WS.
- 🟡 Posição fracionária `u = i + (y − y_i)/(y_(i+1) − y_i)` e `w = j + (x − x_j)/(x_(j+1) − x_j)`, presa aos limites da grade; as 4 células vizinhas recebem contorno com espessura proporcional ao peso bilinear.
- 🟡 Trilha: até 100 pontos (2 s a 50 FPS), opacidade decrescente linear.

**Avisos didáticos (não bloqueantes):**

| Código | Condição | Mensagem (resumo) |
|---|---|---|
| 🟡 W-01 | Avanço de ignição > MBT estimado + 2° na célula | "Avanço acima do MBT estimado: mais avanço aqui não ganha torque e aumenta o risco de knock." |
| 🟡 W-02 | Lambda alvo > 0,90 com carga ≥ 80 % (ou MAP ≥ 1,5 × pressão atmosférica) | "Mistura pobre em alta carga: risco de EGT alta e de detonação." |
| 🟡 W-03 | Alvo de boost acima da pressão máxima do `TurboSpec` ou do limite mecânico | "Boost acima da capacidade do turbo/limite do motor." |
| 🟡 W-04 | Limitador de rotação > `MechanicalLimits.max_rpm` | "Limitador acima da rotação máxima segura do motor." |
| 🟡 W-05 | Overrun com atraso de ignição > 20° ATDC ou janela de corte atrasado > 1,5 s | "Pops & bangs agressivos: EGT pré-turbina pode passar do limite." |
| 🟡 W-06 | Variação entre células vizinhas > 15 % (VE) ou > 6° (ignição) | "Degrau abrupto entre células: pode causar instabilidade." |

- 🟡 O MBT estimado vem da tabela de referência `mbt_reference` do veículo (⚠️ ABERTO: fonte do MBT, OQ-02). Sem essa fonte, W-01 fica inativo e o painel mostra "MBT estimado indisponível".

**Atalhos de teclado:**

| Atalho | Ação |
|---|---|
| 🟡 Setas / `Shift`+setas | Mover célula ativa / estender seleção |
| 🟡 `Ctrl/Cmd+A` | Selecionar tabela inteira |
| 🟡 `Enter` ou `F2` | Editar célula ativa |
| 🟡 `=` | Definir valor na seleção |
| 🟡 `+` / `−` | Somar / subtrair valor |
| 🟡 `*` | Ajuste percentual |
| 🟡 `I` / `Shift+I` | Interpolar linha ou coluna / bloco |
| 🟡 `S` | Suavizar seleção |
| 🟡 `Ctrl/Cmd+C` / `Ctrl/Cmd+V` | Copiar / colar TSV |
| 🟡 `Ctrl/Cmd+Z` / `Ctrl/Cmd+Shift+Z` | Desfazer / refazer |
| 🟡 `Ctrl/Cmd+S` | Salvar versão |
| 🟡 `Ctrl/Cmd+Enter` | Aplicar à sessão |
| 🟡 `F3` | Alternar vista 3D |
| 🟡 `?` | Lista de atalhos |

**Estados da UI:**
- 🟡 Estado vazio: sessão sem calibração ou perfil sem tabelas na secção; texto "Nenhuma tabela nesta secção" ou botão "Criar calibração a partir da base do perfil".
- 🟡 Estado de carregamento: esqueleto da árvore e da grade; edição desativada até descritor e calibração carregados.
- 🟡 Estado de erro: `ProblemDetail` com `title`, `detail` e `code`; erros de campo junto ao input; falha de gravação mostra "não gravado" em vermelho com retry.
- 🟡 Estado de sucesso: "gravado (revisão N)" na barra inferior; após aplicar, "revisão N aplicada à sessão".
- 🟡 Estado bloqueado (puxada ativa): tabelas não live-tunable com cadeado e grade em modo só leitura.

---

## 9. Modelo de Dados

🟡 A UI não cria tabelas no banco. Ela consome os contratos do `ecu-core` e do `ecu-profiles` e guarda preferências e rascunhos em `localStorage`.

**Campos que a UI exige dos contratos de outros componentes (dono indicado):**

```python
# Dono: ecu-profiles. Campos exigidos pela UI em EcuProfileDescriptor.
from typing import Literal
from pydantic import BaseModel, Field

class NavItem(BaseModel):
    id: str
    label: str                                  # nome genérico, sem marcas
    kind: Literal["table", "strategy", "base_setup", "info"]
    target_id: str                              # table_id ou nome do subtipo de StrategyConfig

class NavSection(BaseModel):
    id: str
    label: str
    items: list[ "NavItem"] = Field(min_length=1)

class EcuProfileDescriptorUiFields(BaseModel):
    navigation: list[ "NavSection"] = Field(min_length=1)
    live_tunable_table_ids: list[ str] = Field(default_factory=list)
    load_axis_channel: Literal["map_kpa", "load_pct", "torque_request_nm", "throttle_pct"]
    accent_color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")   # acento neutro, sem cor de marca

# Dono: ecu-core. Campos exigidos pela UI em Axis, Table2D/Table3D e Calibration.
class AxisUiFields(BaseModel):
    unit: str                                   # "rpm", "kPa", "%", "°C"
    source_channel: str                         # canal de telemetria do cursor
class TableUiFields(BaseModel):
    table_id: str
    unit: str
    min: float
    max: float
    decimals: int = Field(ge=0, le=4)
class CalibrationUiFields(BaseModel):
    revision: int = Field(ge=1)                 # concorrência otimista
    version_label: str | None = Field(default=None, max_length=60)
    parent_calibration_id: str | None = None    # linhagem de versões
```

**Pedido de PATCH esperado pela UI (dono: ecu-core):**

```json
{
  "base_revision": 6,
  "cells": [ { "row": 4, "col": 9, "value": 92.5 }, { "row": 4, "col": 10, "value": 94.0 } ]
}
```
🟡 Resposta 200: `{ "revision": 7, "table": { "...Table3D completo..." } }`. Erros: 409 `CALIBRATION_REVISION_CONFLICT`, 409 `TABLE_LOCKED_DURING_RUN`, 422 `TABLE_VALUE_OUT_OF_RANGE`, 422 `TABLE_AXIS_NOT_MONOTONIC`, 404 `CALIBRATION_NOT_FOUND`.

**Estado de front-end (TypeScript):**

```ts
export interface CellRef { row: number; col: number; }
export interface Selection { anchor: CellRef; focus: CellRef; mode: "cells" | "rows" | "cols" | "all"; }

export interface TableDelta {
  tableId: string;
  cells: Array<{ row: number; col: number; before: number; after: number }>;
  op: "set" | "add" | "scale" | "interp_line" | "interp_block" | "smooth" | "paste" | "revert";
}

export interface UndoStack {
  capacity: number;            // padrão 100, mínimo 50
  past: TableDelta[];
  future: TableDelta[];
  push(d: TableDelta): void;   // limpa future
  undo(): TableDelta | undefined;
  redo(): TableDelta | undefined;
}

export interface CellDiff { tableId: string; row: number; col: number; a: number; b: number; }
export interface CalibrationDiff {
  tables: CellDiff[];
  strategies: Array<{ path: string; a: unknown; b: unknown }>;  // ex.: "boost.pid.kp"
  changedCells: number;
}

export interface TuningPrefs {
  version: 1;
  heatmap: "on" | "off";
  lambdaDisplay: "lambda" | "afr";
  show3d: "side" | "below" | "off";
}
// localStorage key: "simremap.ecu-tuning.prefs.v1"; rascunho não gravado em "simremap.ecu-tuning.draft.<calibration_id>".
```

**Versões:** 🟡 Cada "Salvar versão" cria uma `Calibration` com `parent_calibration_id` igual à versão atual; a lista vem de `GET /api/v1/calibrations?lineage=<root_id>`; o diff é calculado no cliente por `diffCalibrations(a, b)` com igualdade numérica após arredondamento a `decimals`.

**Migrações necessárias:** 🟡 Não nesta spec. Os campos acima entram nas migrações do `ecu-core` e do `ecu-profiles` se ainda não existirem.

---

## 10. Integrações e Dependências

| Dependência | Tipo | Impacto se indisponível |
|-------------|------|------------------------|
| 🟡 `ecu-core` (`/api/v1/calibrations*`, PATCH de tabela, `POST /api/v1/sessions/{session_id}/calibration`) | Obrigatória | Sem API: modo só leitura com rascunho local em `localStorage` e retry de gravação. |
| 🟡 `ecu-profiles` (`GET /api/v1/ecu-profiles*`, swap, base-setup) | Obrigatória | Sem descritor não há navegação: estado de erro com o `code`. |
| 🟡 `telemetry-datalogger` (WS para cursor e `run.state`) | Opcional | Sem WS: cursor e `LiveTuneIndicator` ocultos; edição continua. |
| 🟡 `vehicle-catalog` (`MechanicalLimits`, `TurboSpec`, `mbt_reference`) | Opcional | Sem dados: avisos W-01, W-03 e W-04 inativos com indicação. |
| 🟡 `dyno-cockpit-ui` (`lib/ws`, `lib/units` partilhados) | Obrigatória (código) | Partilha de módulos; sem eles a feature não compila. |
| 🟡 `orval` + zod (geração a partir do OpenAPI do FastAPI) | Obrigatória (build) | Falha de geração quebra o CI; esquemas versionados no repositório. |
| 🟡 three.js (MIT) para `Table3DView` | Opcional | Fallback 2D de contorno. |

---

## 11. Edge Cases e Tratamento de Erros

| Cenário | Trigger | Comportamento esperado |
|---------|---------|----------------------|
| 🟡 EC-01: Falha de gravação | PATCH com timeout de 5 s ou 5xx | Retry automático 3 vezes (1 s, 2 s, 4 s); o rascunho fica em `localStorage`; estado "não gravado" com botão "Tentar de novo". |
| 🟡 EC-02: Conflito de revisão | 409 `CALIBRATION_REVISION_CONFLICT` | Diff local vs. servidor; "Recarregar" ou "Sobrescrever" (novo PATCH com a revisão do servidor). |
| 🟡 EC-03: Edição de tabela bloqueada | 409 `TABLE_LOCKED_DURING_RUN` ou tabela fora de `live_tunable_table_ids` com puxada ativa | Reverte a pintura local, mostra cadeado e "bloqueada durante a puxada"; mantém a alteração como rascunho para aplicar depois. |
| 🟡 EC-04: Valor fora dos limites | Entrada > `max` ou < `min` | Prende ao limite, aviso "valor limitado a <max>"; o backend rejeita com 422 `TABLE_VALUE_OUT_OF_RANGE` se chegar sem prender. |
| 🟡 EC-05: Eixo não monotônico | Edição de breakpoint que quebra a ordem estritamente crescente | Bloqueia a gravação do eixo com erro junto ao cabeçalho; espelho de 422 `TABLE_AXIS_NOT_MONOTONIC`. |
| 🟡 EC-06: Colagem inválida | TSV com texto, células vazias ou maior que a tabela | Ignora células não numéricas e fora dos limites da grade; aviso com a contagem; 0 células gravadas se a colagem inteira for inválida. |
| 🟡 EC-07: Interpolação degenerada | Seleção de 1 célula ou breakpoints iguais | Operação desativada com dica "selecione ≥ 2 células numa linha/coluna"; nunca divide por zero. |
| 🟡 EC-08: Undo além da capacidade | Mais de 100 passos | Descarta o passo mais antigo (FIFO); o botão de undo fica desativado no limite. |
| 🟡 EC-09: Descritor sem navegação | `navigation` vazio ou ausente | Estado de erro "perfil sem navegação" com o `profile_id`; nenhuma árvore inventada no front-end. |
| 🟡 EC-10: Item de navegação órfão | `target_id` sem tabela/estratégia na calibração | Item visível com aviso "não disponível nesta calibração" e desativado. |
| 🟡 EC-11: WebGL indisponível | `getContext` nulo ou contexto perdido | Fallback de contorno 2D; selo "modo compatível". |
| 🟡 EC-12: Telemetria indisponível | WS fechado ou sem frames por 2 s | Cursor oculto; `LiveTuneIndicator` mostra "sem dados da bancada"; edição continua. |
| 🟡 EC-13: Esquema zod divergente | O backend rejeita com 422 um payload que o zod aceitou | Mostra os erros do `ProblemDetail` por campo e regista o caso no console em modo dev; o teste de paridade no CI bloqueia a release. |
| 🟡 EC-14: Swap com sessão em puxada | Clique "Trocar ECU" com `run.state` = `running` | Botão desativado com dica "aborte ou aguarde o fim da puxada". |
| 🟡 EC-15: Dados de rascunho corrompidos | JSON inválido no `localStorage` | Descarta o rascunho com aviso e carrega do servidor. |

---

## 12. Segurança e Privacidade

- **Autenticação:** 🟡 Nenhuma no MVP (local-first, um container por estação, mesma origem).
- **Autorização:** 🟡 O perfil local ativo edita as calibrações da sua sessão; calibrações iniciais de cenários marcadas como só leitura pelo `training-scenarios` abrem em modo só leitura (o aluno trabalha numa cópia).
- **Dados sensíveis:** 🟡 Nenhuma PII. Calibrações e preferências são dados técnicos.
- **Entrada não confiável:** 🟡 TSV colado é tratado só como números (parse estrito, sem fórmulas nem HTML); nenhum `dangerouslySetInnerHTML`; CSP `default-src 'self'`.
- **Marcas:** 🟡 Revisão de UI antes do release: nenhuma string, ícone ou cor de marca registada (checklist no PR).
- **Auditoria:** 🟡 O histórico de versões serve de trilha técnica (quem salvou = nickname local, revisão, `t` de relógio do host fora do laço físico).

---

## 13. Plano de Rollout

- **Estratégia:** 🟡 Entrega no Sprint 4 atrás da flag `VITE_FEATURE_ECU_TUNING`. Ordem: grade 2D + operações + undo + PATCH; depois navegação por descritor, estratégias e avisos; depois versões e diff; por fim 3D, cursor e assistente de swap.
- **Como reverter (rollback):** 🟡 Desligar a flag ou voltar à imagem Docker anterior; não há migração própria. Rascunhos em `localStorage` usam chave versionada e são ignorados por versões anteriores.
- **Monitoramento pós-deploy:** 🟡 Testes Playwright de latência (≤ 100 ms) e FPS (≥ 60) no CI; teste de paridade zod/Pydantic; contagem de 409 e de falhas de gravação no painel de diagnóstico nas primeiras aulas.

---

## 14. Open Questions

| # | Pergunta | Impacto | Dono | Prazo |
|---|---------|---------|------|-------|
| OQ-01 | 🟡 O `ecu-profiles` aceita incluir `navigation`, `live_tunable_table_ids`, `load_axis_channel` e `accent_color` no `EcuProfileDescriptor`? | Alto | George | 2026-10-25 |
| OQ-02 | 🟡 Qual a fonte do MBT estimado para o aviso W-01: tabela `mbt_reference` no `vehicle-catalog` ou canal calculado pelo `engine-physics-core`? | Médio | George | 2026-10-25 |
| OQ-03 | 🟡 O `ecu-core` adota `revision`, `parent_calibration_id`, o filtro `lineage` e os códigos `CALIBRATION_REVISION_CONFLICT` e `TABLE_LOCKED_DURING_RUN`? | Alto | George | 2026-10-25 |
| OQ-04 | 🟡 Quais tabelas são live-tunable em cada perfil (sugestão: VE, lambda alvo, ignição e trims; bloqueadas: eixos, base, failsafe, limitador)? | Médio | George | 2026-11-01 |
| OQ-05 | 🟡 O separador decimal da UI segue a locale do navegador (pt-BR com vírgula) ou fica fixo em vírgula? | Baixo | George | 2026-11-01 |

---

## 15. Decisões Tomadas (Decision Log)

| Decisão | Alternativas consideradas | Racional |
|---------|--------------------------|---------|
| 🟡 Navegação 100 % dirigida pelo `EcuProfileDescriptor` | Layout codificado por perfil no front-end | Um só componente para os 4 perfis; novos perfis sem código de UI; diferenças lógicas ficam no backend dono. |
| 🟡 Grade em Canvas 2D com 1 input DOM para a célula em edição | Grade só DOM (1024 células) | 60 FPS com heatmap e cursor no hardware de referência; DOM puro custa layout a cada frame. |
| 🟡 Undo por deltas de células | Cópias completas da tabela | 50+ passos numa 32×32 cabem em < 1 MB; mesmo delta serve ao PATCH e ao diff. |
| 🟡 Interpolação pelos valores dos eixos | Por índice de célula | Coerente com a interpolação em runtime da ECU (breakpoints não uniformes). |
| 🟡 zod gerado do OpenAPI por `orval` | zod escrito à mão | Fonte única nos modelos Pydantic; o teste de paridade apanha divergências. |
| 🟡 three.js em chunk lazy para 3D | WebGL cru | Menos código próprio; o chunk só carrega ao abrir a vista 3D. |
| 🟡 Avisos não bloqueantes | Bloquear valores perigosos | O objetivo didático exige deixar o usuário errar e ver a consequência na bancada (jornada de Lucas). |

---

## Apêndice

### Referências
- 🟡 `_reversa_sdd/prd.md` §4 (ECU, Apresentação), §5, §6, §8, §9.
- 🟡 `_reversa_sdd/personas.md` (Lucas passos 2–5; Rodrigo passos 1–5; Prof. Marcos passo 2).
- 🟡 Specs relacionadas: `ecu-core`, `ecu-profiles`, `dyno-cockpit-ui`, `telemetry-datalogger`, `vehicle-catalog`, `training-scenarios`.
- 🟡 Nota de formatação: genéricos Python aparecem com espaço após o colchete (ex.: `list[ str]`) por convenção deste documento.

### Rastreabilidade
| Critério do PRD | Requisitos |
|---|---|
| 🟡 Lucas: editar boost e avanço, corrigir lambda e overrun | RF-05, RF-14, RF-16, RF-19 |
| 🟡 Rodrigo: swap, base, VE/lambda/ignição, two-step, boost por marcha | RF-02, RF-06, RF-11, RF-14, RF-15, RF-21 |
| 🟡 Prof. Marcos: demonstrar ao vivo o efeito das tabelas | RF-11, RF-12, RF-17, RF-18 |
| 🟡 Editor 2D/3D incluindo 16×16 | RF-03, RF-12, RNF-02 |

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
- 🟡 Sugestões remanescentes: nenhuma
- 🟡 Revisão R1 (2026-10-18): reavaliado após a revisão de consistência entre specs, score 100,0/100.
