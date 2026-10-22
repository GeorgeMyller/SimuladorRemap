/**
 * Fila de importação de pacotes da turma (training-scenarios RF-25): até 50 ficheiros,
 * no máximo 2 uploads em paralelo e estado por ficheiro (recusa mostra o `code`).
 * O ficheiro é enviado tal como foi lido (o servidor recalcula o SHA-256 do JCS).
 */
import { useRef, useState, type DragEvent } from "react";

import { ApiProblem } from "@/lib/api";

import { useScenariosApi } from "./api";
import type { PackageImportResult } from "./types";

export const MAX_FILES = 50;
export const MAX_PARALLEL_UPLOADS = 2;

export type ImportStatus = "queued" | "uploading" | "imported" | "already_imported" | "rejected";

export interface ImportItem {
  key: string;
  name: string;
  status: ImportStatus;
  code?: string;
  detail?: string;
  result?: PackageImportResult;
}

const STATUS_TEXT: Record<ImportStatus, string> = {
  queued: "Na fila",
  uploading: "A enviar…",
  imported: "Importado",
  already_imported: "Já importado",
  rejected: "Recusado",
};

const STATUS_ICON: Record<ImportStatus, string> = {
  queued: "…",
  uploading: "⇡",
  imported: "✓",
  already_imported: "✓",
  rejected: "✗",
};

const REJECT_TEXT: Record<string, string> = {
  PACKAGE_HASH_MISMATCH: "pacote adulterado ou corrompido",
  SCENARIO_VERSION_MISMATCH: "cenário diferente do original",
  PACKAGE_FORMAT_UNSUPPORTED: "formato mais novo que esta versão",
  PACKAGE_MALFORMED: "ficheiro truncado ou não é JSON",
  PACKAGE_SCHEMA_INVALID: "conteúdo fora do formato",
  PACKAGE_NOT_CANONICALIZABLE: "valores NaN ou Infinity",
  PAYLOAD_TOO_LARGE: "acima de 64 MiB; exporte sem logs completos",
  SCENARIO_NOT_FOUND: "importe primeiro o desafio",
};

function readText(file: File): Promise<string> {
  if (typeof file.text === "function") return file.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(typeof reader.result === "string" ? reader.result : "");
    reader.onerror = () => reject(reader.error ?? new Error("leitura falhou"));
    reader.readAsText(file);
  });
}

export interface PackageImportQueueProps {
  onImported?: (result: PackageImportResult) => void;
  onFinished?: (items: ImportItem[]) => void;
  concurrency?: number;
}

export function PackageImportQueue({ onImported, onFinished, concurrency = MAX_PARALLEL_UPLOADS }: PackageImportQueueProps) {
  const api = useScenariosApi();
  const [items, setItems] = useState<ImportItem[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const seq = useRef(0);

  function update(key: string, patch: Partial<ImportItem>) {
    setItems((prev) => prev.map((it) => (it.key === key ? { ...it, ...patch } : it)));
  }

  async function uploadOne(item: ImportItem, file: File): Promise<ImportItem> {
    update(item.key, { status: "uploading" });
    try {
      const raw = await readText(file);
      const result = await api.importPackage(raw);
      const status: ImportStatus = result.already_imported ? "already_imported" : "imported";
      update(item.key, { status, result });
      onImported?.(result);
      return { ...item, status, result };
    } catch (e) {
      const code = e instanceof ApiProblem ? e.code : "INTERNAL_ERROR";
      const detail = e instanceof Error ? e.message : String(e);
      update(item.key, { status: "rejected", code, detail });
      return { ...item, status: "rejected", code, detail };
    }
  }

  async function enqueue(fileList: FileList | File[]) {
    let files = Array.from(fileList);
    if (files.length === 0) return;
    setNotice(null);
    if (files.length > MAX_FILES) {
      setNotice(`Só os primeiros ${MAX_FILES} ficheiros foram aceites.`);
      files = files.slice(0, MAX_FILES);
    }
    const batch = files.map((f) => ({ item: { key: `f${seq.current++}`, name: f.name, status: "queued" as const }, file: f }));
    setItems((prev) => [...prev, ...batch.map((b) => b.item)]);
    setRunning(true);
    const done: ImportItem[] = [];
    let next = 0;
    const worker = async () => {
      while (next < batch.length) {
        const job = batch[next++];
        if (job) done.push(await uploadOne(job.item, job.file));
      }
    };
    await Promise.all(Array.from({ length: Math.max(1, Math.min(concurrency, batch.length)) }, worker));
    setRunning(false);
    onFinished?.(done);
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(false);
    void enqueue(e.dataTransfer.files);
  }

  const counts = items.reduce<Record<ImportStatus, number>>(
    (acc, it) => ({ ...acc, [it.status]: acc[it.status] + 1 }),
    { queued: 0, uploading: 0, imported: 0, already_imported: 0, rejected: 0 },
  );

  return (
    <section aria-labelledby="import-title" className="space-y-2">
      <h3 id="import-title" className="font-semibold">
        Importar pacotes da turma
      </h3>
      <div
        role="region"
        aria-label="Área de importação: arraste até 50 ficheiros .simremap.json"
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`rounded border-2 border-dashed p-4 text-center text-sm ${dragging ? "border-sky-400 bg-sky-950" : "border-zinc-600"}`}
      >
        <p>Arraste e largue até {MAX_FILES} pacotes aqui, ou</p>
        <label className="mt-2 inline-block cursor-pointer rounded bg-sky-700 px-3 py-1">
          escolha os ficheiros
          <input
            ref={inputRef}
            type="file"
            multiple
            accept=".json,application/json"
            className="sr-only"
            aria-label="Ficheiros de pacote"
            onChange={(e) => {
              if (e.target.files) void enqueue(e.target.files);
              if (inputRef.current) inputRef.current.value = "";
            }}
          />
        </label>
      </div>
      {notice && (
        <p role="status" className="text-sm text-amber-300">
          {notice}
        </p>
      )}
      {items.length > 0 && (
        <>
          <p role="status" aria-live="polite" className="text-sm">
            {counts.imported} importados, {counts.already_imported} já importados, {counts.rejected} recusados
            {running ? `, ${counts.queued + counts.uploading} em curso` : ""}.
          </p>
          <ul aria-label="Estado por ficheiro" className="max-h-64 overflow-auto text-sm">
            {items.map((it) => (
              <li key={it.key} data-status={it.status} className="flex justify-between gap-2 border-t border-zinc-800 py-0.5">
                <span className="truncate">{it.name}</span>
                <span className={it.status === "rejected" ? "text-red-300" : it.status === "queued" ? "text-zinc-400" : "text-emerald-300"}>
                  <span aria-hidden="true">{STATUS_ICON[it.status]} </span>
                  {STATUS_TEXT[it.status]}
                  {it.code && <span className="ml-1 font-mono text-xs">{it.code}</span>}
                  {it.code && REJECT_TEXT[it.code] && <span className="ml-1 text-xs">({REJECT_TEXT[it.code]})</span>}
                  {it.result?.evaluation_mismatch && <span className="ml-1 text-xs text-amber-300">avaliação recalculada</span>}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
