import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { TrendingUp, Clock, PieChart as PieIcon, Layers } from "lucide-react";
import { endpoints, type DailyPoint } from "@/lib/api";
import { fmtRub, fmtNum, fmtCompactInt, fmtPct, dayLabel } from "@/lib/format";
import { StatCard } from "@/components/StatCard";
import { cn } from "@/lib/cn";

const DAY_OPTIONS = [7, 30, 90, 180] as const;
const HOUR_DAY_OPTIONS = [1, 7, 30] as const;
const HOUR_RANGE = { 1: 24, 7: 24 * 7, 30: 24 * 30 } as const;

const METRICS = [
  { key: "revenue", label: "Доход", color: "#0EA5E9", fmt: fmtRub },
  { key: "new_users", label: "Юзеры", color: "#8B5CF6", fmt: fmtNum },
  { key: "payments", label: "Платежи", color: "#10B981", fmt: fmtNum },
  { key: "new_subs", label: "Подписки", color: "#F59E0B", fmt: fmtNum },
  { key: "new_paid_subs", label: "Платные", color: "#EC4899", fmt: fmtNum },
] as const;
type MetricKey = (typeof METRICS)[number]["key"];

const DONUT_COLORS = ["#0EA5E9", "#8B5CF6", "#10B981", "#F59E0B", "#EC4899", "#64748B"];

function SegPill<T extends string | number>({
  options, value, onChange, render,
}: { options: readonly T[]; value: T; onChange: (v: T) => void; render: (v: T) => string }) {
  return (
    <div className="inline-flex rounded-xl bg-bg-elevated p-0.5 text-xs font-medium">
      {options.map((o) => (
        <button key={String(o)} onClick={() => onChange(o)}
          className={cn("rounded-lg px-2.5 py-1 transition",
            o === value ? "bg-bg-card text-fg shadow-soft" : "text-fg-muted hover:text-fg")}>
          {render(o)}
        </button>
      ))}
    </div>
  );
}

