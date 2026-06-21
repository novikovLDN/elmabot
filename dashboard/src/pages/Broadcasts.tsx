import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { Radio } from "lucide-react";
import { endpoints, type Segment } from "@/lib/api";
import { fmtNum } from "@/lib/format";
import { useEventStream } from "@/lib/ws";
import { PageLoader } from "@/components/Spinner";

const GROUPS = ["База", "Триал-воронка", "Истекает скоро", "Закончилась"] as const;
function groupOf(key: string): (typeof GROUPS)[number] {
  if (key.startsWith("exp_")) return "Истекает скоро";
  if (key.startsWith("expd_")) return "Закончилась";
  if (key.includes("trial")) return "Триал-воронка";
  return "База";
}

export default function Broadcasts() {
  const navigate = useNavigate();
  const segs = useQuery({ queryKey: ["broadcasts", "segments"], queryFn: endpoints.segments, refetchInterval: 5 * 60_000 });
  const events = useEventStream().filter((e) => e.type.startsWith("broadcast"));

  const grouped = (segs.data ?? []).reduce<Record<string, Segment[]>>((acc, s) => {
    (acc[groupOf(s.key)] ||= []).push(s);
    return acc;
  }, {});

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

      {segs.isLoading ? <PageLoader /> : (
        <div className="space-y-5">
          {GROUPS.filter((g) => grouped[g]?.length).map((g) => (
            <div key={g}>
              <div className="label mb-2 px-1">{g}</div>
              <div className="card divide-y divide-border-subtle overflow-hidden">
                {grouped[g].map((s) => (
                  <button key={s.key}
                    onClick={() => navigate(`/broadcasts/new?segment=${s.key}`)}
                    className="flex w-full items-center justify-between px-4 py-3 text-left text-sm transition hover:bg-bg-elevated">
                    <span className="font-medium">{s.label}</span>
                    <span className="font-bold text-accent">{fmtNum(s.count)}</span>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
