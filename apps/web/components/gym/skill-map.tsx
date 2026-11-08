"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { TrendingDown, TrendingUp } from "lucide-react";
import { RadarChart } from "@/components/radar-chart";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { get, put } from "@/lib/api";
import { errMsg } from "@/lib/hooks";
import type { SkillNode } from "@/lib/lab-types";

const avg = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0);

function leaves(n: SkillNode): SkillNode[] {
  return n.children.length ? n.children.flatMap(leaves) : [n];
}

export function SkillMap() {
  const q = useQuery({ queryKey: ["gym", "skills"], queryFn: () => get<SkillNode[]>("/skills") });
  const tree = q.data ?? [];
  if (q.isLoading) return <p className="text-sm text-muted">Loading…</p>;
  const domains = tree.map((d) => ({ name: d.name, cur: avg(leaves(d).map((x) => x.current_level)), tgt: avg(leaves(d).map((x) => x.target_level)) }));
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="min-w-0 space-y-3">
        {tree.map((d) => (
          <Card key={d.id}>
            <h2 className="mb-2 font-serif text-lg font-semibold">{d.name}</h2>
            <ul className="space-y-1">
              {d.children.map((c) => (
                <SkillRow key={c.id} s={c} depth={0} />
              ))}
            </ul>
          </Card>
        ))}
      </div>
      <aside>
        <Card className="sticky top-4">
          <h2 className="mb-2 text-sm font-semibold">Current vs target</h2>
          <RadarChart
            label="Skill radar by domain"
            axes={domains.map((d) => d.name)}
            max={5}
            series={[
              { name: "current", values: domains.map((d) => d.cur), color: "var(--accent)" },
              { name: "target", values: domains.map((d) => d.tgt), color: "var(--info)", dashed: true },
            ]}
          />
        </Card>
      </aside>
    </div>
  );
}

function Level({ value, onChange, label }: { value: number; onChange: (v: number) => void; label: string }) {
  return (
    <select
      aria-label={label}
      value={Math.round(value)}
      onChange={(e) => onChange(Number(e.target.value))}
      className="rounded border border-border bg-surface px-1 py-0.5 text-xs tabular-nums"
    >
      {[0, 1, 2, 3, 4, 5].map((n) => (
        <option key={n} value={n}>
          {n}
        </option>
      ))}
    </select>
  );
}

function SkillRow({ s, depth }: { s: SkillNode; depth: number }) {
  const qc = useQueryClient();
  const toast = useToast();
  const save = useMutation({
    mutationFn: (body: { current_level?: number; target_level?: number }) => put(`/skills/${s.id}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["gym"] });
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const gap = s.target_level - s.current_level;
  return (
    <li>
      <div className="flex flex-wrap items-center gap-2 rounded px-1 py-1 hover:bg-surface-2" style={{ paddingLeft: depth * 16 + 4 }}>
        <span className="min-w-0 flex-1 text-sm">
          {s.name}
          {s.market_trend > 0.1 && <TrendingUp size={12} className="ml-1 inline text-good" aria-label="rising in the news" />}
          {s.market_trend < -0.1 && <TrendingDown size={12} className="ml-1 inline text-muted" aria-label="cooling in the news" />}
        </span>
        <Badge tone={s.durability === "fundamental" ? "good" : s.durability === "evolving" ? "info" : "warn"}>{s.durability}</Badge>
        <span className="flex items-center gap-1 text-xs text-muted">
          now <Level label={`${s.name} current level`} value={s.current_level} onChange={(v) => save.mutate({ current_level: v })} />
          goal <Level label={`${s.name} target level`} value={s.target_level} onChange={(v) => save.mutate({ target_level: v })} />
        </span>
        <span className="w-20 shrink-0" aria-hidden>
          <span className="block h-1.5 overflow-hidden rounded-full bg-surface-2">
            <span className="block h-full rounded-full bg-accent" style={{ width: `${(s.current_level / 5) * 100}%` }} />
          </span>
          {gap > 0 && <span className="block text-right text-[10px] text-muted">gap {gap.toFixed(0)}</span>}
        </span>
      </div>
      {s.children.length > 0 && (
        <ul>
          {s.children.map((c) => (
            <SkillRow key={c.id} s={c} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}
