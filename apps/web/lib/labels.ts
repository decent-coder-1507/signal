export const HYPE: Record<string, string> = {
  substance: "Substance",
  mixed: "Mixed",
  mostly_hype: "Mostly hype",
  too_early: "Too early",
};

export const DURABILITY: Record<string, string> = {
  fundamental: "Fundamental",
  trend: "Trend",
  churn: "Churn",
};

export const RING: Record<string, string> = { core: "Core", adjacent: "Adjacent", wide: "Wide" };

export const BRIEF_KIND: Record<string, string> = {
  daily: "Daily brief",
  weekend: "Weekend brief",
  catchup: "While you were away",
  custom: "Custom brief",
};

export function hypeTone(v: string | null | undefined): "good" | "warn" | "bad" | "muted" {
  if (v === "substance") return "good";
  if (v === "mixed") return "warn";
  if (v === "mostly_hype") return "bad";
  return "muted";
}

const TZ = "Asia/Kolkata";

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short", timeZone: TZ }).format(
    new Date(iso),
  );
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeZone: TZ }).format(new Date(iso));
}

export function humanize(s: string): string {
  return s.replace(/[_.]/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}
