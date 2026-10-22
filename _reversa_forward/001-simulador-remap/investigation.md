# Investigation: Simulador Completo de Remap Automotivo em Dinamômetro

> Identificador: `001-simulador-remap`
> Data: `2026-10-18`
> Roadmap: `_reversa_forward/001-simulador-remap/roadmap.md`
> Confidência: 🟢 CONFIRMADO, 🟡 INFERIDO, 🔴 LACUNA

🟡 Este documento reúne a pesquisa de fundo das decisões do `roadmap.md`. Cada tema traz o padrão escolhido, as alternativas avaliadas e as referências abertas.
🟡 As referências são citadas por autor, título, ano ou norma. Só há URL para domínios canônicos (`rfc-editor.org`, `docs.python.org`, `sae.org`).
🟡 Nenhum número novo é criado aqui: os coeficientes vêm das specs SDD citadas.

## Sumário

1. Modelagem 0D/1D do motor
2. Combustão: função de Wiebe
3. Transferência de calor: Woschni
4. Atrito: Chen-Flynn
5. Coletores: filling & emptying
6. Knock: Livengood-Wu e Douaud-Eyzat
7. Dano térmico: Larson-Miller (e dano mecânico)
8. Correção de potência: SAE J1349 e DIN 70020
9. Decimação e backpressure de telemetria
10. Determinismo em Python/NumPy
11. Síntese de som do motor com Web Audio
12. WebGL sem GPU dedicada
13. JCS (RFC 8785) para hash de pacotes
14. SQLite vs PostgreSQL
15. Modo do worker: processo vs thread
16. Lacunas de pesquisa

---

## 1. Modelagem 0D/1D do motor

**Problema.** 🟡 O simulador precisa de MBT emergente, pressão no cilindro para o knock, EGT coerente com avanço e lambda, e custo ≤ 0,5 ms por tick a 1000 Hz (`engine-physics-core` RNF-01).

**Padrão escolhido.** 🟡 Modelo híbrido: coletores e turbo em 0D de valor médio (filling & emptying) e ciclo fechado de zona única resolvido por evento de combustão a 1° de cambota (Heun, IVC → EVO). O torque do tick é a média móvel de `n_cyl` eventos. As entradas do solver de ciclo são quantizadas e passam por cache LRU (`engine-physics-core` seção 15).

**Alternativas avaliadas.**

| Alternativa | Vantagem | Motivo da recusa |
|---|---|---|
| Modelo de valor médio puro (MVEM) | Muito barato; padrão em controle | 🟡 Não gera pressão no cilindro nem temperatura da zona não queimada; sem isso o knock e o MBT não emergem. |
| Integração angular contínua dentro de cada tick | Fiel ao ciclo | 🟡 A 7500 rpm no V8 custa demais por tick; acopla o ciclo ao passo do laço. |
| Modelo 1D de ondas (gas dynamics) | Captura sintonia de coletores | 🟡 Custo incompatível com 1000 Hz em Python; fora do escopo (`engine-physics-core` NG-01). |
| Modelo de duas zonas | Melhor estimativa de T_u e NOx | 🟡 Ganho pequeno para o objetivo didático; a T_u da zona única com compressão politrópica basta para Livengood-Wu. |

**Referências.**
- Heywood, J. B. *Internal Combustion Engine Fundamentals*. McGraw-Hill, 1988 (2.ª ed., 2018).
- Guzzella, L.; Onder, C. H. *Introduction to Modeling and Control of Internal Combustion Engine Systems*. Springer, 2.ª ed., 2010.
- Eriksson, L.; Nielsen, L. *Modeling and Control of Engines and Drivelines*. Wiley, 2014.
- Hendricks, E.; Sorenson, S. C. "Mean Value Modelling of Spark Ignition Engines". SAE Technical Paper 900616, 1990.

## 2. Combustão: função de Wiebe

