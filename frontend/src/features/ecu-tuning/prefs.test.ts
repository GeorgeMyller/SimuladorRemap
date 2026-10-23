/** T191 — preferências `simremap.ecu-tuning.prefs.v1`, rascunho por `calibration_id` e λ em AFR (tuning RF-22, EC-15; data-model 4.3). */
import { act, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { beforeEach, describe, expect, it } from "vitest";

import {
  afrToLambda,
  clearDraft,
  DEFAULT_PREFS,
  draftKey,
  isLambdaTable,
  lambdaToAfr,
  loadDraft,
  loadPrefs,
  PREFS_KEY,
  saveDraft,
  savePrefs,
} from "./prefs";
import { TableEditor3D } from "./TableEditor3D";
import { CAL_ID, makeApi } from "./test-utils/fixtures";
import { cellAt, loadedStore } from "./test-utils/harness";

beforeEach(() => localStorage.clear());

describe("preferências (data-model 4.3)", () => {
  it("padrão sem chave e round-trip com a chave versionada", () => {
    expect(loadPrefs(localStorage)).toEqual(DEFAULT_PREFS);
    savePrefs({ version: 1, heatmap: "off", lambdaDisplay: "afr", show3d: "below", autoApply: "off" }, localStorage);
    expect(JSON.parse(localStorage.getItem(PREFS_KEY)!)).toMatchObject({ lambdaDisplay: "afr" });
    expect(loadPrefs(localStorage)).toEqual({ version: 1, heatmap: "off", lambdaDisplay: "afr", show3d: "below", autoApply: "off" });
  });

  it("JSON inválido ou versão diferente cai no padrão; campo inválido usa o padrão do campo", () => {
    localStorage.setItem(PREFS_KEY, "{oops");
    expect(loadPrefs(localStorage)).toEqual(DEFAULT_PREFS);
    localStorage.setItem(PREFS_KEY, JSON.stringify({ version: 2 }));
    expect(loadPrefs(localStorage)).toEqual(DEFAULT_PREFS);
    localStorage.setItem(PREFS_KEY, JSON.stringify({ version: 1, heatmap: "x", lambdaDisplay: "afr", show3d: "side" }));
    expect(loadPrefs(localStorage)).toEqual({ version: 1, heatmap: "on", lambdaDisplay: "afr", show3d: "side", autoApply: "on" });
  });

  it("sem storage não lança", () => {
    expect(loadPrefs(null)).toEqual(DEFAULT_PREFS);
    expect(() => savePrefs(DEFAULT_PREFS, null)).not.toThrow();
  });
});

describe("rascunho por calibration_id", () => {
  it("grava, lê e limpa em simremap.ecu-tuning.draft.<id>", () => {
    saveDraft({ version: 1, calibration_id: "c1", base_version: 3, tables: { ve: [{ row: 1, col: 2, value: 90 }] } }, localStorage);
    expect(localStorage.getItem(draftKey("c1"))).not.toBeNull();
    expect(draftKey("c1")).toBe("simremap.ecu-tuning.draft.c1");
    const loaded = loadDraft("c1", localStorage);
    expect(loaded).toEqual({ kind: "ok", draft: { version: 1, calibration_id: "c1", base_version: 3, tables: { ve: [{ row: 1, col: 2, value: 90 }] } } });
    expect(loadDraft("c2", localStorage)).toEqual({ kind: "none" });
    clearDraft("c1", localStorage);
    expect(loadDraft("c1", localStorage)).toEqual({ kind: "none" });
  });

  it("rascunho sem células remove a chave", () => {
    localStorage.setItem(draftKey("c1"), "x");
    saveDraft({ version: 1, calibration_id: "c1", base_version: 3, tables: { ve: [] } }, localStorage);
    expect(localStorage.getItem(draftKey("c1"))).toBeNull();
  });

  it("JSON corrompido é descartado (EC-15)", () => {
    localStorage.setItem(draftKey("c1"), "{not json");
    expect(loadDraft("c1", localStorage)).toEqual({ kind: "corrupt" });
    expect(localStorage.getItem(draftKey("c1"))).toBeNull();
  });

  it("o workspace restaura o rascunho válido e avisa; corrompido é descartado com aviso", async () => {
    saveDraft({ version: 1, calibration_id: CAL_ID, base_version: 6, tables: { ve: [{ row: 0, col: 0, value: 99 }] } }, localStorage);
    const store = await loadedStore();
    expect(store.getSnapshot().tables.ve!.values[0]![0]).toBe(99);
    expect(store.getSnapshot().notices.map((n) => n.text).join(" ")).toContain("Rascunho local restaurado");
    store.stop();

    localStorage.setItem(draftKey(CAL_ID), "{corrupto");
    const s2 = await loadedStore();
    expect(s2.getSnapshot().tables.ve!.values[0]![0]).toBe(60);
    expect(s2.getSnapshot().notices.some((n) => n.text.includes("corrompido"))).toBe(true);
    s2.stop();
  });
});

describe("lambda em AFR (RF-22)", () => {
  it("lambda 0,85 com E27 (13,2) mostra AFR 11,2", () => {
    expect(lambdaToAfr(0.85, 13.2)).toBeCloseTo(11.22, 6);
    expect(afrToLambda(11.22, 13.2)).toBeCloseTo(0.85, 6);
    expect(isLambdaTable("lambda_target")).toBe(true);
    expect(isLambdaTable("ve")).toBe(false);
  });

  it("a grade exibe AFR e o valor gravado continua em lambda", async () => {
    const api = makeApi();
    const store = await loadedStore(api);
    store.setPrefs({ lambdaDisplay: "afr" });
    render(createElement(TableEditor3D, { store, tableId: "lambda_target", title: "Lambda alvo" }));
    expect(cellAt(0, 0)).toHaveTextContent(/^11[,.]2$/);
    expect(screen.getByRole("grid", { name: /AFR/ })).toBeInTheDocument();
    act(() => {
      store.editCell("lambda_target", 0, 0, 13.2);
    });
    expect(store.getSnapshot().tables.lambda_target!.values[0]![0]).toBeCloseTo(1, 6);
    expect(JSON.parse(localStorage.getItem(PREFS_KEY)!)).toMatchObject({ lambdaDisplay: "afr" });
    store.stop();
  });
});
