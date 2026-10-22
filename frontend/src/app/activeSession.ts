/**
 * Sessão de simulação ativa da casca (navegação Bancada / ECU / Cenários).
 * A sessão do URL (`/sessions/:sessionId/*`) tem prioridade; fora dela vale a última
 * guardada em `localStorage` (`simremap.activeSessionId`).
 */
import { useEffect, useSyncExternalStore } from "react";
import { matchPath, useLocation } from "react-router-dom";

export const ACTIVE_SESSION_KEY = "simremap.activeSessionId";

const listeners = new Set<() => void>();

function read(): string | null {
  try {
    return localStorage.getItem(ACTIVE_SESSION_KEY);
  } catch {
    return null;
  }
}

export function getActiveSessionId(): string | null {
  return read();
}

export function setActiveSessionId(sessionId: string | null): void {
  try {
    if (sessionId) localStorage.setItem(ACTIVE_SESSION_KEY, sessionId);
    else localStorage.removeItem(ACTIVE_SESSION_KEY);
  } catch {
    /* armazenamento indisponível: a sessão fica só no URL */
  }
  listeners.forEach((fn) => fn());
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  window.addEventListener("storage", fn);
  return () => {
    listeners.delete(fn);
    window.removeEventListener("storage", fn);
  };
}

/** Extrai o `session_id` de um caminho `/sessions/:sessionId/...`. */
export function sessionIdFromPath(pathname: string): string | null {
  const match = matchPath({ path: "/sessions/:sessionId/*" }, pathname);
  return match?.params.sessionId ?? null;
}

export function useActiveSessionId(): string | null {
  const { pathname } = useLocation();
  const fromUrl = sessionIdFromPath(pathname);
  const stored = useSyncExternalStore(subscribe, read, () => null);
  useEffect(() => {
    if (fromUrl && fromUrl !== read()) setActiveSessionId(fromUrl);
  }, [fromUrl]);
  return fromUrl ?? stored;
}
