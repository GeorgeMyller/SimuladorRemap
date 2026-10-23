# Apresentação Animada — SimuladorRemap

Apresentação técnica animada e interativa criada com o **Mira Animator** (`mira-animator`), explicando a arquitetura, física de motor a 1000 Hz, dinamômetro virtual e calibração por IA com LAYA.ai.

## Como Abrir e Apresentar

O deck é totalmente autocontido e offline. Todas as dependências (Tailwind, Lucide, D3.js, GSAP, AOS) estão embutidas na pasta `assets/vendor/`.

### 1. Acesso Direto (Navegador / `file://`)

Basta abrir o arquivo no seu navegador (Google Chrome, Edge, Safari ou Firefox):

```bash
open apresentacao/decks/simulador-remap-overview/index.html
```

Ou no Windows:
```cmd
start apresentacao\decks\simulador-remap-overview\index.html
```

---

## Controles de Apresentação e Vídeo

| Tecla / Ação | Função |
|---|---|
| `↓` / `→` / `PageDown` | Avança para o próximo card/slide |
| `↑` / `←` / `PageUp` | Retorna ao card/slide anterior |
| `Home` / `End` | Vai diretamente para a Capa / Encerramento |
| `F` | Alterna modo tela cheia (*Fullscreen*) |
| `C` | Ativa o modo Câmera / Cinema (`mira-cinema.js`) |
| `A` | Ajusta o ritmo / animação contínua |
| `E` | Modo de Edição visual e reorganização de slides |
| `P` | Modo Caneta / Desenho sobre o slide (`mira-draw.js`) |

---

## Conteúdo dos Slides

1. **Capa / Abertura**: Apresentação visual com partículas dinâmicas de fluxo térmico.
2. **A Metáfora Central**: A bancada digital segura vs. o risco de quebra no dinamômetro físico.
3. **Hub Orbital**: Visualização em D3.js do núcleo físico 0D/1D e módulos gravitacionais.
4. **Bancada Virtual (Dinamômetro)**: Curvas em tempo real de potência e torque comparando OEM vs Remap LAYA.
5. **Tunagem com IA (LAYA.ai)**: Os 3 modos (`Safe`, `Balanced`, `Race`), pipeline Hone (MLX) e Sintetica (`@sandeco/itsfine`).
6. **O Coração da Inferência**: Clusterização de células operacionais e controle de threads no PyTorch.
7. **Benchmarks & Qualidade**: Métricas do motor físico (1000 Hz), tempo de resposta (35 ms) e testes automatizados.
8. **Execução & Próximos Passos**: Comandos rápidos para subir a aplicação e inspecionar logs de telemetria.
