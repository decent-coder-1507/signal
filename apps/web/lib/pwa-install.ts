// PWA install prompt (ADR-027). Chrome/Edge fire `beforeinstallprompt` once, often before the Today page mounts, so
// it is captured at module load (this module is imported by the app shell) and kept until the card uses it.

import { useSyncExternalStore } from "react";

type InstallEvent = Event & { prompt: () => Promise<void>; userChoice?: Promise<{ outcome: "accepted" | "dismissed" }> };

const DISMISS_KEY = "signal.install-card.dismissed";
let deferred: InstallEvent | null = null;
let installed = false;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

if (typeof window !== "undefined") {
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault(); // we show our own small card instead of the mini-infobar
    deferred = e as InstallEvent;
    emit();
  });
  window.addEventListener("appinstalled", () => {
    installed = true;
    deferred = null;
    emit();
  });
}

function standalone(): boolean {
  if (typeof window === "undefined") return false;
  const nav = navigator as Navigator & { standalone?: boolean };
  return window.matchMedia?.("(display-mode: standalone)").matches || nav.standalone === true;
}

function dismissed(): boolean {
  try {
    return localStorage.getItem(DISMISS_KEY) === "1";
  } catch {
    return false;
  }
}

/** "available" = the browser offered installation and the user hasn't installed or dismissed it. */
function snapshot(): "available" | "hidden" {
  return deferred && !installed && !standalone() && !dismissed() ? "available" : "hidden";
}

export function useInstallPrompt() {
  const state = useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    snapshot,
    () => "hidden" as const,
  );
  return {
    available: state === "available",
    async install() {
      const e = deferred;
      if (!e) return;
      await e.prompt();
      const choice = await e.userChoice?.catch(() => undefined);
      deferred = null;
      if (choice?.outcome === "accepted") installed = true;
      emit();
    },
    dismiss() {
      try {
        localStorage.setItem(DISMISS_KEY, "1");
      } catch {
        /* storage blocked: hidden for this page view */
      }
      deferred = null;
      emit();
    },
  };
}
