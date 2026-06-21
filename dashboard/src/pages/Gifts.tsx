import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Gift } from "lucide-react";
import { endpoints } from "@/lib/api";
import { fmtDate, fmtNum } from "@/lib/format";
import { PageLoader } from "@/components/Spinner";
import { EmptyState } from "@/components/EmptyState";
import { Pagination } from "./Users";

export default function Gifts() {
  const [page, setPage] = useState(1);
  const list = useQuery({ queryKey: ["gifts", page], queryFn: () => endpoints.gifts(page), refetchInterval: 60_000 });
  const pages = list.data ? Math.max(1, Math.ceil(list.data.total / list.data.limit)) : 1;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Гифты</h1>
        {list.data && <span className="text-sm text-fg-muted">{fmtNum(list.data.total)} всего</span>}
      </div>

      <div className="card overflow-hidden">
        {list.isLoading ? <PageLoader /> :
          list.data && list.data.items.length === 0 ? <EmptyState icon={Gift} title="Подарков пока нет" /> : (
            <div className="divide-y divide-border-subtle">
              {list.data?.items.map((g) => (
                <div key={g.code} className="flex items-center gap-3 px-4 py-3 text-sm">
                  <div className="min-w-0 flex-1">
                    <div className="font-mono text-xs text-fg-muted">{g.code}</div>
                    <div className="text-xs text-fg-subtle">
                      от {g.created_by_username ? "@" + g.created_by_username : g.created_by}
                      {g.redeemed_by ? ` → ${g.redeemed_by_username ? "@" + g.redeemed_by_username : g.redeemed_by}` : ""}
                    </div>
                  </div>
                  <span className="badge-muted">{g.tariff_code}</span>
                  {g.status === "redeemed"
                    ? <span className="badge-success">активирован</span>
                    : <span className="badge-warning">ожидает</span>}
                  <span className="hidden text-xs text-fg-subtle sm:block">{fmtDate(g.created_at)}</span>
                </div>
              ))}
            </div>
          )}
      </div>

      {pages > 1 && <Pagination page={page} pages={pages} onChange={setPage} />}
    </div>
  );
}
