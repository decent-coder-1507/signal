"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileDown, ImageIcon } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button, buttonClass } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { inputClass } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { get, post, put } from "@/lib/api";
import { errMsg } from "@/lib/hooks";
import { Markdown } from "@/lib/markdown";
import { safeUrl } from "@/lib/safe-url";
import { useDraftMutation } from "@/lib/studio-hooks";
import { articleOf, reelOf, type Asset, type Draft, type Slide } from "@/lib/studio-types";

/** Same-origin asset URL (session cookie authenticates <img>/<a>); ids only, never external hosts. */
export const assetSrc = (a: Pick<Asset, "id">) => `/api/assets/${encodeURIComponent(a.id)}`;

export function RenderPanel({ draft }: { draft: Draft }) {
  const qc = useQueryClient();
  const toast = useToast();
  const key = ["studio", "assets", draft.id];
  const assets = useQuery({ queryKey: key, queryFn: () => get<Asset[]>(`/studio/drafts/${draft.id}/assets`) });
  const render = useMutation({
    mutationFn: () => post<Asset[]>(`/studio/drafts/${draft.id}/render`),
    onSuccess: (a) => {
      qc.setQueryData(key, a);
      toast(`Rendered ${a.filter((x) => x.kind === "png").length} images`, "good");
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  // Show the latest render only: a render writes PNGs (+ PDF/MD) in one batch.
  const all = assets.data ?? [];
  const pngs = all.filter((a) => a.kind === "png");
  const pdf = [...all].reverse().find((a) => a.kind === "pdf");
  const md = [...all].reverse().find((a) => a.kind === "md");
  const pages = typeof pdf?.meta.pages === "number" ? (pdf.meta.pages as number) : null;
  const latest = pages ? pngs.slice(-pages) : render.data ? render.data.filter((a) => a.kind === "png") : pngs;
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="card-title">Visuals</h2>
        <div className="flex flex-wrap gap-2">
          {pdf && (
            <a className={buttonClass("secondary", "sm")} href={assetSrc(pdf)} download>
              <FileDown size={14} aria-hidden /> PDF
            </a>
          )}
          {md && (
            <a className={buttonClass("secondary", "sm")} href={assetSrc(md)} download>
              <FileDown size={14} aria-hidden /> Markdown
            </a>
          )}
          <Button size="sm" variant="primary" disabled={render.isPending} onClick={() => render.mutate()}>
            <ImageIcon size={14} aria-hidden /> {render.isPending ? "Rendering…" : latest.length ? "Re-render" : "Render"}
          </Button>
        </div>
      </div>
      {render.isPending && <p className="mt-2 text-xs text-muted">Rendering with Chrome — a few seconds per slide.</p>}
      {latest.length > 0 ? (
        <ul className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
          {latest.map((a, i) => (
            <li key={a.id}>
              {/* eslint-disable-next-line @next/next/no-img-element -- authenticated API asset, not optimisable */}
              <img
                data-testid="slide-image"
                src={assetSrc(a)}
                alt={typeof a.meta.alt === "string" && a.meta.alt ? a.meta.alt : `Slide ${i + 1}`}
                className="w-full rounded-md border border-border bg-surface-2"
                loading="lazy"
              />
            </li>
          ))}
        </ul>
      ) : (
        !render.isPending && <p className="mt-2 text-sm text-muted">Not rendered yet.</p>
      )}
    </Card>
  );
}

export function SlideEditor({ draft }: { draft: Draft }) {
  const v = draft.current!;
  const [items, setItems] = useState<Slide[]>(() => (v.slides?.items ?? []).map((s) => ({ ...s })));
  const save = useDraftMutation(draft.id, (slides: Slide[]) => put<Draft>(`/studio/drafts/${draft.id}`, { slides }), "Slides saved — render again to update the images");
  if (!v.slides) return <p className="text-sm text-muted">No slides on this version.</p>;
  const set = (i: number, patch: Partial<Slide>) => setItems((xs) => xs.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  return (
    <div className="space-y-3" data-testid="slide-editor">
      <p className="text-xs text-muted">
        {items.length} slides · template {v.slides.template ?? "default"} · ≤ 30 words per slide
      </p>
      <ol className="space-y-3">
        {items.map((s, i) => {
          const words = `${s.title} ${s.body ?? ""}`.split(/\s+/).filter(Boolean).length;
          return (
            <li key={i} className="bento p-3">
              <div className="flex items-center justify-between text-xs text-muted">
                <span>Slide {i + 1}</span>
                <span className={words > 30 ? "font-semibold text-bad" : ""}>{words} words</span>
              </div>
              <label className="mt-1 block text-xs">
                Title
                <input className={inputClass} value={s.title} onChange={(e) => set(i, { title: e.target.value })} />
              </label>
              <label className="mt-2 block text-xs">
                Body
                <textarea className={inputClass} rows={2} value={s.body ?? ""} onChange={(e) => set(i, { body: e.target.value })} />
              </label>
              {s.code && (
                <pre className="mt-2 overflow-x-auto rounded bg-surface-2 p-2 font-mono text-xs">
                  <code>{s.code}</code>
                </pre>
              )}
              {!!s.steps?.length && (
                <ol className="mt-2 list-decimal pl-5 text-xs text-muted">
                  {s.steps.map((x, k) => (
                    <li key={k}>{x}</li>
                  ))}
                </ol>
              )}
              <label className="mt-2 block text-xs">
                Alt text
                <input className={inputClass} value={s.alt ?? ""} onChange={(e) => set(i, { alt: e.target.value })} />
              </label>
            </li>
          );
        })}
      </ol>
      <Button variant="primary" disabled={save.isPending} onClick={() => save.mutate(items)}>
        Save slides
      </Button>
    </div>
  );
}

const ts = (t: number) => `${Math.floor(t / 60)}:${String(Math.round((t % 60) * 10) / 10).padStart(2, "0")}`;

export function ReelTable({ draft }: { draft: Draft }) {
  const s = reelOf(draft.current);
  if (!s) return <p className="text-sm text-muted">No reel script on this version.</p>;
  const rows = [s.hook, ...s.beats];
  const total = rows[rows.length - 1]?.t_end ?? 0;
  const hookOk = s.hook.t_start === 0 && s.hook.t_end <= 2;
  return (
    <div className="space-y-3" data-testid="reel-script">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge tone={hookOk ? "good" : "bad"}>
          Hook {s.hook.t_start}–{s.hook.t_end}s {hookOk ? "✓" : "too long"}
        </Badge>
        <Badge tone={total >= 30 && total <= 60 ? "good" : "warn"}>Total {total}s</Badge>
        {s.audio_mood && <Badge tone="muted">Audio: {s.audio_mood}</Badge>}
      </div>
      <div className="bento overflow-x-auto">
        <table className="w-full min-w-[560px] text-sm">
          <thead className="text-left font-mono text-[11px] uppercase tracking-wider text-muted">
            <tr>
              <th className="px-2 py-1.5 font-medium">Time</th>
              <th className="px-2 py-1.5 font-medium">Voice-over</th>
              <th className="px-2 py-1.5 font-medium">On-screen text</th>
              <th className="px-2 py-1.5 font-medium">Shot</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((b, i) => (
              <tr key={i} className="border-t border-border align-top">
                <td className="whitespace-nowrap px-2 py-1.5 font-mono text-xs">
                  {ts(b.t_start)}–{ts(b.t_end)}
                  {i === 0 && <span className="ml-1 text-accent">hook</span>}
                </td>
                <td className="px-2 py-1.5">{b.voiceover}</td>
                <td className="px-2 py-1.5 font-medium">{b.on_screen}</td>
                <td className="px-2 py-1.5 text-muted">{b.shot}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {s.cover_text && (
        <p className="text-sm">
          <span className="text-muted">Cover: </span>
          {s.cover_text}
        </p>
      )}
      {s.caption && <p className="whitespace-pre-wrap text-sm">{s.caption}</p>}
      {!!s.hashtags?.length && <p className="text-sm text-info">{s.hashtags.map((h) => (h.startsWith("#") ? h : `#${h}`)).join(" ")}</p>}
    </div>
  );
}

export function ArticlePreview({ draft }: { draft: Draft }) {
  const a = articleOf(draft.current);
  if (!a) return <p className="text-sm text-muted">No article on this version.</p>;
  return (
    <article className="space-y-3" data-testid="article-preview">
      <header>
        <h2 className="tracking-tight text-2xl font-semibold leading-tight">{a.seo_title}</h2>
        {a.subtitle && <p className="text-muted">{a.subtitle}</p>}
        <p className="mt-1 text-xs text-muted">SEO title: {a.seo_title.length} / 70 characters</p>
      </header>
      {a.tldr && (
        <p className="rounded-md border-l-2 border-accent bg-surface-2 p-3 text-sm">
          <strong>TL;DR </strong>
          {a.tldr}
        </p>
      )}
      <Markdown source={a.body_md} />
      {!!a.tags?.length && (
        <div className="flex flex-wrap gap-1">
          {a.tags.map((t) => (
            <Badge key={t} tone="muted">
              {t}
            </Badge>
          ))}
        </div>
      )}
      {!!a.references?.length && (
        <section>
          <h3 className="text-sm font-semibold">References</h3>
          <ol className="mt-1 list-decimal space-y-0.5 pl-5 text-sm">
            {a.references.map((r, i) => {
              const url = typeof r === "string" ? r : r.url;
              const title = typeof r === "string" ? r : (r.title ?? r.url);
              const href = safeUrl(url);
              return (
                <li key={i} className="break-words">
                  {href ? (
                    <a href={href} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2">
                      {title}
                    </a>
                  ) : (
                    title
                  )}
                </li>
              );
            })}
          </ol>
        </section>
      )}
    </article>
  );
}
