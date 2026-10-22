import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ClassGradeTable } from "./ClassGradeTable";
import { InstructorPanel } from "./InstructorPanel";
import { MAX_PARALLEL_UPLOADS, PackageImportQueue } from "./PackageImportQueue";
import { attempt, evaluation, INSTRUCTOR, makeApi, problem, renderWithApi, result, STAGE1, STUDENT } from "./test-utils/fixtures";
import { ACTIVE_PROFILE_KEY, type PackageImportResult } from "./types";

const TAMPERED = new Set([7, 31]);

function files(n = 50): File[] {
  return Array.from({ length: n }, (_, i) => {
    const body = JSON.stringify({ format_version: 1, kind: "attempt", payload: { i }, sha256: TAMPERED.has(i) ? "0".repeat(64) : "f".repeat(64) });
    return new File([body], `aluno-${i}.simremap.json`, { type: "application/json" });
  });
}

function concurrencyApi() {
  let active = 0;
  let peak = 0;
  const bodies: string[] = [];
  const importPackage = vi.fn(async (raw: string): Promise<PackageImportResult> => {
    bodies.push(raw);
    active += 1;
    peak = Math.max(peak, active);
    await new Promise((r) => setTimeout(r, 1));
    active -= 1;
    const parsed = JSON.parse(raw) as { payload: { i: number }; sha256: string };
    if (parsed.sha256 === "0".repeat(64)) throw problem(422, "PACKAGE_HASH_MISMATCH", "hash inválido");
    return {
      package_sha256: "f".repeat(64),
      kind: "attempt",
      scenario_id: "stage1-oem",
      attempt_id: `att-${parsed.payload.i}`,
      already_imported: false,
      evaluation_mismatch: false,
      recomputed_evaluation: null,
    };
  });
  return { importPackage, bodies, peak: () => peak };
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem(ACTIVE_PROFILE_KEY, INSTRUCTOR.profile_id);
});

describe("PackageImportQueue", () => {
  it("50 ficheiros com 2 adulterados: 48 importados, 2 recusados com PACKAGE_HASH_MISMATCH, no máximo 2 uploads em paralelo", async () => {
    const fake = concurrencyApi();
    const onFinished = vi.fn();
    renderWithApi(<PackageImportQueue onFinished={onFinished} />, makeApi({ importPackage: fake.importPackage }));
    const all = files();
    await userEvent.upload(screen.getByLabelText("Ficheiros de pacote"), all);
    await waitFor(() => expect(onFinished).toHaveBeenCalled(), { timeout: 5000 });
    expect(fake.importPackage).toHaveBeenCalledTimes(50);
    expect(fake.peak()).toBeLessThanOrEqual(MAX_PARALLEL_UPLOADS);
    expect(fake.peak()).toBe(2);
    expect(screen.getByText("48 importados, 0 já importados, 2 recusados.")).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "Estado por ficheiro" });
    const rejected = list.querySelectorAll('[data-status="rejected"]');
    expect(rejected).toHaveLength(2);
    for (const li of rejected) expect(within(li as HTMLElement).getByText("PACKAGE_HASH_MISMATCH")).toBeInTheDocument();
    expect(list.querySelectorAll('[data-status="imported"]')).toHaveLength(48);
    // O ficheiro vai tal como foi lido (sem reserializar).
    expect(fake.bodies).toContain(await all[0]!.text());
  });

  it("aceita arrastar-e-largar, marca já importado e limita a 50 ficheiros", async () => {
    const importPackage = vi.fn((): Promise<PackageImportResult> =>
      Promise.resolve({ package_sha256: "f".repeat(64), kind: "attempt", scenario_id: "stage1-oem", attempt_id: "a", already_imported: true, evaluation_mismatch: true, recomputed_evaluation: null }),
    );
    renderWithApi(<PackageImportQueue />, makeApi({ importPackage }));
    fireEvent.drop(screen.getByRole("region", { name: /Área de importação/ }), { dataTransfer: { files: files(52) } });
    await waitFor(() => expect(screen.getByText("0 importados, 50 já importados, 0 recusados.")).toBeInTheDocument(), { timeout: 5000 });
    expect(screen.getByText("Só os primeiros 50 ficheiros foram aceites.")).toBeInTheDocument();
    expect(screen.getAllByText("avaliação recalculada").length).toBe(50);
  });

  it("SCENARIO_VERSION_MISMATCH mostra 'cenário diferente do original'", async () => {
    const importPackage = vi.fn(() => Promise.reject(problem(409, "SCENARIO_VERSION_MISMATCH")));
    renderWithApi(<PackageImportQueue />, makeApi({ importPackage }));
    await userEvent.upload(screen.getByLabelText("Ficheiros de pacote"), files(1));
    expect(await screen.findByText("(cenário diferente do original)")).toBeInTheDocument();
  });
});

