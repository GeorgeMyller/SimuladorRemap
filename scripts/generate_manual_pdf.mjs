/**
 * Script para converter o manual docx em um PDF profissional, elegante e formatado para A4,
 * com escrita limpa, sem metadocumentação desnecessária e sem referências a normas de estilo.
 */
import fs from 'fs';
import path from 'path';
import { execSync } from 'child_process';
import { createRequire } from 'module';

const require = createRequire(import.meta.url);
const { chromium } = require('../frontend/node_modules/playwright');

const rootDir = process.cwd();
const docxPath = path.join(rootDir, 'docs/Manual-do-Utilizador-SimuladorRemap.docx');
const outputPdfPath = path.join(rootDir, 'docs/Manual-do-Usuario-SimuladorRemap.pdf');
const outputPdfAliasPath = path.join(rootDir, 'docs/Manual-do-Utilizador-SimuladorRemap.pdf');

console.log('1. Convertendo DOCX com imagens embutidas via pandoc...');
let html = execSync(`pandoc "${docxPath}" --embed-resources --standalone -t html`, {
  maxBuffer: 64 * 1024 * 1024,
  encoding: 'utf8'
});

console.log('2. Limpando metadados, removendo Capítulo 0 e referências a ASD-STE100...');

// Remover estilos padrão do pandoc
html = html.replace(/<style>[\s\S]*?<\/style>/i, '');

