/**
 * Navegação do perfil (tuning RF-02, EC-09, EC-10): árvore gerada só de
 * `EcuProfileDescriptor.navigation` (secções e itens que apontam para `table_id` ou `strategy`).
 * Nenhum layout por `profile_id`: rótulos, ordem e agrupamento vêm do descritor. Pesquisa por nome.
 */
import { useId, useMemo, useState } from "react";

import { MSG } from "./messages";
import type { EcuProfileDescriptor, NavItem } from "./types";

export interface ProfileNavigatorProps {
  descriptor: EcuProfileDescriptor;
  activeItemId: string | null;
  onSelect: (item: NavItem) => void;
  /** Item com alvo na calibração ativa (EC-10). Padrão: todos disponíveis. */
  isAvailable?: (item: NavItem) => boolean;
  /** Tabelas bloqueadas agora (cadeado, RF-17). */
  isLocked?: (item: NavItem) => boolean;
}

const KIND_LABEL: Record<NavItem["kind"], string> = {
  table: "Tabela",
  strategy: "Estratégia",
  base_setup: "Configuração base",
  info: "Informação",
};

function normalize(s: string): string {
  return s.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();
}

export function ProfileNavigator({ descriptor, activeItemId, onSelect, isAvailable = () => true, isLocked = () => false }: ProfileNavigatorProps) {
  const [query, setQuery] = useState("");
  const searchId = useId();
  const sections = useMemo(() => {
    const q = normalize(query.trim());
    return descriptor.navigation
      .map((s) => ({ ...s, items: q ? s.items.filter((i) => normalize(i.label).includes(q) || normalize(i.target_id).includes(q)) : s.items }))
      .filter((s) => s.items.length > 0);
  }, [descriptor.navigation, query]);

  if (descriptor.navigation.length === 0) {
    return (
      <p role="alert" className="p-2 text-sm text-red-300">
        {MSG.noNavigation(descriptor.profile_id)}
      </p>
    );
  }

  return (
    <nav aria-label={`Navegação do perfil ${descriptor.name}`} className="flex h-full flex-col gap-2 text-sm" style={{ borderTop: `3px solid ${descriptor.accent_color}` }}>
      <div className="px-2 pt-2">
        <p className="font-semibold text-zinc-100" data-testid="profile-name">
          {descriptor.name}
        </p>
        <label htmlFor={searchId} className="mt-2 block text-xs text-zinc-400">
          Pesquisar tabela
        </label>
        <input
          id={searchId}
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="mt-1 w-full rounded border border-zinc-600 bg-zinc-950 px-2 py-1 text-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-400"
        />
      </div>
      <ul aria-label="Secções" className="flex-1 overflow-auto px-1 pb-2">
        {sections.map((section) => (
          <li key={section.id} className="mb-2">
            <h3 id={`nav-sec-${section.id}`} className="block px-1 py-1 text-xs font-semibold uppercase tracking-wide text-zinc-400">{section.label}</h3>
            <ul aria-labelledby={`nav-sec-${section.id}`}>
              {section.items.map((item) => {
                const available = isAvailable(item);
                const locked = available && isLocked(item);
                const active = item.id === activeItemId;
                return (
                  <li key={item.id}>
                    <button
                      type="button"
                      disabled={!available}
                      onClick={() => onSelect(item)}
                      data-nav-item={item.id}
                      title={available ? KIND_LABEL[item.kind] : MSG.orphanItem}
                      aria-current={active ? "page" : undefined}
                      className={`flex w-full items-center justify-between gap-2 rounded px-2 py-1 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-400 ${
                        active ? "bg-zinc-700 text-white" : "text-zinc-200 hover:bg-zinc-800"
                      } disabled:cursor-not-allowed disabled:text-zinc-500`}
                    >
                      <span>
                        {item.label}
                        {item.requires_package === "race" && <span className="ml-1 text-xs text-zinc-400">(pacote race)</span>}
                        {!available && <span className="block text-xs text-zinc-400">{MSG.orphanItem}</span>}
                      </span>
                      {locked && <LockIcon />}
                    </button>
                  </li>
                );
              })}
            </ul>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export function LockIcon({ label = "cadeado" }: { label?: string }) {
  return (
    <svg role="img" aria-label={label} viewBox="0 0 16 16" width="14" height="14" className="shrink-0 fill-amber-300">
      <path d="M4 7V5a4 4 0 0 1 8 0v2h1v8H3V7h1Zm2 0h4V5a2 2 0 1 0-4 0v2Z" />
    </svg>
  );
}
