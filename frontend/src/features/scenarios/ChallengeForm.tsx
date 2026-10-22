/**
 * Formulário de desafio do instrutor (training-scenarios RF-05): veículo, combustível,
 * objetivos, critérios, defeito oculto opcional e até 5 dicas. O padrão pré-preenchido é o
 * exemplo "400 whp com gasolina comum e EGT ≤ 900 °C" no coupe-30t-i6.
 */
import { useState, type FormEvent } from "react";

import { useScenariosApi } from "./api";
import {
  CRITERION_INFO,
  CRITERION_KINDS,
  DEFECT_KINDS,
  DEFECT_LABELS,
  FUEL_IDS,
  FUEL_LABELS,
  SLUG_RE,
  VEHICLE_IDS,
  VEHICLE_LABELS,
  type Comparator,
  type Criterion,
  type CriterionKind,
  type DefectKind,
  type Hint,
  type HiddenDefect,
  type Scenario,
  type ScenarioView,
} from "./types";
import { ErrorBox } from "./ui";

/** Comparador natural de cada tipo de critério. */
export function defaultComparator(kind: CriterionKind): Comparator {
  if (kind === "final_profile" || kind === "locked_tables" || kind === "defect_diagnosis") return "bool";
  if (kind.startsWith("max_") || kind === "lambda_wot_max") return "le";
  return "ge";
}

function criterion(kind: CriterionKind, threshold: number | null, weight = 1): Criterion {
  return { criterion_id: kind.replaceAll("_", "-"), kind, comparator: defaultComparator(kind), threshold, weight, mandatory: true };
}

const STOCK_HASH_PLACEHOLDER = "0".repeat(64);

export const DEFAULT_CHALLENGE: Scenario = {
  scenario_id: "challenge-400whp-e27",
  kind: "challenge",
  title: "400 whp com gasolina comum e EGT ≤ 900 °C",
  briefing: "Atinja 400 whp no coupé 3.0 turbo com gasolina comum, mantendo a EGT pré-turbina até 900 °C e sem knock.",
  vehicle_id: "coupe-30t-i6",
  initial_profile_id: "oem-stage",
  initial_calibration: { source: "vehicle_stock", payload: null, content_hash: STOCK_HASH_PLACEHOLDER },
  fuel_id: "e27",
  ambient: { temperature_c: 25, pressure_kpa: 99, relative_humidity: 0 },
  correction_standard: "sae_j1349",
  seed: null,
  objectives: ["Atingir 400 whp em todas as puxadas de evidência", "EGT pré-turbina ≤ 900 °C", "Motor 100 % íntegro"],
  constraints: {
    allowed_run_types: ["baseline_pull", "sweep_pull", "multi_pull"],
    gear: 4,
    allowed_final_profiles: [],
    swap_allowed: false,
    locked_table_ids: [],
    max_submissions: 5,
    time_limit_min: null,
    operator_protection: false,
  },
  criteria: {
    criteria: [
      criterion("min_whp", 400, 2),
      criterion("max_egt_c", 900),
      criterion("max_knock_retard_deg", 3),
      criterion("integrity", 100),
      criterion("valid_pulls", 3),
      criterion("max_spread_pct", 3),
    ],
    required_valid_pulls: 3,
    lambda_window_min_rpm: 3000,
    require_defect_diagnosis: false,
  },
  hidden_defect: null,
  hints: [],
  author_nickname: null,
};

const DEFECT_PARAMS: Record<DefectKind, { key: keyof HiddenDefect; label: string; min: number; max: number; step: number; def: number }[]> = {
  fuel_pump_weak: [{ key: "fuel_pump_max_lph", label: "Vazão máxima (L/h)", min: 60, max: 250, step: 1, def: 90 }],
  injector_clogged: [
    { key: "cylinder", label: "Cilindro", min: 1, max: 8, step: 1, def: 1 },
    { key: "injector_flow_factor", label: "Fator de vazão", min: 0.5, max: 0.95, step: 0.01, def: 0.8 },
  ],
  iat_sensor_bias: [{ key: "sensor_bias_c", label: "Desvio (°C)", min: -30, max: 30, step: 1, def: 15 }],
  wastegate_stuck: [{ key: "stuck_position_pct", label: "Posição travada (%)", min: 0, max: 100, step: 1, def: 0 }],
  boost_leak: [{ key: "leak_area_mm2", label: "Área do vazamento (mm²)", min: 5, max: 200, step: 1, def: 40 }],
};

function numberOrNull(v: string): number | null {
  if (v.trim() === "") return null;
  const n = Number(v.replace(",", "."));
  return Number.isFinite(n) ? n : null;
}

export interface ChallengeFormProps {
  onCreated?: (scenario: ScenarioView) => void;
}

