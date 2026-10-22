# Onboarding: Simulador Completo de Remap Automotivo em Dinamômetro

> Identificador: `001-simulador-remap`
> Data: `2026-10-18`
> Roadmap: `_reversa_forward/001-simulador-remap/roadmap.md`
> Confidência: 🟢 CONFIRMADO, 🟡 INFERIDO, 🔴 LACUNA

🟡 Este guia ensina um humano a testar a feature pela primeira vez. Ele descreve o comportamento planejado: siga-o depois do Sprint 4 (2026-11-15), ou até ao sprint que você quer validar (veja a seção 10).
🟡 Os comandos vêm das specs `platform-foundation`, `dyno-bench`, `ecu-profiles`, `telemetry-datalogger` e `training-scenarios`. Os alvos `make bench`, `make accuracy` e `make e2e` são novos e vêm da decisão D-26 do roadmap.
🟡 Os exemplos usam `curl` e `jq`. Troque `<session_id>`, `<run_id>` e os outros identificadores pelos valores devolvidos nas respostas.

## 1. Pré-requisitos

1. Use uma máquina com CPU de 4 núcleos, 8 GB de RAM e sem GPU dedicada (hardware de referência). Mais recursos também servem.
2. Instale o Docker Engine ≥ 24 com Compose v2. Confirme com `docker --version` e `docker compose version`.
3. Reserve 2 GB livres em disco para a imagem (≤ 450 MB) e para o volume `simremap-data`.
4. Instale um navegador desktop Chromium ≥ 120 ou Firefox ≥ 120. Use uma resolução ≥ 1366×768.
5. Para os passos via terminal, instale `curl` e `jq`.
6. Para rodar `make check`, `make bench`, `make accuracy` e `make e2e` fora do Docker, instale `make`, Python 3.12 com `uv` e Node 20 com `npm`.
7. Libere a porta 8000 em `127.0.0.1`.

## 2. Subir o simulador

1. Abra um terminal na raiz do repositório `SimuladorRemap/`.
2. Construa a imagem:
   ```bash
   docker compose -f compose.yaml -f compose.prod.yaml build
   ```
3. Suba o container em segundo plano:
   ```bash
   docker compose -f compose.yaml -f compose.prod.yaml up -d
   ```
4. Aguarde até 60 s com volume vazio (até 15 s com volume já migrado).
5. Verifique a saúde:
   ```bash
   curl -s http://127.0.0.1:8000/api/v1/health | jq
   ```
   - Valor esperado: `"status": "ok"`, `checks.database.status = "ok"`, `checks.redis.status = "disabled"`, `checks.sim_worker.status = "ok"`.
6. Verifique as versões:
   ```bash
   curl -s http://127.0.0.1:8000/api/v1/version | jq
   ```
   - Valor esperado: `api_version = "v1"`, `package_format_version = 1`, `datalog_format_version = 1`, `alembic_head = "0007_scenarios_base"`.
7. (Opcional) Teste o arranque sem rede: o teste de fumo usa `--network none` e deve passar igual.
8. Para desenvolvimento com hot reload, use `docker compose -f compose.yaml -f compose.dev.yaml up`. O Vite abre em `http://localhost:5173`.

## 3. Abrir o navegador

1. Abra `http://localhost:8000`.
2. Confirme que a tela inicial carrega em ≤ 2,5 s e não mostra "Servidor indisponível".
3. Abra a lista de veículos. Valor esperado: 4 veículos validados (`hatch-20t-gdi`, `coupe-30t-i6`, `classic-20t-swap`, `muscle-v8-sc`).
4. Clique em "Ativar som" se quiser o áudio do motor. O áudio fica desligado até esse clique. A tecla `M` silencia.

## 4. Jornada do Lucas (Stage 1/Stage 2 no OEM-Stage)

🟡 Objetivo: quebrar o motor por knock, ler o laudo, corrigir e validar o ganho. Fonte: `requirements.md` RF-40 e `knock-and-failure-model` G-01, G-02.

1. Crie o perfil local `lucas` com papel `student`.
   ```bash
   curl -s -X POST http://127.0.0.1:8000/api/v1/profiles \
     -H 'Content-Type: application/json' -d '{"nickname":"lucas","role":"student"}' | jq
   ```
   - Valor esperado: 201 com `id` e `role = "student"`.
2. Abra o cenário `stage2-pops-bangs` na UI e inicie a tentativa. O sistema cria a sessão no `hatch-20t-gdi` com `oem-stage`, gasolina E27 e executa a baseline automática.
   - Valor esperado: tentativa em `in_progress` com `baseline_run_id` preenchido.
