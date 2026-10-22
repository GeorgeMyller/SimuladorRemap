# Spec: platform-foundation

**Versão:** 1.1
**Status:** Rascunho
**Autor:** reversa-spec-sdd
**Data:** 2026-10-18
**Reviewers:** N/A
**Sprint:** 1 (componente 9, primeiro a implementar)

---

## 1. Resumo

🟡 O componente platform-foundation entrega o esqueleto executável do SimuladorRemap: monorepo `backend/` + `frontend/`, aplicação FastAPI com factory e lifespan, configuração tipada via variáveis `SIMREMAP_`, formato de erro RFC 7807, persistência async com Alembic, worker dedicado ao laço físico, logging JSON, imagem Docker única e portões de qualidade locais. Todos os outros 10 componentes montam os seus routers, modelos e testes sobre esta base, sem redefinir infraestrutura.

---

## 2. Contexto e Motivação

**Problema:**
🟡 O MVP tem 4 semanas e 11 componentes desenvolvidos em sequência. Sem uma base comum, cada componente inventaria o seu formato de erro, a sua sessão de banco, o seu logging e a sua forma de correr o laço físico, gerando incoerência entre specs e retrabalho no Sprint 4.

**Evidências:**
- 🟡 O PRD (seção 8, risco 1) aponta como risco alto o laço físico em Python não atingir 100–1000 Hz com a telemetria simultânea; a mitigação aprovada é separar o laço físico do event loop asyncio.
- 🟡 O PRD (seção 6) exige paridade total dev/staging/prod em Docker, `uv` + `pyproject.toml`, `ruff`, `mypy --strict`, `pytest` + `pytest-cov` e `bandit`.
- 🟡 O PRD (seção 8, último risco) exige um container local-first por estação/aluno para turmas de 20 a 50 alunos sem infraestrutura de rede.

**Por que agora:**
🟡 A ordem aprovada de implementação (9 → 1 → 3 → 4 → 2 → 5 → 6 → 7 → 11 → 10 → 8) coloca este componente em primeiro lugar. Os componentes engine-physics-core e vehicle-catalog, também do Sprint 1, dependem do worker, da configuração e do catálogo de erros definidos aqui.

---

## 3. Goals (Objetivos)

- [ ] 🟡 G-01: Subir a aplicação completa com `docker compose up` em < 60 s (imagem já construída) no hardware de referência (4 núcleos, 8 GB, sem GPU).
- [ ] 🟡 G-02: Garantir que 100 % das respostas de erro HTTP da API usam `application/problem+json` com `code` estável do catálogo.
- [ ] 🟡 G-03: Isolar o laço físico do event loop: com o worker a 1000 Hz, a latência P95 de `GET /api/v1/health` fica < 50 ms.
- [ ] 🟡 G-04: Fazer `make check` passar com cobertura ≥ 85 % por pacote de domínio, zero erros de `mypy --strict`, zero achados `bandit` de severidade média ou alta.
- [ ] 🟡 G-05: Manter a imagem Docker final ≤ 450 MB e a memória residente ociosa do container ≤ 300 MB.

**Métricas de sucesso:**
| Métrica | Baseline atual | Target | Prazo |
|---------|---------------|--------|-------|
| 🟡 Tempo de arranque até `/api/v1/health` = `ok` | inexistente | < 60 s | fim do Sprint 1 (2026-10-25) |
| 🟡 Latência P95 de `/api/v1/health` com worker a 1000 Hz | inexistente | < 50 ms | 2026-10-25 |
| 🟡 Cobertura de testes por pacote de domínio | 0 % | ≥ 85 % | cada sprint |
| 🟡 Erros HTTP fora do formato RFC 7807 | não medido | 0 % | 2026-10-25 |
| 🟡 Tamanho da imagem Docker final | inexistente | ≤ 450 MB | 2026-10-25 |
| 🟡 Tempo de `make check` completo numa máquina de referência | inexistente | ≤ 5 min | 2026-10-25 |

---

## 4. Non-Goals (Fora do Escopo)

- 🟡 NG-01: Não haverá autenticação, contas de usuário nem tokens: o produto é local-first, um container por estação, sem PII (os perfis com nickname pertencem a training-scenarios).
- 🟡 NG-02: Não haverá deploy em nuvem, Kubernetes, orquestração multi-nó nem balanceador de carga; o alvo é `docker compose` numa máquina local ou servidor local.
- 🟡 NG-03: Não haverá CI remoto obrigatório (GitHub Actions ou similar) no MVP; o portão de qualidade é o pipeline local `make check`, reutilizável por um CI futuro sem alteração.
- 🟡 NG-04: Não haverá telemetria de uso, analytics, crash reporting externo nem qualquer chamada de rede para fora do host.
- 🟡 NG-05: Não haverá Server-Side Rendering nem Next.js; o frontend é uma SPA Vite servida como estático pelo FastAPI.
- 🟡 NG-06: Não haverá réplicas, alta disponibilidade nem migração de dados entre estações; a troca de dados entre alunos e instrutor é feita por pacotes exportados (training-scenarios).
- 🟡 NG-07: Este componente não implementa física, ECU, dinamômetro nem telemetria; define só os contratos de hospedagem (worker, routers, erros, sessão de banco).

---

## 5. Usuários e Personas

**Usuário primário:** 🟡 Desenvolvedor do SimuladorRemap (implementador de cada componente) que precisa de uma base pronta: router montado, sessão de banco injetável, erro padronizado, worker do laço físico e portões de qualidade.

**Usuário secundário:** 🟡 Prof. Marcos (instrutor), que instala um container por estação para turmas de 20 a 50 alunos sem rede; Lucas e Rodrigo, que correm o simulador em casa ou na oficina com um único comando Docker.

**Jornada atual (sem a feature):**
1. 🟡 Não existe aplicação; cada componente teria de escolher sozinho o servidor, a configuração e o formato de erro.
2. 🟡 O instrutor não tem como distribuir o simulador de forma idêntica em 20 a 50 estações.
3. 🟡 Não existe verificação automática de qualidade antes de integrar um componente.

**Jornada futura (com a feature):**
1. 🟡 O Prof. Marcos copia a imagem para cada estação e executa `docker compose -f compose.yaml -f compose.prod.yaml up -d`; o navegador abre `http://localhost:8000`.
2. 🟡 Lucas abre o simulador offline em casa com o mesmo comando, com o banco SQLite persistido em volume Docker.
3. 🟡 O desenvolvedor cria `backend/src/simremap/<pacote>/router.py`, regista o router num único ponto e corre `make check` antes de integrar.

---

## 6. Requisitos Funcionais

### 6.1 Requisitos Principais

