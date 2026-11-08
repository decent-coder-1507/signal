"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Send } from "lucide-react";
import { useState } from "react";
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
  telegram_webhook_secret?: string;
  hashnode_publication_id?: string;
};

const CHANNELS = [
  { flag: "channel.telegram", label: "Telegram", note: "Brief summary, instant watches, card mini-sessions, commands." },
  { flag: "channel.email", label: "Email", note: "Daily (optional), weekly and monthly digests." },
  { flag: "channel.push", label: "Web push", note: "Browser notifications from the installed app." },
];

export function ChannelsTab() {
  const q = useQuery({ queryKey: ["settings"], queryFn: () => get<ChannelSettings>("/settings") });
  if (!q.data) return <p className="text-sm text-muted">Loading…</p>;
  return <ChannelsForm s={q.data} />;
}

function randomSecret() {
  const b = new Uint8Array(24);
  crypto.getRandomValues(b);
  return Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
}

function ChannelsForm({ s }: { s: ChannelSettings }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [quietFrom, setQuietFrom] = useState(s.quiet_hours?.[0] ?? "22:30");
  const [quietTo, setQuietTo] = useState(s.quiet_hours?.[1] ?? "07:00");
  const [maxPerDay, setMaxPerDay] = useState(String(s.notifications_max_per_day ?? 4));
  const [secret, setSecret] = useState(s.telegram_webhook_secret ?? "");
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
        <h2 className="mb-3 text-sm font-semibold">Channels</h2>
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
        <p className="mt-3 text-xs text-muted">In-app notifications are always on.</p>
      </Card>

      <Card>
        <h2 className="mb-3 text-sm font-semibold">Notifications</h2>
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
        <h2 className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
          <Send size={16} aria-hidden /> Telegram setup
        </h2>
        <ol className="list-decimal space-y-1.5 pl-5 text-sm">
          <li>
            In Telegram, message <span className="font-medium">@BotFather</span>, send <code className="rounded bg-surface-2 px-1">/newbot</code> and
            copy the bot token.
          </li>
          <li>
            Send any message to your new bot, then get your chat id (for example from{" "}
            <code className="rounded bg-surface-2 px-1">https://api.telegram.org/bot&lt;token&gt;/getUpdates</code>).
          </li>
          <li>
            Put both in <code className="rounded bg-surface-2 px-1">.env</code>:
            <pre className="mt-1 overflow-x-auto rounded-md bg-surface-2 p-2 font-mono text-xs">
              SIGNAL_TELEGRAM_BOT_TOKEN=123456:ABC…{"\n"}SIGNAL_TELEGRAM_CHAT_ID=123456789
            </pre>
          </li>
          <li>
            Local mode (no public HTTPS) uses long polling — run:
            <pre className="mt-1 overflow-x-auto rounded-md bg-surface-2 p-2 font-mono text-xs">uv run python -m signal_core.notify.telegram_poll</pre>
          </li>
          <li>Turn on the Telegram channel above.</li>
        </ol>
        <form
          className="mt-4 flex flex-wrap items-end gap-2 border-t border-border pt-4"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate({ telegram_webhook_secret: secret.trim() });
          }}
        >
          <Field label="Webhook secret (HTTPS deployments only)" hint="Telegram sends it as X-Telegram-Bot-Api-Secret-Token on /telegram/webhook." className="min-w-0 flex-1">
            <input className={inputClass + " font-mono"} value={secret} onChange={(e) => setSecret(e.target.value)} autoComplete="off" />
          </Field>
          <Button onClick={() => setSecret(randomSecret())}>Generate</Button>
          <Button type="submit" variant="primary" disabled={save.isPending}>
            Save secret
          </Button>
        </form>
      </Card>

      <Card className="md:col-span-2">
        <h2 className="mb-2 text-sm font-semibold">Hashnode</h2>
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
