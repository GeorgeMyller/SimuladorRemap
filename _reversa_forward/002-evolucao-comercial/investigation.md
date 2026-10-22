# Investigation: 002-evolucao-comercial

> Data: 2026-10-18. Pesquisa de fundo feita sobre o código entregue pela feature 001.

## 1. Causa raiz do SCENARIO_CALIBRATION_HASH_MISMATCH

- O hash do cenário builtin é injetado em `scenarios/catalog.py::load_builtin` a partir de `calibrations.stock(...).content_hash` (v1 do banco) ou, sem stock, de `factory_content_hash`.
- O clone (`scenarios/ports.py::EcuCalibrationPort.clone`) chama `create(source.content)`, que refaz `parse_content` e recalcula o hash no servidor.
- Qualquer diferença na ida e volta `model_dump(mode="json")` → `parse_content` (padrões preenchidos, floats arredondados, chaves novas), ou um fallback para o hash de fábrica quando o stock ainda não existia, gera hashes diferentes. O teste unitário não pega o caso porque `FakeCalibrations.clone` copia o hash da fonte e `stock` devolve a última versão (o real devolve a v1).
- O seed (`ecu/seed_stock.py`) compara com a **última** versão e grava v2+ quando o arquivo muda, mas o cenário continua preso à v1.

## 2. VVT: alternativas

| Alternativa | Custo por tick | Fidelidade | Escolha |
|---|---|---|---|
| Fator empírico de overlap sobre a VE (tanh) | O(1) | Captura a tendência baixa/alta rotação | ✅ |
| Modelo 1D de ondas no coletor | alto | alta | ❌ (orçamento de 1 ms) |
| Mapa de VE 3D por came (rpm × map × came) | O(1) | depende de dados que o catálogo não tem | ❌ |

Referência conceitual: Heywood, *Internal Combustion Engine Fundamentals*, cap. 6 (eficiência volumétrica, overlap e scavenging).

## 3. Blend de etanol

- AFR estequiométrico do blend: `1/AFR = Σ w_i / AFR_i` na fração mássica (combustíveis E27 e E100 como âncoras).
- PCI, calor latente e densidade: lineares na fração mássica.
- Octanagem: aproximação por curva côncava (o etanol eleva o RON de forma não linear nas primeiras frações).
- Sensor flex: na prática mede a fração de etanol por frequência (50–150 Hz); aqui o sensor publica direto `ethanol_pct` com ruído pequeno e determinístico.

## 4. Divisão de chunks no Vite

- O chunk `Table3DSurface` (530 kB) contém three.js inteiro. Opções: importações nomeadas (tree-shaking do pacote ESM), `build.rollupOptions.output.manualChunks` por pacote, e garantir que só `React.lazy` carregue o chunk.

## 5. Padrões aplicáveis

- Clone-on-write para recursos de fábrica (calibração stock).
- Operações puras sobre tabelas (já usadas em `ecu-tuning/ops`).
- Orquestração de jogo sobre o serviço de tentativas (carreira = camada fina sobre `AttemptService`).
