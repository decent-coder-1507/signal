"use client";

import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { ApiError, get, post } from "@/lib/api";

export type Me = { id: string; email: string; timezone: string; onboarded: boolean; totp_enabled: boolean };

const NAV: { href: string; label: string }[] = [
  { href: "/", label: "Today" },
  { href: "/brief", label: "Brief" },
  { href: "/studio", label: "Studio" },
  { href: "/lab", label: "Lab" },
  { href: "/gym", label: "Gym" },
  { href: "/moat", label: "Moat Radar" },
  { href: "/ask", label: "Ask" },
  { href: "/library", label: "Library" },
  { href: "/reviews", label: "Reviews" },
  { href: "/analytics", label: "Analytics" },
  { href: "/settings", label: "Settings" },
  { href: "/ops", label: "Ops" },
];

const MOBILE = ["/", "/brief", "/studio", "/gym", "/ask"];

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => get<Me>("/me") });
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
    <div className="mx-auto flex min-h-dvh max-w-6xl">
      <nav aria-label="Main" className="sticky top-0 hidden h-dvh w-52 shrink-0 flex-col gap-0.5 border-r border-border px-3 py-5 md:flex">
        <Link href="/" className="mb-5 px-2 font-serif text-xl font-semibold tracking-tight">
          SIGNAL
        </Link>
        {NAV.map((n) => (
          <Link
            key={n.href}
            href={n.href}
            className={clsx(
              "rounded-md px-2 py-1.5 text-sm",
              active(n.href) ? "bg-surface-2 font-medium text-text" : "text-muted hover:text-text",
            )}
          >
            {n.label}
          </Link>
        ))}
        <button
          className="mt-auto px-2 py-1.5 text-left text-sm text-muted hover:text-text"
          onClick={async () => {
            await post("/auth/logout");
            router.replace("/login");
          }}
        >
          Sign out
        </button>
      </nav>
      <main className="min-w-0 flex-1 px-4 pb-24 pt-5 md:px-8 md:pb-10">{children}</main>
      <nav
        aria-label="Mobile"
        className="fixed inset-x-0 bottom-0 z-20 flex justify-around border-t border-border bg-surface/95 px-2 py-2 backdrop-blur md:hidden"
      >
        {MOBILE.map((h) => {
          const n = NAV.find((x) => x.href === h)!;
          return (
            <Link
              key={h}
              href={h}
              className={clsx("min-w-12 rounded-md px-2 py-2 text-center text-xs", active(h) ? "text-accent" : "text-muted")}
            >
              {n.label}
            </Link>
          );
        })}
        <Link href="/settings" className="min-w-12 px-2 py-2 text-center text-xs text-muted">
          More
        </Link>
      </nav>
    </div>
  );
}

export function PageTitle({ children, sub }: { children: ReactNode; sub?: ReactNode }) {
  return (
    <header className="mb-5">
      <h1 className="font-serif text-2xl font-semibold tracking-tight">{children}</h1>
      {sub && <p className="mt-0.5 text-sm text-muted">{sub}</p>}
    </header>
  );
}
