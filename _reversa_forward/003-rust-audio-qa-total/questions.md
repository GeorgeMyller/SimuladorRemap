# Questions: 003-rust-audio-qa-total

| # | Dúvida | Premissa adotada | Como reverter |
|---|--------|------------------|---------------|
| Q1 | Docker compila a extensão Rust? | O Dockerfile ganha um estágio de build com Rust que compila o wheel ABI3 e o instala; se o estágio falhar, a imagem continua válida com o fallback Python. | Remover o estágio; o fallback garante o funcionamento |
| Q2 | Paridade bit a bit ou tolerância? | Tolerância relativa 1e-9 por grandeza por tick nos testes de paridade; o determinismo por seed (mesmo modo nativo/Python) é bit a bit; o digest de referência por arquitetura pode ser regravado com `SIMREMAP_WRITE_DIGESTS=1`. | Exigir bit a bit reescrevendo a ordem das operações |
