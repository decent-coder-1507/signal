"use client";

import clsx from "clsx";
import { ArrowLeft, Plus, Repeat2, Sparkles, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { AskMe } from "@/components/studio/ask-me";
import { Counters, HighlightEditor } from "@/components/studio/highlight-editor";
import { ScorePanel, SourcesPanel } from "@/components/studio/panels";
import { PublishPanel } from "@/components/studio/publish-panel";
import { ArticlePreview, ReelTable, RenderPanel, SlideEditor } from "@/components/studio/visuals";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { inputClass } from "@/components/ui/field";
import { ApiError, post, put } from "@/lib/api";
import { relocate, type SpanIssue } from "@/lib/highlight";
import { useDraft, useDraftMutation, useDrafts } from "@/lib/studio-hooks";
import { PLATFORM_LABEL, textOf, type Draft } from "@/lib/studio-types";

const REPURPOSE = [
  { id: "x_thread", label: "X thread" },
  { id: "x", label: "X post" },
  { id: "linkedin", label: "LinkedIn" },
  { id: "instagram_carousel", label: "Carousel" },
] as const;

const VISUAL = new Set(["instagram_carousel", "linkedin_carousel", "instagram_reel", "hashnode"]);

export default function DraftPage() {
  const { id } = useParams<{ id: string }>();
  const q = useDraft(id);
  if (q.isLoading) return <p className="text-sm text-muted">Loading draft…</p>;
  if (q.error || !q.data)
    return <p className="text-sm text-bad">{q.error instanceof ApiError && q.error.status === 404 ? "Draft not found." : "Could not load this draft."}</p>;
  const d = q.data;
  return (
    <div className="mx-auto max-w-7xl">
      <Header draft={d} />
      {d.pending_questions.length > 0 || !d.current ? (
        d.pending_questions.length > 0 ? (
          <AskMe draft={d} />
        ) : (
          <p className="text-sm text-muted">No version yet.</p>
        )
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_19rem] xl:grid-cols-[16rem_minmax(0,1fr)_19rem]">
          <aside className="order-3 min-w-0 lg:col-start-2 xl:order-1 xl:col-start-1 xl:row-start-1">
            <SourcesPanel draft={d} />
          </aside>
          <section className="order-1 min-w-0 space-y-4 lg:row-span-2 xl:order-2 xl:col-start-2 xl:row-start-1">
            <Editor key={d.current.id} draft={d} />
            {VISUAL.has(d.platform) && <VisualSection draft={d} />}
            <PublishPanel draft={d} />
          </section>
          <aside className="order-2 min-w-0 lg:col-start-2 lg:row-start-1 xl:order-3 xl:col-start-3">
            <ScoreAside draft={d} />
          </aside>
        </div>
      )}
    </div>
  );
}

function Header({ draft: d }: { draft: Draft }) {
  const all = useDrafts();
  const router = useRouter();
  const root = d.parent_draft_id ?? d.id;
  const siblings = (all.data ?? []).filter(
    (x) => x.id === d.id || x.id === root || x.parent_draft_id === root || x.parent_draft_id === d.id || (!!d.idea && x.idea?.id === d.idea.id),
  );
  const tabs = siblings.length ? siblings : [d];
  const repurpose = useDraftMutation(d.id, (platform: string) => post<Draft>(`/studio/drafts/${d.id}/repurpose`, { platform }));
  return (
    <header className="mb-4">
      <Link href="/studio" className="mb-2 inline-flex items-center gap-1 text-sm text-muted hover:text-text">
        <ArrowLeft size={14} aria-hidden /> Studio
      </Link>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="tracking-tight text-2xl font-semibold">{PLATFORM_LABEL[d.platform] ?? d.platform}</h1>
        {d.current && (
          <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Repurpose">
            <span className="inline-flex items-center gap-1 text-xs text-muted">
              <Repeat2 size={14} aria-hidden /> Repurpose →
            </span>
            {REPURPOSE.filter((r) => r.id !== d.platform).map((r) => (
              <Button
                key={r.id}
                size="sm"
                disabled={repurpose.isPending}
                onClick={() => repurpose.mutate(r.id, { onSuccess: (nd) => router.push(`/studio/drafts/${nd.id}`) })}
              >
                {r.label}
              </Button>
            ))}
          </div>
        )}
      </div>
      {tabs.length > 1 && (
        <nav aria-label="Platform versions" className="mt-3 flex gap-1 overflow-x-auto border-b border-border">
          {tabs.map((t) => (
            <Link
              key={t.id}
              href={`/studio/drafts/${t.id}`}
              aria-current={t.id === d.id ? "page" : undefined}
              className={clsx(
                "-mb-px shrink-0 whitespace-nowrap border-b-2 px-3 py-1.5 text-sm",
                t.id === d.id ? "border-accent font-medium" : "border-transparent text-muted hover:text-text",
              )}
            >
              {PLATFORM_LABEL[t.platform] ?? t.platform}
            </Link>
          ))}
        </nav>
      )}
    </header>
  );
}

function ScoreAside({ draft: d }: { draft: Draft }) {
  const pick = useDraftMutation(d.id, (version_id: string) => put<Draft>(`/studio/drafts/${d.id}`, { version_id }), "Switched version");
  return <ScorePanel draft={d} onPickVersion={(vid) => pick.mutate(vid)} picking={pick.isPending} />;
}

function issuesOf(d: Draft): SpanIssue[] {
  return (d.current?.aitell?.issues ?? []) as SpanIssue[];
}

