import { describe, expect, it } from "vitest";

import { GRADES_FIXED_COLUMNS, gradesCsv, neutralizeFormula, stationOf, type GradeRow } from "./gradesCsv";

function row(over: Partial<GradeRow> = {}): GradeRow {
  return {
    nickname: "joao",
    install_id: "a1b2c3d4-0000-4000-8000-000000000000",
    scenario_id: "stage1-oem",
    attempt_id: "att-1",
    submission: 2,
    passed: true,
    total_score: 95.25,
    evaluation_mismatch: false,
    replay_status: "verified",
    package_sha256: "f".repeat(64),
    imported_at: "2026-10-18T10:00:00Z",
    scores: { "delta-whp": 100, egt: 87.5 },
    ...over,
  };
}

describe("gradesCsv", () => {
  it("usa ; e vírgula decimal por padrão, com as colunas fixas e os scores na ordem", () => {
    const csv = gradesCsv([row()], { criterionIds: ["delta-whp", "egt"] });
    const [header, line] = csv.trimEnd().split("\n");
    expect(header).toBe(`${GRADES_FIXED_COLUMNS.join(";")};score_delta-whp;score_egt`);
    expect(line).toBe(`joao;a1b2;stage1-oem;att-1;2;true;95,3;false;verified;${"f".repeat(64)};2026-10-18T10:00:00Z;100,0;87,5`);
    expect(csv.charCodeAt(0)).not.toBe(0xfeff);
  });

  it("opção RFC 4180: vírgula e ponto decimal", () => {
    const csv = gradesCsv([row({ passed: false, total_score: 50 })], { dialect: "rfc4180", criterionIds: ["egt"] });
    expect(csv.split("\n")[1]).toBe(`joao,a1b2,stage1-oem,att-1,2,false,50.0,false,verified,${"f".repeat(64)},2026-10-18T10:00:00Z,87.5`);
  });

  it("=HYPERLINK(1) sai como '=HYPERLINK(1) (RF-26)", () => {
    const csv = gradesCsv([row({ scenario_title: "=HYPERLINK(1)" })], { includeTitle: true });
    expect(csv).toContain(";'=HYPERLINK(1)");
    expect(csv.split("\n")[0]).toContain("imported_at;scenario_title");
  });

  it("neutraliza +, -, @, tab e CR e cita separadores e aspas", () => {
    expect(neutralizeFormula("+1")).toBe("'+1");
    expect(neutralizeFormula("-1")).toBe("'-1");
    expect(neutralizeFormula("@SUM")).toBe("'@SUM");
    expect(neutralizeFormula("\tx")).toBe("'\tx");
    expect(neutralizeFormula("\rx")).toBe("'\rx");
    expect(neutralizeFormula("ok")).toBe("ok");
    const csv = gradesCsv([row({ nickname: 'a;"b"' })]);
    expect(csv.split("\n")[1]?.startsWith('"a;""b"""')).toBe(true);
  });

  it("valores ausentes ficam vazios e a estação usa os 4 primeiros hex", () => {
    const csv = gradesCsv([row({ passed: null, total_score: null, install_id: null, package_sha256: null, imported_at: null, scores: {} })], {
      criterionIds: ["egt"],
    });
    expect(csv.split("\n")[1]).toBe("joao;;stage1-oem;att-1;2;;;false;verified;;;");
    expect(stationOf("8f0c2b7e-0d1a")).toBe("8f0c");
  });

  it("1 cabeçalho + N linhas", () => {
    const rows = Array.from({ length: 48 }, (_, i) => row({ attempt_id: `att-${i}` }));
    expect(gradesCsv(rows).trimEnd().split("\n")).toHaveLength(49);
  });
});
