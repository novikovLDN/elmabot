import { NavLink } from "react-router-dom";
import { mobileItems } from "@/lib/nav";
import { cn } from "@/lib/cn";

export function MobileNav() {
  return (
    <nav className="fixed inset-x-0 bottom-0 z-40 flex border-t border-border bg-bg-card/95 backdrop-blur lg:hidden"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}>
      {mobileItems.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={`/${to}`}
          end={to === ""}
          className={({ isActive }) =>
            cn(
              "flex flex-1 flex-col items-center gap-0.5 py-2.5 text-[10px] font-medium transition",
              isActive ? "text-accent" : "text-fg-subtle",
            )
          }
        >
          <Icon className="h-5 w-5" />
          {label}
        </NavLink>
      ))}
    </nav>
  );
}
