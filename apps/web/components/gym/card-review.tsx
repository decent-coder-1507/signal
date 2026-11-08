"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useEffect, useReducer, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { get, post } from "@/lib/api";
import { RATINGS, reviewKey, reviewReducer, type Rating } from "@/lib/card-review";
import { errMsg } from "@/lib/hooks";
import { isTypingTarget } from "@/lib/keynav";
import type { GymCard } from "@/lib/lab-types";

export function CardsPanel() {
  const q = useQuery({ queryKey: ["gym", "due"], queryFn: () => get<GymCard[]>("/cards/due") });
  const [session, setSession] = useState<GymCard[] | null>(null);
  const due = q.data ?? [];
  if (q.isLoading) return <p className="text-sm text-muted">Loading…</p>;
  return (
    <div className="mx-auto max-w-xl">
      <Card className="text-center">
        {due.length === 0 ? (
          <p className="py-6 text-sm text-muted" data-testid="no-cards">
            No cards due. Come back later — or read an explainer to add some.
          </p>
        ) : (
          <div className="py-4">
            <p className="font-serif text-3xl font-semibold tabular-nums">{due.length}</p>
            <p className="text-sm text-muted">cards due</p>
            <Button className="mt-4" variant="primary" onClick={() => setSession(due)}>
              Start review
            </Button>
            <p className="mt-2 text-xs text-muted">Space to reveal · 1 Again · 2 Hard · 3 Good · 4 Easy</p>
          </div>
        )}
      </Card>
      {session && <ReviewSession cards={session} onClose={() => setSession(null)} />}
    </div>
  );
}

function ReviewSession({ cards, onClose }: { cards: GymCard[]; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [s, dispatch] = useReducer(reviewReducer, { index: 0, revealed: false, reviewed: 0 });
  const [busy, setBusy] = useState(false);
  const [remaining, setRemaining] = useState<number | null>(null);
  const card = cards[s.index];
  const finished = !card || remaining === 0;

  const rate = async (rating: Rating) => {
    if (!card || busy) return;
    setBusy(true);
    try {
      const r = await post<{ remaining_due: number }>(`/cards/${card.id}/review`, { rating });
      setRemaining(r.remaining_due);
      dispatch({ type: "rated" });
    } catch (e) {
      toast(errMsg(e), "bad");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (finished) return;
      const k = reviewKey(e.key, s.revealed, isTypingTarget(e.target));
      if (!k) return;
      e.preventDefault();
      if (k.type === "reveal") dispatch({ type: "reveal" });
      else void rate(k.rating);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  useEffect(() => {
    if (finished) {
      qc.invalidateQueries({ queryKey: ["gym"] });
      qc.invalidateQueries({ queryKey: ["today"] });
    }
  }, [finished, qc]);

  return (
    <div className="fixed inset-0 z-40 flex flex-col bg-bg" role="dialog" aria-modal="true" aria-label="Card review">
      <div className="flex items-center justify-between border-b border-border px-4 py-2 text-sm">
        <span className="tabular-nums text-muted" data-testid="review-progress">
          {Math.min(s.index + 1, cards.length)} / {cards.length}
          {remaining != null && ` · ${remaining} still due`}
        </span>
        <button type="button" aria-label="Close review" onClick={onClose} className="p-1 text-muted hover:text-text">
          <X size={18} aria-hidden />
        </button>
      </div>
      <div className="flex flex-1 items-center justify-center overflow-y-auto p-4">
        {finished ? (
          <div className="text-center">
            <p className="font-serif text-2xl font-semibold">{remaining === 0 || remaining == null ? "No cards due" : "Session done"}</p>
            <p className="mt-1 text-sm text-muted">
              {s.reviewed} reviewed{remaining ? ` · ${remaining} more due — start again from the Cards tab` : ". Today's cards step is complete."}
            </p>
            <Button className="mt-4" variant="primary" onClick={onClose}>
              Close
            </Button>
          </div>
        ) : (
          <div className="w-full max-w-xl" data-testid="review-card">
            <div className="mb-2 flex justify-center gap-1">
              <Badge tone="muted">{card.type}</Badge>
              {card.durability && <Badge tone="muted">{card.durability}</Badge>}
            </div>
            <p className="whitespace-pre-wrap text-center font-serif text-2xl leading-snug">{card.front}</p>
            {s.revealed ? (
              <>
                <hr className="my-6 border-border" />
                <p className="whitespace-pre-wrap text-center text-lg" data-testid="card-back">
                  {card.back}
                </p>
              </>
            ) : (
              <div className="mt-8 flex justify-center">
                <Button variant="primary" onClick={() => dispatch({ type: "reveal" })}>
                  Show answer <kbd className="ml-1 text-xs opacity-70">space</kbd>
                </Button>
              </div>
            )}
          </div>
        )}
      </div>
      {!finished && s.revealed && (
        <div className="grid grid-cols-4 gap-2 border-t border-border p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
          {RATINGS.map((r) => (
            <Button key={r.rating} variant={r.rating === 3 ? "primary" : "secondary"} disabled={busy} onClick={() => rate(r.rating)}>
              {r.label} <kbd className="text-xs opacity-60">{r.key}</kbd>
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}