function Editor({ draft: d }: { draft: Draft }) {
  const v = d.current!;
  const isThread = !!v.thread?.length;
  const original = textOf(v);
  const [body, setBody] = useState(v.body);
  const [posts, setPosts] = useState<string[]>(v.thread ?? []);
  const [comment, setComment] = useState(v.first_comment ?? "");
  const issues = issuesOf(d);
  const dirty = isThread ? posts.join("\n\n") !== original || comment !== v.first_comment : body !== v.body || comment !== v.first_comment;

  const save = useDraftMutation(
    d.id,
    () => put<Draft>(`/studio/drafts/${d.id}`, isThread ? { thread: posts, first_comment: comment } : { body, first_comment: comment }),
    "Saved as a new version",
  );
  const revise = useDraftMutation(d.id, () => post<Draft>(`/studio/drafts/${d.id}/revise`), "Revised");
  const pick = useDraftMutation(d.id, (version_id: string) => put<Draft>(`/studio/drafts/${d.id}`, { version_id }));

  // Latest version per label (A/B) for the quick switcher.
  const byLabel = new Map<string, string>();
  for (const x of [...(d.versions ?? [])].sort((a, b) => a.version - b.version)) byLabel.set(x.label, x.id);
  const listed = issues.filter((i) => i.message);

  return (
    <Card>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h2 className="card-title">Draft</h2>
          <span className="text-xs text-muted">
            v{v.version} · {v.author === "human" ? "your edit" : "AI"}
          </span>
        </div>
        {byLabel.size > 1 && (
          <div role="group" aria-label="Version" className="flex gap-1">
            {[...byLabel.entries()].map(([label, vid]) => (
              <button
                key={label}
                type="button"
                aria-pressed={vid === v.id || v.label === label}
                disabled={pick.isPending}
                onClick={() => vid !== v.id && pick.mutate(vid)}
                className={clsx(
                  "min-h-8 rounded-md border px-2.5 text-xs",
                  v.label === label ? "border-accent bg-accent/10 text-accent" : "border-border text-muted hover:text-text",
                )}
              >
                Version {label}
              </button>
            ))}
          </div>
        )}
      </div>

      {isThread ? (
        <ol className="space-y-2">
          {posts.map((p, i) => (
            <li key={i} data-testid="thread-post">
              <div className="mb-1 flex items-center justify-between text-xs text-muted">
                <span>Post {i + 1}</span>
                <span className="flex items-center gap-2">
                  <span className={p.length > 280 ? "font-semibold text-bad" : ""}>{p.length} / 280</span>
                  {posts.length > 1 && (
                    <button type="button" aria-label={`Remove post ${i + 1}`} onClick={() => setPosts((xs) => xs.filter((_, j) => j !== i))}>
                      <Trash2 size={13} aria-hidden />
                    </button>
                  )}
                </span>
              </div>
              <HighlightEditor
                label={`Post ${i + 1}`}
                minRows={2}
                value={p}
                onChange={(t) => setPosts((xs) => xs.map((x, j) => (j === i ? t : x)))}
                issues={relocate(issues, original, p)}
              />
            </li>
          ))}
          <li>
            <Button size="sm" variant="ghost" onClick={() => setPosts((xs) => [...xs, ""])}>
              <Plus size={14} aria-hidden /> Add post
            </Button>
          </li>
        </ol>
      ) : (
        <HighlightEditor label="Draft text" testId="draft-text" value={body} onChange={setBody} issues={relocate(issues, v.body, body)} />
      )}
      <div className="mt-2">
        <Counters text={isThread ? posts.join("\n\n") : body} limit={d.platform === "x" ? 280 : undefined} />
        {isThread && <p className="mt-0.5 text-xs text-muted">{posts.length} posts (target 4–10)</p>}
      </div>

      {(d.platform === "linkedin" || comment) && (
        <label className="mt-3 block text-xs font-medium">
          First comment (links go here)
          <textarea className={inputClass} rows={2} value={comment} onChange={(e) => setComment(e.target.value)} />
        </label>
      )}

      {listed.length > 0 && (
        <ul className="mt-3 space-y-0.5 text-xs" aria-label="AI-tell issues" data-testid="aitell-issues">
          {listed.map((i, k) => (
            <li key={k} className={i.severity === "error" ? "text-bad" : "text-warn"}>
              {i.severity === "error" ? "●" : "○"} {i.message}
            </li>
          ))}
        </ul>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        <Button variant="primary" disabled={!dirty || save.isPending} onClick={() => save.mutate(undefined)}>
          {save.isPending ? "Saving…" : "Save"}
        </Button>
        <Button disabled={revise.isPending || dirty} onClick={() => revise.mutate(undefined)} title={dirty ? "Save or discard your edits first" : undefined}>
          <Sparkles size={14} aria-hidden /> {revise.isPending ? "Revising…" : "Revise with AI"}
        </Button>
        {dirty && (
          <Button
            variant="ghost"
            onClick={() => {
              setBody(v.body);
              setPosts(v.thread ?? []);
              setComment(v.first_comment ?? "");
            }}
          >
            Discard
          </Button>
        )}
      </div>
    </Card>
  );
}

function VisualSection({ draft: d }: { draft: Draft }) {
  return (
    <div className="space-y-4">
      {(d.platform === "instagram_carousel" || d.platform === "linkedin_carousel") && (
        <Card>
          <h2 className="card-title mb-2">Slides</h2>
          <SlideEditor key={d.current?.id} draft={d} />
        </Card>
      )}
      {d.platform === "instagram_reel" && (
        <Card>
          <h2 className="card-title mb-2">
            Reel script <Badge tone="muted">{d.format}</Badge>
          </h2>
          <ReelTable draft={d} />
        </Card>
      )}
      {d.platform === "hashnode" && (
        <Card>
          <ArticlePreview draft={d} />
        </Card>
      )}
      <RenderPanel draft={d} />
    </div>
  );
}
