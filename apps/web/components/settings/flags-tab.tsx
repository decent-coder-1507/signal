"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { Toggle } from "@/components/ui/toggle";
import { get, put } from "@/lib/api";
import { errMsg } from "@/lib/hooks";
import type { Settings } from "@/lib/types";

const GROUPS: Record<string, string> = {
  engine: "Engines",
  adapter: "Source adapters",
  channel: "Channels",
  publish: "Publishing",
  lab: "Lab",
  ai: "AI",
  ask: "Ask",
};

export function FlagsTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["settings"], queryFn: () => get<Settings>("/settings") });
  const save = useMutation({
    mutationFn: (v: { key: string; on: boolean }) => put<Settings>("/settings", { flags: { [v.key]: v.on } }),
    onSuccess: (s, v) => {
      qc.setQueryData(["settings"], s);
      toast(`${v.key} ${v.on ? "on" : "off"}`, "good");
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const flags = q.data?.flags ?? {};
  const grouped: Record<string, [string, boolean][]> = {};
  for (const [k, v] of Object.entries(flags)) {
    const g = k.split(".")[0];
    (grouped[g] ??= []).push([k, v]);
  }
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {Object.entries(grouped).map(([g, items]) => (
        <Card key={g}>
          <h2 className="mb-2 text-sm font-semibold">{GROUPS[g] ?? g}</h2>
          <ul className="space-y-2">
            {items.map(([k, v]) => (
              <li key={k} className="flex items-center justify-between gap-2">
                <span className="min-w-0 break-all font-mono text-xs">{k}</span>
                <Toggle label={k} checked={v} disabled={save.isPending} onChange={(on) => save.mutate({ key: k, on })} />
              </li>
            ))}
          </ul>
        </Card>
      ))}
    </div>
  );
}
