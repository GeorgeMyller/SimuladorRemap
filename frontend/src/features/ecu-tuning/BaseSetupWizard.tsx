/**
 * Assistente de configuração base do swap OEM → standalone (tuning RF-15; Fluxo Alternativo A;
 * rest-api E-24/E-25). 6 passos: roda fônica, bicos, combustível, sensores, failsafe, revisão.
 * Cada passo é validado com zod antes de avançar; voltar preserva os dados; no fim grava tudo com
 * `PUT /sessions/{id}/ecu/base-setup` (gera o mapa base) e mostra a checklist devolvida.
 */
import { useId, useState, type ReactNode } from "react";

import { isApiProblem } from "@/lib/api";

import type { BaseSetupUpdateBody, EcuApi } from "./api";
import {
  BASE_STEP_LABEL,
  BASE_STEPS,
  FUEL_DEFAULTS,
  FUEL_IDS,
  NTC_CURVES,
  STEP_SCHEMAS,
  TRIGGER_WHEELS,
  type BaseStep,
} from "./baseSetupSchemas";
import { parseCellNumber } from "./ops/tsv";
import type { BaseSetupResult, HardwareSheet, SetupChecklist } from "./types";

type Values = Record<string, string | boolean>;

export interface BaseSetupWizardProps {
  sessionId: string;
  api: Pick<EcuApi, "putBaseSetup">;
  profileName: string;
  hardware: HardwareSheet;
  /** Base já gravada (retomar o assistente) e a sua versão. */
  existing?: Record<string, unknown> | null;
  baseVersion: number | null;
  checklist?: SetupChecklist | null;
  fuels?: { fuel_id: string; afr_stoich: number; density_g_cc?: number }[];
  initialStep?: BaseStep;
  onDone: (result: BaseSetupResult) => void;
  onCancel?: () => void;
}

const STEP_OF_FIELD: Record<string, BaseStep> = { trigger: "trigger", injectors: "injectors", fuel: "fuel", sensors: "sensors", protection: "protection" };

function get(obj: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((o, k) => (o && typeof o === "object" ? (o as Record<string, unknown>)[k] : undefined), obj);
}

function str(v: unknown, fallback: string): string {
  if (typeof v === "number") return String(v);
  if (typeof v === "string") return v;
  if (Array.isArray(v)) return v.join(", ");
  return fallback;
}

