# Questions: 002-evolucao-comercial

> Modo autônomo "não parar": cada `[DÚVIDA]` do `requirements.md` virou premissa explícita no `roadmap.md#4. Premissas`. Revise e responda; uma resposta diferente da premissa pede `/reversa-add` ou nova feature.

| # | Dúvida | Premissa adotada | Onde impacta | Como reverter |
|---|--------|------------------|--------------|---------------|
| Q1 | Onde persistir o estado do modo carreira? | No banco do backend da estação (tabelas `career_profiles` e `career_jobs`, migração `0008`), ligado ao nickname do perfil local. Sem PII. | `backend/src/simremap/career/`, `db/migrations/versions/0008_*` | Trocar por armazenamento no navegador exige remover o pacote `career` e a migração |
| Q2 | O teor de etanol muda com a sessão em andamento? | Não. O teor é escolhido na criação da sessão (`ethanol_pct`) e fica fixo; o sensor flex da ECU lê esse valor (com ruído). Reabastecimento fica para feature futura. | `dyno/contracts.py`, `physics/fuel_blend.py` | Adicionar endpoint de reabastecimento com motor parado (`PhysicsEngine.set_fuel`) |
| Q3 | E se o núcleo da biblioteca 3D sozinho passar de 500 kB? | Divide-se o código em chunks de fornecedor e importações nomeadas para tree-shaking. Se ainda assim o núcleo 3D passar de 500 kB, ele fica isolado num chunk carregado só ao abrir a vista 3D, e a exceção é registrada no relatório (sem esconder o aviso subindo o limite). | `frontend/vite.config.ts`, `Table3DSurface.tsx` | Trocar a superfície por renderização própria em WebGL puro |
