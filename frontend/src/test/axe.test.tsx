import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { expectNoAxeViolations, formatViolations, WCAG_A_AA } from "./axe";

describe("auditoria axe", () => {
  it("passa num formulário rotulado", async () => {
    const { container } = render(
      <main>
        <h1>Formulário</h1>
        <label>
          Nome <input type="text" />
        </label>
      </main>,
    );
    const results = await expectNoAxeViolations(container);
    expect(results.violations).toHaveLength(0);
    expect(WCAG_A_AA).toContain("wcag2aa");
  });

  it("falha com a lista das violações A/AA (botão sem nome, imagem sem alt)", async () => {
    const { container } = render(
      <div>
        <button type="button" />
        <img src="x.png" />
      </div>,
    );
    await expect(expectNoAxeViolations(container)).rejects.toThrow(/button-name[\s\S]*image-alt|image-alt[\s\S]*button-name/);
  });

  it("formatViolations lista id, impacto e nós", () => {
    const text = formatViolations([
      { id: "x", impact: null, help: "ajuda", nodes: [{ target: ["#a"], failureSummary: undefined }] },
    ] as unknown as Parameters<typeof formatViolations>[0]);
    expect(text).toBe("x (?): ajuda\n  - #a: ");
  });
});