| ID | Requisito | Prioridade | Critério de Aceite |
|----|-----------|-----------|-------------------|
| 🟡 RF-01 | 🟡 O sistema deve organizar o código num monorepo com `backend/` (projeto `uv` com `pyproject.toml` e `uv.lock`) e `frontend/` (projeto Vite + React 18 + TypeScript strict), com o layout de pacotes da seção 8. | Must | `uv sync --frozen` em `backend/` e `npm ci` em `frontend/` terminam com código 0 numa clonagem limpa; `python -c "import simremap.core, simremap.physics, simremap.api, simremap.db"` termina com código 0. |
| 🟡 RF-02 | 🟡 O sistema deve expor uma factory `create_app(settings: Settings | None = None) -> FastAPI` com lifespan que inicializa, por esta ordem, logging, engine de banco, migrações (se ativas), Redis (opcional), `SimWorkerHost` e routers; e finaliza na ordem inversa. | Must | Teste com `httpx.AsyncClient` + `LifespanManager` confirma a ordem por eventos de log `startup.<etapa>`; após o shutdown, 0 threads/processos de worker continuam vivos. |
| 🟡 RF-03 | 🟡 O sistema deve montar os routers de cada componente sob `/api/v1` (REST) e `/ws/v1` (WebSocket) a partir de um registo único `simremap.api.registry.ROUTERS`, com uma `tag` OpenAPI por componente. | Must | `GET /openapi.json` lista as tags registadas; um router com prefixo fora de `/api/v1` ou `/ws/v1` faz `create_app` lançar `RouterPrefixError` no arranque. |
| 🟡 RF-04 | 🟡 O sistema deve carregar a configuração via `pydantic-settings` (prefixo `SIMREMAP_`, ficheiro `.env` opcional) com os campos, padrões e limites do modelo `Settings` da seção 9, aceitando `DATABASE_URL` sem prefixo como alias. | Must | Teste define `SIMREMAP_SIM_HZ=50` e obtém `ValidationError` no arranque (limite 100–1000); `DATABASE_URL=postgresql+asyncpg://...` é aceite e tem precedência sobre o padrão SQLite. |
| 🟡 RF-05 | 🟡 O sistema deve responder a todo erro HTTP (4xx/5xx, incluindo 404 de rota, 405, 422 de validação e exceções não tratadas) com `Content-Type: application/problem+json` e corpo `ProblemDetail` contendo `type`, `title`, `status`, `detail`, `code` e `request_id`. | Must | Teste parametrizado sobre 404, 405, 413, 415, 422 e 500 valida o corpo contra o schema `ProblemDetail`; a resposta 500 não contém stack trace nem caminho de ficheiro. |
| 🟡 RF-06 | 🟡 O sistema deve manter um catálogo de `code` de erro com registo único, padrão `^[A-Z][0-9A-Z_]{2,63}$`, mapeamento fixo `code → status HTTP` e verificação de duplicados no arranque. | Must | Registar o mesmo `code` duas vezes com status diferentes lança `ErrorCodeConflict` no arranque; `GET /api/v1/version` devolve `error_catalog_sha256` estável entre arranques. |
| 🟡 RF-07 | 🟡 O sistema deve expor `GET /api/v1/health` com estado agregado (`ok`, `degraded`, `down`) e verificações individuais de `database`, `redis` e `sim_worker`, respondendo 200 em `ok`/`degraded` e 503 em `down`. | Must | Com Redis configurado e indisponível, a resposta é 200 com `status = "degraded"` e `checks.redis.status = "down"`; com banco indisponível, a resposta é 503 com `code = "SERVICE_UNAVAILABLE"` no corpo de erro. |
| 🟡 RF-08 | 🟡 O sistema deve expor `GET /api/v1/version` com `app_version` (SemVer), `api_version = "v1"`, `package_format_version`, `datalog_format_version`, `alembic_head`, `git_sha`, `build_time_utc` e `python_version`. | Must | O campo `alembic_head` é igual ao resultado de `alembic heads`; `app_version` casa com o regex SemVer 2.0; resposta em < 20 ms P95. |
| 🟡 RF-09 | 🟡 O sistema deve fornecer uma sessão `AsyncSession` do SQLAlchemy por pedido via dependência `get_session`, com commit explícito pelo chamador e rollback automático em exceção. | Must | Teste que lança exceção depois de `session.add()` confirma 0 linhas persistidas; 100 pedidos concorrentes em SQLite terminam sem `database is locked`. |
| 🟡 RF-10 | 🟡 O sistema deve gerir o schema com Alembic, com migração inicial `0001_foundation_base`, convenção de nomes de constraints fixa e aplicação automática no arranque quando `SIMREMAP_DB_AUTO_MIGRATE=true`. | Must | Num volume vazio, o arranque cria as tabelas `app_meta` e `alembic_version`; `alembic downgrade base` seguido de `alembic upgrade head` termina com código 0 em SQLite e em PostgreSQL 16. |
| 🟡 RF-11 | 🟡 O sistema deve hospedar o laço físico num `SimWorkerHost` que executa cada sessão de simulação num processo dedicado (modo `process`, padrão) ou numa thread (modo `thread`, só testes), sem executar nenhum tick no event loop asyncio. | Must | Teste instrumenta o event loop e confirma 0 chamadas de `tick()` na thread do loop; com 1 sessão a 1000 Hz, o atraso do event loop (lag medido por timer de 10 ms) fica com P99 < 20 ms. |
| 🟡 RF-12 | 🟡 O sistema deve trocar dados entre o worker e o event loop só por filas limitadas: comandos (cliente → worker, capacidade 64) e saídas (worker → cliente, capacidade 256), com política "descartar o mais antigo" na fila de saída e nunca bloquear o worker. | Must | Teste com consumidor parado durante 10 s mantém o worker a ≥ 99 % de `sim_hz` e incrementa `dropped_outputs`; a fila de comandos cheia devolve `SIM_WORKER_BUSY` (503) ao chamador. |
| 🟡 RF-13 | 🟡 O sistema deve emitir logs estruturados em JSON (uma linha por evento, UTF-8) com os campos `ts`, `level`, `logger`, `event`, `request_id` e, quando aplicável, `session_id`, `run_id` e `code`. | Must | `jq -e .` aceita 100 % das linhas de stdout de um teste de fumo; nenhuma linha contém endereço IP do cliente nem `nickname`. |
| 🟡 RF-14 | 🟡 O sistema deve atribuir um `request_id` (UUID4 ou o valor de `X-Request-ID` recebido, se tiver ≤ 64 caracteres `[0-9A-Za-z-]`) e devolvê-lo no cabeçalho `X-Request-ID` e no corpo `ProblemDetail`. | Must | Pedido com `X-Request-ID: abc-123` recebe o mesmo valor na resposta; pedido com valor de 200 caracteres recebe um UUID4 novo. |
| 🟡 RF-15 | 🟡 O sistema deve servir o build estático do frontend (`/` e `/assets/*`) a partir de `SIMREMAP_STATIC_DIR`, com fallback SPA para `index.html` em rotas que não começam por `/api/` nem `/ws/`. | Must | `GET /dyno/qualquer` devolve 200 com `index.html`; `GET /api/v1/inexistente` devolve 404 `application/problem+json` com `code = "ROUTE_NOT_FOUND"`. |
| 🟡 RF-16 | 🟡 O sistema deve aplicar CORS só para origens `http://localhost:<porta>` e `http://127.0.0.1:<porta>` listadas em `SIMREMAP_CORS_ORIGINS`, sem credenciais, e recusar qualquer outra origem. | Must | Pedido preflight com `Origin: http://evil.example` não recebe `Access-Control-Allow-Origin`; uma origem não-localhost em `SIMREMAP_CORS_ORIGINS` faz o arranque falhar com `ValidationError`. |
| 🟡 RF-17 | 🟡 O sistema deve fornecer um Dockerfile multi-stage (build do frontend em Node 20, resolução de dependências com `uv` e runtime `python:3.12-slim` com utilizador não-root) e ficheiros `compose.yaml` + `compose.dev.yaml` + `compose.staging.yaml` + `compose.prod.yaml` com a mesma imagem. | Must | `docker build` termina com imagem ≤ 450 MB; `docker inspect` mostra `User = 10001`; staging e prod usam a mesma tag de imagem e diferem só em variáveis de ambiente e limites. |
| 🟡 RF-18 | 🟡 O sistema deve definir limites de recurso do container de staging/prod para o hardware de referência: `cpus: 3.0`, `mem_limit: 3g`, `pids_limit: 256`, volume nomeado `simremap-data` montado em `/data`. | Must | `docker compose config` mostra os limites; um teste de carga de 10 min com 1 sessão a 1000 Hz mantém RSS do container ≤ 1,5 GB. |
| 🟡 RF-19 | 🟡 O sistema deve fornecer `make check` (e o equivalente `scripts/check.sh`) que executa, por esta ordem, `ruff check`, `ruff format --check`, `mypy --strict`, `bandit`, `pytest` com cobertura, verificação de cobertura por pacote, `eslint`, `tsc --noEmit` e `vitest run`, falhando no primeiro erro. | Must | Introduzir um `Any` implícito num pacote faz `make check` sair com código ≠ 0 na etapa mypy; um pacote de domínio com 84 % de cobertura faz a etapa `coverage-per-package` falhar. |
| 🟡 RF-20 | 🟡 O sistema deve aplicar a política zero-PII: nenhum campo de dados pessoais (nome real, e-mail, telefone, documento, IP) em modelos persistidos, logs ou exports; o access log do Uvicorn fica desativado e substituído pelo log JSON sem IP. | Must | Teste de varredura em todos os modelos SQLModel e contratos Pydantic falha se algum campo casar com `(?i)(email|phone|cpf|address|ip_addr|real_name)`; o log de pedido não contém o IP do cliente. |
| 🟡 RF-21 | 🟡 O sistema deve versionar a API pelo prefixo `/api/v1` e `/ws/v1`, o envelope WebSocket pelo campo `v = 1`, e os formatos de ficheiro por inteiros `package_format_version = 1` e `datalog_format_version = 1` expostos em `/api/v1/version`. | Must | Um teste de contrato compara as constantes em `simremap.core.versions` com a resposta de `/api/v1/version`; mudar uma constante sem atualizar `CHANGELOG` de formatos faz o teste falhar. |
| 🟡 RF-22 | 🟡 O sistema deve usar Redis só quando `SIMREMAP_REDIS_URL` estiver definido, com interface `KeyValueCache` e implementação em memória (LRU, 10 000 chaves, TTL) como fallback automático quando Redis está ausente ou indisponível. | Should | Sem `SIMREMAP_REDIS_URL`, `cache.set/get` funcionam e `/api/v1/health` mostra `checks.redis.status = "disabled"`; com Redis parado durante a execução, o cache passa a memória em ≤ 1 s e regista `cache.fallback`. |
| 🟡 RF-23 | 🟡 O sistema deve limitar o tamanho do corpo de pedido a `SIMREMAP_MAX_BODY_BYTES` (padrão 16 MiB), com override por rota via dependência `body_limit(bytes)`, respondendo 413 `PAYLOAD_TOO_LARGE`. | Should | Um POST de 17 MiB numa rota sem override recebe 413 sem que o handler seja chamado; uma rota com `body_limit(64 MiB)` aceita 40 MiB. |
| 🟡 RF-24 | 🟡 O sistema deve aplicar cabeçalhos de segurança em todas as respostas: `Content-Security-Policy` restrita a `'self'` (com `connect-src 'self' ws://localhost:* ws://127.0.0.1:*`), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` e `X-Frame-Options: DENY`. | Should | Teste verifica os 4 cabeçalhos em `/`, `/api/v1/health` e numa resposta 404. |

### 6.2 Fluxo Principal (Happy Path)

1. 🟡 O usuário (instrutor ou aluno) executa `docker compose -f compose.yaml -f compose.prod.yaml up -d` numa estação com a imagem `simremap:<versão>` carregada.
2. 🟡 O sistema lê `Settings` das variáveis `SIMREMAP_*`, valida limites e configura o logging JSON (`startup.settings`).
3. 🟡 O sistema cria o engine async (SQLite em `/data/simremap.db` por padrão), aplica `PRAGMA journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout=5000` e executa `alembic upgrade head` (`startup.migrations`).
4. 🟡 O sistema tenta ligar ao Redis se `SIMREMAP_REDIS_URL` existir; sem Redis, ativa o cache em memória (`startup.cache`).
5. 🟡 O sistema inicia o `SimWorkerHost` (sem sessões ativas, 0 processos filhos até ao primeiro `POST /api/v1/sessions` de dyno-bench) e monta os routers registados (`startup.routers`).
6. 🟡 O Docker HEALTHCHECK chama `GET /api/v1/health` a cada 10 s e recebe 200 `status = "ok"` em < 60 s após o `up`.
7. 🟡 O usuário abre `http://localhost:8000` no Chromium/Firefox; o sistema serve `index.html` e os assets com `Cache-Control: public, max-age=31536000, immutable` para ficheiros com hash.
8. 🟡 O frontend chama `GET /api/v1/version`, confirma `api_version = "v1"` e segue para a tela inicial.
9. 🟡 Resultado: aplicação disponível, banco migrado, worker pronto e logs JSON em stdout, sem nenhuma ligação de rede externa.

