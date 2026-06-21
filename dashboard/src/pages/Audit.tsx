import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ScrollText } from "lucide-react";
import { endpoints } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import { PageLoader } from "@/components/Spinner";
import { EmptyState } from "@/components/EmptyState";
import { Pagination } from "./Users";

const ACTION: Record<string, string> = {
  grant: "badge-success", revoke: "badge-danger", broadcast: "badge-accent",
  password_set: "badge-muted",
};

export default function Audit() {
  const [page, setPage] = useState(1);
  const list = useQuery({ queryKey: ["audit", page], queryFn: () => endpoints.audit(page), refetchInterval: 60_000 });
  const pages = list.data ? Math.max(1, Math.ceil(list.data.total / list.data.limit)) : 1;

  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-bold tracking-tight">Аудит</h1>

      <div className="card overflow-hidden">
        {list.isLoading ? <PageLoader /> :
          list.data && list.data.items.length === 0 ? <EmptyState icon={ScrollText} title="Журнал пуст" /> : (
            <div className="divide-y divide-border-subtle">
              {list.data?.items.map((a) => (
                <div key={a.id} className="flex items-center gap-3 px-4 py-3 text-sm">
                  <span className={ACTION[a.action] ?? "badge-muted"}>{a.action}</span>
                  <div className="min-w-0 flex-1 truncate text-fg-muted">
                    {a.target_id ? (a.target_username ? "@" + a.target_username : `id ${a.target_id}`) : ""}
                    {a.detail ? ` · ${a.detail}` : ""}
                  </div>
                  <span className="text-xs text-fg-subtle">{fmtDateTime(a.created_at)}</span>
                </div>
              ))}
            </div>
          )}
      </div>

      {pages > 1 && <Pagination page={page} pages={pages} onChange={setPage} />}
    </div>
  );
}
