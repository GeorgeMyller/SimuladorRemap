# Requirements: Evolução Comercial — Live Tuning, Oficina de Upgrades, Imersão, Carreira e Blindagem de Cenários

> Identificador: `002-evolucao-comercial`
> Data: `2026-10-18`
> Pasta da extração reversa: `_reversa_sdd/` (âncora greenfield: `prd.md` + `sdd/*.md` + adendo vigente `addenda/001-simulador-remap.md`)
> Confidência: 🟢 CONFIRMADO, 🟡 INFERIDO, 🔴 LACUNA / DÚVIDA

## 1. Resumo executivo

A feature 002 evolui o MVP entregue pela feature 001 em seis frentes. A frente 0 elimina o erro `SCENARIO_CALIBRATION_HASH_MISMATCH` que hoje aborta cenários builtin e protege as calibrações de fábrica (`stock-*`) contra sobrescrita. As frentes 1 a 4 aumentam o valor de treino: calibração ao vivo com a bancada e a tabela na mesma tela, ajuste rápido de VE pelo lambda, comando de válvulas variável (VVT), oficina de upgrades mecânicos, combustível flex E27–E100, áudio e visão térmica por arquitetura, pedal progressivo, quatro cenários com defeitos ocultos e um modo carreira. A frente 5 reduz o peso do primeiro carregamento da interface e gera a documentação visual do projeto.

## 2. Contexto a partir do legado

| Fonte | Trecho relevante | Confidência |
|-------|------------------|-------------|
| `_reversa_sdd/addenda/001-simulador-remap.md#Impacto por artefato da extração` | MVP completo com 4 veículos, 4 perfis de ECU, 3 cenários builtin; RF-31 de comando variável ficou fora do backlog; edição de eixos não implementada | 🟡 |
| `_reversa_sdd/sdd/training-scenarios.md#6. Requisitos Funcionais` | Cenários builtin com `initial_calibration.source = vehicle_stock`, hash SHA-256 da calibração inicial validado no início da tentativa; defeitos ocultos (bomba de combustível, bico, sensor, wastegate) | 🟡 |
| `_reversa_sdd/sdd/ecu-core.md#6. Requisitos Funcionais` (RF-31, OQ-03) | Alvos de came de admissão/escape a partir das tabelas `cam_intake_target`/`cam_exhaust_target`; efeito na VE em aberto | 🟡 |
| `_reversa_sdd/sdd/engine-physics-core.md#6. Requisitos Funcionais` | VE verdadeira com termo `k_vvt·g_vvt(rpm, vvt)`; sobrealimentação, contrapressão e EGT; combustíveis E27, E100, Podium | 🟡 |
| `_reversa_sdd/sdd/vehicle-catalog.md#Apêndice A.3` | Parâmetros de turbo, bicos, intercooler e limites mecânicos por veículo | 🟡 |
| `_reversa_sdd/sdd/ecu-tuning-ui.md#6. Requisitos Funcionais` (RF-04 a RF-07, RF-11, RF-17, RF-18) | Seleção retangular, interpolação por eixo, suavização 3×3, cursor de operação ao vivo, tabelas live-tunable, aplicação à sessão | 🟡 |
| `_reversa_sdd/sdd/dyno-cockpit-ui.md#6. Requisitos Funcionais` | Bancada com carro no rolo em Canvas, Web Audio, gauges e controle de pedal por teclado | 🟡 |
| `_reversa_sdd/sdd/knock-and-failure-model.md#6. Requisitos Funcionais` | Modos de falha (knock, pré-ignição, EGT, biela, pistão, turbina) e limites mecânicos estruturais | 🟡 |
| `_reversa_sdd/prd.md#4. Escopo (in)` | Desafios do instrutor com defeitos ocultos; comando variável listado nas estratégias; tabelas 16×16 | 🟡 |
| `_reversa_sdd/prd.md#6. Restrições` | Loop ≥ 100 Hz (alvo 1000 Hz), telemetria 30–60 FPS, hardware de referência 4 núcleos / 8 GB sem GPU, zero PII | 🟡 |

