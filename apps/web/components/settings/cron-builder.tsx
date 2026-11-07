"use client";

import { DAY_NAMES, describeCron, fmtTime, looksLikeCron, parseTime, toCron, type CronPreset } from "@/lib/cron";
import { inputClass } from "@/components/ui/field";

type Kind = CronPreset["kind"];

const KINDS: { id: Kind; label: string }[] = [
  { id: "weekdays", label: "Weekdays at…" },
  { id: "daily", label: "Every day at…" },
  { id: "weekly", label: "Every week on…" },
  { id: "monthly", label: "Monthly on day…" },
  { id: "raw", label: "Custom cron" },
];

function timeOf(p: CronPreset) {
  return p.kind === "raw" ? { hour: 9, minute: 0 } : { hour: p.hour, minute: p.minute };
}

/** Controlled cron builder: presets ↔ 5-field cron (lib/cron), with a raw escape hatch. */
export function CronBuilder({ value, onChange }: { value: CronPreset; onChange: (p: CronPreset) => void }) {
  const t = timeOf(value);
  const cron = toCron(value);
  const switchKind = (k: Kind) => {
    if (k === "raw") onChange({ kind: "raw", cron });
    else if (k === "weekly") onChange({ kind: "weekly", dow: 0, ...t });
    else if (k === "monthly") onChange({ kind: "monthly", day: 1, ...t });
    else onChange({ kind: k, ...t });
  };
  const setTime = (s: string) => {
    const pt = parseTime(s);
    if (pt && value.kind !== "raw") onChange({ ...value, ...pt });
  };
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-sm">
          Schedule
          <select className={inputClass} value={value.kind} onChange={(e) => switchKind(e.target.value as Kind)}>
            {KINDS.map((k) => (
              <option key={k.id} value={k.id}>
                {k.label}
              </option>
            ))}
          </select>
        </label>
        {value.kind === "weekly" && (
          <label className="text-sm">
            Day
            <select
              className={inputClass}
              value={value.dow}
              onChange={(e) => onChange({ ...value, dow: Number(e.target.value) })}
            >
              {DAY_NAMES.map((d, i) => (
                <option key={d} value={i}>
                  {d}
                </option>
              ))}
            </select>
          </label>
        )}
        {value.kind === "monthly" && (
          <label className="text-sm">
            Day of month
            <input
              type="number"
              min={1}
              max={28}
              className={inputClass + " w-24"}
              value={value.day}
              onChange={(e) => onChange({ ...value, day: Math.max(1, Math.min(28, Number(e.target.value) || 1)) })}
            />
          </label>
        )}
        {value.kind !== "raw" ? (
          <label className="text-sm">
            Time
            <input type="time" className={inputClass} value={fmtTime(t.hour, t.minute)} onChange={(e) => setTime(e.target.value)} />
          </label>
        ) : (
          <label className="min-w-0 flex-1 text-sm">
            Cron expression
            <input
              className={inputClass + " font-mono"}
              value={value.cron}
              placeholder="m h dom mon dow"
              onChange={(e) => onChange({ kind: "raw", cron: e.target.value })}
            />
          </label>
        )}
      </div>
      <p className="text-xs text-muted">
        {looksLikeCron(cron) ? describeCron(cron) : "Enter five fields: minute hour day-of-month month day-of-week"}{" "}
        · <code className="font-mono">{cron || "—"}</code>
      </p>
    </div>
  );
}
