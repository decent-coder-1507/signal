"use client";

import clsx from "clsx";
import { Monitor, Moon, Sun } from "lucide-react";
import { useEffect, useSyncExternalStore } from "react";
import { applyTheme, readThemePref, saveThemePref, type ThemePref } from "@/lib/theme";

const listeners = new Set<() => void>();
function subscribe(fn: () => void) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
function setPref(p: ThemePref) {
  saveThemePref(p);
  listeners.forEach((fn) => fn());
}

export function useThemePref(): [ThemePref, (p: ThemePref) => void] {
  const pref = useSyncExternalStore(subscribe, readThemePref, () => "system" as ThemePref);
  return [pref, setPref];
}

const OPTIONS: { id: ThemePref; label: string; Icon: typeof Sun }[] = [
  { id: "light", label: "Light", Icon: Sun },
  { id: "dark", label: "Dark", Icon: Moon },
  { id: "system", label: "System", Icon: Monitor },
];

/** Segmented Light / Dark / System control (sidebar footer). */
export function ThemeToggle({ className }: { className?: string }) {
  const [pref, set] = useThemePref();
  useEffect(() => applyTheme(readThemePref()), []);
  return (
    <div role="radiogroup" aria-label="Theme" className={clsx("flex rounded-[10px] border border-border bg-surface-2 p-0.5", className)}>
      {OPTIONS.map(({ id, label, Icon }) => (
        <button
          key={id}
          type="button"
          role="radio"
          aria-checked={pref === id}
          title={`${label} theme`}
          onClick={() => set(id)}
          className={clsx(
            "inline-flex min-h-7 flex-1 items-center justify-center gap-1 rounded-[8px] px-1.5 text-[11px] font-medium transition-colors",
            pref === id ? "bg-surface text-text shadow-sm" : "text-muted hover:text-text",
          )}
        >
          <Icon size={13} aria-hidden />
          {label}
        </button>
      ))}
    </div>
  );
}

/** Single button that cycles light → dark → system (compact mobile header). */
export function ThemeCycleButton() {
  const [pref, set] = useThemePref();
  useEffect(() => applyTheme(readThemePref()), []);
  const i = OPTIONS.findIndex((o) => o.id === pref);
  const cur = OPTIONS[i] ?? OPTIONS[2];
  const next = OPTIONS[(i + 1) % OPTIONS.length];
  return (
    <button
      type="button"
      aria-label={`Theme: ${cur.label}. Switch to ${next.label}`}
      title={`Theme: ${cur.label}`}
      onClick={() => set(next.id)}
      className="rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-text"
    >
      <cur.Icon size={18} aria-hidden />
    </button>
  );
}
