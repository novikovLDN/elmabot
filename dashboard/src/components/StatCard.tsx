import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";

export function StatCard({
  label, value, icon: Icon, hint, accent = false, loading = false,
}: {
  label: string;
  value: React.ReactNode;
  icon?: LucideIcon;
  hint?: React.ReactNode;
  accent?: boolean;
  loading?: boolean;
}) {
  return (
    <div className="card card-pad hover-lift">
      <div className="flex items-start justify-between gap-3">
        <div className="label">{label}</div>
        {Icon && (
          <div className={cn("grid h-8 w-8 place-items-center rounded-xl",
            accent ? "bg-accent/10 text-accent" : "bg-bg-elevated text-fg-muted")}>
            <Icon className="h-4 w-4" />
          </div>
        )}
      </div>
      <div className="mt-2 text-2xl font-bold tracking-tight">
        {loading ? <span className="skeleton inline-block h-7 w-24 align-middle" /> : value}
      </div>
      {hint && <div className="mt-1 text-xs text-fg-muted">{hint}</div>}
    </div>
  );
}
