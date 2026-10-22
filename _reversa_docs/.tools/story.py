"""Storyteller: glossário, deck, índice de features e páginas das features 001, 002 e 003."""
import os
from common import DATA, load_json, save_json, render, write_page, register, now, esc

AGENT = "reversa-docs-storyteller"

# ---------------------------------------------------------------- glossário
G = [
    # (termo, categoria, definição, onde aparece)
    ("Lambda (λ)", "Mistura", "Razão entre a mistura ar/combustível real e a estequiométrica. λ = 1 é estequiométrico; λ < 1 é rica; λ > 1 é pobre. Mistura pobre em carga alta eleva a temperatura e provoca knock.", "lambda_measured, tabela lambda alvo"),
    ("AFR", "Mistura", "Relação ar/combustível em massa. O AFR estequiométrico muda com o combustível: cerca de 14,7 na gasolina pura e cerca de 9 no E100. Lambda normaliza o AFR pelo estequiométrico.", "physics/fuel_blend.py"),
    ("VE (eficiência volumétrica)", "Ar", "Fração do volume do cilindro que o motor realmente enche de ar em cada ciclo. Nas ECUs standalone a tabela VE (RPM × MAP) define o combustível no modo speed-density.", "tabela VE 16×16, Quick Tune"),
    ("Speed-density", "Ar", "Estratégia que calcula a massa de ar a partir de RPM, MAP, IAT e VE, sem medidor de fluxo de ar.", "ecu-core"),
    ("VVT (comando variável)", "Ar", "Variação da fase dos cames de admissão e escape. Muda o cruzamento de válvulas e, com ele, a VE e a fração residual. Entregue na feature 002 (estratégia vvt).", "ecu/strategies/vvt.py, cam_intake_deg"),
    ("Overlap (cruzamento de válvulas)", "Ar", "Ângulo em que admissão e escape ficam abertos ao mesmo tempo. No simulador: overlap = base + vvt_in − vvt_ex. Em baixa rotação, mais overlap reduz a VE; em alta rotação, com MAP maior que a contrapressão, aumenta a VE.", "physics/fuel.py (ValveOverlap)"),
    ("Fração residual", "Ar", "Parte dos gases queimados que fica no cilindro e dilui a mistura nova. Cresce com o overlap em baixa rotação.", "engine-physics-core"),
    ("MAP", "Sensores", "Pressão absoluta no coletor de admissão (kPa). Eixo de carga das tabelas VE e ignição em ECUs standalone. Acima de 100 kPa indica sobrealimentação.", "eixo das tabelas, Live Cell Tracing"),
    ("IAT", "Sensores", "Temperatura do ar de admissão. IAT alta reduz a densidade do ar e aproxima o limiar de knock. O intercooler esportivo da oficina reduz a IAT.", "SensorReadings"),
    ("ECT", "Sensores", "Temperatura do líquido de arrefecimento. A estratégia VVT fica inibida com motor frio (ECT abaixo do mínimo).", "VvtConfig"),
    ("TPS e pedal", "Sensores", "Posição da borboleta e do pedal. Na bancada, segurar Espaço sobe o pedal a 120 %/s; soltar fecha para 0 % em até 150 ms.", "useHoldThrottle, pedal_pct"),
    ("Sonda wideband", "Sensores", "Sensor de oxigênio de banda larga que mede lambda em toda a faixa. Base da malha fechada.", "closed loop"),
    ("Sensor flex", "Sensores", "Sensor que mede o teor de etanol do combustível. No simulador publica ethanol_pct com ruído pequeno e determinístico.", "SensorReadings.ethanol_pct"),
    ("Malha fechada (closed loop)", "ECU", "Correção contínua do combustível pela leitura da wideband em relação ao lambda alvo, com trims de curto (STFT) e longo prazo (LTFT).", "ecu-core"),
    ("STFT e LTFT", "ECU", "Trims de combustível de curto e de longo prazo. O LTFT reinicia a cada nova sessão.", "ecu-core"),
    ("IDC (duty cycle do bico)", "Combustível", "Percentagem do tempo em que o bico fica aberto no ciclo. Acima de cerca de 85 % o bico satura. Bicos de maior vazão reduzem o IDC para a mesma carga.", "injector_duty_pct"),
    ("Pulso de injeção", "Combustível", "Tempo de abertura do bico em milissegundos por ciclo.", "injector_pw_ms"),
    ("Flex fuel", "Combustível", "Combustível com teor de etanol variável entre E27 e E100. A física mistura as propriedades (AFR, PCI, calor latente, densidade, octanagem) e a ECU compensa combustível, avanço e boost.", "blend_fuel, flex_ign_add, flex_boost_add"),
    ("E27, E100 e Podium", "Combustível", "Gasolina comum brasileira (27 % de etanol), etanol hidratado e gasolina de competição de alta octanagem. Âncoras do blend flex.", "vehicle-catalog"),
    ("Octanagem (RON, MON)", "Combustível", "Resistência do combustível à detonação. O simulador usa ON = (RON + MON) / 2 no limiar de knock.", "knock-and-failure-model"),
    ("Avanço de ignição", "Ignição", "Ângulo antes do PMS em que a vela dispara. Mais avanço aproxima o MBT, mas aumenta pressão e temperatura e pode provocar knock.", "tabela de ignição 3D"),
    ("MBT", "Ignição", "Minimum spark advance for Best Torque: o menor avanço que entrega o torque máximo. Avançar além do MBT não ganha torque e só aumenta o risco.", "jornada do Rodrigo"),
    ("Knock (detonação)", "Falhas", "Autoignição da mistura não queimada depois da faísca. Gera oscilação de pressão, calor no pistão e dano. A física publica knock_sensor_v (0 a 5 V) e knock_intensity (0 a 1).", "damage, espectrograma"),
    ("Pré-ignição e LSPI", "Falhas", "Ignição da mistura antes da faísca, por ponto quente ou, em baixa rotação e carga alta, por LSPI (low-speed pre-ignition). Muito mais destrutiva que o knock.", "damage/model.py"),
    ("Livengood-Wu e Douaud-Eyzat", "Falhas", "Integral de atraso de autoignição (Livengood-Wu) com a correlação de Douaud-Eyzat. Prevê quando a zona não queimada detona.", "knock-and-failure-model"),
    ("EGT", "Temperatura", "Temperatura dos gases de escape. Limite típico de 950 a 980 °C na turbina. A visão térmica pinta o coletor de vermelho (650 °C) a amarelo (980 °C).", "egt_c, render/thermal.ts"),
    ("Laudo forense (autópsia)", "Falhas", "Relatório da quebra com a cadeia causal termodinâmica, os sinais antecipados e recomendações didáticas.", "ForensicReport"),
    ("Saúde de componente", "Falhas", "Valor de 0 a 1 por pistão, biela, válvulas, junta, turbina e bronzinas. Integridade de 100 % equivale a saúde mínima >= 0,999.", "ComponentHealth"),
    ("Wastegate", "Sobrealimentação", "Válvula que desvia gases de escape da turbina para limitar o boost. Um dos defeitos ocultos é a wastegate travada.", "defect-wastegate-stuck"),
    ("Boost e controle PID", "Sobrealimentação", "Pressão de sobrealimentação acima da atmosférica. A ECU controla o boost por malha PID e por marcha.", "ecu-core, boost por marcha"),
    ("Spool e lag", "Sobrealimentação", "Tempo para a turbina ganhar rotação e gerar boost. A turbina upgraded da oficina dá mais fluxo no topo e mais lag em baixa.", "turbo_rpm"),
    ("Contrapressão", "Sobrealimentação", "Pressão no coletor de escape antes da turbina. O downpipe de alto fluxo reduz contrapressão e EGT (escala 0,6).", "exhaust_backpressure_scale"),
    ("Supercharger (compressor)", "Sobrealimentação", "Compressor acionado pela correia do motor, sem lag de turbina. No V8 o áudio tem assobio proporcional à rotação.", "muscle-v8-sc"),
    ("Two-step e launch control", "Estratégias", "Limitador de rotação para largada com atraso de ponto e enriquecimento, para criar boost parado.", "TwoStepConfig"),
    ("Antilag", "Estratégias", "Atraso de ignição e enriquecimento fora de carga para manter a turbina girando entre trocas.", "ecu-core"),
    ("Powershift", "Estratégias", "Corte curto de ignição para trocar de marcha sem tirar o pé.", "ecu-core"),
    ("Overrun e pops & bangs", "Estratégias", "Na desaceleração, corte de injeção atrasado e atraso de ignição queimam combustível no escape. Gera estalos e chamas, mas aquece a turbina.", "overrun, chamas no escape"),
    ("Limitador de rotação", "Estratégias", "Corte de injeção ou ignição acima de uma rotação máxima.", "ecu-core"),
    ("Failsafe", "Estratégias", "Proteções da ECU (EGT, lambda, pressão) que reduzem potência ou cortam o motor.", "BaseSetup"),
    ("Roda fônica e PMS", "Configuração", "Roda dentada que dá posição e rotação do virabrequim; o PMS é o ponto morto superior. PMS errado desloca o avanço real e provoca knock.", "BaseSetup, swap"),
    ("OEM e OEM-Stage", "ECU", "ECU de série do fabricante. OEM-Stage é o perfil genérico do simulador com lógica por torque e carga.", "profiles/descriptors"),
    ("Standalone", "ECU", "ECU programável que substitui a OEM. Perfis genéricos FT-Pro, M1-Race e HT-Elite, sem marcas registradas.", "ecu-profiles"),
    ("Swap", "ECU", "Troca da ECU OEM por uma standalone, com checklist e mapa base gerado por assistente.", "BaseSetupWizard"),
    ("Calibração (remap)", "ECU", "Conjunto versionado de tabelas e estratégias. Calibrações stock-* são somente leitura desde a 002 (409 CALIBRATION_STOCK_IMMUTABLE).", "ecu/calibration.py"),
    ("Tabela live-tunable", "ECU", "Tabela que pode mudar durante a puxada: VE, lambda alvo, ignição, trims e, na 002, as tabelas de came.", "live_tunable_table_ids"),
    ("Stage 1, 2 e 3", "Treino", "Níveis de preparação: Stage 1 só calibração; Stage 2 com peças de admissão e escape; Stage 3 com turbina e internos.", "cenários, Stage Builder"),
    ("Internos forjados", "Oficina", "Pistões e bielas forjados. Elevam carga máxima da biela (×1,35), pressão de cilindro (×1,25) e temperatura do pistão (+40 °C).", "catalog/upgrades.py"),
    ("Intercooler", "Oficina", "Trocador que resfria o ar comprimido. O esportivo melhora a eficiência em +0,08 e reduz a IAT.", "catalog/upgrades.py"),
    ("Downpipe", "Oficina", "Tubo logo após a turbina. O de alto fluxo reduz contrapressão e EGT.", "catalog/upgrades.py"),
    ("whp", "Dinamômetro", "Potência medida na roda (wheel horsepower), com perdas de transmissão.", "dyno-bench"),
    ("Puxada", "Dinamômetro", "Medição no rolo: baseline, varredura (sweep), carga estacionária (steady-state hold) ou série (multi_pull).", "dyno-bench"),
    ("Correção SAE J1349 e DIN 70020", "Dinamômetro", "Normas que corrigem a potência medida para condições atmosféricas padrão.", "dyno-bench"),
    ("Absorvedor de Foucault", "Dinamômetro", "Freio por correntes parasitas que aplica carga no rolo para a carga estacionária.", "dyno-bench"),
    ("Quick Tune", "Live Tuning", "Tecla Q: VE nova = VE atual × (λ medido / λ alvo), limitado a ±25 % por aplicação e só na tabela VE.", "ecu-tuning/ops/quickTune.ts"),
    ("Live Cell Tracing", "Live Tuning", "Destaque piscante da célula [RPM × MAP] em operação, a partir dos frames do WebSocket. Fica estático com prefers-reduced-motion.", "live-tuning/liveCell.ts"),
    ("Interpolação H, V e B", "Live Tuning", "Atalhos do editor: H interpola na horizontal, V na vertical, B suaviza o bloco com núcleo 3×3.", "TableEditorCore"),
    ("Defeito oculto", "Treino", "Falha física escondida no cenário (bomba fraca, vazamento de boost, bico obstruído, wastegate travada) que o aluno precisa diagnosticar antes de culpar o mapa.", "HiddenDefect, defect-*"),
    ("Modo carreira e ordem de serviço", "Treino", "Perfil com saldo e reputação. A ordem paga só com tentativa aprovada; quebra de motor debita o custo do motor.", "backend/career, /workshop"),
    ("Benchmark Reference Baseline v1", "Qualidade", "Conjunto canônico de curvas dos 4 veículos. A física precisa ficar com desvio < 5 % em torque, potência, lambda e EGT.", "tests -m accuracy"),
    ("Determinismo e seed", "Qualidade", "Mesma seed, mesmos upgrades e mesmo etanol produzem a mesma telemetria, verificada por SHA-256.", "D-07, test_determinism_20x"),
    ("Pacote assinado", "Qualidade", "JSON de desafio ou tentativa com SHA-256 do JSON canônico RFC 8785 (JCS). Permite ao instrutor avaliar sem rede.", "SignedPackage"),
    ("seq", "Telemetria", "Número de sequência de cada envelope do WebSocket. Nunca se repete, inclusive em mensagens de erro.", "WsEnvelope"),
    ("Chunk e code-splitting", "Frontend", "Arquivo JavaScript gerado pelo build. A 002 dividiu fornecedores (three, react, zod, uPlot) e carrega páginas por React.lazy; nenhum chunk passa de 500 kB.", "vite.config.ts"),
    ("Rust e crate simremap_rs", "Motor nativo", "Rust é uma linguagem compilada, sem coletor de lixo, com desempenho de C. O crate simremap_rs reúne os kernels nativos da simulação em três submódulos: tables (ECU), cycle (física) e damage (detonação e dano).", "backend/rust/simremap_rs/"),
    ("PyO3", "Motor nativo", "Biblioteca Rust que expõe funções e classes Rust como módulo Python. O crate usa PyO3 0.23; o módulo importável é simremap_rs._native.", "src/lib.rs"),
    ("maturin", "Motor nativo", "Ferramenta que compila um crate PyO3 e o instala como pacote Python. make native roda maturin develop --release; maturin é dependência de desenvolvimento do backend.", "Makefile (make native), pyproject.toml"),
    ("ABI3 (ABI estável)", "Motor nativo", "Interface binária estável do CPython. Um wheel ABI3 compilado para Python 3.12 funciona nas versões seguintes sem recompilar (feature abi3-py312).", "Cargo.toml, _native.abi3.so"),
    ("FFI", "Motor nativo", "Foreign Function Interface: a travessia entre Python e Rust. Cada travessia tem custo fixo; por isso a 003 faz uma chamada por subsistema por tick (D-03), nunca uma por célula de tabela.", "physics/kernels.py, ecu/native_tables.py"),
    ("Kernel", "Motor nativo", "Rotina numérica compacta do caminho quente, executada a cada tick: interpolação de tabelas, ciclo Otto, bloco de gás e turbo, integral de knock e dano. Exemplos: TableSet, CycleKernel e GasKernel.", "simremap_rs.tables, simremap_rs.cycle"),
    ("SIMREMAP_NATIVE", "Motor nativo", "Variável que escolhe o caminho: auto (padrão) usa a extensão se ela importar; off usa só Python; on exige a extensão e falha sem ela. Lida uma vez por processo.", "simremap/core/native.py"),
    ("Fallback Python", "Motor nativo", "Sem a extensão, ou com SIMREMAP_NATIVE=off, a simulação usa o Python de referência com o mesmo comportamento. A imagem Docker funciona sem toolchain Rust.", "core/native.py, Dockerfile"),
    ("Paridade bit a bit", "Motor nativo", "Python e Rust produzem exatamente os mesmos números quando a ordem das operações é a mesma. Os testes de paridade aceitam no máximo erro relativo de 1e-9 por grandeza por tick; o determinismo por seed se mantém.", "backend/tests/native/"),
    ("Hot path (caminho quente)", "Motor nativo", "Código executado milhares de vezes por segundo. No simulador: o tick de 1 ms do laço sensors → ecu → physics → damage → telemetry.", "physics/fastmodel.py"),
    ("Tick e P99", "Desempenho", "Tick é um passo do laço (1 ms a 1000 Hz). P99 é a latência abaixo da qual ficam 99 % dos ticks. No hatch, o tick médio caiu de 179 para 107 µs e o P99 de 490 para 345 µs.", "tests/bench/test_bench_native_tick.py"),
    ("Overrun do worker", "Desempenho", "Evento worker.overrun: o tick passou do orçamento de tempo real. Desde a 003 só conta acima de dt × wall_budget_ticks, e o arrefecimento acelerado do multi_pull declara o seu orçamento.", "core/worker/loop.py"),
    ("Surge do compressor", "Sobrealimentação", "Instabilidade do compressor com pouca vazão e razão de pressão alta: o fluxo reverte e o boost oscila. A 003 recalibrou a linha de surge (0,30·ṁ_choke·√min(N/N_design,1), sem surge abaixo de PR 1,05).", "physics/turbo.py, cycle/gas.rs"),
    ("BOV / diverter", "Sobrealimentação", "Blow-off valve: válvula que alivia a pressão entre compressor e borboleta quando a borboleta fecha. Evita surge no coastdown e gera o chirp de alívio no áudio. Abre com borboleta < 5 % e pré-borboleta > MAP + 10 kPa.", "ecu/runtime.py, audio/AudioEngine.ts"),
    ("Ciclo-limite PID", "ECU", "Oscilação sustentada de uma malha PID com ganhos altos demais. No hatch de série, o PID de boost gerava 7,5 Hz de ±12,3 N·m; os ganhos kp 0,1 / ki 0,3 / kd 0 reduziram para ±0,44 N·m.", "calibrations/oem-stage.json"),
    ("dTPS e enriquecimento de aceleração", "ECU", "dTPS/dt é a taxa de variação da borboleta. A ECU enriquece a mistura quando o pedal sobe rápido. Desde a 003 a taxa usa a mediana de 3 amostras para ignorar ruído do sensor.", "ecu/runtime.py (B1)"),
    ("Calibração ativa", "ECU", "Calibração em uso na sessão depois de aplicar, swap ou base setup. Fica em active_calibration_id; calibration_id segue como a calibração inicial.", "dyno/contracts.py"),
    ("Web Audio", "Áudio", "API do navegador que monta um grafo de nós de áudio (fontes, filtros, ganhos) processado em tempo real. A bancada sintetiza o som do motor sem amostras gravadas.", "dyno-cockpit/audio/graph.ts"),
    ("Pulsos de combustão", "Áudio", "Fonte do som: um impulso por explosão, na frequência de disparo (rpm / 60 × cilindros / 2). Substitui os osciladores puros da 002.", "audio/EngineSynth.ts, waveforms.ts"),
    ("WaveShaper", "Áudio", "Nó do Web Audio que aplica uma curva de saturação ao sinal. Dá corpo e aspereza mecânica aos pulsos.", "audio/graph.ts"),
    ("Passa-baixa dinâmico", "Áudio", "Filtro lowpass cuja frequência de corte sobe de 180 para 1400 Hz com rpm e carga. Em marcha lenta o som é abafado; a plena carga, mais aberto.", "audio/AudioEngine.ts"),
    ("Ressonador (filtro peaking)", "Áudio", "Filtro que reforça uma faixa estreita de frequências, como a caixa do escapamento. A cadeia usa dois: 90–140 Hz e 280–450 Hz.", "audio/archetypes.ts"),
    ("Sub-bass", "Áudio", "Camada abaixo de cerca de 80 Hz que dá peso ao motor nos alto-falantes.", "audio/voices.ts"),
    ("Corte de presença (1–4 kHz)", "Áudio", "Atenuação da faixa onde o ouvido é mais sensível e o som fica estridente. RN-03: nenhum arquétipo passa de 5 % da energia em 1–4 kHz (máximo medido 2,2 %).", "audio/spectrum.ts"),
    ("Ruído de banda estreita", "Áudio", "Ruído filtrado numa faixa estreita. Simula o assobio do turbo sem o apito de um seno puro; nenhum OscillatorNode contínuo no spool.", "audio/AudioEngine.ts"),
    ("Flutter e chirp", "Áudio", "Sons do alívio do turbo: flutter é a vibração do compressor quando o ar volta; chirp é o assobio curto da BOV.", "audio/AudioEngine.ts"),
    ("Arquétipo de áudio", "Áudio", "Perfil sonoro por arquitetura: i4 turbo, i6 turbo, i4 clássico e V8 com compressor. Define ressonadores, saturação e mistura de cada carro.", "audio/archetypes.ts"),
    ("Playwright e spec E2E", "Qualidade", "Playwright abre o app num navegador real e executa fluxos completos. Cada arquivo *.spec.ts é um conjunto de testes; a 003 criou 8 specs novos.", "frontend/e2e/"),
    ("mypy --strict", "Qualidade", "Verificador de tipos estático do Python no modo mais rigoroso. make type roda mypy --strict src tests; na 003 ficou com 0 erros em 440 arquivos.", "Makefile#type"),
]


