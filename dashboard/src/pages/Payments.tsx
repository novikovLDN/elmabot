import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CreditCard } from "lucide-react";
import { endpoints } from "@/lib/api";
import { fmtDateTime, fmtNum, fmtRub } from "@/lib/format";
import { PageLoader } from "@/components/Spinner";
import { EmptyState } from "@/components/EmptyState";
import { Pagination } from "./Users";

const STATUS: Record<string, string> = {
  paid: "badge-success", failed: "badge-danger", pending: "badge-warning", refunded: "badge-muted",
};
const STATUS_LABEL: Record<string, string> = {
  paid: "успех", failed: "ошибка", pending: "ожидает", refunded: "возврат",
};

export default function Payments() {
  const [page, setPage] = useState(1);
  const list = useQuery({ queryKey: ["payments", page], queryFn: () => endpoints.payments(page), refetchInterval: 60_000 });
  const prov = useQuery({ queryKey: ["payments", "providers"], queryFn: () => endpoints.paymentsByProvider(), refetchInterval: 5 * 60_000 });
  const pages = list.data ? Math.max(1, Math.ceil(list.data.total / list.data.limit)) : 1;

  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-bold tracking-tight">Платежи</h1>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {(prov.data ?? []).map((p) => (
          <div key={p.provider} className="card card-pad">
            <div className="label capitalize">{p.provider}</div>
            <div className="mt-1 text-lg font-bold">{fmtRub(p.revenue)}</div>
            <div className="text-xs text-fg-muted">{fmtNum(p.payments)} платежей</div>
          </div>
        ))}
      </div>

      <div className="card overflow-hidden">
        {list.isLoading ? <PageLoader /> :
          list.data && list.data.items.length === 0 ? <EmptyState icon={CreditCard} title="Платежей пока нет" /> : (
            <div className="divide-y divide-border-subtle">
              {list.data?.items.map((p, i) => (
                <div key={i} className="flex items-center gap-3 px-4 py-3 text-sm">
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium">
                      {p.username ? "@" + p.username : p.telegram_id}{" "}
                      <span className="text-xs text-fg-subtle">{p.tariff_code ?? ""}</span>
                    </div>
                    <div className="text-xs text-fg-muted">{fmtDateTime(p.created_at)} · {p.provider}</div>
                  </div>
                  <div className="font-semibold">{fmtRub(p.amount_kopecks)}</div>
                  <span className={STATUS[p.status] ?? "badge-muted"}>{STATUS_LABEL[p.status] ?? p.status}</span>
                </div>
              ))}
            </div>
          )}
      </div>

      {pages > 1 && <Pagination page={page} pages={pages} onChange={setPage} />}
    </div>
  );
}
