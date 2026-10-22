/** Cliente gerado pelo orval (T433/T443) através do mutator `orvalFetch` e dos schemas zod gerados. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { ZodError } from "zod";

import { ApiProblem } from "@/lib/api";
import { setActiveProfileId } from "@/features/scenarios/api";

import { homeApi } from "./homeApi";
import { ECU_PROFILES, HOME_SCENARIOS, sessionFixture, VEHICLES } from "./test-fixtures";

type Call = { url: string; init: RequestInit };

function server(routes: Record<string, { status?: number; body: unknown; problem?: boolean }>) {
  const calls: Call[] = [];
  const fetchMock = vi.fn<typeof fetch>((input, init) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    calls.push({ url, init: init ?? {} });
    const key = Object.keys(routes).find((k) => url.startsWith(k));
    const route = key ? routes[key]! : { status: 404, body: { code: "NOT_FOUND" }, problem: true };
    return Promise.resolve(
      new Response(JSON.stringify(route.body), {
        status: route.status ?? 200,
        headers: { "Content-Type": route.problem ? "application/problem+json" : "application/json" },
      }),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("homeApi", () => {
  it("lista os veículos com include_drafts=true e valida pelo zod gerado", async () => {
    const calls = server({ "/api/v1/vehicles": { body: { catalog_version: "1", catalog_sha256: "c".repeat(64), items: VEHICLES } } });
    const items = await homeApi.listVehicles();
    expect(items.map((v) => v.vehicle_id)).toEqual(["hatch-20t-gdi", "coupe-30t-i6", "classic-20t-swap", "muscle-v8-sc"]);
    expect(calls[0]!.url).toBe("/api/v1/vehicles?include_drafts=true");
    expect(calls[0]!.init.method).toBe("GET");
  });

  it("rejeita respostas fora do contrato (ZodError)", async () => {
    server({ "/api/v1/vehicles": { body: { items: [] } } });
    await expect(homeApi.listVehicles()).rejects.toBeInstanceOf(ZodError);
  });

  it("lista os perfis de ECU", async () => {
    server({ "/api/v1/ecu-profiles": { body: ECU_PROFILES } });
    expect((await homeApi.listEcuProfiles()).map((p) => p.profile_id)).toEqual(["oem-stage", "ft-pro", "m1-race", "ht-elite"]);
  });

  it("aceita a semente sorteada pelo servidor acima de 2^53 (sessão sem seed)", async () => {
    server({ "/api/v1/sessions": { status: 201, body: { ...sessionFixture(), seed: 2 ** 62 + 12345 } } });
    const session = await homeApi.createSession({ vehicle_id: "hatch-20t-gdi" });
    expect(session.session_id).toBe(sessionFixture().session_id);
    expect(session.seed).toBeGreaterThan(Number.MAX_SAFE_INTEGER);
  });

  it("cria a sessão por POST /api/v1/sessions com corpo JSON", async () => {
    const calls = server({ "/api/v1/sessions": { status: 201, body: sessionFixture() } });
    const session = await homeApi.createSession({ vehicle_id: "hatch-20t-gdi", profile_id: "ft-pro" });
    expect(session.session_id).toBe(sessionFixture().session_id);
    expect(calls[0]!.init.method).toBe("POST");
    expect(JSON.parse(calls[0]!.init.body as string)).toEqual({ vehicle_id: "hatch-20t-gdi", profile_id: "ft-pro" });
  });

  it("propaga o ProblemDetail como ApiProblem", async () => {
    server({
      "/api/v1/sessions": {
        status: 409,
        problem: true,
        body: { type: "urn:simremap:problem:SIM_CAPACITY_EXCEEDED", title: "Capacidade", status: 409, detail: "ocupado", code: "SIM_CAPACITY_EXCEEDED", request_id: "r" },
      },
    });
    const error = await homeApi.createSession({ vehicle_id: "hatch-20t-gdi" }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiProblem);
    expect((error as ApiProblem).code).toBe("SIM_CAPACITY_EXCEEDED");
  });

  it("cenários e tentativas levam o perfil de jogador ativo", async () => {
    setActiveProfileId("p-1");
    const calls = server({
      "/api/v1/scenarios/stage1-oem/attempts": { status: 201, body: { attempt_id: "a-1", session_id: "s-1" } },
      "/api/v1/scenarios": { body: HOME_SCENARIOS },
    });
    expect(await homeApi.listScenarios()).toHaveLength(3);
    expect(await homeApi.startAttempt("stage1-oem")).toEqual({ attempt_id: "a-1", session_id: "s-1" });
    expect(new Headers(calls[1]!.init.headers).get("X-Player-Profile-Id")).toBe("p-1");
  });

  it("tentativa sem session_id devolve null", async () => {
    server({ "/api/v1/scenarios/x/attempts": { status: 201, body: { attempt_id: "a-2" } } });
    expect(await homeApi.startAttempt("x")).toEqual({ attempt_id: "a-2", session_id: null });
  });
});