def slug(s):
    import re
    import unicodedata
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


glossary = {"schemaVersion": 1, "generatedAt": now(),
            "source": "requirements.md 1.1 (001), specs SDD, requirements da 002 (sem .reversa/soul.md)",
            "concepts": [{"term": t, "slug": slug(t), "category": c, "definition": d, "where": w} for t, c, d, w in G]}
save_json(os.path.join(DATA, "glossary.json"), glossary)

cats = sorted({c for _, c, _, _ in G})
gl_payload = f"""
<h1>Glossário</h1>
<p class="lead">{len(G)} termos de calibração, física e do próprio código. Cada termo tem link direto (<code>#concept-…</code>) e indica onde aparece no projeto.</p>
<input id="q" class="search" type="search" placeholder="Buscar termo ou definição (ex.: lambda, overlap, IDC)" aria-label="Buscar no glossário">
<div class="chips" id="chips" role="group" aria-label="Filtrar por categoria"><button class="chip" aria-pressed="true" data-cat="">Todas</button>
{"".join(f'<button class="chip" aria-pressed="false" data-cat="{esc(c)}">{esc(c)}</button>' for c in cats)}</div>
<p class="muted" id="count"></p>
<div class="grid g3" id="cards"></div>
"""
gl_script = r"""
<script>
(function () {
  "use strict";
  var G = (window.RV_DATA && window.RV_DATA.glossary && window.RV_DATA.glossary.concepts) || [];
  var box = document.getElementById("cards"), q = document.getElementById("q"), cnt = document.getElementById("count"), cat = "";
  function norm(s) { return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function draw() {
    var t = norm(q.value || "");
    var list = G.filter(function (g) { return (!cat || g.category === cat) && (!t || norm(g.term + " " + g.definition + " " + g.where).indexOf(t) >= 0); });
    cnt.textContent = list.length + " de " + G.length + " termos";
    box.innerHTML = list.map(function (g) {
      return '<article class="card concept" id="concept-' + g.slug + '"><span class="badge cat">' + esc(g.category) + '</span><h3><a href="#concept-' + g.slug + '" style="text-decoration:none;color:inherit">' + esc(g.term) + '</a></h3><p>' + esc(g.definition) + '</p><p class="muted mono" style="font-size:12px">' + esc(g.where) + '</p></article>';
    }).join("");
    if (location.hash) { var el = document.getElementById(location.hash.slice(1)); if (el) el.scrollIntoView(); }
  }
  q.addEventListener("input", draw);
  document.querySelectorAll("#chips .chip").forEach(function (b) {
    b.addEventListener("click", function () {
      document.querySelectorAll("#chips .chip").forEach(function (x) { x.setAttribute("aria-pressed", "false"); });
      b.setAttribute("aria-pressed", "true"); cat = b.dataset.cat; draw();
    });
  });
  draw();
})();
</script>
"""
write_page("glossario.html", render("glossario", "Glossário", gl_payload, AGENT, "glossario", scripts=gl_script))

