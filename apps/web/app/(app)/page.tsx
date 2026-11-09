"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowUpRight, Check, Flame, RefreshCw, Snowflake, Timer } from "lucide-react";
import Link from "next/link";
import { CaptureBox } from "@/components/capture-box";
import { PageTitle, useMe } from "@/components/shell";
import { Badge } from "@/components/ui/badge";
import { Button, buttonClass } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { get, post } from "@/lib/api";
import { habitProgress } from "@/lib/habit";
import { errMsg, useCompleteBrief, useGenerateBrief, useToday } from "@/lib/hooks";
import { BRIEF_KIND, fmtDateTime, humanize } from "@/lib/labels";
import type { Notification, Today } from "@/lib/types";

const STEPS = [
  { id: "brief", label: "Brief triaged" },
  { id: "action", label: "1 action taken" },
  { id: "cards", label: "Cards reviewed" },
] as const;

function longDate(d: string | undefined) {
  if (!d) return undefined;
  const dt = new Date(`${d}T12:00:00Z`);
  if (Number.isNaN(dt.getTime())) return d;
  return new Intl.DateTimeFormat("en-IN", { weekday: "long", day: "numeric", month: "long", timeZone: "Asia/Kolkata" }).format(dt);
}

export default function TodayPage() {
  const me = useMe();
  const today = useToday();
  const generate = useGenerateBrief();
  const complete = useCompleteBrief();
  const t = today.data;
  // GET /today returns only daily/catch-up/weekend briefs, never a review.
  const brief = t?.brief ?? null;

  return (
    <div className="mx-auto max-w-6xl">
      <PageTitle
        eyebrow={longDate(t?.date)}
        sub="Brief → one action → cards. Ten minutes is enough."
        aside={
          <span className="hidden items-center gap-1.5 text-xs text-muted md:inline-flex" aria-hidden>
            <kbd>Ctrl K</kbd> search
          </span>
        }
      >
        Today
      </PageTitle>
      {me.data && !me.data.onboarded && (
        <p className="why-box mb-4 px-4 py-3 text-sm">
          Finish setting up SIGNAL to tune your brief.{" "}
          <Link href="/onboarding" className="font-semibold underline">
            Continue setup
          </Link>
        </p>
      )}
      {today.isLoading && <p className="text-sm text-muted">Loading…</p>}
      {t && (
        <div className="grid grid-flow-row-dense grid-cols-2 gap-3.5 lg:grid-cols-4">
          <Progress t={t} />
          <Streak t={t} />
          <Card className="flex flex-col">
            <dl>
              <dt className="label">Cards due</dt>
              <dd className="num mt-1.5 text-[30px] font-semibold leading-none">{t.cards_due}</dd>
            </dl>
            <div className="mt-auto pt-3">
              {t.cards_due > 0 ? (
                <Link href="/gym?tab=cards" className={buttonClass("secondary", "sm")}>
                  Review cards
                </Link>
              ) : (
                <p className="text-xs text-muted">Nothing due — you&apos;re clear.</p>
              )}
            </div>
          </Card>

          <Card className="col-span-2 lg:col-span-3">
            <CardTitle aside={brief ? fmtDateTime(brief.created_at) : undefined}>
              {brief ? (BRIEF_KIND[brief.content.kind] ?? "Brief") : "Today's brief"}
            </CardTitle>
            {brief ? (
              <>
                {brief.content.topline && (
                  <p className="text-[19px] font-semibold leading-snug tracking-[-0.015em]">{brief.content.topline}</p>
                )}
                <p className="mt-1.5 flex flex-wrap items-center gap-1.5 text-sm text-muted">
                  <Badge>{brief.content.stories.length} stories</Badge>
                  {brief.content.quick_hits.length > 0 && <Badge>{brief.content.quick_hits.length} quick hits</Badge>}
                  {brief.completed_at && <Badge tone="good">done</Badge>}
                </p>
                {!brief.completed_at && (
                  <ol className="mt-4 divide-y divide-border border-y border-border">
                    {brief.content.stories.slice(0, 3).map((s, i) => (
                      <li key={s.story_id} className="flex items-baseline gap-3 py-2.5">
                        <span className="num shrink-0 text-xs font-semibold text-muted">{String(i + 1).padStart(2, "0")}</span>
                        <Link href={`/stories/${s.story_id}`} className="min-w-0 flex-1 text-[15px] font-medium leading-snug hover:underline">
                          {s.title}
                        </Link>
                      </li>
                    ))}
                  </ol>
                )}
                <div className="mt-4 flex flex-wrap gap-2">
                  <Link href="/brief" className={buttonClass("primary")}>
                    Open brief
                  </Link>
                  {!brief.completed_at && (
                    <Button
                      disabled={complete.isPending}
                      onClick={() => complete.mutate({ id: brief.id, minimum: true })}
                      title="Read the top 3 one-liners — still counts for today"
                    >
                      <Timer size={14} aria-hidden /> 2-minute mode
                    </Button>
                  )}
                  <Button variant="ghost" disabled={generate.isPending} onClick={() => generate.mutate()}>
                    <RefreshCw size={14} aria-hidden /> {generate.isPending ? "Generating…" : "Generate brief now"}
                  </Button>
                </div>
              </>
            ) : (
              <>
                <p className="text-sm text-muted">No brief yet today.</p>
                <Button className="mt-3" variant="primary" disabled={generate.isPending} onClick={() => generate.mutate()}>
                  <RefreshCw size={14} aria-hidden /> {generate.isPending ? "Generating…" : "Generate brief now"}
                </Button>
              </>
            )}
          </Card>

          <Card className="col-span-2 lg:col-span-1">
            <CardTitle>This month</CardTitle>
            <dl className="grid grid-cols-3 gap-2 lg:grid-cols-1 lg:gap-3">
              {Object.entries(t.this_month).map(([k, v]) => (
                <div key={k} className="flex flex-col gap-0.5 lg:flex-row lg:items-baseline lg:justify-between">
                  <dt className="text-xs text-muted lg:order-2">{k === "pocs" ? "POCs" : humanize(k)}</dt>
                  <dd className="num text-2xl font-semibold leading-none">{v}</dd>
                </div>
              ))}
            </dl>
          </Card>

          {brief?.content.post_suggestion && (
            <Card className="col-span-2 flex flex-col md:col-span-1">
              <CardTitle aside={brief.content.post_suggestion.platform ?? undefined}>Post suggestion</CardTitle>
              <p className="text-[15px] font-semibold leading-snug">{brief.content.post_suggestion.label}</p>
              <Link
                href={`/stories/${brief.content.post_suggestion.story_id}`}
                className="mt-auto inline-flex items-start gap-1 pt-2 text-xs text-accent underline underline-offset-2"
              >
                {brief.content.post_suggestion.title}
              </Link>
            </Card>
          )}
          {brief?.content.build_spark && (
            <Card className="col-span-2 md:col-span-1">
              <CardTitle>Build spark</CardTitle>
              <p className="text-[15px] font-semibold leading-snug">{brief.content.build_spark.title}</p>
              <p className="mt-1 text-sm text-muted">{brief.content.build_spark.one_liner}</p>
            </Card>
          )}
          {brief?.content.learn && (
            <Card className="col-span-2 flex flex-col md:col-span-1">
              <CardTitle>Learn</CardTitle>
              <p className="text-[15px] font-semibold leading-snug">{brief.content.learn.label ?? brief.content.learn.skill}</p>
              <Link
                href={`/gym?tab=explain&topic=${encodeURIComponent(brief.content.learn.skill ?? brief.content.learn.label ?? "")}&story=${brief.content.learn.story_id}`}
                className="mt-auto inline-flex items-center gap-1 pt-2 text-xs text-accent underline underline-offset-2"
              >
                Read the explainer <ArrowUpRight size={12} aria-hidden />
              </Link>
            </Card>
          )}
          <Notifications unread={t.unread_notifications} />
          <Card className="col-span-2">
            <CardTitle>Capture</CardTitle>
            <CaptureBox />
          </Card>
        </div>
      )}
    </div>
  );
}