export default function Analytics() {
  const [days, setDays] = useState<number>(30);
  const [metric, setMetric] = useState<MetricKey>("revenue");
  const [hourDays, setHourDays] = useState<number>(7);
  const [hourMetric, setHourMetric] = useState<MetricKey>("new_users");
  const [provHours, setProvHours] = useState<number>(720);

  const daily = useQuery({ queryKey: ["stats", "daily", days], queryFn: () => endpoints.daily(days), staleTime: 60_000 });
  const hourly = useQuery({ queryKey: ["stats", "hourly", hourDays], queryFn: () => endpoints.hourly(hourDays), staleTime: 60_000 });
  const providers = useQuery({ queryKey: ["stats", "providers", provHours], queryFn: () => endpoints.providers(provHours), staleTime: 60_000 });
  const breakdown = useQuery({ queryKey: ["stats", "breakdown"], queryFn: () => endpoints.breakdown(), staleTime: 60_000 });

  const activeMetric = METRICS.find((m) => m.key === metric)!;
  const series = daily.data?.series ?? [];

  // Totals over the selected daily range (footer KPIs).
  const sum = (k: keyof DailyPoint) => series.reduce((a, p) => a + (Number(p[k]) || 0), 0);
  const revTotal = sum("revenue");
  const payTotal = sum("payments");
  const usersTotal = sum("new_users");
  const avgCheck = payTotal ? revTotal / payTotal : 0;

  const provRows = providers.data ?? [];
  const provTotal = provRows.reduce((a, p) => a + p.revenue, 0);

  return (
    <div className="stagger-children space-y-6">
      <div>
        <div className="label">Аналитика</div>
        <h1 className="text-2xl font-bold tracking-tight">Аналитика ELMA</h1>
      </div>

      {/* Range totals */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label={`Доход за ${days}д`} value={fmtRub(revTotal)} loading={daily.isLoading} />
        <StatCard label={`Платежи за ${days}д`} value={fmtNum(payTotal)} loading={daily.isLoading} />
        <StatCard label={`Новые юзеры за ${days}д`} value={fmtNum(usersTotal)} loading={daily.isLoading} />
        <StatCard label="Средний чек" value={fmtRub(avgCheck)} loading={daily.isLoading} />
      </div>

      {/* Daily chart */}
      <div className="card card-pad">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2"><TrendingUp className="h-4 w-4 text-fg-subtle" /><h2 className="font-semibold">Динамика по дням</h2></div>
          <div className="flex flex-wrap items-center gap-2">
            <SegPill options={METRICS.map((m) => m.key)} value={metric} onChange={(v) => setMetric(v as MetricKey)}
              render={(k) => METRICS.find((m) => m.key === k)!.label} />
            <SegPill options={DAY_OPTIONS} value={days} onChange={setDays} render={(d) => `${d}д`} />
          </div>
        </div>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={series} margin={{ left: -12, right: 6, top: 4 }}>
              <defs>
                <linearGradient id="agrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={activeMetric.color} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={activeMetric.color} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#EEF0F4" vertical={false} />
              <XAxis dataKey="day" tickFormatter={dayLabel} tick={{ fontSize: 11, fill: "#94A3B8" }} axisLine={false} tickLine={false} minTickGap={24} />
              <YAxis tickFormatter={(v) => fmtCompactInt(metric === "revenue" ? v / 100 : v)} tick={{ fontSize: 11, fill: "#94A3B8" }} axisLine={false} tickLine={false} width={48} />
              <Tooltip contentStyle={{ borderRadius: 12, border: "1px solid #E5E7EB", fontSize: 12 }}
                labelFormatter={(l) => dayLabel(String(l))} formatter={(v: number) => [activeMetric.fmt(v), activeMetric.label]} />
              <Area type="monotone" dataKey={metric as keyof DailyPoint} stroke={activeMetric.color} strokeWidth={2} fill="url(#agrad)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Hourly chart */}
      <div className="card card-pad">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2"><Clock className="h-4 w-4 text-fg-subtle" /><h2 className="font-semibold">По часам · МСК</h2></div>
          <div className="flex flex-wrap items-center gap-2">
            <SegPill options={["new_users", "payments", "revenue"] as MetricKey[]} value={hourMetric} onChange={setHourMetric}
              render={(k) => METRICS.find((m) => m.key === k)!.label} />
            <SegPill options={HOUR_DAY_OPTIONS} value={hourDays} onChange={setHourDays} render={(d) => `${d}д`} />
          </div>
        </div>
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={hourly.data?.series ?? []} margin={{ left: -14, right: 6, top: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#EEF0F4" vertical={false} />
              <XAxis dataKey="hour" tick={{ fontSize: 10, fill: "#94A3B8" }} axisLine={false} tickLine={false} interval={1} />
              <YAxis tickFormatter={(v) => fmtCompactInt(hourMetric === "revenue" ? v / 100 : v)} tick={{ fontSize: 11, fill: "#94A3B8" }} axisLine={false} tickLine={false} width={44} />
              <Tooltip cursor={{ fill: "rgba(14,165,233,.06)" }} contentStyle={{ borderRadius: 12, border: "1px solid #E5E7EB", fontSize: 12 }}
                labelFormatter={(l) => `${l}:00–${Number(l) + 1}:00 МСК`}
                formatter={(v: number) => { const m = METRICS.find((x) => x.key === hourMetric)!; return [m.fmt(v), m.label]; }} />
              <Bar dataKey={hourMetric} radius={[5, 5, 0, 0]} fill={METRICS.find((m) => m.key === hourMetric)!.color} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <p className="mt-2 text-xs text-fg-muted">Учтено окно {HOUR_RANGE[hourDays as keyof typeof HOUR_RANGE]} ч.</p>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Providers donut */}
        <div className="card card-pad">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2"><PieIcon className="h-4 w-4 text-fg-subtle" /><h2 className="font-semibold">Доход по провайдерам</h2></div>
            <SegPill options={[24, 168, 720] as const} value={provHours} onChange={setProvHours}
              render={(h) => (h === 24 ? "24ч" : h === 168 ? "7д" : "30д")} />
          </div>
          {provRows.length === 0 ? (
            <div className="py-10 text-center text-sm text-fg-subtle">Нет оплат за период</div>
          ) : (
            <>
              <div className="h-52">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={provRows} dataKey="revenue" nameKey="provider" innerRadius="58%" outerRadius="88%" paddingAngle={2} stroke="none">
                      {provRows.map((_, i) => <Cell key={i} fill={DONUT_COLORS[i % DONUT_COLORS.length]} />)}
                    </Pie>
                    <Tooltip contentStyle={{ borderRadius: 12, border: "1px solid #E5E7EB", fontSize: 12 }}
                      formatter={(v: number, n) => [fmtRub(v), String(n)]} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div className="mt-2 space-y-1.5">
                {provRows.map((p, i) => (
                  <div key={p.provider} className="flex items-center justify-between text-sm">
                    <span className="flex items-center gap-2">
                      <span className="h-2.5 w-2.5 rounded-full" style={{ background: DONUT_COLORS[i % DONUT_COLORS.length] }} />
                      <span className="font-medium capitalize">{p.provider}</span>
                    </span>
                    <span className="text-fg-muted">{fmtRub(p.revenue)} · {fmtPct(provTotal ? (p.revenue / provTotal) * 100 : 0)}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        {/* Breakdown by tariff */}
        <div className="card card-pad">
          <div className="mb-3 flex items-center gap-2"><Layers className="h-4 w-4 text-fg-subtle" /><h2 className="font-semibold">Разбивка по тарифам (30д)</h2></div>
          {(breakdown.data ?? []).length === 0 ? (
            <div className="py-10 text-center text-sm text-fg-subtle">Нет данных</div>
          ) : (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart layout="vertical" data={breakdown.data ?? []} margin={{ left: 8, right: 12, top: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#EEF0F4" horizontal={false} />
                  <XAxis type="number" tickFormatter={(v) => fmtCompactInt(v / 100)} tick={{ fontSize: 11, fill: "#94A3B8" }} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="tariff_code" tick={{ fontSize: 11, fill: "#94A3B8" }} axisLine={false} tickLine={false} width={90} />
                  <Tooltip contentStyle={{ borderRadius: 12, border: "1px solid #E5E7EB", fontSize: 12 }}
                    formatter={(v: number, _n, item) => [`${fmtRub(v)} · ${fmtNum((item?.payload as { payments?: number })?.payments ?? 0)} пл.`, "Доход"]} />
                  <Bar dataKey="revenue" radius={[0, 5, 5, 0]} fill="#8B5CF6" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
