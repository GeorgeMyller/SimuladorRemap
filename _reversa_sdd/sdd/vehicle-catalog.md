# Spec: vehicle-catalog

**Versão:** 1.1
**Status:** Rascunho
**Autor:** reversa-spec-sdd
**Data:** 2026-10-18
**Reviewers:** N/A
**Sprint:** 1 (componente 3 da ordem aprovada; `hatch-20t-gdi` validado no Sprint 1, os restantes 3 veículos validados até o Sprint 4)

---

## 1. Resumo

🟡 O componente `vehicle-catalog` é a fonte única dos dados técnicos dos 4 veículos do SimuladorRemap: geometria do motor, sobrealimentação, bicos injetores, combustíveis, transmissão, limites mecânicos, curvas de referência e calibração OEM de fábrica.
🟡 Os dados vivem em arquivos JSON versionados, validados por contratos Pydantic v2 no arranque, e são expostos ao `engine-physics-core`, ao `dyno-bench`, ao `ecu-core` e à UI pelos endpoints `GET /api/v1/vehicles`, `GET /api/v1/vehicles/{vehicle_id}` e `GET /api/v1/vehicles/{vehicle_id}/reference-curves`.

---

## 2. Contexto e Motivação

**Problema:**
🟡 O modelo físico só cumpre a meta de desvio < 5 % se cada motor tiver dados coerentes: diâmetro, curso, biela, taxa de compressão, VE física, turbo ou compressor, bicos e perdas de transmissão. Sem um catálogo validado, cada componente inventaria os seus próprios números e o dinamômetro, a ECU e o modelo de dano divergiriam. O aluno também precisa de limites mecânicos explícitos (torque de biela, EGT, rotação de flutuação de válvulas) para entender porque um acerto quebra o motor.

**Evidências:**
- 🟡 O PRD (seção 7) fixa os 4 veículos de referência com cilindrada, taxa, sobrealimentação, potência de série e limites (ex.: 1984 cc, 9,6:1, 220 whp / 350 N·m, biela ~420 N·m, EGT 950 °C no hatch).
- 🟡 O PRD (seção 8, risco 2) avisa que as folhas públicas raramente trazem lambda e EGT; cada curva precisa de fonte, licença e confiança documentadas.
- 🟡 O PRD (seção 6, compliance de marcas) proíbe marcas registradas; os nomes exibidos precisam ser genéricos.
- 🟡 As specs `engine-physics-core`, `dyno-bench` e `ecu-core` já consomem `VehicleSpec`, `EngineSpec`, `FuelSpec`, `MechanicalLimits` e `ReferenceCurve` e abriram perguntas sobre campos (dyno-bench OQ-04, ecu-core OQ-02, ecu-tuning-ui OQ-02) que esta spec resolve.

**Por que agora:**
🟡 O catálogo é o componente 3 da ordem aprovada e pertence ao Sprint 1. O `engine-physics-core` não constrói um `PhysicsEngine` sem `VehicleSpec` e `FuelSpec` válidos, e o teste de referência do `hatch-20t-gdi` é o portão de saída do Sprint 1.

---

## 3. Goals (Objetivos)

- [ ] 🟡 G-01: O sistema carrega e valida os 4 veículos, os 4 combustíveis, as curvas de referência e as calibrações de fábrica no arranque em ≤ 500 ms no hardware de referência, com 0 erros de validação.
- [ ] 🟡 G-02: O sistema publica para o `hatch-20t-gdi` curvas de referência de torque, potência, lambda e EGT que permitem ao `engine-physics-core` medir desvio < 5 % por ponto de RPM no Sprint 1; os 3 veículos restantes atingem o estado `validated` até o Sprint 4.
- [ ] 🟡 G-03: 100 % dos valores numéricos fixados pelo PRD (seção 7) aparecem no catálogo com valor exato e proveniência `prd`.
- [ ] 🟡 G-04: 100 % dos valores sem fonte publicada aparecem na lista `estimated_fields` e são exibidos como estimativa a validar.
- [ ] 🟡 G-05: 0 ocorrências de marcas registradas nos campos exibidos ao usuário, verificadas por teste automático no CI.

**Métricas de sucesso:**

| Métrica | Baseline atual | Target | Prazo |
|---------|---------------|--------|-------|
| 🟡 Tempo de carga e validação do catálogo no arranque | inexistente | ≤ 500 ms | 2026-10-25 |
| 🟡 Veículos com `validation_status = validated` | 0 | 1 (Sprint 1) e 4 (Sprint 4) | 2026-10-25 e 2026-11-15 |
| 🟡 Valores do PRD reproduzidos com exatidão | 0 % | 100 % | 2026-10-25 |
| 🟡 Campos inferidos marcados como estimativa | 0 % | 100 % | 2026-10-25 |
| 🟡 Latência P95 de `GET /api/v1/vehicles` | inexistente | < 20 ms | 2026-10-25 |

---

## 4. Non-Goals (Fora do Escopo)

- 🟡 NG-01: O catálogo não permite ao usuário criar, editar ou importar veículos pela API ou pela UI no MVP; os dados mudam só por commit nos arquivos versionados.
- 🟡 NG-02: O catálogo não modela kits de preparação mecânica (troca de turbo, polia, comando, bielas) nem combinações de peças; cada veículo tem uma única configuração de hardware.
- 🟡 NG-03: O catálogo não calcula física, dano nem estratégia de ECU; só fornece dados e a função pura de comparação com a curva de referência.
- 🟡 NG-04: O catálogo não guarda chassis, aerodinâmica, massa do veículo, pneus para pista nem suspensão, porque o PRD exclui a condução fora do rolo.
- 🟡 NG-05: O catálogo não inclui motores diesel, rotativos, elétricos ou híbridos, nem veículos além dos 4 do PRD.
- 🟡 NG-06: O catálogo não contém logotipos, nomes comerciais nem códigos de peça de fabricantes nos campos exibidos ao usuário.
- 🟡 NG-07: O catálogo não descarrega dados de serviços online; todas as curvas e fontes vêm empacotadas na imagem Docker.

---

## 5. Usuários e Personas

**Usuário primário:** 🟡 Lucas (iniciante em calibração OEM) escolhe o hatch 2.0 turbo GDI, vê a potência de série (220 whp), o limite de EGT (950 °C) e o limite de torque da biela (~420 N·m), e compara a puxada base com a curva de referência.

**Usuário secundário:** 🟡 Rodrigo (preparador intermediário) escolhe o clássico 2.0 turbo para o swap standalone FT-Pro ou o coupé 6 cilindros, e consulta bicos, combustível E100, roda fônica e limites de rotação. 🟡 Prof. Marcos (instrutor) usa os limites mecânicos e as curvas com fonte e confiança para explicar à turma a relação entre calibração e física.

**Consumidores técnicos:** 🟡 `engine-physics-core` (geometria, VE física, turbo, compressor, bicos, combustível), `dyno-bench` (transmissão, perdas, inércia, curvas de referência, calibração de série), `ecu-core` (cilindrada, combustível, limites), `knock-and-failure-model` (limites mecânicos), `dyno-cockpit-ui` e `ecu-tuning-ui` (dados exibidos e avisos).

**Jornada atual (sem a feature):**
1. 🟡 O usuário não tem forma de saber a potência de série nem os limites do motor que vai calibrar.
2. 🟡 O usuário compara as suas puxadas com números de fóruns sem fonte nem condições de medição.
3. 🟡 O usuário descobre o limite da biela ou da EGT só quando o motor real quebra.

**Jornada futura (com a feature):**
1. 🟡 O usuário lista os veículos disponíveis com nome genérico, arquitetura e potência de série.
2. 🟡 O usuário abre o detalhe do veículo e vê geometria, sobrealimentação, combustível, limites mecânicos e os campos marcados como estimativa a validar.
3. 🟡 O usuário executa a puxada base e vê a curva de referência sobreposta, com fonte, licença e confiança.
4. 🟡 O usuário calibra sabendo os limites que provocam cada modo de falha.

---

## 6. Requisitos Funcionais

### 6.1 Requisitos Principais

