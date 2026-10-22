/** Criação de perfil local: só nickname e papel (training-scenarios RF-01). */
import { useId, useState, type FormEvent } from "react";

import { useScenariosApi } from "./api";
import { NICKNAME_RE, type PlayerProfile, type Role } from "./types";
import { ErrorBox } from "./ui";

export interface ProfileCreateDialogProps {
  onCreated: (profile: PlayerProfile) => void;
  onCancel: () => void;
}

export function ProfileCreateDialog({ onCreated, onCancel }: ProfileCreateDialogProps) {
  const api = useScenariosApi();
  const titleId = useId();
  const hintId = useId();
  const [nickname, setNickname] = useState("");
  const [role, setRole] = useState<Role>("student");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const valid = NICKNAME_RE.test(nickname);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    setError(null);
    try {
      onCreated(await api.createProfile({ nickname, role }));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div role="dialog" aria-modal="true" aria-labelledby={titleId} className="rounded border border-zinc-700 bg-zinc-900 p-4">
      <h2 id={titleId} className="text-lg font-semibold">
        Novo perfil
      </h2>
      <form className="mt-3 space-y-3" onSubmit={(e) => void submit(e)} noValidate>
        <div>
          <label htmlFor={`${titleId}-nick`} className="block text-sm">
            Nickname
          </label>
          <input
            id={`${titleId}-nick`}
            className="mt-1 w-full rounded border border-zinc-600 bg-zinc-950 px-2 py-1"
            value={nickname}
            maxLength={24}
            autoComplete="off"
            aria-describedby={hintId}
            aria-invalid={nickname.length > 0 && !valid}
            onChange={(e) => setNickname(e.target.value)}
          />
          <p id={hintId} className="mt-1 text-xs text-zinc-400">
            3 a 24 caracteres: letras, números, «-» ou «_». Sem espaços nem «@». Nenhum outro dado pessoal.
          </p>
        </div>
        <fieldset>
          <legend className="text-sm">Papel</legend>
          <label className="mr-4 inline-flex items-center gap-1">
            <input type="radio" name="role" value="student" checked={role === "student"} onChange={() => setRole("student")} />
            Aluno
          </label>
          <label className="inline-flex items-center gap-1">
            <input type="radio" name="role" value="instructor" checked={role === "instructor"} onChange={() => setRole("instructor")} />
            Instrutor
          </label>
        </fieldset>
        {error !== null && <ErrorBox error={error} />}
        <div className="flex gap-2">
          <button type="submit" disabled={!valid || busy} className="rounded bg-sky-700 px-3 py-1 disabled:opacity-50">
            Criar perfil
          </button>
          <button type="button" onClick={onCancel} className="rounded bg-zinc-700 px-3 py-1">
            Cancelar
          </button>
        </div>
      </form>
    </div>
  );
}
