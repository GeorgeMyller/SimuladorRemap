/**
 * Oficina (Carreira) no navegador (003 T024; RF-16, RF-17; 002 RF-25, RF-26).
 *
 * Teste 1 — carreira paga até liberar a ordem de reputação 60:
 * 1. perfil novo: saldo R$ 5.000,00, reputação 50, 7 ordens; "Swap standalone" bloqueada (60);
 * 2. aceitar "um cilindro quente" ⇒ bancada com o painel da tentativa; na oficina, as outras ordens
 *    ficam bloqueadas (um serviço aberto) e "Liquidar" antes do fim explica o 409;
 * 3. acerto real (λ 0,80 em plena carga, por REST; 0,84 no vazamento, que já enriquece), `multi_pull` de 2 pela UI, "Injetor entupido"
 *    declarado e "Submeter" ⇒ aprovado; "Liquidar" ⇒ +R$ 1.000,00 e reputação +5 (55);
 * 4. idem com "turbo trabalhando demais" (vazamento de pressão, `boost_leak`) ⇒ reputação 60;
 * 5. "Swap standalone" desbloqueada: aceitar abre a bancada; abandonar e liquidar ⇒ reputação −3.
 *
 * Teste 2 — as outras 4 ordens: aceitar (UI) ⇒ bancada com a tentativa do cenário certo;
 * "Abandonar" no painel e "Liquidar" na oficina ⇒ histórico "Abandonado" e reputação −3.
 */
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { API, Cleanup, createPlayer, enrichWot, expectJson, freeCapacity, usePlayer, waitAttemptReady, waitEvaluation, watchConsole } from "./helpers";

test.use({ viewport: { width: 1366, height: 768 } });

interface Order {
  order_id: string;
  title: string;
  scenario_id: string;
  payout_brl: number;
  min_reputation: number;
}

interface Job {
  job_id: string;
  order_id: string;
  attempt_id: string;
  session_id: string | null;
  status: string;
}

const brl = (cents: number) => new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(cents / 100);
// Intl usa espaço não separável entre "R$" e o valor.
const brlPattern = (cents: number) => new RegExp(brl(cents).replace(/\s/g, "\\s").replace("$", "\\$").replace(".", "\\."));

async function listOrders(request: APIRequestContext): Promise<Order[]> {
  return expectJson<Order[]>(await request.get(`${API}/career/orders`), 200);
}

/** Estação dedicada: liberta uma sessão ativa deixada por outro spec (o aceite cria uma sessão). */
async function ensureCapacity(request: APIRequestContext): Promise<void> {
  const probe = await request.post(`${API}/sessions`, { data: { vehicle_id: "hatch-20t-gdi" } });
  if (await freeCapacity(request, probe)) return;
  if (probe.status() === 201) await request.delete(`${API}/sessions/${((await probe.json()) as { session_id: string }).session_id}`);
}

/** Aceita a ordem pela UI e devolve o serviço criado (`POST .../jobs`), já na bancada. */
async function acceptInUi(page: Page, order: Order, cleanup: Cleanup, request: APIRequestContext, headers: Record<string, string>): Promise<Job> {
  await page.goto("/workshop");
  const accepted = page.waitForResponse((r) => r.request().method() === "POST" && /\/career\/profiles\/[^/]+\/jobs$/.test(r.url()));
  await page.getByRole("button", { name: `Aceitar a ordem ${order.title}` }).click();
  const job = await expectJson<Job>(await accepted, 201);
  cleanup.attempt(request, job.attempt_id, headers);
  if (job.session_id) cleanup.session(request, job.session_id);
  await expect(page).toHaveURL(new RegExp(`/sessions/${job.session_id}/dyno$`));
  await expect(page.getByTestId("vehicle-name")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("attempt-sidebar")).toBeVisible();
  return job;
}

/** Liquida o serviço pela UI e devolve o texto do aviso "Serviço liquidado". */
async function settleInUi(page: Page, order: Order): Promise<string> {
  await page.goto("/workshop");
  await page.getByRole("button", { name: `Liquidar o serviço ${order.title}` }).click();
  const banner = page.getByRole("status").filter({ hasText: "Serviço liquidado" });
  await expect(banner).toContainText(order.title, { timeout: 20_000 });
  return (await banner.textContent()) ?? "";
}

