"use client";

import clsx from "clsx";
import { useRef, type ReactNode } from "react";

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  label,
}: {
  tabs: { id: T; label: string }[];
  value: T;
  onChange: (id: T) => void;
  label: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  function onKey(e: React.KeyboardEvent) {
    const i = tabs.findIndex((t) => t.id === value);
    let j: number;
    if (e.key === "ArrowRight") j = (i + 1) % tabs.length;
    else if (e.key === "ArrowLeft") j = (i - 1 + tabs.length) % tabs.length;
    else return;
    e.preventDefault();
    onChange(tabs[j].id);
    ref.current?.querySelectorAll<HTMLButtonElement>("[role=tab]")[j]?.focus();
  }
  return (
    <div
      ref={ref}
      role="tablist"
      aria-label={label}
      onKeyDown={onKey}
      className="mb-5 flex gap-1 overflow-x-auto border-b border-border"
    >
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          type="button"
          id={`tab-${t.id}`}
          aria-selected={t.id === value}
          aria-controls={`panel-${t.id}`}
          tabIndex={t.id === value ? 0 : -1}
          onClick={() => onChange(t.id)}
          className={clsx(
            "-mb-px shrink-0 whitespace-nowrap border-b-2 px-3 py-2 text-sm",
            t.id === value ? "border-accent font-medium text-text" : "border-transparent text-muted hover:text-text",
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function TabPanel({ id, children }: { id: string; children: ReactNode }) {
  return (
    <div role="tabpanel" id={`panel-${id}`} aria-labelledby={`tab-${id}`}>
      {children}
    </div>
  );
}