### 6.3 Fluxos Alternativos

**Fluxo Alternativo A — Desenvolvimento local com hot reload:**
1. 🟡 O desenvolvedor executa `docker compose -f compose.yaml -f compose.dev.yaml up`.
2. 🟡 O sistema monta `backend/src` e `frontend/src` como bind mounts, corre Uvicorn com `--reload` na porta 8000 e o Vite dev server na porta 5173 com proxy de `/api` e `/ws` para `http://backend:8000`.
3. 🟡 O sistema aceita CORS de `http://localhost:5173` e `http://127.0.0.1:5173` (padrão do perfil `dev`).

**Fluxo Alternativo B — PostgreSQL e Redis opcionais (staging):**
1. 🟡 O usuário ativa os perfis Compose `postgres` e `redis` (`--profile postgres --profile redis`).
2. 🟡 O sistema recebe `DATABASE_URL=postgresql+asyncpg://simremap:...@postgres:5432/simremap` e `SIMREMAP_REDIS_URL=redis://redis:6379/0`, aguarda o healthcheck dos serviços (`depends_on: condition: service_healthy`) e aplica as mesmas migrações.

**Fluxo Alternativo C — Banco indisponível no arranque:**
1. 🟡 O sistema tenta ligar ao banco 5 vezes com backoff exponencial (0,5 s, 1 s, 2 s, 4 s, 8 s).
2. 🟡 Sem sucesso, o sistema regista `startup.failed` com `code = "DATABASE_UNAVAILABLE"` e termina com código de saída 3; o Docker reinicia o container (`restart: unless-stopped`).

**Fluxo Alternativo D — Execução sem Docker (desenvolvimento):**
1. 🟡 O desenvolvedor executa `make dev`, que corre `uv run uvicorn simremap.api.main:app --reload` e `npm --prefix frontend run dev` em paralelo.
2. 🟡 O sistema usa `SIMREMAP_DATA_DIR=./.data` e cria `./.data/simremap.db`.

---

## 7. Requisitos Não-Funcionais

| ID | Requisito | Valor alvo | Observação |
|----|-----------|-----------|------------|
| 🟡 RNF-01 | Performance (I/O isolado do laço) | P95 de `GET /api/v1/health` < 50 ms e lag do event loop P99 < 20 ms com 1 sessão a 1000 Hz | Medido com `pytest-benchmark` + sonda de lag (timer de 10 ms) em 4 núcleos. |
| 🟡 RNF-02 | Arranque | ≤ 60 s até health `ok` (imagem construída, volume vazio); ≤ 15 s com volume já migrado | Inclui migrações Alembic. |
| 🟡 RNF-03 | Recursos | RSS ocioso ≤ 300 MB; RSS com 1 sessão ativa ≤ 1,5 GB; limite do container 3 GB e 3,0 CPUs | Deixa ≥ 4 GB e 1 núcleo ao navegador no hardware de referência. |
| 🟡 RNF-04 | Qualidade | Cobertura ≥ 85 % por pacote de domínio; 0 erros `mypy --strict`; 0 achados `bandit` com severidade ≥ média; 0 erros `eslint`/`tsc` | Aplicado por `make check`. |
| 🟡 RNF-05 | Imagem | ≤ 450 MB; build com cache em ≤ 3 min; reconstrução sem cache ≤ 10 min | Medido com `docker image inspect`. |
| 🟡 RNF-06 | Privacidade | 0 campos de PII em modelos, logs e exports; 0 ligações de rede de saída | Teste de varredura de campos + `--network none` no teste de fumo. |
| 🟡 RNF-07 | Determinismo de build | `uv.lock` e `package-lock.json` obrigatórios; `uv sync --frozen` e `npm ci` | Builds repetidos produzem o mesmo conjunto de dependências. |
| 🟡 RNF-08 | Portabilidade | Imagem `linux/amd64` e `linux/arm64`; navegadores Chromium ≥ 120 e Firefox ≥ 120 | macOS com Apple Silicon usa `arm64`. |

