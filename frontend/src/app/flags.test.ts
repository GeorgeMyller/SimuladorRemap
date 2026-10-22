import { describe, expect, it } from "vitest";

import { flagEnabled, readFeatureFlags } from "./flags";

describe("flags de funcionalidade", () => {
  it.each([
    [undefined, true],
    ["", true],
    ["true", true],
    ["1", true],
    ["false", false],
    [" OFF ", false],
    ["0", false],
    [false, false],
    [true, true],
  ])("flagEnabled(%j) = %s", (raw, expected) => {
    expect(flagEnabled(raw)).toBe(expected);
  });

  it("lê VITE_FEATURE_DYNO_COCKPIT e VITE_FEATURE_ECU_TUNING", () => {
    expect(readFeatureFlags({})).toEqual({ dynoCockpit: true, ecuTuning: true });
    expect(readFeatureFlags({ VITE_FEATURE_DYNO_COCKPIT: "false", VITE_FEATURE_ECU_TUNING: "0" })).toEqual({ dynoCockpit: false, ecuTuning: false });
  });
});
