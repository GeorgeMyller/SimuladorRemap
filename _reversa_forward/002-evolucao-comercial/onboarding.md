# Onboarding: testar a feature 002

1. Suba o ambiente: `make dev` (backend em 8000, Vite em 5173) ou `docker compose up`.
2. **Blindagem:** abra Cenários e inicie `stage1-oem`. A tentativa deve abrir sem 422. Rode `curl -X PUT localhost:8000/api/v1/calibrations/stock-hatch-20t-gdi-oem-stage -H 'content-type: application/json' -d '{}'` e confirme 409 `CALIBRATION_STOCK_IMMUTABLE`.
3. **Oficina:** na tela inicial escolha o hatch, abra "Oficina de upgrades", marque turbina upgraded, bicos high-flow, intercooler, downpipe e forjados. Ajuste o etanol para 85 %. Crie a sessão.
4. **Live Tuning:** na bancada clique em "Tela Dividida (Live Tuning)". Segure Espaço para acelerar e solte para dar um blip. Veja a célula da VE piscar. Selecione células e tecle `Q`; use `H`, `V` e `B` numa seleção.
5. **Imersão:** ligue "Visão Térmica / Raio-X" e faça uma puxada; o coletor muda de vermelho para amarelo com a EGT. Compare o som dos 4 carros.
6. **Defeitos:** em Cenários inicie `defect-lean-injector` e use a EGT por cilindro para diagnosticar.
7. **Carreira:** abra "Oficina (Carreira)", aceite uma ordem, entregue o carro e liquide a ordem.
8. **Build:** `npm --prefix frontend run build` e confira que nenhum chunk passa de 500 kB.
