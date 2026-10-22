// Geração de tipos e schemas zod em src/lib/api/generated/ a partir do OpenAPI (D-24; T064).
// Uso: `make api-types` (exporta o openapi.json sem servidor) ou, com o backend em
// 127.0.0.1:8000, `npm run api:generate`. Variáveis: SIMREMAP_OPENAPI (ficheiro ou URL)
// e SIMREMAP_ORVAL_OUT (diretório de saída; padrão src/lib/api/generated).
import { defineConfig } from "orval";

const input = process.env.SIMREMAP_OPENAPI ?? "http://127.0.0.1:8000/openapi.json";
const out = process.env.SIMREMAP_ORVAL_OUT ?? "src/lib/api/generated";

export default defineConfig({
  simremap: {
    input,
    output: {
      mode: "tags-split",
      target: `${out}/endpoints.ts`,
      schemas: `${out}/model`,
      client: "fetch",
      baseUrl: "",
      // O mutator devolve o corpo já validado (apiFetch lança ApiProblem em não-2xx):
      // as funções geradas retornam o tipo da resposta 2xx, não {data, status, headers}.
      override: {
        mutator: { path: "src/lib/api/mutator.ts", name: "orvalFetch" },
        fetch: { includeHttpResponseReturnType: false },
      },
    },
  },
  simremapZod: {
    input,
    output: {
      mode: "tags-split",
      // Subdiretório próprio: em tags-split, `${out}/zod.ts` gravaria `<tag>/<tag>.ts` e
      // sobrescreveria o cliente fetch (paridade T172).
      target: `${out}/zod/zod.ts`,
      client: "zod",
    },
  },
});