# ---------------------------------------------------------------- features-index
SPECS = [
    ("platform-foundation", "Fundação da plataforma", 24, "Monorepo, FastAPI com lifespan, config SIMREMAP_, erros RFC 7807, Alembic, worker do laço, Docker e portões de qualidade.", "core, api, db"),
    ("engine-physics-core", "Física do motor", 26, "Modelo termodinâmico 0D/1D do ciclo Otto (aspirado, turbo, supercharged), passo fixo determinístico de 100 a 1000 Hz.", "physics"),
    ("vehicle-catalog", "Catálogo de veículos", 29, "Fonte única dos 4 veículos: geometria, sobrealimentação, bicos, combustíveis, limites e calibração de fábrica.", "catalog"),
    ("dyno-bench", "Dinamômetro", 26, "Rolo inercial, absorvedor de Foucault, sessões e as 4 puxadas, com correção SAE J1349 ou DIN 70020.", "dyno"),
    ("knock-and-failure-model", "Knock e falhas", 32, "Livengood-Wu e Douaud-Eyzat, pré-ignição, dano por componente, 6 modos de falha e laudo forense.", "damage"),
    ("ecu-core", "Núcleo da ECU", 33, "Tabelas 2D/3D, calibração versionada, estratégias e arbitragem determinística, em até 0,1 ms por tick.", "ecu"),
    ("ecu-profiles", "Perfis de ECU", 31, "OEM-Stage, FT-Pro, M1-Race e HT-Elite; BaseSetup standalone; swap OEM para standalone com assistente.", "profiles"),
    ("telemetry-datalogger", "Telemetria e datalogger", 25, "WebSocket com envelope seq, decimação para 30 a 60 FPS, DataLog com SHA-256, export e import.", "telemetry"),
    ("training-scenarios", "Cenários de treino", 27, "Perfis locais, cenários com defeitos ocultos, tentativas, avaliação objetiva e pacotes assinados.", "scenarios"),
    ("dyno-cockpit-ui", "Bancada (UI)", 22, "Curvas, gauges, espectrograma, carro no rolo, som do motor, datalogger e laudo no navegador.", "frontend dyno-cockpit"),
    ("ecu-tuning-ui", "Software de ECU (UI)", 22, "Editor de tabelas 2D/3D até 32×32, estratégias, assistente de swap, histórico com diff.", "frontend ecu-tuning"),
]
features_index = {"schemaVersion": 1, "generatedAt": now(),
                  "note": "Greenfield: as specs ficam em _reversa_sdd/sdd/*.md e as features em _reversa_forward/<id>/requirements.md",
                  "features": [{"id": "001-simulador-remap", "href": "features/001-simulador-remap.html", "title": "Simulador Completo de Remap em Dinamômetro"},
                               {"id": "002-evolucao-comercial", "href": "features/002-evolucao-comercial.html", "title": "Evolução Comercial"},
                               {"id": "003-rust-audio-qa-total", "href": "features/003-rust-audio-qa-total.html", "title": "Motor Nativo em Rust, Acústica Realista, QA Total e E2E"}],
                  "specs": [{"id": i, "title": t, "rf": rf, "summary": s, "package": p, "path": f"_reversa_sdd/sdd/{i}.md"} for i, t, rf, s, p in SPECS]}
save_json(os.path.join(DATA, "features-index.json"), features_index)

