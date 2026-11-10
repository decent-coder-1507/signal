// Local browser notifications (ADR-027): no push service, no VAPID. While a SIGNAL tab or the installed PWA is open,
// the shell polls the in-app notifications endpoint and shows new ones through the service worker (or the
// Notification API as a fallback). Opt-in is per device and lives in localStorage.

import type { Notification as AppNotification } from "./types";

const ENABLED_KEY = "signal.browser-notify";
const SINCE_KEY = "signal.browser-notify.since";

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* storage blocked: the toggle just won't persist */
  }
}

export function notifySupported(): boolean {
  return typeof window !== "undefined" && "Notification" in window;
}

export function notifyPermission(): NotificationPermission | "unsupported" {
  return notifySupported() ? Notification.permission : "unsupported";
}

export function notifyEnabled(): boolean {
  return notifySupported() && read(ENABLED_KEY) === "on" && Notification.permission === "granted";
}

/** Ask for permission (must run from a click) and remember the opt-in. Returns whether it is now on. */
export async function enableNotify(now: Date = new Date()): Promise<boolean> {
  if (!notifySupported()) return false;
  const perm = Notification.permission === "granted" ? "granted" : await Notification.requestPermission();
  if (perm !== "granted") return false;
  write(ENABLED_KEY, "on");
  write(SINCE_KEY, now.toISOString()); // only notify about what arrives from now on
  return true;
}

export function disableNotify() {
  write(ENABLED_KEY, null);
}

/** The kinds worth interrupting for: a new brief or review, a watch firing, cards due, a scheduled post nudge. */
const NOTIFY_KINDS = new Set(["brief", "weekly", "monthly", "watch", "cards", "publish_assist", "alert"]);

export function notificationHref(n: AppNotification): string {
  const p = n.payload;
  if (typeof p.story_id === "string") return `/stories/${p.story_id}`;
  if (typeof p.draft_id === "string") return `/studio/drafts/${p.draft_id}`;
  if (n.kind === "weekly" || n.kind === "monthly") return "/reviews";
  if (n.kind === "cards") return "/gym";
  if (typeof p.brief_id === "string" || n.kind.includes("brief")) return "/brief";
  return "/";
}

const str = (v: unknown): string | undefined => (typeof v === "string" && v ? v : undefined);

export function notificationTitle(n: AppNotification): string {
  const p = n.payload;
  if (n.kind === "watch") return str(p.watch) ? `Watch fired: ${p.watch}` : "A watch fired";
  if (n.kind === "alert") return str(p.text) ?? "SIGNAL alert";
  return str(p.title) ?? (n.kind === "cards" ? "Cards are due" : "SIGNAL");
}

export function notificationBody(n: AppNotification): string | undefined {
  return n.kind === "watch" ? str(n.payload.title) : undefined;
}

/** Pure: which notifications are new since `since` and worth showing (oldest first). */
export function freshNotifications(list: AppNotification[], since: string | null): AppNotification[] {
  const t = since ? Date.parse(since) : Number.POSITIVE_INFINITY;
  return list
    .filter((n) => !n.read && NOTIFY_KINDS.has(n.kind) && Date.parse(n.created_at) > t)
    .sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at));
}

export function notifySince(): string | null {
  return read(SINCE_KEY);
}

export function setNotifySince(iso: string) {
  write(SINCE_KEY, iso);
}

export async function showBrowserNotification(n: AppNotification) {
  const title = notificationTitle(n);
  const options: NotificationOptions = {
    body: notificationBody(n),
    tag: `signal-${n.id}`,
    icon: "/icon-192.png",
    badge: "/icon-192.png",
    data: { url: notificationHref(n) },
  };
  const reg = "serviceWorker" in navigator ? await navigator.serviceWorker.getRegistration() : undefined;
  if (reg) {
    await reg.showNotification(title, options);
    return;
  }
  const shown = new Notification(title, options);
  shown.onclick = () => {
    window.focus();
    window.location.assign(notificationHref(n));
  };
}
