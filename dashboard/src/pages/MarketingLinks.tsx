import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link2, Plus, Power, Trash2, Copy } from "lucide-react";
import { endpoints, ApiError, type StatLinkRow } from "@/lib/api";
import { fmtNum, fmtRub, fmtPct } from "@/lib/format";
import { PageLoader, Spinner } from "@/components/Spinner";
import { EmptyState } from "@/components/EmptyState";
import { ConfirmButton } from "@/components/ConfirmButton";
import { cn } from "@/lib/cn";
import { toast } from "@/store/toast";

export default function MarketingLinks() {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const list = useQuery({ queryKey: ["links"], queryFn: endpoints.linksList, refetchInterval: 60_000 });
  const refresh = () => qc.invalidateQueries({ queryKey: ["links"] });

  const create = useMutation({
    mutationFn: () => endpoints.linkCreate(name.trim()),
    onSuccess: () => { toast.success("Ссылка создана"); setName(""); refresh(); },
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : "Ошибка"),
  });
  const toggle = useMutation({
    mutationFn: (id: number) => endpoints.linkToggle(id),
    onSuccess: refresh,
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : "Ошибка"),
  });
  const del = useMutation({
    mutationFn: (id: number) => endpoints.linkDelete(id),
    onSuccess: () => { toast.success("Ссылка удалена"); refresh(); },
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : "Ошибка"),
  });

  const copy = (link: string) => {
    navigator.clipboard?.writeText(link).then(
      () => toast.success("Ссылка скопирована"),
      () => toast.error("Не удалось скопировать"),
    );
  };

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-bold tracking-tight">Ссылки для трафика</h1>
        {list.data && <span className="text-sm text-fg-muted">{fmtNum(list.data.length)} шт.</span>}
      </div>

      <div className="card card-pad">
        <div className="label mb-2">Новая ссылка</div>
        <p className="mb-2 text-xs text-fg-muted">
          Отслеживает воронку канала/поста: клик → регистрация → триал → покупка. Slug выдаётся автоматически.
        </p>
        <div className="flex gap-2">
          <input className="input" value={name} placeholder="Напр. «Пост в канале X»"
            onChange={(e) => setName(e.target.value)} />
          <button className="btn-primary shrink-0" disabled={create.isPending || name.trim().length < 2} onClick={() => create.mutate()}>
            {create.isPending ? <Spinner className="h-4 w-4" /> : <Plus className="h-4 w-4" />} Создать
          </button>
        </div>
      </div>

      {list.isLoading ? <PageLoader /> :
        (list.data ?? []).length === 0 ? <EmptyState icon={Link2} title="Ссылок нет" /> : (
          <div className="space-y-3">
            {list.data!.map((l: StatLinkRow) => {
              const conv = l.new_users ? (l.paid / l.new_users) * 100 : 0;
              return (
                <div key={l.id} className={cn("card card-pad space-y-3", !l.active && "opacity-60")}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{l.name}</span>
                    <code className="rounded bg-bg-elevated px-1.5 py-0.5 font-mono text-xs">s-{l.slug}</code>
                    {!l.active && <span className="text-[11px] text-fg-muted">выкл</span>}
                    <button className="btn-ghost ml-auto px-2 text-xs" onClick={() => copy(l.link)}>
                      <Copy className="h-3.5 w-3.5" /> Копировать
                    </button>
                  </div>
                  <div className="truncate rounded-lg bg-bg-elevated px-2.5 py-1.5 font-mono text-xs text-fg-muted">{l.link}</div>
                  <div className="grid grid-cols-3 gap-2 text-center sm:grid-cols-6">
                    <Metric label="Клики" value={fmtNum(l.clicks)} />
                    <Metric label="Регистрации" value={fmtNum(l.new_users)} />
                    <Metric label="Триалы" value={fmtNum(l.trials)} />
                    <Metric label="Оплатили" value={fmtNum(l.paid)} />
                    <Metric label="Конверсия" value={fmtPct(conv)} />
                    <Metric label="Доход" value={fmtRub(l.revenue_kopecks)} />
                  </div>
                  <div className="flex gap-2">
                    <button className="btn-secondary" disabled={toggle.isPending} onClick={() => toggle.mutate(l.id)}>
                      {toggle.isPending && toggle.variables === l.id ? <Spinner className="h-4 w-4" /> : <Power className="h-4 w-4" />}
                      {l.active ? "Выключить" : "Включить"}
                    </button>
                    <ConfirmButton className="ml-auto" variant="danger" icon={Trash2} idleLabel="Удалить" confirmLabel="Точно удалить?"
                      pending={del.isPending && del.variables === l.id} onConfirm={() => del.mutate(l.id)} />
                  </div>
                </div>
              );
            })}
          </div>
        )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-bg-elevated px-2 py-1.5">
      <div className="text-[10px] text-fg-subtle">{label}</div>
      <div className="text-sm font-semibold tabular-nums">{value}</div>
    </div>
  );
}
