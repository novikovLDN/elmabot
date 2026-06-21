import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ShieldCheck } from "lucide-react";
import { endpoints, ApiError } from "@/lib/api";
import { setToken } from "@/lib/auth";
import { Spinner } from "@/components/Spinner";

export default function SetupPassword({ onDone }: { onDone: () => void }) {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get("token") || "";
  const [state, setState] = useState<"checking" | "valid" | "invalid">("checking");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!token) { setState("invalid"); return; }
    endpoints
      .setupCheck(token)
      .then((r) => setState(r.valid ? "valid" : "invalid"))
      .catch(() => setState("invalid"));
  }, [token]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (pw.length < 8) return setError("Пароль — минимум 8 символов");
    if (pw !== pw2) return setError("Пароли не совпадают");
    setBusy(true);
    setError("");
    try {
      const res = await endpoints.setup(token, pw);
      setToken(res.token);
      onDone();
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Ошибка");
      setBusy(false);
    }
  }

  return (
    <div className="relative grid min-h-screen place-items-center overflow-hidden bg-bg px-5">
      <div className="pointer-events-none absolute -left-24 -top-24 h-72 w-72 rounded-full bg-accent/25 blur-3xl" />
      <div className="pointer-events-none absolute -bottom-24 -right-16 h-72 w-72 rounded-full bg-secondary/25 blur-3xl" />

      <div className="relative w-full max-w-sm rounded-2xl border border-white/50 bg-white/80 p-7 shadow-soft backdrop-blur-2xl animate-fade-up">
        <div className="mb-6 flex flex-col items-center text-center">
          <div className="grid h-12 w-12 place-items-center rounded-2xl bg-gradient-to-br from-accent to-secondary text-white shadow-cta">
            <ShieldCheck className="h-6 w-6" />
          </div>
          <h1 className="mt-3 text-xl font-bold tracking-tight">Новый пароль</h1>
          <p className="mt-1 text-sm text-fg-muted">Задайте пароль для входа в дашборд</p>
        </div>

        {state === "checking" && <div className="grid place-items-center py-6"><Spinner /></div>}

        {state === "invalid" && (
          <div className="rounded-xl bg-danger/10 px-4 py-3 text-sm text-danger">
            Ссылка недействительна или истекла. Получите новую командой /dashboard в боте.
          </div>
        )}

        {state === "valid" && (
          <form onSubmit={submit} className="space-y-3">
            <input type="password" autoFocus className="light-input" placeholder="Новый пароль"
              value={pw} onChange={(e) => setPw(e.target.value)} />
            <input type="password" className="light-input" placeholder="Повторите пароль"
              value={pw2} onChange={(e) => setPw2(e.target.value)} />
            {error && <div className="text-sm text-danger">{error}</div>}
            <button type="submit" disabled={busy} className="btn-primary w-full">
              {busy ? <Spinner className="h-4 w-4 text-white" /> : "Сохранить и войти"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
