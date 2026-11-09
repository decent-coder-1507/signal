"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { inputClass } from "@/components/ui/field";
import { post } from "@/lib/api";
import { CitationList } from "@/components/cited-text";
import { CITE_RE, citationIndex, type CitationRef } from "@/lib/citations";
import { errMsg } from "@/lib/hooks";
import type { Explainer } from "@/lib/lab-types";
import { Markdown } from "@/lib/markdown";

const DEPTHS = [
  { id: "plain", label: "Plain" },
  { id: "engineer", label: "Engineer" },
  { id: "deep", label: "Deep" },
] as const;
export type Depth = (typeof DEPTHS)[number]["id"];
export const isDepth = (v: string | null): v is Depth => DEPTHS.some((d) => d.id === v);

/** Replace citation markers with footnote numbers from the resolved source list; unresolvable ids are dropped. */
function numberCitations(body: string, index: Map<string, CitationRef>): string {
  return body.replace(new RegExp(`\s*${CITE_RE.source}`, "g"), (_m, _r, id: string) => {
    const ref = index.get(id.toLowerCase()) ?? index.get(id);
    return ref ? ` [${ref.n}]` : "";
  });
}

export function ExplainerPanel({
  initialTopic = "",
  initialDepth = "engineer",
  storyId,
}: {
  initialTopic?: string;
  initialDepth?: Depth;
  storyId?: string;
}) {
  const qc = useQueryClient();
  const [topic, setTopic] = useState(initialTopic);
  const [depth, setDepth] = useState<Depth>(initialDepth);
  const gen = useMutation({
    mutationFn: (v: { topic: string; depth: Depth }) =>
      post<Explainer>("/explainers", { topic: v.topic, depth: v.depth, story_id: storyId ?? null }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["gym"] }),
  });
  const auto = useRef(false);
  useEffect(() => {
    if (initialTopic && !auto.current) {
      auto.current = true;
      gen.mutate({ topic: initialTopic, depth: initialDepth });
    }
  }, [initialTopic, initialDepth, gen]);
  const ex = gen.data;
  const index = citationIndex(ex?.sources);
  const run = (d: Depth) => {
    setDepth(d);
    if (topic.trim().length >= 2) gen.mutate({ topic: topic.trim(), depth: d });
  };
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          run(depth);
        }}
      >
        <label className="min-w-0 flex-1 text-sm">
          Topic
          <input className={inputClass} value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="e.g. KV-cache, MCP, speculative decoding" />
        </label>
        <Button type="submit" variant="primary" disabled={topic.trim().length < 2 || gen.isPending}>
          {gen.isPending ? "Explaining…" : "Explain"}
        </Button>
      </form>
      <div role="group" aria-label="Depth" className="flex gap-1">
        {DEPTHS.map((d) => (
          <button
            key={d.id}
            type="button"
            aria-pressed={depth === d.id}
            disabled={gen.isPending}
            onClick={() => run(d.id)}
            className={clsx("min-h-8 rounded-full border px-3 text-xs", depth === d.id ? "border-accent bg-accent/10 text-accent" : "border-border text-muted")}
          >
            {d.label}
          </button>
        ))}
      </div>
      {gen.error && <p role="alert" className="text-sm text-bad">{errMsg(gen.error)}</p>}
      {ex && (
        <Card data-testid="explainer">
          <h2 className="tracking-tight text-xl font-semibold">{ex.topic}</h2>
          <p className="mb-3 text-xs text-muted">{ex.depth} depth</p>
          <Markdown source={numberCitations(ex.body, index)} />
          {index.size > 0 && (
            <div className="mt-3" data-testid="explainer-sources">
              <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">Sources</h3>
              <CitationList index={index} />
            </div>
          )}
          {ex.cards.length > 0 && (
            <p className="mt-3 rounded-md bg-surface-2 px-3 py-2 text-sm" data-testid="explainer-cards">
              {ex.cards.length} flashcard{ex.cards.length > 1 ? "s" : ""} added to your review queue.
            </p>
          )}
        </Card>
      )}
    </div>
  );
}
