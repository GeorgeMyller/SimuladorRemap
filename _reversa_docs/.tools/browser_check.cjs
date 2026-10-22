// Carrega cada página via file:// em Chromium headless, sem rede, e coleta erros de JS e de console.
const path = require("path");
const { chromium } = require(process.argv[2]);
const docs = path.resolve(__dirname, "..");
const pages = ["index.html","arquitetura.html","modulos.html","metricas.html","timeline.html","glossario.html","deck.html",
  "features/index.html","features/001-simulador-remap.html","features/002-evolucao-comercial.html","features/003-rust-audio-qa-total.html","topologia.html"];
(async () => {
  const browser = await chromium.launch({ args: ["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"] });
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 1000 }, offline: true });
  const out = [];
  for (const p of pages) {
    const page = await ctx.newPage();
    const errs = [];
    page.on("pageerror", e => errs.push("pageerror: " + e.message));
    page.on("console", m => { if (m.type() === "error") errs.push("console: " + m.text()); });
    page.on("requestfailed", r => errs.push("requestfailed: " + r.url()));
    await page.goto("file://" + path.join(docs, p), { waitUntil: "load" });
    await page.waitForTimeout(p === "modulos.html" ? 3500 : 1800);
    const info = await page.evaluate(() => ({
      rv: !!window.RV_DATA, nav: document.querySelectorAll(".reversa-doc-nav a").length,
      charts: (window.Highcharts && Highcharts.charts.filter(Boolean).length) || 0,
      svgNodes: document.querySelectorAll("#graph circle").length,
      loaderHidden: (document.getElementById("loader") || { style: { display: "none" } }).style.display === "none",
      errorPanels: document.querySelectorAll(".reversa-error-panel").length,
      glossCards: document.querySelectorAll(".concept").length
    }));
    await page.screenshot({ path: path.join(docs, ".logs/shots", p.replace("/", "_") + ".png"), fullPage: p !== "arquitetura.html" });
    out.push({ page: p, ...info, errors: errs });
    await page.close();
  }
  await browser.close();
  console.log(JSON.stringify(out, null, 1));
})();
