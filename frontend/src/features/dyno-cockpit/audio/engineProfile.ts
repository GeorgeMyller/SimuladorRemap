/** Perfil de áudio por veículo (RF-20; T051): arquitetura, ordem de ignição e arquétipo de timbre. */
import type { Vehicle } from "../api";

import type { EngineProfile } from "./AudioEngine";
import { archetypeFor } from "./archetypes";

function pulleyRatioOf(vehicle: Vehicle): number | undefined {
  const sc = (vehicle as { supercharger?: { pulley_ratio?: unknown } | null }).supercharger;
  return typeof sc?.pulley_ratio === "number" ? sc.pulley_ratio : undefined;
}

export function engineProfileFor(vehicle: Vehicle): EngineProfile {
  const { engine } = vehicle;
  const profile: EngineProfile = {
    nCyl: engine.n_cyl,
    architecture: engine.architecture,
    firingOrder: engine.firing_order,
    turbo: vehicle.induction === "turbo",
    archetype: archetypeFor(vehicle.vehicle_id, { nCyl: engine.n_cyl, architecture: engine.architecture, induction: vehicle.induction }),
  };
  const pulley = pulleyRatioOf(vehicle);
  if (pulley !== undefined) profile.pulleyRatio = pulley;
  return profile;
}
