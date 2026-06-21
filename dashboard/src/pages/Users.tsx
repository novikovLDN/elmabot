import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Search, X, ShieldPlus, ShieldX, Users as UsersIcon } from "lucide-react";
import { endpoints, ApiError } from "@/lib/api";
import { fmtDate, fmtDateTime, fmtNum, fmtRub } from "@/lib/format";
import { PageLoader, Spinner } from "@/components/Spinner";
import { EmptyState } from "@/components/EmptyState";
import { toast } from "@/store/toast";
import { cn } from "@/lib/cn";

function subBadge(row: { sub_status: string | null; sub_source: string | null }) {
  if (row.sub_status !== "active") return <span className="badge-muted">нет</span>;
  return row.sub_source === "trial"
    ? <span className="badge-warning">триал</span>
    : <span className="badge-success">платная</span>;
}

export default function Users() {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<number | null>(null);

  const list = useQuery({
    queryKey: ["users", q, page],
    queryFn: () => endpoints.users(q, page),
    refetchInterval: 60_000,
  });

  const pages = list.data ? Math.max(1, Math.ceil(list.data.total / list.data.limit)) : 1;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-bold tracking-tight">Пользователи</h1>
        {list.data && <span className="text-sm text-fg-muted">{fmtNum(list.data.total)} всего</span>}
      </div>

      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-subtle" />
        <input
          className="input pl-9"
          placeholder="Поиск по @username или ID…"
          value={q}
          onChange={(e) => { setQ(e.target.value); setPage(1); }}
        />
      </div>

      <div className="card overflow-hidden">
        {list.isLoading ? (
          <PageLoader />
        ) : list.data && list.data.items.length === 0 ? (
          <EmptyState icon={UsersIcon} title="Ничего не найдено" />
        ) : (
          <div className="divide-y divide-border-subtle">
            {list.data?.items.map((row) => (
              <button
                key={row.telegram_id}
                onClick={() => setSelected(row.telegram_id)}
                className="flex w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-bg-elevated"
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium">
                    {row.username ? "@" + row.username : "—"}{" "}
                    <span className="text-xs text-fg-subtle">{row.telegram_id}</span>
                  </div>
                  <div className="text-xs text-fg-muted">рег. {fmtDate(row.created_at)}</div>
                </div>
                <div className="hidden text-right text-xs text-fg-muted sm:block">
                  {row.payments_paid > 0 ? `${row.payments_paid} опл.` : "—"}
                </div>
                {subBadge(row)}
              </button>
            ))}
          </div>
        )}
      </div>

      {pages > 1 && (
        <Pagination page={page} pages={pages} onChange={setPage} />
      )}

      {selected !== null && <UserDrawer tg={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

export function Pagination({ page, pages, onChange }: { page: number; pages: number; onChange: (p: number) => void }) {
  return (
    <div className="flex items-center justify-center gap-2 text-sm">
      <button className="btn-secondary" disabled={page <= 1} onClick={() => onChange(page - 1)}>Назад</button>
      <span className="text-fg-muted">{page} / {pages}</span>
      <button className="btn-secondary" disabled={page >= pages} onClick={() => onChange(page + 1)}>Вперёд</button>
    </div>
  );
}

function UserDrawer({ tg, onClose }: { tg: number; onClose: () => void }) {
  const qc = useQueryClient();
  const [days, setDays] = useState(30);
  const [confirmRevoke, setConfirmRevoke] = useState(false);
  const detail = useQuery({ queryKey: ["users", "detail", tg], queryFn: () => endpoints.user(tg) });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["users"] });
    qc.invalidateQueries({ queryKey: ["stats"] });
  };

  const grant = useMutation({
    mutationFn: () => endpoints.grant(tg, days),
    onSuccess: () => { toast.success(`Выдано ${days} дн.`); refresh(); },
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : "Ошибка"),
  });
  const revoke = useMutation({
    mutationFn: () => endpoints.revoke(tg),
    onSuccess: () => { toast.success("Доступ отозван"); setConfirmRevoke(false); refresh(); },
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : "Ошибка"),
  });

  const u = (detail.data?.user ?? {}) as Record<string, unknown>;
  const str = (k: string) => (u[k] == null ? "—" : String(u[k]));

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30 animate-fade-in" onClick={onClose}>
      <div className="h-full w-full max-w-md overflow-y-auto bg-bg-card p-5 shadow-soft animate-fade-up"
        onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-bold">
            {u.username ? "@" + String(u.username) : "Пользователь"}
          </h2>
          <button onClick={onClose} className="btn-ghost px-2"><X className="h-5 w-5" /></button>
        </div>

        {detail.isLoading ? <PageLoader /> : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 text-sm">
              <KV label="Telegram ID" value={String(tg)} />
              <KV label="Подписка" value={`${str("sub_status")} / ${str("sub_source")}`} />
              <KV label="Истекает" value={fmtDateTime(u.expires_at as string)} />
              <KV label="Регистрация" value={fmtDate(u.created_at as string)} />
              <KV label="Оплат" value={String(detail.data?.user.payments_paid ?? 0)} />
              <KV label="Потрачено" value={fmtRub(Number(u.spent_kopecks ?? 0))} />
              <KV label="Приглашено" value={`${detail.data?.referral.invited ?? 0}`} />
              <KV label="Достижимость" value={u.is_reachable ? "да" : "нет"} />
            </div>

            <div className="card card-pad space-y-3">
              <div className="label">Выдать / продлить доступ</div>
              <div className="flex items-center gap-2">
                <input type="number" min={1} className="input w-28" value={days}
                  onChange={(e) => setDays(Math.max(1, Number(e.target.value)))} />
                <span className="text-sm text-fg-muted">дней</span>
                <button className="btn-info ml-auto" disabled={grant.isPending} onClick={() => grant.mutate()}>
                  {grant.isPending ? <Spinner className="h-4 w-4 text-white" /> : <ShieldPlus className="h-4 w-4" />} Выдать
                </button>
              </div>
              <button
                className={cn("w-full", confirmRevoke ? "btn-danger" : "btn-secondary")}
                disabled={revoke.isPending}
                onClick={() => (confirmRevoke ? revoke.mutate() : setConfirmRevoke(true))}
              >
                <ShieldX className="h-4 w-4" />
                {confirmRevoke ? "Точно отозвать?" : "Отозвать доступ"}
              </button>
            </div>

            <div>
              <div className="label mb-2">Последние платежи</div>
              <div className="divide-y divide-border-subtle text-sm">
                {(detail.data?.payments ?? []).map((p, i) => (
                  <div key={i} className="flex justify-between py-1.5">
                    <span className="text-fg-muted">{fmtDate(p.created_at as string)}</span>
                    <span>{fmtRub(Number(p.amount_kopecks))} · {String(p.status)}</span>
                  </div>
                ))}
                {(detail.data?.payments ?? []).length === 0 && (
                  <div className="py-3 text-fg-subtle">Платежей нет</div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function KV({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-bg-elevated px-3 py-2">
      <div className="text-[11px] text-fg-subtle">{label}</div>
      <div className="truncate font-medium">{value}</div>
    </div>
  );
}