/** The dashboard's inverted tile: today's 3-step ring. */
function Progress({ t }: { t: Today }) {
  const { done, count } = habitProgress(t);
  const mode = t.habit.mode;
  const pct = (count / 3) * 100;
  const r = 26;
  const circ = 2 * Math.PI * r;
  return (
    <Card invert aria-label="Daily progress" data-testid="habit-progress" className="col-span-2">
      <div className="flex items-center gap-4">
        <svg width="76" height="76" viewBox="0 0 64 64" className="shrink-0" role="img" aria-label={`${count} of 3 steps done`}>
          <circle cx="32" cy="32" r={r} fill="none" stroke="var(--invert-track)" strokeWidth="7" />
          <circle
            cx="32"
            cy="32"
            r={r}
            fill="none"
            stroke="var(--invert-mark)"
            className="glow-mark"
            strokeWidth="7"
            strokeLinecap="round"
            strokeDasharray={circ}
            strokeDashoffset={circ * (1 - pct / 100)}
            transform="rotate(-90 32 32)"
          />
          <text x="32" y="37" textAnchor="middle" fontSize="15" fill="currentColor" fontWeight="600" fontFamily="var(--mono)">
            {count}/3
          </text>
        </svg>
        <div className="min-w-0 flex-1">
          <p className="text-[12.5px] font-medium text-[var(--invert-muted)]">Today</p>
          <ol className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm">
            {STEPS.map((s) => (
              <li
                key={s.id}
                data-testid={`step-${s.id}`}
                data-done={done[s.id] || undefined}
                className={clsx("inline-flex items-center gap-1.5", done[s.id] ? "font-medium" : "text-[var(--invert-muted)]")}
              >
                <span
                  className={clsx(
                    "inline-flex h-4 w-4 items-center justify-center rounded-full border",
                    done[s.id] ? "border-[var(--invert-mark)] bg-[var(--invert-mark)] text-[var(--invert-bg)]" : "border-[var(--invert-muted)]",
                  )}
                  aria-hidden
                >
                  {done[s.id] && <Check size={11} strokeWidth={3} />}
                </span>
                {s.label}
              </li>
            ))}
          </ol>
          <p className="mt-2 text-xs text-[var(--invert-muted)]" data-testid="habit-mode">
            {mode === "full"
              ? "Today is complete. Nice."
              : mode === "minimum"
                ? "Today counts. Add an action if you have a minute."
                : mode === "freeze"
                  ? "Today is covered by a freeze."
                  : "A quick look at the brief is enough to count today."}
          </p>
        </div>
      </div>
    </Card>
  );
}

