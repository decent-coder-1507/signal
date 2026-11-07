"use client";

import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { get } from "@/lib/api";
import { diffLines, diffStats } from "@/lib/diff";
import { humanize } from "@/lib/labels";
import { safeUrl } from "@/lib/safe-url";
import { textOf, type Draft, type DraftVersion, type RawMaterial } from "@/lib/studio-types";
import type { StoryDetail } from "@/lib/types";

type SourceInfo = { label: string; title: string; url?: string; mine?: boolean };

/** Left column: angle, sources and claims → source ids ("r:<id>" = your raw material). */
export function SourcesPanel({ draft }: { draft: Draft }) {
  const idea = draft.idea;
  const story = useQuery({
    queryKey: ["story", idea?.seed_id],
    queryFn: () => get<StoryDetail>(`/stories/${idea!.seed_id}`),
    enabled: idea?.seed_type === "story" && !!idea.seed_id,
  });
  const raw = useQuery({ queryKey: ["studio", "raw"], queryFn: () => get<RawMaterial[]>("/raw-materials") });
  const lookup = (id: string): SourceInfo => {
    if (id.startsWith("r:")) {
      const r = raw.data?.find((x) => x.id === id.slice(2));
      return { label: "your raw material", title: r?.text ?? "(raw material)", mine: true };
    }
    if (id.startsWith("log:")) return { label: "build log", title: "Build log", mine: true };
    const t = story.data?.timeline.find((x) => x.item_id === id);
    return t ? { label: `${t.source} · tier ${t.tier}`, title: t.title, url: t.url } : { label: "source", title: id.slice(0, 8) + "…" };
  };
  const claims = draft.current?.claims ?? [];
  const sourceIds = Array.from(new Set(claims.flatMap((c) => c.source_ids)));
  return (
    <div className="space-y-4">
      {idea && (
        <Card>
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">Angle</h2>
          <div className="mt-1 flex flex-wrap gap-1">
            <Badge tone="accent">{humanize(idea.angle_type)}</Badge>
            {idea.risk !== "low" && <Badge tone="warn">{idea.risk} risk</Badge>}
          </div>
          <p className="mt-1.5 text-sm font-medium">{idea.thesis}</p>
          <p className="mt-1 text-xs text-muted">{idea.credibility}</p>
        </Card>
      )}
      <Card>
        <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">Sources</h2>
        {story.data && (
          <ul className="mt-1.5 space-y-1.5 text-sm">
            {story.data.timeline.map((t) => (
              <li key={t.item_id} className="break-words">
                {safeUrl(t.url) ? (
                  <a href={safeUrl(t.url)} target="_blank" rel="noopener noreferrer" className="hover:underline">
                    {t.title}
                  </a>
                ) : (
                  t.title
                )}
                <span className="block text-xs text-muted">
                  {t.source} · tier {t.tier}
                </span>
              </li>
            ))}
          </ul>
        )}
        {!story.data && sourceIds.length === 0 && <p className="mt-1 text-sm text-muted">No external sources.</p>}
      </Card>
      <Card data-testid="claims">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">Claims</h2>
        {claims.length === 0 ? (
          <p className="mt-1 text-sm text-muted">No factual claims.</p>
        ) : (
          <ul className="mt-1.5 space-y-2.5 text-sm">
            {claims.map((c, i) => (
              <li key={i}>
                <p>{c.sentence}</p>
                <div className="mt-0.5 flex flex-wrap gap-1">
                  {c.source_ids.length === 0 && <Badge tone="muted">opinion</Badge>}
                  {c.source_ids.map((s) => {
                    const info = lookup(s);
                    return (
                      <Badge key={s} tone={info.mine ? "info" : "neutral"} title={info.title}>
                        {info.mine ? "your raw material" : info.label}
                      </Badge>
                    );
                  })}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

const VERDICT_TONE = { supported: "good", partially: "warn", unsupported: "bad" } as const;

/** Right column: scorecard, top edits, AI-sounding phrases, fact-check, checks, versions + diff. */
export function ScorePanel({
  draft,
  onPickVersion,
  picking,
}: {
  draft: Draft;
  onPickVersion: (id: string) => void;
  picking: boolean;
}) {
  const v = draft.current;
  if (!v) return null;
  const g = v.grade;
  const fc = v.factcheck;
  const ch = v.checks;
  return (
    <div className="space-y-4">
      <Card data-testid="scorecard">
        <div className="flex items-baseline justify-between">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">Scorecard</h2>
          {g && (
            <span className={clsx("font-serif text-2xl font-semibold tabular-nums", g.total >= 8 ? "text-good" : "text-warn")} data-testid="score-total">
              {g.total.toFixed(1)}
              <span className="text-sm text-muted"> / 10 · target 8</span>
            </span>
          )}
        </div>
        {g ? (
          <dl className="mt-2 space-y-1.5">
            {Object.entries(g.scores).map(([k, s]) => (
              <div key={k} className="text-sm">
                <div className="flex justify-between gap-2">
                  <dt>{k}</dt>
                  <dd className="tabular-nums text-muted">{s.points.toFixed(1)}</dd>
                </div>
                {s.why && <p className="text-xs text-muted">{s.why}</p>}
              </div>
            ))}
          </dl>
        ) : (
          <p className="mt-1 text-sm text-muted">Human edit — not re-graded. Revise to grade again.</p>
        )}
        {g?.verdict && <p className="mt-2 text-xs text-muted">{g.verdict}</p>}
      </Card>
      {!!g?.top_edits.length && (
        <Card>
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">Top edits</h2>
          <ol className="mt-1 list-decimal space-y-1 pl-5 text-sm">
            {g.top_edits.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ol>
        </Card>
      )}
      {!!g?.ai_phrases.length && (
        <Card>
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">Sounds AI-written</h2>
          <div className="mt-1 flex flex-wrap gap-1">
            {g.ai_phrases.map((p) => (
              <Badge key={p} tone="warn">
                {p}
              </Badge>
            ))}
          </div>
        </Card>
      )}
      <Card data-testid="factcheck">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">Fact-check</h2>
        {!fc || (!fc.results.length && !fc.uncited_sentences.length) ? (
          <p className="mt-1 text-sm text-muted">No factual claims to check.</p>
        ) : (
          <ul className="mt-1.5 space-y-2 text-sm">
            {fc.results.map((r, i) => (
              <li key={i}>
                <Badge tone={VERDICT_TONE[r.verdict]}>{r.verdict}</Badge>
                <p className="mt-0.5">{r.sentence}</p>
                {r.evidence_span && <p className="mt-0.5 border-l-2 border-border pl-2 text-xs text-muted">“{r.evidence_span}”</p>}
                {r.fix_suggestion && <p className="text-xs text-muted">Fix: {r.fix_suggestion}</p>}
              </li>
            ))}
            {fc.uncited_sentences.map((s, i) => (
              <li key={`u${i}`}>
                <Badge tone="bad">no source</Badge>
                <p className="mt-0.5">{s}</p>
              </li>
            ))}
          </ul>
        )}
      </Card>
      {ch && (
        <Card>
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">Checks</h2>
          <dl className="mt-1.5 space-y-2 text-sm">
            <div>
              <dt className="font-medium">Originality</dt>
              <dd className="text-xs text-muted">
                Closest past post: {((ch.originality?.max_similarity_to_own ?? 0) * 100).toFixed(0)}% similar
                {(ch.originality?.flags ?? []).map((f, i) => (
                  <span key={i} className={clsx("block", f.severity === "error" ? "text-bad" : "text-warn")}>
                    {f.message}
                  </span>
                ))}
              </dd>
            </div>
            <div>
              <dt className="font-medium">Safety</dt>
              <dd className="text-xs text-muted">
                {(ch.safety?.flags ?? []).length === 0
                  ? "No flags"
                  : ch.safety!.flags.map((f, i) => (
                      <span key={i} className={clsx("block", f.severity === "high" ? "text-bad" : "text-warn")}>
                        {humanize(f.type)} ({f.severity}): {f.text}
                      </span>
                    ))}
              </dd>
            </div>
            <div>
              <dt className="font-medium">Attribution</dt>
              <dd className="text-xs text-muted">{(ch.attribution ?? []).length ? ch.attribution!.join(" · ") : "—"}</dd>
            </div>
          </dl>
        </Card>
      )}
      <Versions draft={draft} onPick={onPickVersion} picking={picking} />
    </div>
  );
}

function Versions({ draft, onPick, picking }: { draft: Draft; onPick: (id: string) => void; picking: boolean }) {
  const [open, setOpen] = useState<string | null>(null);
  const vs = [...(draft.versions ?? [])].sort((a, b) => b.version - a.version);
  if (!vs.length) return null;
  const prevOf = (v: DraftVersion) => vs.find((x) => x.version < v.version);
  return (
    <Card>
      <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">Versions</h2>
      <ul className="mt-1.5 space-y-1.5 text-sm">
        {vs.map((v) => {
          const prev = prevOf(v);
          const ops = prev ? diffLines(textOf(prev), textOf(v)) : null;
          const st = ops ? diffStats(ops) : null;
          const current = draft.current?.id === v.id;
          return (
            <li key={v.id} className="rounded-md border border-border p-2">
              <div className="flex flex-wrap items-center justify-between gap-1">
                <span>
                  v{v.version} · {v.label} · {v.author}
                  {v.grade && <span className="text-muted"> · {v.grade.total.toFixed(1)}</span>}
                </span>
                <span className="flex gap-2 text-xs">
                  {st && (
                    <button type="button" className="text-muted underline" onClick={() => setOpen(open === v.id ? null : v.id)}>
                      +{st.added} −{st.removed}
                    </button>
                  )}
                  {current ? (
                    <span className="text-accent">current</span>
                  ) : (
                    <button type="button" className="underline" disabled={picking} onClick={() => onPick(v.id)}>
                      use
                    </button>
                  )}
                </span>
              </div>
              {open === v.id && ops && (
                <pre className="mt-1.5 max-h-60 overflow-auto whitespace-pre-wrap break-words rounded bg-surface-2 p-2 font-mono text-[11px]" data-testid="diff">
                  {ops.map((o, i) => (
                    <div key={i} className={o.op === "add" ? "text-good" : o.op === "del" ? "text-bad line-through" : "text-muted"}>
                      {o.op === "add" ? "+ " : o.op === "del" ? "− " : "  "}
                      {o.text}
                    </div>
                  ))}
                </pre>
              )}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
