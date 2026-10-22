# Especificação de Evolução da UI: Responsividade, Controles e Carros Pixel Art

> **Status:** Pronto para Implementação pelo Claude  
> **Origem:** Validação física concluída com sucesso (Medição de potência, remap e quebras catastróficas validadas).  
> **Objetivo:** Refinar a experiência da interface com responsividade total, correção da rolagem por setas direcionais e artes em Pixel Art dos 4 carros.

---

## 1. Relatório de Validação dos Ajustes e Quebras (Backend)

Todos os testes de bancada física foram executados e validados contra a API ativa (`http://127.0.0.1:8000/api/v1`):

1. **Puxada Base (OEM / Série):**
   - Veículo: Hatch 2.0 Turbo GDI.
   - Potência de roda aferida: **214.6 whp**.
   - Torque no motor: **347.4 N·m**.
   - Integridade mecânica: 100% intacto.

2. **Remap Moderado (Stage 1 - Aumento de Pressão e Avanço):**
   - Ajustes na calibração: +25 kPa no alvo de pressão do coletor, +2.0° no mapa de avanço básico (`ignition_base`).
   - Potência de roda aferida: **224.1 whp** (+9.4 whp de ganho real medido).
   - Torque no motor: **360.6 N·m** (+13.2 N·m de ganho real).
   - O simulador comprova que alterações na calibração alteram dinamicamente a física e a curva de potência/torque.

3. **Remap Extremo & Modelo de Danos (Overboost e Sobrecarga):**
   - Ajustes na calibração: Limite de torque liberado (750 N·m), alvo de pressão de 380 kPa e avanço agressivo (+10°).
   - Resultado: **Falha Catastrófica** (`catastrophic_failure`, estado `engine_failed`).
   - Componente rompido: `turbo:turbine`.
   - Mecanismo de falha: `turbo_overspeed_burst` (rotação do turbo atingiu 112% do limite com MAP a 380.7 kPa e EGT a 949.8 °C).
   - Bloqueio do motor: O motor travou (`engine_locked: true`). Novas puxadas foram recusadas com código 409 `ENGINE_DESTROYED`.
   - Restauração: Endpoint `POST /api/v1/sessions/{sid}/engine/restore` restaura com sucesso a integridade física do motor.

---

## 2. Tarefa 1: Correção dos Controles por Teclado (Setas Direcionais)

### O Problema Atual:
- No navegador, quando o usuário pressiona as setas (`ArrowUp`, `ArrowDown`, `ArrowLeft`, `ArrowRight`), o comportamento padrão do navegador é rolar a página verticalmente ou horizontalmente.
- No cockpit do dinamômetro (`DynoCockpitPage.tsx` / `RunControls.tsx`), as setas deveriam controlar a borboleta (aceleração/throttle). Porém, como o controle de foco nem sempre está no slider ou o evento de tecla propaga para a janela, a tela rola para cima/baixo em vez de acelerar com precisão.
- Na tabela da ECU (`TableGrid.tsx`), as setas navegam entre células, mas se o foco escapar, a página rola.

### Solução a Implementar:
1. Em `frontend/src/features/dyno-cockpit/DynoCockpitPage.tsx` e `RunControls.tsx`:
   - Adicionar listener de teclado que intercepta `ArrowUp` e `ArrowDown` para incrementar/decrementar o throttle durante a puxada ativa ou bancada.
   - Invocar `e.preventDefault()` explicitamente sempre que a tecla for capturada para acelerador ou navegação de abas.
   - Adicionar trava para não rolar a janela (`overflow: hidden` ou restrição de scroll no container principal do cockpit).
2. Em `frontend/src/features/ecu-tuning/TableGrid.tsx`:
   - Garantir que `onKeyDown` capture `ArrowUp`, `ArrowDown`, `ArrowLeft`, `ArrowRight` com `e.preventDefault()` de forma incondicional dentro da grade de células.

---

## 3. Tarefa 2: Interface Responsiva (Mobile / Tablet / Desktop)

### Áreas a Adaptar:
1. **Tela Inicial (`HomePage.tsx`):**
   - O grid de seleção de veículos deve ser `grid-cols-1 sm:grid-cols-2 lg:grid-cols-4` para exibir os cards dos 4 carros de forma equilibrada.
   - Dropdowns de perfil de ECU e cenário devem se alinhar em coluna única em telas pequenas e duas colunas em telas médias/grandes.
   - Mensagens de alerta e erro (como `SIM_CAPACITY_EXCEEDED`) devem conter botões de ação para recuperar a sessão ou encerrá-la.

2. **Cockpit do Dinamômetro (`DynoCockpitPage.tsx`):**
   - Em telas pequenas (< 1024px), o layout atualmente quebra colunas fixas.
   - Reorganizar com layout flex/grid responsivo:
     - Topo: Tacômetro/Manômetros principais compactos.
     - Centro: Gráfico de curva de potência e animação do rolo.
     - Lateral/Inferior: Painel de controles da puxada e abas inferiores colapsáveis.

