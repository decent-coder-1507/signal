import clsx from "clsx";
import type { ReactNode } from "react";

export const inputClass =
  "mt-1 block w-full min-w-0 rounded-md border border-border bg-surface px-3 py-2 text-sm text-text placeholder:text-muted";

export function Field({
  label,
  hint,
  children,
  className,
}: {
  label: ReactNode;
  hint?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={clsx("block text-sm", className)}>
      <span className="font-medium">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}
