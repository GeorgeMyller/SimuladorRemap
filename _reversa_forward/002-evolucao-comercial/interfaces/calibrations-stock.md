# Interface: imutabilidade de calibrações stock

- Rotas afetadas: `PUT /api/v1/calibrations/{calibration_id}` (replace e revert) e `PATCH /api/v1/calibrations/{calibration_id}/tables/{table_id}`.
- Regra: `calibration_id` iniciado por `stock-` → **409** `application/problem+json` com `code = "CALIBRATION_STOCK_IMMUTABLE"`, `detail` "Calibrações de fábrica são somente leitura; clone antes de editar.", campo extra `calibration_id`.
- Leitura (`GET`), clone e `reference` continuam permitidos.
- Idempotência: a recusa não cria versão.
- `POST /api/v1/sessions` sem `calibration_id`: a resposta traz `calibration_id` de um clone do usuário (não mais `stock-*`).
