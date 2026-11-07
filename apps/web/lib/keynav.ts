// Keyboard navigation for the brief (§10.2): j/k move focus, u useful, x skip, p post, b build, l learn,
// o/Enter open, ? help. Pure functions so they are unit-testable; the hook lives in components/brief.

export type KeyCommand = "next" | "prev" | "useful" | "skip" | "post" | "build" | "learn" | "open" | "help" | "escape";

export type NavState = { index: number; count: number };
export type NavAction = { type: "next" } | { type: "prev" } | { type: "set"; index: number } | { type: "count"; count: number };

export function navReducer(state: NavState, action: NavAction): NavState {
  switch (action.type) {
    case "next":
      if (state.count === 0) return state;
      return { ...state, index: Math.min(state.count - 1, state.index + 1) };
    case "prev":
      if (state.count === 0) return state;
      return { ...state, index: state.index <= 0 ? 0 : state.index - 1 };
    case "set":
      if (state.count === 0) return { ...state, index: -1 };
      return { ...state, index: Math.max(-1, Math.min(state.count - 1, action.index)) };
    case "count":
      return { count: action.count, index: Math.min(state.index, action.count - 1) };
  }
}

const MAP: Record<string, KeyCommand> = {
  j: "next",
  ArrowDown: "next",
  k: "prev",
  ArrowUp: "prev",
  u: "useful",
  x: "skip",
  p: "post",
  b: "build",
  l: "learn",
  o: "open",
  Enter: "open",
  "?": "help",
  Escape: "escape",
};

export type KeyLike = {
  key: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  altKey?: boolean;
  target?: EventTarget | null;
};

export function isTypingTarget(t: EventTarget | null | undefined): boolean {
  if (!t || typeof t !== "object") return false;
  const el = t as { tagName?: string; isContentEditable?: boolean };
  const tag = (el.tagName ?? "").toUpperCase();
  return el.isContentEditable === true || tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

/** Map a keyboard event to a brief command, or null when it should be left alone. */
export function keyToCommand(e: KeyLike): KeyCommand | null {
  if (e.ctrlKey || e.metaKey || e.altKey) return null;
  if (isTypingTarget(e.target)) return null;
  // Enter on a focused button/link should keep its native behaviour.
  if (e.key === "Enter") {
    const tag = ((e.target as { tagName?: string } | null)?.tagName ?? "").toUpperCase();
    if (tag === "BUTTON" || tag === "A" || tag === "SUMMARY") return null;
  }
  return MAP[e.key] ?? null;
}

export const SHORTCUTS: { keys: string; label: string }[] = [
  { keys: "j / k", label: "Next / previous story" },
  { keys: "u", label: "Useful" },
  { keys: "x", label: "Skip (not for me)" },
  { keys: "p", label: "Post about it" },
  { keys: "b", label: "Build from it" },
  { keys: "l", label: "Learn from it" },
  { keys: "o / Enter", label: "Open story" },
  { keys: "?", label: "Show / hide shortcuts" },
];
