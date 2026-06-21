import { useState } from "react";
import { Zap } from "lucide-react";
import { endpoints, ApiError } from "@/lib/api";
import { setToken } from "@/lib/auth";
import { Spinner } from "@/components/Spinner";

export default function Login({ onDone }: { onDone: () => void }) {
  const [password, setPassword] = useState("");
  const [tg, setTg] = useState("");
  const [advanced, setAdvanced] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await endpoints.login(password, advanced && tg ? Number(tg) : undefined);
      setToken(res.token);
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Не удалось войти");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="relative grid min-h-screen place-items-center overflow-hidden bg-bg px-5">
      {/* aurora */}
      <div className="pointer-events-none absolute -left-24 -top-24 h-72 w-72 rounded-full bg-accent/25 blur-3xl" />
      <div className="pointer-events-none absolute -bottom-24 -right-16 h-72 w-72 rounded-full bg-secondary/25 blur-3xl" />
      <div className="pointer-events-none absolute left-1/3 top-1/2 h-64 w-64 rounded-full bg-violet-400/20 blur-3xl" />

      <form
        onSubmit={submit}
        className="relative w-full max-w-sm rounded-2xl border border-white/50 bg-white/80 p-7 shadow-soft backdrop-blur-2xl animate-fade-up"
      >
        <div className="absolute inset-x-8 top-0 h-px bg-gradient-to-r from-transparent via-accent/60 to-transparent" />

        <div className="mb-6 flex flex-col items-center text-center">
          <div className="grid h-12 w-12 place-items-center rounded-2xl bg-gradient-to-br from-accent to-secondary text-white shadow-cta">
            <Zap className="h-6 w-6" />
          </div>
          <div className="mt-3 text-[11px] font-semibold uppercase tracking-[3px] text-fg-subtle">
            ELMA Admin
          </div>
          <h1 className="mt-1 text-xl font-bold tracking-tight">Вход в консоль</h1>
        </div>

        <label className="label mb-1 block">Пароль</label>
        <input
          type="password"
          autoFocus
          className="light-input"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="••••••••"
        />

        {advanced && (
          <div className="mt-3">
            <label className="label mb-1 block">Telegram ID (если админов несколько)</label>
            <input
              className="light-input"
              value={tg}
              onChange={(e) => setTg(e.target.value.replace(/\D/g, ""))}
              placeholder="123456789"
              inputMode="numeric"
            />
          </div>
        )}

        {error && <div className="mt-3 text-sm text-danger">{error}</div>}

        <button type="submit" disabled={busy || !password} className="btn-primary mt-5 w-full">
          {busy ? <Spinner className="h-4 w-4 text-white" /> : "Войти"}
        </button>

        <div className="mt-4 flex items-center justify-between text-xs text-fg-subtle">
          <button type="button" className="hover:text-fg" onClick={() => setAdvanced((v) => !v)}>
            {advanced ? "Скрыть" : "Указать Telegram ID"}
          </button>
          <span>Пароль — через /dashboard в боте</span>
        </div>
      </form>
    </div>
  );
}
