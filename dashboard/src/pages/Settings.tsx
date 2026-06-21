import { useQuery } from "@tanstack/react-query";
import { KeyRound, LogOut } from "lucide-react";
import { endpoints } from "@/lib/api";
import { fmtNum } from "@/lib/format";
import { logout } from "@/lib/auth";
import { PageLoader } from "@/components/Spinner";

export default function Settings() {
  const s = useQuery({ queryKey: ["settings"], queryFn: endpoints.settings });

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
        <div className="mb-2 flex items-center gap-2">
          <KeyRound className="h-4 w-4 text-fg-subtle" />
          <div className="label">Passkey / WebAuthn</div>
        </div>
        {d.passkeys.length === 0 ? (
          <p className="text-sm text-fg-muted">
            Ключей нет. Вход по Passkey появится в следующем обновлении — пока используйте пароль
            (сброс — командой <span className="font-mono">/dashboard</span> в боте).
          </p>
        ) : (
          <div className="divide-y divide-border-subtle text-sm">
            {d.passkeys.map((p) => (
              <div key={p.credential_id} className="flex justify-between py-2">
                <span className="font-medium">{p.label ?? "Passkey"}</span>
                <span className="text-fg-subtle">{p.credential_id.slice(0, 12)}…</span>
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
