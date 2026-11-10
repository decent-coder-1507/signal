"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, Download, X } from "lucide-react";
import { useEffect, useSyncExternalStore } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { Toggle } from "@/components/ui/toggle";
import { get } from "@/lib/api";
import {
  disableNotify,
  enableNotify,
  freshNotifications,
  notifyEnabled,
  notifyPermission,
  notifySince,
  setNotifySince,
  showBrowserNotification,
} from "@/lib/browser-notify";
import { useInstallPrompt } from "@/lib/pwa-install";
import type { Notification } from "@/lib/types";

const CHANGE_EVENT = "signal-notify-change";
const POLL_MS = 60_000;

function subscribeNotify(cb: () => void) {
  window.addEventListener(CHANGE_EVENT, cb);
  return () => window.removeEventListener(CHANGE_EVENT, cb);
}

function useNotifyOn() {
  return useSyncExternalStore(subscribeNotify, notifyEnabled, () => false);
}

function usePermission() {
  return useSyncExternalStore(subscribeNotify, notifyPermission, () => "default" as const);
}

/**
 * Mounted once in the shell. When browser notifications are on, polls the in-app notifications endpoint while a tab
 * or the installed PWA is open and shows new briefs, watch hits and due cards as system notifications.
 */
export function BrowserNotifier() {
  const on = useNotifyOn();
  const qc = useQueryClient();
  const poll = useQuery({
    queryKey: ["notifications", "poll"],
    queryFn: () => get<Notification[]>("/notifications?limit=20"),
    enabled: on,
    refetchInterval: POLL_MS,
    refetchIntervalInBackground: true,
    staleTime: 0,
  });
  useEffect(() => {
    if (!on || !poll.data) return;
    const fresh = freshNotifications(poll.data, notifySince());
    if (!fresh.length) return;
    setNotifySince(fresh[fresh.length - 1].created_at);
    qc.invalidateQueries({ queryKey: ["today"] });
    for (const n of fresh.slice(-3)) void showBrowserNotification(n).catch(() => undefined);
  }, [on, poll.data, qc]);
  return null;
}

/** Settings → Channels: per-device opt-in for browser notifications. */
export function BrowserNotifyToggle() {
  const toast = useToast();
  const on = useNotifyOn();
  const perm = usePermission();
  const unsupported = perm === "unsupported";
  const flip = async (want: boolean) => {
    if (want) {
      const ok = await enableNotify();
      toast(ok ? "Browser notifications on" : "Notifications were not allowed", ok ? "good" : "bad");
    } else disableNotify();
    window.dispatchEvent(new Event(CHANGE_EVENT));
  };
  return (
    <div className="flex items-start justify-between gap-3" data-testid="browser-notify">
      <span className="min-w-0 text-sm">
        <span className="flex items-center gap-1.5 font-medium">
          <BellRing size={14} aria-hidden /> Browser notifications
        </span>
        <span className="block text-xs text-muted">
          {unsupported
            ? "This browser can't show notifications."
            : perm === "denied"
              ? "Blocked in this browser's site settings — allow notifications for SIGNAL there first."
              : "New brief, watch hits and due cards, while a SIGNAL tab or the installed app is open. This device only."}
        </span>
      </span>
      <Toggle label="Enable browser notifications" checked={on} disabled={unsupported} onChange={(want) => void flip(want)} />
    </div>
  );
}

/** Today: a small "Install SIGNAL" card while the browser offers installation (hidden once installed/dismissed). */
export function InstallCard() {
  const p = useInstallPrompt();
  if (!p.available) return null;
  return (
    <Card data-testid="install-card" className="flex flex-wrap items-center gap-3">
      <Download size={18} className="shrink-0 text-accent" aria-hidden />
      <p className="min-w-0 flex-1 text-sm">
        <span className="font-semibold">Install SIGNAL</span>
        <span className="block text-muted">Open it like an app, share links straight into Capture, and get notifications.</span>
      </p>
      <div className="flex items-center gap-1">
        <Button size="sm" variant="primary" onClick={() => void p.install()}>
          Install
        </Button>
        <Button size="sm" variant="ghost" aria-label="Dismiss install card" onClick={p.dismiss}>
          <X size={14} aria-hidden />
        </Button>
      </div>
    </Card>
  );
}