/** Acerto real do cenário de defeito pela bancada: λ rico (REST), multi_pull de 2 (UI), defeito declarado e submissão. */
async function tuneAndSubmit(page: Page, request: APIRequestContext, job: Job, headers: Record<string, string>, defectLabel: string, lambda: number): Promise<void> {
  const sidebar = page.getByTestId("attempt-sidebar");
  await expect(sidebar.getByRole("status").filter({ hasText: "Estado:" })).toContainText("Em curso", { timeout: 180_000 });
  const session = await expectJson<{ calibration_id: string }>(await request.get(`${API}/sessions/${job.session_id}`), 200);
  await enrichWot(request, job.session_id!, session.calibration_id, lambda);

  await page.getByRole("combobox", { name: "Tipo de puxada" }).selectOption("multi_pull");
  await page.getByRole("spinbutton", { name: "Número de puxadas" }).fill("2");
  const posted = page.waitForResponse((r) => r.request().method() === "POST" && /\/sessions\/[^/]+\/runs$/.test(r.url()));
  await page.getByRole("button", { name: "Iniciar" }).click();
  const multiId = (await expectJson<{ run_id: string }>(await posted, 202)).run_id;
  // A cockpit abre com a puxada base concluída: espera a nova puxada começar e terminar.
  await expect(page.getByTestId("run-status")).toHaveText("puxada em curso", { timeout: 15_000 });
  await expect(page.getByTestId("run-status")).toHaveText("puxada concluída", { timeout: 300_000 });
  await expect(sidebar.getByRole("listitem").filter({ hasText: multiId.slice(-6) }).filter({ hasText: "válida" }).first()).toBeVisible({ timeout: 30_000 });

  await sidebar.getByRole("combobox", { name: "Defeito diagnosticado" }).selectOption({ label: defectLabel });
  const submitted = page.waitForResponse((r) => r.request().method() === "POST" && r.url().endsWith(`/attempts/${job.attempt_id}/submit`));
  await sidebar.getByRole("button", { name: "Submeter" }).click();
  expect((await submitted).status()).toBe(202);
  const evaluation = await waitEvaluation(request, job.attempt_id, headers);
  expect(evaluation.passed, JSON.stringify(evaluation.results)).toBe(true);
  await expect(sidebar.getByRole("link", { name: "Ver resultado da última submissão" })).toBeVisible({ timeout: 30_000 });
}

async function abandonInSidebar(page: Page): Promise<void> {
  const sidebar = page.getByTestId("attempt-sidebar");
  await expect(sidebar.getByRole("status").filter({ hasText: "Estado:" })).toContainText("Em curso", { timeout: 180_000 });
  await sidebar.getByRole("button", { name: "Abandonar" }).click();
  await expect(sidebar.getByRole("button", { name: "Submeter" })).toHaveCount(0, { timeout: 20_000 });
}

