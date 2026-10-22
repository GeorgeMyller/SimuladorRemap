/** Ordens de serviço disponíveis (002 RF-26): bloqueio por reputação mínima e por serviço em aberto (um por perfil). */
import { formatBrl, type WorkOrder } from "./types";

export interface OrderListProps {
  orders: WorkOrder[];
  reputation: number;
  openOrderIds: ReadonlySet<string>;
  busyOrderId: string | null;
  onAccept: (order: WorkOrder) => void;
}

/** O backend aceita um só serviço aberto por perfil (409 `CAREER_JOB_ALREADY_OPEN`): todas as ordens ficam bloqueadas. */
function lockReason(order: WorkOrder, reputation: number, openOrderIds: ReadonlySet<string>): string | null {
  if (openOrderIds.has(order.order_id)) return "Serviço em andamento: liquide-o antes de aceitar de novo.";
  if (openOrderIds.size > 0) return "Há um serviço em andamento: liquide-o antes de aceitar outra ordem.";
  const minimum = order.min_reputation ?? 0;
  if (reputation < minimum) return `Requer reputação ${minimum} (a oficina tem ${reputation}).`;
  return null;
}

export function OrderList({ orders, reputation, openOrderIds, busyOrderId, onAccept }: OrderListProps) {
  if (orders.length === 0) {
    return <p className="rounded border border-zinc-700 p-4 text-sm text-zinc-300">Nenhuma ordem de serviço disponível no momento.</p>;
  }
  return (
    <ul className="grid grid-cols-1 gap-3 lg:grid-cols-2">
      {orders.map((order) => {
        const reason = lockReason(order, reputation, openOrderIds);
        const reasonId = `order-${order.order_id}-lock`;
        const isBusy = busyOrderId === order.order_id;
        return (
          <li key={order.order_id} className={`flex flex-col rounded border p-4 ${reason ? "border-zinc-800 opacity-75" : "border-zinc-700"}`}>
            <h3 className="font-semibold">{order.title}</h3>
            <p className="text-sm text-zinc-300">{order.client}</p>
            <p className="mt-2 flex-1 text-sm text-zinc-200">{order.briefing}</p>
            <dl className="mt-3 grid grid-cols-3 gap-2 text-sm">
              <div>
                <dt className="text-xs text-zinc-400">Pagamento</dt>
                <dd className="font-mono text-emerald-300">{formatBrl(order.payout_brl)}</dd>
              </div>
              <div>
                <dt className="text-xs text-zinc-400">Custo se quebrar</dt>
                <dd className="font-mono text-red-300">{formatBrl(order.engine_cost_brl)}</dd>
              </div>
              <div>
                <dt className="text-xs text-zinc-400">Reputação mínima</dt>
                <dd className="font-mono">{order.min_reputation ?? 0}</dd>
              </div>
            </dl>
            {reason && (
              <p id={reasonId} className="mt-3 text-xs text-amber-200">
                {reason}
              </p>
            )}
            <button
              type="button"
              disabled={reason !== null || busyOrderId !== null}
              aria-describedby={reason ? reasonId : undefined}
              aria-label={`Aceitar a ordem ${order.title}`}
              onClick={() => onAccept(order)}
              className="mt-3 self-start rounded bg-amber-500 px-4 py-1.5 font-semibold text-zinc-950 transition-transform hover:bg-amber-400 active:translate-y-px disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isBusy ? "A aceitar…" : "Aceitar"}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
