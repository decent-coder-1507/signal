// Human-readable cron builder (§14 Settings → routines). Presets map to 5-field cron and back;
// anything we cannot represent falls back to "raw".

export type CronPreset =
  | { kind: "weekdays"; hour: number; minute: number }
  | { kind: "daily"; hour: number; minute: number }
  | { kind: "weekly"; dow: number; hour: number; minute: number } // 0 = Sunday
  | { kind: "monthly"; day: number; hour: number; minute: number }
  | { kind: "raw"; cron: string };

export const DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

const pad = (n: number) => String(n).padStart(2, "0");
export const fmtTime = (h: number, m: number) => `${pad(h)}:${pad(m)}`;

export function parseTime(hhmm: string): { hour: number; minute: number } | null {
  const m = /^(\d{1,2}):(\d{2})$/.exec(hhmm.trim());
  if (!m) return null;
  const hour = Number(m[1]);
  const minute = Number(m[2]);
  if (hour > 23 || minute > 59) return null;
  return { hour, minute };
}

export function toCron(p: CronPreset): string {
  switch (p.kind) {
    case "weekdays":
      return `${p.minute} ${p.hour} * * 1-5`;
    case "daily":
      return `${p.minute} ${p.hour} * * *`;
    case "weekly":
      return `${p.minute} ${p.hour} * * ${p.dow}`;
    case "monthly":
      return `${p.minute} ${p.hour} ${p.day} * *`;
    case "raw":
      return p.cron.trim().replace(/\s+/g, " ");
  }
}

const INT = /^\d+$/;

export function fromCron(cron: string): CronPreset {
  const raw: CronPreset = { kind: "raw", cron: cron.trim() };
  const f = cron.trim().split(/\s+/);
  if (f.length !== 5) return raw;
  const [mi, h, dom, mon, dow] = f;
  if (!INT.test(mi) || !INT.test(h) || mon !== "*") return raw;
  const minute = Number(mi);
  const hour = Number(h);
  if (minute > 59 || hour > 23) return raw;
  if (dom === "*" && dow === "1-5") return { kind: "weekdays", hour, minute };
  if (dom === "*" && dow === "*") return { kind: "daily", hour, minute };
  if (dom === "*" && INT.test(dow) && Number(dow) <= 7) return { kind: "weekly", dow: Number(dow) % 7, hour, minute };
  if (INT.test(dom) && dow === "*" && Number(dom) >= 1 && Number(dom) <= 31)
    return { kind: "monthly", day: Number(dom), hour, minute };
  return raw;
}

const ordinal = (n: number) => {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
};

export function describeCron(cron: string): string {
  const p = fromCron(cron);
  switch (p.kind) {
    case "weekdays":
      return `Weekdays at ${fmtTime(p.hour, p.minute)}`;
    case "daily":
      return `Every day at ${fmtTime(p.hour, p.minute)}`;
    case "weekly":
      return `Every ${DAY_NAMES[p.dow]} at ${fmtTime(p.hour, p.minute)}`;
    case "monthly":
      return `${ordinal(p.day)} of every month at ${fmtTime(p.hour, p.minute)}`;
    case "raw":
      return `Custom: ${p.cron}`;
  }
}

/** Loose client-side check (the API validates with croniter). */
export function looksLikeCron(cron: string): boolean {
  const f = cron.trim().split(/\s+/);
  return f.length === 5 && f.every((x) => /^[\d*,/\-A-Za-z]+$/.test(x));
}