test("carreira: dois serviços pagos com acerto real liberam a ordem de reputação 60", async ({ page, request, browserName }) => {
  test.skip(browserName !== "chromium", "fluxo de referência em Chromium");
  test.setTimeout(900_000);
  const errors = watchConsole(page);
  const cleanup = new Cleanup();
  try {
    await ensureCapacity(request);
    const orders = await listOrders(request);
    expect(orders).toHaveLength(7);
    const byId = Object.fromEntries(orders.map((o) => [o.order_id, o])) as Record<string, Order>;
    const player = await createPlayer(request, `oficina_${Date.now().toString(36).slice(-6)}`);
    await usePlayer(page, player.id);

    // 1. Estado inicial e bloqueio por reputação.
    await page.goto("/workshop");
    await expect(page.getByRole("heading", { name: "Oficina (Carreira)" })).toBeVisible();
    await expect(page.getByText(brlPattern(500_000)).first()).toBeVisible();
    for (const order of orders) await expect(page.getByRole("heading", { name: order.title, exact: true })).toBeVisible();
    const swap = byId["swap-standalone"]!;
    await expect(page.getByRole("button", { name: `Aceitar a ordem ${swap.title}` })).toBeDisabled();
    await expect(page.getByRole("button", { name: `Aceitar a ordem ${swap.title}` })).toHaveAccessibleDescription("Requer reputação 60 (a oficina tem 50).");

    // 2. Aceitar "um cilindro quente" e tentar liquidar antes do fim.
    const lean = byId["diagnostico-cilindro-quente"]!;
    const leanJob = await acceptInUi(page, lean, cleanup, request, player.headers);
    await page.goto("/workshop");
    await expect(page.getByRole("button", { name: `Aceitar a ordem ${byId["stage1-diario-seguro"]!.title}` })).toBeDisabled();
    await page.getByRole("button", { name: `Liquidar o serviço ${lean.title}` }).click();
    await expect(page.getByRole("alert").filter({ hasText: "CAREER_ATTEMPT_NOT_FINISHED" })).toBeVisible();
    await page.getByRole("link", { name: "Abrir bancada" }).click();
    await expect(page.getByTestId("connection-state")).toHaveText("conectado", { timeout: 30_000 });

    // 3. Acerto real, submissão aprovada e pagamento.
    await tuneAndSubmit(page, request, leanJob, player.headers, "Injetor entupido", 0.8);
    const paid1 = await settleInUi(page, lean);
    expect(paid1).toMatch(new RegExp(`Saldo \\+${brlPattern(lean.payout_brl).source}, reputação \\+5`));
    await expect(page.getByText(brlPattern(500_000 + lean.payout_brl)).first()).toBeVisible();
    await expect(page.getByRole("cell", { name: "Pago" })).toHaveCount(1);

    // 4. Vazamento de pressão (boost_leak declarado pela UI).
    const leak = byId["diagnostico-vazamento-pressao"]!;
    const leakJob = await acceptInUi(page, leak, cleanup, request, player.headers);
    await tuneAndSubmit(page, request, leakJob, player.headers, "Vazamento no circuito de pressão", 0.84);
    const paid2 = await settleInUi(page, leak);
    expect(paid2).toContain("reputação +5");
    const career = await expectJson<{ balance_brl: number; reputation: number }>(await request.get(`${API}/career/profiles/${player.id}`), 200);
    expect(career).toMatchObject({ balance_brl: 500_000 + lean.payout_brl + leak.payout_brl, reputation: 60 });

    // 5. Ordem de reputação 60 liberada.
    await page.goto("/workshop");
    await expect(page.getByRole("button", { name: `Aceitar a ordem ${swap.title}` })).toBeEnabled();
    await acceptInUi(page, swap, cleanup, request, player.headers);
    await expect(page.getByTestId("attempt-sidebar").getByRole("heading").first()).toContainText(/Swap standalone/i);
    await abandonInSidebar(page);
    const abandoned = await settleInUi(page, swap);
    expect(abandoned).toContain("reputação -3");
    expect(errors, errors.join("\n")).toEqual([]);
  } finally {
    await cleanup.run();
  }
});

test("carreira: as outras 4 ordens abrem a bancada do cenário certo e liquidam como abandonadas", async ({ page, request, browserName }) => {
  test.skip(browserName !== "chromium", "fluxo de referência em Chromium");
  test.setTimeout(600_000);
  const cleanup = new Cleanup();
  try {
    await ensureCapacity(request);
    const orders = await listOrders(request);
    const player = await createPlayer(request, `ordens_${Date.now().toString(36).slice(-6)}`);
    await usePlayer(page, player.id);
    // Reputação −3 por abandono: da mais exigente para a menos exigente (50 → 38).
    const ids = ["pista-two-step-pops", "diagnostico-bomba-combustivel", "diagnostico-turbo-nao-enche", "stage1-diario-seguro"];
    let reputation = 50;
    for (const id of ids) {
      const order = orders.find((o) => o.order_id === id)!;
      expect(reputation).toBeGreaterThanOrEqual(order.min_reputation);
      const job = await acceptInUi(page, order, cleanup, request, player.headers);
      const attempt = await waitAttemptReady(request, job.attempt_id, player.headers);
      expect(attempt.scenario_id).toBe(order.scenario_id);
      await abandonInSidebar(page);
      const text = await settleInUi(page, order);
      expect(text).toContain("reputação -3");
      reputation -= 3;
      await expect(page.getByRole("cell", { name: "Abandonado" })).toHaveCount(ids.indexOf(id) + 1);
    }
    const career = await expectJson<{ reputation: number }>(await request.get(`${API}/career/profiles/${player.id}`), 200);
    expect(career.reputation).toBe(reputation);
  } finally {
    await cleanup.run();
  }
});