3. Para reproduzir com determinismo pelo terminal, crie a sessão com `seed` 42:
   ```bash
   curl -s -X POST http://127.0.0.1:8000/api/v1/sessions -H 'Content-Type: application/json' \
     -d '{"vehicle_id":"hatch-20t-gdi","profile_id":"oem-stage","seed":42}' | jq
   ```
4. No editor de ECU, suba o boost alvo para 280 kPa abs e some +8° em toda a tabela de avanço base. Grave.
   - Valor esperado: o editor mostra o aviso W-01 (avanço acima do MBT estimado), mas não bloqueia a gravação.
5. Execute uma `sweep_pull` na cockpit (ou `POST /api/v1/sessions/<session_id>/runs` com `{"run_type":"sweep_pull"}`).
   - Valor esperado: knock da classe `severe`, 1 falha catastrófica e puxada em `engine_failed`.
   - Valor esperado: a cockpit abre a autópsia com a cadeia causal (3 a 12 elos) e as recomendações `R-KNOCK-01` e `R-LAMBDA-01`, em ≤ 500 ms.
6. Tente outra puxada sem restaurar.
   - Valor esperado: 409 `ENGINE_DESTROYED`.
7. Restaure o motor pelo botão da autópsia (ou `POST /api/v1/sessions/<session_id>/engine/restore`).
8. Corrija o acerto: λ 0,80 em alta carga, −3° nos cilindros com knock, boost 230 kPa abs e overrun (pops & bangs) com proteção de EGT.
9. Execute a puxada final e a 2.ª puxada de evidência.
   - Valor esperado: `completed`, sem knock acima de `light`, integridade 100 % (saúde mínima ≥ 0,999), EGT ≤ 950 °C, ≥ 5 `pop_events` no coastdown.
   - Valor esperado: Δwhp ≥ +65 sobre a baseline.
10. Submeta a tentativa.
    - Valor esperado: `passed = true` com todos os critérios obrigatórios aprovados.

## 5. Jornada do Rodrigo (swap para standalone)

🟡 Objetivo: trocar a ECU OEM por `FT-Pro`, configurar a base e validar 3 puxadas seguidas. Fonte: `ecu-profiles` Apêndice F e `requirements.md` RF-41.

1. Crie o perfil `rodrigo` (`student`) e abra o cenário `standalone-swap`. O sistema cria a sessão no `classic-20t-swap` com `oem-stage` e etanol E100.
   - Valor esperado: `ecu_state = oem`.
2. Abra o assistente de swap e escolha `FT-Pro` com cópia de segurança da calibração OEM.
   - Valor esperado: `awaiting_base_setup` com 6 itens obrigatórios pendentes.
   - Valor esperado: uma puxada neste estado devolve 409 `ECU_SETUP_INCOMPLETE`.
3. Complete os 6 passos: roda fônica 60-2, ordem 1-3-4-2, bicos 1000 cc/min, combustível E100, MAP 20–400 kPa, wideband padrão e failsafe. Gere o mapa base.
   - Valor esperado: `standalone_ready` e calibração com `metadata.source = wizard`; o motor fica em marcha lenta na cockpit.
4. Trave o ponto a 10° em marcha lenta.
   - Valor esperado: `timing_light_deg` = 10,0 ± 0,1.
5. Execute `steady_state_hold` de 16 células e corrija a VE até o erro de lambda ≤ 3 %.
6. Ajuste a ignição célula a célula até o MBT sem knock severo.
   - Valor esperado: pico de pressão entre 12° e 18° ATDC nas células WOT.
7. Ative o two-step a 4000 rpm e o boost por marcha.
   - Valor esperado: o two-step segura 4000 ± 100 rpm.
8. Execute `multi_pull` com 3 puxadas.
   - Valor esperado: `peak_whp_spread_pct` ≤ 2 %, 0 eventos de falha.
9. Submeta a tentativa.
   - Valor esperado: potência de pico ≥ 300 whp (premissa da seção 4 do roadmap) e margem de knock ≥ 2° pela sonda.

## 6. Jornada do Prof. Marcos (desafio e avaliação objetiva)

🟡 Objetivo: criar um desafio, distribuir o pacote, avaliar a tentativa importada e comparar logs. Fonte: `training-scenarios` RF-05, RF-18 a RF-20, RF-25 e `requirements.md` RF-42.

1. Crie o perfil `marcos` com papel `instructor`.
2. Crie o desafio `challenge-400whp-e27` no `coupe-30t-i6`: gasolina E27, `min_whp = 400`, `max_egt_c = 900`, knock retard ≤ 3°, integridade 100 %, 3 puxadas válidas com dispersão ≤ 3 %.
   - Valor esperado: 201; um perfil `student` que tente criar recebe 403.