---

## 8. Design e Interface

**Componentes afetados:**
- 🟡 Backend: `backend/src/simremap/core/` (config, erros, versões, logging, cache), `backend/src/simremap/api/` (factory, middleware, registo de routers, health/version), `backend/src/simremap/db/` (engine, sessão, base declarativa, Alembic), `backend/src/simremap/core/worker/` (`SimWorkerHost`).
- 🟡 Frontend: `frontend/` (Vite, TypeScript strict, Tailwind, ESLint), `frontend/src/lib/api/` (cliente REST com parser de `ProblemDetail`), `frontend/src/lib/ws/` (cliente WebSocket base).
- 🟡 Infra: `Dockerfile`, `compose*.yaml`, `Makefile`, `scripts/check.sh`, `scripts/coverage_per_package.py`.
- 🟡 Endpoints: `GET /api/v1/health`, `GET /api/v1/version`.

**Convenção de escrita dos blocos de código desta spec:** 🟡 argumentos de tipos genéricos que começam por letra aparecem entre aspas (forward references válidas em Pydantic v2 e mypy), por exemplo `dict["str", "HealthCheck"]`; na implementação, as aspas podem ser removidas.

**Layout do monorepo:**

```text
SimuladorRemap/
  Makefile
  Dockerfile
  compose.yaml               base comum (serviço app, volume simremap-data)
  compose.dev.yaml           bind mounts, --reload, vite dev 5173
  compose.staging.yaml       imagem fixa, limites, perfis postgres/redis
  compose.prod.yaml          imagem fixa, limites, restart unless-stopped
  scripts/check.sh
  scripts/coverage_per_package.py
  backend/
    pyproject.toml
    uv.lock
    alembic.ini
    src/simremap/
      core/ config.py errors.py versions.py logging.py cache.py worker/
      physics/ damage/ catalog/ dyno/ ecu/ profiles/ telemetry/ scenarios/
      api/ main.py registry.py middleware.py health.py
      db/ engine.py base.py migrations/env.py migrations/versions/
    tests/ unit/ integration/ contract/
  frontend/
    package.json package-lock.json vite.config.ts tsconfig.json eslint.config.js
    src/ main.tsx app/ features/ lib/api/ lib/ws/ lib/units/
```

**`pyproject.toml` (conteúdo normativo):**
- 🟡 Seção `project`: `name = "simremap"`, `version = "0.1.0"`, `requires-python = ">=3.12,<3.14"`.
- 🟡 Dependências de runtime: `fastapi>=0.115`, `uvicorn` com o extra `standard` (`>=0.30`), `pydantic>=2.8`, `pydantic-settings>=2.4`, `sqlmodel>=0.0.21`, `sqlalchemy` com o extra `asyncio` (`>=2.0.30`), `aiosqlite>=0.20`, `asyncpg>=0.29`, `alembic>=1.13`, `structlog>=24.1`, `numpy>=2.0`, `redis>=5.0`, `orjson>=3.10`.
- 🟡 Grupo `dev` (seção `dependency-groups`): `pytest>=8`, `pytest-asyncio>=0.23`, `pytest-cov>=5`, `pytest-benchmark>=4`, `httpx>=0.27`, `asgi-lifespan>=2.1`, `ruff>=0.6`, `mypy>=1.11`, `bandit>=1.7`.
- 🟡 Ruff (`tool.ruff`): `line-length = 100`, `target-version = "py312"`, regras `E, F, W, I, B, UP, S, ASYNC, RUF, PL`.
- 🟡 Mypy (`tool.mypy`): `strict = true`, plugin `pydantic.mypy`.
- 🟡 Pytest (`tool.pytest.ini_options`): `asyncio_mode = "auto"`, `addopts = "--cov=simremap --cov-report=json:coverage.json --cov-report=term-missing"`.

**Factory e lifespan (contrato):**

```python
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from fastapi import FastAPI

def create_app(settings: "Settings | None" = None) -> FastAPI:
    """Ordem de startup: logging -> db engine -> migrations -> cache -> worker host -> routers.
    Ordem de shutdown: worker host (stop + join, timeout 5 s) -> cache -> db engine dispose."""
    ...

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator["None"]:
    ...  # guarda dependências em app.state: settings, engine, sessionmaker, cache, worker_host
    yield
    ...

# simremap/api/registry.py
from fastapi import APIRouter
RouterEntry = tuple["str", APIRouter]        # (tag do componente, router com prefixo /api/v1 ou /ws/v1)
ROUTERS: list["RouterEntry"] = []

def register(tag: str, router: APIRouter) -> None:
    """Recusa prefixos fora de /api/v1 e /ws/v1 (RouterPrefixError) e tags duplicadas."""
```

**Contratos de erro (RFC 7807):**

```python
from pydantic import BaseModel, Field, ConfigDict
from typing import Literal

class ProblemDetail(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)
    type: str = Field(..., examples=["urn:simremap:problem:vehicle-not-found"])
    title: str = Field(..., max_length=120)
    status: int = Field(..., ge=400, le=599)
    detail: str = Field(..., max_length=2000)
    code: str = Field(..., pattern=r"^[A-Z][0-9A-Z_]{2,63}$")
    request_id: str = Field(..., max_length=64)
    instance: str | None = None                       # caminho do pedido, sem query string
    errors: list["FieldError"] | None = None          # só para 422

class FieldError(BaseModel):
    loc: list["str | int"]
    msg: str
    type: str

class SimRemapError(Exception):
    """Base de todas as exceções de domínio. Cada componente cria subclasses com code fixo."""
    code: str
    status: int
    title: str
    def __init__(self, detail: str, **extra: object) -> None: ...

def register_error(code: str, status: int, title: str) -> None:
    """Regista no catálogo; duplicado com status diferente -> ErrorCodeConflict no arranque."""
```

- 🟡 Regra do campo `type`: `urn:simremap:problem:` + `code` em minúsculas com `_` trocado por `-`.
- 🟡 Regra do campo `detail`: texto em pt-BR, sem stack trace, sem caminhos de ficheiro, sem valores de configuração sensíveis.
- 🟡 Erros de validação do FastAPI (`RequestValidationError`) são convertidos em 422 `VALIDATION_FAILED` com `errors` preenchido.

**Catálogo de `code` da fundação (os outros componentes registam os seus):**

| Code | Status | Quando |
|------|--------|--------|
| 🟡 `VALIDATION_FAILED` | 422 | Corpo, query ou path inválido segundo o schema Pydantic. |
| 🟡 `ROUTE_NOT_FOUND` | 404 | Rota `/api/*` ou `/ws/*` inexistente. |
| 🟡 `RESOURCE_NOT_FOUND` | 404 | Base genérica; componentes devem preferir códigos específicos (ex.: `VEHICLE_NOT_FOUND`). |
| 🟡 `METHOD_NOT_ALLOWED` | 405 | Método HTTP não suportado na rota. |
| 🟡 `PAYLOAD_TOO_LARGE` | 413 | Corpo acima de `max_body_bytes` ou do override da rota. |
| 🟡 `UNSUPPORTED_MEDIA_TYPE` | 415 | `Content-Type` diferente do aceite pela rota. |
| 🟡 `CONFLICT` | 409 | Base genérica de conflito de estado. |
| 🟡 `INTERNAL_ERROR` | 500 | Exceção não tratada; o log JSON regista `exc_type` e stack trace, a resposta não. |
| 🟡 `SERVICE_UNAVAILABLE` | 503 | Health `down` (banco indisponível). |
| 🟡 `DATABASE_UNAVAILABLE` | 503 | Falha de ligação ao banco num pedido ou no arranque. |
| 🟡 `SIM_WORKER_UNAVAILABLE` | 503 | Processo do worker morreu ou não arrancou em 5 s. |
| 🟡 `SIM_WORKER_BUSY` | 503 | Fila de comandos do worker cheia (64 itens). |
| 🟡 `SIM_CAPACITY_EXCEEDED` | 409 | Pedido de nova sessão acima de `max_active_sessions`. |
| 🟡 `STORAGE_FULL` | 507 | Volume `/data` sem espaço na escrita. |
| 🟡 `STATIC_NOT_BUILT` | 404 | `GET /` sem build do frontend em `SIMREMAP_STATIC_DIR`. |

