"use client";

import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { KeyRound, X } from "lucide-react";
import Link from "next/link";
import { useSyncExternalStore } from "react";
import { get } from "@/lib/api";
import { useLatestBrief } from "@/lib/hooks";

type Health = { status: string; mode: "mock" | "live" };

export function useHealth() {
  return useQuery({ queryKey: ["health"], queryFn: () => get<Health>("/health"), staleTime: 60_000 });
}

/**
 * Trust badge for the shell: a prominent "Demo data" chip in mock mode (fixtures, not real news), a subtle "Live" dot
 * otherwise, plus "Degraded" when the latest brief was assembled without some of its analysis.
 */
export function ModeBadge({ compact = false }: { compact?: boolean }) {
  const health = useHealth();
  const brief = useLatestBrief();
  const mode = health.data?.mode;
  if (!mode) return null;
  const degraded = !!brief.data?.degraded;
  return (
    <span className="flex min-w-0 flex-wrap items-center gap-1.5">
      {mode === "mock" ? (
        <span
          data-testid="mode-badge"
          data-mode="mock"
          title="Mock mode: offline fixtures and recorded AI outputs, not real news."
          className="inline-flex items-center rounded-full border border-warn/50 bg-warn/15 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-warn"
        >
          Demo data
        </span>
      ) : (
        <span data-testid="mode-badge" data-mode="live" title="Live mode: real sources and the Claude Runner." className="inline-flex items-center gap-1 text-[11px] text-muted">
          <span className="h-1.5 w-1.5 rounded-full bg-good" aria-hidden />
          {!compact && "Live"}
          {compact && <span className="sr-only">Live</span>}
        </span>
      )}
      {degraded && (
        <Link
          href="/brief"
          data-testid="degraded-badge"
          title="The latest brief was assembled with some analysis unavailable."
          className={clsx("inline-flex items-center rounded-full border border-bad/40 bg-bad/10 px-2 py-0.5 text-[11px] font-medium text-bad")}
        >
          Degraded
        </Link>
      )}
    </span>
  );
}

const DISMISS_KEY = "signal.default-password-banner.dismissed";
const DISMISS_EVENT = "signal-banner-dismiss";

function readDismissed(): boolean {
  try {
    return sessionStorage.getItem(DISMISS_KEY) === "1";
  } catch {
    return false;
  }
}

function subscribeDismissed(cb: () => void) {
  window.addEventListener(DISMISS_EVENT, cb);
  return () => window.removeEventListener(DISMISS_EVENT, cb);
}

/** Dismissible warning while the admin password is still the seeded placeholder (`/me.default_password`). */
export function DefaultPasswordBanner({ show }: { show: boolean }) {
  const dismissed = useSyncExternalStore(subscribeDismissed, readDismissed, () => true);
  if (!show || dismissed) return null;
  return (
    <div role="alert" data-testid="default-password-banner" className="mb-5 flex items-start gap-3 rounded-xl border border-warn/40 bg-warn/10 px-4 py-3 text-sm">
      <KeyRound size={16} className="mt-0.5 shrink-0 text-warn" aria-hidden />
      <p className="min-w-0 flex-1">
        You&apos;re still using the default password.{" "}
        <Link href="/settings?tab=security" className="font-medium underline underline-offset-2">
          Change it in Settings → Security
        </Link>
        .
      </p>
      <button
        type="button"
        aria-label="Dismiss"
        className="rounded-md p-0.5 text-muted hover:text-text"
        onClick={() => {
          try {
            sessionStorage.setItem(DISMISS_KEY, "1");
          } catch {
            /* storage blocked: the banner comes back on the next render */
          }
          window.dispatchEvent(new Event(DISMISS_EVENT));
        }}
      >
        <X size={14} aria-hidden />
      </button>
    </div>
  );
}