3. (Opcional) Adicione um defeito oculto de bomba de combustível fraca de 90 L/h.
   - Valor esperado: o aluno vê `hidden_defect = null` e `has_hidden_defect = true`.
4. Exporte o pacote do desafio (seção 7). Copie o arquivo para a estação do aluno.
5. Na estação do aluno, importe o pacote, execute a tentativa e exporte o pacote da tentativa.
6. Na estação do instrutor, importe o pacote da tentativa.
   - Valor esperado: o sistema recalcula a avaliação e aprova só se todos os critérios obrigatórios passarem; o `evaluation_sha256` é igual ao do aluno.
7. Exporte e compare os logs antes e depois:
   ```bash
   curl -s "http://127.0.0.1:8000/api/v1/runs/<run_id_antes>/log?format=json" -o antes.json
   curl -s "http://127.0.0.1:8000/api/v1/runs/<run_id_depois>/log?format=json" -o depois.json
   ```
   Use `POST /api/v1/logs/compare` (ou o painel do datalogger) para ver a diferença por bins de RPM.
8. No painel do instrutor, exporte as notas em CSV.
   - Valor esperado: 1 cabeçalho + 1 linha por tentativa importada; um nickname iniciado por `=` sai prefixado por `'`.

## 7. Exportar e importar pacotes

1. Exporte um desafio ou uma tentativa:
   ```bash
   curl -s -X POST http://127.0.0.1:8000/api/v1/packages/export -H 'Content-Type: application/json' \
     -d '{"kind":"challenge","scenario_id":"challenge-400whp-e27"}' -o desafio.simremap.json
   ```
   - Valor esperado: arquivo `simremap-<kind>-<id>-<8 hex>.simremap.json` com campo `sha256`.
2. Importe na outra estação:
   ```bash
   curl -s -X POST http://127.0.0.1:8000/api/v1/packages/import -H 'Content-Type: application/json' \
     --data-binary @desafio.simremap.json | jq
   ```
   - Valor esperado: 201 na 1.ª importação; 200 com `already_imported = true` na 2.ª.
3. Teste a adulteração: altere 1 dígito de um limiar no arquivo e importe de novo.
   - Valor esperado: 422 `PACKAGE_HASH_MISMATCH` com `expected_sha256` e `actual_sha256`; nada é gravado.
4. Teste um pacote de tentativa importado por um perfil `student`.
   - Valor esperado: 403 `INSTRUCTOR_ROLE_REQUIRED`.

## 8. Verificar o desvio contra o benchmark

🟡 A meta é desvio máximo < 5 % por ponto de RPM em torque, potência, lambda e EGT (°C), contra `Reference Benchmark Baseline v1`.

1. Rode a verificação automática (fora do Docker, na raiz):
   ```bash
   make accuracy
   ```
   - Valor esperado: 1 linha por veículo validado com `max_deviation_pct` por grandeza, todos < 5,0, e `benchmark_id = reference-benchmark-baseline-v1`. No fim do Sprint 1 só aparece o `hatch-20t-gdi`.
2. Para verificar à mão, execute a varredura com a calibração de referência:
   ```bash
   curl -s -X POST http://127.0.0.1:8000/api/v1/sessions/<session_id>/runs -H 'Content-Type: application/json' \
     -d '{"run_type":"sweep_pull","start_rpm":2000}' | jq
   curl -s http://127.0.0.1:8000/api/v1/runs/<run_id> | jq '.curve'
   curl -s http://127.0.0.1:8000/api/v1/vehicles/hatch-20t-gdi/reference-curves | jq '{benchmark_id, benchmark_sha256}'
   ```
3. Na cockpit, ative a sobreposição com a referência e confira as 4 curvas.
4. Repita a comparação. Valor esperado: `max_deviation_pct` idêntico bit a bit.
5. Rode o benchmark de desempenho:
   ```bash
   make bench
   ```
   - Valor esperado: física média ≤ 0,5 ms e p99 ≤ 2,0 ms por tick no `muscle-v8-sc` a 7500 rpm; laço ≥ 100 Hz em tempo real (alvo 1000 Hz); `GET /api/v1/health` P95 < 50 ms com o worker a 1000 Hz.

## 9. Rodar `make check` e os testes ponta a ponta

1. Na raiz, instale as dependências: `cd backend && uv sync --frozen`, depois `npm --prefix frontend ci`.
2. Rode o portão de qualidade:
   ```bash
   make check
   ```
   - Ordem: `ruff check`, `ruff format --check`, `mypy --strict`, `bandit`, `pytest` com cobertura, cobertura por pacote (≥ 85 %), `eslint`, `tsc --noEmit`, `vitest run`.
   - Valor esperado: código de saída 0 em ≤ 5 min. A 1.ª etapa que falhar interrompe o pipeline.
