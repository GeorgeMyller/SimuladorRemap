/** Serviços do perfil (002 RF-25, RF-26): os em andamento com "Liquidar" e o histórico dos liquidados. */
import { Link } from "react-router-dom";

import { dynoPath } from "@/app/paths";

import { formatBrlDelta, formatSigned, JOB_STATUS_CLASS, JOB_STATUS_LABEL, type CareerError, type CareerJob } from "./types";

const dateTime = new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" });

export function JobStatusBadge({ job }: { job: CareerJob }) {
  return <span className={`rounded px-2 py-0.5 text-xs font-semibold ${JOB_STATUS_CLASS[job.status]}`}>{JOB_STATUS_LABEL[job.status]}</span>;
}

export interface OpenJobListProps {
  jobs: CareerJob[];
  titleOf: (orderId: string) => string;
  busyJobId: string | null;
  errors: Readonly<Record<string, CareerError>>;
  onSettle: (job: CareerJob) => void;
}

export function OpenJobList({ jobs, titleOf, busyJobId, errors, onSettle }: OpenJobListProps) {
  if (jobs.length === 0) {
    return <p className="rounded border border-zinc-700 p-4 text-sm text-zinc-300">Nenhum serviço em andamento. Aceite uma ordem abaixo.</p>;
  }
  return (
    <ul className="space-y-3">
      {jobs.map((job) => {
        const error = errors[job.job_id];
        return (
          <li key={job.job_id} className="rounded border border-amber-400/60 p-4">
            <div className="flex flex-wrap items-center gap-3">
              <h3 className="font-semibold">{titleOf(job.order_id)}</h3>
              <JobStatusBadge job={job} />
              <span className="text-xs text-zinc-400">Aceito em {dateTime.format(new Date(job.accepted_at))}</span>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {job.session_id && (
                <Link to={dynoPath(job.session_id)} className="rounded border border-amber-400 px-3 py-1.5 text-sm text-amber-200 hover:bg-zinc-800">
                  Abrir bancada
                </Link>
              )}
              <button
                type="button"
                disabled={busyJobId !== null}
                aria-label={`Liquidar o serviço ${titleOf(job.order_id)}`}
                onClick={() => onSettle(job)}
                className="rounded bg-amber-500 px-3 py-1.5 text-sm font-semibold text-zinc-950 transition-transform hover:bg-amber-400 active:translate-y-px disabled:opacity-50"
              >
                {busyJobId === job.job_id ? "A liquidar…" : "Liquidar"}
              </button>
            </div>
            {error && (
              <div role="alert" className="mt-3 rounded border border-red-500 p-3 text-sm">
                <p>{error.text}</p>
                <p className="mt-1 font-mono text-xs text-zinc-300">{error.code}</p>
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

export function JobHistory({ jobs, titleOf }: { jobs: CareerJob[]; titleOf: (orderId: string) => string }) {
  if (jobs.length === 0) {
    return <p className="rounded border border-zinc-700 p-4 text-sm text-zinc-300">Ainda não há serviços liquidados.</p>;
  }
  return (
    <table className="w-full text-left text-sm">
      <thead className="text-xs text-zinc-400">
        <tr>
          <th scope="col" className="py-2 pr-3 font-medium">Serviço</th>
          <th scope="col" className="py-2 pr-3 font-medium">Resultado</th>
          <th scope="col" className="py-2 pr-3 text-right font-medium">Saldo</th>
          <th scope="col" className="py-2 pr-3 text-right font-medium">Reputação</th>
          <th scope="col" className="py-2 font-medium">Liquidado em</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-zinc-800">
        {jobs.map((job) => (
          <tr key={job.job_id}>
            <td className="py-2 pr-3">{titleOf(job.order_id)}</td>
            <td className="py-2 pr-3">
              <JobStatusBadge job={job} />
            </td>
            <td className="py-2 pr-3 text-right font-mono">{job.delta_balance_brl != null ? formatBrlDelta(job.delta_balance_brl) : "-"}</td>
            <td className="py-2 pr-3 text-right font-mono">{job.delta_reputation != null ? formatSigned(job.delta_reputation) : "-"}</td>
            <td className="py-2 text-zinc-300">{job.settled_at ? dateTime.format(new Date(job.settled_at)) : "-"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