fi_payload = f"""
<h1>Features e specs</h1>
<p class="lead">O projeto nasceu greenfield: 11 specs SDD em <code>_reversa_sdd/sdd/</code> descrevem os componentes, e três features do ciclo forward
em <code>_reversa_forward/</code> os implementaram e evoluíram.</p>
<h2>Features</h2>
<div class="grid g2">
<a class="card" href="001-simulador-remap.html"><h3>001 · Simulador Completo de Remap em Dinamômetro</h3><p>MVP integrado das 11 specs: física 0D/1D, 4 veículos, 4 perfis de ECU, falhas com laudo, telemetria e cenários avaliáveis.</p>
<span class="badge ok">452 de 453 ações</span><span class="badge">4 sprints</span><span class="badge">3 jornadas E2E</span></a>
<a class="card" href="002-evolucao-comercial.html"><h3>002 · Evolução Comercial</h3><p>Seis frentes: blindagem de cenários, Live Tuning, VVT + oficina + flex fuel, imersão, defeitos + carreira, build e documentação.</p>
<span class="badge ok">62 de 62 ações</span><span class="badge new">28 RF</span><span class="badge">chunks ≤ 500 kB</span></a>
<a class="card" href="003-rust-audio-qa-total.html"><h3>003 · Motor Nativo em Rust, Acústica Realista, QA Total e E2E</h3><p>Quatro frentes: kernels em Rust (PyO3 ABI3) com fallback Python, nova síntese de áudio, QA total com make type limpo, e E2E Playwright com build de produção.</p>
<span class="badge ok">30 de 33 ações</span><span class="badge n3">18 RF</span><span class="badge">física 2,8×</span><span class="badge">8 specs E2E novos</span></a>
</div>
<h2>Specs SDD (componentes)</h2>
<div class="grid g3">
{"".join(f'<div class="card"><h3>{esc(t)}</h3><p class="mono muted" style="font-size:12px">_reversa_sdd/sdd/{i}.md</p><p>{esc(s)}</p><span class="badge">{rf} RF</span><span class="badge">{esc(p)}</span></div>' for i, t, rf, s, p in SPECS)}
</div>
"""
write_page("features/index.html", render("features", "Features", fi_payload, AGENT, "feature", base="../"))


def acc(title, body, open_=False):
    return f'<details{" open" if open_ else ""}><summary>{title}</summary><div class="body">{body}</div></details>'


