"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Bell } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { get, post } from "@/lib/api";
import { useToday } from "@/lib/hooks";
import { fmtDateTime, humanize } from "@/lib/labels";
import type { Notification } from "@/lib/types";

function hrefFor(n: Notification): string | null {
  const p = n.payload;
  if (typeof p.story_id === "string") return `/stories/${p.story_id}`;
  if (typeof p.draft_id === "string") return `/studio/drafts/${p.draft_id}`;
  if (typeof p.idea_id === "string") return `/lab/${p.idea_id}`;
  if (typeof p.brief_id === "string" || n.kind.includes("brief")) return "/brief";
  if (n.kind.includes("review")) return "/reviews";
  return null;
}

export function NotificationBell({ className }: { className?: string }) {
  const today = useToday();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const list = useQuery({ queryKey: ["notifications"], queryFn: () => get<Notification[]>("/notifications?limit=20"), enabled: open });
  const readAll = useMutation({
    mutationFn: () => post("/notifications/read-all"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notifications"] });
      qc.invalidateQueries({ queryKey: ["today"] });
    },
  });
  const unread = today.data?.unread_notifications ?? 0;
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return (
    <div ref={ref} className={clsx("relative", className)}>
      <button
        type="button"
        aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="relative rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-text"
      >
        <Bell size={18} aria-hidden />
        {unread > 0 && (
          <span data-testid="unread-count" className="absolute -right-0.5 -top-0.5 min-w-4 rounded-full bg-accent px-1 text-center text-[10px] font-semibold leading-4 text-accent-contrast">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 z-50 mt-1 w-80 max-w-[calc(100vw-2rem)] rounded-lg border border-border bg-surface p-3 shadow-xl md:left-0 md:right-auto">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold">Notifications</h2>
            {unread > 0 && (
              <button type="button" className="text-xs underline" onClick={() => readAll.mutate()}>
                Mark all read
              </button>
            )}
          </div>
          {!list.data ? (
            <p className="text-sm text-muted">Loading…</p>
          ) : list.data.length === 0 ? (
            <p className="text-sm text-muted">Nothing yet.</p>
          ) : (
            <ul className="max-h-80 space-y-2 overflow-y-auto text-sm">
              {list.data.map((n) => {
                const title = typeof n.payload.title === "string" ? n.payload.title : humanize(n.kind);
                const href = hrefFor(n);
                return (
                  <li key={n.id} className={clsx("min-w-0 break-words", n.read && "text-muted")}>
                    {!n.read && <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-accent align-middle" aria-label="unread" />}
                    {href ? (
                      <Link href={href} onClick={() => setOpen(false)} className="hover:underline">
                        {title}
                      </Link>
                    ) : (
                      title
                    )}
                    <span className="block text-xs text-muted">{fmtDateTime(n.created_at)}</span>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