**Padrão escolhido.** 🟡 `x_b(θ) = 1 − exp(−a · ((θ − θ0)/Δθ)^(m+1))` com `a = 5` e `m = 2`. A duração Δθ depende de rpm, velocidade laminar (Metghalchi-Keck) e fração residual; o atraso de inflamação depende de rpm (`engine-physics-core` Apêndice A.4).

**Alternativas avaliadas.**
- 🟡 Wiebe dupla (pré-mistura + difusão): útil em diesel; desnecessária em ciclo Otto.
- 🟡 Modelo de chama turbulenta (entrainment, Blizard-Keck / Tabaczynski): mais físico, mas exige geometria da câmara e mais parâmetros sem fonte aberta para os 4 veículos.
- 🟡 Taxa de calor tabelada por ponto de operação: exige dados medidos que o projeto não tem.

**Referências.**
- Vibe (Wiebe), I. I. *Brennverlauf und Kreisprozess von Verbrennungsmotoren*. VEB Verlag Technik, 1970.
- Metghalchi, M.; Keck, J. C. "Burning velocities of mixtures of air with methanol, isooctane, and indolene at high pressure and temperature". *Combustion and Flame* 48, 1982.
- Heywood (1988), capítulos 9 e 14.

🔴 Lacuna: os coeficientes de velocidade laminar de E100 e de Podium são inferidos e precisam de fonte aberta (`engine-physics-core` OQ-05).

## 3. Transferência de calor: Woschni

**Padrão escolhido.** 🟡 `h = 3,26 · B^(−0,2) · p^0,8 · T^(−0,55) · w^0,8`, com velocidade característica de duas parcelas (pistão e combustão) e `T_wall = ECT + 80 K` (`engine-physics-core` Apêndice A.5).

**Alternativas avaliadas.**
- 🟡 Hohenberg (1979): melhor para câmaras pequenas, mas menos citado para SI e com mais calibração.
- 🟡 Annand (1963): inclui radiação; relevante em diesel.
- 🟡 Coeficiente constante: barato, mas distorce a EGT e o MBT quando a carga muda.

**Referências.**
- Woschni, G. "A Universally Applicable Equation for the Instantaneous Heat Transfer Coefficient in the Internal Combustion Engine". SAE Technical Paper 670931, 1967.
- Hohenberg, G. F. "Advanced Approaches for Heat Transfer Calculations". SAE Technical Paper 790825, 1979.
- Annand, W. J. D. "Heat Transfer in the Cylinders of Reciprocating Internal Combustion Engines". *Proc. IMechE* 177, 1963.

## 4. Atrito: Chen-Flynn

**Padrão escolhido.** 🟡 `FMEP = C + A · p_max + B · S̄p + Q · S̄p²`, com coeficientes padrão inferidos e sobreposição por veículo no catálogo (`engine-physics-core` Apêndice A.6).

**Alternativas avaliadas.**
- 🟡 Patton-Nitschke-Heywood (1989): decomposição por componente (anéis, mancais, trem de válvulas); exige dados de projeto mecânico que não existem para veículos genéricos.
- 🟡 FMEP tabelado por rpm: simples, mas ignora a dependência da carga (p_max).

**Referências.**
- Chen, S. K.; Flynn, P. F. "Development of a Single Cylinder Compression Ignition Research Engine". SAE Technical Paper 650733, 1965.
- Patton, K. J.; Nitschke, R. G.; Heywood, J. B. "Development and Evaluation of a Friction Model for Spark-Ignition Engines". SAE Technical Paper 890836, 1989.

## 5. Coletores: filling & emptying

**Padrão escolhido.** 🟡 Coletores de admissão, boost e escape como volumes 0D com balanço de massa; borboleta como orifício compressível com escoamento bloqueado; turbo por equilíbrio de potência no eixo e mapas simplificados; supercharger por deslocamento positivo (`engine-physics-core` Apêndices A.2, A.8, A.9).