| ID | Requisito | Prioridade | Critério de Aceite |
|----|-----------|-----------|-------------------|
| 🟡 RF-01 | 🟡 O sistema deve carregar no arranque todos os arquivos JSON de `backend/src/simremap/catalog/data/` (ou de `SIMREMAP_CATALOG_DIR`), validar cada um com os contratos Pydantic v2 da seção 9 e recusar o arranque com `code = CATALOG_INVALID` e código de saída 4 se houver qualquer erro. | Must | Com um `vehicle.json` sem o campo `engine`, o processo termina com código 4 e o log `startup.failed` lista o arquivo, o ponteiro JSON `/engine` e a mensagem; com os dados válidos o arranque conclui e regista `startup.catalog` com 4 veículos. |
| 🟡 RF-02 | 🟡 O sistema deve conter exatamente os 4 veículos canónicos `hatch-20t-gdi`, `coupe-30t-i6`, `classic-20t-swap` e `muscle-v8-sc`, com `vehicle_id` igual ao nome do diretório. | Must | `GET /api/v1/vehicles?include_drafts=true` devolve 4 itens com esses IDs; um diretório `vehicles/foo-bar/` com `vehicle_id = "foo-baz"` gera `CATALOG_INVALID`. |
| 🟡 RF-03 | 🟡 O sistema deve validar a coerência geométrica do `EngineSpec`: cilindrada calculada `V_d = (π/4) · B² · S · n_cyl` igual à `displacement_cc` declarada com tolerância de 0,5 %, relação biela/manivela `l / (S/2)` entre 2,8 e 4,2. | Must | O `hatch-20t-gdi` (82,5 mm × 92,8 mm × 4) calcula 1984,3 cc e passa; um arquivo com `displacement_cc = 2100` e a mesma geometria gera `CATALOG_INVALID` com ponteiro `/engine/displacement_cc`. |
| 🟡 RF-04 | 🟡 O sistema deve validar a ordem de ignição como permutação de 1..`n_cyl` que começa no cilindro 1. | Must | `hatch-20t-gdi` = 1-3-4-2, `coupe-30t-i6` = 1-5-3-6-2-4, `classic-20t-swap` = 1-3-4-2, `muscle-v8-sc` = 1-5-4-8-6-3-7-2 passam; `[1, 3, 3, 2]` gera `CATALOG_INVALID`. |
| 🟡 RF-05 | 🟡 O sistema deve reproduzir com valor exato e proveniência `prd` todos os valores da seção 7 do PRD (tabela do Apêndice A.1). | Must | Teste paramétrico compara 31 valores (cilindrada, cilindros, taxa, potência, torque, limites) com a tabela A.1 e exige igualdade exata e `provenance.kind == "prd"`. |
| 🟡 RF-06 | 🟡 O sistema deve marcar como estimativa a validar todo campo numérico sem proveniência `prd`, `public_spec` ou `literature`, e expor a lista ordenada de ponteiros JSON em `estimated_fields`. | Must | No `hatch-20t-gdi`, `/engine/rod_length_mm` aparece em `estimated_fields` e `/engine/bore_mm` com proveniência `public_spec` não aparece; a lista é ordenada lexicograficamente. |
| 🟡 RF-07 | 🟡 O sistema deve recusar no arranque qualquer `display_name`, `architecture_note` ou descrição exibida que contenha um termo da lista de marcas do Apêndice A.6, comparado como palavra inteira e sem distinção de maiúsculas. | Must | Um `display_name = "Hatch EA888"` gera `CATALOG_INVALID` com `code` interno `TRADEMARK_IN_DISPLAY_TEXT`; os 4 veículos do pacote passam com 0 ocorrências. |
| 🟡 RF-08 | 🟡 O sistema deve validar as invariantes de `MechanicalLimits`: `rev_limit_rpm ≤ max_rpm < valve_float_rpm`, `turbo_max_rpm` obrigatório se e só se `induction = "turbo"`, e `rod_torque_limit_nm` maior que o torque de pico de série. | Must | `rev_limit_rpm = 7000` com `max_rpm = 6800` gera `CATALOG_INVALID`; o `muscle-v8-sc` com `turbo_max_rpm = null` passa; o hatch com 420 N·m de limite e 350 N·m de série passa. |
| 🟡 RF-09 | 🟡 O sistema deve exigir coerência da sobrealimentação: `induction = "turbo"` exige `turbo` e proíbe `supercharger`; `induction = "supercharger"` exige `supercharger` e proíbe `turbo`; `throttle_location = "pre_compressor"` só é aceite com supercharger. | Must | Um veículo `turbo` com `supercharger` preenchido gera `CATALOG_INVALID`; o `muscle-v8-sc` com `throttle_location = "pre_compressor"` passa. |
| 🟡 RF-10 | 🟡 O sistema deve validar as grelhas físicas (`true_ve`, `g_vvt`, `dead_time_ms`, `mbt_reference`, eficiências) com eixos estritamente crescentes, entre 2 e 32 pontos por eixo, dimensão de `z_values` igual a `len(y) × len(x)` e valores finitos dentro dos limites do campo. | Must | Um `true_ve` com eixo RPM `[1000, 2000, 2000]` gera `CATALOG_INVALID` com `GRID_AXIS_NOT_MONOTONIC`; um valor de VE 1,40 gera erro (limite 0,20 a 1,35). |
| 🟡 RF-11 | 🟡 O sistema deve fornecer os combustíveis `e27`, `e100`, `podium` e `e0` com AFR estequiométrico, PCI, RON/MON, calor de vaporização, densidade, fração mássica de etanol, coeficientes de velocidade laminar e temperatura de superfície de pré-ignição (Apêndice A.5). | Must | `get_fuel("e27").afr_stoich == 13.2`, `get_fuel("e100").density_kg_m3 == 789` e `get_fuel("e100").density_g_cc == 0.789`; um veículo com `stock_fuel_id` fora de `allowed_fuel_ids` gera `CATALOG_INVALID`. |
| 🟡 RF-12 | 🟡 O sistema deve validar cada `ReferenceCurve` com RPM estritamente crescente em passo de 250 rpm, primeiro ponto ≤ 3000 rpm, último ponto ≥ `rev_limit_rpm − 250`, ao menos 8 pontos, e `source`, `license` e `confidence` não vazios. | Must | A curva de série do hatch tem 19 pontos de 2000 a 6500 rpm e passa; uma curva com passo 300 rpm ou sem `license` gera `CATALOG_INVALID`. |
| 🟡 RF-13 | 🟡 O sistema deve validar a coerência entre torque e potência de cada ponto de referência: `power_wheel_kw = torque_crank_nm · ω / 1000 · η_drv − P_fixa` com erro ≤ 1 %. | Must | No ponto 6000 rpm do hatch (307,3 N·m, η 0,85) o valor 164,1 kW passa; 170,0 kW gera `REFERENCE_CURVE_INCONSISTENT`. |
| 🟡 RF-14 | 🟡 O sistema deve expor `GET /api/v1/vehicles` com a lista de `VehicleSummary`, só veículos `validated` por padrão e todos com `include_drafts=true`. | Must | No Sprint 1, sem parâmetro a resposta tem 1 item (`hatch-20t-gdi`); com `include_drafts=true` tem 4 itens, cada um com `validation_status`. |
| 🟡 RF-15 | 🟡 O sistema deve expor `GET /api/v1/vehicles/{vehicle_id}` com o `VehicleDetail` completo, incluindo `estimated_fields`, `data_sha256` e `catalog_version`. | Must | `GET /api/v1/vehicles/hatch-20t-gdi` devolve 200 com `engine.compression_ratio = 9.6`; `GET /api/v1/vehicles/inexistente` devolve 404 `application/problem+json` com `code = VEHICLE_NOT_FOUND`. |
| 🟡 RF-16 | 🟡 O sistema deve expor `GET /api/v1/vehicles/{vehicle_id}/reference-curves` com filtros opcionais `fuel_id` e `calibration_ref` (padrão `stock`). | Must | Para o hatch devolve 1 curva `stock` em `e27` com 4 grandezas; `fuel_id=e100` devolve 404 `REFERENCE_CURVE_NOT_FOUND`. |
| 🟡 RF-17 | 🟡 O sistema deve responder aos 3 endpoints com `ETag` igual ao `catalog_sha256` e devolver 304 sem corpo quando `If-None-Match` coincidir. | Should | Segundo pedido com o mesmo `ETag` devolve 304 e corpo vazio; após mudança de dados e novo arranque o `ETag` muda. |
| 🟡 RF-18 | 🟡 O sistema deve fornecer as perdas de transmissão por veículo (`drivetrain_efficiency`, `drivetrain_fixed_loss_kw`) e as funções puras `crank_to_wheel_kw` e `wheel_to_crank_kw`, coerentes com o `dyno-bench`. | Must | Para o hatch (η 0,85, perda fixa 0 kW), `wheel_to_crank_kw(164.1) = 193,1 ± 0,1` e `crank_to_wheel_kw(193.1) = 164,1 ± 0,1`. |
| 🟡 RF-19 | 🟡 O sistema deve fornecer por veículo a calibração OEM de fábrica do perfil de série, com `stock_calibration_id = "stock-<vehicle_id>-<profile_id>"`, arquivo e SHA-256 declarados no `FactoryCalibrationRef`. | Must | `VehicleSpec.stock_calibration_id` do hatch vale `stock-hatch-20t-gdi-oem-stage`; alterar 1 byte do arquivo da calibração gera `CATALOG_INVALID` com `FILE_HASH_MISMATCH`. |
| 🟡 RF-20 | 🟡 O sistema deve validar, a partir do Sprint 2, cada calibração de fábrica com o contrato `Calibration` do `ecu-core`, com `metadata.source = "oem_stock"`, através do gancho `register_calibration_validator`. | Must | Com o pacote `simremap.ecu` presente, uma calibração de fábrica com eixo não monotónico gera `CATALOG_INVALID` com `TABLE_AXIS_NOT_MONOTONIC`; sem o pacote (Sprint 1) só a integridade JSON e o SHA-256 são verificados. |
| 🟡 RF-21 | 🟡 O sistema deve fornecer por veículo um `ReferenceCommandSchedule` (comandos de malha aberta por RPM a plena carga) para os testes do `engine-physics-core` no Sprint 1, antes da existência do `ecu-core`. | Must | O schedule do hatch cobre 2000 a 6500 rpm em passo de 250 rpm com `throttle_pct = 100`, avanço, lambda alvo e MAP alvo por ponto. |
| 🟡 RF-22 | 🟡 O sistema deve fornecer a função pura `compare_to_reference(curve, simulated)` que interpola linearmente a curva simulada nos RPM de referência e devolve o desvio máximo por grandeza em %, com aprovação quando todos os desvios ficam < `tolerance_pct` (padrão 5,0). | Must | Uma curva simulada igual à referência × 1,04 devolve desvio máximo 4,0 % e `passed = true`; × 1,06 devolve 6,0 % e `passed = false`; EGT compara em °C. |
| 🟡 RF-23 | 🟡 O sistema deve recusar com 409 `VEHICLE_NOT_VALIDATED` a obtenção de um veículo `draft` para criar sessão (`get_for_session`), exceto com `SIMREMAP_CATALOG_ALLOW_DRAFTS=true`. | Must | Com a flag `false`, `get_for_session("muscle-v8-sc")` no Sprint 1 lança `VEHICLE_NOT_VALIDATED`; com a flag `true` devolve o `VehicleSpec` e regista `catalog.draft_used`. |
| 🟡 RF-24 | 🟡 O sistema deve calcular `data_sha256` por veículo e `catalog_sha256` global sobre JSON canónico (chaves ordenadas, separadores compactos, UTF-8, floats em `repr`) para que o mesmo conteúdo gere o mesmo hash. | Must | Dois arranques com os mesmos arquivos geram o mesmo `catalog_sha256`; reordenar chaves dentro de um arquivo não muda o hash; alterar um valor muda o hash. |
| 🟡 RF-25 | 🟡 O sistema deve verificar o `manifest.json` (versão semântica `catalog_version` e SHA-256 de cada arquivo) e recusar arquivos ausentes, extra ou alterados. | Must | Um arquivo novo em `vehicles/` não listado no manifesto gera `CATALOG_INVALID` com `FILE_NOT_IN_MANIFEST`. |
| 🟡 RF-26 | 🟡 O sistema deve fornecer `EngineSpec.mbt_reference` opcional (avanço MBT estimado por RPM e MAP) só para avisos da UI, sem uso pelo `engine-physics-core`. | Should | O hatch expõe `mbt_reference` 16×16 marcado em `estimated_fields`; um teste estático confirma que `simremap.physics` não lê `mbt_reference`. |
| 🟡 RF-27 | 🟡 O sistema deve recusar arquivos de dados com tamanho > 2 MiB, links simbólicos que apontam para fora do diretório do catálogo e codificação diferente de UTF-8. | Must | Um link simbólico para `/etc/passwd` dentro de `vehicles/` gera `CATALOG_INVALID` com `PATH_OUTSIDE_CATALOG`; um arquivo de 3 MiB gera `FILE_TOO_LARGE`. |
| 🟡 RF-28 | 🟡 O sistema deve exigir em `MechanicalLimits` de cada veículo os 4 limites mecânicos estruturais `max_rod_load_kn`, `max_cylinder_pressure_bar`, `max_piston_temp_c` e `valve_float_rpm`, consumidos pelo `knock-and-failure-model`. | Must | Arquivo de veículo sem qualquer um dos 4 campos falha no arranque com `CATALOG_INVALID`; o `hatch-20t-gdi` carrega 52 kN, 120 bar, 330 °C e 7200 rpm. |
| 🟡 RF-29 | 🟡 O sistema deve publicar as curvas de série dos 4 veículos como o benchmark canônico oficial do simulador, `Reference Benchmark Baseline v1` (`benchmark_id = "reference-benchmark-baseline-v1"`), com `benchmark_sha256` calculado sobre os arquivos de curva no `manifest.json`, e `compare_to_reference` deve medir o desvio < 5 % de forma determinística contra esse benchmark. | Must | `GET /api/v1/vehicles/{vehicle_id}/reference-curves` devolve `benchmark_id` e `benchmark_sha256` iguais nas 4 respostas; a mesma série simulada comparada 2 vezes dá `max_deviation_pct` idênticos bit a bit; alterar 1 ponto de curva sem mudar a versão falha o arranque com `CATALOG_INVALID`. |

### 6.2 Fluxo Principal (Happy Path)

