/**
 * Formulários das estratégias (tuning RF-14, RF-19, EC-13): 1 formulário por subtipo de
 * `StrategyConfig` (boost PID/por marcha, limitador, two-step, antilag, powershift, overrun/
 * pops & bangs, malha fechada, detonação e failsafe). Validação zod espelho do Pydantic com o
 * erro junto ao campo; erros 422 do servidor voltam por campo. Avisos W-03/W-04/W-05 não bloqueiam.
 */
import { useId, useState, type FormEvent } from "react";

import { parseCellNumber } from "./ops/tsv";
import {
  FAILSAFE_ACTION_LABEL,
  FAILSAFE_ACTIONS,
  FAILSAFE_RULE_IDS,
  FAILSAFE_RULE_LABEL,
  STRATEGY_FIELDS,
  STRATEGY_LABEL,
  validateStrategy,
  type FieldSpec,
  type StrategyKind,
} from "./strategySchemas";
import type { StrategySupport } from "./types";
import type { TuningWarning } from "./warnings";

export type FieldErrors = Record<string, string>;

export interface StrategyFormProps {
  kind: StrategyKind;
  /** Configuração atual (ou os padrões do subtipo). */
  value: Record<string, unknown>;
  support?: StrategySupport;
  title?: string;
  disabled?: boolean;
  warnings?: readonly TuningWarning[];
  /** Grava; devolve os erros por campo do servidor (422) ou `null` em sucesso. */
  onSave: (config: Record<string, unknown>) => Promise<FieldErrors | null>;
}

const input =
  "w-28 rounded border border-zinc-600 bg-zinc-950 px-1.5 py-1 text-right font-mono text-xs text-zinc-100 aria-[invalid=true]:border-red-400";

function toText(v: unknown): string {
  return typeof v === "number" ? String(v) : typeof v === "string" ? v : "";
}

function issuesToErrors(errors: { path: string; message: string }[]): FieldErrors {
  const out: FieldErrors = {};
  for (const e of errors) if (!(e.path in out)) out[e.path] = e.message;
  return out;
}

export function StrategyForm(props: StrategyFormProps) {
  if (props.kind === "failsafe") return <FailsafeForm {...props} />;
  return <SimpleStrategyForm {...props} kind={props.kind} />;
}

function Header({ kind, title, support }: { kind: StrategyKind; title?: string; support?: StrategySupport }) {
  return (
    <header className="mb-2">
      <h2 className="text-base font-semibold text-zinc-100">{title ?? support?.display_name ?? STRATEGY_LABEL[kind]}</h2>
      {support?.level === "package_race" && <p className="text-xs text-amber-300">Exige o pacote race deste perfil.</p>}
    </header>
  );
}

function FieldWarnings({ list, field }: { list: readonly TuningWarning[]; field: string }) {
  const items = list.filter((w) => w.field === field);
  if (items.length === 0) return null;
  return (
    <>
      {items.map((w, i) => (
        <p key={i} className="text-xs text-amber-300" data-warning={w.code}>
          <span aria-hidden="true">▲ </span>
          {w.code}: {w.message} {w.detail}
        </p>
      ))}
    </>
  );
}

