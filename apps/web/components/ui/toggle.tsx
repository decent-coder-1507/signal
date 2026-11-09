"use client";

import clsx from "clsx";

export function Toggle({
  checked,
  onChange,
  label,
  disabled,
  showLabel = false,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  disabled?: boolean;
  showLabel?: boolean;
}) {
  return (
    <span className={clsx("inline-flex items-center gap-2 text-sm", disabled && "opacity-50")}>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={clsx(
          "relative h-6 w-10 shrink-0 rounded-full border transition-colors disabled:cursor-not-allowed",
          checked ? "border-signal bg-signal" : "border-border-strong bg-surface-2",
        )}
      >
        <span
          className={clsx(
            "absolute top-[3px] h-4 w-4 rounded-full shadow transition-all",
            checked ? "left-[19px] bg-[var(--accent-contrast)]" : "left-[3px] bg-white",
          )}
        />
      </button>
      {showLabel && <span>{label}</span>}
    </span>
  );
}