**Alternativas avaliadas.**
- 🟡 Modelo 1D de ondas: ver tema 1.
- 🟡 Mapas de compressor reais tabelados: mais fiéis, mas sem fonte aberta por veículo; o catálogo aceita mapa tabelado opcional.

**Referências.**
- Guzzella e Onder (2010), capítulo 2 (modelos de enchimento e esvaziamento).
- Eriksson e Nielsen (2014), capítulos 7 e 8 (coletores e turbo).
- Watson, N.; Janota, M. S. *Turbocharging the Internal Combustion Engine*. Macmillan, 1982.
- Aquino, C. F. "Transient A/F Control Characteristics of the 5 Liter Central Fuel Injection Engine". SAE Technical Paper 810494, 1981 (filme de combustível tau-X).

## 6. Knock: Livengood-Wu e Douaud-Eyzat

**Padrão escolhido.** 🟡 Integral de Livengood-Wu `∫ dt/τ ≥ 1` sobre a zona não queimada, desde a faísca até ao fim da combustão, com atraso de autoignição de Douaud-Eyzat `τ = 17,68 · (ON/100)^3,402 · p^(−1,7) · exp(3800/T)` (ms, p em atm, T em K). A intensidade é MAPO (bar) proporcional à fração não queimada no instante da autoignição. A física converte a intensidade em `knock_sensor_v` e `knock_intensity` (`knock-and-failure-model` seção 15; `engine-physics-core` A.10).

**Alternativas avaliadas.**

| Alternativa | Motivo da recusa |
|---|---|
| 🟡 Cinética química detalhada ou reduzida (mecanismos PRF) | Custo proibitivo a 1000 Hz; exige solver rígido. |
| 🟡 Correlações de atraso alternativas (por exemplo, a de Hoepke et al. para combustíveis com etanol) | Promissoras para E100, mas exigem validação; ficam como evolução se o OQ-03 do dano mostrar desvio. |
| 🟡 Limiar fixo de avanço por rpm/carga | Não reage a octanagem, IAT nem boost; contraria o objetivo didático. |
| 🟡 Modelo acústico do sensor | Desnecessário: o espectro é sintético por modos de Draper (`telemetry-datalogger` seção 15). |

**Referências.**
- Livengood, J. C.; Wu, P. C. "Correlation of Autoignition Phenomena in Internal Combustion Engines and Rapid Compression Machines". *Fifth Symposium (International) on Combustion*, 1955.
- Douaud, A. M.; Eyzat, P. "Four-Octane-Number Method for Predicting the Anti-Knock Behavior of Fuels and Engines". SAE Technical Paper 780080, 1978.
- Draper, C. S. "Pressure Waves Accompanying Detonation in the Internal Combustion Engine". *Journal of the Aeronautical Sciences* 5, 1938.
- Heywood (1988), seção 9.6 (knock em motores SI).

🔴 Lacuna: `ON = (RON + MON)/2` com etanol (`knock-and-failure-model` OQ-03) e limiares de ponto quente para pré-ignição (OQ-02) precisam de calibração conjunta no Sprint 2.

## 7. Dano térmico: Larson-Miller (e dano mecânico)

**Padrão escolhido.** 🟡 Dano térmico zero abaixo do limite de temperatura do componente; acima dele, consumo de vida por parâmetro de Larson-Miller `LMP = T · (C + log10 t_r)`, acumulado de forma linear. Dano mecânico por limite de carga sem dispersão: a `seed` só decide os pesos de qual biela quebra (`knock-and-failure-model` seção 15).

**Alternativas avaliadas.**
- 🟡 Larson-Miller contínuo (dano também abaixo do limite): realista para fluência, mas impede "integridade 100 %" com acerto correto.
- 🟡 Regra de Palmgren-Miner com curvas S-N (Basquin) para fadiga: útil em vida longa; o MVP pune eventos de curta duração.
- 🟡 Resistência sorteada por componente: tira a previsibilidade didática ("410 N·m nunca quebra, 430 N·m sempre quebra").

