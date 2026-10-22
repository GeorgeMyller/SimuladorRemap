/** RF-22/RF-25/RF-26 — tabela da turma: ordenação por coluna, filtros, erros, replay e export RFC 4180. */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ClassGradeTable, displayNickname, toGradeRow } from "./ClassGradeTable";
import { attempt, evaluation, makeApi, problem, renderWithApi } from "./test-utils/fixtures";
import type { AttemptView } from "./types";

const ROWS: AttemptView[] = [
  attempt({
    attempt_id: "att-a",
    origin: "imported",
    nickname: "bruno",
    producer_install_id: "ffff0000-0000-4000-8000-000000000000",
    scenario_id: "stage2-pops-bangs",
    scenario_title: "",
    imported_at: "2026-10-18T12:00:00Z",
    replay_status: "running",
    evaluation_mismatch: true,
    last_evaluation: evaluation({ attempt_id: "att-a", passed: true, total_score: 90, submission_index: 2 }),
  }),
  attempt({
    attempt_id: "att-b",
    origin: "imported",
    nickname: "ana",
    producer_install_id: null,
    scenario_id: "stage1-oem",
    imported_at: null,
    replay_status: "verified",
    submissions: 0,
    last_evaluation: null,
  }),
  attempt({
    attempt_id: "att-c",
    origin: "imported",
    nickname: "carla",
    producer_install_id: "aaaa0000-0000-4000-8000-000000000000",
    scenario_id: "stage1-oem",
    imported_at: "2026-10-18T09:00:00Z",
    replay_status: "incompatible_version",
    last_evaluation: evaluation({ attempt_id: "att-c", passed: false, total_score: 40, submission_index: 1 }),
  }),
];

const firstId = () => screen.getAllByRole("row")[1]!.getAttribute("data-attempt");

const createObjectURL = vi.fn(() => "blob:x");

beforeEach(() => {
  createObjectURL.mockClear();
  Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
});

describe("ClassGradeTable — ordenação e filtros", () => {
  it("ordena por todas as colunas nos dois sentidos", async () => {
    renderWithApi(<ClassGradeTable />, makeApi({ listAttempts: vi.fn(() => Promise.resolve({ items: ROWS, next_cursor: null })) }));
    expect(await screen.findByText("3 linhas")).toBeInTheDocument();
    expect(firstId()).toBe("att-b"); // aluno (padrão): ana, bruno (ffff), carla (aaaa)
    const expected: Record<string, [string, string]> = {
      Aluno: ["att-c", "att-b"],
      Cenário: ["att-b", "att-a"],
      Submissão: ["att-b", "att-a"],
      Resultado: ["att-b", "att-a"],
      Pontuação: ["att-b", "att-a"],
      "Avaliação divergente": ["att-b", "att-a"],
      Replay: ["att-c", "att-b"],
      "Importado em": ["att-b", "att-a"],
    };
    for (const [label, [asc, desc]] of Object.entries(expected)) {
      const header = () => screen.getByRole("button", { name: label });
      await userEvent.click(header());
      if (label === "Aluno") {
        // Já ordenado por aluno: o 1.º clique inverte.
        expect(firstId()).toBe(asc);
        await userEvent.click(header());
        expect(firstId()).toBe(desc);
        continue;
      }
      expect(header().closest("th")).toHaveAttribute("aria-sort", "ascending");
      expect(firstId()).toBe(asc);
      await userEvent.click(header());
      expect(header().closest("th")).toHaveAttribute("aria-sort", "descending");
      expect(firstId()).toBe(desc);
    }
  });

  it("filtra por aprovados e reprovados e mostra os textos de replay e importação", async () => {
    renderWithApi(<ClassGradeTable />, makeApi({ listAttempts: vi.fn(() => Promise.resolve({ items: ROWS, next_cursor: null })) }));
    await screen.findByText("3 linhas");
    expect(screen.getByText("em execução")).toBeInTheDocument();
    expect(screen.getByText("versão incompatível")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Replay da tentativa de bruno (ffff)" })).toBeDisabled();
    const anaRow = screen.getByRole("button", { name: "Replay da tentativa de ana" }).closest("tr")!;
    expect(within(anaRow).getAllByText("—").length).toBeGreaterThanOrEqual(1);
    await userEvent.selectOptions(screen.getByLabelText("Resultado"), "passed");
    expect(screen.getByText("1 linhas")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Resultado"), "failed");
    expect(screen.getByText("2 linhas")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Resultado"), "all");
    expect(screen.getByText("3 linhas")).toBeInTheDocument();
  });

  it("export RFC 4180 com cenário cujo briefing falha usa só as colunas base", async () => {
    const getScenario = vi.fn(() => Promise.reject(problem(404, "SCENARIO_NOT_FOUND")));
    renderWithApi(<ClassGradeTable />, makeApi({ listAttempts: vi.fn(() => Promise.resolve({ items: ROWS, next_cursor: null })), getScenario }));
    await screen.findByText("3 linhas");
    await userEvent.selectOptions(screen.getByLabelText("Cenário"), "stage1-oem");
    expect(screen.getByText("2 linhas")).toBeInTheDocument();
    expect(getScenario).toHaveBeenCalledWith("stage1-oem");
    await userEvent.click(screen.getByRole("button", { name: "Exportar CSV (RFC 4180)" }));
    expect(createObjectURL).toHaveBeenCalled();
  });
});

describe("ClassGradeTable — erros", () => {
  it("falha ao listar mostra o erro e 'Tentar de novo' recarrega", async () => {
    const listAttempts = vi
      .fn()
      .mockRejectedValueOnce(problem(503, "DATABASE_UNAVAILABLE"))
      .mockResolvedValue({ items: ROWS, next_cursor: null });
    renderWithApi(<ClassGradeTable />, makeApi({ listAttempts }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("DATABASE_UNAVAILABLE");
    await userEvent.click(within(alert).getByRole("button"));
    expect(await screen.findByText("3 linhas")).toBeInTheDocument();
  });

  it("falha no replay aparece sobre a tabela", async () => {
    const replay = vi.fn(() => Promise.reject(problem(409, "REPLAY_ALREADY_RUNNING")));
    renderWithApi(<ClassGradeTable />, makeApi({ listAttempts: vi.fn(() => Promise.resolve({ items: ROWS, next_cursor: null })), replay }));
    await screen.findByText("3 linhas");
    await userEvent.click(screen.getByRole("button", { name: "Replay da tentativa de ana" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("REPLAY_ALREADY_RUNNING");
  });
});

describe("toGradeRow e displayNickname", () => {
  it("sem avaliação usa o nº de submissões e notas nulas; sem estação mostra só o apelido", () => {
    const row = toGradeRow(ROWS[1]!);
    expect(row).toMatchObject({ submission: 0, passed: null, total_score: null, scores: {} });
    expect(displayNickname(ROWS[1]!)).toBe("ana");
    expect(displayNickname(ROWS[0]!)).toBe("bruno (ffff)");
  });
});
