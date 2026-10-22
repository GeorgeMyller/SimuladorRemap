import { act, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ACTIVE_SESSION_KEY, getActiveSessionId, sessionIdFromPath, setActiveSessionId, useActiveSessionId } from "./activeSession";

function Probe() {
  return <p data-testid="sid">{useActiveSessionId() ?? "-"}</p>;
}

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("sessão ativa da casca", () => {
  it("extrai o session_id das rotas de sessão", () => {
    expect(sessionIdFromPath("/sessions/abc/dyno")).toBe("abc");
    expect(sessionIdFromPath("/sessions/abc/ecu")).toBe("abc");
    expect(sessionIdFromPath("/scenarios")).toBeNull();
  });

  it("guarda, lê e limpa a sessão ativa", () => {
    setActiveSessionId("s1");
    expect(localStorage.getItem(ACTIVE_SESSION_KEY)).toBe("s1");
    expect(getActiveSessionId()).toBe("s1");
    setActiveSessionId(null);
    expect(getActiveSessionId()).toBeNull();
  });

  it("o hook reage a mudanças na mesma aba", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Probe />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("sid")).toHaveTextContent("-");
    act(() => setActiveSessionId("s2"));
    expect(screen.getByTestId("sid")).toHaveTextContent("s2");
  });

  it("sem localStorage disponível degrada para o URL", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("bloqueado");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("bloqueado");
    });
    expect(getActiveSessionId()).toBeNull();
    expect(() => setActiveSessionId("x")).not.toThrow();
    render(
      <MemoryRouter initialEntries={["/sessions/url-1/dyno"]}>
        <Probe />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("sid")).toHaveTextContent("url-1");
  });
});
