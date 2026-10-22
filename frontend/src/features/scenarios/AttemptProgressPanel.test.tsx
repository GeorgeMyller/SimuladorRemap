/* eslint-disable @typescript-eslint/require-await -- mocks assíncronos */
/** 003 T023 — declaração de defeito no painel da tentativa: o enum segue o backend (inclui `boost_leak`). */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { DefectKind as ApiDefectKind } from "@/lib/api/generated/model";

import { ScenariosApiContext } from "./api";
import { AttemptProgressPanel } from "./AttemptProgressPanel";
import { attempt, makeApi, renderWithApi, STAGE1 } from "./test-utils/fixtures";
import { DEFECT_KINDS, DEFECT_LABELS } from "./types";
import { IN_PROGRESS_POLL_MS } from "./useAttempt";

describe("defeitos declaráveis", () => {
  it("DEFECT_KINDS cobre exatamente o enum DefectKind do OpenAPI, todos com rótulo", () => {
    expect([...DEFECT_KINDS].sort()).toEqual(Object.values(ApiDefectKind).sort());
    for (const kind of DEFECT_KINDS) expect(DEFECT_LABELS[kind]).toBeTruthy();
  });
});

describe("AttemptProgressPanel: submissão com defeito declarado", () => {
  it("no cenário defect-boost-leak declara boost_leak e envia na submissão", async () => {
    const submit = vi.fn(async () => ({ attempt_id: "att-1", submission_index: 1, evaluation_status: "pending" as const }));
    const api = makeApi({
      getAttempt: vi.fn(async () => attempt({ scenario_id: "defect-boost-leak", scenario_title: "Diagnóstico: vazamento" })),
      getScenario: vi.fn(async () => ({ ...STAGE1, scenario_id: "defect-boost-leak", has_hidden_defect: true })),
      submit,
    });
    renderWithApi(<AttemptProgressPanel attemptId="att-1" pollMs={60_000} />, api);

    const select = await screen.findByRole("combobox", { name: "Defeito diagnosticado" });
    expect(screen.getByRole("option", { name: "Vazamento no circuito de pressão" })).toBeInTheDocument();
    await userEvent.selectOptions(select, "boost_leak");
    await userEvent.click(screen.getByRole("button", { name: "Submeter" }));

    await waitFor(() => expect(submit).toHaveBeenCalledWith("att-1", { calibration_id: "cal-1", declared_defect: "boost_leak" }));
  });

  it("submete a calibração da última puxada válida (após swap/Base Setup), não o clone inicial", async () => {
    const submit = vi.fn(async () => ({ attempt_id: "att-1", submission_index: 1, evaluation_status: "pending" as const }));
    const getRunCalibrationId = vi.fn(async () => "cal-standalone");
    const base = attempt();
    const runs = [...base.runs, { ...base.runs[0]!, run_id: "01JABCDEFGHJKMNPQRSTVWXYZ2", run_type: "multi_pull" as const, pull_index: 1 }, { ...base.runs[1]! }];
    const api = makeApi({ submit, getRunCalibrationId, getAttempt: vi.fn(async () => attempt({ runs })) });
    renderWithApi(<AttemptProgressPanel attemptId="att-1" pollMs={60_000} />, api);

    await userEvent.click(await screen.findByRole("button", { name: "Submeter" }));

    await waitFor(() => expect(submit).toHaveBeenCalledWith("att-1", { calibration_id: "cal-standalone" }));
    // A última da lista é inválida: vale a anterior (multi_pull válida).
    expect(getRunCalibrationId).toHaveBeenCalledWith("01JABCDEFGHJKMNPQRSTVWXYZ2");
  });

  it("sem resposta da puxada cai na calibração da tentativa", async () => {
    const submit = vi.fn(async () => ({ attempt_id: "att-1", submission_index: 1, evaluation_status: "pending" as const }));
    const api = makeApi({ submit, getRunCalibrationId: vi.fn(() => Promise.reject(new Error("offline"))) });
    renderWithApi(<AttemptProgressPanel attemptId="att-1" pollMs={60_000} />, api);

    await userEvent.click(await screen.findByRole("button", { name: "Submeter" }));

    await waitFor(() => expect(submit).toHaveBeenCalledWith("att-1", { calibration_id: "cal-1" }));
  });
});

describe("AttemptProgressPanel: atualização com a tentativa em curso", () => {
  it("recarrega a tentativa quando a bancada termina uma puxada (refreshKey)", async () => {
    const getAttempt = vi.fn(async () => attempt());
    const api = makeApi({ getAttempt });
    const { rerender } = renderWithApi(<AttemptProgressPanel attemptId="att-1" pollMs={60_000} refreshKey={null} />, api);
    await screen.findByRole("button", { name: "Submeter" });
    expect(getAttempt).toHaveBeenCalledTimes(1);
    rerender(
      <ScenariosApiContext.Provider value={api}>
        <MemoryRouter>
          <AttemptProgressPanel attemptId="att-1" pollMs={60_000} refreshKey="01RUN:completed" />
        </MemoryRouter>
      </ScenariosApiContext.Provider>,
    );
    await waitFor(() => expect(getAttempt).toHaveBeenCalledTimes(2));
  });

  it("em in_progress volta a ler a tentativa a cada 10 s (puxadas feitas noutra aba)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const getAttempt = vi.fn(async () => attempt());
      renderWithApi(<AttemptProgressPanel attemptId="att-1" />, makeApi({ getAttempt }));
      await screen.findByRole("button", { name: "Submeter" });
      expect(getAttempt).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(IN_PROGRESS_POLL_MS + 50);
      await waitFor(() => expect(getAttempt).toHaveBeenCalledTimes(2));
    } finally {
      vi.useRealTimers();
    }
  });
});
