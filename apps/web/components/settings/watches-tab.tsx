"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Search, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, inputClass } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { Toggle } from "@/components/ui/toggle";
import { del, get, post, put } from "@/lib/api";
import { errMsg } from "@/lib/hooks";
import { fmtDateTime } from "@/lib/labels";
import type { Watch } from "@/lib/types";

type Hit = { story_id: string; title: string; explanation: string; created_at: string };

export function WatchesTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["watches"], queryFn: () => get<Watch[]>("/watches") });
  const refresh = () => qc.invalidateQueries({ queryKey: ["watches"] });
  const [query, setQuery] = useState("");
  const [urgency, setUrgency] = useState<"digest" | "instant">("digest");
  const [open, setOpen] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () => post<Watch>("/watches", { query: query.trim(), urgency }),
    onSuccess: () => {
      toast("Watch created", "good");
      setQuery("");
      refresh();
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const patch = useMutation({
    mutationFn: (v: { id: string; enabled: boolean }) => put(`/watches/${v.id}`, { enabled: v.enabled }),
    onSuccess: refresh,
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const remove = useMutation({
    mutationFn: (id: string) => del(`/watches/${id}`),
    onSuccess: () => {
      toast("Watch deleted");
      refresh();
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const check = useMutation({
    mutationFn: () => post<{ checked: number; hits: number }>("/watches/check"),
    onSuccess: (r) => {
      toast(`Checked ${r.checked} watches: ${r.hits} new hits`, "good");
      refresh();
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });

  return (
    <div className="space-y-4">
      <Card>
        <h2 className="card-title mb-1">New watch</h2>
        <p className="mb-3 text-sm text-muted">
          Describe what you want to hear about in plain words, e.g. “any new MCP spec version”.
        </p>
        <form
          className="space-y-3"
          aria-label="New watch"
          onSubmit={(e) => {
            e.preventDefault();
            if (query.trim().length >= 3) create.mutate();
          }}
        >
          <Field label="Watch for">
            <input className={inputClass} value={query} onChange={(e) => setQuery(e.target.value)} minLength={3} required />
          </Field>
          <fieldset className="flex flex-wrap gap-4 text-sm">
            <legend className="sr-only">Urgency</legend>
            <label className="inline-flex items-center gap-1.5">
              <input type="radio" name="urgency" checked={urgency === "digest"} onChange={() => setUrgency("digest")} />
              Digest (next brief)
            </label>
            <label className="inline-flex items-center gap-1.5">
              <input type="radio" name="urgency" checked={urgency === "instant"} onChange={() => setUrgency("instant")} />
              Instant
            </label>
          </fieldset>
          <Button type="submit" variant="primary" disabled={create.isPending || query.trim().length < 3}>
            <Plus size={14} aria-hidden /> Create watch
          </Button>
        </form>
      </Card>

      <div className="flex items-center justify-between">
        <h2 className="card-title">Your watches</h2>
        <Button size="sm" variant="ghost" disabled={check.isPending} onClick={() => check.mutate()}>
          <Search size={14} aria-hidden /> Check now
        </Button>
      </div>
      {(q.data ?? []).length === 0 && <p className="text-sm text-muted">No watches yet.</p>}
      <ul className="space-y-2" aria-label="Watches">
        {(q.data ?? []).map((w) => (
          <li key={w.id} data-testid="watch" className="bento p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="break-words text-sm font-medium">{w.query}</p>
                <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted">
                  <Badge tone={w.urgency === "instant" ? "accent" : "muted"}>{w.urgency}</Badge>
                  <button type="button" className="underline" onClick={() => setOpen(open === w.id ? null : w.id)}>
                    {w.hits} hit{w.hits === 1 ? "" : "s"}
                  </button>
                  {w.last_triggered && <span>· last {fmtDateTime(w.last_triggered)}</span>}
                </div>
              </div>
              <div className="flex items-center gap-1">
                <Toggle label={`Enable watch ${w.query}`} checked={w.enabled} onChange={(v) => patch.mutate({ id: w.id, enabled: v })} />
                <Button size="sm" variant="ghost" aria-label={`Delete watch ${w.query}`} onClick={() => remove.mutate(w.id)}>
                  <Trash2 size={14} aria-hidden />
                </Button>
              </div>
            </div>
            {open === w.id && <WatchHits id={w.id} />}
          </li>
        ))}
      </ul>
    </div>
  );
}

function WatchHits({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["watch-hits", id], queryFn: () => get<Hit[]>(`/watches/${id}/hits`) });
  if (!q.data) return <p className="mt-2 text-xs text-muted">Loading…</p>;
  if (!q.data.length) return <p className="mt-2 text-xs text-muted">No hits yet.</p>;
  return (
    <ul className="mt-2 space-y-1 border-t border-border pt-2 text-sm">
      {q.data.map((h) => (
        <li key={h.story_id + h.created_at}>
          <Link href={`/stories/${h.story_id}`} className="hover:underline">
            {h.title}
          </Link>
          {h.explanation && <p className="text-xs text-muted">{h.explanation}</p>}
        </li>
      ))}
    </ul>
  );
}
