/** Evidência de um critério: abre a puxada na cockpit e o log no `t_sim_s` (RF-12). */
import { Link } from "react-router-dom";

import { dynoPath } from "@/app/routes";

import type { Evidence } from "./types";
import { fmt } from "./ui";

export function evidenceText(e: Evidence): string {
  const parts = [e.channel];
  if (e.value !== null) parts.push(`= ${fmt(e.value, 1)}`);
  if (e.rpm !== null) parts.push(`a ${fmt(e.rpm, 0)} rpm`);
  if (e.t_sim_s !== null) parts.push(`em t = ${fmt(e.t_sim_s, 2)} s`);
  if (e.cylinder !== null) parts.push(`cilindro ${e.cylinder}`);
  return parts.join(" ");
}

export function EvidenceLink({ evidence, sessionId }: { evidence: Evidence; sessionId: string | null }) {
  const search = new URLSearchParams({ run: evidence.run_id });
  if (evidence.t_sim_s !== null) search.set("t", String(evidence.t_sim_s));
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <span>{evidenceText(evidence)}</span>
      {sessionId && (
        <Link className="text-sky-300 underline" to={`${dynoPath(sessionId)}?${search.toString()}`}>
          Abrir puxada {evidence.run_id.slice(-6)} na bancada
        </Link>
      )}
      <a className="text-sky-300 underline" href={evidence.url} target="_blank" rel="noreferrer">
        Ver log
      </a>
    </span>
  );
}
