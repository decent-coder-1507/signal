"use client";

import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { ApiError, get, post } from "@/lib/api";
import {
  Activity,
  CalendarCheck,
  ChartLine,
  CircleDot,
  Dumbbell,
  Ellipsis,
  FlaskConical,
  LibraryBig,
  LogOut,
  Newspaper,
  PenLine,
  Radar,
  Search,
  Settings,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { NotificationBell } from "./notification-bell";
import { openSearch, SearchPalette } from "./search-palette";
import { ThemeCycleButton, ThemeToggle } from "./theme-toggle";

export type Me = {
  id: string;
  email: string;
  timezone: string;
  onboarded: boolean;
  totp_enabled: boolean;
  has_api_token?: boolean;
};

const NAV: { href: string; label: string; icon: LucideIcon }[] = [
  { href: "/", label: "Today", icon: CircleDot },
  { href: "/brief", label: "Brief", icon: Newspaper },
  { href: "/studio", label: "Studio", icon: PenLine },
  { href: "/lab", label: "Lab", icon: FlaskConical },
  { href: "/gym", label: "Gym", icon: Dumbbell },
  { href: "/moat", label: "Moat Radar", icon: Radar },
  { href: "/ask", label: "Ask", icon: Sparkles },
  { href: "/library", label: "Library", icon: LibraryBig },
  { href: "/reviews", label: "Reviews", icon: CalendarCheck },
  { href: "/analytics", label: "Analytics", icon: ChartLine },
  { href: "/settings", label: "Settings", icon: Settings },
  { href: "/ops", label: "Ops", icon: Activity },
];

const MOBILE = ["/", "/brief", "/studio", "/gym", "/ask"];

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => get<Me>("/me") });
}

function Logo({ size = 22 }: { size?: number }) {
  return <span className="glow shrink-0 rounded-[7px] bg-primary" style={{ width: size, height: size }} aria-hidden />;
}

export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const me = useMe();

  useEffect(() => {
    if (me.error instanceof ApiError && me.error.status === 401) router.replace("/login");
  }, [me.error, router]);

  if (me.isLoading || (me.error instanceof ApiError && me.error.status === 401)) {
    return <div className="p-6 text-sm text-muted">Loading…</div>;
  }

  const active = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));

  return (
    <div className="flex min-h-dvh">
      <nav
        aria-label="Main"
        className="sticky top-0 hidden h-dvh w-[220px] shrink-0 flex-col gap-0.5 overflow-y-auto border-r border-[var(--sidebar-border)] bg-sidebar px-3 py-5 md:flex"
      >
        <div className="mb-5 flex items-center justify-between pl-2">
          <Link href="/" className="flex items-center gap-2 text-[17px] font-bold tracking-tight">
            <Logo />
            Signal
          </Link>
          <span className="flex items-center">
            <button
              type="button"
              aria-label="Search (Ctrl+K)"
              title="Search (Ctrl+K)"
              onClick={openSearch}
              className="rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-text"
            >
              <Search size={17} aria-hidden />
            </button>
            <NotificationBell />
          </span>
        </div>
        {NAV.map((n) => {
          const on = active(n.href);
          return (
            <Link
              key={n.href}
              href={n.href}
              aria-current={on ? "page" : undefined}
              className={clsx(
                "flex items-center gap-2.5 rounded-[10px] px-3 py-2 text-sm transition-colors",
                on
                  ? "bg-[var(--nav-active-bg)] font-semibold text-text shadow-[var(--nav-active-shadow)]"
                  : "text-[var(--nav-text)] hover:bg-surface-2 hover:text-text",
              )}
            >
              <n.icon size={16} aria-hidden className={on ? "text-accent" : undefined} />
              {n.label}
            </Link>
          );
        })}
        <div className="mt-auto space-y-3 pt-5">
          <button
            type="button"
            onClick={openSearch}
            className="flex w-full items-center gap-1.5 px-3 text-left text-xs text-muted hover:text-text"
          >
            <kbd>Ctrl K</kbd> to search
          </button>
          <ThemeToggle />
          <button
            type="button"
            className="flex w-full items-center gap-2.5 rounded-[10px] px-3 py-2 text-left text-sm text-[var(--nav-text)] hover:bg-surface-2 hover:text-text"
            onClick={async () => {
              await post("/auth/logout");
              router.replace("/login");
            }}
          >
            <LogOut size={16} aria-hidden />
            Sign out
          </button>
        </div>
      </nav>
      <main className="relative min-w-0 flex-1 px-4 pb-28 pt-16 md:px-8 md:pb-12 md:pt-8 lg:px-10">
        <div className="absolute inset-x-0 top-0 z-30 flex h-12 items-center justify-between border-b border-[var(--sidebar-border)] bg-sidebar px-4 md:hidden">
          <Link href="/" className="flex items-center gap-2 text-[15px] font-bold tracking-tight">
            <Logo size={18} />
            Signal
          </Link>
          <span className="flex items-center">
            <ThemeCycleButton />
            <button type="button" aria-label="Search" onClick={openSearch} className="rounded-md p-1.5 text-muted hover:bg-surface-2">
              <Search size={18} aria-hidden />
            </button>
            <NotificationBell />
          </span>
        </div>
        <div className="mx-auto max-w-[84rem]">{children}</div>
      </main>
      <SearchPalette />
      <nav
        aria-label="Mobile"
        className="fixed inset-x-0 bottom-0 z-20 flex justify-around border-t border-[var(--sidebar-border)] bg-sidebar px-1 pb-[max(0.375rem,env(safe-area-inset-bottom))] pt-1.5 md:hidden"
      >
        {MOBILE.map((h) => {
          const n = NAV.find((x) => x.href === h)!;
          const on = active(h);
          return (
            <Link
              key={h}
              href={h}
              aria-current={on ? "page" : undefined}
              className={clsx(
                "flex min-w-12 flex-col items-center gap-0.5 rounded-[10px] px-2 py-1 text-[11px] font-medium",
                on ? "text-accent" : "text-muted",
              )}
            >
              <n.icon size={19} aria-hidden />
              {n.label}
            </Link>
          );
        })}
        <Link
          href="/settings"
          className="flex min-w-12 flex-col items-center gap-0.5 rounded-[10px] px-2 py-1 text-[11px] font-medium text-muted"
        >
          <Ellipsis size={19} aria-hidden />
          More
        </Link>
      </nav>
    </div>
  );
}

export function PageTitle({
  children,
  sub,
  eyebrow,
  aside,
}: {
  children: ReactNode;
  sub?: ReactNode;
  eyebrow?: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        {eyebrow && <p className="label mb-1">{eyebrow}</p>}
        <h1 className="text-[26px] font-bold leading-tight tracking-[-0.025em]">{children}</h1>
        {sub && <p className="mt-1 text-sm text-muted">{sub}</p>}
      </div>
      {aside && <div className="flex flex-wrap items-center gap-2">{aside}</div>}
    </header>
  );
}
