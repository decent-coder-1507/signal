"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Check, ChevronDown, Keyboard, RefreshCw, ThumbsUp } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useReducer, useRef, useState } from "react";
import { CitationList, CitedText } from "@/components/cited-text";
import { BriefProvenance } from "@/components/brief-provenance";
import { ReportInaccuracy } from "@/components/report-inaccuracy";
import { PageTitle } from "@/components/shell";
import { StoryActionBar, useStoryAction } from "@/components/story-actions";
import { StoryBadges } from "@/components/story-badges";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { post } from "@/lib/api";
import { citationIndex } from "@/lib/citations";
import { useCompleteBrief, useFeedback, useGenerateBrief, useLatestBrief } from "@/lib/hooks";
import { keyToCommand, navReducer, SHORTCUTS } from "@/lib/keynav";
import { BRIEF_KIND, fmtDateTime, RING } from "@/lib/labels";
import type { Brief, BriefStory, FeedbackKind } from "@/lib/types";

type RingFilter = "all" | string;

export default function BriefPage() {
  const brief = useLatestBrief();
  const generate = useGenerateBrief();

  if (brief.isLoading) return <p className="text-sm text-muted">Loading brief…</p>;
  if (brief.error) return <p className="text-sm text-bad">Could not load the brief.</p>;
  if (!brief.data)
    return (
      <div>
        <PageTitle sub="Your daily brief appears here.">Brief</PageTitle>
        <Card>
          <p className="text-sm text-muted">No brief yet. Generate one from what has been ingested so far.</p>
          <Button className="mt-3" variant="primary" disabled={generate.isPending} onClick={() => generate.mutate()}>
            <RefreshCw size={14} aria-hidden /> {generate.isPending ? "Generating…" : "Generate brief now"}
          </Button>
        </Card>
      </div>
    );
  return <BriefView key={brief.data.id} brief={brief.data} />;
}

function useMarkOpened(b: Brief) {
  const qc = useQueryClient();
  const open = useMutation({
    mutationFn: () => post(`/briefs/${b.id}/open`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["today"] }),
  });
  const sent = useRef(false);
  useEffect(() => {
    if (!b.opened_at && !sent.current) {
      sent.current = true;
      open.mutate();
    }
  }, [b.opened_at, open]);
}

