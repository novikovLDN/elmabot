import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, Send, TestTube2, Clock } from "lucide-react";
import {
  endpoints, ApiError,
  type BroadcastPayload, type SchedulePayload, type ScheduleKind,
} from "@/lib/api";
import { fmtNum } from "@/lib/format";
import { Spinner } from "@/components/Spinner";
import { ConfirmButton } from "@/components/ConfirmButton";
import { cn } from "@/lib/cn";
import { toast } from "@/store/toast";

const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
const PRESETS = [
  { key: "buy", label: "🛒 Купить доступ" },
  { key: "channel", label: "📣 Перейти в канал" },
  { key: "referral", label: "🫂 Пригласить друга" },
];
const KINDS: { key: ScheduleKind; label: string }[] = [
  { key: "once", label: "Однократно" },
  { key: "daily", label: "Ежедневно" },
  { key: "weekly", label: "Еженедельно" },
];

export default function BroadcastCreate() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const segs = useQuery({ queryKey: ["broadcasts", "segments"], queryFn: endpoints.segments });

  const [segment, setSegment] = useState(params.get("segment") || "all");
  const [text, setText] = useState("");
  const [photo, setPhoto] = useState("");
  const [btnText, setBtnText] = useState("");
  const [btnUrl, setBtnUrl] = useState("");
  const [presets, setPresets] = useState<Set<string>>(new Set());
  const [abTest, setAbTest] = useState(false);
  const [textB, setTextB] = useState("");

  // Clone: prefill message/photo/button from a past broadcast (segment is left
  // for the admin to re-pick, so nobody re-sends to the wrong audience).
  const cloneId = params.get("clone");
  const clone = useQuery({
    queryKey: ["broadcasts", "clone", cloneId],
    queryFn: () => endpoints.broadcastGet(Number(cloneId)),
    enabled: !!cloneId,
  });
  useEffect(() => {
    if (!clone.data) return;
    setText(clone.data.text || "");
    setPhoto(clone.data.photo_file_id || "");
    setBtnText(clone.data.button_text || "");
    setBtnUrl(clone.data.button_url || "");
    setPresets(new Set((clone.data.buttons || "").split(",").filter(Boolean)));
    setAbTest(clone.data.is_ab);
    setTextB(clone.data.text_b || "");
  }, [clone.data]);

  const [mode, setMode] = useState<"now" | "schedule">(params.get("schedule") ? "schedule" : "now");
  const [kind, setKind] = useState<ScheduleKind>("once");
  const [runAt, setRunAt] = useState(""); // 'YYYY-MM-DDTHH:MM' (MSK) for once
  const [timeMsk, setTimeMsk] = useState("12:00"); // for daily / weekly
  const [weekdays, setWeekdays] = useState<Set<number>>(new Set());

  const count = useMemo(
    () => segs.data?.find((s) => s.key === segment)?.count ?? 0,
    [segs.data, segment],
  );

  const base = (withSegment: boolean): BroadcastPayload => ({
    ...(withSegment ? { segment } : {}),
    text,
    photo_file_id: photo || undefined,
    button_text: btnText || undefined,
    button_url: btnUrl || undefined,
    buttons: presets.size ? [...presets] : undefined,
    text_b: abTest && mode === "now" ? textB || undefined : undefined,
    is_ab: abTest && mode === "now" && !!textB.trim(),
  });

  const togglePreset = (k: string) =>
    setPresets((prev) => {
      const next = new Set(prev);
      next.has(k) ? next.delete(k) : next.add(k);
      return next;
    });

  const schedulePayload = (): SchedulePayload => {
    const p: SchedulePayload = { ...base(true), kind };
    if (kind === "once") p.run_at_local = runAt;
    else {
      p.time_msk = timeMsk;
      if (kind === "weekly") p.weekdays = [...weekdays].sort((a, b) => a - b).join(",");
    }
    return p;
  };

  const test = useMutation({
    mutationFn: () => endpoints.broadcastTestSelf(base(false)),
    onSuccess: () => toast.success("Тест отправлен вам в бот"),
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : "Ошибка"),
  });
  const send = useMutation({
    mutationFn: () => endpoints.broadcastSend(base(true)),
    onSuccess: (r) => { toast.success(`Рассылка запущена: ${fmtNum(r.total)} получателей`); navigate("/broadcasts"); },
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : "Ошибка"),
  });
  const schedule = useMutation({
    mutationFn: () => endpoints.scheduledCreate(schedulePayload()),
    onSuccess: () => { toast.success("Рассылка запланирована"); navigate("/broadcasts"); },
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : "Ошибка"),
  });

  const empty = !text.trim() && !photo.trim();
  const scheduleInvalid =
    (kind === "once" && !runAt) ||
    (kind === "daily" && !timeMsk) ||
    (kind === "weekly" && (!timeMsk || weekdays.size === 0));

  function toggleDay(d: number) {
    setWeekdays((prev) => {
      const next = new Set(prev);
      next.has(d) ? next.delete(d) : next.add(d);
      return next;
    });
  }

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <button onClick={() => navigate(-1)} className="btn-ghost px-2 text-sm"><ArrowLeft className="h-4 w-4" /> Назад</button>
      <h1 className="text-2xl font-bold tracking-tight">{cloneId ? "Копия рассылки" : "Новая рассылка"}</h1>
      {cloneId && (
        <div className="rounded-xl bg-bg-elevated px-3 py-2 text-xs text-fg-muted">
          📋 Текст, фото и кнопка скопированы из рассылки #{cloneId}. <b>Сегмент выберите заново</b>, чтобы не отправить той же аудитории.
        </div>
      )}

      <div className="card card-pad space-y-4">
        <div>
          <label className="label mb-1 block">Сегмент</label>
          <select className="input" value={segment} onChange={(e) => setSegment(e.target.value)}>
            {(segs.data ?? []).map((s) => (
              <option key={s.key} value={s.key}>{s.label} — {fmtNum(s.count)}</option>
            ))}
          </select>
          <div className="mt-1 text-xs text-fg-muted">Получателей: <b>{fmtNum(count)}</b></div>
          {segs.data?.find((s) => s.key === segment)?.description && (
            <div className="mt-1 text-xs text-fg-subtle">💡 {segs.data.find((s) => s.key === segment)!.description}</div>
          )}
        </div>

        <div>
          <label className="label mb-1 block">Текст (HTML)</label>
          <textarea className="input min-h-[140px] font-mono text-sm" value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="<b>Заголовок</b>&#10;&#10;Текст сообщения…" />
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label className="label mb-1 block">photo file_id (необязательно)</label>
            <input className="input" value={photo} onChange={(e) => setPhoto(e.target.value)} placeholder="AgACAgIA…" />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="label mb-1 block">Кнопка</label>
              <input className="input" value={btnText} onChange={(e) => setBtnText(e.target.value)} placeholder="Текст" />
            </div>
            <div>
              <label className="label mb-1 block">URL</label>
              <input className="input" value={btnUrl} onChange={(e) => setBtnUrl(e.target.value)} placeholder="https://" />
            </div>
          </div>
        </div>

        {mode === "now" && (
          <div className="space-y-2">
            <label className="flex cursor-pointer items-center gap-2 text-sm font-medium">
              <input type="checkbox" checked={abTest} onChange={(e) => setAbTest(e.target.checked)} />
              A/B тест — два варианта текста, поровну по аудитории
            </label>
            {abTest && (
              <textarea className="input min-h-[120px] font-mono text-sm" value={textB}
                onChange={(e) => setTextB(e.target.value)}
                placeholder="Вариант B (вариант A — в поле выше)" />
            )}
          </div>
        )}

        <div>
          <label className="label mb-1 block">Готовые кнопки</label>
          <div className="flex flex-wrap gap-1.5">
            {PRESETS.map((p) => (
              <button key={p.key} type="button" onClick={() => togglePreset(p.key)}
                className={cn("rounded-lg px-3 py-1.5 text-sm font-medium transition",
                  presets.has(p.key) ? "btn-primary" : "btn-secondary")}>
                {p.label}
              </button>
            ))}
          </div>
          <div className="mt-1 text-xs text-fg-muted">
            Прикрепляются под сообщением к пользователям (можно вместе со своей кнопкой-ссылкой).
          </div>
        </div>

        {/* Когда отправлять */}
        <div>
          <label className="label mb-1 block">Когда отправлять</label>
          <div className="flex gap-1 rounded-xl bg-bg-elevated p-1">
            <button onClick={() => setMode("now")}
              className={cn("flex-1 rounded-lg px-3 py-1.5 text-sm font-medium transition", mode === "now" ? "bg-bg-surface shadow-sm" : "text-fg-muted")}>
              Сейчас
            </button>
            <button onClick={() => setMode("schedule")}
              className={cn("flex-1 rounded-lg px-3 py-1.5 text-sm font-medium transition", mode === "schedule" ? "bg-bg-surface shadow-sm" : "text-fg-muted")}>
              По расписанию
            </button>
          </div>
        </div>

        {mode === "schedule" && (
          <div className="space-y-3 rounded-xl border border-border-subtle p-3">
            <div className="flex flex-wrap gap-1">
              {KINDS.map((k) => (
                <button key={k.key} onClick={() => setKind(k.key)}
                  className={cn("rounded-lg px-3 py-1.5 text-sm font-medium transition", kind === k.key ? "btn-primary" : "btn-secondary")}>
                  {k.label}
                </button>
              ))}
            </div>

            {kind === "once" && (
              <div>
                <label className="label mb-1 block">Дата и время (МСК, не дальше 7 дней)</label>
                <input type="datetime-local" className="input" value={runAt} onChange={(e) => setRunAt(e.target.value)} />
              </div>
            )}
            {(kind === "daily" || kind === "weekly") && (
              <div>
                <label className="label mb-1 block">Время (МСК)</label>
                <input type="time" className="input max-w-[160px]" value={timeMsk} onChange={(e) => setTimeMsk(e.target.value)} />
              </div>
            )}
            {kind === "weekly" && (
              <div>
                <label className="label mb-1 block">Дни недели</label>
                <div className="flex flex-wrap gap-1.5">
                  {WEEKDAYS.map((w, i) => (
                    <button key={i} onClick={() => toggleDay(i)}
                      className={cn("h-9 w-11 rounded-lg text-sm font-medium transition", weekdays.has(i) ? "btn-primary" : "btn-secondary")}>
                      {w}
                    </button>
                  ))}
                </div>
              </div>
            )}
            <div className="text-xs text-fg-muted">🕒 Всё время — московское (МСК, UTC+3).</div>
          </div>
        )}

        <div className="rounded-xl bg-bg-elevated px-3 py-2 text-xs text-fg-muted">
          💡 Сначала нажмите <b>«Тест админу»</b> — бот пришлёт вам в личку готовое
          сообщение ровно в том виде, в котором его получат пользователи.
        </div>

        <div className="flex flex-wrap items-center gap-2 pt-1">
          <button className="btn-secondary" disabled={empty || test.isPending} onClick={() => test.mutate()}>
            {test.isPending ? <Spinner className="h-4 w-4" /> : <TestTube2 className="h-4 w-4" />} Тест админу
          </button>
          {mode === "now" ? (
            <ConfirmButton
              className="ml-auto" variant="primary" icon={Send}
              idleLabel="Отправить" confirmLabel={`Точно отправить ${fmtNum(count)}?`}
              pending={send.isPending} disabled={empty}
              onConfirm={() => send.mutate()}
            />
          ) : (
            <ConfirmButton
              className="ml-auto" variant="primary" icon={Clock}
              idleLabel="Запланировать" confirmLabel="Точно запланировать?"
              pending={schedule.isPending} disabled={empty || scheduleInvalid}
              onConfirm={() => schedule.mutate()}
            />
          )}
        </div>
      </div>
    </div>
  );
}
