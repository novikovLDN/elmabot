import type { LucideIcon } from "lucide-react";

export function EmptyState({
  icon: Icon, title, hint,
}: { icon: LucideIcon; title: string; hint?: string }) {
  return (
    <div className="grid place-items-center gap-2 py-16 text-center">
      <div className="grid h-12 w-12 place-items-center rounded-2xl bg-bg-elevated text-fg-subtle">
        <Icon className="h-6 w-6" />
      </div>
      <div className="font-semibold text-fg">{title}</div>
      {hint && <div className="max-w-sm text-sm text-fg-muted">{hint}</div>}
    </div>
  );
}
