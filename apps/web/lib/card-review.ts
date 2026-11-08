// Full-screen card review (§9.5): front → reveal (space) → rate Again/Hard/Good/Easy (keys 1–4).

export type Rating = 1 | 2 | 3 | 4;
export type ReviewState = { index: number; revealed: boolean; reviewed: number };
export type ReviewAction = { type: "reveal" } | { type: "rated" } | { type: "reset" };
export type ReviewKey = { type: "reveal" } | { type: "rate"; rating: Rating } | null;

export const RATINGS: { rating: Rating; label: string; key: string }[] = [
  { rating: 1, label: "Again", key: "1" },
  { rating: 2, label: "Hard", key: "2" },
  { rating: 3, label: "Good", key: "3" },
  { rating: 4, label: "Easy", key: "4" },
];

export function reviewReducer(s: ReviewState, a: ReviewAction): ReviewState {
  switch (a.type) {
    case "reveal":
      return { ...s, revealed: true };
    case "rated":
      return { index: s.index + 1, revealed: false, reviewed: s.reviewed + 1 };
    case "reset":
      return { index: 0, revealed: false, reviewed: 0 };
  }
}

/** Space/Enter reveals the back; 1–4 rate only once the back is visible. Typing in fields is ignored. */
export function reviewKey(key: string, revealed: boolean, typing = false): ReviewKey {
  if (typing) return null;
  if (!revealed) return key === " " || key === "Enter" ? { type: "reveal" } : null;
  if (/^[1-4]$/.test(key)) return { type: "rate", rating: Number(key) as Rating };
  return null;
}
