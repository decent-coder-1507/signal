"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { BrowserNotifyToggle } from "@/components/in-app";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, inputClass } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { Toggle } from "@/components/ui/toggle";
import { get, put } from "@/lib/api";
import { errMsg } from "@/lib/hooks";
import type { Settings } from "@/lib/types";

type ChannelSettings = Settings & {
  quiet_hours?: [string, string];
  notifications_max_per_day?: number;
  hashnode_publication_id?: string;
};

// Everything happens in the app (ADR-027): in-app notifications are always on, browser notifications are a
// per-device opt-in, email digests are optional.
const CHANNELS = [{ flag: "channel.email", label: "Email", note: "Weekly and monthly review digests (optional)." }];

export function ChannelsTab() {
  const q = useQuery({ queryKey: ["settings"], queryFn: () => get<ChannelSettings>("/settings") });
  if (!q.data) return <p className="text-sm text-muted">Loading…</p>;
  return <ChannelsForm s={q.data} />;
}

function ChannelsForm({ s }: { s: ChannelSettings }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [quietFrom, setQuietFrom] = useState(s.quiet_hours?.[0] ?? "22:30");
  const [quietTo, setQuietTo] = useState(s.quiet_hours?.[1] ?? "07:00");
  const [maxPerDay, setMaxPerDay] = useState(String(s.notifications_max_per_day ?? 4));
  const [hashnode, setHashnode] = useState(s.hashnode_publication_id ?? "");
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => put<ChannelSettings>("/settings", body),
    onSuccess: (r) => {
      qc.setQueryData(["settings"], r);
      toast("Saved", "good");
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card>
        <h2 className="card-title mb-3">Channels</h2>
        <p className="mb-3 text-sm">
          <span className="font-medium">In-app</span>
          <span className="block text-xs text-muted">Always on: the bell, Today and the Brief page.</span>
        </p>
        <div className="mb-3">
          <BrowserNotifyToggle />
        </div>
        <ul className="space-y-3">
          {CHANNELS.map((c) => (
            <li key={c.flag} className="flex items-start justify-between gap-3">
              <span className="min-w-0 text-sm">
                <span className="font-medium">{c.label}</span>
                <span className="block text-xs text-muted">{c.note}</span>
              </span>
              <Toggle label={`Enable ${c.label}`} checked={!!s.flags[c.flag]} onChange={(on) => save.mutate({ flags: { [c.flag]: on } })} />
            </li>
          ))}
        </ul>
      </Card>

      <Card>
        <h2 className="card-title mb-3">Notifications</h2>
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate({ quiet_hours: [quietFrom, quietTo], notifications_max_per_day: Math.max(0, Number(maxPerDay) || 0) });
          }}
        >
          <div className="flex flex-wrap gap-3">
            <Field label="Quiet from">
              <input type="time" className={inputClass} value={quietFrom} onChange={(e) => setQuietFrom(e.target.value)} required />
            </Field>
            <Field label="Quiet until">
              <input type="time" className={inputClass} value={quietTo} onChange={(e) => setQuietTo(e.target.value)} required />
            </Field>
          </div>
          <Field label="Maximum per day" hint="Instant watches count too. Anything over the cap waits for the next brief.">
            <input type="number" min={0} max={20} className={inputClass + " w-24"} value={maxPerDay} onChange={(e) => setMaxPerDay(e.target.value)} />
          </Field>
          <Button type="submit" variant="primary" disabled={save.isPending}>
            Save
          </Button>
        </form>
      </Card>

      <Card className="md:col-span-2">
        <h2 className="card-title mb-2">Hashnode</h2>
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate({ hashnode_publication_id: hashnode.trim() });
          }}
        >
          <Field label="Publication id" hint="Used only when you confirm “Publish to Hashnode” on an approved article (flag publish.hashnode_api)." className="min-w-0 flex-1">
            <input className={inputClass + " font-mono"} value={hashnode} onChange={(e) => setHashnode(e.target.value)} />
          </Field>
          <Button type="submit" variant="primary" disabled={save.isPending}>
            Save
          </Button>
        </form>
      </Card>
    </div>
  );
}
