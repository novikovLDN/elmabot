import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { Megaphone, Radio } from "lucide-react";
import { endpoints } from "@/lib/api";
import { fmtNum } from "@/lib/format";
import { useEventStream } from "@/lib/ws";
import { PageLoader } from "@/components/Spinner";

export default function Broadcasts() {
  const navigate = useNavigate();
  const segs = useQuery({ queryKey: ["broadcasts", "segments"], queryFn: endpoints.segments, refetchInterval: 5 * 60_000 });
  const events = useEventStream().filter((e) => e.type.startsWith("broadcast"));

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-bold tracking-tight">Рассылки</h1>
        <Link to="/broadcasts/new" className="btn-primary"><Radio className="h-4 w-4" /> Новая</Link>
      </div>

      {events.length > 0 && (
        <div className="card card-pad">
          <div className="label mb-2">Текущий прогресс</div>
          <div className="space-y-1 text-sm">
            {events.slice(0, 5).map((e, i) => (
              <div key={i} className="flex justify-between">
                <span className="font-mono text-xs text-accent">{e.type}</span>
                <span className="text-fg-muted">
                  {"sent" in e ? `отправлено ${String(e.sent)} / ${String(e.total ?? "")}` : ""}
                  {"total" in e && !("sent" in e) ? `получателей ${String(e.total)}` : ""}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="card overflow-hidden">
        <div className="flex items-center gap-2 border-b border-border-subtle px-4 py-2.5 text-sm font-semibold">
          <Megaphone className="h-4 w-4 text-fg-subtle" /> Сегменты аудитории
        </div>
        {segs.isLoading ? <PageLoader /> : (
          <div className="divide-y divide-border-subtle">
            {(segs.data ?? []).map((s) => (
              <button key={s.key}
                onClick={() => navigate(`/broadcasts/new?segment=${s.key}`)}
                className="flex w-full items-center justify-between px-4 py-3 text-left text-sm transition hover:bg-bg-elevated">
                <span className="font-medium">{s.label}</span>
                <span className="badge-muted">{fmtNum(s.count)}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
