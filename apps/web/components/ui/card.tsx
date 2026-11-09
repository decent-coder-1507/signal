import clsx from "clsx";
import type { HTMLAttributes, ReactNode } from "react";

/** Bento card: 18px radius, 1px border; white in light, graphite gradient in dark. `invert` = the signature dark/lime tile. */
export function Card({ className, invert, ...rest }: HTMLAttributes<HTMLElement> & { invert?: boolean }) {
  return <section className={clsx("min-w-0 p-5", invert ? "bento-invert" : "bento", className)} {...rest} />;
}

export function CardTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
      <h2 className="card-title">{children}</h2>
      {aside && <div className="font-mono text-[11px] text-muted">{aside}</div>}
    </div>
  );
}

/** Big mono metric numeral with a label (bento stat tile content). Use inside a <dl>. */
export function Metric({
  label,
  value,
  unit,
  className,
  valueClassName,
}: {
  label: ReactNode;
  value: ReactNode;
  unit?: ReactNode;
  className?: string;
  valueClassName?: string;
}) {
  return (
    <div className={clsx("min-w-0", className)}>
      <dt className="label">{label}</dt>
      <dd className={clsx("num mt-1.5 text-[28px] font-semibold leading-none", valueClassName)}>
        {value}
        {unit && <span className="ml-1 font-sans text-sm font-normal tracking-normal text-muted">{unit}</span>}
      </dd>
    </div>
  );
}
