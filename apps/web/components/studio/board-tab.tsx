"use client";

import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import Link from "next/link";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Dialog } from "@/components/ui/dialog";
import { get } from "@/lib/api";
import { fmtDateTime, humanize } from "@/lib/labels";
import { PLATFORM_LABEL, textOf, type Board, type ContentIdea } from "@/lib/studio-types";
import { AnglePicker } from "./angles-dialog";

const COLS = [
  { id: "idea", label: "Idea" },
  { id: "drafting", label: "Drafting" },
  { id: "ready", label: "Ready" },
  { id: "scheduled", label: "Scheduled" },
  { id: "published", label: "Published" },
  { id: "measured", label: "Measured" },
] as const;

export function BoardTab() {
  const q = useQuery({ queryKey: ["studio", "board"], queryFn: () => get<Board>("/studio/board") });
  const [idea, setIdea] = useState<ContentIdea | null>(null);
  if (!q.data) return <p className="text-sm text-muted">Loading…</p>;
  return (
    <>
      <div className="-mx-4 overflow-x-auto px-4 pb-2 md:mx-0 md:px-0">
        <div className="grid min-w-[1080px] grid-cols-6 gap-3">
          {COLS.map((c) => {
            const cards = q.data[c.id] ?? [];
            return (
              <section key={c.id} aria-label={c.label} data-testid={`column-${c.id}`} className="min-w-0 rounded-[18px] border border-border bg-sidebar p-2.5">
                <h2 className="mb-2 flex items-center justify-between px-1 font-mono text-[11px] font-medium uppercase tracking-wider text-muted">
                  {c.label}
                  <span className="chip num">{cards.length}</span>
                </h2>
                <ul className="space-y-2">
                  {cards.map((card) =>
                    card.kind === "idea" ? (
                      <li key={card.id}>
                        <button
                          type="button"
                          onClick={() => setIdea(card)}
                          className="block w-full rounded-xl border border-border bg-surface p-3 text-left text-sm shadow-[var(--card-shadow)] transition-colors hover:border-accent"
                        >
                          <Badge tone="accent">{humanize(card.angle_type)}</Badge>
                          <span className="mt-1 line-clamp-3 block">{card.thesis}</span>
                        </button>
                      </li>
                    ) : (
                      <li key={card.id}>
                        <Link
                          href={`/studio/drafts/${card.id}`}
                          data-testid="board-draft"
                          className="block rounded-xl border border-border bg-surface p-3 text-sm shadow-[var(--card-shadow)] transition-colors hover:border-accent"
                        >
                          <span className="flex flex-wrap items-center gap-1">
                            <Badge tone="muted">{PLATFORM_LABEL[card.platform] ?? card.platform}</Badge>
                            {card.post_within_24h && <Badge tone="warn">24 h</Badge>}
                            {card.current?.grade && (
                              <span className={clsx("num text-xs font-semibold", card.current.grade.total >= 8 ? "text-good" : "text-muted")}>
                                {card.current.grade.total.toFixed(1)}
                              </span>
                            )}
                          </span>
                          <span className="mt-1 line-clamp-3 block">
                            {card.idea?.thesis ?? (textOf(card.current).slice(0, 120) || "Waiting for your answers")}
                          </span>
                          {card.scheduled_for && <span className="mt-1 block text-xs text-muted">{fmtDateTime(card.scheduled_for)}</span>}
                        </Link>
                      </li>
                    ),
                  )}
                </ul>
              </section>
            );
          })}
        </div>
      </div>
      <Dialog open={!!idea} onClose={() => setIdea(null)} title="Draft this idea" wide>
        {idea && <AnglePicker ideas={[idea]} onDone={() => setIdea(null)} />}
      </Dialog>
    </>
  );
}