1. 🟡 O `platform-foundation` executa a etapa `startup.catalog` do lifespan antes de montar os routers; o sistema lê `manifest.json` e verifica o SHA-256 de cada arquivo listado.
2. 🟡 O sistema lê os 4 combustíveis, os 4 `vehicle.json`, as curvas de referência e as calibrações de fábrica, valida cada um com Pydantic v2 e aplica as validações cruzadas (RF-03 a RF-13).
3. 🟡 O sistema calcula `estimated_fields`, `data_sha256` e `catalog_sha256`, guarda o `Catalog` imutável em memória e regista `startup.catalog` com `vehicles = 4`, `validated = 1` (Sprint 1) e a duração em ms.
4. 🟡 O usuário (Lucas) abre a seleção de veículos; a UI chama `GET /api/v1/vehicles` e o sistema devolve 200 com o `hatch-20t-gdi` e `ETag`.
5. 🟡 O usuário abre o detalhe; a UI chama `GET /api/v1/vehicles/hatch-20t-gdi` e o sistema devolve o `VehicleDetail` com limites (biela ~420 N·m, EGT 950 °C) e `estimated_fields`.
6. 🟡 O usuário cria a sessão no `dyno-bench`; o `dyno-bench` chama `catalog.get_for_session("hatch-20t-gdi")` e recebe o `VehicleSpec`, o `FuelSpec` de série (`e27`) e o `stock_calibration_id`.
7. 🟡 O usuário executa a puxada base; a UI chama `GET /api/v1/vehicles/hatch-20t-gdi/reference-curves` e sobrepõe a curva de referência às curvas medidas.
8. 🟡 Resultado: a puxada base fica comparável à referência e `compare_to_reference` devolve desvio máximo < 5 % por grandeza.

### 6.3 Fluxos Alternativos

**Fluxo Alternativo A — Instrutor ou desenvolvedor usa um veículo em `draft`:**
1. 🟡 O usuário define `SIMREMAP_CATALOG_ALLOW_DRAFTS=true` (padrão `true` em `dev` e `false` em `prod`) e reinicia o container.
2. 🟡 O sistema aceita `get_for_session` em veículos `draft`, regista `catalog.draft_used` com o `vehicle_id` e a UI mostra o selo "estimativa a validar".

**Fluxo Alternativo B — Validação de um veículo no Sprint 4:**
1. 🟡 O desenvolvedor ajusta os campos estimados (`true_ve`, Chen-Flynn, mapa do compressor) dentro dos limites do contrato e executa `test_reference_curves.py` do `engine-physics-core`.
2. 🟡 Com desvio < 5 % em todas as grandezas da curva de série, o desenvolvedor muda `validation_status` para `validated`, define `validated_on`, incrementa `data_version`, regenera o manifesto (`uv run python -m simremap.catalog.tools.rehash`) e faz commit.
3. 🟡 O teste de CI `test_validated_vehicles_pass_reference` falha se algum veículo `validated` não cumprir o desvio < 5 %.

**Fluxo Alternativo C — Curva de referência sem lambda ou EGT:**
1. 🟡 A curva declara só as grandezas disponíveis em `quantities` (ex.: `torque_crank_nm`, `power_wheel_kw`) e os pontos têm `lambda_value = null` e `egt_c = null`.
2. 🟡 O sistema compara só as grandezas declaradas; a resposta de `compare_to_reference` lista as grandezas ausentes em `not_compared`.

**Fluxo Alternativo D — Cliente com cache válida:**
1. 🟡 A UI repete `GET /api/v1/vehicles` com `If-None-Match` igual ao `ETag` anterior.
2. 🟡 O sistema devolve 304 sem corpo e a UI usa a cópia local.

---

## 7. Requisitos Não-Funcionais

| ID | Requisito | Valor alvo | Observação |
|----|-----------|-----------|------------|
| 🟡 RNF-01 | Tempo de arranque do catálogo | ≤ 500 ms para carga, validação e hash dos 4 veículos | 🟡 Medido pelo evento `startup.catalog` no hardware de referência (4 núcleos, 8 GB) |
| 🟡 RNF-02 | Latência dos endpoints | P95 < 20 ms em `GET /api/v1/vehicles` e P95 < 50 ms em `GET /api/v1/vehicles/{vehicle_id}` | 🟡 Dados em memória; serialização pré-calculada por `data_sha256` |
| 🟡 RNF-03 | Tamanho das respostas | `VehicleDetail` ≤ 256 KiB; lista ≤ 16 KiB | 🟡 Grelhas até 32×32 em float |
| 🟡 RNF-04 | Memória | ≤ 32 MB de RSS adicional para o catálogo carregado | 🟡 Modelos `frozen`, partilhados por referência |
| 🟡 RNF-05 | Determinismo | `catalog_sha256` idêntico em 100 % dos arranques com os mesmos arquivos | 🟡 JSON canónico (RF-24); entra no log de cada puxada |
| 🟡 RNF-06 | Qualidade | Cobertura ≥ 85 % no pacote `catalog`, `mypy --strict` com 0 erros, `bandit` sem achados médios ou altos | 🟡 Portões do `platform-foundation` |
| 🟡 RNF-07 | Operação offline | 100 % dos dados e fontes disponíveis sem rede | 🟡 Local-first (PRD) |
| 🟡 RNF-08 | Compliance de marcas | 0 termos da lista do Apêndice A.6 em textos exibidos | 🟡 Teste `test_no_trademarks.py` no CI |

---

## 8. Design e Interface

**Componentes afetados:**
- 🟡 `backend/src/simremap/catalog/` (novo): `contracts.py` (modelos Pydantic), `grids.py` (`Grid1D`, `Grid2D`, interpolação), `loader.py` (leitura, manifesto, validação cruzada), `service.py` (`CatalogService`), `provenance.py` (`estimated_fields`), `trademarks.py` (lista de termos), `drivetrain.py` (conversões whp ↔ virabrequim), `compare.py` (`compare_to_reference`), `errors.py` (registo de `code`), `tools/rehash.py` e `tools/gen_ve.py`.
- 🟡 `backend/src/simremap/catalog/data/` (novo): `manifest.json`, `fuels/<fuel_id>.json`, `vehicles/<vehicle_id>/vehicle.json`, `vehicles/<vehicle_id>/reference-curves/<curve_id>.json`, `vehicles/<vehicle_id>/calibrations/<profile_id>.json`.
- 🟡 `backend/src/simremap/api/routers/vehicles.py` (novo): os 3 endpoints.
- 🟡 Frontend: `frontend/src/lib/api/vehicles.ts` (cliente tipado com `ETag`); a seleção de veículo e a sobreposição da curva pertencem a `dyno-cockpit-ui`.

**Interface interna (contrato para os outros componentes):**

```python
class CatalogService:
    """Instância única criada no lifespan; imutável após o arranque."""
    catalog_version: str            # semver do manifest.json, ex.: "1.0.0"
    catalog_sha256: str             # 64 hex

    def list_vehicles(self, include_drafts: bool = False) -> list[ "VehicleSummary" ]: ...
    def get_vehicle(self, vehicle_id: str) -> "VehicleSpec": ...          # VEHICLE_NOT_FOUND
    def get_for_session(self, vehicle_id: str) -> "VehicleSpec": ...      # + VEHICLE_NOT_VALIDATED
    def get_fuel(self, fuel_id: str) -> "FuelSpec": ...                   # FUEL_NOT_FOUND
    def get_reference_curves(self, vehicle_id: str, fuel_id: str | None = None,
                             calibration_ref: str = "stock") -> list[ "ReferenceCurve" ]: ...
    def get_reference_command_schedule(self, vehicle_id: str) -> "ReferenceCommandSchedule": ...
    def get_factory_calibration_payload(self, vehicle_id: str, profile_id: str) -> dict[ str, object ]: ...

def register_calibration_validator(fn: "Callable[ [ dict[ str, object ] ], None ]") -> None:
    """Chamado pelo ecu-core no import; o loader valida as calibrações de fábrica com fn."""

def crank_to_wheel_kw(vehicle: "VehicleSpec", power_crank_kw: float) -> float: ...
def wheel_to_crank_kw(vehicle: "VehicleSpec", power_wheel_kw: float) -> float: ...
def compare_to_reference(curve: "ReferenceCurve",
                         simulated: list[ "ReferenceCurvePoint" ]) -> "ReferenceComparison": ...
```

- 🟡 O worker do laço físico recebe o `VehicleSpec` e o `FuelSpec` serializados (`model_dump_json`) e reconstrói os modelos no processo filho; o worker nunca lê os arquivos do catálogo.
- 🟡 `wheel_to_crank_kw(v, p) = (p + v.drivetrain_fixed_loss_kw) / v.drivetrain_efficiency`; `crank_to_wheel_kw(v, p) = p · v.drivetrain_efficiency − v.drivetrain_fixed_loss_kw`; `whp = power_wheel_kw / 0,7457`.

**Endpoints REST:**

| Método e caminho | Request | Resposta | Erros |
|---|---|---|---|
| 🟡 `GET /api/v1/vehicles` | query `include_drafts: bool = false` | 200 `VehicleListResponse`; header `ETag` | 304 com `If-None-Match` igual; 422 `VALIDATION_ERROR` para query inválida |
| 🟡 `GET /api/v1/vehicles/{vehicle_id}` | path `vehicle_id` com padrão `^[0-9a-z]+(-[0-9a-z]+){1,5}$` | 200 `VehicleDetail`; header `ETag` | 404 `VEHICLE_NOT_FOUND`; 422 `VEHICLE_ID_INVALID`; 304 |
| 🟡 `GET /api/v1/vehicles/{vehicle_id}/reference-curves` | query `fuel_id` (FuelId opcional), `calibration_ref` (padrão `stock`) | 200 `ReferenceCurveListResponse`; header `ETag` | 404 `VEHICLE_NOT_FOUND`; 404 `REFERENCE_CURVE_NOT_FOUND`; 422 `VALIDATION_ERROR`; 304 |

- 🟡 Todos os erros usam `application/problem+json` com `ProblemDetail` do `platform-foundation`; `Cache-Control: no-cache` em todas as respostas 200.
- 🟡 O endpoint de detalhe devolve veículos `draft` com 200 e `validation_status = "draft"`, para a UI mostrar o selo; só a criação de sessão é bloqueada (RF-23).

**Registo de `code` de erro (via `register_error`):**

| Code | Status | Quando |
|---|---|---|
| 🟡 `VEHICLE_NOT_FOUND` | 404 | `vehicle_id` com padrão válido e inexistente |
| 🟡 `VEHICLE_ID_INVALID` | 422 | `vehicle_id` fora do padrão slug |
| 🟡 `VEHICLE_NOT_VALIDATED` | 409 | Sessão pedida para veículo `draft` com drafts desligados |
| 🟡 `REFERENCE_CURVE_NOT_FOUND` | 404 | Nenhuma curva para o filtro pedido |
| 🟡 `FUEL_NOT_FOUND` | 404 | `fuel_id` desconhecido em chamada interna |
| 🟡 `FUEL_NOT_ALLOWED` | 409 | Combustível fora de `allowed_fuel_ids` do veículo (usado por `ecu-profiles` e `dyno-bench`) |
| 🟡 `CATALOG_INVALID` | 500 | Só no arranque; nunca devolvido por HTTP (o arranque falha antes dos routers) |

**Comportamento esperado na UI (consumida por `dyno-cockpit-ui`):**
- 🟡 Estado vazio: sem veículos `validated` e com drafts desligados, a lista mostra "Nenhum veículo validado nesta versão".
- 🟡 Estado de carregamento: esqueleto de 4 cartões enquanto `GET /api/v1/vehicles` não responde (o pedido falha em timeout de 5 s).
- 🟡 Estado de erro: problem+json mostrado com `title` e botão "Tentar de novo" (retry manual).
- 🟡 Estado de sucesso: cartão com `display_name`, `architecture_note`, `rated.peak_power_whp`, `stock_fuel_id`, selo `validated` ou "estimativa a validar"; no detalhe, cada campo de `estimated_fields` mostra o ícone de estimativa com a nota de proveniência.

---

## 9. Modelo de Dados

