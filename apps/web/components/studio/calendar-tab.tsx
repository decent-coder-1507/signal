"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { get } from "@/lib/api";
import { describeCron } from "@/lib/cron";
import { safeUrl } from "@/lib/safe-url";
import { PLATFORM_LABEL, type CalendarData } from "@/lib/studio-types";

const LANES = ["linkedin", "x", "instagram", "hashnode"] as const;
const laneOf = (p: string) => (p.startsWith("x") ? "x" : p.startsWith("instagram") ? "instagram" : p.startsWith("linkedin") ? "linkedin" : p);

const TZ = "Asia/Kolkata";
const dayKey = (iso: string) => new Intl.DateTimeFormat("en-CA", { timeZone: TZ }).format(new Date(iso));
const addDays = (ymd: string, n: number) => {
  const d = new Date(`${ymd}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};
const dayLabel = (ymd: string) =>
  new Intl.DateTimeFormat("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }).format(new Date(`${ymd}T00:00:00Z`));
const timeLabel = (iso: string) => new Intl.DateTimeFormat("en-IN", { timeStyle: "short", timeZone: TZ }).format(new Date(iso));

export function CalendarTab() {
  const [start, setStart] = useState<string | null>(null); // null = this week (server decides)
  const q = useQuery({
    queryKey: ["studio", "calendar", start],
    queryFn: () => get<CalendarData>(`/calendar?days=7${start ? `&start=${start}` : ""}`),
  });
  const c = q.data;
  if (!c) return <p className="text-sm text-muted">Loading…</p>;
  const days = Array.from({ length: c.days }, (_, i) => addDays(c.start, i));
  type Entry = { id: string; platform: string; at: string; kind: "scheduled" | "published"; url?: string };
  const entries: Entry[] = [
    ...c.scheduled.map((x) => ({ ...x, kind: "scheduled" as const })),
    ...c.published.map((x) => ({ ...x, kind: "published" as const })),
  ];
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Button size="sm" variant="ghost" aria-label="Previous week" onClick={() => setStart(addDays(c.start, -7))}>
          <ChevronLeft size={16} aria-hidden />
        </Button>
        <span className="text-sm font-medium">
          {dayLabel(days[0])} – {dayLabel(days[days.length - 1])}
        </span>
        <Button size="sm" variant="ghost" aria-label="Next week" onClick={() => setStart(addDays(c.start, 7))}>
          <ChevronRight size={16} aria-hidden />
        </Button>
        {start && (
          <Button size="sm" variant="ghost" onClick={() => setStart(null)}>
            This week
          </Button>
        )}
      </div>

      <Card>
        <h2 className="card-title mb-2">Weekly goals</h2>
        <ul className="grid gap-3 sm:grid-cols-3">
          {Object.entries(c.goals).map(([p, g]) => (
            <li key={p}>
              <div className="flex justify-between text-sm">
                <span>{({ linkedin: "LinkedIn", x: "X", instagram: "Instagram", hashnode: "Hashnode" } as Record<string, string>)[p] ?? p}</span>
                <span className="tabular-nums text-muted">
                  {g.done} / {g.goal}
                </span>
              </div>
              <div className="mt-1 h-2 overflow-hidden rounded-full bg-surface-2" role="progressbar" aria-valuemin={0} aria-valuemax={g.goal} aria-valuenow={g.done} aria-label={`${p} goal`}>
                <div className="glow h-full rounded-full bg-signal" style={{ width: `${Math.min(100, (g.done / Math.max(1, g.goal)) * 100)}%` }} />
              </div>
            </li>
          ))}
        </ul>
      </Card>

      <div className="bento overflow-x-auto">
        <table className="w-full min-w-[760px] table-fixed text-xs">
          <thead className="bg-surface-2 text-muted">
            <tr>
              <th className="w-24 px-2 py-1.5 text-left font-medium">Platform</th>
              {days.map((d) => (
                <th key={d} className="px-2 py-1.5 text-left font-medium">
                  {dayLabel(d)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {LANES.map((lane) => (
              <tr key={lane} className="border-t border-border align-top">
                <th scope="row" className="px-2 py-2 text-left font-medium">
                  {({ linkedin: "LinkedIn", x: "X", instagram: "Instagram", hashnode: "Hashnode" } as Record<string, string>)[lane]}
                </th>
                {days.map((d) => (
                  <td key={d} className="space-y-1 px-1.5 py-1.5">
                    {entries
                      .filter((e) => laneOf(e.platform) === lane && dayKey(e.at) === d)
                      .map((e) =>
                        e.kind === "scheduled" ? (
                          <Link key={e.id} href={`/studio/drafts/${e.id}`} className="block rounded border border-accent/50 bg-accent/10 px-1.5 py-1 hover:underline">
                            {timeLabel(e.at)} · scheduled
                          </Link>
                        ) : safeUrl(e.url) ? (
                          <a key={e.id} href={safeUrl(e.url)} target="_blank" rel="noopener noreferrer" className="block rounded border border-good/50 bg-good/10 px-1.5 py-1 hover:underline">
                            {timeLabel(e.at)} · posted
                          </a>
                        ) : (
                          <span key={e.id} className="block rounded border border-good/50 bg-good/10 px-1.5 py-1">
                            {timeLabel(e.at)} · posted
                          </span>
                        ),
                      )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <h2 className="card-title mb-2">Series slots</h2>
          {c.series.length === 0 ? (
            <p className="text-sm text-muted">No series yet.</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {c.series.map((s) => (
                <li key={s.id}>
                  <span className="font-medium">{s.name}</span> <Badge tone="muted">{PLATFORM_LABEL[s.platform] ?? s.platform}</Badge>
                  <span className="block text-xs text-muted">
                    {describeCron(s.cadence)}
                    {s.slot && ` · ${s.slot}`}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card>
          <h2 className="card-title mb-2">Evergreen bank</h2>
          {c.evergreen.length === 0 ? (
            <p className="text-sm text-muted">Ready posts saved as evergreen fill quiet days.</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {c.evergreen.map((d) => (
                <li key={d.id}>
                  <Link href={`/studio/drafts/${d.id}`} className="hover:underline">
                    {d.idea?.thesis ?? "Draft"}
                  </Link>{" "}
                  <Badge tone="muted">{PLATFORM_LABEL[d.platform] ?? d.platform}</Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
