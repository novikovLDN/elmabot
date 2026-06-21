import { CheckCircle2, XCircle, Info } from "lucide-react";
import { useToastStore } from "@/store/toast";
import { cn } from "@/lib/cn";

const ICON = { success: CheckCircle2, error: XCircle, info: Info };
const TONE = {
  success: "border-success/30 text-success",
  error: "border-danger/30 text-danger",
  info: "border-accent/30 text-accent",
};

export function Toaster() {
  const toasts = useToastStore((s) => s.toasts);
  const remove = useToastStore((s) => s.remove);
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex flex-col items-center gap-2 px-4">
      {toasts.map((t) => {
        const Icon = ICON[t.kind];
        return (
          <button
            key={t.id}
            onClick={() => remove(t.id)}
            className={cn(
              "pointer-events-auto flex max-w-sm items-center gap-2 rounded-xl border bg-bg-card px-4 py-3 text-sm font-medium shadow-soft animate-fade-up",
              TONE[t.kind],
            )}
          >
            <Icon className="h-4 w-4 shrink-0" />
            <span className="text-fg">{t.text}</span>
          </button>
        );
      })}
    </div>
  );
}
