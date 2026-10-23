import { createRequire } from "node:module";
import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const require = createRequire(import.meta.url);
const playwrightPath = path.resolve("frontend/node_modules/playwright");
const { chromium } = fs.existsSync(playwrightPath) ? require(playwrightPath) : await import("playwright");

const BASE_URL = "http://localhost:8000";
const ROOT_DIR = process.cwd().endsWith("frontend") ? path.resolve("..") : path.resolve(".");
const VIDEOS_DIR = path.join(ROOT_DIR, "docs/videos");

async function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function createFreshSession() {
  console.log("1. Criando sessao limpa para o teste...");
  let res = await fetch(`${BASE_URL}/api/v1/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ vehicle_id: "hatch-20t-gdi", profile_id: "oem-stage", sim_hz: 1000 })
  });

  if (res.status === 409) {
    const data = await res.json();
    for (const sid of data.active_session_ids || []) {
      console.log(`Limpando sessao anterior: ${sid}`);
      await fetch(`${BASE_URL}/api/v1/sessions/${sid}`, { method: "DELETE" });
    }
    res = await fetch(`${BASE_URL}/api/v1/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ vehicle_id: "hatch-20t-gdi", profile_id: "oem-stage", sim_hz: 1000 })
    });
  }

  const session = await res.json();
  console.log(`Sessao criada: ${session.session_id}`);
  return { sessionId: session.session_id, stockId: session.active_calibration_id };
}

async function prepareBrokenCalibration(vehicleId, profileId, stockId) {
  console.log("Preparando calibracao com avanco excessivo (+10 graus e 290 kPa de pressao)...");
  const cloneRes = await fetch(`${BASE_URL}/api/v1/calibrations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      vehicle_id: vehicleId,
      profile_id: profileId,
      source: "clone",
      clone_from_id: stockId,
      metadata: { name: "Mapa Errado (Avanço Excessivo)" }
    })
  });
  const cal = await cloneRes.json();
  const tables = cal.tables;

  // Adiciona +10 graus de avanço de ignição e pressão 290 kPa
  const ig = tables.ignition_base;
  ig.values = ig.values.map((row) => row.map((v) => v + 10));

  const p = tables.oem_pressure_target;
  p.values = p.values.map((row) => row.map((v) => (v >= 140 ? 290 : v)));

  for (const name of ["torque_request", "torque_limit", "torque_limit_gear"]) {
    if (tables[name]) {
      const t = tables[name];
      t.values = t.dims === 3 ? t.values.map((row) => row.map((v) => 1.5 * v)) : t.values.map((v) => 1.5 * v);
    }
  }

  await fetch(`${BASE_URL}/api/v1/calibrations/${cal.calibration_id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      base_version: cal.version,
      fuel_model: cal.fuel_model,
      tables,
      strategies: cal.strategies,
      profile_params: cal.profile_params,
      metadata: { ...cal.metadata, name: "Mapa Errado", change_summary: "Ponto +10 graus e 290 kPa" }
    })
  });

  return cal.calibration_id;
}

