import type { z } from "zod";

import { ApiProblem, PROBLEM_JSON, problemDetailSchema } from "./problem";

export { ApiProblem, isApiProblem, PROBLEM_JSON } from "./problem";
export type { FieldError, ProblemDetail } from "./problem";

/** Prefixo único da API REST (D-33). */
export const API_PREFIX = "/api/v1";

/** Timeout padrão do cliente REST da UI (contracts/rest-api.md §1.3). */
export const DEFAULT_TIMEOUT_MS = 5000;

export interface ApiFetchOptions<T> extends Omit<RequestInit, "body"> {
  /** Corpo serializado como JSON (define `Content-Type: application/json`). */
  json?: unknown;
  /** Corpo bruto (ex.: `FormData`, `Blob`); exclusivo com `json`. */
  body?: BodyInit | null;
  /** Schema zod opcional para validar a resposta. */
  schema?: z.ZodType<T>;
  /** Timeout em ms (padrão 5000; 0 desliga). */
  timeoutMs?: number;
}

/** Monta a URL: caminhos relativos ganham o prefixo `/api/v1`. */
export function apiUrl(path: string): string {
  if (/^https?:\/\//.test(path) || path.startsWith(`${API_PREFIX}/`) || path === API_PREFIX) {
    return path;
  }
  return `${API_PREFIX}${path.startsWith("/") ? path : `/${path}`}`;
}

function linkSignals(timeoutMs: number, external?: AbortSignal | null): {
  signal: AbortSignal;
  timedOut: () => boolean;
  dispose: () => void;
} {
  const controller = new AbortController();
  let expired = false;
  const timer =
    timeoutMs > 0
      ? setTimeout(() => {
          expired = true;
          controller.abort();
        }, timeoutMs)
      : undefined;
  const onAbort = () => controller.abort();
  if (external) {
    if (external.aborted) controller.abort();
    else external.addEventListener("abort", onAbort, { once: true });
  }
  return {
    signal: controller.signal,
    timedOut: () => expired,
    dispose: () => {
      if (timer !== undefined) clearTimeout(timer);
      external?.removeEventListener("abort", onAbort);
    },
  };
}

async function toProblem(response: Response): Promise<ApiProblem> {
  const requestId = response.headers.get("X-Request-ID");
  const contentType = response.headers.get("Content-Type") ?? "";
  if (contentType.startsWith(PROBLEM_JSON)) {
    const parsed = problemDetailSchema.safeParse(await response.json().catch(() => null));
    if (parsed.success) return new ApiProblem(parsed.data);
  }
  return ApiProblem.synthetic(
    response.status,
    response.status >= 500 ? "INTERNAL_ERROR" : "UNEXPECTED_RESPONSE",
    `Resposta inesperada do servidor (HTTP ${response.status}).`,
    requestId,
  );
}

/**
 * Chamada REST à API v1. Envia `Accept: application/json`, lança `ApiProblem`
 * em respostas não-2xx (com `status`, `code`, `title`, `detail`, `requestId`) e
 * devolve `undefined` em 204.
 */
export async function apiFetch<T = unknown>(
  path: string,
  options: ApiFetchOptions<T> = {},
): Promise<T> {
  const { json, schema, timeoutMs = DEFAULT_TIMEOUT_MS, headers, signal, body, ...init } = options;
  const finalHeaders = new Headers(headers);
  if (!finalHeaders.has("Accept")) finalHeaders.set("Accept", "application/json");
  let finalBody: BodyInit | null | undefined = body;
  if (json !== undefined) {
    finalHeaders.set("Content-Type", "application/json");
    finalBody = JSON.stringify(json);
  }

  const link = linkSignals(timeoutMs, signal);
  let response: Response;
  try {
    response = await fetch(apiUrl(path), {
      ...init,
      headers: finalHeaders,
      body: finalBody ?? null,
      signal: link.signal,
    });
  } catch (error) {
    if (link.timedOut()) {
      throw ApiProblem.synthetic(0, "CLIENT_TIMEOUT", "O servidor não respondeu a tempo.");
    }
    if (signal?.aborted) throw error;
    throw ApiProblem.synthetic(0, "NETWORK_ERROR", "Não foi possível contactar o servidor.");
  } finally {
    link.dispose();
  }

  if (!response.ok) throw await toProblem(response);
  if (response.status === 204) return undefined as T;
  const data: unknown = await response.json();
  return schema ? schema.parse(data) : (data as T);
}
