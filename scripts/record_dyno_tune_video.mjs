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
  console.log("1. Criando sessao limpa...");
  // Limpa sessoes ativas se houver
  let res = await fetch(`${BASE_URL}/api/v1/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ vehicle_id: "hatch-20t-gdi", profile_id: "oem-stage" })
  });

  if (res.status === 409) {
    const data = await res.json();
    for (const sid of data.active_session_ids || []) {
      console.log(`Limpando sessao antiga: ${sid}`);
      await fetch(`${BASE_URL}/api/v1/sessions/${sid}`, { method: "DELETE" });
    }
    res = await fetch(`${BASE_URL}/api/v1/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ vehicle_id: "hatch-20t-gdi", profile_id: "oem-stage" })
    });
  }

  const session = await res.json();
  console.log(`Sessao criada com sucesso: ${session.session_id}`);
  return session.session_id;
}

async function run() {
  if (!fs.existsSync(VIDEOS_DIR)) {
    fs.mkdirSync(VIDEOS_DIR, { recursive: true });
  }

  const sessionId = await createFreshSession();

  console.log("2. Inicializando navegador com gravacao de video...");
  const browser = await chromium.launch({
    headless: true,
    args: ["--no-sandbox", "--disable-setuid-sandbox"]
  });

  const context = await browser.newContext({
    viewport: { width: 1366, height: 768 },
    recordVideo: {
      dir: VIDEOS_DIR,
      size: { width: 1366, height: 768 }
    }
  });

  const page = await context.newPage();

  try {
    console.log("3. Abrindo Bancada de Dinamometro (Cockpit)...");
    await page.goto(`${BASE_URL}/sessions/${sessionId}/dyno`, { waitUntil: "networkidle" });
    await sleep(2500);

    console.log("4. Iniciando Puxada 1 (OEM / Stock)...");
    const startBtn = page.getByRole("button", { name: "Iniciar" });
    await startBtn.waitFor({ state: "visible", timeout: 15000 });
    await startBtn.click();

    console.log("Aguardando puxada OEM em curso...");
    await sleep(4000);

    // Aguarda o status voltar a disponivel (termino da puxada)
    await page.waitForFunction(() => {
      const btns = Array.from(document.querySelectorAll("button"));
      const b = btns.find((el) => el.textContent && el.textContent.trim() === "Iniciar");
      return b && !b.disabled;
    }, { timeout: 60000 });

    console.log("Puxada 1 concluida! Exibindo curvas de potencia e torque OEM...");
    await sleep(3500);

    console.log("5. Navegando para o Workspace da ECU...");
    await page.goto(`${BASE_URL}/sessions/${sessionId}/ecu`, { waitUntil: "networkidle" });
    await sleep(2500);

    // Se houver banner de calibração stock, clona para edição
    const cloneBtn = page.getByRole("button", { name: "Clonar e editar" });
    if (await cloneBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      console.log("Clonando mapa original para criar versao customizada de preparacao...");
      await cloneBtn.click();
      await sleep(2000);
    }

    // Seleciona modo de IA: Race
    const selectMode = page.getByRole("combobox", { name: "Modo de agressividade da IA" });
    if (await selectMode.isVisible({ timeout: 2000 }).catch(() => false)) {
      console.log("Selecionando Modo Race (Max. Potencia)...");
      await selectMode.selectOption("race");
      await sleep(1000);
    }

    // Clica em Tunar com IA
    console.log("6. Acionando 'Tunar com IA' (LAYA.ai)...");
    const aiBtn = page.getByRole("button", { name: /Tunar com IA/i });
    await aiBtn.waitFor({ state: "visible", timeout: 5000 });
    await aiBtn.click();

    console.log("Aguardando inferencia LAYA.ai otimizar celulas de VE e Ignicao...");
    await sleep(3500);

    // Clica em Aplicar à Sessão
    console.log("7. Aplicando nova calibracao a sessao viva...");
    const applyBtn = page.getByRole("button", { name: "Aplicar à sessão" });
    if (await applyBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await applyBtn.click();
      await sleep(1000);
      const confirmBtn = page.getByRole("button", { name: "Confirmar" });
      if (await confirmBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
        await confirmBtn.click();
      }
      await sleep(2000);
    }

    console.log("8. Retornando a Bancada do Dinamometro...");
    await page.goto(`${BASE_URL}/sessions/${sessionId}/dyno`, { waitUntil: "networkidle" });
    await sleep(2500);

    console.log("9. Iniciando Puxada 2 (Motor Tunado com LAYA.ai)...");
    const startBtn2 = page.getByRole("button", { name: "Iniciar" });
    await startBtn2.waitFor({ state: "visible", timeout: 15000 });
    await startBtn2.click();

    console.log("Aguardando puxada Remap em curso...");
    await sleep(4000);

    await page.waitForFunction(() => {
      const btns = Array.from(document.querySelectorAll("button"));
      const b = btns.find((el) => el.textContent && el.textContent.trim() === "Iniciar");
      return b && !b.disabled;
    }, { timeout: 60000 });

    console.log("Puxada 2 concluida! Exibindo comparacao antes x depois (OEM vs Remap)...");
    await sleep(5000);

    console.log("Gravacao finalizada!");
  } finally {
    const videoObj = page.video();
    await page.close();
    await context.close();
    await browser.close();

    if (videoObj) {
      const rawPath = await videoObj.path();
      console.log(`Video gravado em: ${rawPath}`);
      const finalWebm = path.join(VIDEOS_DIR, "dyno_tune_comparison.webm");
      const finalMp4 = path.join(VIDEOS_DIR, "dyno_tune_comparison.mp4");

      fs.copyFileSync(rawPath, finalWebm);
      console.log(`Copiado para: ${finalWebm}`);

      try {
        console.log("Convertendo para MP4 via ffmpeg...");
        execSync(`ffmpeg -y -i "${finalWebm}" -c:v libx264 -pix_fmt yuv420p -r 30 -movflags +faststart "${finalMp4}"`, { stdio: "inherit" });
        console.log(`Video MP4 gerado com sucesso: ${finalMp4}`);
      } catch (err) {
        console.error("Erro ao converter com ffmpeg:", err.message);
      }
    }
  }
}

run().catch((err) => {
  console.error("Falha no script de gravacao:", err);
  process.exit(1);
});
