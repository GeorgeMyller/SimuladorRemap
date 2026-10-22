# Interface: carreira (`/api/v1/career`)

| Método | Caminho | Corpo | Resposta |
|---|---|---|---|
| GET | `/career/profiles/{profile_id}` | — | 200 perfil (cria com saldo inicial se não existir) |
| GET | `/career/orders` | — | 200 lista de ordens (`order_id`, `title`, `client`, `briefing`, `scenario_id`, `payout_brl`, `engine_cost_brl`, `min_reputation`) |
| POST | `/career/profiles/{profile_id}/jobs` | `{"order_id":"..."}` | 201 job com `attempt_id` e `session_id`; 409 `CAREER_REPUTATION_TOO_LOW`; 409 `CAREER_JOB_ALREADY_OPEN` |
| POST | `/career/jobs/{job_id}/settle` | — | 200 job liquidado; 409 `CAREER_ATTEMPT_NOT_FINISHED` |
| GET | `/career/profiles/{profile_id}/jobs` | — | 200 histórico |

Erros em `application/problem+json`. A liquidação é idempotente (segunda chamada devolve o mesmo job).