3. Rode as 3 jornadas automatizadas:
   ```bash
   make e2e
   ```
   - Valor esperado: Lucas, Rodrigo e Prof. Marcos aprovados com `seed` 42; 20 execuções repetidas com o mesmo digest.

## 10. O que testar em cada sprint

| Sprint | Data de fim | O que já funciona |
|---|---|---|
| 1 | 2026-10-25 | Seções 2 e 8 (só o hatch, sem UI de cockpit), `make check`, `make bench`. |
| 2 | 2026-11-01 | Passos 3 a 9 da jornada do Lucas por REST (sem editor nem cockpit). |
| 3 | 2026-11-08 | Cockpit no navegador, datalog, export/import de log, jornada do Rodrigo por REST. |
| 4 | 2026-11-15 | Todo o guia, incluindo editor de ECU, cenários, pacotes e painel do instrutor. |

## 11. Troubleshooting

| Sintoma | Causa provável | Ação |
|---|---|---|
| `docker compose up` falha com porta em uso | Outro serviço usa 8000 | Pare o serviço ou mude a porta publicada no `compose.yaml` (mantenha `127.0.0.1`). |
| `/api/v1/health` devolve 503 `SERVICE_UNAVAILABLE` | Banco indisponível ou volume sem permissão | Veja `docker compose logs app` e procure `startup.failed` com `DATABASE_UNAVAILABLE`; confirme o volume `simremap-data` montado em `/data`. |
| Container reinicia em ciclo (código 3) | 5 tentativas de ligação ao banco falharam | Corrija `DATABASE_URL` ou a permissão de `/data`; o Docker reinicia sozinho. |
| `GET /` devolve 404 `STATIC_NOT_BUILT` | Build do frontend ausente | Reconstrua a imagem com `docker compose ... build`. |
| Criar sessão devolve 409 `SIM_CAPACITY_EXCEEDED` | Já existe 1 sessão ativa | Encerre a sessão com `DELETE /api/v1/sessions/<session_id>`. |
| Criar sessão devolve 409 `VEHICLE_NOT_VALIDATED` | Veículo ainda em `draft` | Use um veículo validado ou, só em dev, `SIMREMAP_CATALOG_ALLOW_DRAFTS=true` e reinicie. |
| Puxada devolve 409 `ENGINE_DESTROYED` | Motor bloqueado após falha | Restaure com `POST /api/v1/sessions/<session_id>/engine/restore`. |
| Puxada devolve 409 `ECU_SETUP_INCOMPLETE` | `BaseSetup` standalone incompleta | Complete os itens listados em `missing` no assistente. |
| Puxada devolve 409 `RUN_IN_PROGRESS` | Outra puxada em curso | Aguarde o fim ou aborte com `POST .../runs/<run_id>/abort`. |
| Gravar calibração devolve 409 `CALIBRATION_VERSION_CONFLICT` | `base_version` desatualizada | Recarregue a calibração e repita a alteração. |
| Aplicar calibração devolve 409 `TABLE_NOT_LIVE_TUNABLE` | Alteração em tabela bloqueada durante a puxada | Aguarde o fim da puxada ou altere só tabelas live-tunable. |
| Cockpit mostra "telemetria indisponível" | 10 falhas de reconexão do WS | Verifique `sim_worker` no health e clique em "Tentar de novo". |
| Respostas 503 `SIM_WORKER_UNAVAILABLE` | Processo do worker morreu | Encerre a sessão e crie outra; veja `worker.crashed` nos logs. |
| Cockpit abaixo de 30 FPS | Navegador sem aceleração ou muitos painéis | Feche painéis não usados; confirme a aceleração por hardware no navegador; o espectrograma cai para Canvas 2D sozinho. |
| `make accuracy` reprova um veículo | Desvio ≥ 5 % numa grandeza | Veja a grandeza e o RPM no relatório; não altere a curva do benchmark sem nova versão. |
| `make check` falha em `coverage-per-package` | Pacote abaixo de 85 % | Acrescente testes no pacote listado. |
| Hash diferente entre execuções | Máquina de arquitetura diferente ou imagem diferente | Compare só na mesma imagem e na mesma arquitetura (`amd64` é a referência). |
| Logs com `worker.overrun` frequentes | CPU insuficiente para 1000 Hz | Rode com `sim_hz` menor (mínimo 100) na criação da sessão e registre o resultado do `make bench`. |
