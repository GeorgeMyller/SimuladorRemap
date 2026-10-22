# Interface: sessões com upgrades e flex

## GET /api/v1/upgrades
Resposta 200: `{"categories":[{"category":"turbo","options":[{"part_id":"stock","label":"Série"},{"part_id":"upgraded","label":"Turbina upgraded","effects":{...}}]}, ...]}`. Categorias: `turbo`, `injectors`, `fuel_pump`, `intercooler`, `downpipe`, `internals`.

## POST /api/v1/sessions (campos novos, opcionais)
```json
{"vehicle_id":"hatch-20t-gdi","upgrades":{"turbo":"upgraded","injectors":"high_flow","fuel_pump":"high_flow","intercooler":"sport","downpipe":"high_flow","internals":"forged"},"ethanol_pct":85}
```
- `ethanol_pct` (27–100) implica `fuel_id = "flex"`; o veículo precisa permitir `e27` e `e100`, senão 409 `FUEL_NOT_ALLOWED` (código já registrado com 409 no catálogo de erros).
- Peça incompatível → 422 `UPGRADE_NOT_COMPATIBLE` com `category` e `part_id`.
- A resposta `SimulationSession` ecoa `upgrades` e `ethanol_pct`.
- Timeout e idempotência inalterados.