**Contratos de health e versão:**

```python
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field

CheckStatus = Literal["ok", "down", "disabled"]

class HealthCheck(BaseModel):
    status: CheckStatus
    latency_ms: float | None = Field(default=None, ge=0)
    detail: str | None = Field(default=None, max_length=200)

class HealthStatus(BaseModel):
    status: Literal["ok", "degraded", "down"]   # down se database=down; degraded se redis ou sim_worker = down
    checks: dict["str", "HealthCheck"]              # chaves fixas: "database", "redis", "sim_worker"
    uptime_s: float = Field(..., ge=0)
    active_sessions: int = Field(..., ge=0)

class VersionInfo(BaseModel):
    app_version: str = Field(..., pattern=r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$")
    api_version: Literal["v1"] = "v1"
    ws_envelope_version: Literal[1] = 1
    package_format_version: int = Field(1, ge=1)
    datalog_format_version: int = Field(1, ge=1)
    alembic_head: str
    error_catalog_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    git_sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{7,40}$")
    build_time_utc: datetime | None = None
    python_version: str
```

| Endpoint | Request | Resposta | Códigos HTTP |
|----------|---------|----------|--------------|
| 🟡 `GET /api/v1/health` | sem corpo | `HealthStatus` | 200 (`ok`/`degraded`), 503 (`SERVICE_UNAVAILABLE`) |
| 🟡 `GET /api/v1/version` | sem corpo | `VersionInfo` | 200 |

**Catálogo consolidado de endpoints (revisão R1):** 🟡 todo endpoint REST do produto usa o prefixo `/api/v1/`; o WebSocket usa `/ws/v1/`. O registo `simremap.api.registry` recusa no arranque qualquer router fora destes prefixos (`RouterPrefixError`), e um teste de contrato compara o `openapi.json` com esta tabela.

| Dono | Método e caminho |
|---|---|
| 🟡 platform-foundation | `GET /api/v1/health`, `GET /api/v1/version` |
| 🟡 vehicle-catalog | `GET /api/v1/vehicles`, `GET /api/v1/vehicles/{vehicle_id}`, `GET /api/v1/vehicles/{vehicle_id}/reference-curves` |
| 🟡 dyno-bench | `POST /api/v1/sessions`, `GET /api/v1/sessions/{session_id}`, `DELETE /api/v1/sessions/{session_id}`, `POST /api/v1/sessions/{session_id}/runs`, `POST /api/v1/sessions/{session_id}/runs/{run_id}/abort`, `GET /api/v1/runs/{run_id}` |
| 🟡 knock-and-failure-model | `GET /api/v1/sessions/{session_id}/engine/health`, `POST /api/v1/sessions/{session_id}/engine/restore`, `GET /api/v1/runs/{run_id}/forensic-report` |
| 🟡 ecu-core | `GET /api/v1/calibrations`, `POST /api/v1/calibrations`, `GET /api/v1/calibrations/{calibration_id}`, `PUT /api/v1/calibrations/{calibration_id}`, `PATCH /api/v1/calibrations/{calibration_id}/tables/{table_id}`, `POST /api/v1/sessions/{session_id}/calibration` |
| 🟡 ecu-profiles | `GET /api/v1/ecu-profiles`, `GET /api/v1/ecu-profiles/{profile_id}`, `POST /api/v1/sessions/{session_id}/ecu/swap`, `GET /api/v1/sessions/{session_id}/ecu/base-setup`, `PUT /api/v1/sessions/{session_id}/ecu/base-setup` |
| 🟡 telemetry-datalogger | `GET /api/v1/telemetry/channels`, `GET /api/v1/runs/{run_id}/log`, `POST /api/v1/logs/import`, `POST /api/v1/logs/compare`, WebSocket `/ws/v1/sessions/{session_id}/telemetry` |
| 🟡 training-scenarios | `GET /api/v1/profiles`, `POST /api/v1/profiles`, `GET /api/v1/scenarios`, `POST /api/v1/scenarios`, `GET /api/v1/scenarios/{scenario_id}`, `GET /api/v1/scenarios/{scenario_id}/stats`, `POST /api/v1/scenarios/{scenario_id}/attempts`, `GET /api/v1/attempts`, `GET /api/v1/attempts/{attempt_id}`, `POST /api/v1/attempts/{attempt_id}/hints`, `POST /api/v1/attempts/{attempt_id}/abandon`, `POST /api/v1/attempts/{attempt_id}/submit`, `GET /api/v1/attempts/{attempt_id}/evaluation`, `POST /api/v1/attempts/{attempt_id}/replay`, `POST /api/v1/packages/export`, `POST /api/v1/packages/import` |

🟡 **Códigos de erro transversais padronizados (revisão R1):** `ECU_PROFILE_NOT_FOUND` (404, perfil de ECU inexistente, em todas as specs) e `SIM_CAPACITY_EXCEEDED` (409, limite de sessões ativas atingido, em todas as specs).

- 🟡 A verificação `database` executa `SELECT 1` com timeout de 1 s; `redis` executa `PING` com timeout de 0,5 s; `sim_worker` verifica que todos os processos de sessões ativas respondem a heartbeat nos últimos 2 s.

**Contrato do worker do laço físico (isolamento do event loop):**

```python
from typing import Protocol, Literal
from pydantic import BaseModel, Field

class WorkerConfig(BaseModel):
    mode: Literal["process", "thread"] = "process"
    start_method: Literal["spawn", "forkserver"] = "spawn"
    command_queue_size: int = Field(64, ge=8, le=1024)
    output_queue_size: int = Field(256, ge=16, le=4096)
    heartbeat_interval_s: float = Field(0.5, gt=0, le=5)
    stop_timeout_s: float = Field(5.0, gt=0, le=30)

class SimTask(Protocol):
    """Implementado por dyno-bench (orquestra physics, ecu, damage, telemetry). Corre só no worker."""
    def setup(self, init_payload: bytes) -> None: ...
    def handle_command(self, command: dict["str", object]) -> None: ...
    def tick(self) -> None: ...                      # um passo dt = 1 / sim_hz
    def drain_outputs(self) -> list["bytes"]: ...      # frames/eventos serializados, já decimados
    def teardown(self) -> None: ...

class SimWorkerHandle(Protocol):
    session_id: str
    async def send(self, command: dict["str", object]) -> None: ...   # SIM_WORKER_BUSY se cheia
    def outputs(self) -> "AsyncOutputStream": ...                   # iterador async de bytes
    async def stop(self) -> None: ...
    @property
    def stats(self) -> "WorkerStats": ...

class WorkerStats(BaseModel):
    ticks: int = Field(..., ge=0)
    achieved_hz: float = Field(..., ge=0)            # média móvel de 1 s
    overrun_ticks: int = Field(..., ge=0)            # ticks que excederam dt de parede
    dropped_outputs: int = Field(..., ge=0)
    last_heartbeat_t_wall_s: float
```

