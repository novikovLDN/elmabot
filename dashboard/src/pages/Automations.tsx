import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Zap, Power, Trash2, Pencil, Save, RotateCcw } from "lucide-react";
import {
  endpoints, ApiError,
  type BuiltinAutomation, type CustomAutomation, type AutomationCreate,
} from "@/lib/api";
import { fmtNum } from "@/lib/format";
import { PageLoader, Spinner } from "@/components/Spinner";
import { ConfirmButton } from "@/components/ConfirmButton";
import { cn } from "@/lib/cn";
import { toast } from "@/store/toast";

const TRIGGERS = [
  { key: "after_signup", label: "После регистрации", verb: "через" },
  { key: "after_trial_expire", label: "После конца триала (не купил)", verb: "через" },
  { key: "before_sub_expire", label: "До конца платной", verb: "за" },
  { key: "after_sub_expire", label: "После конца платной", verb: "через" },
  { key: "after_first_purchase", label: "После первой оплаты", verb: "через" },
  { key: "after_bypass_purchase", label: "Купил ГБ, но нет премиума", verb: "через" },
];
const SCOPES = [
  { key: "", label: "Без скидки" },
  { key: "all", label: "Скидка на все тарифы" },
  { key: "1m", label: "Скидка на 1 месяц" },
  { key: "3m", label: "Скидка на 3 месяца" },
  { key: "6m", label: "Скидка на 6 месяцев" },
  { key: "12m", label: "Скидка на 1 год" },
];
function triggerText(t: string, delay: number): string {
  const tr = TRIGGERS.find((x) => x.key === t);
  return `${tr?.label ?? t} · ${tr?.verb ?? "через"} ${delay} ч`;
}

const TABS = [
  { key: "builtin", label: "Встроенные" },
  { key: "custom", label: "Свои" },
] as const;

export default function Automations() {
  const [tab, setTab] = useState<"builtin" | "custom">("builtin");
  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2">
        <Zap className="h-5 w-5 text-accent" />
        <h1 className="text-2xl font-bold tracking-tight">Автоматические рассылки</h1>
      </div>
      <p className="text-sm text-fg-muted">
        Сообщения, которые бот отправляет сам по событиям (триал, продление, уход клиента).
        Встроенные можно отредактировать или выключить; свои — создать под любой триггер.
      </p>
      <div className="flex gap-1 rounded-xl bg-bg-elevated p-1">
        {TABS.map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={cn("rounded-lg px-3 py-1.5 text-sm font-medium transition",
              tab === t.key ? "bg-bg-surface shadow-sm" : "text-fg-muted hover:text-fg")}>
            {t.label}
          </button>
        ))}
      </div>
      {tab === "builtin" ? <BuiltinTab /> : <CustomTab />}
    </div>
  );
}

function BuiltinTab() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["automations", "builtin"], queryFn: endpoints.automationsBuiltin });
  const refresh = () => qc.invalidateQueries({ queryKey: ["automations", "builtin"] });
  if (list.isLoading) return <PageLoader />;
  return (
    <div className="space-y-3">
      {(list.data ?? []).map((a) => <BuiltinRow key={a.key} a={a} onSaved={refresh} />)}
    </div>
  );
}

