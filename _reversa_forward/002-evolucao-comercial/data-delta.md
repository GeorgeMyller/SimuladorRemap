# Data Delta: 002-evolucao-comercial

> Diff conceitual sobre o modelo da feature 001 (`_reversa_forward/001-simulador-remap/data-model.md`).

## Tabelas novas (migração `0008_career`, encadeada após `0007_scenarios_base`)

### `career_profiles`

| Campo | Tipo | Regra |
|---|---|---|
| `profile_id` | texto PK | id do perfil local (nickname) |
| `balance_brl` | inteiro (centavos) | começa em 500000 (R$ 5.000,00); pode ficar negativo |
| `reputation` | inteiro | 0–100, começa em 50 |
| `created_at`, `updated_at` | timestamp UTC | — |

### `career_jobs`

| Campo | Tipo | Regra |
|---|---|---|
| `job_id` | texto PK | uuid |
| `profile_id` | texto FK → `career_profiles` | índice |
| `order_id` | texto | id da ordem em `career/orders.json` |
| `attempt_id` | texto | tentativa criada no aceite |
| `status` | texto | `accepted`, `paid`, `failed`, `engine_broken`, `abandoned` |
| `payout_brl`, `engine_cost_brl` | inteiro | copiados da ordem no aceite |
| `delta_balance_brl`, `delta_reputation` | inteiro | preenchidos na liquidação |
| `accepted_at`, `settled_at` | timestamp UTC | — |

## Campos novos em contratos (sem tabela)

| Modelo | Campo | Tipo | Padrão |
|---|---|---|---|
| `SessionCreateRequest` / `SimulationSession` | `upgrades` | `UpgradePackage` | todas as categorias `stock` |
| `SessionCreateRequest` / `SimulationSession` | `ethanol_pct` | float 27–100 ou null | null (combustível do `fuel_id`) |
| `PhysicsConfig` | `exhaust_backpressure_scale` | float 0,3–1,0 | 1,0 |
| `PhysicsConfig` | `fuel_pump_capacity_scale` | float 1,0–3,0 | 1,0 |
| `SensorReadings` | `ethanol_pct` | float ou null | null |
| `StrategyKind` | `vvt` | enum | — |
| `TableKind` | `flex_ign_add`, `flex_boost_add` | enum | — |
| `AxisQuantity` | `ethanol_pct` | enum | — |
| `DefectKind` | `boost_leak` (`leak_area_mm2`) | enum | — |
| `FuelId` | `flex` | literal | — |

## Dados de seed

- `scenarios/builtin/`: 4 JSONs novos (`defect-*`).
- `career/orders.json`: ordens de serviço fixas.
- Nenhuma alteração nos JSONs do catálogo de veículos.
