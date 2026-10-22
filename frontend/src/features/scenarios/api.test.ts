import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiProblem } from "@/lib/api";

import { getActiveProfileId, problemMessage, scenariosApi, setActiveProfileId } from "./api";
import { ACTIVE_PROFILE_KEY } from "./types";

const PROFILE = "11111111-1111-4111-8111-111111111111";

function json(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  localStorage.clear();
  fetchMock = vi.fn(() => Promise.resolve(json([])));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

function lastCall(): { url: string; init: RequestInit } {
  const call = fetchMock.mock.calls.at(-1) as [string, RequestInit];
  return { url: call[0], init: call[1] };
}

describe("scenariosApi", () => {
  it("envia X-Player-Profile-Id do perfil ativo", async () => {
    setActiveProfileId(PROFILE);
    expect(getActiveProfileId()).toBe(PROFILE);
    await scenariosApi.listScenarios("base");
    const { url, init } = lastCall();
    expect(url).toBe("/api/v1/scenarios?kind=base");
    expect(new Headers(init.headers).get("X-Player-Profile-Id")).toBe(PROFILE);
    setActiveProfileId(null);
    expect(localStorage.getItem(ACTIVE_PROFILE_KEY)).toBeNull();
    await scenariosApi.listProfiles();
    expect(new Headers(lastCall().init.headers).has("X-Player-Profile-Id")).toBe(false);
  });

  it("monta os caminhos e métodos dos endpoints E-30 a E-45", async () => {
    setActiveProfileId(PROFILE);
    const calls: [() => Promise<unknown>, string, string][] = [
      [() => scenariosApi.createProfile({ nickname: "abc", role: "student" }), "POST", "/api/v1/profiles"],
      [() => scenariosApi.getScenario("stage1-oem"), "GET", "/api/v1/scenarios/stage1-oem"],
      [() => scenariosApi.getStats("stage1-oem"), "GET", "/api/v1/scenarios/stage1-oem/stats"],
      [() => scenariosApi.startAttempt("stage1-oem"), "POST", "/api/v1/scenarios/stage1-oem/attempts"],
      [() => scenariosApi.listAttempts({ origin: "imported", limit: 50 }), "GET", "/api/v1/attempts?origin=imported&limit=50"],
      [() => scenariosApi.getAttempt("a"), "GET", "/api/v1/attempts/a"],
      [() => scenariosApi.revealHint("a"), "POST", "/api/v1/attempts/a/hints"],
      [() => scenariosApi.abandon("a"), "POST", "/api/v1/attempts/a/abandon"],
      [() => scenariosApi.submit("a", { calibration_id: "c" }), "POST", "/api/v1/attempts/a/submit"],
      [() => scenariosApi.getEvaluation("a", 2), "GET", "/api/v1/attempts/a/evaluation?submission=2"],
      [() => scenariosApi.replay("a"), "POST", "/api/v1/attempts/a/replay"],
      [() => scenariosApi.createScenario({ scenario: {} as never }), "POST", "/api/v1/scenarios"],
    ];
    for (const [fn, method, url] of calls) {
      await fn();
      expect(lastCall().url).toBe(url);
      expect(lastCall().init.method).toBe(method);
    }
  });

  it("importa o ficheiro sem reserializar", async () => {
    const raw = '{"sha256":"x",  "kind":"attempt"}';
    await scenariosApi.importPackage(raw);
    const { init } = lastCall();
    expect(init.body).toBe(raw);
    expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
  });

  it("exporta e lê o nome do Content-Disposition; erro vira ApiProblem", async () => {
    fetchMock.mockResolvedValueOnce(
      json({ sha256: "f" }, 200, { "Content-Disposition": 'attachment; filename="simremap-challenge-x-12345678.simremap.json"' }),
    );
    const file = await scenariosApi.exportPackage({ kind: "challenge", scenario_id: "x", include_full_logs: false });
    expect(file.filename).toBe("simremap-challenge-x-12345678.simremap.json");
    expect(file.content).toBe('{"sha256":"f"}');

    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ type: "urn:x", title: "Não avaliada", status: 409, detail: "sem avaliação", code: "ATTEMPT_NOT_EVALUATED", request_id: "r" }),
        { status: 409, headers: { "Content-Type": "application/problem+json" } },
      ),
    );
    const err = await scenariosApi.exportPackage({ kind: "attempt", attempt_id: "a", include_full_logs: false }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiProblem);
    expect((err as ApiProblem).code).toBe("ATTEMPT_NOT_EVALUATED");
    expect(problemMessage(err).code).toBe("ATTEMPT_NOT_EVALUATED");

    fetchMock.mockResolvedValueOnce(new Response("x", { status: 500 }));
    const other = await scenariosApi.exportPackage({ kind: "attempt", attempt_id: "a", include_full_logs: false }).catch((e: unknown) => e);
    expect((other as ApiProblem).code).toBe("UNEXPECTED_RESPONSE");

    fetchMock.mockRejectedValueOnce(new TypeError("offline"));
    const net = await scenariosApi.exportPackage({ kind: "attempt", attempt_id: "a", include_full_logs: false }).catch((e: unknown) => e);
    expect((net as ApiProblem).code).toBe("NETWORK_ERROR");
    expect(problemMessage(new Error("x"))).toEqual({ code: "INTERNAL_ERROR", text: "x" });
  });
});
