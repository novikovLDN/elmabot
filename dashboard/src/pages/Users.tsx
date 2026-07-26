import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Search, X, ShieldPlus, ShieldX, Users as UsersIcon, Wallet, Percent, RefreshCw } from "lucide-react";
import { endpoints, ApiError } from "@/lib/api";
import { fmtDate, fmtDateTime, fmtNum, fmtRub } from "@/lib/format";
import { PageLoader } from "@/components/Spinner";
import { EmptyState } from "@/components/EmptyState";
import { ConfirmButton } from "@/components/ConfirmButton";
import { toast } from "@/store/toast";

const PAY_STATUS: Record<string, string> = {
  paid: "badge-success", failed: "badge-danger", pending: "badge-warning", refunded: "badge-muted",
};
const PAY_LABEL: Record<string, string> = {
  paid: "успех", failed: "ошибка", pending: "ожидает", refunded: "возврат",
};

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
        <input className="input pl-9" placeholder="Поиск по @username или ID…"
          value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
      </div>

      <div className="card overflow-hidden">
        {list.isLoading ? <PageLoader /> :
          list.data && list.data.items.length === 0 ? <EmptyState icon={UsersIcon} title="Ничего не найдено" /> : (
            <div className="divide-y divide-border-subtle">
              {list.data?.items.map((row) => (
                <button key={row.telegram_id} onClick={() => setSelected(row.telegram_id)}
                  className="flex w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-bg-elevated">
                  <div className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-bg-elevated text-xs font-bold text-fg-muted">
                    {(row.username?.[0] ?? "#").toUpperCase()}
                  </div>
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

      {pages > 1 && <Pagination page={page} pages={pages} onChange={setPage} />}
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
  const [discPct, setDiscPct] = useState(20);
  const [discDays, setDiscDays] = useState(3);
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
    onSuccess: () => { toast.success("Доступ отозван"); refresh(); },
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : "Ошибка"),
  });
  const reissue = useMutation({
    mutationFn: () => endpoints.reissue(tg),
    onSuccess: () => { toast.success("Ключ перевыпущен"); refresh(); },
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : "Ошибка"),
  });
  const setDisc = useMutation({
    mutationFn: () => endpoints.setDiscount(tg, discPct, discDays),
    onSuccess: () => { toast.success(`Скидка −${discPct}% на ${discDays} дн.`); refresh(); },
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : "Ошибка"),
  });
  const clearDisc = useMutation({
    mutationFn: () => endpoints.clearDiscount(tg),
    onSuccess: () => { toast.success("Скидка снята"); refresh(); },
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : "Ошибка"),
  });

  const u = (detail.data?.user ?? {}) as Record<string, unknown>;
  const str = (k: string) => (u[k] == null ? "—" : String(u[k]));
  const payments = detail.data?.payments ?? [];
  const offerActive = !!u.offer_pct && !!u.offer_expires_at && new Date(u.offer_expires_at as string) > new Date();

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30 backdrop-blur-sm animate-fade-in" onClick={onClose}>
      <div className="h-full w-full max-w-md overflow-y-auto bg-bg-card shadow-soft animate-fade-up" onClick={(e) => e.stopPropagation()}>
        {/* header */}
        <div className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-border-subtle bg-bg-card/95 px-5 py-4 backdrop-blur">
          <div className="flex items-center gap-3">
            <div className="grid h-11 w-11 place-items-center rounded-full bg-gradient-to-br from-accent/15 to-secondary/15 text-sm font-bold text-accent">
              {(String(u.username ?? "#")[0] ?? "#").toUpperCase()}
            </div>
            <div>
              <div className="font-bold leading-tight">{u.username ? "@" + String(u.username) : "Пользователь"}</div>
              <div className="text-xs text-fg-subtle">{tg}</div>
            </div>
          </div>
          <button onClick={onClose} className="btn-ghost px-2"><X className="h-5 w-5" /></button>
        </div>

        {detail.isLoading ? <PageLoader /> : (
          <div className="space-y-4 p-5">
            <div className="grid grid-cols-2 gap-2.5 text-sm">
              <KV label="Подписка" value={`${str("sub_status")} · ${str("sub_source")}`} />
              <KV label="Истекает" value={fmtDateTime(u.expires_at as string)} />
              <KV label="Регистрация" value={fmtDate(u.created_at as string)} />
              <KV label="Достижимость" value={u.is_reachable ? "✓ да" : "✗ нет"} />
              <KV label="Оплат" value={String(detail.data?.user.payments_paid ?? 0)} />
              <KV label="Потрачено" value={fmtRub(Number(u.spent_kopecks ?? 0))} />
              <KV label="Приглашено" value={`${detail.data?.referral.invited ?? 0}`} />
              <KV label="Купили друзья" value={`${detail.data?.referral.purchased ?? 0}`} />
            </div>

            {/* access control — every action double-confirmed */}
            <div className="card card-pad space-y-3 border-accent/20">
              <div className="label">Управление доступом</div>
              <div className="flex items-center gap-2">
                <input type="number" min={1} className="input w-24" value={days}
                  onChange={(e) => setDays(Math.max(1, Number(e.target.value)))} />
                <span className="text-sm text-fg-muted">дней</span>
                <ConfirmButton className="ml-auto" variant="info" icon={ShieldPlus}
                  idleLabel="Выдать" confirmLabel={`Выдать ${days} дн.?`}
                  pending={grant.isPending} onConfirm={() => grant.mutate()} />
              </div>
              <ConfirmButton className="w-full" variant="secondary" icon={ShieldX}
                idleLabel="Отозвать доступ" confirmLabel="Точно отозвать доступ?"
                pending={revoke.isPending} onConfirm={() => revoke.mutate()} />
              <ConfirmButton className="w-full" variant="secondary" icon={RefreshCw}
                idleLabel="Перевыпустить ключ" confirmLabel="Точно перевыпустить? Старая ссылка перестанет работать"
                pending={reissue.isPending} onConfirm={() => reissue.mutate()} />
            </div>

            {/* personal discount (offer) */}
            <div className="card card-pad space-y-3">
              <div className="label">Персональная скидка</div>
              {offerActive ? (
                <div className="rounded-xl bg-bg-elevated px-3 py-2 text-sm">
                  Активна: <b>−{String(u.offer_pct)}%</b> до {fmtDateTime(u.offer_expires_at as string)}
                </div>
              ) : (
                <div className="text-xs text-fg-muted">Скидки нет — применится на экране покупки.</div>
              )}
              <div className="flex flex-wrap items-center gap-2">
                <input type="number" min={1} max={99} className="input w-20" value={discPct}
                  onChange={(e) => setDiscPct(Math.min(99, Math.max(1, Number(e.target.value))))} />
                <span className="text-sm text-fg-muted">% на</span>
                <input type="number" min={1} max={365} className="input w-20" value={discDays}
                  onChange={(e) => setDiscDays(Math.min(365, Math.max(1, Number(e.target.value))))} />
                <span className="text-sm text-fg-muted">дн.</span>
                <ConfirmButton className="ml-auto" variant="info" icon={Percent}
                  idleLabel="Дать скидку" confirmLabel={`−${discPct}% на ${discDays} дн.?`}
                  pending={setDisc.isPending} onConfirm={() => setDisc.mutate()} />
              </div>
              {offerActive && (
                <ConfirmButton className="w-full" variant="secondary" icon={X}
                  idleLabel="Снять скидку" confirmLabel="Точно снять?"
                  pending={clearDisc.isPending} onConfirm={() => clearDisc.mutate()} />
              )}
            </div>

            {/* full payment history */}
            <div>
              <div className="mb-2 flex items-center gap-2">
                <Wallet className="h-4 w-4 text-fg-subtle" />
                <div className="label">История платежей ({payments.length})</div>
              </div>
              <div className="card divide-y divide-border-subtle overflow-hidden text-sm">
                {payments.map((p, i) => (
                  <div key={i} className="flex items-center justify-between gap-3 px-3.5 py-2.5">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold">{fmtRub(Number(p.amount_kopecks))}</span>
                        {p.tariff_code ? <span className="badge-muted">{String(p.tariff_code)}</span> : null}
                      </div>
                      <div className="truncate text-xs text-fg-subtle">
                        {fmtDateTime(p.created_at as string)}
                        {p.provider && p.provider !== "unknown" ? ` · ${String(p.provider)}` : ""}
                      </div>
                    </div>
                    <span className={PAY_STATUS[String(p.status)] ?? "badge-muted"}>
                      {PAY_LABEL[String(p.status)] ?? String(p.status)}
                    </span>
                  </div>
                ))}
                {payments.length === 0 && <div className="px-3.5 py-4 text-fg-subtle">Платежей нет</div>}
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
