import clsx from "clsx";
import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

export function buttonClass(variant: Variant = "secondary", size: Size = "md", extra?: string) {
  return clsx(
    "inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
    size === "sm" ? "min-h-8 px-2.5 py-1 text-xs" : "min-h-10 px-3.5 py-2 text-sm",
    variant === "primary" && "bg-accent text-accent-contrast hover:opacity-90",
    variant === "secondary" && "border border-border bg-surface text-text hover:bg-surface-2",
    variant === "ghost" && "text-muted hover:bg-surface-2 hover:text-text",
    variant === "danger" && "border border-border bg-surface text-bad hover:bg-surface-2",
    extra,
  );
}

export function Button({
  variant,
  size,
  className,
  type = "button",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size }) {
  return <button type={type} className={buttonClass(variant, size, className)} {...rest} />;
}