**Referências.**
- Larson, F. R.; Miller, J. "A Time-Temperature Relationship for Rupture and Creep Stresses". *Transactions of the ASME* 74, 1952.
- Miner, M. A. "Cumulative Damage in Fatigue". *Journal of Applied Mechanics* 12, 1945.
- Heywood (1988), capítulo 12 (temperaturas de componentes).

## 8. Correção de potência: SAE J1349 e DIN 70020

**Padrão escolhido.** 🟡 Fator de correção constante por puxada, calculado das condições do ar ambiente da célula (`AmbientConditions`). SAE J1349 é o padrão; DIN 70020 é opcional; `none` desliga a correção (`dyno-bench` seção 15). O resumo indica `correction_out_of_range` quando o fator sai da faixa da norma.

**Alternativas avaliadas.**
- 🟡 Correção por ponto com IAT pós-intercooler: contraria a definição das normas, que usam o ar de entrada da célula.
- 🟡 ISO 1585 e EEC 80/1269: equivalentes à J1349 em muitas condições; não foram pedidas pelo PRD.
- 🟡 Sem correção: torna puxadas em ambientes diferentes incomparáveis.

**Referências.**
- SAE J1349. *Engine Power Test Code — Spark Ignition and Compression Ignition — As Installed Net Power Rating*. SAE International (revisão de 2011). Catálogo da norma em `https://www.sae.org/`.
- DIN 70020. *Kraftfahrzeugbau; Allgemeines* (definições de potência e condições de referência). Deutsches Institut für Normung.
- ISO 1585. *Road vehicles — Engine test code — Net power*. ISO.

## 9. Decimação e backpressure de telemetria

**Padrão escolhido.** 🟡 Decimação no worker por fronteira `frame_index(k) = floor(k · fps / sim_hz)`, com agregação por canal: `max` para knock, EGT, pressão de pico, retardo e duty; `min` para saúde; `any` para flags. Backpressure por conexão: fila de frames de 8 itens com descarte do mais antigo e fila de eventos de 256 itens que descarta primeiro `event.knock`; `run.state` e `event.failure` nunca são descartados (`telemetry-datalogger` RF-05, RF-08, RF-09). Na saída do worker, o roadmap separa uma faixa crítica sem descarte (D-05).

**Alternativas avaliadas.**

| Alternativa | Motivo da recusa |
|---|---|
| 🟡 Enviar cada tick ao event loop e decimar lá | 1000 itens/s pela fila entre processos; custo de serialização alto. |
| 🟡 Último valor por janela (sample-and-hold) | Um pico de knock de 1 tick desaparece. |
| 🟡 LTTB (Largest-Triangle-Three-Buckets) | Ótimo para gráficos estáticos, mas não é causal nem barato por janela ao vivo; útil no futuro para a vista de histórico. |
| 🟡 Fila sem limite | Memória cresce sem teto com cliente parado. |
| 🟡 Bloquear o produtor | Quebra o tempo real do laço. |

**Referências.**
- Fette, I.; Melnikov, A. *The WebSocket Protocol*. RFC 6455, 2011. `https://www.rfc-editor.org/rfc/rfc6455`.
- Steinarsson, S. *Downsampling Time Series for Visual Representation*. Dissertação de mestrado, Universidade da Islândia, 2013 (LTTB).
- Documentação Python, `asyncio.Queue` e `queue.Queue`: `https://docs.python.org/3/library/asyncio-queue.html`, `https://docs.python.org/3/library/queue.html`.

## 10. Determinismo em Python/NumPy