function BuiltinRow({ a, onSaved }: { a: BuiltinAutomation; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(a.text_override ?? a.default);
  const [offset, setOffset] = useState(a.offset_hours ?? a.offset_default ?? 0);
  const editable = a.key !== "traffic";
  const save = useMutation({
    mutationFn: (p: { enabled: boolean; text: string; offset: number | null }) =>
      endpoints.automationSetBuiltin(a.key, p.enabled, p.text, p.offset),
    onSuccess: () => { toast.success("Сохранено"); onSaved(); },
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : "Ошибка"),
  });
  // Toggle preserves the current text + timing overrides.
  const curOffset = a.timing ? (a.offset_override ?? null) : null;
  return (
    <div className={cn("card card-pad space-y-2", !a.enabled && "opacity-70")}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">{a.name}</span>
        {a.text_override && <span className="badge-muted text-[11px]">текст изменён</span>}
        {a.offset_override != null && <span className="badge-muted text-[11px]">время изменено</span>}
        {!a.enabled && <span className="text-[11px] text-fg-muted">выключен</span>}
        <button className="btn-secondary ml-auto" disabled={save.isPending}
          onClick={() => save.mutate({ enabled: !a.enabled, text: a.text_override ?? "", offset: curOffset })}>
          <Power className="h-4 w-4" /> {a.enabled ? "Выключить" : "Включить"}
        </button>
        {editable && (
          <button className="btn-secondary" onClick={() => setOpen((v) => !v)}>
            {open ? "Скрыть" : "Настроить"}
          </button>
        )}
      </div>
      <div className="text-xs text-fg-muted">🕒 {a.when}{a.timing ? ` · сейчас: ${a.offset_hours} ч` : ""}</div>
      {open && editable && (
        <div className="space-y-2">
          {a.timing && (
            <div>
              <label className="label mb-1 block">{a.offset_label ?? "Время, часов"}</label>
              <input type="number" min={0} max={8760} className="input max-w-[160px]" value={offset}
                onChange={(e) => setOffset(Math.max(0, Math.min(8760, Number(e.target.value))))} />
            </div>
          )}
          <label className="label block">Текст</label>
          <textarea className="input min-h-[120px] font-mono text-sm" value={text} onChange={(e) => setText(e.target.value)} />
          <div className="text-xs text-fg-subtle">
            HTML + премиум-эмодзи <code>![🎁](tg://emoji?id=…)</code>.
          </div>
          <div className="flex gap-2">
            <button className="btn-primary" disabled={save.isPending}
              onClick={() => save.mutate({ enabled: a.enabled, text, offset: a.timing ? offset : null })}>
              {save.isPending ? <Spinner className="h-4 w-4" /> : <Save className="h-4 w-4" />} Сохранить
            </button>
            <button className="btn-secondary" onClick={() => {
              setText(a.default); setOffset(a.offset_default ?? 0);
              save.mutate({ enabled: a.enabled, text: "", offset: null });
            }}>
              <RotateCcw className="h-4 w-4" /> Сбросить
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

type FormValues = { name: string; trigger: string; delay: number; text: string; scope: string; pct: number; hours: number };
const EMPTY: FormValues = { name: "", trigger: "after_trial_expire", delay: 24, text: "", scope: "", pct: 20, hours: 24 };

function toCreate(v: FormValues): AutomationCreate {
  const p: AutomationCreate = { name: v.name, trigger_type: v.trigger, delay_hours: v.delay, text: v.text };
  if (v.scope) { p.discount_scope = v.scope; p.discount_pct = v.pct; p.discount_hours = v.hours; }
  return p;
}
function toUpdate(v: FormValues): Record<string, unknown> {
  return {
    name: v.name, trigger_type: v.trigger, delay_hours: v.delay, text: v.text,
    discount_pct: v.scope ? v.pct : "", discount_hours: v.hours, discount_scope: v.scope || "all",
  };
}
function fromAuto(a: CustomAutomation): FormValues {
  return {
    name: a.name, trigger: a.trigger_type, delay: a.delay_hours, text: a.text,
    scope: a.discount_scope && a.discount_pct ? a.discount_scope : "",
    pct: a.discount_pct ?? 20, hours: a.discount_hours ?? 24,
  };
}

function CustomTab() {
  const qc = useQueryClient();
  const [editing, setEditing] = useState<number | null>(null);
  const list = useQuery({ queryKey: ["automations", "custom"], queryFn: endpoints.automationsList });
  const refresh = () => qc.invalidateQueries({ queryKey: ["automations", "custom"] });
  const toggle = useMutation({
    mutationFn: (id: number) => endpoints.automationToggle(id),
    onSuccess: refresh, onError: (e) => toast.error(e instanceof ApiError ? e.detail : "Ошибка"),
  });
  const del = useMutation({
    mutationFn: (id: number) => endpoints.automationDelete(id),
    onSuccess: () => { toast.success("Удалено"); refresh(); },
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : "Ошибка"),
  });
  const create = useMutation({
    mutationFn: (v: FormValues) => endpoints.automationCreate(toCreate(v)),
    onSuccess: () => { toast.success("Автоматизация создана"); refresh(); },
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : "Ошибка"),
  });
  const update = useMutation({
    mutationFn: (arg: { id: number; v: FormValues }) => endpoints.automationUpdate(arg.id, toUpdate(arg.v)),
    onSuccess: () => { toast.success("Сохранено"); setEditing(null); refresh(); },
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : "Ошибка"),
  });

  return (
    <div className="space-y-4">
      <AutoForm title="Новая автоматизация" submitLabel="Создать" resetOnSubmit
        pending={create.isPending} onSubmit={(v) => create.mutate(v)} />

      {list.isLoading ? <PageLoader /> : (list.data ?? []).length === 0 ? (
        <div className="card card-pad text-sm text-fg-muted">Своих автоматизаций пока нет.</div>
      ) : (
        <div className="space-y-2">
          {list.data!.map((a: CustomAutomation) => (
            <div key={a.id} className={cn("card card-pad space-y-1", !a.enabled && "opacity-70")}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">{a.name}</span>
                {a.discount_pct ? <span className="badge-muted text-[11px]">−{a.discount_pct}% · {a.discount_hours}ч</span> : null}
                {!a.enabled && <span className="text-[11px] text-fg-muted">выключена</span>}
                <button className="btn-secondary ml-auto" onClick={() => setEditing(editing === a.id ? null : a.id)}>
                  <Pencil className="h-4 w-4" /> {editing === a.id ? "Скрыть" : "Изменить"}
                </button>
                <button className="btn-secondary" disabled={toggle.isPending} onClick={() => toggle.mutate(a.id)}>
                  <Power className="h-4 w-4" /> {a.enabled ? "Выкл" : "Вкл"}
                </button>
                <ConfirmButton variant="danger" icon={Trash2} idleLabel="Удалить" confirmLabel="Точно?"
                  pending={del.isPending && del.variables === a.id} onConfirm={() => del.mutate(a.id)} />
              </div>
              <div className="text-xs text-fg-muted">🕒 {triggerText(a.trigger_type, a.delay_hours)} · отправлено {fmtNum(a.sent_count)}</div>
              {editing === a.id ? (
                <div className="pt-2">
                  <AutoForm initial={fromAuto(a)} submitLabel="Сохранить"
                    pending={update.isPending} onSubmit={(v) => update.mutate({ id: a.id, v })} />
                </div>
              ) : (
                <div className="truncate text-xs text-fg-subtle">{a.text.replace(/<[^>]+>/g, "").slice(0, 100)}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AutoForm({ title, initial, submitLabel, pending, resetOnSubmit, onSubmit }: {
  title?: string; initial?: FormValues; submitLabel: string; pending: boolean;
  resetOnSubmit?: boolean; onSubmit: (v: FormValues) => void;
}) {
  const [v, setV] = useState<FormValues>(initial ?? EMPTY);
  const set = <K extends keyof FormValues>(k: K, val: FormValues[K]) => setV((p) => ({ ...p, [k]: val }));
  const submit = () => { onSubmit(v); if (resetOnSubmit) setV(EMPTY); };

  return (
    <div className={cn(title ? "card card-pad" : "rounded-xl border border-border-subtle p-3", "space-y-3")}>
      {title && <div className="label">{title}</div>}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label className="label mb-1 block">Название</label>
          <input className="input" value={v.name} placeholder="Напр. «Догон через 2 дня»" onChange={(e) => set("name", e.target.value)} />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="label mb-1 block">Триггер</label>
            <select className="input" value={v.trigger} onChange={(e) => set("trigger", e.target.value)}>
              {TRIGGERS.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
            </select>
          </div>
          <div>
            <label className="label mb-1 block">Через/за, часов</label>
            <input type="number" min={0} max={8760} className="input" value={v.delay}
              onChange={(e) => set("delay", Math.max(0, Math.min(8760, Number(e.target.value))))} />
          </div>
        </div>
      </div>
      <div>
        <label className="label mb-1 block">Текст (HTML + премиум-эмодзи)</label>
        <textarea className="input min-h-[110px] font-mono text-sm" value={v.text}
          onChange={(e) => set("text", e.target.value)} placeholder="<b>Заголовок</b>&#10;&#10;Текст…" />
      </div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <div>
          <label className="label mb-1 block">Скидка при отправке</label>
          <select className="input" value={v.scope} onChange={(e) => set("scope", e.target.value)}>
            {SCOPES.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
        </div>
        {v.scope && (
          <>
            <div>
              <label className="label mb-1 block">%</label>
              <input type="number" min={1} max={99} className="input" value={v.pct}
                onChange={(e) => set("pct", Math.max(1, Math.min(99, Number(e.target.value))))} />
            </div>
            <div>
              <label className="label mb-1 block">Часов действует</label>
              <input type="number" min={1} max={8760} className="input" value={v.hours}
                onChange={(e) => set("hours", Math.max(1, Math.min(8760, Number(e.target.value))))} />
            </div>
          </>
        )}
      </div>
      <button className="btn-primary" disabled={pending || v.name.trim().length < 2 || !v.text.trim()} onClick={submit}>
        {pending ? <Spinner className="h-4 w-4" /> : <Save className="h-4 w-4" />} {submitLabel}
      </button>
    </div>
  );
}
