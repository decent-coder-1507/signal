"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, Trash2 } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, inputClass } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { Toggle } from "@/components/ui/toggle";
import { del, get, post, put } from "@/lib/api";
import { describeCron, looksLikeCron, toCron, type CronPreset } from "@/lib/cron";
import { errMsg } from "@/lib/hooks";
import { fmtDateTime, humanize } from "@/lib/labels";
import type { Routine } from "@/lib/types";
import { CronBuilder } from "./cron-builder";

const CHANNELS = ["app", "telegram", "email", "push"] as const;

export function RoutinesTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["routines"], queryFn: () => get<Routine[]>("/routines") });
  const refresh = () => qc.invalidateQueries({ queryKey: ["routines"] });
  const toggle = useMutation({
    mutationFn: (v: { id: string; enabled: boolean }) => put(`/routines/${v.id}`, { enabled: v.enabled }),
    onSuccess: refresh,
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const runNow = useMutation({
    mutationFn: (id: string) => post<{ status: string; name: string }>(`/routines/${id}/run-now`),
    onSuccess: (r) => {
      refresh();
      qc.invalidateQueries({ queryKey: ["brief"] });
      qc.invalidateQueries({ queryKey: ["today"] });
      toast(`${r.name}: ${r.status}`, r.status === "failed" ? "bad" : "good");
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const remove = useMutation({
    mutationFn: (id: string) => del(`/routines/${id}`),
    onSuccess: refresh,
    onError: (e) => toast(errMsg(e), "bad"),
  });

  return (
    <div className="space-y-4">
      <ul className="space-y-2" aria-label="Routines">
        {(q.data ?? []).map((r) => (
          <li key={r.id} data-testid="routine" className="rounded-lg border border-border bg-surface p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="font-mono text-sm font-medium">{r.name}</p>
                <p className="text-xs text-muted">
                  {describeCron(r.cron)} · next {r.next_run_at ? fmtDateTime(r.next_run_at) : "—"}
                  {r.last_run_at && ` · last ${fmtDateTime(r.last_run_at)}`}
                </p>
              </div>
              <div className="flex items-center gap-1">
                <Toggle label={`Enable ${r.name}`} checked={r.enabled} onChange={(v) => toggle.mutate({ id: r.id, enabled: v })} />
                <Button size="sm" variant="ghost" disabled={runNow.isPending} onClick={() => runNow.mutate(r.id)}>
                  <Play size={14} aria-hidden /> Run now
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`Delete ${r.name}`}
                  onClick={() => {
                    if (window.confirm(`Delete routine ${r.name}?`)) remove.mutate(r.id);
                  }}
                >
                  <Trash2 size={14} aria-hidden />
                </Button>
              </div>
            </div>
            <div className="mt-2 flex flex-wrap gap-1">
              {r.steps.map((s) => (
                <Badge key={s} tone="muted">
                  {s}
                </Badge>
              ))}
              {r.channels.map((c) => (
                <Badge key={c} tone="info">
                  {c}
                </Badge>
              ))}
            </div>
          </li>
        ))}
      </ul>
      <NewRoutine onCreated={refresh} />
    </div>
  );
}

function NewRoutine({ onCreated }: { onCreated: () => void }) {
  const toast = useToast();
  const steps = useQuery({ queryKey: ["routine-steps"], queryFn: () => get<string[]>("/routines/steps") });
  const [name, setName] = useState("");
  const [preset, setPreset] = useState<CronPreset>({ kind: "weekly", dow: 0, hour: 9, minute: 0 });
  const [chosen, setChosen] = useState<string[]>([]);
  const [channels, setChannels] = useState<string[]>(["app"]);
  const cron = toCron(preset);
  const create = useMutation({
    mutationFn: () => post<Routine>("/routines", { name: name.trim(), cron, steps: chosen, channels }),
    onSuccess: (r) => {
      toast(`Created ${r.name}`, "good");
      setName("");
      setChosen([]);
      onCreated();
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const flip = (xs: string[], x: string) => (xs.includes(x) ? xs.filter((y) => y !== x) : [...xs, x]);
  return (
    <Card>
      <h2 className="mb-3 text-sm font-semibold">New custom routine</h2>
      <form
        className="space-y-4"
        aria-label="New routine"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <Field label="Name">
          <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. sunday_deep_dive" required />
        </Field>
        <CronBuilder value={preset} onChange={setPreset} />
        <fieldset>
          <legend className="text-sm font-medium">Steps (in order)</legend>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {(steps.data ?? []).map((s) => (
              <label
                key={s}
                className="inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs has-[:checked]:border-accent has-[:checked]:bg-accent/10"
              >
                <input type="checkbox" checked={chosen.includes(s)} onChange={() => setChosen((xs) => flip(xs, s))} />
                {humanize(s)}
              </label>
            ))}
          </div>
          {chosen.length > 0 && <p className="mt-1 text-xs text-muted">Runs: {chosen.join(" → ")}</p>}
        </fieldset>
        <fieldset>
          <legend className="text-sm font-medium">Deliver to</legend>
          <div className="mt-1 flex flex-wrap gap-3 text-sm">
            {CHANNELS.map((c) => (
              <label key={c} className="inline-flex items-center gap-1.5">
                <input type="checkbox" checked={channels.includes(c)} onChange={() => setChannels((xs) => flip(xs, c))} />
                {c}
              </label>
            ))}
          </div>
        </fieldset>
        <Button type="submit" variant="primary" disabled={create.isPending || !name.trim() || !chosen.length || !looksLikeCron(cron)}>
          Create routine
        </Button>
      </form>
    </Card>
  );
}