function Streak({ t }: { t: Today }) {
  const qc = useQueryClient();
  const toast = useToast();
  const freeze = useMutation({
    mutationFn: () => post<{ ok: boolean }>("/habit/freeze"),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["today"] });
      toast(r.ok ? "Freeze used — your streak is safe" : "No freeze available right now", r.ok ? "good" : "info");
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  return (
    <Card className="flex flex-col">
      <dl data-testid="streak">
        <dt className="label inline-flex items-center gap-1">
          <Flame size={13} className="text-hot" aria-hidden /> Streak
        </dt>
        <dd className="num mt-1.5 text-[30px] font-semibold leading-none">
          {t.habit.streak}
          <span className="ml-1 font-sans text-sm font-normal tracking-normal text-muted">{t.habit.streak === 1 ? "day" : "days"}</span>
        </dd>
      </dl>
      {t.habit.streak === 0 && <p className="mt-1 text-xs text-muted">Start a streak today</p>}
      <div className="mt-auto flex flex-wrap items-center gap-2 pt-3">
        <Badge tone="good">
          <Snowflake size={11} className="mr-1" aria-hidden />
          {t.habit.freezes_left} freezes left
        </Badge>
        {t.habit.mode === "missed" && t.habit.freezes_left > 0 && (
          <Button size="sm" variant="ghost" disabled={freeze.isPending} onClick={() => freeze.mutate()}>
            Use a freeze
          </Button>
        )}
      </div>
    </Card>
  );
}

function Notifications({ unread }: { unread: number }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["notifications"], queryFn: () => get<Notification[]>("/notifications?limit=10") });
  const readAll = useMutation({
    mutationFn: () => post("/notifications/read-all"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notifications"] });
      qc.invalidateQueries({ queryKey: ["today"] });
    },
  });
  const items = (q.data ?? []).filter((n) => !n.read);
  return (
    <Card className="col-span-2 md:col-span-1">
      <CardTitle
        aside={
          unread > 0 ? (
            <button type="button" className="font-sans text-xs underline" onClick={() => readAll.mutate()}>
              Mark all read
            </button>
          ) : undefined
        }
      >
        Notifications {unread > 0 && <span className="num text-accent">({unread})</span>}
      </CardTitle>
      {items.length === 0 ? (
        <p className="text-sm text-muted">All caught up.</p>
      ) : (
        <ul className="space-y-2.5 text-sm">
          {items.map((n) => {
            const title = typeof n.payload.title === "string" ? n.payload.title : humanize(n.kind);
            const storyId = typeof n.payload.story_id === "string" ? n.payload.story_id : null;
            return (
              <li key={n.id} className="min-w-0 break-words">
                {storyId ? (
                  <Link href={`/stories/${storyId}`} className="font-medium hover:underline">
                    {title}
                  </Link>
                ) : (
                  title
                )}
                <span className="block font-mono text-[11px] text-muted">{fmtDateTime(n.created_at)}</span>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