## 3. Personas e cenários de uso

| Persona | Objetivo | Cenário-chave |
|---------|----------|---------------|
| Lucas (aluno, remap OEM) | Ver na mesma tela o carro no rolo e a célula da tabela que está trabalhando | Ativa a tela dividida, segura Espaço para acelerar, vê a célula piscar e corrige a VE com `Q` |
| Lucas | Treinar como uma oficina de verdade | Aceita uma ordem de serviço "Stage 1 diário seguro", entrega aprovada e recebe pagamento e reputação |
| Rodrigo (preparador, standalone) | Montar um Stage 2/3 completo | Cria a sessão com turbina maior, bicos de maior vazão, intercooler, downpipe e internos forjados, e acerta em E85 com sensor flex |
| Rodrigo | Diagnosticar defeitos antes de culpar o mapa | Resolve o cenário de bico obstruído olhando a EGT por cilindro |
| Prof. Marcos (instrutor) | Demonstrar ao vivo o efeito das tabelas e de componentes | Mostra a visão térmica do coletor ficando incandescente com EGT alta e compara o timbre das 4 arquiteturas |
| Prof. Marcos | Confiar nos cenários builtin em todas as estações | Nenhum aluno recebe 422 de hash ao iniciar um cenário builtin, mesmo após re-seed da calibração stock |

## 4. Regras de negócio novas ou alteradas

1. **RN-01:** Ao iniciar uma tentativa de cenário **builtin** com `initial_calibration.source = vehicle_stock`, uma divergência entre o hash do clone e o hash gravado no cenário não aborta a tentativa. O sistema ressincroniza o cenário com o hash da calibração de fábrica e registra um aviso no log. 🟡
   - Origem: `_reversa_sdd/sdd/training-scenarios.md#6. Requisitos Funcionais`
   - Tipo: alterada
2. **RN-02:** Cenários não builtin (importados ou do instrutor) mantêm o 422 `SCENARIO_CALIBRATION_HASH_MISMATCH`, porque o hash faz parte da avaliação assinada. 🟡
   - Tipo: preservada (explicitada)
3. **RN-03:** Calibrações com identificador iniciado por `stock-` são somente leitura pela API pública: substituição, reversão e edição de tabela são recusadas. Só o seed interno cria versões dessas calibrações. 🟡
   - Tipo: nova
4. **RN-04:** O Quick Tune corrige a VE por `VE_nova = VE_atual × (λ_medido / λ_alvo)`, limitada aos mínimos e máximos da tabela e a no máximo ±25 % por aplicação. Só atua em tabela do tipo VE. 🟡
   - Tipo: nova
5. **RN-05:** Um pacote de upgrades só aceita peças compatíveis com o veículo: turbina só em veículo turbo, intercooler só em veículo com intercooler, e internos forjados em qualquer veículo. Peça incompatível gera 422. 🟡
   - Tipo: nova
6. **RN-06:** O teor de etanol do combustível flex varia de 27 % a 100 % (E27 a E100) e só é aceito em veículo que permite os dois combustíveis E27 e E100. 🟡
   - Tipo: nova
7. **RN-07:** No modo carreira, o pagamento de uma ordem de serviço só é creditado quando a tentativa vinculada termina aprovada. Uma quebra de motor debita o custo do motor da ordem. O saldo pode ficar negativo. 🟡
   - Tipo: nova
8. **RN-08:** A estratégia `vvt` só é suportada pelos perfis que declaram o controle de came. O veículo sem VVT no catálogo (`classic-20t-swap`) ignora os alvos de came. 🟡
   - Tipo: nova

## 5. Requisitos Funcionais

