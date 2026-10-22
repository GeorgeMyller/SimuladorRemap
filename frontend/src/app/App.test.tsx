import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ACTIVE_SESSION_KEY } from "./activeSession";
import { App } from "./App";
import type { FeatureFlags } from "./flags";
import { ECU_PROFILES, VEHICLES } from "./test-fixtures";

const version = {
  app_version: "0.1.0",
  api_version: "v1",
  ws_envelope_version: 1,
  package_format_version: 1,
  datalog_format_version: 1,
  alembic_head: "0001_foundation_base",
  error_catalog_sha256: "a".repeat(64),
  git_sha: null,
  build_time_utc: null,
  python_version: "3.12.10",
};

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

/** Servidor falso por URL: versão, catálogo, perfis de ECU e cenários (tela inicial). */
function okVersion(input?: RequestInfo | URL): Response {
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : (input?.url ?? "");
  if (url.includes("/vehicles")) return json({ catalog_version: "1", catalog_sha256: "b".repeat(64), items: VEHICLES });
  if (url.includes("/ecu-profiles")) return json(ECU_PROFILES);
  if (url.includes("/scenarios")) return json([]);
  if (url.includes("/api/v1/profiles")) return json([]);
  return json(version);
}

function renderAt(path: string, flags?: FeatureFlags) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App versionRetryMs={0} {...(flags ? { flags } : {})} />
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  localStorage.clear();
});

describe("App", () => {
  it("mostra carregamento e depois a casca com a versão", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>((input) => Promise.resolve(okVersion(input))));
    renderAt("/");
    expect(screen.getByRole("status")).toHaveTextContent("A iniciar o simulador");
    expect(await screen.findByRole("heading", { name: "Nova sessão" })).toBeInTheDocument();
    expect(screen.getByText("v0.1.0")).toBeInTheDocument();
    expect(await screen.findByRole("radio", { name: /Hatch 2.0 Turbo GDI/ })).toBeChecked();
    expect(screen.getByRole("navigation", { name: "Navegação principal" })).toBeInTheDocument();
  });

  it.each([
    ["/sessions/s1/dyno", "Bancada de dinamômetro"],
    ["/sessions/s1/ecu", "Workspace da ECU"],
    ["/scenarios", "Cenários de treino"],
    ["/rota/inexistente", "Página não encontrada"],
  ])("carrega a rota %s", async (path, title) => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>((input) => Promise.resolve(okVersion(input))));
    renderAt(path);
    expect(await screen.findByRole("heading", { name: title })).toBeInTheDocument();
  });

  it("mostra Servidor indisponível após 3 falhas e permite tentar de novo", async () => {
    const fetchMock = vi.fn<typeof fetch>(() => Promise.reject(new TypeError("offline")));
    vi.stubGlobal("fetch", fetchMock);
    renderAt("/");
    expect(await screen.findByText("Servidor indisponível")).toBeInTheDocument();
    expect(screen.getByText("NETWORK_ERROR")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(3);
    fetchMock.mockClear();

    fetchMock.mockImplementation((input) => Promise.resolve(okVersion(input)));
    await userEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByRole("heading", { name: "Nova sessão" })).toBeInTheDocument();
  });

  it("sem sessão ativa a navegação não mostra Bancada nem ECU", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>((input) => Promise.resolve(okVersion(input))));
    renderAt("/rota/inexistente");
    const nav = await screen.findByRole("navigation", { name: "Navegação principal" });
    expect(within(nav).queryByRole("link", { name: "Bancada" })).not.toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: "ECU" })).not.toBeInTheDocument();
  });

  it("usa a sessão do URL na navegação e guarda-a como ativa", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>((input) => Promise.resolve(okVersion(input))));
    renderAt("/sessions/abc123/ecu");
    const nav = await screen.findByRole("navigation", { name: "Navegação principal" });
    expect(within(nav).getByRole("link", { name: "Bancada" })).toHaveAttribute("href", "/sessions/abc123/dyno");
    expect(within(nav).getByRole("link", { name: "ECU" })).toHaveAttribute("href", "/sessions/abc123/ecu");
    expect(within(nav).getByRole("link", { name: "Cenários" })).toHaveAttribute("href", "/scenarios");
    expect(localStorage.getItem(ACTIVE_SESSION_KEY)).toBe("abc123");
  });

  it("fora da sessão a navegação usa a última sessão ativa guardada", async () => {
    localStorage.setItem(ACTIVE_SESSION_KEY, "s-guardada");
    vi.stubGlobal("fetch", vi.fn<typeof fetch>((input) => Promise.resolve(okVersion(input))));
    renderAt("/scenarios");
    const nav = await screen.findByRole("navigation", { name: "Navegação principal" });
    expect(within(nav).getByRole("link", { name: "Bancada" })).toHaveAttribute("href", "/sessions/s-guardada/dyno");
  });

  it.each([
    ["VITE_FEATURE_DYNO_COCKPIT", "/sessions/s1/dyno", "Bancada"],
    ["VITE_FEATURE_ECU_TUNING", "/sessions/s1/ecu", "ECU"],
  ])("com %s=false a rota cai na NotFoundPage e some da navegação", async (flag, path, link) => {
    vi.stubEnv(flag, "false");
    vi.stubGlobal("fetch", vi.fn<typeof fetch>((input) => Promise.resolve(okVersion(input))));
    renderAt(path);
    expect(await screen.findByRole("heading", { name: "Página não encontrada" })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Navegação principal" });
    expect(within(nav).queryByRole("link", { name: link })).not.toBeInTheDocument();
  });

  it("o atalho /profiles abre os perfis dos cenários", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>((input) => Promise.resolve(okVersion(input))));
    renderAt("/profiles");
    expect(await screen.findByRole("heading", { name: "Perfis desta estação" })).toBeInTheDocument();
  });

  it("o atalho /instructor abre o painel do instrutor (exige perfil Instrutor)", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>((input) => Promise.resolve(okVersion(input))));
    renderAt("/instructor");
    expect(await screen.findByText(/O painel do instrutor exige um perfil/)).toBeInTheDocument();
  });
});