**Padrão escolhido.** 🟡
- Tempo só por contagem de ticks; o relógio de parede só cadencia o tempo real.
- `numpy.random.Generator(PCG64)` com `SeedSequence.spawn` por canal, em ordem fixa.
- Proibição de `time.*` e `random` nos pacotes do laço, imposta por lint e por teste.
- BLAS/OpenMP em 1 thread no worker (variáveis `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`).
- Hashes sobre representações canônicas: floats a 6 casas nos JSON internos e bytes `float32` no datalog.
- Somatórios em ordem fixa; nada de iteração sobre `set` no laço.
- Garantia só na mesma imagem e arquitetura (D-08).

**Alternativas avaliadas.**
- 🟡 Aritmética de ponto fixo ou `decimal`: determinismo entre plataformas, mas custo proibitivo.
- 🟡 `random` da biblioteca padrão com semente global: um consumidor novo muda todos os streams.
- 🟡 Arredondamento agressivo antes de cada passo: mascara erros e degrada a física.

**Referências.**
- IEEE 754-2019. *IEEE Standard for Floating-Point Arithmetic*. IEEE, 2019.
- O'Neill, M. E. "PCG: A Family of Simple Fast Space-Efficient Statistically Good Algorithms for Random Number Generation". Relatório técnico HMC-CS-2014-0905, Harvey Mudd College, 2014.
- Documentação NumPy, *Random Generator* e *SeedSequence* (seção "Parallel random number generation").
- Documentação Python, `time.perf_counter`, `math.fsum` e `PYTHONHASHSEED`: `https://docs.python.org/3/library/time.html`, `https://docs.python.org/3/library/math.html`, `https://docs.python.org/3/using/cmdline.html`.
- Goldberg, D. "What Every Computer Scientist Should Know About Floating-Point Arithmetic". *ACM Computing Surveys* 23(1), 1991.

## 11. Síntese de som do motor com Web Audio

**Padrão escolhido.** 🟡 Síntese procedural em `AudioEngine.ts`: fundamental de ignição `f = rpm/60 · n_cyl/2` (200 Hz com 4 cilindros a 6000 rpm), harmônicos por ordem de ignição, ruído filtrado para admissão, assobio de turbo por `turbo_rpm`, blow-off, estalos de overrun e som de quebra. O `AudioContext` fica `suspended` até ao primeiro gesto (`dyno-cockpit-ui` RF-18, RF-19).

**Alternativas avaliadas.**
- 🟡 Amostras gravadas com crossfade por rpm: realistas, mas exigem licença e não cobrem 4 arquiteturas.
- 🟡 Síntese granular com amostras: mesma questão de licença.
- 🟡 `AudioWorklet` com síntese por amostra: mais controle, mas mais código; fica como evolução se os nós nativos não bastarem.

**Referências.**
- W3C. *Web Audio API*. W3C Recommendation, 2021.
- Farnell, A. *Designing Sound*. MIT Press, 2010 (síntese procedural de motores).
- Diretrizes de autoplay dos navegadores Chromium e Firefox (exigem gesto do usuário).

## 12. WebGL sem GPU dedicada

**Padrão escolhido.** 🟡 uPlot em Canvas 2D para todas as curvas; WebGL (1 ou 2) só no espectrograma, que desloca uma textura em vez de copiar `ImageData`, com fallback automático para Canvas 2D; three.js só no chunk lazy da superfície 3D do editor. O laço `requestAnimationFrame` é desacoplado do `onmessage` por buffer em anel (`dyno-cockpit-ui` seção 15; `ecu-tuning-ui` seção 15).

**Fundamento.** 🟡 Sem GPU dedicada, os navegadores usam GPU integrada ou rasterização por software (SwiftShader no Chromium, llvmpipe no Linux). Canvas 2D com poucos objetos e WebGL com uma textura cabem nesse orçamento; cenas 3D completas e SVG com milhares de nós não cabem.

**Alternativas avaliadas.**
- 🟡 Recharts e outros gráficos em SVG: custo de layout por frame impede 60 FPS.
- 🟡 Chart.js e ECharts: maiores e mais lentos que uPlot para séries densas.
- 🟡 three.js para a cockpit inteira: memória e risco de trade dress de modelos reais.
- 🟡 `OffscreenCanvas` em Web Worker: ganho possível; fica como otimização se a medição do Sprint 3 mostrar jank.