| ID | Requisito | Prioridade | Critério de aceite | Confidência |
|----|-----------|------------|--------------------|-------------|
| RF-01 | Iniciar tentativa de cenário builtin com calibração stock nunca retorna 422 de hash; o hash do cenário é ressincronizado com a calibração de fábrica | Must | Teste: alterar o conteúdo da v1 `stock-*` no banco e iniciar `stage1-oem` retorna 201 e o clone tem o mesmo hash que o `initial_calibration.content_hash` atualizado | 🟡 |
| RF-02 | O carregamento dos cenários builtin calcula o hash pela mesma rota de serialização usada pelo clone | Must | Teste: hash gravado no cenário = hash do clone criado logo depois, para os 7 builtins | 🟡 |
| RF-03 | `PUT`, revert e `PATCH` de tabela em calibração `stock-*` retornam erro `CALIBRATION_STOCK_IMMUTABLE` (HTTP 409) | Must | Teste de API: PUT em `stock-hatch-20t-gdi-oem-stage` → 409 com o código; a v1 continua igual | 🟡 |
| RF-04 | A edição a partir da interface nunca tenta gravar numa calibração `stock-*`: a sessão trabalha numa cópia do usuário | Must | Teste: criar sessão sem `calibration_id`, editar uma célula → PATCH aceito numa calibração cujo id não começa por `stock-` | 🟡 |
| RF-05 | A bancada tem o modo "Tela Dividida (Live Tuning)": controles, gauges e carro no rolo de um lado; editor compacto da tabela da sessão do outro | Must | Teste de componente: o botão alterna o layout; a tabela VE 16×16 da sessão aparece ao lado do `CarOnRollerView` | 🟡 |
| RF-06 | Live Cell Tracing: a célula [RPM × MAP] em operação pisca em tempo real a partir dos frames do WebSocket | Must | Teste: frame com rpm 3000 e map 100 kPa destaca a célula mais próxima com a classe de destaque; a célula muda quando o frame muda | 🟡 |
| RF-07 | Edições no modo Live Tuning são aplicadas à sessão automaticamente, sem passo manual, quando a tabela é live-tunable | Must | Teste: editar a célula dispara o PATCH e em seguida o `POST /sessions/{id}/calibration` | 🟡 |
| RF-08 | Quick Tune (botão e tecla `Q`) aplica RN-04 na célula ativa ou nas células selecionadas da tabela VE | Must | Teste unitário: VE 80, λ medido 0,90, λ alvo 0,80 → 90; correção limitada a ±25 % | 🟡 |
| RF-09 | Interpolação rápida: `H` (horizontal), `V` (vertical) e `B` (suavização de bloco 2D), com botões na barra | Must | Teste: `H` numa linha selecionada com extremos 10 e 40 em eixo uniforme dá 20 e 30 no meio; `B` aplica o núcleo 3×3 | 🟡 |
| RF-10 | Física de VVT: avanço de came de admissão e escape altera a VE e a fração residual pelo cruzamento de válvulas (overlap) | Must | Teste: em baixa rotação, overlap maior reduz a VE; em alta rotação com MAP > contrapressão, overlap aumenta a VE | 🟡 |
| RF-11 | Estratégia `vvt` na ECU: alvos de came pelas tabelas, inibição com motor frio e limitação de taxa | Must | Teste: com ECT < limiar os alvos são 0; com a tabela, o alvo iguala a interpolação | 🟡 |
| RF-12 | A posição real dos cames e os alvos aparecem na telemetria (`cam_intake_deg`, `cam_exhaust_deg`, `cam_intake_target_deg`, `cam_exhaust_target_deg`) e as tabelas de came aparecem na navegação dos perfis com VVT | Should | Teste: subscrever `cam_intake_deg` recebe valores; descritor OEM-Stage lista `cam_intake_target` na navegação | 🟡 |
| RF-13 | Oficina de upgrades (Stage Builder): catálogo de peças por API e pacote escolhido ao criar a sessão | Must | `GET /api/v1/upgrades` lista as 6 categorias; `POST /api/v1/sessions` com `upgrades` cria a sessão com o veículo modificado | 🟡 |
| RF-14 | Turbina upgraded: mais fluxo no topo e mais inércia (lag) em baixa | Must | Teste: com turbina upgraded a rotação do turbo demora mais a atingir 80 % em baixa e a vazão máxima do compressor é maior | 🟡 |
| RF-15 | Bicos de maior vazão e bomba de alta vazão reduzem o duty cycle do bico para a mesma carga | Must | Teste: mesma condição com bicos high-flow → `injector_duty_pct` menor; bomba high-flow eleva o teto de vazão | 🟡 |
| RF-16 | Intercooler esportivo reduz a IAT; downpipe de alto fluxo reduz contrapressão e EGT | Must | Teste: mesma condição → IAT menor com intercooler; EGT e contrapressão menores com downpipe | 🟡 |
| RF-17 | Internos forjados elevam `max_rod_load_kn`, `max_cylinder_pressure_bar` e `max_piston_temp_c` | Must | Teste: `apply_upgrades` com forjados eleva os três limites; `StructuralLimits` da sessão reflete os novos valores | 🟡 |
| RF-18 | Flex Fuel: teor de etanol de 27 % a 100 % na criação da sessão; física usa o combustível misturado; ECU lê o sensor de etanol e interpola combustível, avanço e boost | Must | Teste: E50 tem AFR estequiométrico entre E27 e E100; a ECU com sensor em 85 % aumenta o pulso de injeção face a 27 % | 🟡 |
| RF-19 | Interface da oficina e do flex: seletor de peças e controle de teor de etanol na tela de criação de sessão | Must | Teste de componente: escolher peças e E85 envia `upgrades` e `ethanol_pct` no POST da sessão | 🟡 |
| RF-20 | Áudio por arquitetura: timbres distintos para 4 cil. turbo moderno, 6 em linha turbo, 4 cil. turbo clássico com marcha lenta irregular e V8 com assobio do compressor | Must | Teste unitário: os 4 perfis de áudio produzem conjuntos de harmônicos diferentes; o V8 tem componente de compressor proporcional à rotação | 🟡 |
| RF-21 | Visão Térmica / Raio-X no carro no rolo: coletor e carcaça da turbina com gradiente vermelho → laranja → amarelo entre 650 °C e 980 °C de EGT, fumaça e fagulhas distintas por modo de falha, chamas no escape nos pops & bangs | Must | Teste: a função de cor devolve vermelho escuro a 650 °C, laranja a ~815 °C e amarelo claro a 980 °C; o toggle liga e desliga a camada | 🟡 |
| RF-22 | Pedal progressivo: segurar Espaço sobe o pedal continuamente até 100 %; soltar fecha para 0 % rapidamente; W/S continuam com passos fixos | Must | Teste: segurar Espaço 1 s leva o pedal a ≥ 90 %; soltar leva a 0 % em ≤ 150 ms | 🟡 |
| RF-23 | Quatro cenários builtin novos com defeitos ocultos: `defect-fuel-pump`, `defect-boost-leak`, `defect-lean-injector`, `defect-wastegate-stuck` | Must | Teste: o catálogo carrega 7 builtins; cada cenário novo cria a sessão com o defeito físico correspondente e exige diagnóstico | 🟡 |
| RF-24 | O defeito de bomba de combustível só perde pressão de forma relevante acima de 5.500 RPM em carga plena | Must | Teste de física: lambda em carga plena pobre acima de 5.500 rpm e dentro da janela abaixo de 5.000 rpm | 🟡 |
| RF-25 | Modo Carreira: perfil com saldo e reputação, ordens de serviço com metas, aceite vinculado a uma tentativa de cenário, liquidação com pagamento ou custo do motor | Must | Teste de API: aceitar uma ordem cria uma tentativa; liquidar uma tentativa aprovada credita o pagamento; quebra debita o custo do motor | 🟡 |
| RF-26 | Página "Oficina (Carreira)" na navegação, com saldo, reputação, ordens disponíveis e histórico | Must | Teste de componente: a página lista as ordens, o botão aceitar abre a bancada da sessão da tentativa | 🟡 |
| RF-27 | Code-splitting: páginas pesadas e a superfície 3D carregam sob demanda e nenhum chunk do build passa de 500 kB | Must | `npm run build` sem aviso de chunk > 500 kB | 🟡 |
| RF-28 | Documentação visual em `_reversa_docs/` gerada pelo `/reversa-docs` com arquitetura, dashboards, glossário e páginas das features | Should | `_reversa_docs/index.html` abre offline e cita as features 001 e 002 | 🟡 |

