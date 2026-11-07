"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Flag, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, type ReactNode } from "react";
import { CitationList, CitedText } from "@/components/cited-text";
import { StoryActionBar } from "@/components/story-actions";
import { StoryBadges } from "@/components/story-badges";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { ApiError, get, post } from "@/lib/api";
import { citationIndex, type CitationRef } from "@/lib/citations";
import { errMsg, useFeedback } from "@/lib/hooks";
import { safeUrl } from "@/lib/safe-url";
import { DURABILITY, fmtDate, HYPE, humanize } from "@/lib/labels";
import type { FeedbackKind, StoryDetail } from "@/lib/types";

export default function StoryPage() {
  const { id } = useParams<{ id: string }>();
  const q = useQuery({ queryKey: ["story", id], queryFn: () => get<StoryDetail>(`/stories/${id}`) });
  const feedback = useFeedback();
  const opened = useRef<string | null>(null);

  useEffect(() => {
    if (q.data && opened.current !== id) {
      opened.current = id;
      feedback.mutate({ id, kind: "opened", silent: true });
    }
  }, [q.data, id, feedback]);

  if (q.isLoading) return <p className="text-sm text-muted">Loading story…</p>;
  if (q.error)
    return (
      <p className="text-sm text-bad">
        {q.error instanceof ApiError && q.error.status === 404 ? "Story not found." : "Could not load this story."}
      </p>
    );
  if (!q.data) return null;
  return <StoryView data={q.data} />;
}

function Section({ title, children, testId }: { title: string; children: ReactNode; testId?: string }) {
  return (
    <section className="mt-6" data-testid={testId}>
      <h2 className="mb-1.5 font-serif text-lg font-semibold">{title}</h2>
      <div className="text-[15px] leading-relaxed">{children}</div>
    </section>
  );
}

