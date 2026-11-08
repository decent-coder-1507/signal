"use client";

import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useReducer, useRef } from "react";
import { Badge } from "@/components/ui/badge";
import { get } from "@/lib/api";
import { initialPalette, isPaletteShortcut, KIND_LABEL, paletteReducer, resultTarget, type SearchResult } from "@/lib/search-palette";

const KINDS = ["", "story", "item", "idea", "note", "explainer", "build_log"];

/** Global ⌘K / Ctrl+K search over stories, articles, ideas, notes, explainers and build logs. */
export function SearchPalette() {
  const [s, dispatch] = useReducer(paletteReducer, initialPalette);
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isPaletteShortcut(e)) {
        e.preventDefault();
        dispatch({ type: "toggle" });
      }
    };
    const onOpen = () => dispatch({ type: "open" });
    window.addEventListener("keydown", onKey);
    window.addEventListener("signal:search", onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("signal:search", onOpen);
    };
  }, []);

  useEffect(() => {
    if (s.open) input.current?.focus();
  }, [s.open]);

  useEffect(() => {
    const q = s.query.trim();
    if (!s.open || q.length < 2) return;
    const ctl = new AbortController();
    const t = setTimeout(() => {
      get<SearchResult[]>(`/search?q=${encodeURIComponent(q)}${s.kind ? `&kind=${s.kind}` : ""}&limit=20`)
        .then((results) => !ctl.signal.aborted && dispatch({ type: "results", results }))
        .catch(() => undefined);
    }, 180);
    return () => {
      ctl.abort();
      clearTimeout(t);
    };
  }, [s.query, s.kind, s.open]);

  const go = (r: SearchResult) => {
    const t = resultTarget(r);
    if (!t) return;
    dispatch({ type: "close" });
    if (t.external) window.open(t.href, "_blank", "noopener,noreferrer");
    else router.push(t.href);
  };

  if (!s.open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 pt-[12vh]" onMouseDown={() => dispatch({ type: "close" })}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Search"
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          e.stopPropagation();
          if (e.key === "Escape") dispatch({ type: "close" });
          else if (e.key === "ArrowDown") {
            e.preventDefault();
            dispatch({ type: "move", delta: 1 });
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            dispatch({ type: "move", delta: -1 });
          } else if (e.key === "Enter" && s.results[s.active]) {
            e.preventDefault();
            go(s.results[s.active]);
          }
        }}
        className="w-full max-w-xl overflow-hidden rounded-xl border border-border bg-surface shadow-2xl"
      >
        <div className="flex items-center gap-2 border-b border-border px-3">
          <Search size={16} className="text-muted" aria-hidden />
          <input
            ref={input}
            role="combobox"
            aria-expanded={s.results.length > 0}
            aria-controls="search-results"
            aria-activedescendant={s.results[s.active] ? `sr-${s.active}` : undefined}
            aria-label="Search everything"
            placeholder="Search stories, notes, ideas…"
            value={s.query}
            onChange={(e) => dispatch({ type: "query", query: e.target.value })}
            className="min-w-0 flex-1 bg-transparent py-3 text-sm outline-none"
          />
          <select
            aria-label="Kind"
            value={s.kind}
            onChange={(e) => dispatch({ type: "kind", kind: e.target.value })}
            className="rounded border border-border bg-surface px-1 py-0.5 text-xs"
          >
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {k ? KIND_LABEL[k] : "All"}
              </option>
            ))}
          </select>
        </div>
        <ul id="search-results" role="listbox" className="max-h-[50vh] overflow-y-auto">
          {s.query.trim().length >= 2 && s.results.length === 0 && <li className="px-3 py-4 text-sm text-muted">No matches yet.</li>}
          {s.results.map((r, i) => (
            <li
              key={`${r.kind}-${r.id}`}
              id={`sr-${i}`}
              role="option"
              aria-selected={i === s.active}
              onMouseEnter={() => dispatch({ type: "move", delta: i - s.active })}
              onClick={() => go(r)}
              className={`cursor-pointer border-b border-border px-3 py-2 last:border-0 ${i === s.active ? "bg-surface-2" : ""}`}
            >
              <div className="flex items-center gap-2">
                <Badge tone="muted">{KIND_LABEL[r.kind] ?? r.kind}</Badge>
                <span className="min-w-0 flex-1 truncate text-sm font-medium">{r.title}</span>
                {r.date && <span className="shrink-0 text-xs text-muted">{r.date}</span>}
              </div>
              {r.snippet && <p className="mt-0.5 line-clamp-2 text-xs text-muted">{r.snippet}</p>}
            </li>
          ))}
        </ul>
        <p className="border-t border-border px-3 py-1.5 text-[11px] text-muted">↑↓ to move · Enter to open · Esc to close</p>
      </div>
    </div>
  );
}

/** Opens the palette from a button (e.g. on mobile, where there is no keyboard shortcut). */
export function openSearch() {
  window.dispatchEvent(new Event("signal:search"));
}
