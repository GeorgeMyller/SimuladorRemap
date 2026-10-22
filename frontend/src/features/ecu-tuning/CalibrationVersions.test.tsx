/* eslint-disable @typescript-eslint/require-await -- mocks assíncronos */
/** T197 — CalibrationVersions e diff célula a célula entre duas versões; reverter cria N+1 (tuning RF-16; Fluxo C; D-15). */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CalibrationVersions } from "./CalibrationVersions";
import { calibrationFixture, CAL_ID, makeApi } from "./test-utils/fixtures";
import { loadedStore, renderWorkspace } from "./test-utils/harness";
import type { Calibration } from "./types";

beforeEach(() => localStorage.clear());

function versionsPair(): { v5: Calibration; v6: Calibration } {
  const v5 = calibrationFixture({ version: 5 });
  const v6 = structuredClone(calibrationFixture({ version: 6 }));
  const ve = v6.tables.ve!.values as number[][];
  ve[4]![9] = 92.5;
  ve[4]![10] = 94;
  ve[5]![9] = 10;
  return { v5, v6 };
}

describe("CalibrationVersions (RF-16)", () => {
  it("duas versões que diferem em 3 células mostram '3 células alteradas' com antes → depois", async () => {
    const { v5, v6 } = versionsPair();
    const fetchVersion = vi.fn(async (v: number) => (v === 5 ? v5 : v6));
    render(<CalibrationVersions versions={calibrationFixture().versions!} currentVersion={6} fetchVersion={fetchVersion} onRevert={vi.fn()} />);
    expect(screen.getAllByRole("row")).toHaveLength(3);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Comparar A × B" }));
    });
    expect(fetchVersion).toHaveBeenCalledWith(5);
    expect(fetchVersion).toHaveBeenCalledWith(6);
    expect(screen.getByTestId("diff-summary")).toHaveTextContent("3 células alteradas");
    const cells = [...document.querySelectorAll("[data-diff-cell]")].map((e) => e.getAttribute("data-diff-cell"));
    expect(cells).toEqual(["ve:4,9", "ve:4,10", "ve:5,9"]);
    expect(document.querySelector('[data-diff-cell="ve:4,9"]')).toHaveTextContent(/73[.,]00 → 92[.,]50/);
  });

  it("estratégias entram no diff por caminho", async () => {
    const a = calibrationFixture({ version: 5 });
    const b = calibrationFixture({ version: 6, strategies: { rev_limiter: { ...a.strategies.rev_limiter!, hard_rpm: 7400 } } });
    render(<CalibrationVersions versions={calibrationFixture().versions!} currentVersion={6} fetchVersion={async (v) => (v === 5 ? a : b)} onRevert={vi.fn()} />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Comparar A × B" }));
    });
    expect(document.querySelector('[data-diff-path="rev_limiter.hard_rpm"]')).toHaveTextContent("7000 → 7400");
    expect(screen.getByTestId("diff-summary")).toHaveTextContent("0 células alteradas · 1 parâmetro alterado");
  });

  it("reverter chama PUT {base_version, revert_to_version} e cria a versão N+1", async () => {
    const api = makeApi();
    const store = await loadedStore(api);
    await act(async () => {
      await store.revertTo(5);
    });
    expect(api.putCalibration).toHaveBeenCalledWith(CAL_ID, { base_version: 6, revert_to_version: 5, change_summary: "reverter para a versão 5" });
    expect(store.getSnapshot().calibration!.version).toBe(7);
    expect(store.queue!.version).toBe(7);
    store.stop();
  });

  it("no workspace: Versões → Reverter oferece 'Aplicar à sessão'", async () => {
    const api = makeApi();
    renderWorkspace(api);
    await screen.findByTestId("workspace-profile");
    fireEvent.click(screen.getByRole("button", { name: "Versões" }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Reverter para 5" }));
    });
    await waitFor(() => expect(screen.getByTestId("revision")).toHaveTextContent("7"));
    expect(api.putCalibration).toHaveBeenCalledWith(CAL_ID, expect.objectContaining({ revert_to_version: 5 }));
  });

  it("sem versões mostra o estado vazio", () => {
    render(<CalibrationVersions versions={[]} currentVersion={1} fetchVersion={vi.fn()} onRevert={vi.fn()} />);
    expect(screen.getByText("Sem versões anteriores.")).toBeInTheDocument();
  });
});