function imported(i: number) {
  return attempt({
    attempt_id: `att-${i}`,
    origin: "imported",
    profile_id: null,
    nickname: i % 2 ? "joao" : `aluno${String(i).padStart(2, "0")}`,
    producer_install_id: `${(i % 2 ? "a1b2" : "c3d4")}0000-0000-4000-8000-000000000000`,
    package_sha256: i.toString(16).padStart(64, "0"),
    imported_at: "2026-10-18T11:00:00Z",
    replay_status: i === 3 ? "mismatch" : "not_run",
    evaluation_mismatch: i === 5,
    last_evaluation: evaluation({
      attempt_id: `att-${i}`,
      passed: i % 4 !== 0,
      total_score: 50 + i,
      results: [result({ criterion_id: "delta-whp", kind: "min_delta_whp", score: 100 }), result({ criterion_id: "egt", score: i === 1 ? 76 : 100 })],
    }),
    scenario_title: i === 2 ? "=HYPERLINK(1)" : "Stage 1 OEM",
  });
}

describe("ClassGradeTable e InstructorPanel", () => {
  it("tabela com 48 linhas, ordenação, filtros, replay e CSV com 1 cabeçalho + 48 linhas", async () => {
    const rows = Array.from({ length: 48 }, (_, i) => imported(i));
    const listAttempts = vi
      .fn()
      .mockResolvedValueOnce({ items: rows.slice(0, 30), next_cursor: "c1" })
      .mockResolvedValue({ items: rows.slice(30), next_cursor: null });
    const replay = vi.fn(() => Promise.resolve({ attempt_id: "att-0", replay_status: "running" as const, runs_to_replay: 2 }));
    const blobs: Blob[] = [];
    Object.assign(URL, {
      createObjectURL: vi.fn((b: Blob) => {
        blobs.push(b);
        return "blob:x";
      }),
      revokeObjectURL: vi.fn(),
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    renderWithApi(<ClassGradeTable />, makeApi({ listAttempts, replay, getScenario: vi.fn(() => Promise.resolve(STAGE1)) }));
    expect(await screen.findByText("48 linhas")).toBeInTheDocument();
    expect(listAttempts).toHaveBeenCalledWith({ origin: "imported", limit: 200, cursor: "c1" });
    expect(screen.getAllByText("joao (a1b2)").length).toBe(24);
    expect(screen.getByText("replay divergente")).toBeInTheDocument();
    expect(screen.getByText("⚠ Sim (recalculada)")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Pontuação" }));
    let firstRow = screen.getAllByRole("row")[1]!;
    expect(firstRow).toHaveAttribute("data-attempt", "att-0");
    await userEvent.click(screen.getByRole("button", { name: /Pontuação/ }));
    firstRow = screen.getAllByRole("row")[1]!;
    expect(firstRow).toHaveAttribute("data-attempt", "att-47");

    await userEvent.selectOptions(screen.getByLabelText("Cenário"), "stage1-oem");
    await userEvent.click(screen.getByRole("button", { name: "Exportar CSV" }));
    const csv = await blobs[0]!.text();
    const lines = csv.trimEnd().split("\n");
    expect(lines).toHaveLength(49);
    expect(lines[0]).toMatch(/imported_at;score_delta-whp;score_egt;score_integrity$/);
    expect(csv).toContain(";a1b2;");

    await userEvent.selectOptions(screen.getByLabelText("Resultado"), "failed");
    expect(screen.getByText("12 linhas")).toBeInTheDocument();

    await userEvent.click(screen.getAllByRole("button", { name: /Replay da tentativa/ })[0]!);
    expect(replay).toHaveBeenCalled();
  });

  it("estado vazio da turma", async () => {
    renderWithApi(<ClassGradeTable />, makeApi());
    expect(await screen.findByText("Ainda sem tentativas importadas.")).toBeInTheDocument();
  });

  it("InstructorPanel: aluno não acede; instrutor cria desafio padrão e exporta", async () => {
    localStorage.setItem(ACTIVE_PROFILE_KEY, STUDENT.profile_id);
    const first = renderWithApi(<InstructorPanel />, makeApi());
    expect(await screen.findByText(/exige um perfil com papel/)).toBeInTheDocument();
    first.unmount();

    localStorage.setItem(ACTIVE_PROFILE_KEY, INSTRUCTOR.profile_id);
    const createScenario = vi.fn((body: { scenario: unknown }) => Promise.resolve({ ...STAGE1, ...(body.scenario as object), has_hidden_defect: false }));
    const exportPackage = vi.fn(() => Promise.resolve({ filename: "simremap-challenge-challenge-400whp-e27-12345678.simremap.json", content: "{}" }));
    Object.assign(URL, { createObjectURL: vi.fn(() => "blob:x"), revokeObjectURL: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const listScenarios = vi.fn(() =>
      Promise.resolve([{ scenario_id: "challenge-400whp-e27", kind: "challenge" as const, title: "400 whp", vehicle_id: "coupe-30t-i6", fuel_id: "e27", has_hidden_defect: false, available: true, last_evaluation_passed: null }]),
    );
    renderWithApi(<InstructorPanel />, makeApi({ createScenario, exportPackage, listScenarios }));
    expect(await screen.findByRole("heading", { name: "Painel do instrutor" })).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Tipo de defeito oculto"), "fuel_pump_weak");
    expect(screen.getByLabelText("Vazão máxima (L/h)")).toHaveValue(90);
    await userEvent.click(screen.getByRole("button", { name: "Adicionar dica" }));
    await userEvent.type(screen.getByLabelText("Texto da dica 1"), "Veja a pressão de combustível");
    await userEvent.click(screen.getByRole("button", { name: "Criar desafio" }));
    await waitFor(() => expect(createScenario).toHaveBeenCalled());
    const sent = (createScenario.mock.calls[0]![0] as { scenario: Record<string, unknown> }).scenario;
    expect(sent).toMatchObject({ scenario_id: "challenge-400whp-e27", vehicle_id: "coupe-30t-i6", fuel_id: "e27" });
    expect(sent.hidden_defect).toMatchObject({ kind: "fuel_pump_weak", fuel_pump_max_lph: 90 });
    const crit = (sent.criteria as { criteria: { kind: string; threshold: number | null }[]; required_valid_pulls: number });
    expect(crit.required_valid_pulls).toBe(3);
    expect(crit.criteria.map((c) => [c.kind, c.threshold])).toEqual([
      ["min_whp", 400],
      ["max_egt_c", 900],
      ["max_knock_retard_deg", 3],
      ["integrity", 100],
      ["valid_pulls", 3],
      ["max_spread_pct", 3],
    ]);
    expect(await screen.findByText(/Desafio challenge-400whp-e27 criado/)).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Exportar desafio challenge-400whp-e27" }));
    expect(exportPackage).toHaveBeenCalledWith({ kind: "challenge", scenario_id: "challenge-400whp-e27", include_full_logs: false });

    await userEvent.click(screen.getByRole("tab", { name: "Turma" }));
    expect(screen.getByRole("region", { name: /Área de importação/ })).toBeInTheDocument();
    expect(await screen.findByText("Ainda sem tentativas importadas.")).toBeInTheDocument();
  });
});