🟡 O catálogo não cria tabelas no banco nem migração Alembic. Os dados são arquivos JSON versionados no repositório e empacotados na imagem Docker. As sessões e puxadas do `dyno-bench` guardam `vehicle_id`, `data_version` e `catalog_sha256` para auditoria e replay.

**Contratos Pydantic v2 (`simremap/catalog/contracts.py`):**

```python
import math
from datetime import date
from enum import StrEnum
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

VehicleId = Annotated[ str, Field(pattern=r"^[0-9a-z]+(-[0-9a-z]+){1,5}$", max_length=48) ]
FuelId = Literal["e27", "e100", "podium", "e0"]
ProfileIdLiteral = Literal["oem-stage", "ft-pro", "m1-race", "ht-elite"]  # igual a EcuProfileId
Quantity = Literal["torque_crank_nm", "power_wheel_kw", "lambda_value", "egt_c"]
AxisName = Literal["rpm", "map_kpa", "cam_deg", "battery_v", "dp_kpa", "pressure_ratio"]


class CatalogModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class ProvenanceKind(StrEnum):
    PRD = "prd"                    # valor exato da seção 7 do PRD
    PUBLIC_SPEC = "public_spec"    # ficha técnica pública da arquitetura de inspiração
    LITERATURE = "literature"      # Heywood ou outra literatura aberta
    DERIVED = "derived"            # calculado de outros campos (ex.: cilindrada)
    ESTIMATE = "estimate"          # inferido, a validar


class Provenance(CatalogModel):
    kind: ProvenanceKind
    note: str = Field("", max_length=300)
    source: str | None = Field(None, max_length=300)   # citação textual; obrigatório em public_spec/literature


class Grid1D(CatalogModel):
    x_name: AxisName
    x_values: list[ float ] = Field(min_length=2, max_length=32)   # estritamente crescente
    values: list[ float ] = Field(min_length=2, max_length=32)     # len == len(x_values)


class Grid2D(CatalogModel):
    x_name: AxisName                                              # colunas (ex.: rpm)
    x_values: list[ float ] = Field(min_length=2, max_length=32)
    y_name: AxisName                                              # linhas (ex.: map_kpa)
    y_values: list[ float ] = Field(min_length=2, max_length=32)
    z_values: list[ list[ float ] ]                                 # len(y) linhas × len(x) colunas
    # validação: eixos estritamente crescentes, dimensões coerentes, valores finitos;
    # interpolação bilinear com saturação nas bordas (sem extrapolação)


class VvtSpec(CatalogModel):
    intake_min_deg: float = Field(0.0, ge=-10.0, le=10.0)          # graus de cambota, + = avanço
    intake_max_deg: float = Field(..., ge=0.0, le=80.0)
    exhaust_min_deg: float | None = Field(None, ge=-10.0, le=10.0) # None = sem VVT de escape
    exhaust_max_deg: float | None = Field(None, ge=0.0, le=80.0)
    actuator_tau_s: float = Field(0.15, ge=0.02, le=1.0)
    k_vvt: float = Field(0.06, ge=0.0, le=0.20)                    # ganho máximo de VE pelo VVT
    g_vvt: Grid2D                                                  # x = rpm, y = cam_deg, valores −1..1


class IntercoolerSpec(CatalogModel):
    kind: Literal["air_to_air", "air_to_water"]
    effectiveness: float = Field(0.75, ge=0.40, le=0.95)            # ε
    k_dp_kpa_per_kgps2: float = Field(..., ge=0.0, le=200.0)        # Δp_ic = k · ṁ²


class ChenFlynnSpec(CatalogModel):
    c_bar: float = Field(0.25, ge=0.0, le=1.0)
    a: float = Field(0.005, ge=0.0, le=0.02)
    b_bar_s_m: float = Field(0.09, ge=0.0, le=0.3)
    q_bar_s2_m2: float = Field(0.0009, ge=0.0, le=0.005)


class EngineSpec(CatalogModel):
    architecture: Literal["inline", "v"]
    n_cyl: int = Field(..., ge=3, le=8)
    v_angle_deg: float | None = Field(None, ge=45.0, le=120.0)      # obrigatório se architecture == "v"
    bore_mm: float = Field(..., ge=60.0, le=110.0)
    stroke_mm: float = Field(..., ge=60.0, le=110.0)
    rod_length_mm: float = Field(..., ge=100.0, le=200.0)
    compression_ratio: float = Field(..., ge=7.0, le=14.0)
    displacement_cc: float = Field(..., ge=500.0, le=8000.0)         # validado ±0,5 % pela geometria
    valvetrain: Literal["sohc", "dohc", "ohv"]
    valves_per_cyl: Literal[2, 3, 4, 5]
    firing_order: list[ int ]                                         # permutação de 1..n_cyl, começa em 1
    ivc_deg_abdc: float = Field(..., ge=0.0, le=90.0)                # fecho da admissão após PMI, VVT a 0
    evo_deg_bbdc: float = Field(..., ge=0.0, le=90.0)                # abertura do escape antes do PMI
    vvt: VvtSpec | None = None
    injection_type: Literal["gdi", "pfi"]
    throttle_diameter_mm: float = Field(..., ge=30.0, le=120.0)
    throttle_location: Literal["post_compressor", "pre_compressor"] = "post_compressor"
    intake_manifold_volume_l: float = Field(..., gt=0.5, le=20.0)
    boost_volume_l: float | None = Field(None, gt=0.5, le=20.0)      # None em pre_compressor
    exhaust_manifold_volume_l: float = Field(..., gt=0.2, le=10.0)
    intercooler: IntercoolerSpec | None = None
    recip_mass_g: float = Field(..., ge=200.0, le=1500.0)             # pistão + pino + anéis + pé da biela
    true_ve: Grid2D                                                   # x = rpm, y = map_kpa, 0,20..1,35
    mbt_reference: Grid2D | None = None                               # só UI (RF-26), graus BTDC
    wiebe_duration_ref_deg: float = Field(55.0, ge=30.0, le=90.0)
    wiebe_rpm_ref: float = Field(3000.0, ge=1000.0, le=8000.0)
    friction: ChenFlynnSpec = ChenFlynnSpec()
    crank_trigger: Literal["60-2", "36-1", "36-2", "24-1"] = "60-2"    # roda fônica de série
    cam_sync: Literal["1x", "4x", "none"] = "1x"

    @computed_field
    @property
    def calc_displacement_cc(self) -> float:
        return math.pi / 4 * (self.bore_mm / 10) ** 2 * (self.stroke_mm / 10) * self.n_cyl


class CompressorMapSpec(CatalogModel):        # forma paramétrica do engine-physics-core A.8
    pr_design: float = Field(..., ge=1.5, le=4.5)
    n_design_rpm: float = Field(..., ge=50_000, le=300_000)
    n_max_rpm: float = Field(..., ge=50_000, le=320_000)
    m_choke_max_kg_s: float = Field(..., gt=0.05, le=1.5)
    eta_max: float = Field(..., ge=0.60, le=0.82)
    m_peak_kg_s: float = Field(..., gt=0.02, le=1.2)
    m_range_kg_s: float = Field(..., gt=0.02, le=1.0)
    k1: float = Field(0.6, ge=0.0, le=2.0)
    k2: float = Field(0.4, ge=0.0, le=2.0)
    n_peak_rpm: float = Field(..., ge=30_000, le=300_000)
    table: Grid2D | None = None   # mapa tabelado (x = pressure_ratio, y = rpm) substitui a forma paramétrica


class TurboSpec(CatalogModel):
    housing: Literal["single_scroll", "twin_scroll"]
    compressor_ar: float | None = Field(None, gt=0.2, le=1.5)        # ex.: 0,50 no classic
    turbine_ar: float | None = Field(None, gt=0.2, le=1.5)           # ex.: 0,63 no classic
    rotor_inertia_kg_m2: float = Field(..., gt=1e-6, le=5e-4)
    bearing_friction_k: float = Field(..., ge=0.0, le=1e-6)          # P_fric = k · ω², W·s²
    turbine_area_eff_cm2: float = Field(..., gt=1.0, le=40.0)
    turbine_efficiency: Grid1D                                        # x = pressure_ratio
    wastegate_kind: Literal["internal", "external"]
    wastegate_area_max_cm2: float = Field(..., gt=0.5, le=20.0)
    wastegate_spring_kpa: float = Field(..., ge=20.0, le=200.0)       # relativa
    wastegate_full_open_delta_kpa: float = Field(40.0, gt=5.0, le=150.0)
    blow_off_valve: bool = True
    compressor: CompressorMapSpec


class SuperchargerSpec(CatalogModel):
    sc_type: Literal["roots", "twin_screw"]
    displacement_l_per_rev: float = Field(..., gt=0.5, le=5.0)
    pulley_ratio: float = Field(..., ge=1.0, le=4.0)
    k_leak: float = Field(0.08, ge=0.0, le=0.5)
    n_ref_rpm: float = Field(10_000, ge=2_000, le=25_000)
    adiabatic_efficiency: Grid1D                                      # x = pressure_ratio
    mech_efficiency: float = Field(0.90, ge=0.70, le=0.98)
    bypass_valve: bool = True
    max_rotor_rpm: float = Field(..., ge=5_000, le=30_000)


class InjectorSpec(CatalogModel):
    count_per_cyl: Literal[1, 2] = 1
    flow_cc_min: float = Field(..., gt=50.0, le=5000.0)               # vazão estática a dp_ref_kpa
    dp_ref_kpa: float = Field(..., gt=100.0, le=40_000.0)
    rail_pressure_min_kpa: float = Field(..., gt=100.0, le=40_000.0)
    rail_pressure_max_kpa: float = Field(..., gt=100.0, le=40_000.0)
    pressure_reference: Literal["manifold", "atmosphere", "cylinder"]  # GDI usa cylinder
    dead_time_ms: Grid2D                                              # x = battery_v, y = dp_kpa
    min_pulse_ms: float = Field(0.3, ge=0.0, le=3.0)
    max_duty_pct: float = Field(85.0, ge=50.0, le=100.0)


class FuelSpec(CatalogModel):
    fuel_id: FuelId
    display_name: str = Field(..., min_length=3, max_length=60)
    afr_stoich: float = Field(..., ge=8.0, le=15.5)
    lhv_mj_kg: float = Field(..., ge=20.0, le=45.0)                    # PCI
    ron: float = Field(..., ge=80.0, le=120.0)
    mon: float = Field(..., ge=70.0, le=110.0)
    knock_on: float = Field(..., ge=80.0, le=120.0)                    # ON usado em Douaud-Eyzat
    h_fg_kj_kg: float = Field(..., ge=200.0, le=1200.0)
    density_kg_m3: float = Field(..., ge=650.0, le=850.0)
    ethanol_mass_fraction: float = Field(..., ge=0.0, le=1.0)
    laminar_bm_m_s: float
    laminar_bphi_m_s: float
    laminar_phi_m: float
    preignition_surface_temp_c: float = Field(..., ge=600.0, le=1100.0)
    provenance: dict[ str, Provenance ] = Field(default_factory=dict)

    @computed_field
    @property
    def density_g_cc(self) -> float:           # nome consumido pelo ecu-core
        return self.density_kg_m3 / 1000.0


class MechanicalLimits(CatalogModel):
    rod_torque_limit_nm: float = Field(..., gt=100.0, le=3000.0)       # torque de freio sustentado na cambota
    max_rod_load_kn: float = Field(..., gt=10.0, le=300.0)            # força de pico admissível por biela (kN)
    max_cylinder_pressure_bar: float = Field(..., ge=60.0, le=250.0)  # pressão de pico admissível no cilindro (bar abs.)
    egt_max_c: float = Field(..., ge=750.0, le=1100.0)                 # pré-turbina
    max_rpm: float = Field(..., ge=4000.0, le=10_000.0)                # rotação máxima segura
    rev_limit_rpm: float = Field(..., ge=3000.0, le=10_000.0)          # corte de fábrica, ≤ max_rpm
    valve_float_rpm: float = Field(..., ge=4000.0, le=11_000.0)        # > max_rpm
    turbo_max_rpm: float | None = Field(None, ge=50_000, le=320_000)   # obrigatório só em turbo
    max_piston_temp_c: float = Field(..., ge=250.0, le=450.0)          # coroa do pistão

    @computed_field
    @property
    def egt_limit_c(self) -> float:            # sinónimo usado pelo dyno-bench (RF-15 dele)
        return self.egt_max_c


class RatedFigures(CatalogModel):
    peak_power_whp: float = Field(..., gt=50.0, le=1500.0)
    peak_power_rpm: float
    peak_torque_nm: float = Field(..., gt=50.0, le=2000.0)             # no virabrequim
    peak_torque_rpm_from: float
    peak_torque_rpm_to: float
    power_ceiling_whp: float | None = None    # teto informativo do PRD (ex.: 750, 600, 800)
    power_range_whp: tuple[ float, float ] | None = None               # ex.: (300, 600) no classic


class ReferenceCommandPoint(CatalogModel):
    rpm: float
    throttle_pct: float = Field(100.0, ge=0.0, le=100.0)
    ignition_advance_deg: float = Field(..., ge=-30.0, le=60.0)       # BTDC
    lambda_target: float = Field(..., ge=0.65, le=1.10)
    map_target_kpa: float = Field(..., ge=20.0, le=400.0)
    wastegate_duty_pct: float = Field(0.0, ge=0.0, le=100.0)
    vvt_intake_deg: float = 0.0
    vvt_exhaust_deg: float = 0.0
    injection_end_deg_btdc: float | None = None


class ReferenceCommandSchedule(CatalogModel):
    vehicle_id: VehicleId
    fuel_id: FuelId
    points: list[ ReferenceCommandPoint ] = Field(min_length=8, max_length=64)  # rpm crescente, passo 250


class FactoryCalibrationRef(CatalogModel):
    profile_id: ProfileIdLiteral
    calibration_id: str = Field(pattern=r"^stock-[0-9a-z-]+-(oem-stage|ft-pro|m1-race|ht-elite)$")
    file: str = Field(pattern=r"^calibrations/[0-9a-z-]+\.json$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class VehicleSpec(CatalogModel):
    vehicle_id: VehicleId
    display_name: str = Field(..., min_length=3, max_length=60)       # genérico, sem marcas
    architecture_note: str = Field(..., min_length=10, max_length=160)
    body: Literal["hatch", "sedan", "coupe"]
    data_version: int = Field(..., ge=1)
    validation_status: Literal["draft", "validated"]
    validated_on: date | None = None                                  # obrigatório se validated
    induction: Literal["turbo", "supercharger", "natural"]
    engine: EngineSpec
    turbo: TurboSpec | None = None
    supercharger: SuperchargerSpec | None = None
    injectors: InjectorSpec
    stock_fuel_id: FuelId
    allowed_fuel_ids: list[ FuelId ] = Field(min_length=1)
    drive_layout: Literal["fwd", "rwd", "awd"]
    gear_ratios: list[ float ] = Field(min_length=4, max_length=10)    # 1ª..n, decrescente
    final_drive_ratio: float = Field(..., ge=2.0, le=5.5)
    tire_radius_m: float = Field(..., ge=0.25, le=0.40)                # raio dinâmico
    drivetrain_efficiency: float = Field(..., ge=0.70, le=0.95)       # η_drv
    drivetrain_fixed_loss_kw: float = Field(0.0, ge=0.0, le=20.0)      # P_fixa
    driveline_inertia_kg_m2: float = Field(..., gt=0.5, le=10.0)       # vista na roda
    mechanical_limits: MechanicalLimits
    rated: RatedFigures
    stock_profile_id: ProfileIdLiteral
    stock_calibration_id: str
    factory_calibrations: list[ FactoryCalibrationRef ] = Field(min_length=1)
    reference_command_schedule: ReferenceCommandSchedule
    reference_curve_ids: list[ str ] = Field(min_length=1)
    provenance: dict[ str, Provenance ] = Field(default_factory=dict)  # chave = ponteiro JSON

    @model_validator(mode="after")
    def _cross_checks(self) -> "VehicleSpec":
        # RF-03, RF-04, RF-08, RF-09, RF-11, RF-19; erros com ponteiro JSON e code interno
        return self
```