## 6. Requisitos Não Funcionais

| Tipo | Requisito | Evidência ou justificativa | Confidência |
|------|-----------|----------------------------|-------------|
| Desempenho | O passo da física com VVT, upgrades e flex continua ≤ 1 ms por tick no hardware de desenvolvimento (laço ≥ 1000 Hz) | `_reversa_sdd/prd.md#6. Restrições` | 🟡 |
| Desempenho | A tela dividida mantém 30–60 FPS na bancada com a tabela 16×16 visível | `_reversa_sdd/prd.md#3. Métricas de sucesso` | 🟡 |
| Precisão | Veículo sem upgrades e com combustível de série mantém o desvio < 5 % contra o `Reference Benchmark Baseline v1` (testes `-m accuracy` continuam aprovados) | `_reversa_sdd/addenda/001-simulador-remap.md` | 🟡 |
| Determinismo | Mesma seed, mesmos upgrades e mesmo teor de etanol produzem a mesma telemetria | `_reversa_sdd/sdd/dyno-bench.md#6. Requisitos Funcionais` | 🟡 |
| Segurança | Nenhum dado pessoal no modo carreira: só nickname local | `_reversa_sdd/prd.md#6. Restrições` | 🟡 |
| Qualidade | `ruff`, `mypy --strict`, `bandit`, `pytest`, `tsc`, `eslint` e `vitest` continuam limpos; cobertura mínima por pacote mantida | `Makefile#check` | 🟡 |
| Acessibilidade | Controles novos têm rótulo acessível e atalhos listados no diálogo de atalhos | `_reversa_sdd/sdd/dyno-cockpit-ui.md` | 🟡 |
| Compatibilidade | Contratos novos são aditivos: campos opcionais com padrão; clientes antigos continuam funcionando | `_reversa_sdd/sdd/platform-foundation.md` | 🟡 |