function StoryView({ data }: { data: StoryDetail }) {
  const { story: s, insight: ins, timeline, related, why } = data;
  const idx: Map<string, CitationRef> = citationIndex(ins?.citations);
  const qc = useQueryClient();
  const toast = useToast();
  const feedback = useFeedback();
  const regen = useMutation({
    mutationFn: () => post(`/stories/${s.id}/regenerate-insight`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["story", s.id] });
      toast("Insight regenerated", "good");
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const fb = (kind: FeedbackKind, context: Record<string, unknown> = {}) => feedback.mutate({ id: s.id, kind, context });

  return (
    <article className="mx-auto max-w-3xl">
      <Link href="/brief" className="mb-3 inline-flex items-center gap-1 text-sm text-muted hover:text-text">
        <ArrowLeft size={14} aria-hidden /> Brief
      </Link>
      <StoryBadges
        ring={s.ring}
        update={s.update}
        hype={ins?.hype_verdict ?? s.hype_verdict}
        durability={ins?.durability ?? s.durability}
        degraded={ins?.degraded}
      />
      <h1 className="mt-2 font-serif text-2xl font-semibold leading-tight tracking-tight md:text-3xl">{s.title}</h1>
      <p className="mt-1 text-xs text-muted">
        First seen {fmtDate(s.first_seen)} · updated {fmtDate(s.last_updated)}
        {ins?.reading_time ? ` · ${ins.reading_time} min primary read` : ""}
      </p>

      <div className="mt-4">
        <StoryActionBar id={s.id} title={s.title} followed={s.followed} />
      </div>

      {!ins && <p className="mt-6 text-sm text-muted">No insight has been generated for this story yet.</p>}

      {ins && (
        <>
          <Section title="What happened" testId="what-happened">
            <p>
              <CitedText text={ins.what_happened} index={idx} />
            </p>
          </Section>
          <Section title="Why it matters to you" testId="why-you">
            <p>
              <CitedText text={ins.why_you} index={idx} />
            </p>
          </Section>
          {ins.what_changes && (
            <Section title="What changes">
              <p>
                <CitedText text={ins.what_changes} index={idx} />
              </p>
            </Section>
          )}
          <div className="mt-6 grid gap-3 sm:grid-cols-2">
            <Card>
              <h2 className="text-sm font-semibold">Hype check</h2>
              <p className="mt-1 text-sm font-medium">{HYPE[ins.hype_verdict] ?? ins.hype_verdict}</p>
              {!!ins.hype_reasons?.length && (
                <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-muted">
                  {ins.hype_reasons.map((r, i) => (
                    <li key={i}>
                      <CitedText text={r} index={idx} />
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card>
              <h2 className="text-sm font-semibold">Durability</h2>
              <p className="mt-1 text-sm font-medium">{DURABILITY[ins.durability] ?? ins.durability}</p>
              {ins.durability_reason && <p className="mt-1 text-sm text-muted">{ins.durability_reason}</p>}
            </Card>
          </div>
          {ins.moat_note && (
            <Section title="Moat note">
              <p>
                <CitedText text={ins.moat_note} index={idx} />
              </p>
            </Section>
          )}
          {!!ins.open_questions?.length && (
            <Section title="Open questions">
              <ul className="list-disc space-y-1 pl-5">
                {ins.open_questions.map((qq, i) => (
                  <li key={i}>{qq}</li>
                ))}
              </ul>
            </Section>
          )}
          {!!ins.actions?.length && (
            <Section title="Suggested actions">
              <ul className="space-y-1.5">
                {ins.actions.map((a, i) => (
                  <li key={i} className="flex flex-wrap items-baseline gap-2 text-sm">
                    <Badge tone="muted">{humanize(a.type)}</Badge>
                    <span>{a.label}</span>
                    {a.platform && <span className="text-xs text-muted">({a.platform})</span>}
                  </li>
                ))}
              </ul>
            </Section>
          )}
          <div className="mt-6 flex flex-wrap items-center gap-2 text-sm">
            {ins.confidence != null && (
              <Badge tone={ins.confidence >= 0.7 ? "good" : ins.confidence >= 0.4 ? "warn" : "bad"} title={ins.confidence_reason ?? undefined}>
                Confidence {Math.round(ins.confidence * 100)}%
              </Badge>
            )}
            {(ins.uncertainty_labels ?? []).map((u) => (
              <Badge key={u} tone="warn">
                {u}
              </Badge>
            ))}
          </div>
          {ins.confidence_reason && <p className="mt-1 text-xs text-muted">{ins.confidence_reason}</p>}
          {idx.size > 0 && (
            <section className="mt-6">
              <h2 className="mb-1.5 text-sm font-semibold">Sources</h2>
              <CitationList index={idx} />
            </section>
          )}
        </>
      )}

      <Section title="Timeline" testId="timeline">
        {timeline.length === 0 ? (
          <p className="text-sm text-muted">No items.</p>
        ) : (
          <ol className="relative space-y-3 border-l border-border pl-4">
            {timeline.map((t) => (
              <li key={t.item_id} data-testid="timeline-item" className="relative">
                <span className="absolute -left-[21px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-surface bg-accent" aria-hidden />
                <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
                  <span>{fmtDate(t.published_at)}</span>
                  <Badge tone={t.tier === 1 ? "good" : t.tier === 2 ? "info" : "muted"} title="Source tier">
                    Tier {t.tier}
                  </Badge>
                  <span>{t.label}</span>
                </div>
                {safeUrl(t.url) ? (
                  <a
                    href={safeUrl(t.url)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-0.5 block break-words text-sm font-medium hover:underline"
                  >
                    {t.title}
                  </a>
                ) : (
                  <p className="mt-0.5 break-words text-sm font-medium">{t.title}</p>
                )}
                <p className="text-xs text-muted">
                  {t.source}
                  {t.summary ? ` — ${t.summary}` : ""}
                </p>
              </li>
            ))}
          </ol>
        )}
      </Section>

      {related.length > 0 && (
        <Section title="Related stories">
          <ul className="space-y-1 text-sm">
            {related.map((r) => (
              <li key={r.id}>
                <Link href={`/stories/${r.id}`} className="hover:underline">
                  {r.title}
                </Link>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <WhyPanel why={why} />

      <div className="mt-6 flex flex-wrap gap-1.5 border-t border-border pt-4" role="group" aria-label="Feedback">
        {(
          [
            ["useful", "Useful"],
            ["not_for_me", "Not for me"],
            ["more", "More like this"],
            ["less", "Less like this"],
            ["known", "Already knew"],
            ["saved", "Save"],
          ] as [FeedbackKind, string][]
        ).map(([k, label]) => (
          <Button key={k} size="sm" onClick={() => fb(k)} disabled={feedback.isPending}>
            {label}
          </Button>
        ))}
        <Button size="sm" variant="danger" onClick={() => fb("wrong", { block: "insight", version: ins?.version })}>
          <Flag size={14} aria-hidden /> Report inaccuracy
        </Button>
        <Button size="sm" variant="ghost" disabled={regen.isPending} onClick={() => regen.mutate()}>
          <RefreshCw size={14} aria-hidden /> {regen.isPending ? "Regenerating…" : "Regenerate insight"}
        </Button>
      </div>
      {ins && (
        <p className="mt-3 text-[11px] text-muted">
          Insight v{ins.version} · {ins.model} · prompt {ins.prompt_version}
        </p>
      )}
    </article>
  );
}

function WhyPanel({ why }: { why: StoryDetail["why"] }) {
  const subs = Object.entries(why.sub_scores).filter(([, v]) => v != null) as [string, number][];
  return (
    <details className="mt-6 rounded-lg border border-border bg-surface p-4" data-testid="why-seeing">
      <summary className="cursor-pointer text-sm font-semibold">Why am I seeing this?</summary>
      <p className="mt-2 text-sm">
        Final score <span className="font-medium tabular-nums">{why.final_score.toFixed(2)}</span>
        {why.matched_profile && <span className="text-muted"> · closest profile match: {why.matched_profile}</span>}
      </p>
      {subs.length > 0 && (
        <dl className="mt-3 space-y-1.5">
          {subs.map(([k, v]) => (
            <div key={k} className="grid grid-cols-[7rem_1fr_auto] items-center gap-2 text-xs">
              <dt className="text-muted">{humanize(k)}</dt>
              <dd className="h-1.5 overflow-hidden rounded-full bg-surface-2">
                <div className="h-full rounded-full bg-accent" style={{ width: `${Math.max(0, Math.min(1, v)) * 100}%` }} />
              </dd>
              <dd className="tabular-nums text-muted">
                {v.toFixed(2)}
                {why.weights?.[k] != null && <span title="weight"> × {why.weights[k]}</span>}
              </dd>
            </div>
          ))}
        </dl>
      )}
      {why.penalties.length > 0 && (
        <p className="mt-3 text-xs">
          <span className="font-medium text-bad">Penalties: </span>
          {why.penalties.join(", ")}
        </p>
      )}
      {why.judge?.reason && (
        <p className="mt-3 text-xs text-muted">
          <span className="font-medium text-text">Judge: </span>
          {why.judge.reason}
        </p>
      )}
      {!!why.judge?.matched_topics?.length && (
        <p className="mt-1 text-xs text-muted">Matched topics: {why.judge.matched_topics.join(", ")}</p>
      )}
    </details>
  );
}
