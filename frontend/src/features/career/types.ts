/** Tipos e formatação do Modo Carreira (002 RF-25, RF-26). Valores monetários em centavos de BRL. */
import type { CareerJob, CareerProfile, JobStatus, WorkOrder } from "@/lib/api/generated/model";

import { isApiProblem } from "@/lib/api";

export type { CareerJob, CareerProfile, JobStatus, WorkOrder };

const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });

/** Centavos → "R$ 5.000,00". */
export function formatBrl(cents: number): string {
  return brl.format(cents / 100);
}

/** Centavos com sinal explícito: "+R$ 1.200,00" ou "-R$ 9.000,00". */
export function formatBrlDelta(cents: number): string {
  return `${cents >= 0 ? "+" : "-"}${formatBrl(Math.abs(cents))}`;
}

export function formatSigned(value: number): string {
  return value >= 0 ? `+${value}` : `${value}`;
}

export const JOB_STATUS_LABEL: Record<JobStatus, string> = {
  accepted: "Em andamento",
  paid: "Pago",
  failed: "Reprovado",
  engine_broken: "Motor quebrado",
  abandoned: "Abandonado",
};

export const JOB_STATUS_CLASS: Record<JobStatus, string> = {
  accepted: "bg-amber-500 text-zinc-950",
  paid: "bg-emerald-700 text-white",
  failed: "bg-red-700 text-white",
  engine_broken: "bg-red-900 text-red-50",
  abandoned: "bg-zinc-700 text-zinc-100",
};

const CAREER_ERROR_TEXT: Record<string, string> = {
  CAREER_ATTEMPT_NOT_FINISHED: "A tentativa deste serviço ainda não terminou. Termine o trabalho na bancada e envie a avaliação antes de liquidar.",
  CAREER_REPUTATION_TOO_LOW: "A reputação da oficina ainda não chega para esta ordem.",
  CAREER_JOB_ALREADY_OPEN: "Já há um serviço em andamento nesta oficina. Liquide-o antes de aceitar outra ordem.",
  PLAYER_PROFILE_NOT_FOUND: "O perfil de jogador ativo não existe mais. Escolha outro perfil.",
  ROUTE_NOT_FOUND: "O Modo Carreira está desativado nesta instalação.",
  SIM_CAPACITY_EXCEEDED: "Já existe uma sessão de simulação ativa. Encerre-a no Início antes de aceitar a ordem.",
};

export interface CareerError {
  code: string;
  text: string;
}

export function careerError(error: unknown): CareerError {
  if (isApiProblem(error)) return { code: error.code, text: CAREER_ERROR_TEXT[error.code] ?? (error.detail || error.title) };
  return { code: "UNEXPECTED_RESPONSE", text: "Resposta do servidor fora do contrato da API." };
}
