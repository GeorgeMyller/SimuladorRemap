/**
 * Textos pt-BR do editor de ECU (tuning RF-19, T452): avisos didáticos W-01 a W-06 com o link
 * de ajuda de cada um e as mensagens de estado da UI (§8 "Estados da UI").
 */

export type WarningCode = "W-01" | "W-02" | "W-03" | "W-04" | "W-05" | "W-06";

export interface WarningText {
  title: string;
  message: string;
  help: string;
  /** Âncora da ajuda no painel de avisos. */
  helpHref: string;
}

export const WARNING_TEXTS: Record<WarningCode, WarningText> = {
  "W-01": {
    title: "Avanço acima do MBT estimado",
    message: "Avanço acima do MBT estimado: mais avanço aqui não ganha torque e aumenta o risco de knock.",
    help: "O MBT é o menor avanço que dá o torque máximo. Passar 2° dele não aumenta a potência; só eleva a pressão de pico e a chance de detonação. Reduza o avanço até perto do MBT e confirme na bancada.",
    helpHref: "#ajuda-w-01",
  },
  "W-02": {
    title: "Mistura pobre em alta carga",
    message: "Mistura pobre em alta carga: risco de EGT alta e de detonação.",
    help: "Com carga alta (≥ 80 % ou MAP ≥ 1,5 × atmosférica), lambda acima de 0,90 aquece a câmara e o escape. Motores sobrealimentados costumam usar 0,78–0,85 em plena carga.",
    helpHref: "#ajuda-w-02",
  },
  "W-03": {
    title: "Boost acima da capacidade",
    message: "Boost acima da capacidade do turbo/limite do motor.",
    help: "O alvo de pressão passa da razão de pressão de projeto do compressor. O turbo sai da zona eficiente, a temperatura de admissão sobe e o controle pode não alcançar o alvo.",
    helpHref: "#ajuda-w-03",
  },
  "W-04": {
    title: "Limitador acima da rotação segura",
    message: "Limitador acima da rotação máxima segura do motor.",
    help: "O corte de rotação deve ficar abaixo da rotação máxima mecânica do motor (molas de válvula, bielas). Acima dela há risco de flutuação de válvula e quebra.",
    helpHref: "#ajuda-w-04",
  },
  "W-05": {
    title: "Pops & bangs agressivos",
    message: "Pops & bangs agressivos: EGT pré-turbina pode passar do limite.",
    help: "Atraso de ignição maior que 20° ATDC ou janela de corte atrasado maior que 1,5 s queima combustível no coletor. A temperatura antes da turbina sobe rápido.",
    helpHref: "#ajuda-w-05",
  },
  "W-06": {
    title: "Degrau abrupto entre células",
    message: "Degrau abrupto entre células: pode causar instabilidade.",
    help: "Células vizinhas com diferença maior que 15 % (VE) ou 6° (ignição) fazem o motor oscilar ao passar de uma zona para a outra. Use interpolar ou suavizar.",
    helpHref: "#ajuda-w-06",
  },
};

export const MSG = {
  loading: "A carregar o perfil e a calibração…",
  noNavigation: (profileId: string) => `Perfil sem navegação (${profileId}).`,
  emptySection: "Nenhuma tabela nesta secção",
  orphanItem: "não disponível nesta calibração",
  noCalibration: "Sessão sem calibração.",
  createFromBase: "Criar calibração a partir da base do perfil",
  saved: (v: number) => `gravado (revisão ${v})`,
  saving: "a gravar",
  notSaved: "não gravado",
  conflict: "conflito",
  applied: (v: number) => `revisão ${v} aplicada à sessão`,
  lockedDuringRun: "bloqueada durante a puxada",
  noBenchData: "sem dados da bancada",
  mbtUnavailable: "MBT estimado indisponível",
  clamped: (n: number, lim: string) => `valor limitado a ${lim} (${n} ${n === 1 ? "célula" : "células"})`,
  pasteIgnored: (n: number) => `${n} ${n === 1 ? "célula ignorada" : "células ignoradas"}`,
  pasteNothing: "Colagem inválida: 0 células gravadas.",
  interpHint: "selecione ≥ 2 células numa linha/coluna",
  draftRestored: "Rascunho local restaurado (alterações ainda não gravadas).",
  draftCorrupt: "Rascunho local corrompido: descartado e recarregado do servidor.",
  swapDuringRun: "aborte ou aguarde o fim da puxada",
  compatMode: "modo compatível",
  readOnly: "Calibração só leitura",
  stockReadOnly: "Calibração de série (somente leitura): use \"Clonar e editar\" para criar a sua cópia.",
  stockImmutable: "A calibração de série não pode ser alterada. Clone-a para editar.",
  cloneAndEdit: "Clonar e editar",
  cloning: "A clonar a calibração…",
  cloned: (name: string) => `Cópia "${name}" criada e aplicada à sessão: a edição está liberada.`,
  quickTuneVeOnly: "Quick Tune só atua na tabela VE",
  quickTuneNoLambda: "Quick Tune precisa de λ medido e λ alvo da bancada (sem dados de lambda).",
  quickTuneNoCells: "Quick Tune: nenhuma célula para corrigir.",
} as const;
