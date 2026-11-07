"use client";

import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { inputClass } from "@/components/ui/field";
import { RING } from "@/lib/labels";
import type { Profile, TopicEntry, Topics } from "@/lib/types";
import { useProfile, useSaveProfile } from "./profile-tab";

const RINGS = ["core", "adjacent", "wide"] as const;
type R = (typeof RINGS)[number];

export function TopicsTab() {
  const q = useProfile();
  if (!q.data) return <p className="text-sm text-muted">Loading…</p>;
  return <TopicsForm key={q.data.version} p={q.data} />;
}

function TopicsForm({ p }: { p: Profile }) {
  const save = useSaveProfile();
  const [topics, setTopics] = useState<Record<R, TopicEntry[]>>(() => ({
    core: [...((p.topics.core as TopicEntry[]) ?? [])],
    adjacent: [...((p.topics.adjacent as TopicEntry[]) ?? [])],
    wide: [...((p.topics.wide as TopicEntry[]) ?? [])],
  }));
  const [newName, setNewName] = useState("");
  const [newRing, setNewRing] = useState<R>("core");

  const update = (r: R, i: number, patch: Partial<TopicEntry>) =>
    setTopics((t) => ({ ...t, [r]: t[r].map((x, j) => (j === i ? { ...x, ...patch } : x)) }));
  const move = (r: R, i: number, to: R) =>
    setTopics((t) => ({ ...t, [r]: t[r].filter((_, j) => j !== i), [to]: [...t[to], t[r][i]] }));
  const remove = (r: R, i: number) => setTopics((t) => ({ ...t, [r]: t[r].filter((_, j) => j !== i) }));

  return (
    <div className="space-y-4">
      {RINGS.map((r) => (
        <Card key={r}>
          <h2 className="mb-2 text-sm font-semibold">{RING[r]}</h2>
          {topics[r].length === 0 && <p className="text-sm text-muted">No topics.</p>}
          <ul className="space-y-3">
            {topics[r].map((t, i) => (
              <li key={t.name} className="grid gap-2 sm:grid-cols-[12rem_1fr_auto] sm:items-center">
                <span className="min-w-0 truncate text-sm font-medium" title={(t.keywords ?? []).join(", ")}>
                  {t.name}
                </span>
                <div className="flex items-center gap-2">
                  <input
                    type="range"
                    min={0}
                    max={2}
                    step={0.05}
                    value={t.weight}
                    aria-label={`${t.name} weight`}
                    onChange={(e) => update(r, i, { weight: Number(e.target.value) })}
                    className="min-w-0 flex-1 accent-[var(--accent)]"
                  />
                  <span className="w-10 text-right text-xs tabular-nums text-muted">{t.weight.toFixed(2)}</span>
                </div>
                <div className="flex items-center gap-1">
                  <select
                    aria-label={`${t.name} ring`}
                    value={r}
                    onChange={(e) => move(r, i, e.target.value as R)}
                    className="rounded-md border border-border bg-surface px-2 py-1 text-xs"
                  >
                    {RINGS.map((x) => (
                      <option key={x} value={x}>
                        {RING[x]}
                      </option>
                    ))}
                  </select>
                  <Button size="sm" variant="ghost" aria-label={`Remove ${t.name}`} onClick={() => remove(r, i)}>
                    <Trash2 size={14} aria-hidden />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      ))}
      <Card>
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const name = newName.trim().toLowerCase().replace(/\s+/g, "-");
            if (!name) return;
            setTopics((t) => ({ ...t, [newRing]: [...t[newRing], { name, weight: 0.5, keywords: [newName.trim()] }] }));
            setNewName("");
          }}
        >
          <label className="min-w-0 flex-1 text-sm">
            New topic
            <input className={inputClass} value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="e.g. robotics" />
          </label>
          <select
            aria-label="Ring for new topic"
            value={newRing}
            onChange={(e) => setNewRing(e.target.value as R)}
            className="min-h-10 rounded-md border border-border bg-surface px-2 text-sm"
          >
            {RINGS.map((x) => (
              <option key={x} value={x}>
                {RING[x]}
              </option>
            ))}
          </select>
          <Button type="submit">
            <Plus size={14} aria-hidden /> Add
          </Button>
        </form>
      </Card>
      <Button
        variant="primary"
        disabled={save.isPending}
        onClick={() => save.mutate({ topics: { ...p.topics, ...topics } as Topics })}
      >
        Save topics
      </Button>
    </div>
  );
}
