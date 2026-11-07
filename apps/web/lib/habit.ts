import type { Today } from "./types";

/** Daily progress (§10.2): brief triaged → 1 action → cards reviewed (no cards due counts as done). */
export function habitProgress(t: Pick<Today, "habit" | "cards_due">) {
  const s = t.habit.steps ?? {};
  const done = {
    brief: !!s.brief,
    action: !!s.action,
    cards: !!s.cards || t.cards_due === 0,
  };
  return { done, count: Object.values(done).filter(Boolean).length };
}
