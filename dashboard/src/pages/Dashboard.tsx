import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import {
  Wallet, Users as UsersIcon, CreditCard, TrendingUp, Activity, Radio, Gift, Share2,
} from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { endpoints, type DailyPoint } from "@/lib/api";
import { fmtRub, fmtNum, fmtCompactInt, dayLabel } from "@/lib/format";
import { useEventStream } from "@/lib/ws";
import { StatCard } from "@/components/StatCard";
import { cn } from "@/lib/cn";

const DAY_OPTIONS = [7, 30, 90, 180] as const;

const METRICS = [
  { key: "revenue", label: "Доход", color: "#0EA5E9", fmt: fmtRub },
  { key: "new_users", label: "Юзеры", color: "#8B5CF6", fmt: fmtNum },
  { key: "payments", label: "Платежи", color: "#10B981", fmt: fmtNum },
  { key: "new_paid_subs", label: "Платные", color: "#EC4899", fmt: fmtNum },
] as const;
type MetricKey = (typeof METRICS)[number]["key"];

function SegPill<T extends string | number>({
  options, value, onChange, render,
}: { options: readonly T[]; value: T; onChange: (v: T) => void; render: (v: T) => string }) {
  return (
    <div className="inline-flex rounded-xl bg-bg-elevated p-0.5 text-xs font-medium">
      {options.map((o) => (
        <button
          key={String(o)}
          onClick={() => onChange(o)}
          className={cn("rounded-lg px-2.5 py-1 transition",
            o === value ? "bg-bg-card text-fg shadow-soft" : "text-fg-muted hover:text-fg")}
        >
          {render(o)}
        </button>
      ))}
    </div>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [days, setDays] = useState<number>(30);
  const [metric, setMetric] = useState<MetricKey>("revenue");
  const events = useEventStream();

  const ov = useQuery({ queryKey: ["stats", "overview"], queryFn: endpoints.overview, refetchInterval: 60_000 });
  const daily = useQuery({
    queryKey: ["stats", "daily", days], queryFn: () => endpoints.daily(days),
    refetchInterval: 5 * 60_000, staleTime: 60_000,
  });
  const providers = useQuery({ queryKey: ["stats", "providers"], queryFn: () => endpoints.providers(), refetchInterval: 5 * 60_000 });
  const segs = useQuery({ queryKey: ["broadcasts", "segments"], queryFn: endpoints.segments, refetchInterval: 5 * 60_000 });

  const u = ov.data?.users;
  const h = ov.data?.health;
  const activeMetric = METRICS.find((m) => m.key === metric)!;
  const series = daily.data?.series ?? [];

  const conv = u && u.users_total ? (u.buyers / u.users_total) * 100 : 0;

  return (
    <div className="stagger-children space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="label">Обзор</div>
          <h1 className="text-2xl font-bold tracking-tight">Дашборд ELMA</h1>
        </div>
        <Link to="/broadcasts/new" className="btn-primary">
          <Radio className="h-4 w-4" /> Новая рассылка
        </Link>
      </div>

      {/* Hero KPIs */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Доход всего" icon={Wallet} accent loading={ov.isLoading}
          value={fmtRub(u?.revenue_total)} hint={`Сегодня: ${fmtRub(u?.revenue_today)}`} />
        <StatCard label="Активные подписки" icon={Activity} loading={ov.isLoading}
          value={fmtNum(h?.active_total)} hint={`Платных: ${fmtNum(h?.active_paid)} · триал: ${fmtNum(h?.active_trial)}`} />
        <StatCard label="Платящие" icon={CreditCard} loading={ov.isLoading}
          value={fmtNum(u?.buyers)} hint={`Платежей: ${fmtNum(u?.payments_paid)}`} />
        <StatCard label="Пользователи" icon={UsersIcon} loading={ov.isLoading}
          value={fmtNum(u?.users_total)} hint={`Сегодня: +${fmtNum(u?.users_today)}`} />
      </div>

      {/* Daily chart */}
      <div className="card card-pad">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-fg-subtle" />
            <h2 className="font-semibold">Динамика</h2>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <SegPill options={METRICS.map((m) => m.key)} value={metric}
              onChange={(v) => setMetric(v as MetricKey)}
              render={(k) => METRICS.find((m) => m.key === k)!.label} />
            <SegPill options={DAY_OPTIONS} value={days} onChange={setDays} render={(d) => `${d}д`} />
          </div>
        </div>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={series} margin={{ left: -12, right: 6, top: 4 }}>
              <defs>
                <linearGradient id="grad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={activeMetric.color} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={activeMetric.color} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#EEF0F4" vertical={false} />
              <XAxis dataKey="day" tickFormatter={dayLabel} tick={{ fontSize: 11, fill: "#94A3B8" }}
                axisLine={false} tickLine={false} minTickGap={24} />
              <YAxis tickFormatter={(v) => fmtCompactInt(metric === "revenue" ? v / 100 : v)}
                tick={{ fontSize: 11, fill: "#94A3B8" }} axisLine={false} tickLine={false} width={48} />
              <Tooltip
                contentStyle={{ borderRadius: 12, border: "1px solid #E5E7EB", fontSize: 12 }}
                labelFormatter={(l) => dayLabel(String(l))}
                formatter={(v: number) => [activeMetric.fmt(v), activeMetric.label]} />
              <Area type="monotone" dataKey={metric as keyof DailyPoint} stroke={activeMetric.color}
                strokeWidth={2} fill="url(#grad)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Subscriptions health */}
      <div>
        <h2 className="mb-3 font-semibold">Подписки · здоровье</h2>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatCard label="Активные" value={fmtNum(h?.active_total)} loading={ov.isLoading} />
          <StatCard label="Платные активные" value={fmtNum(h?.active_paid)} loading={ov.isLoading} />
          <StatCard label="Триалы активные" value={fmtNum(h?.active_trial)} loading={ov.isLoading} />
          <StatCard label="Конверсия в покупку" value={conv.toFixed(1) + "%"} loading={ov.isLoading}
            hint={`${fmtNum(u?.buyers)} из ${fmtNum(u?.users_total)}`} />
        </div>
      </div>

      {/* Providers + segments */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="card card-pad">
          <h2 className="mb-3 font-semibold">Провайдеры (30 дней)</h2>
          <div className="space-y-2">
            {(providers.data ?? []).map((p) => (
              <div key={p.provider} className="flex items-center justify-between rounded-xl bg-bg-elevated px-3 py-2 text-sm">
                <span className="font-medium capitalize">{p.provider}</span>
                <span className="text-fg-muted">{fmtNum(p.payments)} · {fmtRub(p.revenue)}</span>
              </div>
            ))}
            {providers.data && providers.data.length === 0 && (
              <div className="py-6 text-center text-sm text-fg-subtle">Пока нет оплат</div>
            )}
          </div>
        </div>

        <div className="card card-pad">
          <h2 className="mb-3 font-semibold">Сегменты для рассылок</h2>
          <div className="flex flex-wrap gap-2">
            {(segs.data ?? []).slice(0, 14).map((s) => (
              <button key={s.key}
                onClick={() => navigate(`/broadcasts/new?segment=${s.key}`)}
                className="badge-muted hover:bg-border-subtle">
                {s.label} <span className="ml-1 font-semibold text-fg">{fmtNum(s.count)}</span>
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Live stream */}
      <div className="card card-pad">
        <div className="mb-3 flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-success" />
          </span>
          <h2 className="font-semibold">Живой поток событий</h2>
        </div>
        <div className="divide-y divide-border-subtle">
          {events.length === 0 && <div className="py-6 text-center text-sm text-fg-subtle">Ожидание событий…</div>}
          {events.map((e, i) => (
            <div key={i} className="flex items-center justify-between gap-3 py-2 text-sm">
              <span className="font-mono text-xs text-accent">{e.type}</span>
              <span className="truncate text-fg-muted">
                {"telegram_id" in e ? `id ${String(e.telegram_id)}` : ""}
                {"segment" in e ? ` ${String(e.segment)}` : ""}
                {"sent" in e ? ` ✓${String(e.sent)}` : ""}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Quick links */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Link to="/referrals" className="card card-pad hover-lift flex items-center gap-2 text-sm font-medium">
          <Share2 className="h-4 w-4 text-accent" /> Рефералы
        </Link>
        <Link to="/gifts" className="card card-pad hover-lift flex items-center gap-2 text-sm font-medium">
          <Gift className="h-4 w-4 text-accent" /> Гифты
        </Link>
        <Link to="/payments" className="card card-pad hover-lift flex items-center gap-2 text-sm font-medium">
          <CreditCard className="h-4 w-4 text-accent" /> Платежи
        </Link>
        <Link to="/users" className="card card-pad hover-lift flex items-center gap-2 text-sm font-medium">
          <UsersIcon className="h-4 w-4 text-accent" /> Пользователи
        </Link>
      </div>
    </div>
  );
}
