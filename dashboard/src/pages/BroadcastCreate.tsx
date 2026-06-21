import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, Send, TestTube2 } from "lucide-react";
import { endpoints, ApiError, type BroadcastPayload } from "@/lib/api";
import { fmtNum } from "@/lib/format";
import { Spinner } from "@/components/Spinner";
import { ConfirmButton } from "@/components/ConfirmButton";
import { toast } from "@/store/toast";

export default function BroadcastCreate() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const segs = useQuery({ queryKey: ["broadcasts", "segments"], queryFn: endpoints.segments });

  const [segment, setSegment] = useState(params.get("segment") || "all");
  const [text, setText] = useState("");
  const [photo, setPhoto] = useState("");
  const [btnText, setBtnText] = useState("");
  const [btnUrl, setBtnUrl] = useState("");

  const count = useMemo(
    () => segs.data?.find((s) => s.key === segment)?.count ?? 0,
    [segs.data, segment],
  );

  const payload = (withSegment: boolean): BroadcastPayload => ({
    ...(withSegment ? { segment } : {}),
    text,
    photo_file_id: photo || undefined,
    button_text: btnText || undefined,
    button_url: btnUrl || undefined,
  });

  const test = useMutation({
    mutationFn: () => endpoints.broadcastTestSelf(payload(false)),
    onSuccess: () => toast.success("Тест отправлен вам в бот"),
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : "Ошибка"),
  });
  const send = useMutation({
    mutationFn: () => endpoints.broadcastSend(payload(true)),
    onSuccess: (r) => { toast.success(`Рассылка запущена: ${fmtNum(r.total)} получателей`); navigate("/broadcasts"); },
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : "Ошибка"),
  });

  const empty = !text.trim() && !photo.trim();

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <button onClick={() => navigate(-1)} className="btn-ghost px-2 text-sm"><ArrowLeft className="h-4 w-4" /> Назад</button>
      <h1 className="text-2xl font-bold tracking-tight">Новая рассылка</h1>

      <div className="card card-pad space-y-4">
        <div>
          <label className="label mb-1 block">Сегмент</label>
          <select className="input" value={segment} onChange={(e) => setSegment(e.target.value)}>
            {(segs.data ?? []).map((s) => (
              <option key={s.key} value={s.key}>{s.label} — {fmtNum(s.count)}</option>
            ))}
          </select>
          <div className="mt-1 text-xs text-fg-muted">Получателей: <b>{fmtNum(count)}</b></div>
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

        <div className="rounded-xl bg-bg-elevated px-3 py-2 text-xs text-fg-muted">
          💡 Сначала нажмите <b>«Тест админу»</b> — бот пришлёт вам в личку готовое
          сообщение ровно в том виде, в котором его получат пользователи.
        </div>

        <div className="flex flex-wrap items-center gap-2 pt-1">
          <button className="btn-secondary" disabled={empty || test.isPending} onClick={() => test.mutate()}>
            {test.isPending ? <Spinner className="h-4 w-4" /> : <TestTube2 className="h-4 w-4" />} Тест админу
          </button>
          <ConfirmButton
            className="ml-auto" variant="primary" icon={Send}
            idleLabel="Отправить" confirmLabel={`Точно отправить ${fmtNum(count)}?`}
            pending={send.isPending} disabled={empty}
            onConfirm={() => send.mutate()}
          />
        </div>
      </div>
    </div>
  );
}