function SimpleStrategyForm({ kind, value, support, title, disabled, warnings = [], onSave }: StrategyFormProps & { kind: Exclude<StrategyKind, "failsafe"> }) {
  const fields = STRATEGY_FIELDS[kind];
  const formId = useId();
  const [state, setState] = useState<Record<string, string | boolean>>(() => {
    const init: Record<string, string | boolean> = {};
    for (const f of fields) init[f.name] = f.type === "bool" ? (typeof value[f.name] === "boolean" ? (value[f.name] as boolean) : f.default) : toText(value[f.name] ?? f.default);
    return init;
  });
  const [errors, setErrors] = useState<FieldErrors>({});
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");

  if (support?.level === "unsupported") {
    return (
      <section className="p-2">
        <Header kind={kind} title={title} support={support} />
        <p className="text-sm text-zinc-300">Estratégia não suportada neste perfil.</p>
      </section>
    );
  }

  const restricted = support?.restricted_options ?? {};

  const build = (): { payload: Record<string, unknown>; local: FieldErrors } => {
    const payload: Record<string, unknown> = { kind };
    const local: FieldErrors = {};
    for (const f of fields) {
      const raw = state[f.name];
      if (f.type === "number") {
        const n = parseCellNumber(String(raw ?? ""));
        if (n === null) local[f.name] = `${f.label}: digite um número`;
        else payload[f.name] = n;
      } else payload[f.name] = raw;
    }
    for (const [option, allowed] of Object.entries(restricted)) {
      const v = payload[option];
      if (v !== undefined && !allowed.includes(typeof v === "string" ? v : JSON.stringify(v))) local[option] = `Opção não suportada neste perfil (aceites: ${allowed.join(", ")}).`;
    }
    return { payload, local };
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const { payload, local } = build();
    if (Object.keys(local).length > 0) {
      setErrors(local);
      setStatus("error");
      return;
    }
    const verdict = validateStrategy(payload);
    if (!verdict.ok) {
      setErrors(issuesToErrors(verdict.errors));
      setStatus("error");
      return;
    }
    setErrors({});
    setStatus("saving");
    const serverErrors = await onSave(verdict.data);
    if (serverErrors) {
      setErrors(serverErrors);
      setStatus("error");
    } else setStatus("saved");
  };

  const renderField = (f: FieldSpec) => {
    const id = `${formId}-${f.name}`;
    const err = errors[f.name];
    const errId = `${id}-err`;
    if (f.type === "bool") {
      return (
        <div key={f.name} className="flex items-center gap-2 py-0.5">
          <input id={id} type="checkbox" checked={Boolean(state[f.name])} disabled={disabled} onChange={(ev) => setState({ ...state, [f.name]: ev.target.checked })} />
          <label htmlFor={id} className="text-xs text-zinc-200">
            {f.label}
          </label>
        </div>
      );
    }
    const allowed = restricted[f.name];
    return (
      <div key={f.name} className="grid grid-cols-[minmax(10rem,1fr)_auto] items-center gap-x-2 py-0.5">
        <label htmlFor={id} className="text-xs text-zinc-200">
          {f.label}
          {f.type === "number" && f.unit && f.unit !== "-" ? <span className="text-zinc-400"> ({f.unit})</span> : null}
        </label>
        {f.type === "number" ? (
          <input
            id={id}
            inputMode="decimal"
            value={String(state[f.name] ?? "")}
            disabled={disabled}
            aria-invalid={err ? true : undefined}
            aria-describedby={err ? errId : undefined}
            onChange={(ev) => setState({ ...state, [f.name]: ev.target.value })}
            className={input}
          />
        ) : (
          <select
            id={id}
            value={String(state[f.name] ?? f.default)}
            disabled={disabled}
            aria-invalid={err ? true : undefined}
            aria-describedby={err ? errId : undefined}
            onChange={(ev) => setState({ ...state, [f.name]: ev.target.value })}
            className="rounded border border-zinc-600 bg-zinc-950 px-1 py-1 text-xs text-zinc-100"
          >
            {f.options.map((o) => (
              <option key={o.value} value={o.value} disabled={allowed ? !allowed.includes(o.value) : false}>
                {o.label}
              </option>
            ))}
          </select>
        )}
        {err && (
          <p id={errId} role="alert" className="col-span-2 text-xs text-red-300">
            {err}
          </p>
        )}
        <div className="col-span-2">
          <FieldWarnings list={warnings} field={`${kind}.${f.name}`} />
        </div>
      </div>
    );
  };

  return (
    <form onSubmit={(e) => void submit(e)} aria-label={title ?? STRATEGY_LABEL[kind]} className="max-w-2xl rounded border border-zinc-700 bg-zinc-900 p-3" noValidate>
      <Header kind={kind} title={title} support={support} />
      <div className="grid gap-x-6 md:grid-cols-2">{fields.map(renderField)}</div>
      {errors[""] && (
        <p role="alert" className="mt-2 text-xs text-red-300">
          {errors[""]}
        </p>
      )}
      <div className="mt-3 flex items-center gap-2">
        <button type="submit" disabled={disabled || status === "saving"} className="rounded bg-sky-700 px-3 py-1 text-xs font-semibold text-white hover:bg-sky-600 disabled:opacity-50">
          {status === "saving" ? "A gravar…" : "Gravar estratégia"}
        </button>
        <span role="status" className="text-xs text-zinc-300">
          {status === "saved" ? "Estratégia gravada." : status === "error" ? "Corrija os campos assinalados." : ""}
        </span>
      </div>
    </form>
  );
}

