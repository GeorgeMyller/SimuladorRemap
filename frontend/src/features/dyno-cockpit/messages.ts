/** Mensagens pt-BR da cockpit (RF-04, RF-05, RF-12, RF-21; §8 "Estados da UI"). */
import { formatNumber, formatTemperature } from "@/lib/units";

export const MSG = {
  title: "Bancada de dinamômetro",
  evidenceRun: "Evidência",
  attemptPanel: "Progresso da tentativa",
  connecting: "Conectando à bancada",
  empty: "Nenhuma puxada ainda. Escolha um tipo e clique Iniciar.",
  telemetryUnavailable: "telemetria indisponível",
  retry: "Tentar de novo",
  back: "Voltar",
  frameLoss: "perda de frames",
  aborted: "abortada",
  partial: "parcial",
  reconnecting: (n: number, max: number) => `reconectando (${n}/${max})`,
  connected: "conectado",
  closed: "desconectado",
  backendDown: "backend indisponível",
  runInProgress: "Já existe uma puxada em curso",
  engineDestroyed: "Motor destruído",
  viewReport: "Ver laudo",
  restoreEngine: "Restaurar motor",
  reportUnavailable: "laudo indisponível, tentar de novo",
  compatMode: "modo compatível",
  outOfScale: "fora de escala",
  noData: (channel: string) => `sem dados de ${channel}`,
  enableSound: "Ativar som",
  start: "Iniciar",
  abort: "Abortar",
  noReference: "Curvas de referência indisponíveis",
  ready: "pronto",
  throttleHint: "W / S (±5 %) · Shift (±1 %) · segure Espaço",
  thermalView: "Visão Térmica / Raio-X",
  thermalViewOn: "Visão térmica ligada: coletor e turbina coloridos pela EGT",
} as const;

/** Atalhos da trilha de imersão (RF-21, RF-22), listados no diálogo `?`. */
export const IMMERSION_SHORTCUTS: readonly { keys: string; action: string }[] = [
  { keys: "Espaço (segurar)", action: "Acelerador com mola: sobe o pedal até 100 %; soltar fecha para 0 %" },
  { keys: "W / S", action: "Borboleta ±5 % (Shift: ±1 %)" },
  { keys: "T", action: "Ligar / desligar a Visão Térmica / Raio-X do carro no rolo" },
];

export const RUN_TYPE_LABEL = {
  baseline_pull: "Puxada base",
  sweep_pull: "Varredura (sweep)",
  steady_state_hold: "Carga estacionária",
  multi_pull: "Múltiplas puxadas",
} as const;

export const FAILURE_MODE_LABEL: Record<string, string> = {
  knock_damage: "dano por knock",
  pre_ignition: "pré-ignição",
  egt_overtemp: "sobretemperatura de escape",
  rod_failure: "falha de biela",
  piston_failure: "falha de pistão",
  turbo_meltdown: "fusão do turbo",
};

export const KNOCK_CLASS_LABEL = { light: "leve", moderate: "moderado", severe: "severo" } as const;

export const LIMITER_LABEL: Record<string, string> = {
  rev_limiter: "Limitador de rotação",
  two_step: "Two-step",
  overboost_cut: "Corte por sobrepressão",
  antilag_protect: "Proteção do antilag",
  overrun_protect: "Proteção de overrun",
};

export const RUN_STATE_LABEL: Record<string, string> = {
  idle: "em espera",
  arming: "armando",
  running: "em curso",
  coastdown: "desaceleração",
  completed: "concluída",
  aborted: "abortada",
  engine_failed: "motor destruído",
};

/** "Knock severo, cilindro 2, 4,5° de retardo" (RF-21). */
export function knockAlarmText(knockClass: keyof typeof KNOCK_CLASS_LABEL, cylinder: number, retardDeg: number, locale?: string): string {
  const cls = KNOCK_CLASS_LABEL[knockClass];
  return `Knock ${cls}, cilindro ${cylinder}, ${formatNumber(retardDeg, 1, locale)}° de retardo`;
}

export function limiterAlarmText(kind: string, active: boolean, rpm: number, locale?: string): string {
  const label = LIMITER_LABEL[kind] ?? kind;
  return `${label} ${active ? "ativo" : "desativado"} (${formatNumber(rpm, 0, locale)} rpm)`;
}

export function egtAlarmText(egtC: number, limitC: number, locale?: string): string {
  return `EGT alta: ${formatTemperature(egtC, locale)} (limite ${formatTemperature(limitC, locale)})`;
}

export function failureAlarmText(mode: string): string {
  return `${MSG.engineDestroyed}: ${FAILURE_MODE_LABEL[mode] ?? mode}`;
}
