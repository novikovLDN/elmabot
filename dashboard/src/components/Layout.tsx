import { Outlet } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Zap } from "lucide-react";
import { Sidebar } from "./Sidebar";
import { MobileNav } from "./MobileNav";
import { endpoints } from "@/lib/api";

export function Layout() {
  const me = useQuery({ queryKey: ["me"], queryFn: endpoints.me, staleTime: Infinity });

  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <main className="min-w-0 flex-1 pb-24 lg:pb-10">
        <header className="glass sticky top-0 z-30 border-b border-border/70">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3 sm:px-6">
            <div className="flex items-center gap-2 lg:hidden">
              <div className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-accent to-secondary text-white shadow-cta">
                <Zap className="h-4 w-4" />
              </div>
              <span className="text-sm font-bold tracking-tight">ELMA</span>
            </div>
            <div className="hidden text-sm text-fg-subtle lg:block">Консоль управления</div>
            <div className="flex items-center gap-2 text-sm">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-75" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-success" />
              </span>
              <span className="font-medium text-fg-muted">
                {me.data?.username ? "@" + me.data.username : "admin"}
              </span>
            </div>
          </div>
        </header>
        <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6">
          <Outlet />
        </div>
      </main>
      <MobileNav />
    </div>
  );
}