async function run() {
  if (!fs.existsSync(VIDEOS_DIR)) {
    fs.mkdirSync(VIDEOS_DIR, { recursive: true });
  }

  const { sessionId, stockId } = await createFreshSession();
  const brokenCalibrationId = await prepareBrokenCalibration("hatch-20t-gdi", "oem-stage", stockId);

  console.log("2. Inicializando Chromium Full HD (1920x1080) com captura do audio nativo...");
  const browser = await chromium.launch({
    headless: true,
    args: ["--no-sandbox", "--disable-setuid-sandbox", "--autoplay-policy=no-user-gesture-required"]
  });

  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    recordVideo: {
      dir: VIDEOS_DIR,
      size: { width: 1920, height: 1080 }
    }
  });

  const page = await context.newPage();

  // Injeta script para capturar 100% do áudio nativo sintetizado pelo AudioEngine via MediaStream
  await page.addInitScript(() => {
    window.__recordedAudioChunks = [];
    const OrigAudioContext = window.AudioContext || window.webkitAudioContext;

    window.AudioContext = class extends OrigAudioContext {
      constructor(...args) {
        super(...args);
        window.__audioCtx = this;
        const streamDest = this.createMediaStreamDestination();
        this.__streamDest = streamDest;

        const origConnect = AudioNode.prototype.connect;
        AudioNode.prototype.connect = function (dest, ...rest) {
          if (dest === this.context.destination && this.context.__streamDest) {
            try {
              origConnect.call(this, this.context.__streamDest);
            } catch (e) {}
          }
          return origConnect.call(this, dest, ...rest);
        };

        try {
          const rec = new MediaRecorder(streamDest.stream, {
            mimeType: "audio/webm;codecs=opus",
            audioBitsPerSecond: 192000
          });
          window.__audioRecorder = rec;
          rec.ondataavailable = (e) => {
            if (e.data && e.data.size > 0) {
              window.__recordedAudioChunks.push(e.data);
            }
          };
          rec.start(100);
        } catch (err) {
          console.error("Falha ao inicializar MediaRecorder de audio:", err);
        }
      }
    };
  });

  try {
    console.log("3. Abrindo Bancada do Dinamometro (Cockpit Full HD)...");
    await page.goto(`${BASE_URL}/sessions/${sessionId}/dyno`, { waitUntil: "networkidle" });
    await sleep(2500);

    // Ativa o áudio nativo na interface
    const enableSoundBtn = page.getByRole("button", { name: "Ativar som" });
    if (await enableSoundBtn.isVisible({ timeout: 4000 }).catch(() => false)) {
      console.log("Clicando em 'Ativar som' para liberar o sintetizador de audio do motor...");
      await enableSoundBtn.click();
      await sleep(1500);
    }

    // Garante que o AudioContext está em execução
    await page.evaluate(() => {
      if (window.__audioCtx && window.__audioCtx.state === "suspended") {
        window.__audioCtx.resume();
      }
    });

    // ==========================================
    // ETAPA 1: PUXADA 1 - OEM LIMPA (~20s)
    // ==========================================
    console.log("4. Iniciando Puxada 1 (OEM de Fábrica - ~20 segundos)...");
    const startBtn = page.getByRole("button", { name: "Iniciar" });
    await startBtn.waitFor({ state: "visible", timeout: 15000 });
    await startBtn.click();

    console.log("Gravando som nativo da aceleracao no rolo (1200 a 6500 RPM)...");
    await sleep(3500);

    // Aguarda o término da puxada 1
    await page.waitForFunction(() => {
      const btns = Array.from(document.querySelectorAll("button"));
      const b = btns.find((el) => el.textContent && el.textContent.trim() === "Iniciar");
      return b && !b.disabled;
    }, { timeout: 60000 });

    console.log("Puxada 1 concluida! Exibindo potencia e torque OEM (250 cv / 35 kgfm)...");
    await sleep(4000); // completa os ~20 segundos de foco na primeira puxada

    // ==========================================
    // ETAPA 2: LIVE TUNING NA TELA DIVIDIDA
    // ==========================================
    console.log("5. Abrindo Tela Dividida (Live Tuning) no Cockpit...");
    const splitBtn = page.getByRole("button", { name: "Tela Dividida (Live Tuning)" });
    if (await splitBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await splitBtn.click();
    } else {
      await page.keyboard.press("l");
    }
    await sleep(2500);

    // Se houver banner de clonar, clica nele
    const cloneBtn = page.getByRole("button", { name: "Clonar e editar" });
    if (await cloneBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      console.log("Clonando calibração original...");
      await cloneBtn.click();
      await sleep(1500);
    }

    // Aplica o mapa com ponto excessivo à sessão ativa
    console.log("Aplicando o mapa com avanço excessivo de ponto (+10°)...");
    await fetch(`${BASE_URL}/api/v1/sessions/${sessionId}/calibration`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ calibration_id: brokenCalibrationId, profile_options: { auto_fix_checksum: true } })
    });

    // Aguarda o usuário visualizar o mapa ajustado em tela dividida
    await sleep(5000);

    // ==========================================
    // ETAPA 3: PUXADA 2 - DETONAÇÃO E QUEBRA!
    // ==========================================
    console.log("6. Iniciando Puxada 2 (Ponto excessivo - A quebra do motor)...");
    const startBtn2 = page.getByRole("button", { name: "Iniciar" });
    await startBtn2.waitFor({ state: "visible", timeout: 15000 });
    await startBtn2.click();

    console.log("Motor subindo giro com ponto excessivo... aguardando quebra e som de breakage()...");

    const failDeadline = Date.now() + 45000;
    while (Date.now() < failDeadline) {
      const statusText = await page.getByTestId("run-status").textContent().catch(() => "");
      if (statusText && statusText.toLowerCase().includes("motor destruído")) {
        console.log("💥 MOTOR DESTRUÍDO! Detonação severa detectada!");
        break;
      }
      await sleep(500);
    }

    await sleep(2000);

    // Garante abertura do Laudo Forense se não abriu sozinho
    const dialog = page.getByRole("dialog");
    const viewReportBtn = page.getByRole("button", { name: "Ver laudo" });
    if (!(await dialog.isVisible())) {
      if (await viewReportBtn.isVisible()) {
        console.log("Abrindo laudo forense...");
        await viewReportBtn.click();
      }
    }

    console.log("7. Exibindo Laudo Forense em tela cheia (Pistão e Biela destruídos por knock)...");
    await sleep(8000); // 8 segundos focados no laudo forense com o diagrama do motor danificado

    console.log("Gravacao da jornada finalizada com sucesso!");
  } finally {
    // Extrai o áudio nativo gravado diretamente da memória do navegador
    console.log("8. Extraindo arquivo de audio nativo gravado...");
    let audioBase64 = null;
    try {
      audioBase64 = await page.evaluate(async () => {
        if (window.__audioRecorder && window.__audioRecorder.state !== "inactive") {
          window.__audioRecorder.stop();
          await new Promise((r) => setTimeout(r, 400));
        }
        const blob = new Blob(window.__recordedAudioChunks, { type: "audio/webm" });
        return new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onloadend = () => {
            const res = reader.result;
            const b64 = typeof res === "string" ? res.split(",")[1] : "";
            resolve(b64);
          };
          reader.onerror = reject;
          reader.readAsDataURL(blob);
        });
      });
    } catch (err) {
      console.error("Falha ao extrair audio nativo:", err.message);
    }

    const videoObj = page.video();
    await page.close();
    await context.close();
    await browser.close();

    if (videoObj) {
      const rawVideoPath = await videoObj.path();
      console.log(`Video bruto gravado em: ${rawVideoPath}`);

      const finalWebm = path.join(VIDEOS_DIR, "dyno_engine_break_demo.webm");
      const nativeAudioWebm = path.join(VIDEOS_DIR, "dyno_engine_break_native_sound.webm");
      const finalMp4 = path.join(VIDEOS_DIR, "dyno_engine_break_demo.mp4");
      const posterJpg = path.join(VIDEOS_DIR, "poster_engine_break.jpg");

      fs.copyFileSync(rawVideoPath, finalWebm);

      if (audioBase64 && audioBase64.length > 100) {
        const audioBuffer = Buffer.from(audioBase64, "base64");
        fs.writeFileSync(nativeAudioWebm, audioBuffer);
        console.log(`Audio nativo original salvo com sucesso (${(audioBuffer.length / 1024).toFixed(1)} KB): ${nativeAudioWebm}`);

        try {
          console.log("Muxing: unindo video gravado e audio nativo original via ffmpeg...");
          execSync(
            `ffmpeg -y -i "${finalWebm}" -i "${nativeAudioWebm}" -c:v libx264 -pix_fmt yuv420p -r 30 -c:a aac -b:a 192k -shortest -movflags +faststart "${finalMp4}"`,
            { stdio: "inherit" }
          );
          console.log(`Video final MP4 com audio original gerado com sucesso: ${finalMp4}`);
        } catch (err) {
          console.error("Erro ao juntar video e audio via ffmpeg:", err.message);
        }
      } else {
        console.warn("Audio nativo nao foi capturado com tamanho suficiente, convertendo apenas video...");
        execSync(
          `ffmpeg -y -i "${finalWebm}" -c:v libx264 -pix_fmt yuv420p -r 30 -movflags +faststart "${finalMp4}"`,
          { stdio: "inherit" }
        );
      }

      // Gera thumbnail da autopsia
      try {
        execSync(`ffmpeg -y -sseof -3 -i "${finalMp4}" -update 1 -q:v 2 "${posterJpg}"`, { stdio: "inherit" });
        console.log(`Poster gerado: ${posterJpg}`);
      } catch (err) {
        console.warn("Aviso ao gerar poster:", err.message);
      }

      // Atualiza apresentação
      const deckVideoDir = path.resolve("apresentacao/decks/simulador-remap-overview/assets/video");
      if (fs.existsSync(deckVideoDir)) {
        fs.copyFileSync(finalMp4, path.join(deckVideoDir, "dyno_engine_break_demo.mp4"));
        if (fs.existsSync(posterJpg)) {
          fs.copyFileSync(posterJpg, path.join(deckVideoDir, "poster_engine_break.jpg"));
        }
        console.log("Copiado com sucesso para apresentacao/!");
      }
    }
  }
}

run().catch((err) => {
  console.error("Erro na execucao:", err);
  process.exit(1);
});