## 7. Critérios de Aceitação

```gherkin
Cenário: Cenário builtin inicia mesmo com calibração stock re-semeada
  Dado que a v1 da calibração stock do hatch foi alterada no banco
  Quando o aluno inicia a tentativa do cenário "stage1-oem"
  Então a tentativa é criada com status 201
  E o hash do clone é igual ao hash da calibração inicial do cenário

Cenário: Cenário importado com hash divergente continua recusado
  Dado um cenário importado cujo hash de calibração inicial não confere
  Quando o aluno inicia a tentativa
  Então a resposta é 422 com o código SCENARIO_CALIBRATION_HASH_MISMATCH

Cenário: Calibração de fábrica é somente leitura
  Dado a calibração "stock-hatch-20t-gdi-oem-stage"
  Quando um cliente envia PUT para substituí-la
  Então a resposta é 409 com o código CALIBRATION_STOCK_IMMUTABLE
  E a versão 1 continua igual

Cenário: Live Tuning com célula ativa
  Dado uma sessão em puxada estacionária a 3000 rpm e 100 kPa
  Quando o usuário ativa a tela dividida
  Então a célula da VE mais próxima de 3000 rpm e 100 kPa pisca
  E ao pressionar Q a VE dessa célula é corrigida pelo lambda medido e aplicada à sessão

Cenário: Quick Tune fora de tabela VE
  Dado que a tabela aberta é a de avanço de ignição
  Quando o usuário pressiona Q
  Então nenhuma célula muda e aparece o aviso "Quick Tune só atua na tabela VE"

Cenário: Sessão com upgrades
  Dado o hatch turbo
  Quando o usuário cria a sessão com turbina upgraded, bicos high-flow e internos forjados
  Então a sessão responde com o pacote de upgrades
  E o limite de carga da biela da sessão é maior que o de série

Cenário: Upgrade incompatível
  Dado o V8 com compressor mecânico
  Quando o usuário pede turbina upgraded
  Então a resposta é 422 com o código UPGRADE_NOT_COMPATIBLE

Cenário: Flex fuel E85
  Dado o hatch com combustível flex em 85 % de etanol
  Quando a sessão roda uma puxada
  Então o lambda medido fica na janela alvo sem edição manual da VE

Cenário: Teor de etanol fora do intervalo
  Quando o usuário pede 15 % de etanol
  Então a resposta é 422 de validação

Cenário: Blip de acelerador
  Dado a bancada em marcha lenta
  Quando o usuário segura Espaço por 1 s e solta
  Então o pedal sobe acima de 90 % e volta a 0 % em até 150 ms

Cenário: Ordem de serviço aprovada
  Dado um perfil de carreira com saldo 0
  Quando o jogador aceita a ordem "Stage 1 diário seguro" e a tentativa termina aprovada
  Então o saldo aumenta o valor do pagamento e a reputação sobe

Cenário: Motor quebrado na ordem
  Dado uma ordem aceita
  Quando a tentativa termina com motor quebrado
  Então o saldo diminui o custo do motor e a reputação cai

Cenário: Build sem chunks grandes
  Quando o frontend é construído
  Então nenhum arquivo JavaScript gerado passa de 500 kB
```