function initialValues(hw: HardwareSheet, existing: Record<string, unknown> | null | undefined, fuels: BaseSetupWizardProps["fuels"]): Values {
  const e = existing ?? {};
  const fuelId = str(get(e, "fuel.fuel_id"), hw.tank_fuel_id);
  const catalogFuel = fuels?.find((f) => f.fuel_id === fuelId);
  const def = FUEL_DEFAULTS[fuelId as keyof typeof FUEL_DEFAULTS] ?? FUEL_DEFAULTS.e27;
  const phase = str(get(e, "trigger.phase_sensor"), hw.phase_sensor_present ? "cam_hall" : "none");
  return {
    "trigger.wheel": str(get(e, "trigger.wheel"), hw.trigger_wheel),
    "trigger.tdc_offset_deg": str(get(e, "trigger.tdc_offset_deg"), String(hw.tdc_offset_nominal_deg)),
    "trigger.phase_sensor": phase,
    "trigger.phase_edge_deg": str(get(e, "trigger.phase_edge_deg"), "0"),
    "trigger.injection_mode": str(get(e, "trigger.injection_mode"), phase === "cam_hall" ? "sequential" : "semi_sequential"),
    "trigger.ignition_mode": str(get(e, "trigger.ignition_mode"), "wasted_spark"),
    "trigger.firing_order": str(get(e, "trigger.firing_order"), hw.firing_order.join(", ")),
    "trigger.timing_lock_deg": str(get(e, "trigger.timing_lock_deg"), ""),
    "injectors.flow_cc_min": str(get(e, "injectors.flow_cc_min"), String(hw.injector_label_cc_min)),
    "injectors.ref_pressure_kpa": str(get(e, "injectors.ref_pressure_kpa"), "300"),
    "injectors.dead_time_v": str(get(e, "injectors.dead_time_v"), "8, 10, 12, 13.5, 14.5, 16"),
    "injectors.dead_time_ms": str(get(e, "injectors.dead_time_ms"), "2.2, 1.6, 1.2, 1, 0.9, 0.8"),
    "injectors.fuel_pressure_mode": str(get(e, "injectors.fuel_pressure_mode"), "map_referenced"),
    "injectors.rail_pressure_kpa": str(get(e, "injectors.rail_pressure_kpa"), "300"),
    "fuel.fuel_id": fuelId,
    "fuel.afr_stoich": str(get(e, "fuel.afr_stoich"), String(catalogFuel?.afr_stoich ?? def.afr)),
    "fuel.density_g_cc": str(get(e, "fuel.density_g_cc"), String(catalogFuel?.density_g_cc ?? def.density)),
    "sensors.map.min_kpa": str(get(e, "sensors.map.min_kpa"), String(hw.map_sensor_label_kpa[0])),
    "sensors.map.max_kpa": str(get(e, "sensors.map.max_kpa"), String(hw.map_sensor_label_kpa[1])),
    "sensors.iat.curve": str(get(e, "sensors.iat.curve"), "ntc_a"),
    "sensors.ect.curve": str(get(e, "sensors.ect.curve"), "ntc_a"),
    "sensors.wideband.enabled": get(e, "sensors.wideband") === null ? false : true,
    "sensors.wideband.lambda_at_0v": str(get(e, "sensors.wideband.lambda_at_0v"), "0.5"),
    "sensors.wideband.lambda_at_5v": str(get(e, "sensors.wideband.lambda_at_5v"), "1.5"),
    "protection.rev_limit_rpm": str(get(e, "protection.rev_limit_rpm"), "7000"),
    "protection.overspeed_rpm": str(get(e, "protection.overspeed_rpm"), "7500"),
    "protection.overboost_kpa": str(get(e, "protection.overboost_kpa"), "260"),
    "protection.egt_max_c": str(get(e, "protection.egt_max_c"), "950"),
    "protection.ect_max_c": str(get(e, "protection.ect_max_c"), "110"),
    "protection.oil_pressure_min_kpa": str(get(e, "protection.oil_pressure_min_kpa"), "100"),
    "protection.lean_delta_lambda": str(get(e, "protection.lean_delta_lambda"), "0.1"),
    "wizard.max_map_kpa": "200",
    "wizard.idle_rpm": "900",
    "wizard.grid": "16",
  };
}

const num = (v: string | boolean | undefined) => parseCellNumber(String(v ?? "")) ?? Number.NaN;
const list = (v: string | boolean | undefined) =>
  String(v ?? "")
    .split(/[;\s]+|,\s+/)
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s) => parseCellNumber(s) ?? Number.NaN);

