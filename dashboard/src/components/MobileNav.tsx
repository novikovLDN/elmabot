import { useState } from "react";
import { NavLink } from "react-router-dom";
import { Menu, X } from "lucide-react";
import { mobileItems, sections } from "@/lib/nav";
import { cn } from "@/lib/cn";

// 4 primary tabs on the bottom bar; everything else lives behind «Ещё».
const primary = mobileItems.slice(0, 4);

export function MobileNav() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <nav className="fixed inset-x-0 bottom-0 z-40 flex border-t border-border bg-bg-card/95 backdrop-blur lg:hidden"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}>
        {primary.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={`/${to}`} end={to === ""}
            className={({ isActive }) => cn(
              "flex flex-1 flex-col items-center gap-0.5 py-2.5 text-[10px] font-medium transition",
              isActive ? "text-accent" : "text-fg-subtle",
            )}>
            <Icon className="h-5 w-5" />
            {label}
          </NavLink>
        ))}
        <button onClick={() => setOpen(true)}
          className="flex flex-1 flex-col items-center gap-0.5 py-2.5 text-[10px] font-medium text-fg-subtle transition">
          <Menu className="h-5 w-5" />
          Ещё
        </button>
      </nav>

      {open && (
        <div className="fixed inset-0 z-50 flex flex-col justify-end bg-black/40 backdrop-blur-sm lg:hidden animate-fade-in"
          onClick={() => setOpen(false)}>
          <div className="max-h-[80vh] overflow-y-auto rounded-t-2xl border-t border-border bg-bg-card p-4 animate-fade-up"
            style={{ paddingBottom: "calc(env(safe-area-inset-bottom) + 16px)" }}
            onClick={(e) => e.stopPropagation()}>
            <div className="mb-3 flex items-center justify-between">
              <span className="font-bold">Меню</span>
              <button onClick={() => setOpen(false)} className="btn-ghost px-2"><X className="h-5 w-5" /></button>
            </div>
            {sections.map((s) => (
              <div key={s.label} className="mb-3">
                <div className="label mb-1 px-1">{s.label}</div>
                <div className="grid grid-cols-2 gap-2">
                  {s.items.map(({ to, label, icon: Icon }) => (
                    <NavLink key={to} to={`/${to}`} end={to === ""} onClick={() => setOpen(false)}
                      className={({ isActive }) => cn(
                        "flex items-center gap-2 rounded-xl px-3 py-2.5 text-sm font-medium transition",
                        isActive ? "bg-accent/10 text-accent" : "bg-bg-elevated text-fg hover:bg-border-subtle",
                      )}>
                      <Icon className="h-4 w-4 shrink-0" />
                      <span className="truncate">{label}</span>
                    </NavLink>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