3. **Workspace da ECU (`EcuWorkspace.tsx`):**
   - Em telas menores, a visualização 3D e a tabela 2D devem alternar em abas em vez de tentar dividir espaço fixo.
   - A tabela deve ter scroll horizontal com cabeçalhos fixos (sticky header).

---

## 4. Tarefa 3: Ilustrações dos Carros em Pixel Art

### Conceito Visual:
Estilo Pixel Art retro-moderno (16-bit / 32-bit), com silhueta lateral bem definida, sombras nítidas, detalhes de rodas, spoiler, intercooler ou intake visível.
Formato recomendado: Componentes SVG ou canvas/imagens limpas com renderização `pixelated` (`image-rendering: pixelated`).

### As 4 Categorias de Carros:

1. **Hatch 2.0 Turbo GDI (`hatch-20t-gdi`)**:
   - Estilo: Hot Hatch moderno estilo Golf GTI / Civic Type R / Megane RS.
   - Características: Silhueta hatchback compacta, aerofólio traseiro de teto, grade frontal com intercooler aparente, pinças de freio coloridas, linha de cintura esportiva.
   - Cores sugeridas: Cinza Nardo ou Vermelho vibrante.

2. **Coupé 3.0 Turbo 6 em Linha (`coupe-30t-i6`)**:
   - Estilo: Coupé esportivo premium de tração traseira estilo BMW M2/M4 ou Supra Mk5.
   - Características: Capô longo para acomodar o 6 cilindros em linha, teto com caimento fastback baixo, difusor traseiro duplo escape, postura agressiva e baixa.
   - Cores sugeridas: Azul elétrico / metálico ou Branco com detalhes pretos.

3. **Clássico 2.0 Turbo de Swap (`classic-20t-swap`)**:
   - Estilo: Carro clássico quadrado dos anos 80/90 estilo Gol Quadrado / Chevette / Sierra Cosworth.
   - Características: Linhas retas e angulares, faróis retangulares, rodas clássicas tipo BBS/Pingo d'Água, turbocompressor saindo na frente ou escape direto, aspecto de projeto forjado de arrancada.
   - Cores sugeridas: Preto fosco / Cinza chumbo ou Prata clássico.

4. **Muscle V8 5.0 Sobrealimentado (`muscle-v8-sc`)**:
   - Estilo: Muscle Car americano estilo Mustang Shelby / Dodge Challenger Hellcat.
   - Características: Carroçaria robusta e larga (widebody), capô com entrada de ar proeminente / blower do supercharger aparente, rodas traseiras mais largas com pneus de alta tração.
   - Cores sugeridas: Amarelo com faixas pretas ou Laranja queimado.

### Onde Integrar os Carros Pixel Art:
- **`HomePage.tsx`:** No card de seleção de veículo, substituir os textos secos por uma prévia gráfica com a ilustração Pixel Art do carro no topo do card.
- **`DynoCockpitPage.tsx`:** Exibir o carro em pixel art montado sobre os rolos dinamométricos com animação sutil de vibração e rotação das rodas durante a aceleração.

---

## 5. Status de Implementação (2026-10-18)

- **Teclado:** `RunControls` ganhou `arrowKeys` (listener global: ↑/↓ mexem na borboleta em "Patamar"; todas as setas fora de campos têm `preventDefault`; desligado com diálogos abertos). `TableGrid` faz `preventDefault` incondicional nas setas; `TableEditorCore` devolve o foco à grade quando a seta vem de um botão do editor. Trava de rolagem feita por `preventDefault` (sem `overflow: hidden`, para não bloquear o scroll por toque no mobile).
- **Responsivo:** HomePage `grid-cols-1 sm:grid-cols-2 lg:grid-cols-4`, selects `md:grid-cols-2`, erro de criação com "Retomar sessão ativa" / "Encerrar sessão ativa" (`DELETE /sessions/{id}`). Cockpit em coluna única abaixo de `lg` (instrumentos → carro → gráficos → puxada → abas); bloqueio "Resolução não suportada (< 1366 px)" e a subscrição reduzida foram removidos. ECU: grade 1/2/3 colunas (`lg`/`xl`) e abas "Tabela | Vista 3D" abaixo de `lg`.
- **Pixel art:** `frontend/src/features/pixel-cars/` (`sprites.ts` rasteriza os 4 carros; `PixelArtCar.tsx` em SVG `crispEdges`). Integrado nos cards da HomePage e no canvas de `CarOnRollerView` (rodas giram com o rolo, vibração, carroçaria queimada após falha).
- **Verificação:** tsc, eslint e vitest (461 testes) verdes; capturas Playwright em 390 px e 1440 px.
