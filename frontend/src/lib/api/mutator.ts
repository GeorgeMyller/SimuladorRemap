import { apiFetch } from "./client";

/** Mutator do orval (D-24): os clientes gerados passam por `apiFetch`. */
export async function orvalFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const { body, ...rest } = init ?? {};
  return apiFetch<T>(url, { ...rest, body: body ?? null });
}

export default orvalFetch;
