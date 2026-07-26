import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { Radio, History, Clock, Info, RefreshCw, Play, Pause, Trash2 } from "lucide-react";
import {
  endpoints, ApiError,
  type Segment, type BroadcastHistoryRow, type ScheduledRow,
} from "@/lib/api";
import { fmtNum, fmtDateTime } from "@/lib/format";
import { useEventStream } from "@/lib/ws";
import { PageLoader, Spinner } from "@/components/Spinner";
import { ConfirmButton } from "@/components/ConfirmButton";
import { cn } from "@/lib/cn";
import { toast } from "@/store/toast";

const GROUPS = ["База", "Триал-воронка", "Продление", "Возврат"] as const;
function groupOf(key: string): (typeof GROUPS)[number] {
  if (key.startsWith("exp_in_")) return "Продление";
  if (key.startsWith("expd_") || key === "paid_lapsed") return "Возврат";
  if (key.includes("trial") || key === "cold") return "Триал-воронка";
  return "База";
}

const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
const SOURCE_LABEL: Record<string, string> = { manual: "вручную", resend: "повтор", scheduled: "по расписанию" };
const KIND_LABEL: Record<string, string> = { once: "однократно", daily: "ежедневно", weekly: "еженедельно" };

function scheduleText(s: ScheduledRow): string {
  if (s.kind === "once") return `однократно · ${fmtDateTime(s.run_at)} МСК`;
  if (s.kind === "daily") return `ежедневно в ${s.time_msk ?? ""} МСК`;
  const days = (s.weekdays ?? "").split(",").filter(Boolean).map((d) => WEEKDAYS[Number(d)]).join(", ");
  return `еженедельно (${days}) в ${s.time_msk ?? ""} МСК`;
}

const TABS = [
  { key: "segments", label: "Сегменты", icon: Radio },
  { key: "history", label: "История", icon: History },
  { key: "scheduled", label: "Запланированные", icon: Clock },
  { key: "help", label: "Инструкция", icon: Info },
] as const;
type TabKey = (typeof TABS)[number]["key"];

export default function Broadcasts() {
  const [tab, setTab] = useState<TabKey>("segments");
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

      <div className="flex flex-wrap gap-1 rounded-xl bg-bg-elevated p-1">
        {TABS.map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={cn(
              "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition",
              tab === t.key ? "bg-bg-surface text-fg shadow-sm" : "text-fg-muted hover:text-fg",
            )}>
            <t.icon className="h-4 w-4" /> {t.label}
          </button>
        ))}
      </div>

      {tab === "segments" && <SegmentsTab />}
      {tab === "history" && <HistoryTab />}
      {tab === "scheduled" && <ScheduledTab />}
      {tab === "help" && <HelpTab />}
    </div>
  );
}