**Curvas de referência:**

```python
class ReferenceCurvePoint(CatalogModel):
    rpm: float = Field(..., ge=500.0, le=10_000.0)
    torque_crank_nm: float | None = Field(None, ge=0.0)
    power_wheel_kw: float | None = Field(None, ge=0.0)
    lambda_value: float | None = Field(None, ge=0.6, le=1.3)
    egt_c: float | None = Field(None, ge=200.0, le=1100.0)

    @computed_field
    @property
    def power_wheel_whp(self) -> float | None:
        return None if self.power_wheel_kw is None else self.power_wheel_kw / 0.7457


class ReferenceConditions(CatalogModel):
    correction: Literal["sae_j1349", "din_70020", "uncorrected"] = "sae_j1349"
    ambient_temp_c: float = 25.0
    ambient_pressure_kpa: float = 99.0
    dyno_type: Literal["inertial_roller", "loaded_roller", "engine_dyno"] = "inertial_roller"
    gear: int = Field(4, ge=1, le=10)


class ReferenceCurve(CatalogModel):
    curve_id: str = Field(pattern=r"^[0-9a-z-]{3,64}$")               # ex.: "stock-e27"
    vehicle_id: VehicleId
    calibration_ref: str = "stock"                                    # "stock" ou calibration_id
    fuel_id: FuelId
    conditions: ReferenceConditions = ReferenceConditions()
    quantities: list[ Quantity ] = Field(min_length=1, max_length=4)
    points: list[ ReferenceCurvePoint ] = Field(min_length=8, max_length=64)
    source: str = Field(..., min_length=5, max_length=300)
    license: str = Field(..., min_length=2, max_length=64)            # SPDX ou "internal-estimate"
    confidence: Literal["measured", "published", "estimated"]
    quantity_confidence: dict[ str, Literal["measured", "published", "estimated"] ] = Field(default_factory=dict)
    tolerance_pct: float = Field(5.0, gt=0.0, le=20.0)
    benchmark_id: Literal["reference-benchmark-baseline-v1"] = "reference-benchmark-baseline-v1"  # benchmark canônico oficial (revisão R1)


class QuantityDeviation(CatalogModel):
    quantity: Quantity
    max_deviation_pct: float
    rpm_at_max: float
    points_compared: int


class ReferenceComparison(CatalogModel):
    curve_id: str
    deviations: list[ QuantityDeviation ]
    not_compared: list[ Quantity ]
    passed: bool
```

**Respostas da API:**

```python
class VehicleSummary(CatalogModel):
    vehicle_id: VehicleId
    display_name: str
    architecture_note: str
    body: str
    induction: str
    n_cyl: int
    displacement_cc: float
    stock_fuel_id: FuelId
    stock_profile_id: ProfileIdLiteral
    rated: RatedFigures
    validation_status: Literal["draft", "validated"]
    data_version: int


class VehicleListResponse(CatalogModel):
    catalog_version: str
    catalog_sha256: str
    items: list[ VehicleSummary ]


class VehicleDetail(VehicleSpec):
    estimated_fields: list[ str ]         # ponteiros JSON ordenados
    data_sha256: str
    catalog_version: str
    fuels: list[ FuelSpec ]               # os combustíveis de allowed_fuel_ids


class ReferenceCurveListResponse(CatalogModel):
    vehicle_id: VehicleId
    catalog_sha256: str
    benchmark_id: Literal["reference-benchmark-baseline-v1"] = "reference-benchmark-baseline-v1"
    benchmark_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")   # hash dos arquivos de curva das 4 viaturas
    items: list[ ReferenceCurve ]
```

**Regras de comparação (`compare_to_reference`):**
- 🟡 Para cada grandeza `q` em `curve.quantities`, interpola-se a série simulada linearmente nos RPM de referência que estejam dentro do intervalo simulado; pontos fora do intervalo não contam.
- 🟡 `dev_pct(q, rpm) = |sim − ref| / |ref| · 100`; para `egt_c` a base é o valor em °C (convenção do `engine-physics-core`).
- 🟡 `passed = true` quando, para todas as grandezas comparadas, `max dev_pct < tolerance_pct` e `points_compared ≥ 8`.

**Formato do `manifest.json`:**

```json
{
  "catalog_version": "1.0.0",
  "files": [
    {"path": "fuels/e27.json", "sha256": "<64 hex>"},
    {"path": "vehicles/hatch-20t-gdi/vehicle.json", "sha256": "<64 hex>"}
  ]
}
```

---

## 10. Integrações e Dependências

| Dependência | Tipo | Impacto se indisponível |
|-------------|------|------------------------|
| 🟡 `platform-foundation` (lifespan, `register_error`, `ProblemDetail`, `Settings`, logging JSON) | Obrigatória | 🟡 Sem a fundação o catálogo não arranca; a etapa `startup.catalog` corre depois de `startup.cache` e antes de `startup.routers` |
| 🟡 `engine-physics-core` (consumidor de `VehicleSpec`, `FuelSpec`, `true_ve`, `ReferenceCommandSchedule`) | Consumidor interno | 🟡 Sem consumidor o catálogo funciona; o teste de referência do Sprint 1 depende dos dois |
| 🟡 `dyno-bench` (consumidor de transmissão, perdas, inércia, `MechanicalLimits`, `stock_calibration_id`, `ReferenceCurve`) | Consumidor interno | 🟡 Sessão recusada com 404 `VEHICLE_NOT_FOUND` ou 409 `VEHICLE_NOT_VALIDATED` |
| 🟡 `ecu-core` (contrato `Calibration` para validar calibrações de fábrica; consome `displacement_cc`, `n_cyl`, `afr_stoich`, `density_g_cc`, `egt_max_c`) | Obrigatória a partir do Sprint 2 | 🟡 No Sprint 1 o validador não está registado; só integridade JSON e SHA-256 |
| 🟡 `ecu-profiles` (`EcuProfileId`, `BaseSetup` usa bicos e roda fônica do catálogo) | Consumidor interno (Sprint 3) | 🟡 Teste garante `ProfileIdLiteral` igual ao enum `EcuProfileId` |
| 🟡 `knock-and-failure-model` (consumidor de `MechanicalLimits` e `FuelSpec.knock_on`, `preignition_surface_temp_c`) | Consumidor interno | 🟡 Sem consumidor nenhum dano é calculado; o catálogo não muda |
| 🟡 `dyno-cockpit-ui` e `ecu-tuning-ui` (consumidores REST) | Consumidor externo | 🟡 Sem catálogo a UI mostra o estado de erro e não sobrepõe referência |
| 🟡 Literatura aberta (Heywood) e fichas técnicas públicas das arquiteturas de inspiração | Referência de dados | 🟡 Valores sem fonte ficam como `estimate` (RF-06) |
| 🟡 Pydantic v2 e biblioteca padrão (`json`, `hashlib`, `pathlib`) | Biblioteca | 🟡 Sem dependência nova; YAML não é usado |

---

## 11. Edge Cases e Tratamento de Erros

