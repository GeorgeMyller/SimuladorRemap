/**
 * Tipos e regras puras da oficina de upgrades (002 RF-13, RF-18, RF-19; interfaces/sessions-upgrades-flex.md).
 * O pacote fica todo de série por padrão; só peças diferentes de `stock` e o Flex ligado vão no POST.
 */
import type { SessionCreateRequest, UpgradeCategoryOptions, UpgradePackage } from "@/lib/api/generated/model";

export type UpgradeCategory = UpgradeCategoryOptions["category"];
export type { UpgradeCategoryOptions };

export const UPGRADE_CATEGORIES: readonly UpgradeCategory[] = [
  "turbo",
  "injectors",
  "fuel_pump",
  "intercooler",
  "downpipe",
  "internals",
];

export const STOCK_PART = "stock";
export const ETHANOL_MIN_PCT = 27;
export const ETHANOL_MAX_PCT = 100;
export const ETHANOL_DEFAULT_PCT = 85;

/** O que o veículo aceita (lido de `GET /vehicles/{id}`). */
export interface VehicleCompat {
  vehicleId: string;
  hasTurbo: boolean;
  hasIntercooler: boolean;
  /** Flex só existe com E27 e E100 permitidos no veículo. */
  flexAllowed: boolean;
}

export type PartSelection = Record<UpgradeCategory, string>;

export interface StageSelection {
  parts: PartSelection;
  /** `null` = Flex desligado. */
  ethanolPct: number | null;
}

export const STOCK_SELECTION: StageSelection = {
  parts: { turbo: STOCK_PART, injectors: STOCK_PART, fuel_pump: STOCK_PART, intercooler: STOCK_PART, downpipe: STOCK_PART, internals: STOCK_PART },
  ethanolPct: null,
};

export const CATEGORY_LABEL: Record<UpgradeCategory, string> = {
  turbo: "Turbina",
  injectors: "Bicos injetores",
  fuel_pump: "Bomba de combustível",
  intercooler: "Intercooler",
  downpipe: "Downpipe",
  internals: "Internos do motor",
};

/** Motivo de a peça não servir no veículo, ou `null` se serve. A peça de série sempre serve. */
export function incompatibilityReason(category: UpgradeCategory, partId: string, compat: VehicleCompat): string | null {
  if (partId === STOCK_PART) return null;
  if (category === "turbo" && !compat.hasTurbo) return "Só para motor turbo.";
  if (category === "intercooler" && !compat.hasIntercooler) return "O motor não tem intercooler.";
  return null;
}

/** Campos do `POST /sessions`: omite o pacote todo de série e o Flex desligado. */
export function toSessionFields(selection: StageSelection): Pick<SessionCreateRequest, "upgrades" | "ethanol_pct"> {
  const changed = UPGRADE_CATEGORIES.filter((category) => selection.parts[category] !== STOCK_PART);
  const fields: Pick<SessionCreateRequest, "upgrades" | "ethanol_pct"> = {};
  if (changed.length > 0) {
    fields.upgrades = Object.fromEntries(changed.map((category) => [category, selection.parts[category]]));
  }
  if (selection.ethanolPct !== null) fields.ethanol_pct = selection.ethanolPct;
  return fields;
}

/** Peças instaladas na sessão (`SimulationSession.upgrades`; categoria ausente = série). */
export function partsFromPackage(pkg: UpgradePackage | null | undefined): PartSelection {
  const parts = { ...STOCK_SELECTION.parts };
  for (const category of UPGRADE_CATEGORIES) {
    const part = pkg?.[category];
    if (part) parts[category] = part;
  }
  return parts;
}

/** Corpo do `PUT /sessions/{id}/upgrades`: o pacote completo substitui o instalado. */
export function toUpgradePackage(parts: PartSelection): UpgradePackage {
  return Object.fromEntries(UPGRADE_CATEGORIES.map((category) => [category, parts[category]]));
}

/** Categorias em que a escolha difere das peças instaladas. */
export function changedCategories(installed: PartSelection, chosen: PartSelection): UpgradeCategory[] {
  return UPGRADE_CATEGORIES.filter((category) => installed[category] !== chosen[category]);
}

const EFFECT_LABEL: Record<string, string> = {
  turbine_area_eff_scale: "Área efetiva da turbina",
  compressor_flow_scale: "Vazão do compressor",
  compressor_n_peak_scale: "Rotação de pico do compressor",
  rotor_inertia_scale: "Inércia do rotor (mais lag)",
  wastegate_area_scale: "Área da wastegate",
  injector_flow_scale: "Vazão dos bicos",
  fuel_pump_capacity_scale: "Capacidade da bomba",
  intercooler_effectiveness_add: "Efetividade do intercooler",
  exhaust_backpressure_scale: "Contrapressão do escape",
  max_rod_load_scale: "Carga máxima da biela",
  rod_torque_limit_scale: "Torque sustentado da biela",
  max_cylinder_pressure_scale: "Pressão máxima no cilindro",
  max_piston_temp_add_c: "Temperatura máxima do pistão",
};

const number = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 });

/** Texto de um efeito: `_scale` é fator (×1,25); `_add` é soma (+0,08, +40 °C). */
export function describeEffect(key: string, value: number): string {
  const label = EFFECT_LABEL[key] ?? key;
  if (key.endsWith("_scale")) return `${label} ×${number.format(value)}`;
  const unit = key.endsWith("_c") ? " °C" : "";
  return `${label} +${number.format(value)}${unit}`;
}

/** Mensagem clara para os erros da criação de sessão ligados à oficina e ao Flex. */
export function stageErrorText(code: string, extra: Record<string, unknown> = {}): string | null {
  if (code === "FUEL_NOT_ALLOWED") {
    return "Este carro não aceita Flex Fuel: ele precisa permitir E27 e E100. Desligue o Flex ou escolha outro carro.";
  }
  if (code === "UPGRADE_NOT_COMPATIBLE") {
    const category = typeof extra.category === "string" ? CATEGORY_LABEL[extra.category as UpgradeCategory] : undefined;
    const part = category ? `A peça de ${category.toLowerCase()}` : "Uma peça escolhida";
    return `${part} não serve neste carro. Volte essa categoria para Série.`;
  }
  return null;
}