- 🟡 Regras de isolamento: (a) o event loop nunca chama `SimTask.tick`; (b) o worker nunca importa `fastapi` nem toca no banco; (c) a comunicação usa só `multiprocessing.Queue` limitadas (modo `process`) ou `queue.Queue` limitadas (modo `thread`), com ponte para asyncio por `loop.run_in_executor` numa thread leitora dedicada; (d) a fila de saída descarta o item mais antigo quando cheia; (e) a fila de comandos nunca descarta: devolve `SIM_WORKER_BUSY`.
- 🟡 Ritmo: o worker avança `t_sim_s` só por contagem de ticks (`t_sim_s = tick_index / sim_hz`); o relógio de parede (`time.perf_counter`) serve só para cadenciar o tempo real e medir `overrun_ticks`, nunca entra no cálculo físico.
- 🟡 Capacidade: `max_active_sessions` padrão 1, máximo 2 por container; cada sessão ocupa 1 processo filho.

**Logging estruturado:**
- 🟡 Biblioteca `structlog` com renderer JSON (`orjson`), saída para stdout, nível por `SIMREMAP_LOG_LEVEL` (padrão `INFO`).
- 🟡 Campos obrigatórios: `ts` (ISO-8601 UTC com milissegundos), `level`, `logger`, `event` (snake/dot case estável, ex.: `http.request`, `worker.overrun`), `request_id`.
- 🟡 Evento `http.request` por pedido: `method`, `path` (sem query string), `status`, `duration_ms`; sem IP, sem cabeçalhos, sem corpo.
- 🟡 O worker envia os seus logs pela fila de saída com tipo interno `log` e o processo principal reemite-os; limite de 50 linhas/s por sessão (excedente contado em `log_dropped`).

**Dockerfile multi-stage (estrutura normativa):**

```dockerfile
FROM node:20-alpine AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build                      # gera /fe/dist

FROM ghcr.io/astral-sh/uv:0.4-python3.12-bookworm-slim AS backend
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --frozen --no-dev

FROM python:3.12-slim-bookworm AS runtime
RUN useradd --uid 10001 --create-home simremap && mkdir /data && chown simremap /data
WORKDIR /app
COPY --from=backend /app /app
COPY --from=frontend /fe/dist /app/static
ENV PATH="/app/.venv/bin:$PATH" SIMREMAP_STATIC_DIR=/app/static SIMREMAP_DATA_DIR=/data
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=2s --retries=6 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health',timeout=2).status==200 else 1)"
CMD ["uvicorn", "simremap.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--ws-ping-interval", "20"]
```

**Compose e perfis de ambiente:**

| Arquivo | Perfil `SIMREMAP_ENV` | Diferenças permitidas |
|---------|----------------------|-----------------------|
| 🟡 `compose.yaml` | base | Serviço `app`, porta `127.0.0.1:8000:8000`, volume `simremap-data:/data`, serviços opcionais `postgres` (perfil `postgres`) e `redis` (perfil `redis`). |
| 🟡 `compose.dev.yaml` | `dev` | Bind mounts, `--reload`, serviço `frontend` (Vite 5173), `LOG_LEVEL=DEBUG`, sem limites. |
| 🟡 `compose.staging.yaml` | `staging` | Imagem com tag fixa, limites da RF-18, perfis `postgres` e `redis` ativos por padrão. |
| 🟡 `compose.prod.yaml` | `prod` | Imagem com tag fixa, limites da RF-18, `restart: unless-stopped`, SQLite em volume. |
| 🟡 testes | `test` | `mode = "thread"`, SQLite em memória (`sqlite+aiosqlite:///:memory:` com `StaticPool`), sem Redis. |

- 🟡 Paridade: staging e prod usam a mesma imagem e o mesmo `CMD`; a única variação é por variáveis de ambiente e pelos limites. O perfil `dev` muda só o comando e os mounts.
- 🟡 A porta publica-se em `127.0.0.1` por padrão; publicar em `0.0.0.0` exige editar `SIMREMAP_BIND_PUBLIC=true` e muda o padrão de CORS (ver OQ-03).

**Pipeline local `make check`:**

```makefile
check: lint type security test cov fe-lint fe-type fe-test
lint:     ; cd backend && uv run ruff check . && uv run ruff format --check .
type:     ; cd backend && uv run mypy --strict src tests
security: ; cd backend && uv run bandit -r src -ll -q
test:     ; cd backend && uv run pytest -q
cov:      ; cd backend && uv run python ../scripts/coverage_per_package.py --min 85 \
              --packages core physics damage catalog dyno ecu profiles telemetry scenarios api db
fe-lint:  ; npm --prefix frontend run lint
fe-type:  ; npm --prefix frontend exec -- tsc --noEmit
fe-test:  ; npm --prefix frontend exec -- vitest run
```

- 🟡 `coverage_per_package.py` lê `coverage.json`, agrega linhas por pacote de topo em `simremap.*` e falha com código 1 listando cada pacote abaixo do mínimo; pacotes ainda vazios (só `__init__.py`) são ignorados.
- 🟡 Frontend: `tsconfig.json` com `"strict": true`, `"noUncheckedIndexedAccess": true`; ESLint com `@typescript-eslint/recommended-type-checked` e `react-hooks`; 0 avisos permitidos (`--max-warnings 0`).

**Cliente REST do frontend (`frontend/src/lib/api/`):**
- 🟡 Função `apiFetch<T>(path, init)` que prefixa `/api/v1`, envia `Accept: application/json` e, em resposta com `Content-Type: application/problem+json`, lança `ApiProblem` com `status`, `code`, `title`, `detail`, `requestId`.
- 🟡 Os componentes de UI mostram `detail` ao usuário e `request_id` num rodapé copiável do erro.

**Estados da UI (casca da aplicação):**
- 🟡 Estado vazio: sem dados de domínio, a casca mostra a navegação e a mensagem "Nenhuma sessão ativa".
- 🟡 Estado de carregamento: enquanto `/api/v1/version` não responde, a casca mostra um indicador de progresso e o texto "A iniciar o simulador".
- 🟡 Estado de erro: se `/api/v1/version` falhar 3 vezes (intervalo de 2 s), a casca mostra "Servidor indisponível" com o `code` e o botão "Tentar de novo".
- 🟡 Estado de sucesso: a casca mostra a versão (`app_version`) no rodapé e libera a navegação.

---

## 9. Modelo de Dados

**Configuração (`simremap/core/config.py`):**

```python
from pathlib import Path
from typing import Literal
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SIMREMAP_", env_file=".env", extra="ignore", frozen=True)

    env: Literal["dev", "test", "staging", "prod"] = "prod"
    data_dir: Path = Path("/data")
    static_dir: Path | None = Path("/app/static")
    database_url: str = Field(
        default="sqlite+aiosqlite:////data/simremap.db",
        validation_alias=AliasChoices("DATABASE_URL", "SIMREMAP_DATABASE_URL"),
    )                                                   # aceita sqlite+aiosqlite:// e postgresql+asyncpg://
    db_auto_migrate: bool = True
    db_pool_size: int = Field(5, ge=1, le=20)           # ignorado em SQLite
    redis_url: str | None = None                        # ex.: redis://redis:6379/0
    cache_max_keys: int = Field(10_000, ge=100, le=1_000_000)
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    bind_public: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    max_body_bytes: int = Field(16 * 1024 * 1024, ge=1024, le=256 * 1024 * 1024)
    sim_hz: int = Field(1000, ge=100, le=1000)          # padrão global; dyno-bench pode pedir outro valor no intervalo
    ws_fps: int = Field(50, ge=30, le=60)               # padrão global de telemetry-datalogger
    worker_mode: Literal["process", "thread"] = "process"
    max_active_sessions: int = Field(1, ge=1, le=2)

    @field_validator("database_url")
    @classmethod
    def _driver(cls, v: str) -> str:
        if not v.startswith(("sqlite+aiosqlite://", "postgresql+asyncpg://")):
            raise ValueError("DATABASE_URL deve usar sqlite+aiosqlite ou postgresql+asyncpg")
        return v

    @field_validator("cors_origins")
    @classmethod
    def _localhost_only(cls, v: list[str]) -> list[str]:
        """Cada origem deve casar com ^http://(localhost|127\\.0\\.0\\.1)(:\\d{1,5})?$ ."""
        ...
```