**Referências.**
- Khronos Group. *WebGL Specification* 1.0 e *WebGL 2.0 Specification*.
- WHATWG. *HTML Living Standard*, seções "The canvas element" e "Animation frames".
- Documentação do projeto uPlot (Leeoniya, licença MIT) e do three.js (licença MIT).

## 13. JCS (RFC 8785) para hash de pacotes

**Padrão escolhido.** 🟡 `sha256 = hex(SHA-256(JCS({"format_version": v, "kind": k, "payload": p})))`, com a biblioteca `rfc8785` (Apache-2.0). JCS ordena chaves por unidades UTF-16, serializa números no formato ECMAScript e remove espaços. `NaN` e `Infinity` tornam o pacote não canonicalizável (422 `PACKAGE_NOT_CANONICALIZABLE`). Os hashes internos (`content_hash`, `setup_hash`, `curve_sha256`) mantêm `json.dumps(sort_keys=True)` com floats a 6 casas (`training-scenarios` seção 15).

**Alternativas avaliadas.**

| Alternativa | Motivo da recusa |
|---|---|
| 🟡 `json.dumps(sort_keys=True, separators=(",", ":"))` | Depende da serialização de floats do Python; um script externo noutra linguagem pode divergir. |
| 🟡 HMAC-SHA256 com segredo do instrutor | Autentica autoria, mas exige distribuição de segredo; fica para `format_version = 2` (premissa da `[DÚVIDA]`). |
| 🟡 Assinatura Ed25519 | Igual ao HMAC, com gestão de chaves pública/privada. |
| 🟡 Hash do arquivo bruto | Muda com espaços e ordem de chaves; quebra o recálculo. |

**Referências.**
- Rundgren, A.; Jordan, B.; Erdtman, S. *JSON Canonicalization Scheme (JCS)*. RFC 8785, 2020. `https://www.rfc-editor.org/rfc/rfc8785`.
- NIST. *Secure Hash Standard (SHS)*. FIPS 180-4, 2015.
- Bray, T. (ed.). *The JavaScript Object Notation (JSON) Data Interchange Format*. RFC 8259, 2017. `https://www.rfc-editor.org/rfc/rfc8259`.
- Krawczyk, H.; Bellare, M.; Canetti, R. *HMAC: Keyed-Hashing for Message Authentication*. RFC 2104, 1997. `https://www.rfc-editor.org/rfc/rfc2104`.
- Josefsson, S.; Liusvaara, I. *Edwards-Curve Digital Signature Algorithm (EdDSA)*. RFC 8032, 2017. `https://www.rfc-editor.org/rfc/rfc8032`.
- Shafranovich, Y. *Common Format and MIME Type for Comma-Separated Values (CSV) Files*. RFC 4180, 2005. `https://www.rfc-editor.org/rfc/rfc4180` (CSV de notas e de log; o prefixo `'` contra injeção de fórmulas segue a recomendação OWASP "CSV Injection").

## 14. SQLite vs PostgreSQL

**Padrão escolhido.** 🟡 SQLite com WAL, `foreign_keys=ON` e `busy_timeout=5000` em `/data/simremap.db`; PostgreSQL 16 opcional por `DATABASE_URL`, testado em todas as migrações no Sprint 4 (D-09).

**Comparação.**

| Critério | SQLite | PostgreSQL 16 |
|---|---|---|
| Operação numa estação | 🟡 Zero administração; um arquivo no volume | 🟡 Serviço extra no compose, memória e healthcheck |
| Concorrência de escrita | 🟡 Um escritor por vez; WAL permite leitores concorrentes | 🟡 MVCC completo |
| Tamanho da imagem e RSS | 🟡 Embutido no Python | 🟡 Container adicional (≈ 100–150 MB de RAM em repouso) |
| Migrações Alembic | 🟡 Exige `render_as_batch=True` para `ALTER` | 🟡 Suporte direto |
| Cópia e rollback | 🟡 Copiar o arquivo | 🟡 `pg_dump` |

