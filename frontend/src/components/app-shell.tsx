"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Activity, Bell, BrainCircuit, ClipboardList, LineChart, LogOut, Moon, ShieldCheck, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useApi } from "@/lib/api";
import type { Me } from "@/lib/types";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Executive dashboard", icon: Activity },
  { href: "/alerts", label: "Alerts", icon: Bell },
  { href: "/forecasts", label: "Forecasts", icon: LineChart },
  { href: "/copilot", label: "Epi copilot", icon: BrainCircuit },
  { href: "/models", label: "Model performance", icon: ShieldCheck },
  { href: "/audit", label: "Audit log", icon: ClipboardList, roles: ["admin"] },
];

const ROLE_LABEL: Record<string, string> = {
  admin: "Administrator",
  epidemiologist: "Epidemiologist",
  cdc_analyst: "CDC analyst",
  state_health_officer: "State health officer",
  healthcare_partner: "Healthcare partner",
  viewer: "Viewer",
};

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { data: me } = useApi<Me>("auth/me");
  const [dark, setDark] = useState(false);

  useEffect(() => {
    let stored: string | null = null;
    try {
      stored = localStorage.getItem("sh-theme");
    } catch {}
    const isDark = stored ? stored === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
    setDark(isDark);
  }, []);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);

  const toggleTheme = () => {
    setDark((d) => {
      try {
        localStorage.setItem("sh-theme", d ? "light" : "dark");
      } catch {}
      return !d;
    });
  };

  async function logout() {
    await fetch("/bff/logout", { method: "POST" });
    router.push("/login");
  }

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r bg-card md:flex">
        <div className="flex items-center gap-2 px-5 py-5">
          <div className="grid size-8 place-items-center rounded-md bg-primary text-primary-foreground">
            <Activity className="size-4" />
          </div>
          <div>
            <div className="text-sm font-semibold leading-tight">SentinelHealth AI</div>
            <div className="text-[11px] text-muted-foreground">Outbreak intelligence</div>
          </div>
        </div>
        <nav className="flex-1 space-y-0.5 px-3">
          {NAV.filter((n) => !n.roles || (me && n.roles.includes(me.role))).map(({ href, label, icon: Icon }) => {
            const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <Link key={href} href={href}
                className={cn("flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
                  active ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground")}>
                <Icon className="size-4" />
                {label}
              </Link>
            );
          })}
        </nav>
        <div className="border-t p-4 text-xs">
          {me && (
            <div className="mb-3">
              <div className="truncate font-medium">{me.full_name}</div>
              <div className="text-muted-foreground">{ROLE_LABEL[me.role] ?? me.role}{me.jurisdiction ? ` · ${me.jurisdiction}` : " · National"}</div>
            </div>
          )}
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={toggleTheme} aria-label="Toggle theme">
              {dark ? <Sun /> : <Moon />}
            </Button>
            <Button variant="outline" size="sm" onClick={logout} className="flex-1">
              <LogOut /> Sign out
            </Button>
          </div>
        </div>
      </aside>
      <main className="min-w-0 flex-1">
        <div className="mx-auto max-w-[1400px] px-4 py-6 md:px-8">{children}</div>
      </main>
    </div>
  );
}

export function PageHeader({ title, description, children }: { title: string; description?: string; children?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}
