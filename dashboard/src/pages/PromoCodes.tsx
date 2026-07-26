import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ticket, Plus, Power, Trash2 } from "lucide-react";
import { endpoints, ApiError, type PromoRow, type PromoCreate } from "@/lib/api";
import { fmtNum, fmtDate } from "@/lib/format";
import { PageLoader, Spinner } from "@/components/Spinner";
import { EmptyState } from "@/components/EmptyState";
import { ConfirmButton } from "@/components/ConfirmButton";
import { cn } from "@/lib/cn";
import { toast } from "@/store/toast";

function rewardText(p: PromoRow): string {
  return p.kind === "days"
    ? `+${p.grant_days} дн. доступа`
    : `−${p.discount_pct}% на ${p.discount_days} дн.`;
}

export default function PromoCodes() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["promo"], queryFn: endpoints.promoList });
  const refresh = () => qc.invalidateQueries({ queryKey: ["promo"] });

  const toggle = useMutation({
    mutationFn: (code: string) => endpoints.promoToggle(code),
    onSuccess: refresh,
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : "Ошибка"),
  });
  const del = useMutation({
    mutationFn: (code: string) => endpoints.promoDelete(code),
    onSuccess: () => { toast.success("Промокод удалён"); refresh(); },
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : "Ошибка"),
  });

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-bold tracking-tight">Промокоды</h1>
        {list.data && <span className="text-sm text-fg-muted">{fmtNum(list.data.length)} шт.</span>}
      </div>

      <CreateForm onCreated={refresh} />

      {list.isLoading ? <PageLoader /> :
        (list.data ?? []).length === 0 ? <EmptyState icon={Ticket} title="Промокодов нет" /> : (
          <div className="card divide-y divide-border-subtle overflow-hidden">
            {list.data!.map((p) => {
              const expired = p.expires_at && new Date(p.expires_at) <= new Date();
              const exhausted = p.max_uses != null && p.uses >= p.max_uses;
              return (
                <div key={p.code} className={cn("flex flex-wrap items-center gap-3 px-4 py-3 text-sm", (!p.active || expired || exhausted) && "opacity-60")}>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <code className="rounded bg-bg-elevated px-1.5 py-0.5 font-mono font-semibold">{p.code}</code>
                      <span className="badge-muted">{rewardText(p)}</span>
                      {!p.active && <span className="text-[11px] text-fg-muted">выкл</span>}
                      {expired && <span className="text-[11px] text-danger">истёк</span>}
                      {exhausted && <span className="text-[11px] text-danger">исчерпан</span>}
                    </div>
                    <div className="text-xs text-fg-muted">
                      Использован: <b>{fmtNum(p.uses)}</b>{p.max_uses != null ? ` / ${fmtNum(p.max_uses)}` : " (∞)"}
                      {" · "}на юзера: {p.per_user_limit}
                      {p.expires_at ? ` · до ${fmtDate(p.expires_at)}` : ""}
                    </div>
                  </div>
                  <button className="btn-secondary" disabled={toggle.isPending} onClick={() => toggle.mutate(p.code)}>
                    {toggle.isPending && toggle.variables === p.code ? <Spinner className="h-4 w-4" /> : <Power className="h-4 w-4" />}
                    {p.active ? "Выкл" : "Вкл"}
                  </button>
                  <ConfirmButton variant="danger" icon={Trash2} idleLabel="Удалить" confirmLabel="Точно удалить?"
                    pending={del.isPending && del.variables === p.code} onConfirm={() => del.mutate(p.code)} />
                </div>
              );
            })}
          </div>
        )}
    </div>
  );
}

function CreateForm({ onCreated }: { onCreated: () => void }) {
  const [code, setCode] = useState("");
  const [kind, setKind] = useState<"discount" | "days">("discount");
  const [pct, setPct] = useState(20);
  const [discDays, setDiscDays] = useState(3);
  const [grantDays, setGrantDays] = useState(30);
  const [maxUses, setMaxUses] = useState("");
  const [perUser, setPerUser] = useState(1);
  const [expDays, setExpDays] = useState("");

  const create = useMutation({
    mutationFn: () => {
      const p: PromoCreate = {
        code, kind, per_user_limit: perUser,
        max_uses: maxUses ? Number(maxUses) : null,
        expires_days: expDays ? Number(expDays) : null,
      };
      if (kind === "discount") { p.discount_pct = pct; p.discount_days = discDays; }
      else p.grant_days = grantDays;
      return endpoints.promoCreate(p);
    },
    onSuccess: () => { toast.success("Промокод создан"); setCode(""); onCreated(); },
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : "Ошибка"),
  });

  return (
    <div className="card card-pad space-y-3">
      <div className="label">Новый промокод</div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label className="label mb-1 block">Код</label>
          <input className="input font-mono" value={code} placeholder="SALE20"
            onChange={(e) => setCode(e.target.value.replace(/[^A-Za-z0-9_-]/g, ""))} />
        </div>
        <div>
          <label className="label mb-1 block">Награда</label>
          <div className="flex gap-1 rounded-xl bg-bg-elevated p-1">
            <button onClick={() => setKind("discount")}
              className={cn("flex-1 rounded-lg px-3 py-1.5 text-sm font-medium", kind === "discount" ? "bg-bg-card shadow-sm" : "text-fg-muted")}>Скидка</button>
            <button onClick={() => setKind("days")}
              className={cn("flex-1 rounded-lg px-3 py-1.5 text-sm font-medium", kind === "days" ? "bg-bg-card shadow-sm" : "text-fg-muted")}>Дни доступа</button>
          </div>
        </div>
      </div>

      {kind === "discount" ? (
        <div className="grid grid-cols-2 gap-3">
          <NumField label="Скидка, %" value={pct} min={1} max={99} onChange={setPct} />
          <NumField label="Действует, дней" value={discDays} min={1} max={365} onChange={setDiscDays} />
        </div>
      ) : (
        <NumField label="Бонусных дней" value={grantDays} min={1} max={3650} onChange={setGrantDays} />
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div>
          <label className="label mb-1 block">Всего активаций</label>
          <input type="number" min={1} className="input" value={maxUses} placeholder="∞"
            onChange={(e) => setMaxUses(e.target.value)} />
        </div>
        <NumField label="На пользователя" value={perUser} min={1} max={100} onChange={setPerUser} />
        <div>
          <label className="label mb-1 block">Истекает через, дней</label>
          <input type="number" min={1} className="input" value={expDays} placeholder="без срока"
            onChange={(e) => setExpDays(e.target.value)} />
        </div>
      </div>

      <button className="btn-primary" disabled={create.isPending || code.length < 3} onClick={() => create.mutate()}>
        {create.isPending ? <Spinner className="h-4 w-4" /> : <Plus className="h-4 w-4" />} Создать
      </button>
    </div>
  );
}

function NumField({ label, value, min, max, onChange }: { label: string; value: number; min: number; max: number; onChange: (v: number) => void }) {
  return (
    <div>
      <label className="label mb-1 block">{label}</label>
      <input type="number" min={min} max={max} className="input" value={value}
        onChange={(e) => onChange(Math.min(max, Math.max(min, Number(e.target.value))))} />
    </div>
  );
}