// Remover o Capítulo 0 ("0. Como ler este manual") por completo
html = html.replace(/<h1[^>]*id=\"como-ler-este-manual\"[^>]*>[\s\S]*?(?=<h1[^>]*id=\"o-sistema\")/i, '');

// Remover menções residuais à norma ASD-STE100
html = html.replace(/Escrita controlada ASD-STE100 adaptada ao português ·\s*/gi, '');
html = html.replace(/ASD-STE100/gi, '');

// Ajustes terminológicos para pt-BR
html = html
  .replace(/\butilizador\b/gi, (m) => (m[0] === 'U' ? 'Usuário' : 'usuário'))
  .replace(/\butilizadores\b/gi, (m) => (m[0] === 'U' ? 'Usuários' : 'usuários'))
  .replace(/\bficheiro\b/gi, (m) => (m[0] === 'F' ? 'Arquivo' : 'arquivo'))
  .replace(/\bficheiros\b/gi, (m) => (m[0] === 'F' ? 'Arquivos' : 'arquivos'))
  .replace(/\bsecção\b/gi, (m) => (m[0] === 'S' ? 'Seção' : 'seção'))
  .replace(/\bsecções\b/gi, (m) => (m[0] === 'S' ? 'Seções' : 'seções'))
  .replace(/\bpartilhada\b/gi, 'compartilhada')
  .replace(/\bdetetou\b/gi, 'detectou')
  .replace(/\bplaneie\b/gi, 'planeje')
  .replace(/\bpercentagem\b/gi, 'porcentagem');

// Capa técnica profissional sem referência a ASD-STE100
const coverHtml = `
<div class="cover-page">
  <div class="cover-top-badge">MANUAL TÉCNICO OFICIAL</div>
  <div class="cover-hero">
    <h1 class="cover-title">SimuladorRemap</h1>
    <h2 class="cover-subtitle">Manual do Usuário — Aluno e Instrutor</h2>
    <p class="cover-tagline">
      Guia completo de calibração de ECU em dinamômetro virtual com física termodinâmica 0D/1D,
      cenários práticos com avaliação objetiva e gestão de turmas.
    </p>
  </div>
  <div class="cover-meta-grid">
    <div class="cover-meta-card">
      <span class="meta-label">Versão do Sistema</span>
      <span class="meta-value">v0.1.0</span>
    </div>
    <div class="cover-meta-card">
      <span class="meta-label">Edição</span>
      <span class="meta-value">1ª Edição — Outubro de 2026</span>
    </div>
    <div class="cover-meta-card">
      <span class="meta-label">Tipo de Documento</span>
      <span class="meta-value">Manual de Operação e Instrução</span>
    </div>
    <div class="cover-meta-card">
      <span class="meta-label">Público-Alvo</span>
      <span class="meta-value">Alunos, Preparadores e Instrutores</span>
    </div>
  </div>
</div>
`;

// Substituir o primeiro H1 e subtítulo pela capa estruturada
html = html.replace(/<h1[^>]*>Manual do SimuladorRemap<\/h1>\s*<p>Manual do utilizador[^<]*<\/p>/i, coverHtml);

// Estilizar callouts (Advertência, Cuidado, Nota)
html = html.replace(/<p><strong>Advertência<\/strong><\/p>\s*<p>([\s\S]*?)<\/p>/gi, 
  '<div class="callout callout-warning"><div class="callout-header"><span class="callout-icon">⚠️</span> <strong class="callout-title">Advertência</strong></div><div class="callout-body"><p>$1</p></div></div>');

html = html.replace(/<p><strong>Cuidado<\/strong><\/p>\s*<p>([\s\S]*?)<\/p>/gi, 
  '<div class="callout callout-caution"><div class="callout-header"><span class="callout-icon">⚡</span> <strong class="callout-title">Cuidado</strong></div><div class="callout-body"><p>$1</p></div></div>');

html = html.replace(/<p><strong>Nota<\/strong><\/p>\s*<p>([\s\S]*?)<\/p>/gi, 
  '<div class="callout callout-note"><div class="callout-header"><span class="callout-icon">ℹ️</span> <strong class="callout-title">Nota</strong></div><div class="callout-body"><p>$1</p></div></div>');

// Injetar folha de estilo de alta precisão gráfica para impressão / PDF
const customCss = `
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

  @page {
    size: A4 portrait;
    margin: 22mm 16mm 22mm 16mm;
  }

  * {
    box-sizing: border-box;
  }

  body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 10pt;
    line-height: 1.55;
    color: #1e293b;
    background-color: #ffffff;
    margin: 0;
    padding: 0;
  }

  /* Capa Profissional */
  .cover-page {
    page-break-after: always;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    min-height: 90vh;
    padding: 40px 10px 20px 10px;
  }

  .cover-top-badge {
    align-self: flex-start;
    background: #0f172a;
    color: #38bdf8;
    font-size: 8pt;
    font-weight: 700;
    letter-spacing: 1.5px;
    padding: 6px 14px;
    border-radius: 4px;
    border: 1px solid #1e293b;
  }

  .cover-hero {
    margin-top: 60px;
    margin-bottom: 60px;
  }

  .cover-title {
    font-size: 34pt !important;
    font-weight: 800;
    color: #0f172a !important;
    letter-spacing: -0.5px;
    margin: 0 0 10px 0 !important;
    border: none !important;
    page-break-before: avoid !important;
  }

  .cover-subtitle {
    font-size: 18pt;
    font-weight: 600;
    color: #f59e0b;
    margin: 0 0 24px 0;
  }

  .cover-tagline {
    font-size: 11.5pt;
    color: #475569;
    max-width: 600px;
    line-height: 1.6;
    margin: 0;
  }

  .cover-meta-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 16px;
    padding-top: 24px;
    border-top: 1px solid #e2e8f0;
  }

  .cover-meta-card {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 12px 16px;
    display: flex;
    flex-direction: column;
  }

  .meta-label {
    font-size: 7.5pt;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: #64748b;
    font-weight: 600;
    margin-bottom: 4px;
  }

  .meta-value {
    font-size: 9.5pt;
    color: #0f172a;
    font-weight: 600;
  }

  /* Títulos e Quebras de Página */
  h1 {
    font-size: 18pt;
    font-weight: 700;
    color: #0f172a;
    page-break-before: always;
    border-bottom: 2px solid #0f172a;
    padding-bottom: 8px;
    margin-top: 0;
    margin-bottom: 16px;
  }

  h1#índice, #índice h1 {
    page-break-before: avoid;
  }

  h2 {
    font-size: 13pt;
    font-weight: 600;
    color: #1e293b;
    margin-top: 22px;
    margin-bottom: 10px;
    page-break-after: avoid;
    break-after: avoid;
    border-left: 3px solid #f59e0b;
    padding-left: 8px;
  }

  h3 {
    font-size: 11pt;
    font-weight: 600;
    color: #334155;
    margin-top: 16px;
    margin-bottom: 8px;
    page-break-after: avoid;
    break-after: avoid;
  }

  p {
    margin-top: 0;
    margin-bottom: 9px;
    text-align: justify;
  }

  /* Listas */
  ol, ul {
    margin-top: 4px;
    margin-bottom: 12px;
    padding-left: 22px;
  }

  li {
    margin-bottom: 4px;
  }

  /* Tabelas */
  table {
    width: 100% !important;
    border-collapse: collapse;
    margin: 14px 0 18px 0;
    page-break-inside: avoid;
    break-inside: avoid;
    font-size: 8.5pt;
  }

  thead th {
    background-color: #0f172a !important;
    color: #f8fafc !important;
    font-weight: 600;
    padding: 8px 10px;
    text-align: left;
    border: 1px solid #0f172a;
  }

  tbody td {
    padding: 6px 10px;
    border: 1px solid #cbd5e1;
    vertical-align: top;
  }

  tbody tr:nth-child(even) td {
    background-color: #f8fafc;
  }

  /* Figuras e Imagens */
  figure {
    margin: 16px 0;
    page-break-inside: avoid;
    break-inside: avoid;
    text-align: center;
  }

  figure img {
    max-width: 92%;
    max-height: 440px;
    object-fit: contain;
    border-radius: 6px;
    border: 1px solid #cbd5e1;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.08);
  }

  figcaption {
    font-size: 8pt;
    color: #64748b;
    margin-top: 6px;
    font-style: italic;
    text-align: center;
  }

  /* Callouts */
  .callout {
    margin: 12px 0 14px 0;
    padding: 10px 14px;
    border-radius: 6px;
    page-break-inside: avoid;
    break-inside: avoid;
  }

  .callout-header {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 4px;
  }

  .callout-icon {
    font-size: 11pt;
  }

  .callout-title {
    font-size: 9.5pt;
    font-weight: 700;
  }

  .callout-body p {
    margin: 0;
    font-size: 9pt;
  }

  .callout-warning {
    background-color: #fef2f2;
    border: 1px solid #fecaca;
    border-left: 4px solid #ef4444;
  }
  .callout-warning .callout-title {
    color: #991b1b;
  }

  .callout-caution {
    background-color: #fffbeb;
    border: 1px solid #fde68a;
    border-left: 4px solid #f59e0b;
  }
  .callout-caution .callout-title {
    color: #92400e;
  }

  .callout-note {
    background-color: #f0f9ff;
    border: 1px solid #bae6fd;
    border-left: 4px solid #0284c7;
  }
  .callout-note .callout-title {
    color: #075985;
  }

  code {
    font-family: 'JetBrains Mono', monospace;
    font-size: 8.5pt;
    background-color: #f1f5f9;
    padding: 2px 5px;
    border-radius: 4px;
    border: 1px solid #e2e8f0;
    color: #0f172a;
  }
</style>
`;

html = html.replace('</head>', `${customCss}\n</head>`);

console.log('3. Renderizando PDF com Playwright...');
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();

await page.setContent(html, { waitUntil: 'load', timeout: 60000 });
await page.waitForTimeout(2000);

console.log('4. Exportando PDF formatado em A4...');
await page.pdf({
  path: outputPdfPath,
  format: 'A4',
  printBackground: true,
  displayHeaderFooter: true,
  headerTemplate: `
    <div style="width: 100%; font-size: 7.5pt; color: #94a3b8; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; display: flex; justify-content: space-between; padding: 0 16mm; border-bottom: 1px solid #f1f5f9; padding-bottom: 4px;">
      <span>SimuladorRemap — Manual do Usuário v0.1.0</span>
      <span>Engenharia Automotiva & Calibração de ECU</span>
    </div>
  `,
  footerTemplate: `
    <div style="width: 100%; font-size: 7.5pt; color: #64748b; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; display: flex; justify-content: space-between; padding: 0 16mm; border-top: 1px solid #e2e8f0; padding-top: 4px;">
      <span>SimuladorRemap — Dinamômetro Virtual</span>
      <span>Página <span class="pageNumber"></span> de <span class="totalPages"></span></span>
    </div>
  `,
  margin: {
    top: '20mm',
    bottom: '20mm',
    left: '16mm',
    right: '16mm'
  }
});

fs.copyFileSync(outputPdfPath, outputPdfAliasPath);

await browser.close();
console.log('✅ PDF gerado com sucesso em:');
console.log(' -', outputPdfPath);
console.log(' -', outputPdfAliasPath);
