/** Painel "Atalhos" da cockpit (tecla `?`), com ordem de foco lógica (RF-22). */
import { Dialog } from "./Dialog";
import { IMMERSION_SHORTCUTS } from "./messages";

export const SHORTCUTS: readonly { keys: string; action: string }[] = [
  { keys: "Enter (foco nos controles da puxada)", action: "Iniciar puxada" },
  { keys: "Esc", action: "Abortar puxada ativa; fechar diálogo aberto" },
  { keys: "Seta-cima / seta-baixo", action: "Borboleta ±5 % (carga estacionária)" },
  { keys: "Shift + seta", action: "Borboleta ±1 %" },
  { keys: "M", action: "Silenciar / reativar o som" },
  { keys: "U", action: "Abrir o menu de unidades" },
  { keys: "1–4", action: "Selecionar a aba inferior" },
  { keys: "D", action: "Painel de diagnóstico (FPS, superfície, perda de frames)" },
  { keys: "L", action: "Tela Dividida (Live Tuning): bancada e editor da tabela lado a lado" },
  ...IMMERSION_SHORTCUTS,
  { keys: "?", action: "Abrir esta lista de atalhos" },
];

export function ShortcutsDialog({ onClose }: { onClose: () => void }) {
  return (
    <Dialog titleId="shortcuts-title" title="Atalhos de teclado" onClose={onClose}>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-zinc-300">
            <th scope="col" className="py-1 pr-4">
              Tecla
            </th>
            <th scope="col" className="py-1">
              Ação
            </th>
          </tr>
        </thead>
        <tbody>
          {SHORTCUTS.map((s) => (
            <tr key={s.keys} className="border-t border-zinc-700">
              <td className="py-1 pr-4 font-mono text-amber-300">{s.keys}</td>
              <td className="py-1">{s.action}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Dialog>
  );
}