**Base declarativa e convenção de nomes (`simremap/db/base.py`):**

```python
from sqlalchemy import MetaData

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
metadata = MetaData(naming_convention=NAMING_CONVENTION)
```

- 🟡 Convenções de tabela: nomes em `snake_case` no singular (`dyno_run`, `data_log`), chave primária `id` do tipo `String(36)` (UUID4 texto) ou slug `String(64)` para IDs canónicos (`hatch-20t-gdi`), colunas `created_at` e `updated_at` em UTC (`DateTime(timezone=True)`), JSON em coluna `JSON` (SQLite texto, PostgreSQL `JSONB` via variante), binários em `LargeBinary`.
- 🟡 Mixins fornecidos: `UUIDPrimaryKeyMixin`, `TimestampMixin` (preenchimento por `server_default=func.now()` e `onupdate`).

**Entidades novas:**

```text
app_meta {
  key: String(64) PK          // ex.: "install_id", "schema_created_at", "last_boot_app_version"
  value: String(512)          // texto; install_id é UUID4 local, sem relação com pessoa
  updated_at: DateTime(tz)    // UTC
}
```

**Migrações necessárias:** 🟡 Sim. A revisão `0001_foundation_base` cria `app_meta`. Cada componente acrescenta revisões próprias encadeadas linearmente (`down_revision` da anterior), com nome `NNNN_<componente>_<descricao>`; não são permitidos ramos (`alembic heads` deve devolver 1 revisão, verificado em teste). Migrações devem funcionar em SQLite (com `render_as_batch=True`) e em PostgreSQL 16.

**Sessão async (`simremap/db/engine.py`):**

```python
from collections.abc import AsyncIterator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

def build_engine(settings: "Settings") -> "AsyncEngine": ...
    # SQLite: connect_args={"timeout": 5}, evento "connect" aplica PRAGMA journal_mode=WAL,
    #         foreign_keys=ON, busy_timeout=5000, synchronous=NORMAL
    # PostgreSQL: pool_size=settings.db_pool_size, pool_pre_ping=True

async def get_session() -> AsyncIterator["AsyncSession"]:
    """expire_on_commit=False; rollback automático em exceção; close no fim do pedido."""
```

**Constantes de versão (`simremap/core/versions.py`):**

```python
API_VERSION = "v1"
WS_ENVELOPE_VERSION = 1
PACKAGE_FORMAT_VERSION = 1     # SignedPackage de training-scenarios
DATALOG_FORMAT_VERSION = 1     # DataLog de telemetry-datalogger
```

- 🟡 Regra de compatibilidade: leitores aceitam `format_version` ≤ ao valor atual e recusam valores superiores com o `code` do componente dono (ex.: `LOG_FORMAT_UNSUPPORTED`); mudar a semântica de um campo exige incrementar o inteiro.

---

## 10. Integrações e Dependências

| Dependência | Tipo | Impacto se indisponível |
|-------------|------|------------------------|
| 🟡 Python 3.12 + `uv` | Obrigatória | Sem eles não há build; a imagem Docker fixa as versões. |
| 🟡 FastAPI, Uvicorn, Pydantic v2, pydantic-settings | Obrigatória | Sem servidor; falha de build. |
| 🟡 SQLAlchemy 2 async + SQLModel + Alembic + aiosqlite | Obrigatória | Sem persistência; arranque termina com código 3 após retry (Fluxo C). |
| 🟡 PostgreSQL 16 + asyncpg | Opcional | Fallback para SQLite padrão quando `DATABASE_URL` não está definido. |
| 🟡 Redis 7 | Opcional | Fallback automático para cache em memória; health `degraded`. |
| 🟡 structlog + orjson | Obrigatória | Sem logging JSON; falha de build. |
| 🟡 NumPy 2 | Obrigatória | Usado pelos componentes físicos dentro do worker. |
| 🟡 Node 20 + Vite + React 18 + TypeScript + Tailwind + ESLint + Vitest | Obrigatória (build) | Sem frontend estático; a API continua a funcionar. |
| 🟡 Docker Engine ≥ 24 + Compose v2 | Obrigatória (distribuição) | Execução sem Docker possível só em modo dev (Fluxo D). |
| 🟡 dyno-bench (`SimTask`) | Consumidor interno | Sem `SimTask`, o worker arranca sem sessões; health `sim_worker` = `ok` com 0 sessões. |
| 🟡 Todos os componentes (routers, erros, migrações) | Consumidores internos | Registam-se em `registry.ROUTERS`, `register_error` e na cadeia Alembic. |

---

## 11. Edge Cases e Tratamento de Erros

| Cenário | Trigger | Comportamento esperado |
|---------|---------|----------------------|
| 🟡 EC-01: Banco indisponível no arranque | SQLite em volume sem permissão de escrita ou PostgreSQL fora do ar | 🟡 Retry com backoff (0,5 → 8 s, 5 tentativas); depois log `startup.failed` com `code = "DATABASE_UNAVAILABLE"` e saída com código 3. |
| 🟡 EC-02: Banco cai durante a execução | Timeout de 1 s em `SELECT 1` ou erro de ligação num pedido | 🟡 Pedido devolve 503 `DATABASE_UNAVAILABLE`; health devolve 503 `down`; o worker continua a correr (não depende do banco). |
| 🟡 EC-03: Redis indisponível | `PING` falha ou timeout de 0,5 s | 🟡 Fallback para cache em memória em ≤ 1 s, log `cache.fallback`, health `degraded`; retry de ligação a cada 30 s. |
| 🟡 EC-04: Processo do worker morre | Exceção não tratada no `SimTask` ou OOM do processo filho | 🟡 Heartbeat ausente por 2 s marca a sessão como falhada; o host emite saída interna `worker.crashed`; pedidos à sessão devolvem 503 `SIM_WORKER_UNAVAILABLE`; nenhum restart automático da sessão. |
| 🟡 EC-05: Worker não acompanha o ritmo | Tick de parede > `dt` em ≥ 5 % dos ticks numa janela de 1 s | 🟡 Incrementa `overrun_ticks`, log `worker.overrun` (máx. 1/s); a física continua determinística porque `t_sim_s` depende só da contagem de ticks. |
| 🟡 EC-06: Consumidor lento | Fila de saída cheia (256 itens) | 🟡 Descarta o item mais antigo, incrementa `dropped_outputs`; o worker nunca bloqueia. |
| 🟡 EC-07: Fila de comandos cheia | 64 comandos pendentes | 🟡 `send()` devolve 503 `SIM_WORKER_BUSY` sem bloquear o event loop. |
| 🟡 EC-08: Configuração inválida | `SIMREMAP_SIM_HZ=2000`, origem CORS não-localhost ou driver de banco desconhecido | 🟡 Falha no arranque com `ValidationError` legível no log JSON (`startup.invalid_settings`, campos e limites); saída com código 2. |
| 🟡 EC-09: Migração com ramos | Duas revisões com o mesmo `down_revision` | 🟡 Teste `test_single_alembic_head` falha em `make check`; no arranque, `alembic upgrade head` recusa com log `startup.migrations_failed`. |
| 🟡 EC-10: Volume `/data` cheio | `OSError: No space left on device` na escrita | 🟡 Pedido devolve 507 `STORAGE_FULL` (registado pela fundação); health mantém `ok` se leitura funcionar; log `db.storage_full`. |
| 🟡 EC-11: Build do frontend ausente | `SIMREMAP_STATIC_DIR` inexistente ou sem `index.html` | 🟡 A API arranca normalmente; `GET /` devolve 404 `STATIC_NOT_BUILT` com `detail` a indicar `npm run build`; log `startup.static_missing`. |
| 🟡 EC-12: Shutdown com sessão ativa | `SIGTERM` do Docker durante uma puxada | 🟡 O host envia `stop` ao worker, aguarda até 5 s, depois termina o processo; o lifespan fecha o engine; saída com código 0 em ≤ 10 s. |
| 🟡 EC-13: Exceção não tratada num handler | Bug num router de componente | 🟡 Resposta 500 `INTERNAL_ERROR` em `problem+json` sem stack trace; log JSON com `exc_type`, `request_id` e stack trace. |
| 🟡 EC-14: `X-Request-ID` malicioso | Cabeçalho com mais de 64 caracteres ou caracteres de controle | 🟡 Valor descartado, novo UUID4 gerado; nenhum eco do valor original no log. |
| 🟡 EC-15: Capacidade de sessões excedida | Segundo `POST /api/v1/sessions` com `max_active_sessions = 1` | 🟡 409 `SIM_CAPACITY_EXCEEDED`; nenhuma criação de processo. |