## 8. Prioridade MoSCoW

| Item | MoSCoW | Justificativa |
|------|--------|---------------|
| RF-01 a RF-04 | Must | Erro bloqueante em produção nos cenários builtin |
| RF-05 a RF-09 | Must | Pedido explícito; maior ganho de usabilidade |
| RF-10, RF-11 | Must | Pedido explícito; fecha RF-31 do ecu-core |
| RF-12 | Should | Visibilidade do VVT; não bloqueia a física |
| RF-13 a RF-19 | Must | Pedido explícito; Stage 2/3 realista |
| RF-20 a RF-22 | Must | Pedido explícito; imersão |
| RF-23 a RF-26 | Must | Pedido explícito; treino e retenção |
| RF-27 | Must | Pedido explícito; desempenho do primeiro carregamento |
| RF-28 | Should | Documentação; não altera o produto |
| RNF de precisão | Must | Não pode regredir o benchmark |

## 9. Esclarecimentos

> Nenhuma sessão de dúvidas registrada ainda. Modo autônomo "não parar": as dúvidas abaixo viram premissas no `roadmap.md` e ficam registradas em `questions.md`.

## 10. Lacunas

- 🔴 [DÚVIDA] Onde persistir o estado do modo carreira (saldo, reputação, histórico): no banco do backend da estação ou só no navegador?
- 🔴 [DÚVIDA] O teor de etanol pode mudar com a sessão em andamento (reabastecimento) ou só na criação da sessão?
- 🔴 [DÚVIDA] Se o núcleo da biblioteca 3D sozinho passar de 500 kB, aceita-se um chunk de fornecedor isolado acima do limite ou a superfície 3D deve ser trocada?

## 11. Histórico de alterações

| Data | Alteração | Autor |
|------|-----------|-------|
| 2026-10-18 | Versão inicial gerada por `/reversa-requirements` (modo autônomo) | reversa |
