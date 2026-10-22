/** Seletor de perfil local: cartões com nickname e papel, troca imediata sem senha (RF-01, RF-02). */
import { useState } from "react";

import { ProfileCreateDialog } from "./ProfileCreateDialog";
import type { PlayerProfile } from "./types";
import { ErrorBox, SkeletonCards } from "./ui";
import { selectProfile, useProfiles } from "./useActiveProfile";

export function RoleBadge({ role }: { role: PlayerProfile["role"] }) {
  return role === "instructor" ? (
    <span className="rounded bg-amber-700 px-1.5 py-0.5 text-xs font-medium text-white">Instrutor</span>
  ) : (
    <span className="rounded bg-zinc-700 px-1.5 py-0.5 text-xs text-zinc-100">Aluno</span>
  );
}

export function ProfilePicker({ onSelected }: { onSelected?: (profile: PlayerProfile) => void }) {
  const { profiles, active, loading, error, reload } = useProfiles();
  const [creating, setCreating] = useState(false);

  function choose(profile: PlayerProfile) {
    selectProfile(profile.profile_id);
    onSelected?.(profile);
  }

  return (
    <section aria-labelledby="profiles-title" className="space-y-3">
      <div className="flex items-center justify-between">
        <h1 id="profiles-title" className="text-xl font-semibold">
          Perfis desta estação
        </h1>
        <button type="button" className="rounded bg-sky-700 px-3 py-1" onClick={() => setCreating(true)}>
          Novo perfil
        </button>
      </div>
      {creating && (
        <ProfileCreateDialog
          onCancel={() => setCreating(false)}
          onCreated={(p) => {
            setCreating(false);
            reload();
            choose(p);
          }}
        />
      )}
      {error !== null && <ErrorBox error={new Error(error)} onRetry={reload} />}
      {loading ? (
        <SkeletonCards />
      ) : profiles.length === 0 ? (
        <p className="text-zinc-400">Ainda sem perfis. Crie o primeiro com «Novo perfil».</p>
      ) : (
        <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {profiles.map((p) => {
            const current = active?.profile_id === p.profile_id;
            return (
              <li key={p.profile_id}>
                <button
                  type="button"
                  aria-pressed={current}
                  onClick={() => choose(p)}
                  className={`flex w-full items-center justify-between rounded border p-3 text-left ${
                    current ? "border-sky-500 bg-sky-950" : "border-zinc-700 bg-zinc-900"
                  }`}
                >
                  <span className="font-medium">{p.nickname}</span>
                  <span className="flex items-center gap-2">
                    <RoleBadge role={p.role} />
                    {current && <span className="text-xs text-sky-300">(ativo)</span>}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
