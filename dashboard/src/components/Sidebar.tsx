import { NavLink } from "react-router-dom";
import { LogOut, Zap } from "lucide-react";
import { sections } from "@/lib/nav";
import { logout } from "@/lib/auth";
import { cn } from "@/lib/cn";

export function Sidebar() {
  return (
    <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-border bg-bg-card px-3 py-5 lg:flex">
      <div className="flex items-center gap-2 px-2 pb-5">
        <div className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-accent to-secondary text-white shadow-cta">
          <Zap className="h-5 w-5" />
        </div>
        <div className="leading-tight">
          <div className="text-sm font-bold tracking-tight">ELMA</div>
          <div className="text-[11px] text-fg-subtle">Admin Console</div>
        </div>
      </div>

      <nav className="flex-1 space-y-5 overflow-y-auto">
        {sections.map((section) => (
          <div key={section.label}>
            <div className="label px-3 pb-1.5">{section.label}</div>
            <div className="space-y-0.5">
              {section.items.map(({ to, label, icon: Icon }) => (
                <NavLink
                  key={to}
                  to={`/${to}`}
                  end={to === ""}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-2.5 rounded-xl px-3 py-2 text-sm font-medium transition",
                      isActive
                        ? "bg-fg text-white shadow-cta"
                        : "text-fg-muted hover:bg-bg-elevated hover:text-fg",
                    )
                  }
                >
                  <Icon className="h-4 w-4" />
                  {label}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>

      <button onClick={logout} className="btn-ghost mt-2 justify-start">
        <LogOut className="h-4 w-4" /> Выйти
      </button>
    </aside>
  );
}
