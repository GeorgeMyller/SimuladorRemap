import { afterEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { ApiProblem, apiFetch, apiUrl, isApiProblem } from "./client";

function jsonResponse(body: unknown, init: ResponseInit & { contentType?: string } = {}): Response {
  const { contentType = "application/json", ...rest } = init;
  return new Response(JSON.stringify(body), {
    status: 200,
    ...rest,
    headers: { "Content-Type": contentType, ...(rest.headers ?? {}) },
  });
}

function mockFetch(response: Response | Error) {
  const fn = vi.fn<typeof fetch>(() =>
    response instanceof Error ? Promise.reject(response) : Promise.resolve(response),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("apiUrl", () => {
  it("prefixa /api/v1 em caminhos relativos", () => {
    expect(apiUrl("/vehicles")).toBe("/api/v1/vehicles");
    expect(apiUrl("vehicles")).toBe("/api/v1/vehicles");
    expect(apiUrl("/api/v1/health")).toBe("/api/v1/health");
  });
});

describe("apiFetch", () => {
  it("envia Accept json e devolve o corpo", async () => {
    const fetchMock = mockFetch(jsonResponse({ status: "ok" }));
    await expect(apiFetch<{ status: string }>("/health")).resolves.toEqual({ status: "ok" });
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe("/api/v1/health");
    expect(new Headers(init?.headers).get("Accept")).toBe("application/json");
  });

  it("serializa json e valida a resposta com schema", async () => {
    const fetchMock = mockFetch(jsonResponse({ id: "a" }, { status: 201 }));
    const result = await apiFetch("/things", {
      method: "POST",
      json: { name: "x" },
      schema: z.object({ id: z.string() }),
    });
    expect(result).toEqual({ id: "a" });
    const init = fetchMock.mock.calls[0]?.[1];
    expect(init?.body).toBe('{"name":"x"}');
    expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
  });

  it("devolve undefined em 204", async () => {
    mockFetch(new Response(null, { status: 204 }));
    await expect(apiFetch("/sessions/x", { method: "DELETE" })).resolves.toBeUndefined();
  });

  it("lança ApiProblem a partir de application/problem+json", async () => {
    mockFetch(
      jsonResponse(
        {
          type: "urn:simremap:problem:table-value-out-of-range",
          title: "Valor fora do limite da tabela",
          status: 422,
          detail: "A célula (4, 9) vale 151,0 e o máximo é 150,0.",
          code: "TABLE_VALUE_OUT_OF_RANGE",
          request_id: "rid-42",
          instance: "/api/v1/calibrations/c1/tables/ve",
          table_id: "ve",
          row: 4,
        },
        { status: 422, contentType: "application/problem+json" },
      ),
    );
    const error: unknown = await apiFetch("/calibrations/c1/tables/ve").catch((e: unknown) => e);
    expect(isApiProblem(error)).toBe(true);
    const problem = error as ApiProblem;
    expect(problem.status).toBe(422);
    expect(problem.code).toBe("TABLE_VALUE_OUT_OF_RANGE");
    expect(problem.title).toBe("Valor fora do limite da tabela");
    expect(problem.detail).toContain("151,0");
    expect(problem.requestId).toBe("rid-42");
    expect(problem.extra).toEqual({ table_id: "ve", row: 4 });
  });

  it("gera ApiProblem sintético para erro sem problem+json", async () => {
    mockFetch(
      new Response("boom", { status: 502, headers: { "X-Request-ID": "gw-1" } }),
    );
    const problem = (await apiFetch("/x").catch((e: unknown) => e)) as ApiProblem;
    expect(problem).toBeInstanceOf(ApiProblem);
    expect(problem.status).toBe(502);
    expect(problem.code).toBe("INTERNAL_ERROR");
    expect(problem.requestId).toBe("gw-1");
  });

  it("converte falha de rede em NETWORK_ERROR", async () => {
    mockFetch(new TypeError("Failed to fetch"));
    const problem = (await apiFetch("/x").catch((e: unknown) => e)) as ApiProblem;
    expect(problem.code).toBe("NETWORK_ERROR");
  });

  it("aborta após o timeout com CLIENT_TIMEOUT", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(
        (_url, init) =>
          new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () => reject(new DOMException("abort", "AbortError")));
          }),
      ),
    );
    const pending = apiFetch("/lento", { timeoutMs: 50 }).catch((e: unknown) => e);
    await vi.advanceTimersByTimeAsync(60);
    const problem = (await pending) as ApiProblem;
    expect(problem.code).toBe("CLIENT_TIMEOUT");
  });
});
