/**
 * Som do motor no navegador (003 T024; RF-07 a RF-10, RF-17; cockpit RF-19).
 *
 * Um script de inicialização instrumenta a Web Audio API (instâncias de `AudioContext`, nós
 * criados e ligações `connect`). Com interação real do usuário (clique em "Ativar som" quando o
 * navegador exige gesto), o contexto fica `running`, o grafo é montado (osciladores/buffers,
 * ganhos e ligação ao destino) e uma puxada base com som ligado termina sem erros de consola nem
 * exceções. "M" silencia e reativa.
 */
import { expect, test } from "@playwright/test";

import { Cleanup, createSession, openCockpit, startRunInCockpit, watchConsole } from "./helpers";

test.use({ viewport: { width: 1366, height: 768 } });

interface AudioProbe {
  contexts: number;
  states: string[];
  nodes: Record<string, number>;
  connects: number;
  toDestination: number;
  errors: string[];
}

declare global {
  interface Window {
    __audioProbe?: AudioProbe;
    __audioState?: () => string | null;
  }
}

test("áudio: AudioContext criado, grafo montado e puxada com som sem erros", async ({ page, request, browserName }) => {
  test.skip(browserName !== "chromium", "Web Audio de referência em Chromium");
  test.setTimeout(180_000);
  await page.addInitScript(() => {
    const probe: AudioProbe = { contexts: 0, states: [], nodes: {}, connects: 0, toDestination: 0, errors: [] };
    window.__audioProbe = probe;
    const Native = window.AudioContext;
    if (!Native) return;
    const contexts: AudioContext[] = [];
    class ProbedAudioContext extends Native {
      constructor(options?: AudioContextOptions) {
        super(options);
        probe.contexts += 1;
        contexts.push(this);
        this.addEventListener("statechange", () => probe.states.push(this.state));
      }
    }
    window.AudioContext = ProbedAudioContext;
    window.__audioState = () => contexts.at(-1)?.state ?? null;
    for (const name of Object.getOwnPropertyNames(BaseAudioContext.prototype)) {
      if (!name.startsWith("create")) continue;
      const original = (BaseAudioContext.prototype as unknown as Record<string, (...args: unknown[]) => unknown>)[name];
      if (typeof original !== "function") continue;
      (BaseAudioContext.prototype as unknown as Record<string, unknown>)[name] = function (this: BaseAudioContext, ...args: unknown[]) {
        probe.nodes[name] = (probe.nodes[name] ?? 0) + 1;
        try {
          return original.apply(this, args);
        } catch (error) {
          probe.errors.push(`${name}: ${String(error)}`);
          throw error;
        }
      };
    }
    // eslint-disable-next-line @typescript-eslint/unbound-method -- reaplicado com o `this` do nó
    const connect = AudioNode.prototype.connect as (...args: unknown[]) => unknown;
    AudioNode.prototype.connect = function (this: AudioNode, ...args: unknown[]) {
      probe.connects += 1;
      if (args[0] instanceof AudioDestinationNode) probe.toDestination += 1;
      return connect.apply(this, args);
    } as typeof AudioNode.prototype.connect;
  });

  const errors = watchConsole(page);
  const cleanup = new Cleanup();
  try {
    const session = await createSession(request, { vehicle_id: "hatch-20t-gdi", seed: 42 }, cleanup);
    await openCockpit(page, session.session_id);

    // Gesto real do usuário: "Ativar som" quando o navegador suspende o contexto.
    const group = page.getByRole("group", { name: "Som do motor" });
    await expect(group).toBeVisible();
    const enable = group.getByRole("button", { name: "Ativar som" });
    if (await enable.isVisible()) await enable.click();
    const toggle = group.getByRole("button", { name: /Som (ligado|desligado)/ });
    await expect(toggle).toBeVisible({ timeout: 10_000 });
    if ((await toggle.textContent()) === "Som desligado") await toggle.click();
    await expect(toggle).toHaveText("Som ligado");

    await expect.poll(() => page.evaluate(() => window.__audioProbe!.contexts)).toBeGreaterThanOrEqual(1);
    const state = await page.evaluate(() => {
      const probe = window.__audioProbe!;
      return { ...probe };
    });
    expect(state.errors, state.errors.join("\n")).toEqual([]);

    // Puxada base com som: o grafo recebe fontes e ganhos e chega ao destino.
    await startRunInCockpit(page, "baseline_pull");
    await expect(page.getByTestId("run-status")).toHaveText("puxada em curso", { timeout: 15_000 });
    await expect
      .poll(() => page.evaluate(() => window.__audioProbe!.toDestination), { timeout: 20_000 })
      .toBeGreaterThanOrEqual(1);
    const graph = await page.evaluate(() => window.__audioProbe!);
    const sources = (graph.nodes.createOscillator ?? 0) + (graph.nodes.createBufferSource ?? 0) + (graph.nodes.createConstantSource ?? 0);
    expect(sources, JSON.stringify(graph.nodes)).toBeGreaterThan(0);
    expect(graph.nodes.createGain ?? 0, JSON.stringify(graph.nodes)).toBeGreaterThan(0);
    expect(graph.connects).toBeGreaterThan(2);
    expect(await page.evaluate(() => window.__audioState!())).toBe("running");

    // M silencia e reativa (fora de campos de texto).
    await page.getByRole("heading", { name: "Bancada de dinamômetro" }).click();
    await page.keyboard.press("m");
    await expect(toggle).toHaveText("Som desligado");
    await page.keyboard.press("m");
    await expect(toggle).toHaveText("Som ligado");

    await expect(page.getByTestId("run-status")).toHaveText("puxada concluída", { timeout: 150_000 });
    const final = await page.evaluate(() => window.__audioProbe!);
    expect(final.errors, final.errors.join("\n")).toEqual([]);
    expect(final.states).not.toContain("closed");
    expect(errors, errors.join("\n")).toEqual([]);
  } finally {
    await cleanup.run();
  }
});
