/**
 * CSV de notas do instrutor (contracts/file-formats.md seção 6; training-scenarios RF-25, RF-26).
 * Função pura, gerada no navegador: UTF-8 sem BOM, padrão pt-BR (`;` e vírgula decimal)
 * ou RFC 4180 (`,` e ponto decimal). Células que começam por `=`, `+`, `-`, `@`, tabulação
 * ou retorno de carro recebem o prefixo `'` (proteção contra injeção de fórmulas).
 */

export const GRADES_FIXED_COLUMNS = [
  "nickname",
  "station",
  "scenario_id",
  "attempt_id",
  "submission",
  "passed",
  "total_score",
  "evaluation_mismatch",
  "replay_status",
  "package_sha256",
  "imported_at",
] as const;

export interface GradeRow {
  nickname: string;
  install_id: string | null;
  scenario_id: string;
  scenario_title?: string;
  attempt_id: string;
  submission: number;
  passed: boolean | null;
  total_score: number | null;
  evaluation_mismatch: boolean;
  replay_status: string;
  package_sha256: string | null;
  imported_at: string | null;
  /** Pontuação por `criterion_id`. */
  scores: Record<string, number | null | undefined>;
}

export interface GradesCsvOptions {
  /** `pt-BR` (padrão): `;` e vírgula decimal; `rfc4180`: `,` e ponto decimal. */
  dialect?: "pt-BR" | "rfc4180";
  /** `criterion_id` do cenário filtrado, na ordem de `ChallengeCriteria.criteria`. */
  criterionIds?: string[];
  /** Acrescenta a coluna `scenario_title` no fim das colunas fixas. */
  includeTitle?: boolean;
}

const FORMULA_START = /^[=+\-@\t\r]/;

/** Prefixa `'` em células que o Excel/LibreOffice interpretariam como fórmula. */
export function neutralizeFormula(value: string): string {
  return FORMULA_START.test(value) ? `'${value}` : value;
}

function quote(value: string, sep: string): string {
  if (value.includes(sep) || value.includes('"') || value.includes("\n") || value.includes("\r")) {
    return `"${value.replaceAll('"', '""')}"`;
  }
  return value;
}

function cell(value: string, sep: string): string {
  return quote(neutralizeFormula(value), sep);
}

function decimal(value: number | null | undefined, comma: boolean): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "";
  const s = value.toFixed(1);
  return comma ? s.replace(".", ",") : s;
}

/** Estação = 4 primeiros hex do `install_id` (separa nicknames iguais). */
export function stationOf(installId: string | null | undefined): string {
  return (installId ?? "").replaceAll("-", "").slice(0, 4);
}

export function gradesCsv(rows: GradeRow[], options: GradesCsvOptions = {}): string {
  const ptBr = (options.dialect ?? "pt-BR") === "pt-BR";
  const sep = ptBr ? ";" : ",";
  const criterionIds = options.criterionIds ?? [];
  const header: string[] = [...GRADES_FIXED_COLUMNS];
  if (options.includeTitle) header.push("scenario_title");
  header.push(...criterionIds.map((id) => `score_${id}`));

  const lines = [header.map((h) => cell(h, sep)).join(sep)];
  for (const r of rows) {
    const values = [
      r.nickname,
      stationOf(r.install_id),
      r.scenario_id,
      r.attempt_id,
      String(r.submission),
      r.passed === null ? "" : String(r.passed),
      decimal(r.total_score, ptBr),
      String(r.evaluation_mismatch),
      r.replay_status,
      r.package_sha256 ?? "",
      r.imported_at ?? "",
    ];
    if (options.includeTitle) values.push(r.scenario_title ?? "");
    for (const id of criterionIds) values.push(decimal(r.scores[id], ptBr));
    lines.push(values.map((v) => cell(v, sep)).join(sep));
  }
  return `${lines.join("\n")}\n`;
}