function SegmentsTab() {
  const navigate = useNavigate();
  const segs = useQuery({ queryKey: ["broadcasts", "segments"], queryFn: endpoints.segments, refetchInterval: 5 * 60_000 });
  const grouped = (segs.data ?? []).reduce<Record<string, Segment[]>>((acc, s) => {
    (acc[groupOf(s.key)] ||= []).push(s);
    return acc;
  }, {});
  if (segs.isLoading) return <PageLoader />;
  return (
    <div className="space-y-5">
      {GROUPS.filter((g) => grouped[g]?.length).map((g) => (
        <div key={g}>
          <div className="label mb-2 px-1">{g}</div>
          <div className="card divide-y divide-border-subtle overflow-hidden">
            {grouped[g].map((s) => (
              <button key={s.key} onClick={() => navigate(`/broadcasts/new?segment=${s.key}`)}
                className="flex w-full items-center justify-between px-4 py-3 text-left text-sm transition hover:bg-bg-elevated">
                <span className="font-medium">{s.label}</span>
                <span className="font-bold text-accent">{fmtNum(s.count)}</span>
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function HistoryTab() {
  const qc = useQueryClient();
  const hist = useQuery({ queryKey: ["broadcasts", "history"], queryFn: () => endpoints.broadcastHistory(500) });
  const resend = useMutation({
    mutationFn: (id: number) => endpoints.broadcastResend(id),
    onSuccess: (r) => { toast.success(`Повтор запущен: ${fmtNum(r.total)} получателей`); qc.invalidateQueries({ queryKey: ["broadcasts", "history"] }); },
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : "Ошибка"),
  });

  if (hist.isLoading) return <PageLoader />;
  const rows = hist.data ?? [];
  if (!rows.length) return <div className="card card-pad text-sm text-fg-muted">Рассылок пока не было.</div>;

  return (
    <div className="card divide-y divide-border-subtle overflow-hidden">
      {rows.map((b: BroadcastHistoryRow) => (
        <div key={b.id} className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="font-medium">{b.segment}</span>
              <span className="rounded bg-bg-elevated px-1.5 py-0.5 text-[11px] text-fg-muted">{SOURCE_LABEL[b.source] ?? b.source}</span>
              {b.status === "running" && <span className="text-[11px] text-accent">идёт…</span>}
            </div>
            <div className="truncate text-xs text-fg-muted">
              {fmtDateTime(b.created_at)} МСК · {b.text ? b.text.replace(/<[^>]+>/g, "").slice(0, 80) : "🖼 фото"}
            </div>
          </div>
          <div className="text-right text-xs tabular-nums">
            <div>👥 {fmtNum(b.total)} · 📨 {fmtNum(b.sent)}</div>
            <div className="text-fg-muted">🚫 {fmtNum(b.blocked)} · ⚠️ {fmtNum(b.failed)}</div>
          </div>
          <ConfirmButton
            variant="secondary" icon={RefreshCw} idleLabel="Повтор" confirmLabel="Точно повторить?"
            pending={resend.isPending && resend.variables === b.id}
            disabled={b.status === "running"}
            onConfirm={() => resend.mutate(b.id)}
          />
        </div>
      ))}
    </div>
  );
}

function ScheduledTab() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["broadcasts", "scheduled"], queryFn: endpoints.scheduledList, refetchInterval: 60_000 });
  const toggle = useMutation({
    mutationFn: (id: number) => endpoints.scheduledToggle(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["broadcasts", "scheduled"] }),
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : "Ошибка"),
  });
  const cancel = useMutation({
    mutationFn: (id: number) => endpoints.scheduledCancel(id),
    onSuccess: () => { toast.success("Расписание удалено"); qc.invalidateQueries({ queryKey: ["broadcasts", "scheduled"] }); },
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : "Ошибка"),
  });

  if (list.isLoading) return <PageLoader />;
  const rows = list.data ?? [];

  return (
    <div className="space-y-4">
      <Link to="/broadcasts/new?schedule=1" className="btn-primary inline-flex"><Clock className="h-4 w-4" /> Запланировать рассылку</Link>
      {!rows.length ? (
        <div className="card card-pad text-sm text-fg-muted">Запланированных рассылок нет.</div>
      ) : (
        <div className="card divide-y divide-border-subtle overflow-hidden">
          {rows.map((s: ScheduledRow) => (
            <div key={s.id} className={cn("flex flex-wrap items-center gap-3 px-4 py-3 text-sm", !s.active && "opacity-60")}>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{s.segment}</span>
                  <span className="rounded bg-bg-elevated px-1.5 py-0.5 text-[11px] text-fg-muted">{KIND_LABEL[s.kind] ?? s.kind}</span>
                  {!s.active && <span className="text-[11px] text-fg-muted">на паузе</span>}
                </div>
                <div className="truncate text-xs text-fg-muted">{scheduleText(s)}</div>
                <div className="text-xs text-fg-muted">
                  Ближайший запуск: <b>{fmtDateTime(s.run_at)} МСК</b>
                  {s.run_count > 0 && ` · выполнено ${s.run_count}×`}
                </div>
              </div>
              <button className="btn-secondary" disabled={toggle.isPending} onClick={() => toggle.mutate(s.id)}>
                {toggle.isPending && toggle.variables === s.id ? <Spinner className="h-4 w-4" />
                  : s.active ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                {s.active ? "Пауза" : "Возобновить"}
              </button>
              <ConfirmButton
                variant="danger" icon={Trash2} idleLabel="Удалить" confirmLabel="Точно удалить?"
                pending={cancel.isPending && cancel.variables === s.id}
                onConfirm={() => cancel.mutate(s.id)}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function HelpTab() {
  return (
    <div className="card card-pad space-y-4 text-sm leading-relaxed">
      <div>
        <div className="mb-1 text-base font-bold">📋 Инструкция для админа</div>
        <p className="text-fg-muted">Всё время в дашборде — <b>московское (МСК, UTC+3)</b>. Именно по нему планируются и показываются рассылки.</p>
      </div>

      <Section title="1. Отправить сейчас">
        Кнопка <b>«Новая»</b> → выберите сегмент, напишите текст (можно HTML:
        <code className="mx-1 rounded bg-bg-elevated px-1">&lt;b&gt;</code>,
        <code className="mx-1 rounded bg-bg-elevated px-1">&lt;i&gt;</code>,
        ссылки), при желании укажите <b>photo file_id</b> и кнопку (текст + URL).
        Сначала жмите <b>«Тест админу»</b> — бот пришлёт вам сообщение ровно
        в том виде, в котором его получат пользователи. Затем <b>«Отправить»</b>.
      </Section>

      <Section title="2. История (последние 500)">
        Вкладка <b>«История»</b> — все прошедшие рассылки: сегмент, время (МСК),
        доставлено / заблокировали / ошибки. Кнопка <b>«Повтор»</b> отправляет
        ту же рассылку заново текущему составу сегмента (состав пересчитывается
        на момент повтора).
      </Section>

      <Section title="3. Запланировать / повторяющиеся">
        Вкладка <b>«Запланированные»</b> → <b>«Запланировать рассылку»</b>.
        Три режима:
        <ul className="mt-1 list-disc space-y-0.5 pl-5">
          <li><b>Однократно</b> — дата и время (МСК), не дальше 7 дней.</li>
          <li><b>Ежедневно</b> — время (МСК), каждый день.</li>
          <li><b>Еженедельно</b> — дни недели + время (МСК).</li>
        </ul>
        Расписание можно <b>поставить на паузу</b> и <b>возобновить</b> (при
        возобновлении ближайший запуск переносится на следующий слот, чтобы не
        сработать сразу), либо <b>удалить</b>. «Ближайший запуск» показывает,
        когда сработает в следующий раз.
      </Section>

      <Section title="4. Сегменты и результат">
        Состав сегмента считается в момент отправки. По завершении каждый админ
        получает в бот итог: доставлено / заблокировали / ошибок. Прогресс
        больших рассылок виден вверху этой страницы в реальном времени.
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border-t border-border-subtle pt-3">
      <div className="mb-1 font-semibold">{title}</div>
      <div className="text-fg-muted">{children}</div>
    </div>
  );
}
