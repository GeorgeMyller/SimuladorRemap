/** Diálogo de atalhos do editor de ECU (tecla `?`, tuning RF-20; §8 "Atalhos de teclado"). */
import { Dialog } from "../dyno-cockpit/Dialog";

export const ECU_SHORTCUTS: readonly { keys: string; action: string }[] = [
  { keys: "Setas / Shift + setas", action: "Mover a célula ativa / estender a seleção" },
  { keys: "Tab / Shift + Tab", action: "Próxima / anterior célula na linha" },
  { keys: "Home / End (Ctrl/Cmd: início/fim da tabela)", action: "Início / fim da linha" },
  { keys: "PageUp / PageDown", action: "Subir / descer uma página" },
  { keys: "Ctrl/Cmd + A", action: "Selecionar a tabela inteira" },
  { keys: "Enter ou F2 (ou digitar um número)", action: "Editar a célula ativa" },
  { keys: "=", action: "Definir valor na seleção" },
  { keys: "+ / −", action: "Somar / subtrair valor" },
  { keys: "*", action: "Ajuste percentual" },
  { keys: "I / Shift + I", action: "Interpolar linha ou coluna / bloco" },
  { keys: "S", action: "Suavizar a seleção" },
  { keys: "Q", action: "Quick Tune: VE × λ medido / λ alvo na célula ativa ou seleção (±25 %)" },
  { keys: "H / V", action: "Interpolar horizontal (eixo X) / vertical (eixo Y)" },
  { keys: "B", action: "Suavizar bloco 3×3 nas células selecionadas" },
  { keys: "Ctrl/Cmd + C / Ctrl/Cmd + V", action: "Copiar / colar TSV (planilhas)" },
  { keys: "Ctrl/Cmd + Z / Ctrl/Cmd + Shift + Z", action: "Desfazer / refazer" },
  { keys: "Ctrl/Cmd + S", action: "Salvar versão" },
  { keys: "Ctrl/Cmd + Enter", action: "Aplicar à sessão" },
  { keys: "F3", action: "Alternar a vista 3D" },
  { keys: "Esc", action: "Reduzir a seleção à célula ativa; fechar diálogo" },
  { keys: "?", action: "Abrir esta lista de atalhos" },
];

export function ShortcutsDialog({ onClose }: { onClose: () => void }) {
  return (
    <Dialog titleId="ecu-shortcuts-title" title="Atalhos do editor de ECU" onClose={onClose}>
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
          {ECU_SHORTCUTS.map((s) => (
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