---

## 12. Segurança e Privacidade

- 🟡 **Autenticação:** nenhuma (NG-01). A superfície fica restrita por publicação da porta em `127.0.0.1` e por CORS só localhost.
- 🟡 **Autorização:** sem papéis na fundação; a distinção aluno/instrutor (`role`) pertence a training-scenarios e não é um controle de segurança.
- 🟡 **Dados sensíveis:** zero PII (RF-20); o `install_id` é um UUID4 aleatório local; logs sem IP, cabeçalhos ou corpos.
- 🟡 **Auditoria:** log JSON de cada pedido (`http.request`) e de eventos de ciclo de vida (`startup.*`, `shutdown.*`, `worker.*`); sem log de auditoria persistido.
- 🟡 **Container:** utilizador não-root `10001`, sistema de ficheiros da aplicação só leitura em prod (`read_only: true` com `tmpfs: /tmp`), volume gravável só em `/data`, `cap_drop: ["ALL"]`, `security_opt: ["no-new-privileges:true"]`.
- 🟡 **Cadeia de dependências:** lockfiles obrigatórios; `bandit -ll` no portão; nenhuma dependência proprietária (custo zero em licenças).
- 🟡 **Rede:** nenhuma chamada de saída; o teste de fumo corre com `--network none` (exceto loopback) e deve passar.

---

## 13. Plano de Rollout

- 🟡 **Estratégia:** big bang local por versão de imagem (`simremap:<SemVer>`); cada estação recebe a imagem por `docker load` (ficheiro `.tar`) ou registry local; sem feature flags na fundação.
- 🟡 **Como reverter (rollback):** (1) parar o container; (2) iniciar a tag anterior; (3) se a nova versão aplicou migrações, executar `docker compose run --rm app alembic downgrade <revisão anterior>` antes de iniciar a tag anterior; cópia de segurança automática de `/data/simremap.db` para `/data/backup/simremap-<versão>-<timestamp>.db` antes de cada `upgrade` com revisões pendentes (mantém as 3 últimas).
- 🟡 **Monitoramento pós-deploy:** nas primeiras 48 h, observar no log JSON `worker.overrun` (alvo < 1 % dos ticks), `cache.fallback`, eventos com `level = "error"` (alvo 0) e o estado do HEALTHCHECK do Docker (`docker ps` sem `unhealthy`).

---

## 14. Open Questions

| # | Pergunta | Impacto | Dono | Prazo |
|---|---------|---------|------|-------|
| 🟡 OQ-01 | ⚠️ ABERTO: o modo `process` (spawn + filas `multiprocessing`) cumpre 1000 Hz com telemetria a 50 FPS no hardware de referência, ou o padrão deve ser `thread` com NumPy liberando o GIL? Decidir por benchmark no Sprint 1. | Alto | George | 2026-10-24 |
| 🟡 OQ-02 | ⚠️ ABERTO: o limite do container (3 GB, 3,0 CPUs) deixa folga suficiente ao navegador com WebGL na mesma máquina de 8 GB? | Médio | George | 2026-10-31 |
| 🟡 OQ-03 | ⚠️ ABERTO: o instrutor precisa de acessar a estação do aluno pela rede local (publicar em `0.0.0.0`)? Se sim, a política CORS só localhost e a ausência de autenticação precisam de revisão. | Médio | George | 2026-11-07 |
| 🟡 OQ-04 | ⚠️ ABERTO: PostgreSQL entra na matriz de testes de cada sprint ou só no fim do Sprint 4? | Baixo | George | 2026-10-25 |
| 🟡 OQ-05 | ⚠️ ABERTO: `max_active_sessions` deve permitir 2 sessões (ex.: comparação ao vivo pelo instrutor) ou fixar 1 no MVP? | Baixo | George | 2026-11-01 |

---

## 15. Decisões Tomadas (Decision Log)

| Decisão | Alternativas consideradas | Racional |
|---------|--------------------------|---------|
| 🟡 Frontend em Vite (SPA) servido pelo FastAPI na mesma imagem | Next.js com SSR; Nginx separado | Local-first, um container por estação, sem servidor Node em runtime; reduz imagem e superfície. |
| 🟡 Worker do laço físico em processo dedicado por sessão (padrão), thread só em testes | Laço no event loop; thread única para todas as sessões | Evita competição pelo GIL com o I/O asyncio (risco 1 do PRD); isolamento de falhas por sessão; sujeito a confirmação em OQ-01. |
| 🟡 Filas limitadas com descarte do mais antigo na saída e recusa explícita na entrada | Filas ilimitadas; bloqueio do produtor | O laço físico nunca bloqueia; comandos do usuário nunca se perdem em silêncio. |
| 🟡 Erros RFC 7807 com `type` em URN `urn:simremap:problem:*` | URLs HTTP para documentação de erro | O produto é offline; uma URN não sugere um recurso de rede inexistente. |
| 🟡 SQLite com WAL em volume Docker como padrão; PostgreSQL por `DATABASE_URL` | PostgreSQL obrigatório | Um container por estação sem serviços extras; PostgreSQL fica para staging/servidor local. |
| 🟡 structlog com JSON em stdout | `logging` padrão com formatter próprio; ficheiros de log | Formato estável com contexto (`request_id`, `session_id`) e coleta por `docker logs`. |
| 🟡 Cobertura mínima por pacote de domínio, não global | Cobertura global ≥ 85 % | Uma média global esconderia pacotes de domínio sem testes. |
| 🟡 Porta publicada em `127.0.0.1` por padrão | `0.0.0.0` | Sem autenticação, expor na rede local seria um risco; a exceção fica em OQ-03. |

---

## Apêndice

### Referências
- 🟡 `_reversa_sdd/prd.md` (seções 6, 7, 8 e 9: restrições, dependências, riscos e critério de desempenho).
- 🟡 `_reversa_sdd/personas.md` (Lucas, Rodrigo, Prof. Marcos).
- 🟡 RFC 7807 / RFC 9457 (Problem Details for HTTP APIs).
- 🟡 Documentação de FastAPI (lifespan), pydantic-settings, SQLAlchemy 2 asyncio, Alembic (naming conventions, batch mode), uv (Docker integration).

### Histórico de Revisões
| Versão | Data | Autor | Mudanças |
|--------|------|-------|---------|
| 🟡 1.0 | 2026-10-18 | reversa-spec-sdd | Criação inicial |
| 🟡 1.1 | 2026-10-18 | reversa-spec-sdd | Revisão R1 de consistência entre specs (decisões do usuário: knock, nomes de campo, códigos de erro, seq, campos de integração, prefixo /api/v1/, OEM-Stage, benchmark v1) |

## Relatório de avaliação (reversa-spec-sdd)

- 🟡 Score final: 100,0/100 (Excelente, pronta para implementação)
- 🟡 Iterações: 2 (scores: 85,0 → 100,0)
- 🟡 Breakdown: Completude 100 %, Testabilidade 100 %, Clareza 100 %, Escopo 100 %, Edge Cases 100 %
- 🟡 Gaps críticos remanescentes: nenhum
- 🟡 Sugestões remanescentes: nenhuma
- 🟡 Revisão R1 (2026-10-18): reavaliado após a revisão de consistência entre specs, score 100,0/100.