export function ChallengeForm({ onCreated }: ChallengeFormProps) {
  const api = useScenariosApi();
  const [draft, setDraft] = useState<Scenario>(DEFAULT_CHALLENGE);
  const [objectivesText, setObjectivesText] = useState(DEFAULT_CHALLENGE.objectives.join("\n"));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [created, setCreated] = useState<ScenarioView | null>(null);

  const set = (patch: Partial<Scenario>) => setDraft((d) => ({ ...d, ...patch }));
  const setCriteria = (criteria: Criterion[]) => setDraft((d) => ({ ...d, criteria: { ...d.criteria, criteria } }));
  const updateCriterion = (i: number, patch: Partial<Criterion>) =>
    setCriteria(draft.criteria.criteria.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  const setHints = (hints: Hint[]) => set({ hints: hints.map((h, i) => ({ ...h, order: i + 1 })) });

  const objectives = objectivesText.split("\n").map((s) => s.trim()).filter(Boolean);
  const slugOk = SLUG_RE.test(draft.scenario_id);
  const valid = slugOk && draft.title.trim().length >= 3 && objectives.length > 0 && draft.criteria.criteria.length > 0;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!valid) return;
    setBusy(true);
    setError(null);
    try {
      const scenario: Scenario = { ...draft, objectives };
      const result = await api.createScenario({ scenario });
      setCreated(result);
      onCreated?.(result);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  function setDefect(kind: DefectKind | "") {
    if (!kind) {
      set({ hidden_defect: null });
      return;
    }
    const defect: HiddenDefect = { kind, start_t_sim_s: 0 };
    for (const p of DEFECT_PARAMS[kind]) (defect as unknown as Record<string, number>)[p.key] = p.def;
    set({ hidden_defect: defect });
  }

  const input = "rounded border border-zinc-600 bg-zinc-950 px-2 py-1";

  return (
    <form aria-label="Novo desafio" className="space-y-3 text-sm" onSubmit={(e) => void submit(e)} noValidate>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="flex flex-col">
          Identificador (slug)
          <input className={input} value={draft.scenario_id} aria-invalid={!slugOk} onChange={(e) => set({ scenario_id: e.target.value })} />
        </label>
        <label className="flex flex-col">
          Título
          <input className={input} value={draft.title} maxLength={80} onChange={(e) => set({ title: e.target.value })} />
        </label>
        <label className="flex flex-col">
          Veículo
          <select className={input} value={draft.vehicle_id} onChange={(e) => set({ vehicle_id: e.target.value })}>
            {VEHICLE_IDS.map((v) => (
              <option key={v} value={v}>
                {VEHICLE_LABELS[v]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col">
          Combustível
          <select className={input} value={draft.fuel_id} onChange={(e) => set({ fuel_id: e.target.value })}>
            {FUEL_IDS.map((f) => (
              <option key={f} value={f}>
                {FUEL_LABELS[f]}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label className="flex flex-col">
        Briefing
        <textarea className={input} rows={3} maxLength={4000} value={draft.briefing} onChange={(e) => set({ briefing: e.target.value })} />
      </label>
      <label className="flex flex-col">
        Objetivos (um por linha)
        <textarea className={input} rows={3} value={objectivesText} onChange={(e) => setObjectivesText(e.target.value)} />
      </label>

      <fieldset className="space-y-1">
        <legend className="font-semibold">Critérios</legend>
        <label className="flex items-center gap-2">
          Puxadas válidas exigidas
          <input
            type="number"
            min={1}
            max={10}
            className={`${input} w-20`}
            value={draft.criteria.required_valid_pulls}
            onChange={(e) => setDraft((d) => ({ ...d, criteria: { ...d.criteria, required_valid_pulls: Number(e.target.value) || 1 } }))}
          />
        </label>
        <table className="w-full">
          <thead>
            <tr className="text-left">
              <th scope="col">Tipo</th>
              <th scope="col">Comparador</th>
              <th scope="col">Limiar</th>
              <th scope="col">Peso</th>
              <th scope="col">Obrigatório</th>
              <th scope="col">
                <span className="sr-only">Remover</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {draft.criteria.criteria.map((c, i) => (
              <tr key={i}>
                <td>
                  <select
                    aria-label={`Tipo do critério ${i + 1}`}
                    className={input}
                    value={c.kind}
                    onChange={(e) => {
                      const kind = e.target.value as CriterionKind;
                      const comparator = defaultComparator(kind);
                      updateCriterion(i, { kind, comparator, criterion_id: kind.replaceAll("_", "-"), threshold: comparator === "bool" ? null : c.threshold });
                    }}
                  >
                    {CRITERION_KINDS.map((k) => (
                      <option key={k} value={k}>
                        {CRITERION_INFO[k].label}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <select
                    aria-label={`Comparador do critério ${i + 1}`}
                    className={input}
                    value={c.comparator}
                    onChange={(e) => updateCriterion(i, { comparator: e.target.value as Comparator })}
                  >
                    <option value="ge">≥</option>
                    <option value="le">≤</option>
                    <option value="bool">sim/não</option>
                  </select>
                </td>
                <td>
                  <input
                    aria-label={`Limiar do critério ${i + 1} (${CRITERION_INFO[c.kind].unit})`}
                    className={`${input} w-24`}
                    inputMode="decimal"
                    disabled={c.comparator === "bool"}
                    value={c.threshold ?? ""}
                    onChange={(e) => updateCriterion(i, { threshold: numberOrNull(e.target.value) })}
                  />
                </td>
                <td>
                  <input
                    aria-label={`Peso do critério ${i + 1}`}
                    type="number"
                    min={0.1}
                    max={10}
                    step={0.1}
                    className={`${input} w-20`}
                    value={c.weight}
                    onChange={(e) => updateCriterion(i, { weight: Number(e.target.value) || 1 })}
                  />
                </td>
                <td>
                  <input
                    aria-label={`Critério ${i + 1} obrigatório`}
                    type="checkbox"
                    checked={c.mandatory}
                    onChange={(e) => updateCriterion(i, { mandatory: e.target.checked })}
                  />
                </td>
                <td>
                  <button type="button" className="rounded bg-zinc-700 px-2" onClick={() => setCriteria(draft.criteria.criteria.filter((_, j) => j !== i))}>
                    Remover
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button
          type="button"
          disabled={draft.criteria.criteria.length >= 20}
          className="rounded bg-zinc-700 px-2 py-1"
          onClick={() => setCriteria([...draft.criteria.criteria, criterion("min_torque_nm", 400)])}
        >
          Adicionar critério
        </button>
      </fieldset>

      <fieldset className="space-y-1">
        <legend className="font-semibold">Defeito oculto (opcional)</legend>
        <select aria-label="Tipo de defeito oculto" className={input} value={draft.hidden_defect?.kind ?? ""} onChange={(e) => setDefect(e.target.value as DefectKind | "")}>
          <option value="">Sem defeito</option>
          {DEFECT_KINDS.map((k) => (
            <option key={k} value={k}>
              {DEFECT_LABELS[k]}
            </option>
          ))}
        </select>
        {draft.hidden_defect &&
          DEFECT_PARAMS[draft.hidden_defect.kind].map((p) => (
            <label key={p.key} className="ml-2 inline-flex items-center gap-1">
              {p.label}
              <input
                type="number"
                min={p.min}
                max={p.max}
                step={p.step}
                className={`${input} w-24`}
                value={Number(draft.hidden_defect?.[p.key] ?? p.def)}
                onChange={(e) =>
                  setDraft((d) => (d.hidden_defect ? { ...d, hidden_defect: { ...d.hidden_defect, [p.key]: Number(e.target.value) } } : d))
                }
              />
            </label>
          ))}
        {draft.hidden_defect && (
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={draft.criteria.require_defect_diagnosis}
              onChange={(e) => setDraft((d) => ({ ...d, criteria: { ...d.criteria, require_defect_diagnosis: e.target.checked } }))}
            />
            Exigir diagnóstico do defeito
          </label>
        )}
      </fieldset>

      <fieldset className="space-y-1">
        <legend className="font-semibold">Dicas ({draft.hints.length}/5)</legend>
        {draft.hints.map((h, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2">
            <input
              aria-label={`Texto da dica ${i + 1}`}
              className={`${input} flex-1`}
              maxLength={500}
              value={h.text}
              onChange={(e) => setHints(draft.hints.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))}
            />
            <label className="inline-flex items-center gap-1">
              Após reprovações
              <input
                type="number"
                min={1}
                max={5}
                className={`${input} w-16`}
                value={h.unlock.after_failed_submissions ?? ""}
                onChange={(e) =>
                  setHints(
                    draft.hints.map((x, j) => (j === i ? { ...x, unlock: { ...x.unlock, after_failed_submissions: numberOrNull(e.target.value) } } : x)),
                  )
                }
              />
            </label>
            <button type="button" className="rounded bg-zinc-700 px-2" onClick={() => setHints(draft.hints.filter((_, j) => j !== i))}>
              Remover
            </button>
          </div>
        ))}
        <button
          type="button"
          disabled={draft.hints.length >= 5}
          className="rounded bg-zinc-700 px-2 py-1 disabled:opacity-50"
          onClick={() => setHints([...draft.hints, { order: draft.hints.length + 1, text: "", unlock: {} }])}
        >
          Adicionar dica
        </button>
      </fieldset>

      {error !== null && <ErrorBox error={error} />}
      {created && (
        <p role="status" className="text-emerald-300">
          <span aria-hidden="true">✓ </span>Desafio {created.scenario_id} criado.
        </p>
      )}
      <button type="submit" disabled={!valid || busy} className="rounded bg-emerald-700 px-4 py-2 disabled:opacity-50">
        Criar desafio
      </button>
    </form>
  );
}