| Cenário | Trigger | Comportamento esperado |
|---------|---------|----------------------|
| 🟡 EC-01: Diretório do catálogo indisponível | `SIMREMAP_CATALOG_DIR` aponta para caminho inexistente ou sem permissão de leitura | O arranque falha com `startup.failed`, `code = CATALOG_INVALID`, código de saída 4; sem retry e sem fallback para dados embutidos, porque um motor com dados parciais viola a meta de 5 %. |
| 🟡 EC-02: JSON malformado | Vírgula extra ou codificação não UTF-8 num `vehicle.json` | O arranque falha com `CATALOG_INVALID` indicando arquivo, linha e coluna do erro de parse. |
| 🟡 EC-03: Arquivo alterado sem rehash | SHA-256 do arquivo difere do `manifest.json` | Falha com `FILE_HASH_MISMATCH` e os dois hashes no log; o desenvolvedor executa `tools/rehash.py`. |
| 🟡 EC-04: Geometria incoerente | Cilindrada declarada difere > 0,5 % da calculada | Falha com ponteiro `/engine/displacement_cc`, valor declarado e calculado. |
| 🟡 EC-05: Grelha física inválida | Eixo não monotónico, dimensão errada, NaN ou VE fora de 0,20..1,35 | Falha com `GRID_AXIS_NOT_MONOTONIC`, `GRID_SHAPE_MISMATCH` ou `GRID_VALUE_OUT_OF_RANGE` e o ponteiro da célula. |
| 🟡 EC-06: Marca registada no texto exibido | `display_name` contém termo da lista A.6 | Falha com `TRADEMARK_IN_DISPLAY_TEXT`; o termo encontrado é registado no log. |
| 🟡 EC-07: Curva de referência incompleta | Curva sem lambda e EGT | Aceite se `quantities` só declarar as grandezas presentes; `compare_to_reference` lista as ausentes em `not_compared`; um ponto com valor nulo numa grandeza declarada gera falha `REFERENCE_POINT_MISSING_VALUE`. |
| 🟡 EC-08: Curva incoerente com a transmissão | `power_wheel_kw` difere > 1 % de `torque · ω · η_drv − P_fixa` | Falha com `REFERENCE_CURVE_INCONSISTENT` e o RPM do primeiro ponto divergente. |
| 🟡 EC-09: Veículo inexistente | `GET /api/v1/vehicles/abc-def` | 404 `VEHICLE_NOT_FOUND` em `application/problem+json`. |
| 🟡 EC-10: `vehicle_id` com formato inválido | `GET /api/v1/vehicles/../etc` ou letras maiúsculas | 422 `VEHICLE_ID_INVALID`; o caminho nunca é usado para ler arquivos (o catálogo está em memória). |
| 🟡 EC-11: Sessão em veículo `draft` | `get_for_session("coupe-30t-i6")` no Sprint 1 com drafts desligados | 409 `VEHICLE_NOT_VALIDATED` com `detail` "veículo em validação, previsto para o Sprint 4". |
| 🟡 EC-12: Calibração de fábrica inválida | Validador do `ecu-core` recusa o arquivo | O arranque falha com `CATALOG_INVALID` e o `code` original do `ecu-core` (ex.: `TABLE_AXIS_NOT_MONOTONIC`). |
| 🟡 EC-13: Validador do `ecu-core` com falha interna | O validador registado lança exceção não prevista | O arranque falha com `CATALOG_INVALID` e `CALIBRATION_VALIDATOR_ERROR`; não há fallback silencioso. |
| 🟡 EC-14: Link simbólico ou arquivo grande | Link para fora do diretório ou arquivo > 2 MiB | Falha com `PATH_OUTSIDE_CATALOG` ou `FILE_TOO_LARGE` antes do parse. |
| 🟡 EC-15: Combustível não permitido | `ecu-profiles` pede `e100` para o `muscle-v8-sc` | 409 `FUEL_NOT_ALLOWED` com a lista `allowed_fuel_ids` no `detail`. |
| 🟡 EC-16: Pedido lento do cliente | A UI não recebe resposta em 5 s (timeout do cliente) | O cliente mostra o estado de erro e oferece retry; o servidor não guarda estado do pedido. |

---

## 12. Segurança e Privacidade

- 🟡 **Autenticação:** nenhuma. Os 3 endpoints são só de leitura e servem uma aplicação local-first que escuta em `127.0.0.1` por padrão (`platform-foundation`).
- 🟡 **Autorização:** sem papéis. Nenhum endpoint escreve dados; o catálogo é imutável em runtime.
- 🟡 **Dados sensíveis:** nenhum PII. O catálogo só contém dados técnicos de motores.
- 🟡 **Integridade:** manifesto com SHA-256 por arquivo (RF-25), `catalog_sha256` no log de cada puxada para auditoria e replay.
- 🟡 **Entrada:** `vehicle_id` validado por regex antes de qualquer lookup; os arquivos são lidos só no arranque com `json.loads` (sem `eval`, sem YAML, sem pickle); links simbólicos e arquivos > 2 MiB são recusados (RF-27).
- 🟡 **Compliance de marcas:** a lista de termos do Apêndice A.6 bloqueia marcas em textos exibidos; a inspiração técnica fica só nesta spec e em `provenance.note`, que a UI não exibe.

---

## 13. Plano de Rollout

- 🟡 **Estratégia:** entrega incremental. Sprint 1: contratos, loader, endpoints, 4 combustíveis e 4 `vehicle.json` completos; `hatch-20t-gdi` em `validated` após o teste de referência do `engine-physics-core`; os 3 restantes em `draft` com estimativas. Sprint 2: registo do validador de calibração do `ecu-core`. Sprint 4: `coupe-30t-i6`, `classic-20t-swap` e `muscle-v8-sc` passam a `validated`.
- 🟡 **Feature flag:** `SIMREMAP_CATALOG_ALLOW_DRAFTS` (padrão `true` em `dev`/`test`, `false` em `staging`/`prod`).
- 🟡 **Validação antes de ligar em prod:** CI executa `test_catalog_loads.py`, `test_prd_values.py` (RF-05), `test_no_trademarks.py` (RF-07) e `test_validated_vehicles_pass_reference` (desvio < 5 %).
- 🟡 **Como reverter (rollback):** os dados são arquivos versionados; `git revert` do commit de dados e nova imagem Docker revertem o catálogo; a imagem anterior continua válida porque o catálogo não tem migração de banco. Um veículo com regressão volta a `draft` no arquivo de dados.
- 🟡 **Monitoramento pós-deploy:** evento `startup.catalog` (duração, contagem, `catalog_sha256`), contagem de `catalog.draft_used` e de 404 `VEHICLE_NOT_FOUND`.

---

## 14. Open Questions

| # | Pergunta | Impacto | Dono | Prazo |
|---|---------|---------|------|-------|
| OQ-01 | 🟡 ⚠️ ABERTO: o `coupe-30t-i6` fica com uma só variante (10,2:1, injeção direta) ou ganha uma segunda variante 8,5:1 com injeção no coletor (ex.: `coupe-30t-i6-lc`)? Esta spec modela só a variante 10,2:1. | Médio | George | 2026-10-31 |
| OQ-02 | 🟡 Resolvida na revisão R1 (2026-10-18): os datasets de série dos 4 veículos formam o benchmark canônico oficial `Reference Benchmark Baseline v1`; o desvio < 5 % mede-se contra ele. O campo `confidence` continua a registar a proveniência de cada grandeza; uma futura troca por folhas medidas gera a versão v2 do benchmark. | Alto | George | 2026-10-24 |
| OQ-03 | 🟡 ⚠️ ABERTO: o `classic-20t-swap` começa com perfil de série `oem-stage` (ECU original conservadora) ou já com `ft-pro` em mapa base? Esta spec usa `oem-stage` com calibração conservadora para a jornada do Rodrigo (troca OEM → standalone). | Médio | George | 2026-10-31 |
| OQ-04 | 🟡 ⚠️ ABERTO: o `classic-20t-swap` é 8v (2 válvulas, SOHC) ou 16v? Esta spec usa 8v sem VVT. | Baixo | George | 2026-11-07 |
| OQ-05 | 🟡 ⚠️ ABERTO: os limites mecânicos do `muscle-v8-sc` (biela 1000 N·m) refletem internos de série capazes de 800 whp ou uma preparação? O PRD diz "460 whp de série, até 800 whp". | Médio | George | 2026-11-07 |
| OQ-06 | 🟡 ⚠️ ABERTO: o `coupe-30t-i6` com internos forjados até 750 whp precisa de um turbo maior para atingir esse teto; kits de turbo ficam fora do MVP (NG-02)? | Médio | George | 2026-11-07 |
| OQ-07 | 🟡 ⚠️ ABERTO: os limites de EGT do `classic-20t-swap` e do `muscle-v8-sc` (950 °C) não constam do PRD; confirmar os valores. | Médio | George | 2026-10-31 |

---

## 15. Decisões Tomadas (Decision Log)

| Decisão | Alternativas consideradas | Racional |
|---------|--------------------------|---------|
| 🟡 Dados em JSON com manifesto SHA-256 | YAML; tabelas no banco SQLite | JSON é da biblioteca padrão, determinístico para hash e já é o formato de troca do PRD; dados de referência não pertencem ao banco do usuário. |
| 🟡 Validação completa no arranque, sem fallback | Validação preguiçosa por veículo | Um erro de dados descoberto durante uma puxada quebraria o determinismo e a meta de 5 %; falhar cedo é verificável no CI. |
| 🟡 `egt_max_c` é o nome canónico e `egt_limit_c` é sinónimo calculado | Renomear num dos consumidores | `ecu-core` usa `egt_max_c` e `dyno-bench` usa `egt_limit_c`; o sinónimo evita quebrar as duas specs. |
| 🟡 `density_kg_m3` canónico com `density_g_cc` calculado | Só g/cm³ | SI interno (convenções) e compatibilidade com o `ecu-core`. |
| 🟡 `rev_limit_rpm`, `max_rpm` e `valve_float_rpm` separados | Um único limite de rotação | O corte de fábrica, a rotação máxima segura e a flutuação de válvulas são grandezas físicas diferentes usadas por `dyno-bench`, `engine-physics-core` e modelo de dano. |
| 🟡 O catálogo é dono dos arquivos de calibração de fábrica; o `ecu-core` é dono do schema `Calibration` | `ecu-profiles` dono dos arquivos | Responde a ecu-core OQ-02: a calibração de fábrica é um dado do veículo (versionado com ele); o schema e a materialização pertencem ao `ecu-core`, com `source = "oem_stock"`. |
| 🟡 `mbt_reference` opcional só para a UI | Canal calculado pela física | Responde a ecu-tuning-ui OQ-02: a física não usa tabela de MBT (MBT emerge do modelo); a UI precisa de um valor estimado barato para o aviso W-01. |
| 🟡 Curvas de série dos 4 veículos como benchmark canônico `Reference Benchmark Baseline v1` (revisão R1) | Esperar folhas públicas medidas | 🟡 Torna o desvio < 5 % verificável de forma determinística desde o Sprint 1; a proveniência fica registada em `confidence` e uma troca de dados exige nova versão do benchmark. |
| 🟡 Limites estruturais `max_rod_load_kn`, `max_cylinder_pressure_bar`, `max_piston_temp_c`, `valve_float_rpm` obrigatórios (revisão R1) | Campos opcionais em kPa e N | 🟡 Decisão do usuário; nomes únicos para o catálogo e para o modelo de dano. |
| 🟡 Coupé modelado como uma variante 10,2:1 | Duas variantes no mesmo `vehicle_id` | O ID canónico é único e a variante 10,2:1 com injeção direta corresponde aos 340 whp de série; a variante 8,5:1 fica em OQ-01. |
| 🟡 Torque de referência no virabrequim e potência na roda | Ambos na roda | Corresponde ao PRD (220 whp / 350 N·m) e ao `dyno-bench` (`T_eng` estimado e `P_wheel` medido). |
| 🟡 Perda fixa de transmissão padrão 0 kW | Perda fixa por veículo | Mantém a relação `P_crank = P_wheel / η_drv` do `dyno-bench` exata; o campo existe para afinação futura. |

