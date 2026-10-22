/**
 * Stage Builder (002 RF-13, RF-19; T047): escolha de peças nas 6 categorias do `GET /upgrades` e
 * controle do Flex Fuel (E27 a E100) na criação da sessão. Componente controlado: o pai guarda a
 * `StageSelection` e a converte em `upgrades` e `ethanol_pct` com `toSessionFields`.
 * Peças que não servem no veículo ficam desabilitadas com o motivo; o Flex só aparece se o
 * veículo permite E27 e E100.
 */
import type { WorkshopApi } from "./api";
import { EthanolControl } from "./EthanolControl";
import {
  CATEGORY_LABEL,
  describeEffect,
  incompatibilityReason,
  type StageSelection,
  type UpgradeCategoryOptions,
  type VehicleCompat,
} from "./types";
import { useStageBuilderData } from "./useStageBuilderData";

export interface StageBuilderProps {
  api: WorkshopApi;
  vehicleId: string;
  value: StageSelection;
  onChange: (next: StageSelection) => void;
  disabled?: boolean;
}

export function StageBuilder({ api, vehicleId, value, onChange, disabled = false }: StageBuilderProps) {
  const { data, retry } = useStageBuilderData(api, vehicleId);

  return (
    <section aria-labelledby="stage-builder-title" className="rounded border border-zinc-700 p-4">
      <h2 id="stage-builder-title" className="font-semibold">
        Oficina: peças e combustível
      </h2>
      {data.status === "loading" && (
        <div role="status" aria-label="A carregar a oficina" className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }, (_, i) => (
            <span key={i} className="h-24 rounded bg-zinc-800 motion-safe:animate-pulse" />
          ))}
        </div>
      )}
      {data.status === "error" && (
        <div role="alert" className="mt-3 rounded border border-red-500 p-3 text-sm">
          <p>Não foi possível carregar a oficina. A sessão pode ser criada com o carro de série.</p>
          <p className="mt-1 font-mono text-xs text-zinc-300">{data.message}</p>
          <button type="button" onClick={retry} className="mt-2 rounded border border-amber-400 px-3 py-1 text-amber-200 hover:bg-zinc-800">
            Tentar de novo
          </button>
        </div>
      )}
      {data.status === "ready" && (
        <>
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {data.categories.map((group) => (
              <CategoryPicker
                key={group.category}
                group={group}
                compat={data.compat}
                selected={value.parts[group.category]}
                disabled={disabled}
                onSelect={(partId) => onChange({ ...value, parts: { ...value.parts, [group.category]: partId } })}
              />
            ))}
          </div>
          <EthanolControl
            allowed={data.compat.flexAllowed}
            value={value.ethanolPct}
            disabled={disabled}
            onChange={(ethanolPct) => onChange({ ...value, ethanolPct })}
          />
        </>
      )}
    </section>
  );
}

export interface CategoryPickerProps {
  group: UpgradeCategoryOptions;
  compat: VehicleCompat;
  selected: string;
  disabled: boolean;
  onSelect: (partId: string) => void;
}

export function CategoryPicker({ group, compat, selected, disabled, onSelect }: CategoryPickerProps) {
  const name = `upgrade-${group.category}`;
  return (
    <fieldset className="rounded border border-zinc-800 p-3">
      <legend className="px-1 text-sm font-semibold">{CATEGORY_LABEL[group.category]}</legend>
      <div className="space-y-2">
        {group.options.map((option) => {
          const reason = incompatibilityReason(group.category, option.part_id, compat);
          const inputId = `${name}-${option.part_id}`;
          const effects = Object.entries(option.effects ?? {});
          const checked = selected === option.part_id;
          return (
            <label
              key={option.part_id}
              htmlFor={inputId}
              className={`flex gap-2 rounded border p-2 text-sm transition-colors ${checked ? "border-amber-400 bg-zinc-900" : "border-zinc-800"} ${reason ? "cursor-not-allowed opacity-60" : "cursor-pointer hover:border-zinc-500"}`}
            >
              <input
                id={inputId}
                type="radio"
                name={name}
                value={option.part_id}
                checked={checked}
                disabled={disabled || reason !== null}
                aria-describedby={reason ? `${inputId}-reason` : undefined}
                onChange={() => onSelect(option.part_id)}
                className="mt-0.5 accent-amber-400"
              />
              <span>
                <span className="block font-medium">{option.label}</span>
                {effects.length > 0 && (
                  <ul className="mt-1 text-xs text-zinc-300">
                    {effects.map(([key, amount]) => (
                      <li key={key}>{describeEffect(key, amount)}</li>
                    ))}
                  </ul>
                )}
                {reason && (
                  <span id={`${inputId}-reason`} className="mt-1 block text-xs text-amber-200">
                    {reason}
                  </span>
                )}
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
