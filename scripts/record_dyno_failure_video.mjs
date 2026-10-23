import { createRequire } from "node:module";
import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { generateDynoSoundtrack } from "./generate_dyno_audio.mjs";

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
  console.log("Preparando calibracao errada (ponto excessivo +10 graus e pressao 290 kPa)...");
  const cloneRes = await fetch(`${BASE_URL}/api/v1/calibrations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      vehicle_id: vehicleId,
      profile_id: profileId,
      source: "clone",
      clone_from_id: stockId,
      metadata: { name: "Remap Agressivo Errado (Over-advanced)" }
    })
  });
  const cal = await cloneRes.json();
  const tables = cal.tables;

  // Exagera ponto de ignição (+10 graus) e pressão
  const ig = tables.ignition_base;
  ig.values = ig.values.map(row => row.map(v => v + 10));

  const p = tables.oem_pressure_target;
  p.values = p.values.map(row => row.map(v => (v >= 140 ? 290 : v)));

  for (const name of ["torque_request", "torque_limit", "torque_limit_gear"]) {
    if (tables[name]) {
      const t = tables[name];
      t.values = t.dims === 3 ? t.values.map(row => row.map(v => 1.5 * v)) : t.values.map(v => 1.5 * v);
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
      metadata: { ...cal.metadata, name: "Remap Errado", change_summary: "Ponto +10 graus e 290 kPa" }
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

  console.log("2. Inicializando Chromium em Full HD (1920x1080)...");
  const browser = await chromium.launch({
    headless: true,
    args: ["--no-sandbox", "--disable-setuid-sandbox"]
  });

  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    recordVideo: {
      dir: VIDEOS_DIR,
      size: { width: 1920, height: 1080 }
    }
  });

  const page = await context.newPage();
  const startTime = Date.now();
  let failTimestampSec = 39.0;

  try {
    console.log("3. Abrindo Bancada do Dinamometro (Cockpit Full HD)...");
    await page.goto(`${BASE_URL}/sessions/${sessionId}/dyno`, { waitUntil: "networkidle" });
    await sleep(3000);

    // ==========================================
    // ETAPA 1: PUXADA OEM LIMPA (~20 segundos)
    // ==========================================
    console.log("4. Iniciando Puxada 1 (OEM / Fábrica - 20 segundos)...");
    const startBtn = page.getByRole("button", { name: "Iniciar" });
    await startBtn.waitFor({ state: "visible", timeout: 15000 });
    await startBtn.click();

    console.log("Acelerando no rolo: acompanhando RPM e curva de potencia OEM...");
    await sleep(3500);

    // Aguarda o botão Iniciar voltar a ficar ativo (fim da puxada 1)
    await page.waitForFunction(() => {
      const btns = Array.from(document.querySelectorAll("button"));
      const b = btns.find((el) => el.textContent && el.textContent.trim() === "Iniciar");
      return b && !b.disabled;
    }, { timeout: 60000 });

    console.log("Puxada 1 concluida com sucesso! Exibindo potencia OEM (250 cv / 35 kgfm)...");
    await sleep(4000); // completa ~21 segundos de vídeo até aqui

    // ==========================================
    // ETAPA 2: TUNAGEM SIMPLES NA ECU (~8 segundos)
    // ==========================================
    console.log("5. Entrando no Workspace da ECU para ajuste...");
    await page.goto(`${BASE_URL}/sessions/${sessionId}/ecu`, { waitUntil: "networkidle" });
    await sleep(2500);

    // Aplica a calibração com ponto excessivo (+10°)
    console.log("Aplicando calibracao com avanco de ignicao excessivo (+10 graus)...");
    await fetch(`${BASE_URL}/api/v1/sessions/${sessionId}/calibration`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ calibration_id: brokenCalibrationId, profile_options: { auto_fix_checksum: true } })
    });

    // Recarrega a tela da ECU para mostrar a nova calibração com os números exagerados
    await page.reload({ waitUntil: "networkidle" });
    await sleep(3500);

    // ==========================================
    // ETAPA 3: PUXADA 2 - O MOTOR QUEBRA!
    // ==========================================
    console.log("6. Retornando ao Dinamometro para a segunda puxada...");
    await page.goto(`${BASE_URL}/sessions/${sessionId}/dyno`, { waitUntil: "networkidle" });
    await sleep(2500);

    console.log("7. Iniciando Puxada 2 com a calibracao errada...");
    const startBtn2 = page.getByRole("button", { name: "Iniciar" });
    await startBtn2.waitFor({ state: "visible", timeout: 15000 });
    await startBtn2.click();

    console.log("Motor subindo giro... aguardando detonacao e quebra...");
    
    // Aguarda status virar 'motor destruído' ou surgir o laudo
    const failDeadline = Date.now() + 45000;
    let failed = false;
    while (Date.now() < failDeadline) {
      const statusText = await page.getByTestId("run-status").textContent().catch(() => "");
      if (statusText && statusText.toLowerCase().includes("motor destruído")) {
        failed = true;
        failTimestampSec = (Date.now() - startTime) / 1000;
        console.log(`💥 MOTOR DESTRUIDO aos ${failTimestampSec.toFixed(1)} segundos de video!`);
        break;
      }
      await sleep(500);
    }

    // Se o dialog do Laudo Forense não abrir sozinho, clica em 'Ver laudo'
    await sleep(2000);
    const dialog = page.getByRole("dialog");
    const viewReportBtn = page.getByRole("button", { name: "Ver laudo" });

    if (!(await dialog.isVisible())) {
      if (await viewReportBtn.isVisible()) {
        console.log("Abrindo laudo forense...");
        await viewReportBtn.click();
      }
    }

    console.log("8. Exibindo Laudo Forense de Quebra (Pistao / Biela destruidos por detonacao)...");
    await sleep(8000); // 8 segundos focados no laudo forense e diagrama do motor danificado!

    console.log("Gravacao da jornada concluida com sucesso!");
  } finally {
    const totalVideoSec = Math.ceil((Date.now() - startTime) / 1000);
    console.log(`Duracao total do video: ${totalVideoSec}s. Instante da quebra: ${failTimestampSec.toFixed(1)}s.`);

    const videoObj = page.video();
    await page.close();
    await context.close();
    await browser.close();

    if (videoObj) {
      const rawPath = await videoObj.path();
      console.log(`Video bruto gravado em: ${rawPath}`);
      const finalWebm = path.join(VIDEOS_DIR, "dyno_engine_break_demo.webm");
      const finalWav = path.join(VIDEOS_DIR, "dyno_engine_break_sound.wav");
      const finalMp4 = path.join(VIDEOS_DIR, "dyno_engine_break_demo.mp4");
      const posterJpg = path.join(VIDEOS_DIR, "poster_engine_break.jpg");

      fs.copyFileSync(rawPath, finalWebm);

      // Gera áudio perfeitamente sincronizado com os eventos do vídeo
      console.log("Sintetizando trilha de audio dinamica com ronco do motor, turbo, estouro e alarme...");
      generateDynoSoundtrack(finalWav, { totalDuration: totalVideoSec, failTime: failTimestampSec });

      try {
        console.log("Renderizando video final Full HD 1080p com audio via ffmpeg...");
        // Combina o vídeo gravado com o áudio sincronizado
        execSync(
          `ffmpeg -y -i "${finalWebm}" -i "${finalWav}" -c:v libx264 -pix_fmt yuv420p -r 30 -c:a aac -b:a 192k -shortest -movflags +faststart "${finalMp4}"`,
          { stdio: "inherit" }
        );
        console.log(`Video final MP4 com som gerado: ${finalMp4}`);

        // Extrai thumbnail da tela do laudo forense
        const thumbTime = Math.max(1, totalVideoSec - 3);
        execSync(`ffmpeg -y -ss ${thumbTime} -i "${finalMp4}" -vframes 1 -q:v 2 "${posterJpg}"`, { stdio: "inherit" });
        console.log(`Poster da autopsia gerado: ${posterJpg}`);

        // Copia para a apresentação
        const deckVideoDir = path.resolve("apresentacao/decks/simulador-remap-overview/assets/video");
        if (fs.existsSync(deckVideoDir)) {
          fs.copyFileSync(finalMp4, path.join(deckVideoDir, "dyno_engine_break_demo.mp4"));
          fs.copyFileSync(posterJpg, path.join(deckVideoDir, "poster_engine_break.jpg"));
          console.log("Copiado com sucesso para a apresentacao do Mira Animator!");
        }
      } catch (err) {
        console.error("Erro no processamento ffmpeg:", err.message);
      }
    }
  }
}

run().catch((err) => {
  console.error("Erro na execucao:", err);
  process.exit(1);
});