interface RuleState {
  rule_id: string;
  enabled: boolean;
  threshold: string;
  confirm_s: string;
  actions: string[];
  action_value: string;
  release_s: string;
  latch_until_stop: boolean;
}

function FailsafeForm({ value, support, title, disabled, onSave }: StrategyFormProps) {
  const formId = useId();
  const rulesIn = Array.isArray(value.rules) ? (value.rules as Record<string, unknown>[]) : [];
  const [enabled, setEnabled] = useState(value.enabled !== false);
  const [overspeed, setOverspeed] = useState(toText(value.overspeed_rpm ?? 7500));
  const [rules, setRules] = useState<RuleState[]>(() =>
    rulesIn.map((r) => ({
      rule_id: typeof r.rule_id === "string" ? r.rule_id : "egt_high",
      enabled: r.enabled !== false,
      threshold: toText(r.threshold),
      confirm_s: toText(r.confirm_s ?? 0.5),
      actions: Array.isArray(r.actions) ? (r.actions as string[]) : [],
      action_value: toText(r.action_value ?? 0),
      release_s: toText(r.release_s ?? 2),
      latch_until_stop: r.latch_until_stop === true,
    })),
  );
  const [errors, setErrors] = useState<FieldErrors>({});
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");

  const update = (i: number, patch: Partial<RuleState>) => setRules(rules.map((r, k) => (k === i ? { ...r, ...patch } : r)));
  const numOr = (s: string) => parseCellNumber(s) ?? Number.NaN;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const payload = {
      kind: "failsafe",
      enabled,
      overspeed_rpm: numOr(overspeed),
      rules: rules.map((r) => ({
        rule_id: r.rule_id,
        enabled: r.enabled,
        threshold: numOr(r.threshold),
        confirm_s: numOr(r.confirm_s),
        actions: r.actions,
        action_value: numOr(r.action_value),
        release_s: numOr(r.release_s),
        latch_until_stop: r.latch_until_stop,
      })),
    };
    const verdict = validateStrategy(payload);
    if (!verdict.ok) {
      setErrors(issuesToErrors(verdict.errors));
      setStatus("error");
      return;
    }
    setErrors({});
    setStatus("saving");
    const serverErrors = await onSave(verdict.data);
    if (serverErrors) {
      setErrors(serverErrors);
      setStatus("error");
    } else setStatus("saved");
  };

  const err = (path: string) =>
    errors[path] ? (
      <p role="alert" className="text-xs text-red-300">
        {errors[path]}
      </p>
    ) : null;

  return (
    <form onSubmit={(e) => void submit(e)} aria-label={title ?? STRATEGY_LABEL.failsafe} className="rounded border border-zinc-700 bg-zinc-900 p-3" noValidate>
      <Header kind="failsafe" title={title} support={support} />
      <div className="flex flex-wrap items-center gap-4 text-xs text-zinc-200">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={enabled} disabled={disabled} onChange={(e) => setEnabled(e.target.checked)} /> Ativo
        </label>
        <label htmlFor={`${formId}-os`} className="flex items-center gap-2">
          Sobre-rotação (rpm)
        </label>
        <input id={`${formId}-os`} inputMode="decimal" value={overspeed} disabled={disabled} aria-invalid={errors.overspeed_rpm ? true : undefined} onChange={(e) => setOverspeed(e.target.value)} className={input} />
      </div>
      {err("overspeed_rpm")}
      {err("rules")}
      <table className="mt-2 w-full text-xs">
        <caption className="sr-only">Regras de proteção</caption>
        <thead className="text-left text-zinc-300">
          <tr>
            <th scope="col">Regra</th>
            <th scope="col">Ativa</th>
            <th scope="col">Limiar</th>
            <th scope="col">Confirmação (s)</th>
            <th scope="col">Ações</th>
            <th scope="col">Valor da ação</th>
            <th scope="col">Liberação (s)</th>
            <th scope="col">Só com motor parado</th>
            <th scope="col">
              <span className="sr-only">Remover</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rules.map((r, i) => (
            <tr key={i} className="border-t border-zinc-700 align-top">
              <td>
                <select aria-label={`Regra ${i + 1}`} value={r.rule_id} disabled={disabled} onChange={(e) => update(i, { rule_id: e.target.value })} className="rounded border border-zinc-600 bg-zinc-950 px-1 py-1">
                  {FAILSAFE_RULE_IDS.map((id) => (
                    <option key={id} value={id}>
                      {FAILSAFE_RULE_LABEL[id]}
                    </option>
                  ))}
                </select>
              </td>
              <td>
                <input type="checkbox" aria-label={`Regra ${i + 1} ativa`} checked={r.enabled} disabled={disabled} onChange={(e) => update(i, { enabled: e.target.checked })} />
              </td>
              <td>
                <input aria-label={`Limiar da regra ${i + 1}`} inputMode="decimal" value={r.threshold} disabled={disabled} onChange={(e) => update(i, { threshold: e.target.value })} className={input} />
                {err(`rules.${i}.threshold`)}
              </td>
              <td>
                <input aria-label={`Confirmação da regra ${i + 1}`} inputMode="decimal" value={r.confirm_s} disabled={disabled} onChange={(e) => update(i, { confirm_s: e.target.value })} className={input} />
                {err(`rules.${i}.confirm_s`)}
              </td>
              <td>
                <fieldset>
                  <legend className="sr-only">Ações da regra {i + 1}</legend>
                  {FAILSAFE_ACTIONS.map((a) => (
                    <label key={a} className="mr-2 inline-flex items-center gap-1">
                      <input
                        type="checkbox"
                        checked={r.actions.includes(a)}
                        disabled={disabled}
                        onChange={(e) => update(i, { actions: e.target.checked ? [...r.actions, a] : r.actions.filter((x) => x !== a) })}
                      />
                      {FAILSAFE_ACTION_LABEL[a]}
                    </label>
                  ))}
                </fieldset>
                {err(`rules.${i}.actions`)}
              </td>
              <td>
                <input aria-label={`Valor da ação da regra ${i + 1}`} inputMode="decimal" value={r.action_value} disabled={disabled} onChange={(e) => update(i, { action_value: e.target.value })} className={input} />
              </td>
              <td>
                <input aria-label={`Liberação da regra ${i + 1}`} inputMode="decimal" value={r.release_s} disabled={disabled} onChange={(e) => update(i, { release_s: e.target.value })} className={input} />
                {err(`rules.${i}.release_s`)}
              </td>
              <td>
                <input type="checkbox" aria-label={`Regra ${i + 1} só libera com motor parado`} checked={r.latch_until_stop} disabled={disabled} onChange={(e) => update(i, { latch_until_stop: e.target.checked })} />
              </td>
              <td>
                <button type="button" disabled={disabled} onClick={() => setRules(rules.filter((_, k) => k !== i))} className="rounded border border-zinc-600 px-1.5 py-0.5 hover:bg-zinc-800">
                  Remover
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          disabled={disabled}
          onClick={() => setRules([...rules, { rule_id: FAILSAFE_RULE_IDS.find((id) => !rules.some((r) => r.rule_id === id)) ?? "egt_high", enabled: true, threshold: "0", confirm_s: "0.5", actions: ["boost_cut"], action_value: "0", release_s: "2", latch_until_stop: false }])}
          className="rounded border border-zinc-600 px-3 py-1 text-xs hover:bg-zinc-800"
        >
          Acrescentar regra
        </button>
        <button type="submit" disabled={disabled || status === "saving"} className="rounded bg-sky-700 px-3 py-1 text-xs font-semibold text-white hover:bg-sky-600 disabled:opacity-50">
          {status === "saving" ? "A gravar…" : "Gravar estratégia"}
        </button>
        <span role="status" className="text-xs text-zinc-300">
          {status === "saved" ? "Estratégia gravada." : status === "error" ? "Corrija os campos assinalados." : ""}
        </span>
      </div>
    </form>
  );
}

/** Erros por campo a partir de um `ProblemDetail` 422 (EC-13). */
export function problemToFieldErrors(problem: { detail: string; errors: { loc: (string | number)[]; msg: string }[]; extra: Record<string, unknown> } | null, kind: string): FieldErrors {
  if (!problem) return { "": "Não foi possível gravar a estratégia." };
  const out: FieldErrors = {};
  for (const e of problem.errors) {
    const loc = e.loc.map(String);
    const i = loc.indexOf(kind);
    const path = (i >= 0 ? loc.slice(i + 1) : loc.slice(-1)).join(".");
    out[path] = e.msg;
  }
  const fields = problem.extra.fields;
  if (Array.isArray(fields)) for (const f of fields) out[String(f).split(".").slice(2).join(".") || ""] = problem.detail;
  if (Object.keys(out).length === 0) out[""] = problem.detail;
  return out;
}