function buildStep(step: BaseStep, v: Values): unknown {
  switch (step) {
    case "trigger":
      return {
        wheel: v["trigger.wheel"],
        tdc_offset_deg: num(v["trigger.tdc_offset_deg"]),
        phase_sensor: v["trigger.phase_sensor"],
        phase_edge_deg: num(v["trigger.phase_edge_deg"]),
        injection_mode: v["trigger.injection_mode"],
        ignition_mode: v["trigger.ignition_mode"],
        firing_order: list(v["trigger.firing_order"]),
        timing_lock_deg: String(v["trigger.timing_lock_deg"] ?? "").trim() === "" ? null : num(v["trigger.timing_lock_deg"]),
      };
    case "injectors":
      return {
        flow_cc_min: num(v["injectors.flow_cc_min"]),
        ref_pressure_kpa: num(v["injectors.ref_pressure_kpa"]),
        dead_time_v: list(v["injectors.dead_time_v"]),
        dead_time_ms: list(v["injectors.dead_time_ms"]),
        fuel_pressure_mode: v["injectors.fuel_pressure_mode"],
        rail_pressure_kpa: num(v["injectors.rail_pressure_kpa"]),
      };
    case "fuel":
      return { fuel_id: v["fuel.fuel_id"], afr_stoich: num(v["fuel.afr_stoich"]), density_g_cc: num(v["fuel.density_g_cc"]) };
    case "sensors":
      return {
        map: { min_kpa: num(v["sensors.map.min_kpa"]), max_kpa: num(v["sensors.map.max_kpa"]) },
        iat: { curve: v["sensors.iat.curve"] },
        ect: { curve: v["sensors.ect.curve"] },
        wideband: v["sensors.wideband.enabled"] ? { lambda_at_0v: num(v["sensors.wideband.lambda_at_0v"]), lambda_at_5v: num(v["sensors.wideband.lambda_at_5v"]) } : null,
      };
    case "protection":
      return {
        rev_limit_rpm: num(v["protection.rev_limit_rpm"]),
        overspeed_rpm: num(v["protection.overspeed_rpm"]),
        overboost_kpa: num(v["protection.overboost_kpa"]),
        egt_max_c: num(v["protection.egt_max_c"]),
        ect_max_c: num(v["protection.ect_max_c"]),
        oil_pressure_min_kpa: num(v["protection.oil_pressure_min_kpa"]),
        lean_delta_lambda: num(v["protection.lean_delta_lambda"]),
      };
    case "review":
      return { max_map_kpa: num(v["wizard.max_map_kpa"]), rev_limit_rpm: null, idle_rpm: num(v["wizard.idle_rpm"]), grid: Number(v["wizard.grid"]), fuel_model_mode: null };
  }
}

/** Valida o passo; devolve os erros por campo (`<passo>.<campo>`) ou o objeto validado. */
export function validateStep(step: BaseStep, values: Values): { ok: true; data: unknown } | { ok: false; errors: Record<string, string> } {
  const parsed = STEP_SCHEMAS[step].safeParse(buildStep(step, values));
  if (parsed.success) return { ok: true, data: parsed.data };
  const errors: Record<string, string> = {};
  const prefix = step === "review" ? "wizard" : step;
  for (const issue of parsed.error.issues) {
    const path = [prefix, ...issue.path.map(String)].join(".");
    if (!(path in errors)) errors[path] = issue.message;
  }
  return { ok: false, errors };
}

