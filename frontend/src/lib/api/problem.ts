import { z } from "zod";

/** Schema do corpo `application/problem+json` (contracts/rest-api.md §2). */
export const problemDetailSchema = z.looseObject({
  type: z.string(),
  title: z.string(),
  status: z.number().int().min(400).max(599),
  detail: z.string(),
  code: z.string().regex(/^[A-Z][0-9A-Z_]{2,63}$/),
  request_id: z.string().max(64),
  instance: z.string().nullish(),
  errors: z
    .array(
      z.object({
        loc: z.array(z.union([z.string(), z.number()])),
        msg: z.string(),
        type: z.string(),
      }),
    )
    .nullish(),
});

export type ProblemDetail = z.infer<typeof problemDetailSchema>;
export type FieldError = NonNullable<ProblemDetail["errors"]>[number];

export const PROBLEM_JSON = "application/problem+json";

/** Erro lançado por `apiFetch` para toda resposta não-2xx ou falha de rede. */
export class ApiProblem extends Error {
  readonly status: number;
  readonly code: string;
  readonly title: string;
  readonly detail: string;
  readonly requestId: string | null;
  readonly type: string;
  readonly instance: string | null;
  readonly errors: FieldError[];
  /** Campos extra do domínio (ex.: `table_id`, `row`, `latest_version`). */
  readonly extra: Record<string, unknown>;

  constructor(problem: ProblemDetail) {
    super(problem.detail);
    this.name = "ApiProblem";
    const { type, title, status, detail, code, request_id, instance, errors, ...extra } = problem;
    this.status = status;
    this.code = code;
    this.title = title;
    this.detail = detail;
    this.requestId = request_id;
    this.type = type;
    this.instance = instance ?? null;
    this.errors = errors ?? [];
    this.extra = extra;
  }

  /** Falha sem corpo `ProblemDetail` (rede, timeout ou resposta inesperada). */
  static synthetic(
    status: number,
    code: string,
    detail: string,
    requestId: string | null = null,
  ): ApiProblem {
    return new ApiProblem({
      type: `urn:simremap:problem:${code.toLowerCase().replaceAll("_", "-")}`,
      title: code,
      status,
      detail,
      code,
      request_id: requestId ?? "",
    });
  }
}

export function isApiProblem(value: unknown): value is ApiProblem {
  return value instanceof ApiProblem;
}