def table(head, rows, nums=()):
    th = "".join(f'<th{" class=num" if i in nums else ""}>{h}</th>' for i, h in enumerate(head))
    trs = "".join("<tr>" + "".join(f'<td{" class=num" if i in nums else ""}>{c}</td>' for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f'<div class="table-wrap"><table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>'


# ---------------------------------------------------------------- feature 001
f1 = f"""
<p class="muted"><a href="index.html">Features</a> / 001-simulador-remap</p>
<h1>001 · Simulador Completo de Remap em Dinamômetro</h1>
<p class="lead"><b>Em uma frase:</b> o MVP do SimuladorRemap, uma aplicação web local-first num container por estação, onde o aluno calibra uma ECU real
num dinamômetro virtual com física termodinâmica e vê o motor ganhar potência ou quebrar com laudo da causa.</p>
<div class="grid g4">
<div class="card kpi"><div class="v">452/453</div><div class="l">ações concluídas</div><div class="s">T091 pendente (smoke do container)</div></div>
<div class="card kpi"><div class="v">11</div><div class="l">specs integradas</div><div class="s">ordem 9 → 1 → 3 → 4 → 2 → 5 → 6 → 7 → 11 → 10 → 8</div></div>
<div class="card kpi"><div class="v">&lt; 5 %</div><div class="l">desvio nos 4 veículos</div><div class="s">torque: 3,4 · 1,4 · 2,3 · 3,5 %</div></div>
<div class="card kpi"><div class="v">2035 + 450</div><div class="l">testes no fecho</div><div class="s">backend + frontend; Playwright 7/7</div></div>
</div>
<h2>Como funciona</h2>
<div class="flow"><span>Tela inicial: carro, perfil, cenário</span><b>→</b><span>POST /api/v1/sessions</span><b>→</b><span>worker do laço 1000 Hz</span><b>→</b>
<span>sensors → ecu → physics → damage → telemetry</span><b>→</b><span>WS 30 a 60 FPS</span><b>→</b><span>bancada: curvas, gauges, som</span><b>→</b><span>datalog SHA-256 e laudo</span></div>
{acc("Escopo por sprint", table(["Sprint", "Componentes", "Fatia entregue"], [
    ["1", "platform-foundation, engine-physics-core, vehicle-catalog", "Container local, erros padronizados, laço físico isolado, catálogo com hatch-20t-gdi validado"],
    ["2", "dyno-bench, knock-and-failure-model, ecu-core", "Sessões e 4 puxadas, knock, dano, 6 modos de falha, laudo, runtime de ECU"],
    ["3", "ecu-profiles, telemetry-datalogger, dyno-cockpit-ui", "4 perfis, swap standalone, WS de telemetria, datalog, tela da bancada"],
    ["4", "ecu-tuning-ui, training-scenarios", "Editor de ECU, perfis locais, cenários, avaliação, pacotes, painel do instrutor"]]), True)}
{acc("Resultado das 3 jornadas", table(["Persona", "Resultado medido"], [
    ["Lucas (Stage 1/2 no OEM-Stage)", "Série 214,7 whp; Stage 1 +46 whp; Stage 2 com pops &amp; bangs +67,7 whp sem knock e EGT 915 °C; calibração exagerada quebra a biela com laudo de 5 elos"],
    ["Rodrigo (swap para FT-Pro)", "Clássico 2.0 turbo com cerca de 334 whp em multi_pull e dispersão de 0,34 %"],
    ["Prof. Marcos (desafio)", "Desafio exportado; a tentativa é avaliada com o mesmo evaluation_sha256 na estação do instrutor"]]))}
{acc("Componentes implementados (11 specs)", table(["Spec", "RF", "Pacote", "Deltas registrados no adendo"], [
    ["platform-foundation", "24", "core, api, db", "worker_mode = process por benchmark; limite de corpo por rota (64 MiB nos imports); ping WS 15 s"],
    ["engine-physics-core", "26", "physics", "Euler linearmente implícito nas pressões (Heun instável a 1 ms); teto de 2400 K no gás da porta"],
    ["vehicle-catalog", "29", "catalog", "Turbo, compressor, VE e avanço recalibrados para o benchmark; catalog_version 1.1.0; 4 veículos validated"],
    ["dyno-bench", "26", "dyno", "Sessão congelada até o primeiro comando; V8 medido em 5.ª marcha"],
    ["knock-and-failure-model", "32", "damage", "DamageConfig 1.2.0; τ de Douaud-Eyzat ×4,25; LSPI só acima de 2700 kPa de IMEP"],
    ["ecu-core", "33", "ecu", "Table2D/Table3D e Calibration; RF-31 (comando variável) ficou fora e foi entregue na 002"],
    ["ecu-profiles", "31", "profiles", "OEM-Stage com marcha lenta, corte na desaceleração; two-step ±100 rpm"],
    ["telemetry-datalogger", "25", "telemetry", "Canal pedal_pct; 77 kB/s com compressão WS; log de multi_pull (~257 MB) passa do limite de import"],
    ["training-scenarios", "27", "scenarios", "standalone-swap = 300 whp absolutos; pacotes só SHA-256 sem PIN"],
    ["dyno-cockpit-ui", "22", "frontend/dyno-cockpit", "Seletor dos 4 carros; limites de boost dos gauges inferidos"],
    ["ecu-tuning-ui", "22", "frontend/ecu-tuning", "Trim de ignição ±10° na UI; edição de breakpoints de eixo não implementada"]], nums=(1,)))}
{acc("Decisões técnicas centrais", "<ul>" + "".join(f"<li>{x}</li>" for x in [
    "<b>D-01</b> Monólito modular FastAPI com 1 pacote por componente e registro único de routers.",
    "<b>D-04</b> Laço físico em processo dedicado por sessão, decidido por benchmark.",
    "<b>D-05</b> Saída do worker em duas faixas: crítica sem descarte e frames com descarte do mais antigo.",
    "<b>D-07</b> Tempo só por contagem de ticks e RNG PCG64 por canal; time e random proibidos nos pacotes determinísticos.",
    "<b>D-09</b> SQLite em WAL por padrão; PostgreSQL 16 opcional.",
    "<b>D-11</b> Pacotes de desafio com SHA-256 do JCS (RFC 8785).",
    "<b>D-22</b> uPlot em Canvas 2D; espectrograma em WebGL; three.js só no chunk lazy da superfície 3D.",
    "<b>D-23</b> Som do motor sintetizado em Web Audio, sem amostras licenciadas."]) + "</ul>")}
{acc("Modelo de dados e contratos", "<p>19 tabelas em 7 migrações lineares (<code>0001_foundation_base</code> a <code>0007_scenarios_base</code>), validadas em SQLite e PostgreSQL 16. Contratos em <code>_reversa_forward/001-simulador-remap/contracts/</code>: <code>rest-api.md</code>, <code>websocket-telemetry.md</code>, <code>simulation-bus.md</code>, <code>file-formats.md</code>. Cliente REST gerado por orval com 39 caminhos.</p>")}
{acc("Pendências e pontos de atenção", "<ul><li><b>T091</b>: <code>scripts/smoke_container.sh</code> não rodou porque o disco da VM do Docker Desktop está cheio. <code>docker compose config</code> e <code>docker build --check</code> passam.</li><li>O laço de 1000 Hz foi medido em Apple Silicon (0,078 ms por tick), ainda sem medição no hardware de referência de 4 núcleos.</li><li>21 ações com confidência 🔴 (benchmarks e calibrações de referência estimadas).</li></ul>")}
<h2>Fontes</h2>
<p class="mono muted" style="font-size:12.5px">_reversa_forward/001-simulador-remap/requirements.md · roadmap.md · actions.md · legacy-impact.md · regression-watch.md (W001 a W297) · _reversa_sdd/addenda/001-simulador-remap.md</p>
"""
write_page("features/001-simulador-remap.html", render("feature-001-simulador-remap", "Feature 001", f1, AGENT, "feature", base="../"))

# ---------------------------------------------------------------- feature 002
FRONTS = [
    ("0", "Blindagem de cenários e calibrações", "RF-01 a RF-04",
     "Elimina o 422 SCENARIO_CALIBRATION_HASH_MISMATCH nos cenários builtin e torna as calibrações stock-* somente leitura.",
     ["Causa raiz: o cenário guardava o hash da v1 gravada, mas o clone recalculava o hash após model_dump → parse_content.",
      "D-01: load_builtin calcula o hash pela mesma rota do clone.",
      "D-02: autocura em builtin vehicle_stock; cenários importados mantêm o 422.",
      "D-03: PUT, revert e PATCH em stock-* retornam 409 CALIBRATION_STOCK_IMMUTABLE.",
      "D-04: sessão sem calibration_id nasce com um clone do usuário."],
     "scenarios/catalog.py, scenarios/attempts.py, scenarios/ports.py, ecu/router.py, dyno/session.py"),
    ("1", "Live Tuning", "RF-05 a RF-09",
     "Bancada e tabela na mesma tela, célula ativa piscando ao vivo e correção rápida da VE pelo lambda.",
     ["Tela Dividida (tecla L): controles, gauges e carro de um lado; editor compacto da tabela da sessão do outro.",
      "Live Cell Tracing: a célula [RPM × MAP] em operação pisca a partir dos frames do WebSocket.",
      "Edições aplicadas à sessão automaticamente (PATCH e POST /sessions/{id}/calibration).",
      "Quick Tune Q: VE × (λ medido / λ alvo), limite ±25 %, só tabela VE.",
      "H, V e B: interpolação horizontal, vertical e suavização 3×3."],
     "frontend/dyno-cockpit/live-tuning/, ecu-tuning/ops/quickTune.ts, TableEditorCore.tsx"),
    ("2", "Física e ECU: VVT, oficina de upgrades e flex fuel", "RF-10 a RF-19",
     "Comando variável com efeito real na VE, peças mecânicas que mudam o veículo e combustível flex E27 a E100.",
     ["VVT: overlap = base + vvt_in − vvt_ex, efeito zero no cronograma de série (benchmark preservado).",
      "Estratégia vvt (10.º kind) nos 4 perfis: inibição com motor frio, limite de taxa, offsets.",
      "Oficina: turbo (área ×1,25, choke ×1,30, inércia ×1,45), bicos ×1,5, bomba 1,8, intercooler +0,08, downpipe 0,6, forjados.",
      "apply_upgrades(vehicle, pacote) via model_copy; peça incompatível retorna 422 UPGRADE_NOT_COMPATIBLE.",
      "Flex: blend_fuel mistura AFR (1/AFR linear na fração mássica), PCI, h_fg, densidade e octanagem; a ECU lê ethanol_pct."],
     "physics/fuel.py, physics/fuel_blend.py, ecu/strategies/vvt.py, catalog/upgrades.py, frontend/workshop/StageBuilder.tsx"),
    ("3", "Imersão", "RF-20 a RF-22",
     "Som, imagem e pedal mais próximos do rolo real.",
     ["Áudio por arquitetura: i4 turbo moderno, i6 turbo, i4 turbo clássico com marcha lenta irregular, V8 com assobio do compressor.",
      "Visão Térmica / Raio-X (tecla T): coletor e turbina de vermelho (650 °C) a laranja (815 °C) e amarelo (980 °C).",
      "Partículas por modo de falha e chamas de escape nos pops &amp; bangs.",
      "Pedal progressivo: Espaço sobe 120 %/s; soltar volta a 0 % em até 150 ms."],
     "frontend/dyno-cockpit/audio/, render/thermal.ts, CarAnimator.ts, useHoldThrottle.ts"),
    ("4", "Treino: defeitos ocultos e modo carreira", "RF-23 a RF-26",
     "Quatro cenários de diagnóstico e uma camada de jogo de oficina sobre as tentativas.",
     ["Cenários novos: defect-fuel-pump, defect-boost-leak, defect-lean-injector, defect-wastegate-stuck (7 builtins no total).",
      "Bomba fraca (84 L/h): lambda na janela abaixo de 5.000 rpm e pobre acima de 5.500 rpm.",
      "Carreira: perfil com saldo (R$ 5.000,00 inicial) e reputação 0 a 100; 7 ordens de serviço ligadas a cenários.",
      "Pagamento só com tentativa aprovada; quebra debita o custo do motor; liquidação idempotente.",
      "Migração 0008_career com career_profiles e career_jobs; página Oficina (Carreira) em /workshop."],
     "scenarios/builtin/defect-*.json, backend/career/, db/migrations/versions/0008_career.py, frontend/career/WorkshopPage.tsx"),
    ("5", "Desempenho do build e documentação", "RF-27 e RF-28",
     "Primeiro carregamento mais leve e este mini-site.",
     ["Code-splitting com codeSplitting.groups (Vite 8 / rolldown): vendor-three, vendor-react, vendor-zod, vendor-uplot.",
      "Todas as páginas por React.lazy, inclusive a da carreira.",
      "Maior chunk caiu de 530 kB (Table3DSurface) para 352 kB (vendor-three), sem subir chunkSizeWarningLimit.",
      "RF-28 / T062: documentação visual em _reversa_docs/ (esta execução)."],
     "frontend/vite.config.ts, Table3DSurface.tsx, _reversa_docs/"),
]
fronts_html = "".join(
    f'<div class="card front"><h3>Frente {n} · {esc(t)} <span class="badge">{rf}</span></h3><p>{esc(s)}</p>'
    f'<ul>{"".join(f"<li>{b}</li>" for b in bl)}</ul><p class="mono muted" style="font-size:12px">{esc(files)}</p></div>'
    for n, t, rf, s, bl, files in FRONTS)

f2 = f"""
<p class="muted"><a href="index.html">Features</a> / 002-evolucao-comercial</p>
<h1>002 · Evolução Comercial</h1>
<p class="lead"><b>Em uma frase:</b> um delta sobre o MVP, sem reescrita, que corrige o erro de hash dos cenários, coloca a calibração ao vivo na bancada,
fecha o VVT, cria a oficina de upgrades e o flex fuel, aumenta a imersão, adiciona defeitos ocultos e modo carreira, e alivia o build.</p>
<div class="grid g4">
<div class="card kpi"><div class="v">62/62</div><div class="l">ações concluídas</div><div class="s">T062 (documentação visual) concluída</div></div>
<div class="card kpi"><div class="v">28</div><div class="l">requisitos funcionais</div><div class="s">8 regras de negócio, 6 frentes</div></div>
<div class="card kpi"><div class="v">2128 · 571</div><div class="l">testes aprovados</div><div class="s">backend (35 saltados) · frontend</div></div>
<div class="card kpi"><div class="v">352 kB</div><div class="l">maior chunk</div><div class="s">limite 500 kB; antes 530 kB</div></div>
</div>
<h2>As 6 frentes</h2>
<div class="grid g2">{fronts_html}</div>
<h2>Detalhes</h2>
{acc("Regras de negócio novas ou alteradas", table(["ID", "Regra"], [
    ["RN-01", "Builtin com vehicle_stock e hash divergente não aborta: ressincroniza o hash e registra aviso"],
    ["RN-02", "Cenários importados ou do instrutor mantêm o 422 SCENARIO_CALIBRATION_HASH_MISMATCH"],
    ["RN-03", "Calibrações stock-* são somente leitura pela API pública"],
    ["RN-04", "Quick Tune: VE_nova = VE_atual × (λ_medido / λ_alvo), limite ±25 %, só tabela VE"],
    ["RN-05", "Pacote de upgrades só aceita peças compatíveis com o veículo; incompatível gera 422"],
    ["RN-06", "Etanol de 27 % a 100 %, só em veículo que aceita E27 e E100"],
    ["RN-07", "Carreira: pagamento só com tentativa aprovada; quebra debita o custo do motor; saldo pode ficar negativo"],
    ["RN-08", "Estratégia vvt só nos perfis com controle de came; classic-20t-swap ignora os alvos"]]), True)}
{acc("Novos componentes e onde estão", table(["Componente", "Camada", "Caminho"], [
    ["career", "backend", "backend/src/simremap/career/ (contratos, orders.json, repositório, serviço, router /api/v1/career)"],
    ["upgrades", "backend", "backend/src/simremap/catalog/upgrades.py e GET /api/v1/upgrades"],
    ["fuel_blend", "backend", "backend/src/simremap/physics/fuel_blend.py"],
    ["vvt", "backend", "backend/src/simremap/ecu/strategies/vvt.py e ValveOverlap em physics/fuel.py"],
    ["live-tuning", "frontend", "frontend/src/features/dyno-cockpit/live-tuning/ (LiveTuningPanel, liveCell)"],
    ["workshop", "frontend", "frontend/src/features/workshop/ (StageBuilder, controle de etanol)"],
    ["career (UI)", "frontend", "frontend/src/features/career/ (WorkshopPage, rota /workshop)"]]))}
{acc("Contratos alterados (aditivos)", table(["Contrato", "Tipo", "Mudança"], [
    ["Calibrações", "HTTP", "409 CALIBRATION_STOCK_IMMUTABLE em stock-*"],
    ["Sessões", "HTTP", "upgrades (UpgradePackage) e ethanol_pct (27 a 100 ou null) no POST /api/v1/sessions"],
    ["Upgrades", "HTTP", "GET /api/v1/upgrades com 6 categorias"],
    ["Carreira", "HTTP", "/api/v1/career: perfil, ordens, aceitar, liquidar"],
    ["Telemetria", "WebSocket", "cam_intake_deg, cam_exhaust_deg, cam_*_target_deg, ethanol_pct"],
    ["Cliente REST", "orval", "regenerado com 44 caminhos (antes 39)"]]))}
{acc("Comportamentos da 001 alterados de propósito", "<ul><li>Sessão sem calibration_id aponta para um clone do usuário, não para stock-*.</li><li>EcuProfileDescriptor exige 10 kinds (antes 9).</li><li>BUILTIN_IDS com 7 cenários (antes 3); a taxa de conclusão passa a contar os cenários de defeito.</li><li>Áudio e animação da bancada diferentes por arquitetura.</li><li>Fecho de sessão idempotente (abandono durante a baseline responde 200).</li></ul>")}
{acc("Premissas adotadas no modo autônomo", table(["#", "Dúvida", "Premissa"], [
    ["Q1", "Onde persistir a carreira?", "No banco do backend da estação, sem PII"],
    ["Q2", "O etanol muda com a sessão em andamento?", "Não; fixo na criação da sessão"],
    ["Q3", "E se o núcleo 3D passar de 500 kB?", "Isolar em chunk lazy e registrar a exceção (não foi preciso)"]]))}
{acc("Vigilância de regressão (W298 a W319)", "<p>22 observações sem peso de regressão (âncora greenfield). Destaques: W298 builtin nunca retorna 422 de hash; W301 stock-* imutável; W303 sinal de vvt_ex no overlap; W304 benchmark &lt; 5 % sem upgrades; W313 liquidação idempotente; W318 nenhum chunk &gt; 500 kB.</p>")}
{acc("Pontos de atenção", "<ul><li>Depois do build verde (T060), um agente externo editou <code>DynoCockpitPage.tsx</code> e <code>DynoChart.tsx</code> e introduziu 2 erros TypeScript (<code>h.run.summary</code> possivelmente null). <b>Resolvido na 003</b> (T002).</li><li>O adendo <code>_reversa_sdd/addenda/002-evolucao-comercial.md</code> foi gerado em 18/10 23:32 UTC.</li><li>A 003 alterou comportamentos da 002: áudio por pulsos no lugar dos osciladores por arquitetura e PID de boost do hatch (série 216,3 → 214,7 whp). Ver a <a href='003-rust-audio-qa-total.html'>feature 003</a>.</li></ul>")}
<h2>Como testar</h2>
<ol><li>Suba o ambiente com <code>make dev</code> ou <code>docker compose up</code>.</li><li>Inicie <code>stage1-oem</code> em Cenários: a tentativa abre sem 422.</li><li>Na tela inicial, abra a Oficina de upgrades, marque as peças e ajuste o etanol para 85 %.</li><li>Na bancada, ative a Tela Dividida, segure Espaço e tecle Q na célula que pisca.</li><li>Ligue a Visão Térmica e faça uma puxada.</li><li>Abra Oficina (Carreira), aceite uma ordem e liquide.</li><li>Rode <code>npm --prefix frontend run build</code> e confira os chunks.</li></ol>
<h2>Fontes</h2>
<p class="mono muted" style="font-size:12.5px">_reversa_forward/002-evolucao-comercial/requirements.md · roadmap.md · actions.md · legacy-impact.md · regression-watch.md · data-delta.md · questions.md · investigation.md · interfaces/*.md</p>
"""
write_page("features/002-evolucao-comercial.html", render("feature-002-evolucao-comercial", "Feature 002", f2, AGENT, "feature", base="../"))

# ---------------------------------------------------------------- feature 003
FRONTS3 = [
    ("1", "Motor nativo em Rust", "RF-01 a RF-06",
     "Os kernels de alta frequência da simulação passam para Rust nativo via PyO3, com fallback transparente em Python.",
     ["Crate <code>backend/rust/simremap_rs</code>: PyO3 0.23, ABI3 ≥ 3.12, maturin; submódulos <code>tables</code>, <code>cycle</code> e <code>damage</code>.",
      "Seletor <code>simremap/core/native.py</code>: <code>SIMREMAP_NATIVE=auto|off|on</code>, lido uma vez por processo.",
      "ECU: <code>ecu/native_tables.py</code> avalia as tabelas em lote (<code>TableSet.eval</code>); estratégias boost PID, VVT/overlap, overrun, two-step e flex em <code>tables/strategies.rs</code>.",
      "Física: <code>physics/kernels.py</code> monta <code>CycleKernel</code> (Wiebe, VE, entalpia, EGT) e <code>GasKernel</code> (borboleta, compressor/turbina, eixo do turbo, intercooler); <code>fastmodel.py</code> constrói os contratos do hot path em 1/3 do custo.",
      "Dano: <code>damage/native_bridge.py</code> liga a integral de knock e o dano dos 6 modos em <code>damage.rs</code>.",
      "Resultado: física 2,8× mais rápida, ECU −28 %, dano −84 %, sem <code>worker.overrun</code> no sweep_pull dos 4 veículos."],
     "backend/rust/simremap_rs/src/{tables*,cycle*,damage.rs}, core/native.py, physics/kernels.py, physics/fastmodel.py, ecu/native_tables.py, damage/native_bridge.py"),
    ("2", "Acústica realista", "RF-07 a RF-10",
     "Som mecânico e orgânico no lugar do apito agudo do turbo e dos osciladores puros.",
     ["Cadeia: pulsos de combustão → WaveShaper → passa-baixa dinâmico 180→1400 Hz → ressonadores 90–140 e 280–450 Hz → sub-bass → corte de presença em 1–4 kHz.",
      "Turbo por ruído de banda estreita mais um harmônico discreto; flutter e chirp no alívio (BOV/diverter). Nenhum <code>OscillatorNode</code> senoidal contínuo no spool.",
      "Pops &amp; bangs graves: punch de 90 a 160 Hz, estalo filtrado e decay curto.",
      "4 arquétipos (i4 turbo, i6 turbo, i4 clássico, V8 com compressor) com energia em 1–4 kHz abaixo de 5 % (máximo 2,2 %).",
      "Grafo com detecção de capacidades: sem <code>WaveShaperNode</code> ou <code>ConvolverNode</code>, o nó vira ganho unitário sem exceção."],
     "frontend/src/features/dyno-cockpit/audio/ (AudioEngine, EngineSynth, graph, voices, archetypes, waveforms, spectrum)"),
    ("3", "QA total", "RF-11 a RF-16",
     "Tipos limpos e verificação funcional de todas as telas e fluxos, com cada bug corrigido coberto por teste.",
     ["Os 2 erros TS da <code>DynoCockpitPage.tsx</code> corrigidos (T002); <code>tsc</code> limpo.",
      "<code>make type</code> (<code>mypy --strict src tests</code>) com 0 erros em 440 arquivos: <code>__init__.py</code> nos testes e configuração do mypy.",
      "<code>backend/tests/qa/</code>: sessão livre, encerramento, retomada, upgrades, etanol, 4 tipos de puxada, autópsia, restauração, swap e base setup via API.",
      "Os 7 cenários iniciam, rodam baseline e são aprovados com acerto real (<code>test_scenarios_approvable.py</code>).",
      "As 7 ordens da carreira são aceitas, executadas e liquidadas com pagamento (<code>test_career_orders.py</code>).",
      "9 correções de QA no frontend (tela inicial, cenários, carreira, bancada, Live Tuning, atalhos)."],
     "backend/tests/qa/, backend/pyproject.toml, frontend/src/app/homeApi.ts, features/scenarios/*, features/career/*"),
    ("4", "E2E e entrega", "RF-17 e RF-18",
     "Fluxos novos cobertos de ponta a ponta, build de produção e documentação.",
     ["8 specs Playwright novos: <code>career-workshop</code>, <code>stage-builder-flex</code>, <code>defect-scenarios</code>, <code>live-tuning</code>, <code>audio</code>, <code>native-engine</code>, <code>ecu-workspace</code>, <code>bench-controls</code>.",
      "E2E em <code>SIMREMAP_E2E_LOCAL=1</code> (backend próprio com dados temporários) e <code>SIMREMAP_E2E_NATIVE</code> para o motor nativo.",
      "24+ testes Playwright aprovados; live-tuning e native-engine 4/4.",
      "<code>npm run build</code> sem erros e <code>frontend/dist</code> atualizado (T028).",
      "Este mini-site atualizado (T029)."],
     "frontend/e2e/*.spec.ts, frontend/e2e/helpers.ts, frontend/playwright.config.ts, frontend/dist/, _reversa_docs/"),
]
fronts3_html = "".join(
    f'<div class="card front"><h3>Frente {n} · {esc(t)} <span class="badge n3">{rf}</span></h3><p>{esc(sm)}</p>'
    f'<ul>{"".join(f"<li>{b}</li>" for b in bl)}</ul><p class="mono muted" style="font-size:12px">{esc(files)}</p></div>'
    for n, t, rf, sm, bl, files in FRONTS3)
FX = [
    ("FX1", "T031", "Sessão, worker e API", [
        "A sessão expõe a calibração ativa (<code>active_calibration_id/version</code>) depois de aplicar, swap ou base setup; a UI do editor usa a ativa.",
        "Seeds sorteadas ≤ 2^53−1, seguras para JavaScript.",
        "<code>native_enabled</code> e <code>native_version</code> em <code>/api/v1/version</code>.",
        "Arrefecimento do <code>multi_pull</code> sem overrun (3,9–11,5 % → 0 %): o worker só conta acima de <code>dt × wall_budget_ticks</code>.",
        "<code>engine/health</code> em sessão encerrada responde 409 <code>SESSION_CLOSED</code>; cliente orval regenerado."],
     "dyno/contracts.py, dyno/session.py, dyno/runner.py, core/worker/loop.py, api/health.py, damage/router.py, ecu-tuning/workspaceStore.ts"),
    ("FX2", "T032", "ECU", [
        "B1: dTPS/dt pela mediana de 3 amostras; o enriquecimento de aceleração deixa de disparar com ruído do TPS.",
        "B2: o 1.º aplicar compara com a versão carregada (<code>initial_calibration_version</code>); <code>changed_tables</code> deixa de vir vazio.",
        "Navegação do OEM-Stage só com os cilindros que o motor tem (itens \"Avanço cil. N\" fora da navegação).",
        "PID de boost OEM do hatch kp 0,1 / ki 0,3 / kd 0: oscilação de torque ±12,3 → ±0,44 N·m; potência de série 216,3 → 214,7 whp."],
     "ecu/runtime.py, ecu/apply.py, ecu/session_port.py, profiles/descriptors/oem_stage.py, catalog/data/vehicles/hatch-20t-gdi/"),
    ("FX3", "T033", "Física", [
        "B4: linha de surge <code>0,30·ṁ_choke·√min(N/N_design,1)</code>, sem surge abaixo de PR 1,05; a BOV usa a pressão pré-borboleta.",
        "Surge a plena carga na série: hatch 17,2 → 1,4 %, coupé 10,6 → 0,6 %, clássico 18,8 → 0,1 %.",
        "B5: oscilação de 7,5 Hz do torque eliminada (com o PID da FX2).",
        "Mesma correção em Python e em Rust, com paridade."],
     "physics/turbo.py, backend/rust/simremap_rs/src/cycle/gas.rs, tests/physics/test_turbo.py"),
]
fx_html = "".join(
    f'<div class="card front"><h3>{fid} · {esc(t)} <span class="badge">{act}</span></h3><ul>{"".join(f"<li>{b}</li>" for b in bl)}</ul>'
    f'<p class="mono muted" style="font-size:12px">{esc(files)}</p></div>' for fid, act, t, bl, files in FX)

f3 = f"""
<p class="muted"><a href="index.html">Features</a> / 003-rust-audio-qa-total</p>
<h1>003 · Motor Nativo em Rust, Acústica Realista, QA Total e E2E</h1>
<p class="lead"><b>Em uma frase:</b> a simulação ganha um caminho nativo opcional em Rust, com paridade bit a bit e fallback Python;
a bancada ganha um som mecânico sem estridência; todas as telas e fluxos passam por QA; e os fluxos novos ficam cobertos por E2E.</p>
<div class="grid g4">
<div class="card kpi"><div class="v">30/33</div><div class="l">ações concluídas</div><div class="s">T029 (este site) em execução; T027 e T030 abertas</div></div>
<div class="card kpi"><div class="v">2,8×</div><div class="l">física mais rápida</div><div class="s">tick do hatch 179 → 107 µs; P99 490 → 345 µs</div></div>
<div class="card kpi"><div class="v">2,2 %</div><div class="l">maior energia em 1–4 kHz</div><div class="s">limite 5 % nos 4 arquétipos</div></div>
<div class="card kpi"><div class="v">7/7 · 7/7</div><div class="l">cenários aprovados · ordens pagas</div><div class="s">com acerto real</div></div>
</div>
<h2>As 4 frentes</h2>
<div class="grid g2">{fronts3_html}</div>
<h2>Correções repassadas pelo QA (fase 6)</h2>
<p class="muted">O QA de fluxos (T020) e o E2E (T024) acharam defeitos fora do escopo original. Cada um virou uma ação nova com teste.</p>
<div class="grid g3">{fx_html}</div>
<h2>Detalhes</h2>
{acc("Desempenho medido", table(["Medida", "Python", "Rust", "Ganho"], [
    ["Física por tick (hatch)", "104,8 µs", "38,0 µs", "2,8×"],
    ["ECU por tick", "27,5 µs", "19,8 µs", "−28 %"],
    ["Dano por tick", "48,0 µs", "7,5 µs", "−84 %"],
    ["Tick médio: hatch", "179 µs", "107 µs", "−40 %"],
    ["Tick médio: coupé", "159 µs", "93 µs", "−42 %"],
    ["Tick médio: clássico", "158 µs", "97 µs", "−39 %"],
    ["Tick médio: V8 muscle", "192 µs", "106 µs", "−45 %"],
    ["P99 do tick (hatch)", "490 µs", "345 µs", "−30 %"],
    ["Janelas com overrun no sweep_pull", "n/d", "0 nos 4 veículos", ""],
    ["Overrun no arrefecimento do multi_pull", "3,9–11,5 %", "0 %", "FX1"]]), True)}
{acc("Qualidade verificada", "<ul>" + "".join(f"<li>{x}</li>" for x in [
    "Frontend: 627 testes vitest aprovados (571 na 002).",
    "Playwright: 24+ aprovados; live-tuning e native-engine 4/4.",
    "Backend: <code>-m accuracy</code> 9/9 com o nativo ligado e desligado (desvio &lt; 5 %); <code>-m e2e</code> 49 aprovados.",
    "<code>mypy --strict src tests</code>: 0 erros em 440 arquivos.",
    "Paridade Python × Rust em <code>tests/native/</code> (tabelas, ciclo, dano), com tolerância relativa máxima de 1e-9.",
    "Os 7 cenários aprovados com acerto real e as 7 ordens da carreira pagas (<code>tests/qa/</code>).",
    "T027 (<code>make check</code> completo com nativo ligado e desligado) segue aberta em <code>actions.md</code>."]) + "</ul>")}
{acc("Regras de negócio novas", table(["ID", "Regra"], [
    ["RN-01", "A extensão nativa é opcional. Sem ela, o comportamento é idêntico ao Python de referência"],
    ["RN-02", "Com a extensão, física, ECU e dano ficam dentro de 1e-9 relativo por tick (bit a bit com a mesma ordem de operações); o determinismo por seed se mantém"],
    ["RN-03", "Nenhum som estridente entre 1 kHz e 4 kHz domina o espectro em nenhum arquétipo"]]))}
{acc("Decisões técnicas", table(["ID", "Decisão"], [
    ["D-01", "maturin como dev dependency; build com <code>maturin develop --release</code>; pacote Python <code>simremap_rs</code> com extensão <code>_native</code>"],
    ["D-02", "Seletor único <code>simremap/core/native.py</code> com <code>SIMREMAP_NATIVE</code> (auto padrão, off, on)"],
    ["D-03", "Granularidade FFI: um kernel por subsistema por tick, com arrays e structs planos"],
    ["D-04", "Paridade: <code>tests/native/</code> compara Python × Rust em entradas aleatórias com seed (rel 1e-9)"],
    ["D-05", "Áudio: pulsos → WaveShaper → lowpass dinâmico → peaking → sub-bass → master com corte em 1–4 kHz; turbo por ruído de banda estreita"],
    ["D-06", "<code>make type</code>: módulos únicos nos testes e correção dos erros"],
    ["D-07", "E2E em <code>SIMREMAP_E2E_LOCAL=1</code>, sem tocar no banco do usuário"],
    ["D-08", "Dockerfile com estágio Rust opcional para o wheel"]]))}
{acc("Premissas adotadas no modo autônomo", table(["#", "Dúvida", "Premissa"], [
    ["Q1", "O Docker compila a extensão Rust?", "Sim, num estágio opcional; se o estágio falhar, a imagem segue válida com o fallback Python"],
    ["Q2", "Paridade bit a bit ou tolerância?", "Tolerância relativa 1e-9 nos testes; determinismo por seed bit a bit; digest de referência regravável por arquitetura com SIMREMAP_WRITE_DIGESTS=1"]]))}
{acc("Contratos alterados (aditivos)", table(["Contrato", "Tipo", "Mudança"], [
    ["Sessões", "HTTP", "<code>active_calibration_id</code> e <code>active_calibration_version</code>; seeds sorteadas ≤ 2^53−1"],
    ["Versão", "HTTP", "<code>native_enabled</code> e <code>native_version</code> em <code>/api/v1/version</code>"],
    ["Saúde do motor", "HTTP", "<code>engine/health</code> em sessão encerrada → 409 <code>SESSION_CLOSED</code>"],
    ["Cliente REST", "orval", "<code>frontend/openapi.json</code> e <code>src/lib/api/generated/</code> regenerados"],
    ["Banco", "SQL", "Sem migração nova"]]))}
{acc("Comportamentos alterados de propósito", "<ul><li><code>calibration_id</code> da sessão segue como calibração inicial; a ativa vive em <code>active_calibration_id</code>.</li><li>O overrun do worker não conta os ticks de arrefecimento acelerado acima do orçamento declarado.</li><li>A calibração de fábrica do hatch mudou os ganhos do PID de boost (série 216,3 → 214,7 whp).</li><li>A tentativa é liquidada antes de expor a avaliação; puxadas e restauros ficam registrados antes do fecho (a carreira cobra o motor quebrado).</li><li>O áudio deixa de usar osciladores puros.</li></ul>")}
{acc("Vigilância de regressão (W320 a W334)", "<p>15 observações sem peso de regressão (âncora greenfield). Destaques: W320 <code>SIMREMAP_NATIVE=off</code> usa só Python; W321 paridade bit a bit; W322 accuracy &lt; 5 % nos dois modos; W323 surge a plena carga &lt; 2 %; W329 overrun só acima do orçamento; W331 oscilação de 7,5 Hz &lt; ±5 N·m; W332 sem seno contínuo no spool e 1–4 kHz &lt; 5 %; W333 7 cenários e 7 ordens; W334 <code>make type</code> limpo.</p>")}
<h2>Como testar</h2>
<ol><li>Compile a extensão com <code>make native</code> (ou rode sem ela: o fallback Python assume).</li>
<li>Confira o modo em <code>GET /api/v1/version</code>: <code>native_enabled</code> deve ser <code>true</code>.</li>
<li>Em <code>backend/</code>, rode <code>SIMREMAP_NATIVE=on uv run pytest tests/native tests/bench</code>. Depois rode <code>SIMREMAP_NATIVE=off make accuracy</code> na raiz.</li>
<li>Na bancada, segure Espaço até 6000 rpm e solte: o turbo deve soprar sem apito e os pops devem ser graves.</li>
<li>Rode <code>make type</code> e <code>make e2e-local</code> (Playwright contra estações locais).</li>
<li>Rode <code>npm --prefix frontend run build</code>.</li></ol>
<h2>Fontes</h2>
<p class="mono muted" style="font-size:12.5px">_reversa_forward/003-rust-audio-qa-total/requirements.md · roadmap.md · questions.md · actions.md · legacy-impact.md · regression-watch.md (W320 a W334) · progress.jsonl · backend/rust/simremap_rs/ · backend/tests/{{native,qa,bench}}/ · frontend/e2e/</p>
"""
write_page("features/003-rust-audio-qa-total.html", render("feature-003-rust-audio-qa-total", "Feature 003", f3, AGENT, "feature", base="../"))

# ---------------------------------------------------------------- deck
SLIDES = [
    ("SimuladorRemap", '<div id="deck-seal" style="width:200px;height:200px;margin:0 auto 20px"></div><p class="lead" style="margin:auto">Simulador e plataforma de treino de remap automotivo em dinamômetro, com física termodinâmica real.</p>'),
    ("Propósito", "<p>Aprender calibração exige carro, dinamômetro e aceitar o risco de quebrar o motor. As ferramentas de ECU não simulam o motor e os jogos não oferecem ECU completa.</p><p><b>O SimuladorRemap</b> une as duas coisas: ECU OEM e standalone sobre um motor 0D/1D que ganha potência ou quebra de forma coerente.</p>"),
    ("Para quem", "<div class='grid g3'><div class='card'><h3>Lucas</h3>Aluno de remap OEM. Stage 1, Stage 2 e pops &amp; bangs sem quebrar motor real.</div><div class='card'><h3>Rodrigo</h3>Preparador em transição para standalone. VE 3D, PID de boost, two-step.</div><div class='card'><h3>Prof. Marcos</h3>Instrutor com turmas de 20 a 50 alunos e um único dinamômetro.</div></div>"),
    ("Arquitetura", "<p>Monólito modular: 12 pacotes Python (FastAPI), 7 features React e, desde a 003, kernels nativos em Rust (PyO3 ABI3) com fallback Python, num container por estação.</p><div class='flow' style='justify-content:center'><span>sensors</span><b>→</b><span>ecu</span><b>→</b><span>physics</span><b>→</b><span>damage</span><b>→</b><span>telemetry</span></div><p><a href='arquitetura.html'>Ver a arquitetura completa</a></p>"),
    ("Módulos", "<p>89 arestas de importação entre pacotes, incluindo as pontes ecu → tables.rs, physics → cycle.rs e damage → damage.rs. <code>core</code> e <code>catalog</code> são os mais importados; <code>profiles</code> depende fortemente de <code>ecu</code>.</p><p><a href='modulos.html'>Ver o grafo de módulos</a></p>"),
    ("Métricas", "<div class='grid g3'><div class='card kpi'><div class='v'>2,8×</div><div class='l'>física com Rust</div></div><div class='card kpi'><div class='v'>627</div><div class='l'>testes frontend</div></div><div class='card kpi'><div class='v'>9/9</div><div class='l'>accuracy, nativo ligado e desligado</div></div></div><p><a href='metricas.html'>Ver o dashboard</a></p>"),
    ("Linha do tempo", "<ul><li>17/10 23:20 UTC: brief, ideation, personas e PRD</li><li>18/10 01:11 a 09:11: código da feature 001 (452 ações)</li><li>18/10 11:03: adendo da 001</li><li>18/10 21:25 a 23:30: feature 002 (62 ações) e documentação visual</li><li>18/10 23:36 a 19/10 01:55: feature 003 (Rust, áudio, QA, E2E)</li></ul><p><a href='timeline.html'>Ver a linha do tempo</a></p>"),
    ("Decisões fundadoras", "<ul><li>Laço físico determinístico em processo dedicado, 1000 Hz</li><li>Tempo só por ticks; SHA-256 em física, dano, datalog e avaliação</li><li>Local-first e zero PII: só nickname</li><li>Nomes genéricos de ECU: OEM-Stage, FT-Pro, M1-Race, HT-Elite</li></ul>"),
    ("Feature destaque: 003", "<p>Quatro frentes: motor nativo em Rust com fallback Python (física 2,8×, ECU −28 %, dano −84 %), acústica sem estridência em 1–4 kHz, QA total (make type limpo, 7 cenários e 7 ordens aprovados) e 8 specs E2E novos.</p><p><a href='features/003-rust-audio-qa-total.html'>Ver a feature 003</a> · <a href='features/002-evolucao-comercial.html'>Ver a 002</a> · <a href='features/001-simulador-remap.html'>Ver a 001</a></p>"),
    ("Próximos passos", "<ol><li>Fechar T027: make check completo com o nativo ligado e desligado.</li><li>Fechar T030: adendo da 003 com /reversa-sync.</li><li>Medir o tick no hardware de referência de 4 núcleos.</li><li>Rodar T091 (smoke do container) com espaço no Docker.</li><li>Rodar /reversa para extrair soul e chronicle e enriquecer este site.</li></ol><p><a href='glossario.html'>Consultar o glossário</a></p>"),
]
slides_html = "".join(f'<section class="slide" data-i="{i}" aria-roledescription="slide" aria-label="{i+1} de {len(SLIDES)}"{" hidden" if i else ""}>'
                      f'<h1>{esc(t)}</h1><div class="slide-body">{b}</div></section>' for i, (t, b) in enumerate(SLIDES))
deck_payload = f"""
<style>
#deck{{background:var(--surface);border:1px solid var(--line);border-radius:14px;min-height:560px;padding:48px 64px;position:relative;text-align:center}}
#deck .slide h1{{font-size:38px;margin-bottom:22px}} #deck .slide-body{{max-width:900px;margin:0 auto;font-size:18px;text-align:left}}
#deck .slide-body .flow{{font-size:15px}} #deck:fullscreen{{display:flex;flex-direction:column;justify-content:center}}
.deck-bar{{display:flex;gap:8px;align-items:center;justify-content:center;margin-top:12px}}
</style>
<div id="deck" tabindex="0" aria-label="Apresentação do projeto">{slides_html}</div>
<div class="deck-bar"><button class="btn" id="prev" aria-label="Slide anterior">← Anterior</button><span id="pos" class="muted"></span>
<button class="btn" id="next" aria-label="Próximo slide">Próximo →</button><button class="btn" id="fs">Tela cheia (F)</button></div>
<p class="muted" style="text-align:center">Use as setas ← e → do teclado e a tecla F para tela cheia.</p>
"""
deck_script = r"""
<script>
(function () {
  var s = document.querySelectorAll(".slide"), i = 0, pos = document.getElementById("pos"), deck = document.getElementById("deck");
  function go(n) { i = Math.max(0, Math.min(s.length - 1, n)); s.forEach(function (x, k) { x.hidden = k !== i; }); pos.textContent = (i + 1) + " / " + s.length; }
  document.getElementById("prev").onclick = function () { go(i - 1); };
  document.getElementById("next").onclick = function () { go(i + 1); };
  document.getElementById("fs").onclick = function () { if (deck.requestFullscreen) deck.requestFullscreen(); };
  document.addEventListener("keydown", function (e) {
    if (e.target.tagName === "INPUT") return;
    if (e.key === "ArrowRight") go(i + 1); else if (e.key === "ArrowLeft") go(i - 1);
    else if (e.key === "f" || e.key === "F") { if (document.fullscreenElement) document.exitFullscreen(); else if (deck.requestFullscreen) deck.requestFullscreen(); }
  });
  var seal = document.getElementById("deck-seal");
  if (seal && window.RV_DATA && window.RV_DATA.sealSvg) seal.innerHTML = window.RV_DATA.sealSvg;
  go(0);
})();
</script>
"""
write_page("deck.html", render("deck", "Deck", deck_payload, AGENT, "deck", scripts=deck_script))

register("storyteller", AGENT, ["glossario.html", "deck.html", "features/index.html",
                                "features/001-simulador-remap.html", "features/002-evolucao-comercial.html",
                                "features/003-rust-audio-qa-total.html"])
print("storyteller ok", len(G), "termos;", len(SLIDES), "slides; 3 features + 11 specs")
