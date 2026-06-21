import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Share2 } from "lucide-react";
import { endpoints } from "@/lib/api";
import { fmtNum } from "@/lib/format";
import { PageLoader } from "@/components/Spinner";
import { EmptyState } from "@/components/EmptyState";
import { StatCard } from "@/components/StatCard";
import { Pagination } from "./Users";

export default function Referrals() {
  const [page, setPage] = useState(1);
  const overall = useQuery({ queryKey: ["referrals", "overall"], queryFn: endpoints.referralsOverall, refetchInterval: 60_000 });
  const top = useQuery({ queryKey: ["referrals", "top", page], queryFn: () => endpoints.referralsTop(page), refetchInterval: 60_000 });
  const pages = top.data ? Math.max(1, Math.ceil(top.data.total / top.data.limit)) : 1;

  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-bold tracking-tight">Рефералы</h1>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatCard label="Всего приглашений" value={fmtNum(overall.data?.total)} loading={overall.isLoading} />
        <StatCard label="Оплативших друзей" value={fmtNum(overall.data?.credited)} loading={overall.isLoading} />
        <StatCard label="Активных рефереров" value={fmtNum(overall.data?.referrers)} loading={overall.isLoading} />
      </div>

      <div className="card overflow-hidden">
        <div className="border-b border-border-subtle px-4 py-2.5 text-sm font-semibold">Топ-рефереры</div>
        {top.isLoading ? <PageLoader /> :
          top.data && top.data.items.length === 0 ? <EmptyState icon={Share2} title="Пока никто не приглашал" /> : (
            <div className="divide-y divide-border-subtle">
              {top.data?.items.map((r, i) => (
                <div key={r.referrer_id} className="flex items-center gap-3 px-4 py-3 text-sm">
                  <span className="w-6 text-fg-subtle">{(page - 1) * 25 + i + 1}</span>
                  <div className="min-w-0 flex-1 truncate font-medium">
                    {r.username ? "@" + r.username : r.referrer_id}
                  </div>
                  <span className="text-fg-muted">приглашено {fmtNum(r.invited)}</span>
                  <span className="badge-success">купили {fmtNum(r.purchased)}</span>
                </div>
              ))}
            </div>
          )}
      </div>

      {pages > 1 && <Pagination page={page} pages={pages} onChange={setPage} />}
    </div>
  );
}