---

## Apêndice

### A.1 Valores do PRD (proveniência `prd`, igualdade exata no teste RF-05)

| Veículo | Campo | Valor |
|---|---|---|
| 🟡 `hatch-20t-gdi` | `engine.displacement_cc`, `engine.n_cyl`, `engine.compression_ratio` | 1984; 4; 9,6 |
| 🟡 `hatch-20t-gdi` | `rated.peak_power_whp`, `rated.peak_torque_nm` | 220; 350 |
| 🟡 `hatch-20t-gdi` | `mechanical_limits.rod_torque_limit_nm`, `mechanical_limits.egt_max_c` | 420; 950 |
| 🟡 `hatch-20t-gdi` | `induction`, `stock_profile_id` | turbo; `oem-stage` |
| 🟡 `coupe-30t-i6` | `engine.displacement_cc`, `engine.n_cyl`, `engine.architecture`, `engine.compression_ratio` | 2998; 6; inline; 10,2 |
| 🟡 `coupe-30t-i6` | `rated.peak_power_whp`, `rated.power_ceiling_whp`, `mechanical_limits.egt_max_c` | 340; 750; 980 |
| 🟡 `coupe-30t-i6` | `induction`, `turbo.housing` | turbo; um único turbo |
| 🟡 `classic-20t-swap` | `engine.displacement_cc`, `engine.n_cyl`, `engine.compression_ratio` | 1984; 4; 8,5 |
| 🟡 `classic-20t-swap` | `turbo.compressor_ar`, `turbo.turbine_ar`, `stock_fuel_id`, `rated.power_range_whp` | 0,50; 0,63; `e100`; (300, 600) |
| 🟡 `muscle-v8-sc` | `engine.displacement_cc`, `engine.n_cyl`, `engine.architecture` | 4951; 8; v |
| 🟡 `muscle-v8-sc` | `induction`, `rated.peak_power_whp`, `rated.power_ceiling_whp` | supercharger; 460; 800 |

### A.2 Ficha por veículo (valores não listados em A.1 são `estimate`, salvo indicação `public_spec`)

| Campo | `hatch-20t-gdi` | `coupe-30t-i6` | `classic-20t-swap` | `muscle-v8-sc` |
|---|---|---|---|---|
| 🟡 `display_name` | Hatch 2.0 turbo GDI | Coupé 3.0 turbo 6 em linha | Clássico 2.0 turbo de swap | Muscle V8 5,0 sobrealimentado |
| 🟡 `architecture_note` | Inspirado em arquitetura 2.0 turbo GDI de 4 cilindros | Inspirado em arquitetura 3.0 turbo de 6 cilindros em linha | Inspirado em arquitetura 2.0 8v de 4 cilindros turbo forjado | Inspirado em arquitetura V8 5,0 DOHC com compressor volumétrico |
| 🟡 Diâmetro × curso (mm) | 82,5 × 92,8 (`public_spec`) | 82,0 × 94,6 (`public_spec`) | 82,5 × 92,8 (`public_spec`) | 92,2 × 92,7 (`public_spec`) |
| 🟡 Cilindrada calculada (cc) | 1984,3 | 2997,5 | 1984,3 | 4951,3 |
| 🟡 Biela (mm) | 144,0 | 144,4 | 144,0 | 150,7 |
| 🟡 Válvulas por cilindro, comando | 4, dohc | 4, dohc | 2, sohc | 4, dohc |
| 🟡 Ordem de ignição | 1-3-4-2 | 1-5-3-6-2-4 | 1-3-4-2 | 1-5-4-8-6-3-7-2 |
| 🟡 VVT admissão / escape (graus) | 0..50 / 0..30 | 0..70 / 0..55 | sem VVT | 0..50 / 0..50 |
| 🟡 IVC ABDC / EVO BBDC (graus) | 40 / 45 | 45 / 45 | 38 / 40 | 50 / 50 |
| 🟡 Injeção, roda fônica | gdi, 60-2 | gdi, 60-2 | pfi, 60-2 | pfi, 36-1 |
| 🟡 Borboleta (mm), posição | 56, post_compressor | 68, post_compressor | 60, post_compressor | 87, pre_compressor |
| 🟡 Volumes admissão / boost / escape (L) | 3,0 / 4,5 / 0,8 | 4,0 / 3,0 / 1,2 | 3,5 / 6,0 / 1,5 | 8,0 / nenhum / 2,0 |
| 🟡 Intercooler (tipo, ε) | air_to_air, 0,75 | air_to_water, 0,80 | air_to_air, 0,72 | air_to_water, 0,70 |
| 🟡 Massa alternada por cilindro (g) | 600 | 610 | 640 | 780 |
| 🟡 Combustível de série / permitidos | `e27` / `e27`, `podium`, `e0` | `e27` / `e27`, `podium`, `e0` | `e100` / `e100`, `e27`, `podium` | `e27` / `e27`, `podium`, `e0` |
| 🟡 Tração, marchas | fwd; 3,46 2,05 1,30 0,92 0,74 0,62 | rwd; 5,00 3,20 2,14 1,72 1,31 1,00 0,82 0,64 | fwd; 3,45 1,94 1,29 0,97 0,80 | rwd; 3,66 2,43 1,69 1,32 1,00 0,65 |
| 🟡 Diferencial, raio do pneu (m) | 4,12; 0,316 | 3,15; 0,333 | 3,89; 0,300 | 3,73; 0,352 |
| 🟡 `drivetrain_efficiency`, inércia na roda (kg·m²) | 0,85; 2,4 | 0,85; 3,2 | 0,88; 2,0 | 0,85; 3,6 |
| 🟡 Perfil de série, `stock_calibration_id` | `oem-stage`, `stock-hatch-20t-gdi-oem-stage` | `oem-stage`, `stock-coupe-30t-i6-oem-stage` | `oem-stage`, `stock-classic-20t-swap-oem-stage` (OQ-03) | `oem-stage`, `stock-muscle-v8-sc-oem-stage` |
| 🟡 Calibrações de fábrica adicionais | nenhuma | nenhuma | `ft-pro` mapa base (`stock-classic-20t-swap-ft-pro`) | nenhuma |
| 🟡 Estado no Sprint 1 | `validated` | `draft` | `draft` | `draft` |

### A.3 Sobrealimentação, bicos e limites (estimativas a validar)

| Campo | `hatch-20t-gdi` | `coupe-30t-i6` | `classic-20t-swap` | `muscle-v8-sc` |
|---|---|---|---|---|
| 🟡 Tipo | turbo compacto OEM, single_scroll, wastegate interna | turbo único twin_scroll, wastegate interna | turbo 0,50 / 0,63, wastegate externa | twin_screw 2,65 L/rev, polia 1,90 |
| 🟡 Inércia do rotor (kg·m²), área efetiva da turbina (cm²) | 2,0e-5; 7,0 | 3,5e-5; 11,0 | 4,5e-5; 13,0 | não se aplica |
| 🟡 Wastegate: área máxima (cm²), mola (kPa rel.) | 3,0; 50 | 4,5; 60 | 11,3; 90 | bypass ligado |
| 🟡 Compressor: PR_design, N_design, N_max (rpm) | 2,6; 200 000; 220 000 | 2,4; 170 000; 190 000 | 3,2; 140 000; 155 000 | η_ad 0,72 → 0,60 entre PR 1,0 e 2,0 |
| 🟡 Compressor: ṁ_choke,max, η_max, ṁ_pk, ṁ_range (kg/s) | 0,22; 0,74; 0,13; 0,10 | 0,38; 0,76; 0,24; 0,16 | 0,55; 0,75; 0,38; 0,22 | k_leak 0,08; N_ref 10 000 rpm |
| 🟡 MAP alvo de série (kPa abs.) | 230 | 215 | 230 | 165 |
| 🟡 Bicos: vazão (cm³/min) a Δp_ref (kPa) | 870 a 10 000 | 1100 a 10 000 | 2000 a 300 | 1000 a 400 |
| 🟡 Pressão de rail mín..máx (kPa), referência | 5000..20 000, cylinder | 5000..20 000, cylinder | 300..300, manifold | 400..400, manifold |
| 🟡 Tempo morto a 14 V (ms) | 0,35 | 0,35 | 1,00 | 0,80 |
| 🟡 `rod_torque_limit_nm` | 420 (`prd`) | 1000 (forjado) | 720 (forjado) | 1000 (OQ-05) |
| 🟡 `max_rod_load_kn` | 52 (estimativa) | 95 (forjado, estimativa) | 70 (forjado, estimativa) | 90 (estimativa) |
| 🟡 `max_cylinder_pressure_bar` | 120 | 160 | 140 | 145 |
| 🟡 `egt_max_c` | 950 (`prd`) | 980 (`prd`) | 950 (OQ-07) | 950 (OQ-07) |
| 🟡 `rev_limit_rpm` / `max_rpm` / `valve_float_rpm` | 6500 / 6800 / 7200 | 7000 / 7200 / 7600 | 7500 / 7800 / 8200 | 7500 / 7800 / 8000 |
| 🟡 `turbo_max_rpm` ou rotor máximo do compressor | 210 000 | 180 000 | 150 000 | 18 000 (rotor) |
| 🟡 `max_piston_temp_c` | 330 | 360 | 350 | 340 |
| 🟡 `power_ceiling_whp` | 300 (estimativa pelo limite da biela) | 750 (`prd`) | 600 (`prd`) | 800 (`prd`) |

### A.4 Curvas de referência de série — `Reference Benchmark Baseline v1` (âncoras a 500 rpm; o arquivo tem passo de 250 rpm com interpolação linear entre âncoras; proveniência `confidence = estimated`, `license = internal-estimate`; benchmark canônico oficial do simulador desde a revisão R1)

**`hatch-20t-gdi` (`stock-e27`, η 0,85, SAE J1349, 4ª marcha):**

| RPM | Torque virabrequim (N·m) | Potência virabrequim (kW) | Potência roda (kW) | whp | Lambda | EGT (°C) |
|---|---|---|---|---|---|---|
| 🟡 2000 | 350,0 | 73,3 | 62,3 | 83,6 | 0,95 | 720 |
| 🟡 2500 | 350,0 | 91,6 | 77,9 | 104,4 | 0,95 | 760 |
| 🟡 3000 | 350,0 | 110,0 | 93,5 | 125,3 | 0,95 | 800 |
| 🟡 3500 | 350,0 | 128,3 | 109,0 | 146,2 | 0,93 | 840 |
| 🟡 4000 | 350,0 | 146,6 | 124,6 | 167,1 | 0,90 | 870 |
| 🟡 4500 | 350,0 | 164,9 | 140,2 | 188,0 | 0,88 | 890 |
| 🟡 5000 | 345,0 | 180,6 | 153,5 | 205,9 | 0,85 | 905 |
| 🟡 5500 | 331,0 | 190,6 | 162,0 | 217,3 | 0,83 | 915 |
| 🟡 6000 | 307,3 | 193,1 | 164,1 | 220,1 | 0,82 | 920 |
| 🟡 6500 | 276,0 | 187,9 | 159,7 | 214,1 | 0,82 | 925 |