export function BaseSetupWizard(props: BaseSetupWizardProps) {
  const uid = useId();
  const [values, setValues] = useState<Values>(() => initialValues(props.hardware, props.existing, props.fuels));
  const [step, setStep] = useState<BaseStep>(props.initialStep && BASE_STEPS.includes(props.initialStep) ? props.initialStep : "trigger");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [result, setResult] = useState<BaseSetupResult | null>(null);
  const index = BASE_STEPS.indexOf(step);

  const set = (k: string, v: string | boolean) => setValues((prev) => ({ ...prev, [k]: v }));

  const next = () => {
    const verdict = validateStep(step, values);
    if (!verdict.ok) {
      setErrors(verdict.errors);
      return;
    }
    setErrors({});
    setStep(BASE_STEPS[Math.min(BASE_STEPS.length - 1, index + 1)]!);
  };

  const back = () => {
    setErrors({});
    setStep(BASE_STEPS[Math.max(0, index - 1)]!);
  };

  const finish = async () => {
    const all: Record<string, unknown> = {};
    for (const s of BASE_STEPS) {
      const verdict = validateStep(s, values);
      if (!verdict.ok) {
        setErrors(verdict.errors);
        setStep(s);
        return;
      }
      all[s] = verdict.data;
    }
    const body: BaseSetupUpdateBody = {
      base_version: props.baseVersion,
      base_setup: { trigger: all.trigger, injectors: all.injectors, fuel: all.fuel, sensors: all.sensors, protection: all.protection, feature_package: "base" },
      generate_base_map: true,
      wizard: { ...(all.review as Record<string, unknown>), rev_limit_rpm: (all.protection as { rev_limit_rpm: number }).rev_limit_rpm },
      apply_limits_to_calibration: true,
    };
    setBusy(true);
    setServerError(null);
    try {
      const res = await props.api.putBaseSetup(props.sessionId, body);
      setResult(res);
      if (res.ecu_state === "standalone_ready") props.onDone(res);
    } catch (error) {
      if (isApiProblem(error)) {
        const field = typeof error.extra.field === "string" ? error.extra.field : null;
        if (field) {
          const target = STEP_OF_FIELD[field.split(".")[0] ?? ""];
          if (target) setStep(target);
          setErrors({ [field]: `${error.detail}${typeof error.extra.reason === "string" ? ` (${error.extra.reason})` : ""}` });
        }
        setServerError(`${error.title}: ${error.detail} (${error.code})`);
      } else setServerError("Não foi possível gravar a configuração base.");
    } finally {
      setBusy(false);
    }
  };

  const field = (key: string, label: string, opts: { unit?: string; options?: readonly (readonly [string, string])[]; hint?: string } = {}): ReactNode => {
    const id = `${uid}-${key}`;
    const err = errors[key];
    return (
      <div key={key} className="grid grid-cols-[minmax(11rem,1fr)_auto] items-center gap-x-2 py-1">
        <label htmlFor={id} className="text-xs text-zinc-200">
          {label}
          {opts.unit && <span className="text-zinc-400"> ({opts.unit})</span>}
        </label>
        {opts.options ? (
          <select id={id} value={String(values[key])} onChange={(e) => set(key, e.target.value)} aria-invalid={err ? true : undefined} aria-describedby={err ? `${id}-e` : undefined} className="rounded border border-zinc-600 bg-zinc-950 px-1 py-1 text-xs text-zinc-100">
            {opts.options.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        ) : (
          <input id={id} value={String(values[key] ?? "")} onChange={(e) => set(key, e.target.value)} aria-invalid={err ? true : undefined} aria-describedby={err ? `${id}-e` : undefined} className="w-44 rounded border border-zinc-600 bg-zinc-950 px-1.5 py-1 text-right font-mono text-xs text-zinc-100 aria-[invalid=true]:border-red-400" />
        )}
        {opts.hint && <p className="col-span-2 text-[11px] text-zinc-400">{opts.hint}</p>}
        {err && (
          <p id={`${id}-e`} role="alert" className="col-span-2 text-xs text-red-300">
            {err}
          </p>
        )}
      </div>
    );
  };

  const fuelOptions = FUEL_IDS.map((f) => [f, FUEL_DEFAULTS[f].label] as const);

  return (
    <section aria-labelledby={`${uid}-title`} className="rounded border border-zinc-700 bg-zinc-900 p-3">
      <h2 id={`${uid}-title`} className="text-base font-semibold text-zinc-100">
        Configuração base — {props.profileName}
      </h2>
      <ol className="my-2 flex flex-wrap gap-1 text-xs" aria-label="Passos do assistente">
        {BASE_STEPS.map((s, i) => (
          <li key={s} aria-current={s === step ? "step" : undefined} className={`rounded px-2 py-0.5 ${s === step ? "bg-sky-700 text-white" : i < index ? "bg-zinc-700 text-zinc-100" : "bg-zinc-800 text-zinc-400"}`}>
            {i + 1}. {BASE_STEP_LABEL[s]}
          </li>
        ))}
      </ol>
      <fieldset className="min-h-[14rem]">
        <legend className="mb-1 text-sm font-semibold text-zinc-100">
          Passo {index + 1} de {BASE_STEPS.length}: {BASE_STEP_LABEL[step]}
        </legend>
        {step === "trigger" && (
          <>
            <p className="mb-1 text-[11px] text-zinc-400">Ficha do carro: roda {props.hardware.trigger_wheel}, sensor de fase {props.hardware.phase_sensor_present ? "presente" : "ausente"}, ordem {props.hardware.firing_order.join("-")}.</p>
            {field("trigger.wheel", "Roda fônica", { options: TRIGGER_WHEELS.map((w) => [w, w] as const) })}
            {field("trigger.tdc_offset_deg", "Ângulo da falha ao PMS do cil. 1", { unit: "°", hint: "Confirme com a pistola de ponto após a partida." })}
            {field("trigger.phase_sensor", "Sensor de fase", { options: [["none", "Sem sensor"], ["cam_hall", "Hall no comando"]] })}
            {field("trigger.phase_edge_deg", "Borda do sensor de fase", { unit: "°" })}
            {field("trigger.injection_mode", "Injeção", { options: [["sequential", "Sequencial"], ["semi_sequential", "Semissequencial"], ["batch", "Em grupo"]] })}
            {field("trigger.ignition_mode", "Ignição", { options: [["sequential", "Sequencial"], ["wasted_spark", "Centelha perdida"]] })}
            {field("trigger.firing_order", "Ordem de ignição", { hint: "Separe por vírgula e espaço (ex.: 1, 3, 4, 2)." })}
            {field("trigger.timing_lock_deg", "Trava de ponto (vazio = livre)", { unit: "° BTDC" })}
          </>
        )}
        {step === "injectors" && (
          <>
            {field("injectors.flow_cc_min", "Vazão do bico", { unit: "cc/min" })}
            {field("injectors.ref_pressure_kpa", "Pressão de referência", { unit: "kPa" })}
            {field("injectors.dead_time_v", "Tensões do tempo morto", { unit: "V" })}
            {field("injectors.dead_time_ms", "Tempo morto", { unit: "ms" })}
            {field("injectors.fuel_pressure_mode", "Regulador", { options: [["map_referenced", "Referenciado ao MAP"], ["fixed_rail", "Linha fixa"]] })}
            {field("injectors.rail_pressure_kpa", "Pressão da linha", { unit: "kPa" })}
          </>
        )}
        {step === "fuel" && (
          <>
            {field("fuel.fuel_id", "Combustível", { options: fuelOptions })}
            {field("fuel.afr_stoich", "AFR estequiométrico", { hint: "Um valor errado aqui desloca toda a mistura." })}
            {field("fuel.density_g_cc", "Densidade", { unit: "g/cc" })}
          </>
        )}
        {step === "sensors" && (
          <>
            {field("sensors.map.min_kpa", "MAP a 0,5 V", { unit: "kPa" })}
            {field("sensors.map.max_kpa", "MAP a 4,5 V", { unit: "kPa" })}
            {field("sensors.iat.curve", "Curva do sensor de ar", { options: NTC_CURVES.map((c) => [c, c.toUpperCase().replace("_", " ")] as const) })}
            {field("sensors.ect.curve", "Curva do sensor do motor", { options: NTC_CURVES.map((c) => [c, c.toUpperCase().replace("_", " ")] as const) })}
            <label className="flex items-center gap-2 py-1 text-xs text-zinc-200">
              <input type="checkbox" checked={Boolean(values["sensors.wideband.enabled"])} onChange={(e) => set("sensors.wideband.enabled", e.target.checked)} />
              Sonda lambda de banda larga (malha fechada)
            </label>
            {values["sensors.wideband.enabled"] === true && (
              <>
                {field("sensors.wideband.lambda_at_0v", "Lambda a 0 V")}
                {field("sensors.wideband.lambda_at_5v", "Lambda a 5 V")}
              </>
            )}
          </>
        )}
        {step === "protection" && (
          <>
            {field("protection.rev_limit_rpm", "Corte de rotação", { unit: "rpm" })}
            {field("protection.overspeed_rpm", "Sobre-rotação (failsafe)", { unit: "rpm" })}
            {field("protection.overboost_kpa", "Sobrepressão", { unit: "kPa abs" })}
            {field("protection.egt_max_c", "EGT máxima", { unit: "°C" })}
            {field("protection.ect_max_c", "Temperatura máxima do motor", { unit: "°C" })}
            {field("protection.oil_pressure_min_kpa", "Pressão mínima de óleo", { unit: "kPa" })}
            {field("protection.lean_delta_lambda", "Desvio pobre tolerado", { unit: "Δλ" })}
          </>
        )}
        {step === "review" && (
          <>
            <dl className="mb-2 grid grid-cols-2 gap-x-4 text-xs text-zinc-200">
              <dt className="text-zinc-400">Roda fônica</dt>
              <dd>{String(values["trigger.wheel"])}</dd>
              <dt className="text-zinc-400">Ordem de ignição</dt>
              <dd>{String(values["trigger.firing_order"])}</dd>
              <dt className="text-zinc-400">Bicos</dt>
              <dd>{String(values["injectors.flow_cc_min"])} cc/min</dd>
              <dt className="text-zinc-400">Combustível</dt>
              <dd>
                {String(values["fuel.fuel_id"])} (AFR {String(values["fuel.afr_stoich"])})
              </dd>
              <dt className="text-zinc-400">MAP</dt>
              <dd>
                {String(values["sensors.map.min_kpa"])}–{String(values["sensors.map.max_kpa"])} kPa
              </dd>
              <dt className="text-zinc-400">Corte</dt>
              <dd>{String(values["protection.rev_limit_rpm"])} rpm</dd>
            </dl>
            {field("wizard.max_map_kpa", "MAP máximo do mapa base", { unit: "kPa abs" })}
            {field("wizard.idle_rpm", "Marcha lenta alvo", { unit: "rpm" })}
            {field("wizard.grid", "Tamanho da grade", { options: [["12", "12×12"], ["16", "16×16"], ["20", "20×20"]] })}
          </>
        )}
      </fieldset>
      {(result?.checklist ?? props.checklist) && <ChecklistView checklist={(result?.checklist ?? props.checklist)!} />}
      {result && result.ecu_state !== "standalone_ready" && (
        <p role="alert" className="mt-2 text-xs text-amber-300">
          Base gravada, mas a checklist mínima ainda tem pendências.
        </p>
      )}
      {result?.warnings.map((w) => (
        <p key={w} className="text-xs text-amber-300">
          {w}
        </p>
      ))}
      {serverError && (
        <p role="alert" className="mt-2 text-xs text-red-300">
          {serverError}
        </p>
      )}
      <div className="mt-3 flex justify-between gap-2">
        <div className="flex gap-2">
          {props.onCancel && (
            <button type="button" onClick={props.onCancel} className="rounded border border-zinc-600 px-3 py-1 text-xs hover:bg-zinc-800">
              Fechar
            </button>
          )}
          <button type="button" onClick={back} disabled={index === 0} className="rounded border border-zinc-600 px-3 py-1 text-xs hover:bg-zinc-800 disabled:opacity-50">
            Voltar
          </button>
        </div>
        {step === "review" ? (
          <button type="button" onClick={() => void finish()} disabled={busy} className="rounded bg-emerald-700 px-3 py-1 text-xs font-semibold text-white hover:bg-emerald-600 disabled:opacity-50">
            {busy ? "A gravar…" : "Gravar e gerar mapa base"}
          </button>
        ) : (
          <button type="button" onClick={next} className="rounded bg-sky-700 px-3 py-1 text-xs font-semibold text-white hover:bg-sky-600">
            Avançar
          </button>
        )}
      </div>
    </section>
  );
}

const STATUS_LABEL: Record<string, string> = { ok: "ok", missing: "em falta", invalid: "inválido", warning: "atenção" };

export function ChecklistView({ checklist }: { checklist: SetupChecklist }) {
  return (
    <div className="mt-2 rounded border border-zinc-700 p-2 text-xs">
      <p className="mb-1 font-semibold text-zinc-200">Checklist {checklist.minimum_valid ? "(mínimo completo)" : "(mínimo incompleto)"}</p>
      <ul className="grid grid-cols-2 gap-x-4">
        {checklist.items.map((item) => (
          <li key={item.id} className={item.status === "ok" ? "text-emerald-300" : item.status === "warning" ? "text-amber-300" : "text-red-300"}>
            {item.id}: {STATUS_LABEL[item.status] ?? item.status}
            {item.message ? ` — ${item.message}` : ""}
          </li>
        ))}
      </ul>
    </div>
  );
}
