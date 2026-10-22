/** T176 — `simremap.cockpit.prefs.v1`: JSON inválido volta aos padrões (data-model 4.3). */
import { beforeEach, describe, expect, it } from "vitest";

import { buildSubscription } from "./channels";
import { DEFAULT_PREFS, loadPrefs, PREFS_KEY, savePrefs, visibleForSubscription } from "./prefs";

describe("prefs da cockpit", () => {
  beforeEach(() => localStorage.clear());

  it("sem chave devolve os padrões (whp, bar, áudio desligado, volume 60 %)", () => {
    const p = loadPrefs(localStorage);
    expect(p).toEqual(DEFAULT_PREFS);
    expect(p.units.power).toBe("whp");
    expect(p.units.boost).toBe("bar");
    expect(p.audio).toEqual({ enabled: false, muted: false, volume: 0.6 });
  });

  it("JSON inválido, versão diferente ou campos fora do schema voltam aos padrões", () => {
    for (const raw of ["{nao json", JSON.stringify({ ...DEFAULT_PREFS, version: 2 }), JSON.stringify({ ...DEFAULT_PREFS, units: { power: "hp" } }), "null", "[]"]) {
      localStorage.setItem(PREFS_KEY, raw);
      expect(loadPrefs(localStorage)).toEqual(DEFAULT_PREFS);
    }
  });

  it("grava e relê na chave versionada", () => {
    const next = { ...DEFAULT_PREFS, units: { ...DEFAULT_PREFS.units, power: "kW" as const }, audio: { enabled: true, muted: true, volume: 0.3 } };
    savePrefs(next, localStorage);
    expect(JSON.parse(localStorage.getItem(PREFS_KEY)!)).toEqual(next);
    expect(loadPrefs(localStorage)).toEqual(next);
  });

  it("storage indisponível não lança", () => {
    const broken = {
      getItem: () => {
        throw new Error("bloqueado");
      },
      setItem: () => {
        throw new Error("quota");
      },
    } as unknown as Storage;
    expect(loadPrefs(broken)).toEqual(DEFAULT_PREFS);
    expect(() => savePrefs(DEFAULT_PREFS, broken)).not.toThrow();
    expect(loadPrefs(null)).toEqual(DEFAULT_PREFS);
  });
});

describe("subscrição por painel visível (RF-02)", () => {
  it("só a aba inferior ativa é visível; recolher o espectrograma tira os canais de espectro", () => {
    const visible = visibleForSubscription(DEFAULT_PREFS);
    expect(visible).toContain("spectrogram");
    const sub = buildSubscription({ visiblePanels: visible, nCyl: 4, audioActive: false, pressureCylinder: 1 });
    expect(sub.spectrum).toBe(true);
    expect(sub.channels).toContain("knock_sensor_v_cyl4");
    expect(sub.channels).toContain("knock_intensity_cyl1");
    const collapsed = visibleForSubscription({ ...DEFAULT_PREFS, visiblePanels: DEFAULT_PREFS.visiblePanels.filter((p) => p !== "bottom") });
    const sub2 = buildSubscription({ visiblePanels: collapsed, nCyl: 4, audioActive: false, pressureCylinder: 1 });
    expect(sub2.spectrum).toBe(false);
    expect(sub2.channels.some((c) => c.startsWith("knock_sensor_v") || c.startsWith("knock_intensity"))).toBe(false);
  });

  it("áudio ativo acrescenta turbo_rpm; pressão pede o cilindro; resolução pequena reduz", () => {
    const sub = buildSubscription({ visiblePanels: ["pressure"], nCyl: 4, audioActive: true, pressureCylinder: 3 });
    expect(sub.channels).toContain("turbo_rpm");
    expect(sub.pressure_trace).toEqual({ cylinder: 3 });
    const reduced = buildSubscription({ visiblePanels: ["dyno"], nCyl: 4, audioActive: true, pressureCylinder: 1, reduced: true });
    expect(reduced.channels).toEqual(["rpm"]);
  });
});
