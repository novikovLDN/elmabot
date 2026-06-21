import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fingerprint, KeyRound, LogOut, Plus, Trash2 } from "lucide-react";
import { endpoints, ApiError } from "@/lib/api";
import { fmtDate, fmtNum } from "@/lib/format";
import { logout } from "@/lib/auth";
import { registerPasskey } from "@/lib/passkey";
import { PageLoader, Spinner } from "@/components/Spinner";
import { toast } from "@/store/toast";

export default function Settings() {
  const qc = useQueryClient();
  const s = useQuery({ queryKey: ["settings"], queryFn: endpoints.settings });
  const pk = useQuery({ queryKey: ["passkey-available"], queryFn: endpoints.passkeyAvailable });

  const addKey = useMutation({
    mutationFn: () => registerPasskey("Passkey"),
    onSuccess: () => { toast.success("Passkey добавлен"); qc.invalidateQueries({ queryKey: ["settings"] }); qc.invalidateQueries({ queryKey: ["passkey-available"] }); },
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : "Не удалось добавить ключ"),
  });
  const delKey = useMutation({
    mutationFn: (id: string) => endpoints.passkeyDelete(id),
    onSuccess: () => { toast.success("Ключ удалён"); qc.invalidateQueries({ queryKey: ["settings"] }); },
    onError: () => toast.error("Не удалось удалить"),
  });

  if (s.isLoading || !s.data) return <PageLoader />;
  const d = s.data;

  return (
    <div className="max-w-2xl space-y-5">
      <h1 className="text-2xl font-bold tracking-tight">Настройки</h1>

      <div className="card card-pad space-y-3">
        <div className="label">Аккаунт</div>
        <Row k="Админ" v={d.admin.username ? "@" + d.admin.username : String(d.admin.telegram_id)} />
        <Row k="Telegram ID" v={String(d.admin.telegram_id)} />
        <button onClick={logout} className="btn-secondary mt-1"><LogOut className="h-4 w-4" /> Выйти</button>
      </div>

      <div className="card card-pad space-y-3">
        <div className="label">Сервис</div>
        <Row k="Бренд" v={d.brand} />
        <Row k="Триал" v={`${d.trial_days} дн.`} />
        <Row k="Лимит устройств" v={fmtNum(d.device_limit)} />
        <Row k="Реф. бонус" v={`${d.referral_bonus_days} дн.`} />
        <Row k="Приём платежей" v={d.payments_enabled ? "включён" : "выключен"} />
      </div>

      <div className="card card-pad">
        <div className="label mb-2">Тарифы</div>
        <div className="divide-y divide-border-subtle text-sm">
          {d.tariffs.map((t) => (
            <div key={t.code} className="flex justify-between py-2">
              <span className="font-medium">{t.title}</span>
              <span className="text-fg-muted">{fmtNum(t.price_rub)} ₽ · {t.days} дн.{t.save_label ? ` · ${t.save_label}` : ""}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="card card-pad">
        <div className="mb-3 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <KeyRound className="h-4 w-4 text-fg-subtle" />
            <div className="label">Passkey / WebAuthn</div>
          </div>
          {pk.data?.available && (
            <button className="btn-info px-3 py-1.5 text-xs" disabled={addKey.isPending} onClick={() => addKey.mutate()}>
              {addKey.isPending ? <Spinner className="h-4 w-4 text-white" /> : <Plus className="h-4 w-4" />} Добавить
            </button>
          )}
        </div>

        {!pk.data?.available ? (
          <p className="text-sm text-fg-muted">
            WebAuthn недоступен на сервере. Используйте пароль (сброс — командой{" "}
            <span className="font-mono">/dashboard</span> в боте).
          </p>
        ) : d.passkeys.length === 0 ? (
          <p className="flex items-center gap-2 text-sm text-fg-muted">
            <Fingerprint className="h-4 w-4" /> Ключей нет — добавьте Passkey для быстрого входа.
          </p>
        ) : (
          <div className="divide-y divide-border-subtle text-sm">
            {d.passkeys.map((p) => (
              <div key={p.credential_id} className="flex items-center justify-between py-2">
                <div>
                  <div className="font-medium">{p.label ?? "Passkey"}</div>
                  <div className="text-xs text-fg-subtle">добавлен {fmtDate(p.created_at)}</div>
                </div>
                <button className="btn-ghost px-2 text-danger" onClick={() => delKey.mutate(p.credential_id)}>
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between text-sm">
      <span className="text-fg-muted">{k}</span>
      <span className="font-medium">{v}</span>
    </div>
  );
}
