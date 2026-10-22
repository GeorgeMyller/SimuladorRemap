/**
 * Página "Oficina (Carreira)" (002 RF-25, RF-26; T048). Usa o perfil de jogador ativo dos
 * cenários (`profile_id` da carreira) e mostra saldo, reputação, ordens, serviços em andamento
 * e histórico. Aceitar cria a tentativa e abre a bancada da sessão; liquidar mostra o delta de
 * saldo e reputação. Sem dados pessoais: nem apelido nem id do perfil aparecem na tela.
 */
import { useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";

import { setActiveSessionId } from "@/app/activeSession";
import { dynoPath } from "@/app/paths";
import { useActiveProfileId } from "@/features/scenarios/useActiveProfile";

import { careerApi, type CareerApi } from "./api";
import { JobHistory, OpenJobList } from "./JobList";
import { OrderList } from "./OrderList";
import { careerError, formatBrl, formatBrlDelta, formatSigned, type CareerError, type CareerJob, type WorkOrder } from "./types";
import { useCareer } from "./useCareer";

const PROFILE_LOST_CODES = new Set(["PLAYER_PROFILE_NOT_FOUND"]);

export interface WorkshopPageProps {
  api?: CareerApi;
}

function PageShell({ children }: { children: ReactNode }) {
  return (
    <section aria-labelledby="workshop-title" className="mx-auto max-w-6xl py-6 sm:py-8">
      <h1 id="workshop-title" className="text-2xl font-semibold">
        Oficina (Carreira)
      </h1>
      {children}
    </section>
  );
}

function ChooseProfile({ text }: { text: string }) {
  return (
    <div className="mt-6 rounded border border-zinc-700 p-6">
      <p>{text}</p>
      <Link to="/scenarios/profiles" className="mt-3 inline-block rounded bg-amber-500 px-4 py-2 font-semibold text-zinc-950 hover:bg-amber-400">
        Escolher perfil
      </Link>
    </div>
  );
}

export default function WorkshopPage({ api = careerApi }: WorkshopPageProps) {
  const profileId = useActiveProfileId();
  const { data, reload } = useCareer(api, profileId);
  const navigate = useNavigate();
  const [busyOrderId, setBusyOrderId] = useState<string | null>(null);
  const [busyJobId, setBusyJobId] = useState<string | null>(null);
  const [acceptError, setAcceptError] = useState<CareerError | null>(null);
  const [settleErrors, setSettleErrors] = useState<Record<string, CareerError>>({});
  const [settled, setSettled] = useState<CareerJob | null>(null);

  const orders = data.status === "ready" ? data.orders : [];
  const titleOf = (orderId: string) => orders.find((o) => o.order_id === orderId)?.title ?? orderId;

  if (!profileId) {
    return (
      <PageShell>
        <ChooseProfile text="A oficina pertence a um perfil de jogador. Escolha ou crie um perfil local para começar a carreira." />
      </PageShell>
    );
  }
  if (data.status === "loading") {
    return (
      <PageShell>
        <div role="status" aria-label="A carregar a oficina" className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <span className="h-24 rounded bg-zinc-800 motion-safe:animate-pulse" />
          <span className="h-24 rounded bg-zinc-800 motion-safe:animate-pulse" />
        </div>
      </PageShell>
    );
  }
  if (data.status === "error") {
    if (PROFILE_LOST_CODES.has(data.error.code)) {
      return (
        <PageShell>
          <ChooseProfile text={data.error.text} />
        </PageShell>
      );
    }
    return (
      <PageShell>
        <div role="alert" className="mt-6 rounded border border-red-500 p-4">
          <p className="font-semibold">Não foi possível abrir a oficina.</p>
          <p className="mt-1 text-sm text-zinc-200">{data.error.text}</p>
          <p className="mt-1 font-mono text-xs text-zinc-400">{data.error.code}</p>
          <button type="button" onClick={reload} className="mt-3 rounded bg-amber-500 px-3 py-1.5 font-semibold text-zinc-950 hover:bg-amber-400">
            Tentar de novo
          </button>
        </div>
      </PageShell>
    );
  }

  const { profile, jobs } = data;
  const openJobs = jobs.filter((job) => job.status === "accepted");
  const history = jobs.filter((job) => job.status !== "accepted");
  const openOrderIds = new Set(openJobs.map((job) => job.order_id));

  async function accept(order: WorkOrder) {
    if (!profileId) return;
    setBusyOrderId(order.order_id);
    setAcceptError(null);
    try {
      const job = await api.acceptOrder(profileId, order.order_id);
      if (job.session_id) {
        setActiveSessionId(job.session_id);
        void navigate(dynoPath(job.session_id));
        return;
      }
      void navigate(`/attempts/${encodeURIComponent(job.attempt_id)}`);
    } catch (error) {
      setAcceptError(careerError(error));
      setBusyOrderId(null);
    }
  }

  async function settle(job: CareerJob) {
    setBusyJobId(job.job_id);
    setSettled(null);
    setSettleErrors(({ [job.job_id]: _dropped, ...rest }) => rest);
    try {
      setSettled(await api.settleJob(job.job_id));
      reload();
    } catch (error) {
      setSettleErrors((current) => ({ ...current, [job.job_id]: careerError(error) }));
    } finally {
      setBusyJobId(null);
    }
  }

  return (
    <PageShell>
      <dl className="mt-4 flex flex-wrap gap-x-10 gap-y-3">
        <div>
          <dt className="text-sm text-zinc-400">Saldo</dt>
          <dd className={`font-mono text-3xl font-semibold ${profile.balance_brl < 0 ? "text-red-300" : "text-emerald-300"}`}>{formatBrl(profile.balance_brl)}</dd>
        </div>
        <div>
          <dt className="text-sm text-zinc-400">Reputação</dt>
          <dd className="font-mono text-3xl font-semibold">
            {profile.reputation}
            <span className="text-base text-zinc-400"> / 100</span>
          </dd>
        </div>
      </dl>

      {settled && (
        <div role="status" className="mt-4 rounded border border-emerald-500 p-3 text-sm">
          <p className="font-semibold">Serviço liquidado: {titleOf(settled.order_id)}</p>
          <p className="mt-1 font-mono">
            Saldo {formatBrlDelta(settled.delta_balance_brl ?? 0)}, reputação {formatSigned(settled.delta_reputation ?? 0)}
          </p>
        </div>
      )}

      <h2 className="mt-8 text-lg font-semibold">Serviços em andamento</h2>
      <div className="mt-3">
        <OpenJobList jobs={openJobs} titleOf={titleOf} busyJobId={busyJobId} errors={settleErrors} onSettle={(job) => void settle(job)} />
      </div>

      <h2 className="mt-8 text-lg font-semibold">Ordens de serviço</h2>
      {acceptError && (
        <div role="alert" className="mt-3 rounded border border-red-500 p-3 text-sm">
          <p>{acceptError.text}</p>
          <p className="mt-1 font-mono text-xs text-zinc-300">{acceptError.code}</p>
        </div>
      )}
      <div className="mt-3">
        <OrderList orders={orders} reputation={profile.reputation} openOrderIds={openOrderIds} busyOrderId={busyOrderId} onAccept={(order) => void accept(order)} />
      </div>

      <h2 className="mt-8 text-lg font-semibold">Histórico</h2>
      <div className="mt-3 overflow-x-auto">
        <JobHistory jobs={history} titleOf={titleOf} />
      </div>
    </PageShell>
  );
}
