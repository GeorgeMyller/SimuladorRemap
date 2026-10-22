/**
 * Playwright (D-26; cockpit RNF-01/RNF-06; jornadas T221–T224): testes em `e2e/`.
 *
 * Alvos do servidor:
 * - padrão: o container local em http://127.0.0.1:8000 (mesma imagem de produção); o
 *   `webServer` sobe-o com `docker compose ... up` e espera `/api/v1/health` (reutiliza um
 *   servidor que já responda);
 * - `SIMREMAP_E2E_LOCAL=1`: sem Docker — `vite build` do frontend e duas estações locais do
 *   backend (`python -m simremap.api.serve` do `backend/.venv`, dados em diretórios temporários
 *   vazios): a do instrutor (baseURL, porta `SIMREMAP_E2E_PORT`, padrão 8765) e a do aluno
 *   (`SIMREMAP_E2E_STUDENT_URL`, porta seguinte), usada pela jornada do Prof. Marcos;
 * - `SIMREMAP_E2E_BASE_URL` muda o alvo (ex.: `http://127.0.0.1:5173` com `make dev`);
 * - `SIMREMAP_E2E_NATIVE` (`auto`, `on`, `off`; padrão `auto`) vira `SIMREMAP_NATIVE` nas estações
 *   locais (extensão Rust `simremap_rs`, feature 003); `on` faz a estação falhar sem a extensão;
 * - `SIMREMAP_E2E_NO_SERVER=1` não arranca nada (servidor gerido fora do Playwright, como em
 *   `scripts/e2e_local.sh`).
 *
 * Browsers (RNF-08): Chromium sempre, com viewport de 1366×768 (mínimo da cockpit; o
 * `devices["Desktop Chrome"]` traz 1280×720). Firefox só quando o browser do Playwright está
 * instalado (`npx playwright install firefox`); `SIMREMAP_E2E_FIREFOX=1` força-o e `=0` desliga-o.
 * Execução: `SIMREMAP_E2E_LOCAL=1 npx playwright test`, `make e2e` ou `npm run e2e`.
 */
import { existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, devices, firefox, type PlaywrightTestConfig } from "@playwright/test";

const VIEWPORT = { width: 1366, height: 768 };
const isCI = Boolean(process.env.CI);
const local = process.env.SIMREMAP_E2E_LOCAL === "1";
const manageServer = process.env.SIMREMAP_E2E_NO_SERVER !== "1";

const localPort = Number(process.env.SIMREMAP_E2E_PORT ?? "8765");
const nativeMode = process.env.SIMREMAP_E2E_NATIVE ?? "auto";
const studentPort = localPort + 1;
const baseURL = process.env.SIMREMAP_E2E_BASE_URL ?? (local ? `http://127.0.0.1:${localPort}` : "http://127.0.0.1:8000");
if (local && !process.env.SIMREMAP_E2E_STUDENT_URL) {
  // Lido pelos specs nos workers (herdam o ambiente do processo principal).
  process.env.SIMREMAP_E2E_STUDENT_URL = `http://127.0.0.1:${studentPort}`;
}

function firefoxInstalled(): boolean {
  try {
    return existsSync(firefox.executablePath());
  } catch {
    return false;
  }
}

const firefoxFlag = process.env.SIMREMAP_E2E_FIREFOX;
const withFirefox = firefoxFlag === "1" || (firefoxFlag !== "0" && firefoxInstalled());

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const BACKEND = join(ROOT, "backend");
const DIST = join(ROOT, "frontend", "dist");

type WebServer = Extract<NonNullable<PlaywrightTestConfig["webServer"]>, { command: string }>;

function localStation(name: string, port: number, build: boolean): WebServer {
  const data = join(tmpdir(), `simremap-e2e-${name}-${port}`);
  const env = [
    "SIMREMAP_ENV=dev",
    `SIMREMAP_DATA_DIR='${data}'`,
    `SIMREMAP_STATIC_DIR='${DIST}'`,
    "SIMREMAP_LOG_LEVEL=WARNING",
    `SIMREMAP_NATIVE=${nativeMode}`,
  ].join(" ");
  const serve = `rm -rf '${data}' && mkdir -p '${data}' && cd '${BACKEND}' && ${env} exec .venv/bin/python -m simremap.api.serve --port ${port}`;
  return {
    command: build ? `npx vite build >/dev/null && ${serve}` : serve,
    url: `http://127.0.0.1:${port}/api/v1/health`,
    reuseExistingServer: false,
    timeout: 300_000,
    stdout: "ignore",
    stderr: "pipe",
  };
}

const dockerServer: WebServer = {
  command: "docker compose -f ../compose.yaml -f ../compose.prod.yaml up --build app",
  url: `${baseURL}/api/v1/health`,
  reuseExistingServer: true,
  timeout: 600_000,
  stdout: "ignore",
  stderr: "pipe",
};

function webServer(): PlaywrightTestConfig["webServer"] {
  if (!manageServer) return undefined;
  if (!local) return dockerServer;
  // O build do frontend corre antes da 1.ª estação; a 2.ª serve o mesmo dist.
  return [localStation("instrutor", localPort, true), localStation("aluno", studentPort, false)];
}

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.spec.ts",
  outputDir: "./test-results",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: isCI ? 1 : 0,
  forbidOnly: isCI,
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  use: {
    baseURL,
    locale: "pt-BR",
    viewport: VIEWPORT,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"], viewport: VIEWPORT } },
    ...(withFirefox ? [{ name: "firefox", use: { ...devices["Desktop Firefox"], viewport: VIEWPORT } }] : []),
  ],
  webServer: webServer(),
});
