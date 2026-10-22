/**
 * Auditoria axe-core (vitest-axe) das telas principais: 0 violações WCAG 2.x A/AA
 * (cockpit RNF-06, tuning G-05). `color-contrast` exige layout e CSS reais e não é
 * mensurável no jsdom (desligada aqui); o contraste é verificado no navegador real (Playwright).
 */
import type { AxeResults, Result } from "axe-core";
import { configureAxe } from "vitest-axe";

export const WCAG_A_AA = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"];

const runAxe = configureAxe({
  runOnly: { type: "tag", values: WCAG_A_AA },
  rules: { "color-contrast": { enabled: false } },
});

export function formatViolations(violations: Result[]): string {
  return violations
    .map((v) => `${v.id} (${v.impact ?? "?"}): ${v.help}\n${v.nodes.map((n) => `  - ${n.target.join(" ")}: ${n.failureSummary ?? ""}`).join("\n")}`)
    .join("\n");
}

/** Corre o axe no elemento e falha com a lista legível das violações A/AA. */
export async function expectNoAxeViolations(element: Element = document.body): Promise<AxeResults> {
  const results = await runAxe(element);
  if (results.violations.length > 0) {
    throw new Error(`Violações de acessibilidade (A/AA):\n${formatViolations(results.violations)}`);
  }
  return results;
}