function BriefView({ brief }: { brief: Brief }) {
  const c = brief.content;
  const router = useRouter();
  const feedback = useFeedback();
  const action = useStoryAction();
  const complete = useCompleteBrief();
  const generate = useGenerateBrief();
  useMarkOpened(brief);

  const rings = Array.from(new Set(c.stories.map((s) => s.ring)));
  const [ring, setRing] = useState<RingFilter>("all");
  const stories = ring === "all" ? c.stories : c.stories.filter((s) => s.ring === ring);
  const [nav, dispatch] = useReducer(navReducer, { index: -1, count: stories.length });
  const [marked, setMarked] = useState<Record<string, FeedbackKind>>({});
  const [help, setHelp] = useState(false);
  const cardRefs = useRef<(HTMLElement | null)[]>([]);

  const pickRing = (r: RingFilter) => {
    setRing(r);
    const n = r === "all" ? c.stories.length : c.stories.filter((s) => s.ring === r).length;
    dispatch({ type: "count", count: n });
    dispatch({ type: "set", index: -1 });
  };

  useEffect(() => {
    if (nav.index < 0) return;
    const el = cardRefs.current[nav.index];
    el?.focus({ preventScroll: true });
    el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [nav.index]);

  const giveFeedback = (s: BriefStory, kind: FeedbackKind) => {
    setMarked((m) => ({ ...m, [s.story_id]: kind }));
    feedback.mutate({ id: s.story_id, kind, context: { brief_id: brief.id } });
  };

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const cmd = keyToCommand(e);
      if (!cmd) return;
      if (cmd === "help") {
        e.preventDefault();
        setHelp((h) => !h);
        return;
      }
      if (cmd === "escape") {
        setHelp(false);
        return;
      }
      if (cmd === "next" || cmd === "prev") {
        e.preventDefault();
        dispatch({ type: cmd });
        return;
      }
      const s = stories[nav.index];
      if (!s) return;
      e.preventDefault();
      if (cmd === "useful") giveFeedback(s, "useful");
      else if (cmd === "skip") giveFeedback(s, "not_for_me");
      else if (cmd === "open") router.push(`/stories/${s.story_id}`);
      else action.mutate({ kind: cmd, id: s.story_id, title: s.title });
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const kindLabel =
    c.kind === "catchup" && c.since
      ? `${BRIEF_KIND.catchup} (${Math.max(1, Math.round((Date.parse(brief.period_end) - Date.parse(c.since)) / 86_400_000))} days)`
      : (BRIEF_KIND[c.kind] ?? c.kind);

  return (
    <div className="mx-auto max-w-3xl">
      <PageTitle eyebrow={<span className="font-mono">{fmtDateTime(brief.created_at)}</span>}>
        <span data-testid="brief-kind">{kindLabel}</span>
      </PageTitle>
      {c.topline && (
        <p className="-mt-3 mb-6 text-[17px] leading-snug text-text-2" data-testid="brief-topline">
          {c.topline}
        </p>
      )}
      {c.degraded && (
        <p className="mb-4 rounded-xl border border-warn/40 bg-warn/10 px-4 py-2.5 text-sm">
          Some analysis was unavailable; parts of this brief are ranked by deterministic scores only.
        </p>
      )}

      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div role="group" aria-label="Filter by ring" className="flex flex-wrap gap-1">
          {["all", ...rings].map((r) => (
            <button
              key={r}
              type="button"
              aria-pressed={ring === r}
              onClick={() => pickRing(r)}
              className={clsx(
                "min-h-8 rounded-full border px-3.5 text-xs font-medium transition-colors",
                ring === r ? "border-primary bg-primary text-primary-contrast" : "border-border-strong bg-surface text-muted hover:text-text",
              )}
            >
              {r === "all" ? `All (${c.stories.length})` : `${RING[r] ?? r} (${c.stories.filter((s) => s.ring === r).length})`}
            </button>
          ))}
        </div>
        <div className="relative">
          <Button size="sm" variant="ghost" aria-expanded={help} onClick={() => setHelp((h) => !h)} aria-label="Keyboard shortcuts">
            <Keyboard size={14} aria-hidden /> ?
          </Button>
          {help && (
            <div
              role="dialog"
              aria-label="Keyboard shortcuts"
              className="absolute right-0 z-30 mt-1 w-64 rounded-xl border border-border bg-surface p-3.5 text-sm shadow-lg"
            >
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5">
                {SHORTCUTS.map((s) => (
                  <div key={s.keys} className="contents">
                    <dt>
                      <kbd>{s.keys}</kbd>
                    </dt>
                    <dd className="text-muted">{s.label}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}
        </div>
      </div>

      {c.quiet && (
        <Card className="mb-4">
          <p className="text-sm">{c.quiet.message}</p>
          {c.quiet.deep_dive && (
            <Link className="mt-2 inline-block text-sm text-accent underline" href={`/stories/${c.quiet.deep_dive.story_id}`}>
              {c.quiet.deep_dive.title}
            </Link>
          )}
        </Card>
      )}

      <ol className="space-y-3.5" aria-label="Top stories">
        {stories.map((s, i) => (
          <li key={s.story_id}>
            <StoryCardView
              story={s}
              briefId={brief.id}
              rank={c.stories.indexOf(s) + 1}
              focused={nav.index === i}
              marked={marked[s.story_id]}
              onFocus={() => dispatch({ type: "set", index: i })}
              onFeedback={(k) => giveFeedback(s, k)}
              cardRef={(el) => {
                cardRefs.current[i] = el;
              }}
            />
          </li>
        ))}
      </ol>

      <div className="mt-5 grid gap-3.5 sm:grid-cols-2">
      {c.post_suggestion && (
        <Card>
          <CardTitle aside={c.post_suggestion.platform ?? undefined}>Post suggestion</CardTitle>
          <p className="text-sm">{c.post_suggestion.label}</p>
          {c.post_suggestion.angle && <p className="mt-1 text-sm text-muted">Angle: {c.post_suggestion.angle}</p>}
          <Link href={`/stories/${c.post_suggestion.story_id}`} className="mt-1 inline-block text-xs text-accent underline">
            {c.post_suggestion.title}
          </Link>
        </Card>
      )}
      {c.build_spark && (
        <Card>
          <CardTitle aside={c.build_spark.type}>Build spark</CardTitle>
          <p className="text-[15px] font-semibold leading-snug">{c.build_spark.title}</p>
          <p className="text-sm text-muted">{c.build_spark.one_liner}</p>
        </Card>
      )}
      {c.learn && (
        <Card>
          <CardTitle>Learn</CardTitle>
          <p className="text-sm">{c.learn.label ?? c.learn.skill}</p>
          <div className="mt-1 flex flex-wrap gap-3 text-xs">
            <Link
              href={`/gym?tab=explain&topic=${encodeURIComponent(c.learn.skill ?? c.learn.label ?? "")}&story=${c.learn.story_id}`}
              className="text-accent underline"
            >
              Read the explainer
            </Link>
            <Link href={`/stories/${c.learn.story_id}`} className="text-muted underline">
              From today&apos;s story
            </Link>
          </div>
        </Card>
      )}

      {c.watches.length > 0 && (
        <Card>
          <CardTitle>Watches triggered</CardTitle>
          <ul className="space-y-2 text-sm">
            {c.watches.map((w, i) => (
              <li key={i}>
                <span className="text-muted">{w.watch}: </span>
                <Link href={`/stories/${w.story_id}`} className="underline underline-offset-2">
                  {w.title}
                </Link>
                {w.explanation && <p className="text-xs text-muted">{w.explanation}</p>}
              </li>
            ))}
          </ul>
        </Card>
      )}
      </div>

      {c.quick_hits.length > 0 && (
        <details className="group mt-3.5 bento p-5">
          <summary className="card-title flex cursor-pointer list-none items-center justify-between">
            Quick hits ({c.quick_hits.length})
            <ChevronDown size={16} className="transition-transform group-open:rotate-180" aria-hidden />
          </summary>
          <ul className="mt-2 space-y-2 text-sm">
            {c.quick_hits.map((q) => (
              <li key={q.story_id}>
                <Link href={`/stories/${q.story_id}`} className="font-medium hover:underline">
                  {q.title}
                </Link>
                <span className="ml-1.5 text-xs text-muted">· {RING[q.ring] ?? q.ring}</span>
              </li>
            ))}
          </ul>
        </details>
      )}

      <div className="bento-invert mt-5 flex flex-wrap items-center justify-between gap-3 p-5">
        <p className="text-sm text-[var(--invert-muted)]">
          {c.cards_due > 0 ? `${c.cards_due} cards due today.` : "No cards due."}{" "}
          {brief.completed_at ? "Brief marked done." : "Triaged everything you need?"}
        </p>
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="ghost"
            className="text-[var(--invert-muted)] hover:bg-white/10 hover:text-[var(--invert-text)]"
            disabled={generate.isPending}
            onClick={() => generate.mutate()}
          >
            <RefreshCw size={14} aria-hidden /> {generate.isPending ? "Generating…" : "Regenerate"}
          </Button>
          <Button
            variant="primary"
            className="bg-[var(--invert-mark)] text-[var(--invert-on-mark)]"
            disabled={complete.isPending || !!brief.completed_at}
            onClick={() => complete.mutate({ id: brief.id, minimum: false })}
          >
            <Check size={16} aria-hidden /> {brief.completed_at ? "Brief done" : "Mark brief done"}
          </Button>
        </div>
      </div>

      <BriefProvenance briefId={brief.id} />
    </div>
  );
}

const HINTS: [string, string][] = [
  ["u", "useful"],
  ["p", "post"],
  ["b", "build"],
  ["l", "learn"],
  ["x", "skip"],
];

function StoryCardView({
  story: s,
  briefId,
  rank,
  focused,
  marked,
  onFocus,
  onFeedback,
  cardRef,
}: {
  story: BriefStory;
  briefId: string;
  rank: number;
  focused: boolean;
  marked?: FeedbackKind;
  onFocus: () => void;
  onFeedback: (k: FeedbackKind) => void;
  cardRef: (el: HTMLElement | null) => void;
}) {
  const idx = citationIndex(s.citations);
  return (
    <article
      ref={cardRef}
      tabIndex={-1}
      data-testid="story-card"
      data-focused={focused || undefined}
      aria-current={focused || undefined}
      onFocus={onFocus}
      className={clsx(
        "bento p-5 outline-none transition-shadow md:p-6",
        focused && "border-accent! shadow-[0_0_0_1px_var(--accent),var(--signal-glow)]",
        marked === "not_for_me" && "opacity-60",
      )}
    >
      <div className="flex items-center gap-2.5">
        <span className="num shrink-0 text-xs font-semibold text-muted" aria-label={`Rank ${rank}`}>
          {String(rank).padStart(2, "0")}
        </span>
        <div className="min-w-0 flex-1">
          <StoryBadges
            ring={s.ring}
            update={s.update}
            hype={s.hype_verdict}
            durability={s.durability}
            exploration={s.exploration}
            degraded={s.degraded}
          />
        </div>
        {idx.size > 0 && <span className="hidden shrink-0 font-mono text-[11px] text-muted sm:inline">{idx.size} src</span>}
      </div>
      <h2 className="mt-3 text-[19px] font-semibold leading-snug tracking-[-0.015em]">
        <Link href={`/stories/${s.story_id}`} className="hover:underline">
          {s.title}
        </Link>
      </h2>
      <p className="mt-1.5 text-[14.5px] leading-relaxed text-text-2">
        <CitedText text={s.one_line} index={idx} />
      </p>
      {s.update && s.what_changed && (
        <p className="mt-2 text-sm">
          <span className="font-medium text-info">What changed: </span>
          {s.what_changed}
        </p>
      )}
      {s.why_you && (
        <div className="why-box mt-3.5 px-3.5 py-3 text-[13.5px] leading-relaxed">
          <p className="font-semibold">Why it matters to you</p>
          <p className="mt-0.5">
            <CitedText text={s.why_you} index={idx} />
          </p>
        </div>
      )}
      {s.uncertainty.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {s.uncertainty.map((u) => (
            <Badge key={u} tone="warn">
              {u}
            </Badge>
          ))}
        </div>
      )}
      <div className="mt-4">
        <StoryActionBar
          id={s.story_id}
          title={s.title}
          leading={
            <Button
              size="sm"
              variant={marked === "useful" ? "primary" : "secondary"}
              aria-pressed={marked === "useful"}
              aria-keyshortcuts="u"
              onClick={() => onFeedback("useful")}
            >
              <ThumbsUp size={14} aria-hidden /> Useful
            </Button>
          }
        />
        <p className="mt-3 hidden flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted md:flex" aria-hidden>
          <span className="inline-flex items-center gap-1">
            <kbd>j</kbd>
            <kbd>k</kbd> move
          </span>
          {HINTS.map(([k, l]) => (
            <span key={k} className="inline-flex items-center gap-1">
              <kbd>{k}</kbd> {l}
            </span>
          ))}
        </p>
        {marked && (
          <p className="mt-1.5 text-xs text-muted" data-testid="feedback-state">
            {marked === "useful" ? "Marked useful" : marked === "not_for_me" ? "Skipped" : `Marked: ${marked}`}
          </p>
        )}
      </div>
      <div className="mt-3 flex flex-wrap items-start justify-between gap-2">
        {idx.size > 0 ? (
          <details className="min-w-0 flex-1 text-sm">
            <summary className="cursor-pointer py-1.5 text-xs text-muted hover:text-text">Sources ({idx.size})</summary>
            <div className="mt-2">
              <CitationList index={idx} />
            </div>
          </details>
        ) : (
          <span />
        )}
        <ReportInaccuracy targetType="story" targetId={s.story_id} context={{ brief_id: briefId, block: "brief_card" }} />
      </div>
    </article>
  );
}