**`coupe-30t-i6` (`stock-e27`, η 0,85):**

| RPM | Torque virabrequim (N·m) | Potência virabrequim (kW) | Potência roda (kW) | whp | Lambda | EGT (°C) |
|---|---|---|---|---|---|---|
| 🟡 1500 | 430,0 | 67,5 | 57,4 | 77,0 | 0,98 | 700 |
| 🟡 2000 | 500,0 | 104,7 | 89,0 | 119,4 | 0,95 | 760 |
| 🟡 3000 | 500,0 | 157,1 | 133,5 | 179,1 | 0,90 | 820 |
| 🟡 4000 | 500,0 | 209,4 | 178,0 | 238,7 | 0,86 | 870 |
| 🟡 5000 | 500,0 | 261,8 | 222,5 | 298,4 | 0,82 | 910 |
| 🟡 5500 | 495,0 | 285,1 | 242,3 | 325,0 | 0,80 | 930 |
| 🟡 6000 | 474,5 | 298,1 | 253,4 | 339,8 | 0,80 | 940 |
| 🟡 6500 | 425,0 | 289,3 | 245,9 | 329,8 | 0,80 | 945 |
| 🟡 7000 | 380,0 | 278,6 | 236,8 | 317,5 | 0,80 | 950 |

**`classic-20t-swap` (`stock-e100`, η 0,88, calibração `oem-stage` conservadora):**

| RPM | Torque virabrequim (N·m) | Potência virabrequim (kW) | Potência roda (kW) | whp | Lambda | EGT (°C) |
|---|---|---|---|---|---|---|
| 🟡 3000 | 330,0 | 103,7 | 91,2 | 122,3 | 0,82 | 680 |
| 🟡 4000 | 430,0 | 180,1 | 158,5 | 212,6 | 0,80 | 740 |
| 🟡 5000 | 450,0 | 235,6 | 207,3 | 278,1 | 0,78 | 790 |
| 🟡 6000 | 420,0 | 263,9 | 232,2 | 311,4 | 0,78 | 820 |
| 🟡 6500 | 397,0 | 270,2 | 237,8 | 318,9 | 0,78 | 835 |
| 🟡 7000 | 355,0 | 260,2 | 229,0 | 307,1 | 0,78 | 845 |
| 🟡 7500 | 320,0 | 251,3 | 221,2 | 296,6 | 0,78 | 850 |

**`muscle-v8-sc` (`stock-e27`, η 0,85):**

| RPM | Torque virabrequim (N·m) | Potência virabrequim (kW) | Potência roda (kW) | whp | Lambda | EGT (°C) |
|---|---|---|---|---|---|---|
| 🟡 2000 | 470,0 | 98,4 | 83,7 | 112,2 | 0,90 | 650 |
| 🟡 3000 | 560,0 | 175,9 | 149,5 | 200,5 | 0,85 | 720 |
| 🟡 4000 | 630,0 | 263,9 | 224,3 | 300,8 | 0,82 | 780 |
| 🟡 4500 | 650,0 | 306,3 | 260,4 | 349,1 | 0,80 | 810 |
| 🟡 5000 | 645,0 | 337,7 | 287,1 | 385,0 | 0,80 | 830 |
| 🟡 6000 | 612,0 | 384,5 | 326,9 | 438,3 | 0,79 | 860 |
| 🟡 6500 | 593,6 | 404,1 | 343,4 | 460,6 | 0,79 | 870 |
| 🟡 7000 | 540,0 | 395,8 | 336,5 | 451,2 | 0,79 | 875 |
| 🟡 7500 | 490,0 | 384,8 | 327,1 | 438,7 | 0,79 | 880 |

- 🟡 Potência no virabrequim: `P = T · 2π · rpm / 60 / 1000` (kW); potência na roda `P · η_drv − P_fixa`; whp = kW / 0,7457.
- 🟡 Nos pontos intermediários de 250 rpm interpolam-se torque, lambda e EGT, e a potência recalcula-se pela fórmula acima (garante RF-13).

### A.5 Combustíveis (iguais ao Apêndice A.11 do `engine-physics-core`)

| `fuel_id` | AFR_st | PCI (MJ/kg) | RON / MON / `knock_on` | h_fg (kJ/kg) | ρ (kg/m³) | Fração mássica de etanol | Pré-ignição de superfície (°C) |
|---|---|---|---|---|---|---|---|
| 🟡 `e27` (gasolina comum BR) | 13,2 | 38,7 | 94 / 82 / 94 (estimativa) | 512 | 745 | 0,28 | 880 (estimativa) |
| 🟡 `e100` (etanol) | 9,0 | 26,8 | 109 / 90 / 106 (estimativa) | 920 | 789 | 1,00 | 830 (estimativa) |
| 🟡 `podium` (competição, E0) | 14,4 | 42,9 | 102 / 88 / 102 (estimativa) | 340 | 755 | 0,00 | 920 (estimativa) |
| 🟡 `e0` (gasolina pura) | 14,7 | 43,4 | 95 / 85 / 95 | 350 | 740 | 0,00 | 900 (estimativa) |

- 🟡 Velocidade laminar (Metghalchi-Keck) gasolina: `B_m = 0,305`, `B_φ = −0,549`, `φ_m = 1,21` (`literature`); etanol: `B_m = 0,465`, `B_φ = −1,0`, `φ_m = 1,10` (estimativa); misturas por interpolação linear da fração mássica de etanol, calculada pelo catálogo no arquivo de dados.

### A.6 Lista de termos proibidos em textos exibidos (`trademarks.py`)

- 🟡 Fabricantes e marcas: volkswagen, vw, audi, seat, skoda, bmw, toyota, lexus, ford, mustang, chevrolet, gm, corvette, camaro, dodge, mopar, bosch, continental, fueltech, motec, haltech, garrett, borgwarner, ihi, eaton, whipple, magnuson, roush, shelby.
- 🟡 Códigos de motor e de peça: ea888, tsi, tfsi, gti, b58, n55, 2jz, 2jz-gte, supra, coyote, ls, ls3, lsa, lt4, ap, is20, is38, ft600, ft550, m1, elite, nexus.
- 🟡 Os perfis canónicos (`FT-Pro`, `M1-Race`, `HT-Elite`, `OEM-Stage`) são nomes genéricos definidos pelo PRD e ficam fora do âmbito deste teste, que só cobre textos de veículos.

### A.7 Geração da VE física estimada (`tools/gen_ve.py`)

- 🟡 Fórmula de autoria (determinística, usada só para gerar o arquivo): `VE(rpm, map) = clip(VE_pk · (1 − k_r · ((rpm − rpm_pk)/rpm_span)²) · (1 − k_m · exp(−map/map_c)), 0,20, 1,35)`.
- 🟡 Parâmetros: hatch `VE_pk 0,98`, `rpm_pk 4200`, `rpm_span 4000`, `k_r 0,35`, `k_m 0,30`, `map_c 60 kPa`; coupé `1,00`, `4500`, `4500`, `0,30`, `0,30`, `60`; clássico 8v `0,90`, `5000`, `4500`, `0,40`, `0,25`, `70`; muscle `0,96`, `4500`, `4500`, `0,30`, `0,30`, `60`.
- 🟡 Eixos 16 × 16: RPM 800, 1000, 1250, 1500, 1750, 2000, 2500, 3000, 3500, 4000, 4500, 5000, 5500, 6000, 6500, 7000 (estendido até `max_rpm` quando maior); MAP 20, 30, 40, 50, 60, 70, 80, 90, 100, 120, 140, 160, 180, 200, 230, 260 kPa (estendido até 300 kPa no clássico).
- 🟡 A afinação para cumprir o desvio < 5 % altera os valores do arquivo; a fórmula serve de ponto de partida e o arquivo final é a fonte de verdade.

### A.8 Exemplo resumido de `vehicles/hatch-20t-gdi/vehicle.json`

```json
{
  "vehicle_id": "hatch-20t-gdi",
  "display_name": "Hatch 2.0 turbo GDI",
  "architecture_note": "Inspirado em arquitetura 2.0 turbo GDI de 4 cilindros",
  "body": "hatch",
  "data_version": 1,
  "validation_status": "validated",
  "validated_on": "2026-10-25",
  "induction": "turbo",
  "engine": {"architecture": "inline", "n_cyl": 4, "bore_mm": 82.5, "stroke_mm": 92.8,
             "rod_length_mm": 144.0, "compression_ratio": 9.6, "displacement_cc": 1984,
             "firing_order": [1, 3, 4, 2], "injection_type": "gdi", "valvetrain": "dohc",
             "valves_per_cyl": 4, "ivc_deg_abdc": 40, "evo_deg_bbdc": 45},
  "stock_fuel_id": "e27",
  "allowed_fuel_ids": ["e27", "podium", "e0"],
  "drive_layout": "fwd",
  "drivetrain_efficiency": 0.85,
  "drivetrain_fixed_loss_kw": 0.0,
  "driveline_inertia_kg_m2": 2.4,
  "mechanical_limits": {"rod_torque_limit_nm": 420, "egt_max_c": 950, "max_rpm": 6800,
                        "rev_limit_rpm": 6500, "valve_float_rpm": 7200,
                        "turbo_max_rpm": 210000, "max_rod_load_kn": 52,
                        "max_cylinder_pressure_bar": 120, "max_piston_temp_c": 330},
  "stock_profile_id": "oem-stage",
  "stock_calibration_id": "stock-hatch-20t-gdi-oem-stage",
  "provenance": {
    "/engine/compression_ratio": {"kind": "prd", "note": "PRD seção 7, item 1"},
    "/engine/bore_mm": {"kind": "public_spec", "source": "ficha técnica pública da arquitetura de inspiração"},
    "/mechanical_limits/rod_torque_limit_nm": {"kind": "prd", "note": "limite da biela de série ~420 N·m"}
  }
}
```

### Referências
- 🟡 `_reversa_sdd/prd.md` (seções 4, 6, 7, 8 e 9) e `_reversa_sdd/personas.md`.
- 🟡 Heywood, J. B. Internal Combustion Engine Fundamentals (geometria, VE, combustíveis, atrito).
- 🟡 Specs relacionadas: `engine-physics-core.md`, `dyno-bench.md`, `ecu-core.md`, `platform-foundation.md`, `ecu-profiles.md`, `knock-and-failure-model.md`, `dyno-cockpit-ui.md`, `ecu-tuning-ui.md`.

### Histórico de Revisões
| Versão | Data | Autor | Mudanças |
|--------|------|-------|---------|
| 🟡 1.0 | 2026-10-18 | reversa-spec-sdd | Criação inicial |
| 🟡 1.1 | 2026-10-18 | reversa-spec-sdd | Revisão R1 de consistência entre specs (decisões do usuário: knock, nomes de campo, códigos de erro, seq, campos de integração, prefixo /api/v1/, OEM-Stage, benchmark v1) |

## Relatório de avaliação (reversa-spec-sdd)

- 🟡 Score final: 100,0/100 (⭐ Excelente — Pronta para implementação)
- 🟡 Iterações: 2 (scores: 85 → 100)
- 🟡 Breakdown: Completude 100 %, Testabilidade 100 %, Clareza 100 %, Escopo 100 %, Edge Cases 100 %
- 🟡 Gaps críticos remanescentes: nenhum
- 🟡 Sugestões remanescentes: nenhuma
- 🟡 Revisão R1 (2026-10-18): reavaliado após a revisão de consistência entre specs, score 100,0/100.