🟡 Conclusão: com 1 usuário e 1 sessão por container, o limite de um escritor do SQLite não pesa. O datalog grava no fim da puxada e os binários ficam em `/data/logs`, fora do banco.

**Referências.**
- Documentação SQLite: "Write-Ahead Logging", "PRAGMA foreign_keys", "Appropriate Uses For SQLite".
- Documentação PostgreSQL 16: "Concurrency Control (MVCC)".
- Documentação SQLAlchemy 2.0 (asyncio) e Alembic ("Running Batch Migrations for SQLite").
- Documentação Python, `sqlite3`: `https://docs.python.org/3/library/sqlite3.html`.

## 15. Modo do worker: processo vs thread

**Padrão escolhido.** 🟡 Processo dedicado por sessão (`spawn`) como padrão; fallback `thread` por benchmark até 2026-10-24 (D-04).

| Critério | `process` (`spawn`) | `thread` |
|---|---|---|
| Disputa pelo GIL com o I/O asyncio | 🟡 Nenhuma | 🟡 Alta; NumPy só solta o GIL em operações vetoriais longas, e o laço tem muitos arrays pequenos |
| Custo de comunicação | 🟡 Pickle por item nas `multiprocessing.Queue` | 🟡 Referência em memória |
| Isolamento de falhas | 🟡 Crash ou OOM ficam no processo filho | 🟡 Um crash derruba a API |
| Tempo de arranque da sessão | 🟡 Centenas de ms (import do NumPy no filho) | 🟡 Imediato |

**Alternativas avaliadas.**
- 🟡 Laço no event loop: viola o isolamento pedido pelo PRD.
- 🟡 Subinterpreters (PEP 734) e Python free-threaded (PEP 703, 3.13t): promissores, mas experimentais em 2026 para NumPy e para a imagem `python:3.12-slim`.
- 🟡 `forkserver`: arranque mais rápido que `spawn`, mas indisponível em todas as plataformas de dev; aceite como opção de configuração.

**Referências.**
- Documentação Python, `multiprocessing` (contextos e métodos de arranque): `https://docs.python.org/3/library/multiprocessing.html`.
- Documentação Python, `threading` e `asyncio` (`loop.run_in_executor`): `https://docs.python.org/3/library/asyncio-eventloop.html`.
- Gross, S. *PEP 703 — Making the Global Interpreter Lock Optional in CPython*, 2023.
- Snow, E. *PEP 734 — Multiple Interpreters in the Stdlib*, 2023.

## 16. Lacunas de pesquisa

- 🔴 Dados medidos de lambda e EGT para os 4 veículos: o benchmark v1 usa estimativas internas (`confidence = estimated`). Uma troca por medições gera o benchmark v2.
- 🔴 Velocidade laminar de E100 e Podium com fonte aberta confirmada (`engine-physics-core` OQ-05).
- 🔴 Octanagem efetiva de Douaud-Eyzat com etanol (`knock-and-failure-model` OQ-03).
- 🔴 Validação dos parâmetros do espectro sintético de knock (T = 2400 K, C = 1,0, τ_d = 1,0 ms) contra literatura aberta (`telemetry-datalogger` OQ-03).
- 🔴 Medição real do custo do modo `process` × `thread` no hardware de referência (Sprint 1).
- 🟡 Nota de norma: o RFC 7807 citado nas specs foi substituído pelo RFC 9457 (*Problem Details for HTTP APIs*, 2023, `https://www.rfc-editor.org/rfc/rfc9457`). O formato é compatível; o projeto mantém o `Content-Type: application/problem+json` e os campos atuais.
