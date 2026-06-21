import { useEffect, useRef, useState } from "react";
import { AlertTriangle } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Spinner } from "./Spinner";
import { cn } from "@/lib/cn";

type Variant = "primary" | "danger" | "info" | "secondary";
const BASE: Record<Variant, string> = {
  primary: "btn-primary", danger: "btn-danger", info: "btn-info", secondary: "btn-secondary",
};

/** Two-step confirmation button: the first click "arms" it (turns into a danger
 *  "точно?" state), a second click within 3.5s fires. Every destructive admin
 *  action goes through this. */
export function ConfirmButton({
  onConfirm, idleLabel, confirmLabel = "Точно? Нажмите ещё раз",
  variant = "primary", icon: Icon, pending, disabled, className,
}: {
  onConfirm: () => void;
  idleLabel: React.ReactNode;
  confirmLabel?: React.ReactNode;
  variant?: Variant;
  icon?: LucideIcon;
  pending?: boolean;
  disabled?: boolean;
  className?: string;
}) {
  const [armed, setArmed] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => () => clearTimeout(timer.current), []);

  function click() {
    if (disabled || pending) return;
    if (armed) {
      clearTimeout(timer.current);
      setArmed(false);
      onConfirm();
    } else {
      setArmed(true);
      timer.current = setTimeout(() => setArmed(false), 3500);
    }
  }

  return (
    <button
      onClick={click}
      disabled={disabled || pending}
      className={cn(armed ? "btn-danger animate-fade-in" : BASE[variant], className)}
    >
      {pending ? <Spinner className="h-4 w-4 text-white" />
        : armed ? <AlertTriangle className="h-4 w-4" />
        : Icon ? <Icon className="h-4 w-4" /> : null}
      {armed ? confirmLabel : idleLabel}
    </button>
  );
}
