/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Backend local (uvicorn) em 127.0.0.1:8000. No compose.dev.yaml, defina
// SIMREMAP_BACKEND_URL=http://backend:8000.
const backend = process.env.SIMREMAP_BACKEND_URL ?? "http://127.0.0.1:8000";
const backendWs = backend.replace(/^http/, "ws");

// Saída do build: o FastAPI serve o diretório de SIMREMAP_STATIC_DIR (D-02, RF-15).
// Sem a variável, o build vai para frontend/dist (copiado para /app/static no Dockerfile).
const outDir = process.env.SIMREMAP_STATIC_DIR ?? "dist";

// Chunks de fornecedor (002 D-16, RF-27): nenhum chunk > 500 kB sem subir chunkSizeWarningLimit.
// Vite 8 usa o rolldown: `manualChunks` está obsoleto e puxa as dependências para o mesmo chunk
// (o three.module.js arrastava o three.core.js), por isso os grupos de `codeSplitting` com
// prioridade. O three.js 0.186 publica o núcleo (three.core.js) e o renderizador WebGL
// (three.module.js) em arquivos separados; cada um vira um chunk só carregado pela vista 3D
// (premissa Q3). Grupo de maior prioridade captura primeiro.
const nodeModule = (pattern: string) => new RegExp(`[\\\\/]node_modules[\\\\/]${pattern}`);
const VENDOR_GROUPS = [
  { name: "vendor-three-core", test: nodeModule("three[\\\\/]build[\\\\/]three\\.core\\.js$"), priority: 50 },
  { name: "vendor-three", test: nodeModule("three[\\\\/]"), priority: 40 },
  { name: "vendor-react", test: nodeModule("(react|react-dom|react-router|react-router-dom|scheduler|cookie|set-cookie-parser)[\\\\/]"), priority: 30 },
  { name: "vendor-zod", test: nodeModule("zod[\\\\/]"), priority: 20 },
  { name: "vendor-uplot", test: nodeModule("uplot[\\\\/]"), priority: 10 },
];

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    host: "localhost",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: backend, changeOrigin: false },
      "/ws": { target: backendWs, ws: true, changeOrigin: false },
    },
  },
  build: {
    outDir,
    emptyOutDir: true,
    sourcemap: false,
    target: "es2022",
    rolldownOptions: {
      output: { codeSplitting: { groups: VENDOR_GROUPS } },
    },
  },
  test: {
    environment: "jsdom",
    globals: false,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
    restoreMocks: true,
    // Cobertura v8 (`npm run test:coverage`): ≥ 80 % por feature (cockpit RNF-09, tuning RNF-08,
    // scenarios) e na casca/lib; ≥ 85 % nas operações de tabela da ECU (tuning RNF-08).
    coverage: {
      provider: "v8",
      reporter: ["text-summary", "text", "json-summary", "html"],
      reportsDirectory: "coverage",
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/**/*.test.{ts,tsx}",
        "src/**/test-utils/**",
        "src/**/test-fixtures.ts",
        "src/test/**",
        "src/lib/api/generated/**",
        "src/main.tsx",
        "src/**/*.d.ts",
        // Superfície WebGL do three.js (chunk lazy): sem WebGL no jsdom; coberta pelo Playwright.
        "src/features/ecu-tuning/Table3DSurface.tsx",
      ],
      thresholds: {
        "src/app/**": { statements: 80, branches: 80, functions: 80, lines: 80 },
        "src/lib/**": { statements: 80, branches: 80, functions: 80, lines: 80 },
        "src/features/dyno-cockpit/**": { statements: 80, branches: 80, functions: 80, lines: 80 },
        "src/features/ecu-tuning/**": { statements: 80, branches: 80, functions: 80, lines: 80 },
        "src/features/ecu-tuning/ops/**": { statements: 85, branches: 85, functions: 85, lines: 85 },
        "src/features/scenarios/**": { statements: 80, branches: 80, functions: 80, lines: 80 },
      },
    },
  },
});
