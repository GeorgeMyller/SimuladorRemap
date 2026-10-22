import { useCallback, useEffect, useState } from "react";
import { z } from "zod";

import { apiFetch, ApiProblem } from "@/lib/api/client";

export const versionInfoSchema = z.object({
  app_version: z.string(),
  api_version: z.literal("v1"),
  ws_envelope_version: z.literal(1),
  package_format_version: z.number().int(),
  datalog_format_version: z.number().int(),
  alembic_head: z.string(),
  error_catalog_sha256: z.string(),
  git_sha: z.string().nullish(),
  build_time_utc: z.string().nullish(),
  python_version: z.string(),
});

export type VersionInfo = z.infer<typeof versionInfoSchema>;

export type VersionState =
  | { status: "loading" }
  | { status: "ready"; version: VersionInfo }
  | { status: "error"; code: string; detail: string };

/** 3 tentativas com intervalo de 2 s (platform-foundation, estados da casca). */
export const VERSION_ATTEMPTS = 3;
export const VERSION_RETRY_MS = 2000;

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export function useAppVersion(retryMs: number = VERSION_RETRY_MS): {
  state: VersionState;
  retry: () => void;
} {
  const [state, setState] = useState<VersionState>({ status: "loading" });
  const [round, setRound] = useState(0);

  useEffect(() => {
    let active = true;
    async function load(): Promise<void> {
      let last: ApiProblem | null = null;
      for (let attempt = 1; attempt <= VERSION_ATTEMPTS && active; attempt += 1) {
        try {
          const version = await apiFetch("/version", { schema: versionInfoSchema });
          if (active) setState({ status: "ready", version });
          return;
        } catch (error) {
          last =
            error instanceof ApiProblem
              ? error
              : ApiProblem.synthetic(0, "UNEXPECTED_RESPONSE", "Resposta de versão inválida.");
          if (attempt < VERSION_ATTEMPTS) await sleep(retryMs);
        }
      }
      if (active && last) setState({ status: "error", code: last.code, detail: last.detail });
    }
    void load();
    return () => {
      active = false;
    };
  }, [round, retryMs]);

  const retry = useCallback(() => {
    setState({ status: "loading" });
    setRound((value) => value + 1);
  }, []);

  return { state, retry };
}
