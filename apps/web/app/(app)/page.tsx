"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Check, Flame, RefreshCw, Snowflake, Timer } from "lucide-react";
import Link from "next/link";
import { CaptureBox } from "@/components/capture-box";
import { PageTitle, useMe } from "@/components/shell";
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

export default function TodayPage() {
  const me = useMe();
  const today = useToday();
  const generate = useGenerateBrief();
  const complete = useCompleteBrief();
  const t = today.data;
  const brief = t?.brief;

  return (
    <div className="mx-auto max-w-4xl">
      <PageTitle sub="Brief → one action → cards. Ten minutes is enough.">Today</PageTitle>
      {me.data && !me.data.onboarded && (
        <p className="mb-4 rounded-md border border-accent/40 bg-accent/10 px-3 py-2 text-sm">
          Finish setting up SIGNAL to tune your brief.{" "}
          <Link href="/onboarding" className="font-medium underline">
            Continue setup
          </Link>
        </p>
      )}
      {today.isLoading && <p className="text-sm text-muted">Loading…</p>}
      {t && (
        <div className="grid gap-4 md:grid-cols-[1fr_18rem]">
          <div className="min-w-0 space-y-4">
            <Progress t={t} />

            <Card>
              <CardTitle aside={brief ? fmtDateTime(brief.created_at) : undefined}>
                {brief ? (BRIEF_KIND[brief.content.kind] ?? "Brief") : "Today's brief"}
              </CardTitle>
              {brief ? (
                <>
                  {brief.content.topline && <p className="font-serif text-lg leading-snug">{brief.content.topline}</p>}
                  <p className="mt-1 text-sm text-muted">
                    {brief.content.stories.length} stories
                    {brief.content.quick_hits.length ? ` · ${brief.content.quick_hits.length} quick hits` : ""}
                    {brief.completed_at ? " · done" : ""}
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2">
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
                  {!brief.completed_at && (
                    <ol className="mt-3 space-y-1 border-t border-border pt-3 text-sm">
                      {brief.content.stories.slice(0, 3).map((s) => (
                        <li key={s.story_id}>
                          <Link href={`/stories/${s.story_id}`} className="hover:underline">
                            {s.title}
                          </Link>
                        </li>
                      ))}
                    </ol>
                  )}
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

            {brief?.content.post_suggestion && (
              <Card>
                <CardTitle aside={brief.content.post_suggestion.platform ?? undefined}>Post suggestion</CardTitle>
                <p className="text-sm">{brief.content.post_suggestion.label}</p>
                <Link href={`/stories/${brief.content.post_suggestion.story_id}`} className="mt-1 inline-block text-xs text-accent underline">
                  {brief.content.post_suggestion.title}
                </Link>
              </Card>
            )}
            {brief?.content.build_spark && (
              <Card>
                <CardTitle>Build spark</CardTitle>
                <p className="text-sm font-medium">{brief.content.build_spark.title}</p>
                <p className="text-sm text-muted">{brief.content.build_spark.one_liner}</p>
              </Card>
            )}
            {brief?.content.learn && (
              <Card>
                <CardTitle>Learn</CardTitle>
                <p className="text-sm">{brief.content.learn.label ?? brief.content.learn.skill}</p>
              </Card>
            )}
            <Card>
              <CardTitle>Capture</CardTitle>
              <CaptureBox />
            </Card>
          </div>

          <aside className="min-w-0 space-y-4">
            <Card>
              <CardTitle>This month</CardTitle>
              <dl className="grid grid-cols-3 gap-2 text-center">
                {Object.entries(t.this_month).map(([k, v]) => (
                  <div key={k}>
                    <dd className="font-serif text-2xl font-semibold tabular-nums">{v}</dd>
                    <dt className="text-xs text-muted">{k === "pocs" ? "POCs" : humanize(k)}</dt>
                  </div>
                ))}
              </dl>
            </Card>
            <Card>
              <CardTitle>Cards due</CardTitle>
              <p className="text-sm">
                {t.cards_due > 0 ? (
                  <>
                    <span className="font-semibold tabular-nums">{t.cards_due}</span> cards ready for review
                  </>
                ) : (
                  <span className="text-muted">Nothing due — you&apos;re clear.</span>
                )}
              </p>
            </Card>
            <Notifications unread={t.unread_notifications} />
          </aside>
        </div>
      )}
    </div>
  );
}

function Progress({ t }: { t: Today }) {
  const { done, count } = habitProgress(t);
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
  const mode = t.habit.mode;
  const pct = (count / 3) * 100;
  const r = 26;
  const circ = 2 * Math.PI * r;
  return (
    <Card aria-label="Daily progress" data-testid="habit-progress">
      <div className="flex items-center gap-4">
        <svg width="64" height="64" viewBox="0 0 64 64" className="shrink-0" role="img" aria-label={`${count} of 3 steps done`}>
          <circle cx="32" cy="32" r={r} fill="none" stroke="var(--surface-2)" strokeWidth="7" />
          <circle
            cx="32"
            cy="32"
            r={r}
            fill="none"
            stroke="var(--accent)"
            strokeWidth="7"
            strokeLinecap="round"
            strokeDasharray={circ}
            strokeDashoffset={circ * (1 - pct / 100)}
            transform="rotate(-90 32 32)"
          />
          <text x="32" y="37" textAnchor="middle" fontSize="15" fill="var(--text)" fontWeight="600">
            {count}/3
          </text>
        </svg>
        <div className="min-w-0 flex-1">
          <ol className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
            {STEPS.map((s) => (
              <li
                key={s.id}
                data-testid={`step-${s.id}`}
                data-done={done[s.id] || undefined}
                className={clsx("inline-flex items-center gap-1", done[s.id] ? "text-text" : "text-muted")}
              >
                <span
                  className={clsx(
                    "inline-flex h-4 w-4 items-center justify-center rounded-full border",
                    done[s.id] ? "border-good bg-good text-surface" : "border-border",
                  )}
                  aria-hidden
                >
                  {done[s.id] && <Check size={11} strokeWidth={3} />}
                </span>
                {s.label}
              </li>
            ))}
          </ol>
          <p className="mt-1.5 text-xs text-muted" data-testid="habit-mode">
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
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-border pt-3 text-sm">
        <span className="inline-flex items-center gap-1" data-testid="streak">
          <Flame size={14} className="text-accent" aria-hidden />
          {t.habit.streak > 0 ? `${t.habit.streak}-day streak` : "Start a streak today"}
        </span>
        <span className="inline-flex items-center gap-1 text-muted">
          <Snowflake size={14} aria-hidden /> {t.habit.freezes_left} freezes left this month
        </span>
        {mode === "missed" && t.habit.freezes_left > 0 && (
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
    <Card>
      <CardTitle
        aside={
          unread > 0 ? (
            <button type="button" className="underline" onClick={() => readAll.mutate()}>
              Mark all read
            </button>
          ) : undefined
        }
      >
        Notifications {unread > 0 && <span className="text-accent">({unread})</span>}
      </CardTitle>
      {items.length === 0 ? (
        <p className="text-sm text-muted">All caught up.</p>
      ) : (
        <ul className="space-y-2 text-sm">
          {items.map((n) => {
            const title = typeof n.payload.title === "string" ? n.payload.title : humanize(n.kind);
            const storyId = typeof n.payload.story_id === "string" ? n.payload.story_id : null;
            return (
              <li key={n.id} className="min-w-0 break-words">
                {storyId ? (
                  <Link href={`/stories/${storyId}`} className="hover:underline">
                    {title}
                  </Link>
                ) : (
                  title
                )}
                <span className="block text-xs text-muted">{fmtDateTime(n.created_at)}</span>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
