"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, CheckCircle2, Copy, ExternalLink, FileDown, Send, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button, buttonClass } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, inputClass } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { get, post } from "@/lib/api";
import { errMsg } from "@/lib/hooks";
import { fmtDateTime } from "@/lib/labels";
import { safeUrl } from "@/lib/safe-url";
import { draftKey, gateReasons, useDraftMutation } from "@/lib/studio-hooks";
import type { Draft } from "@/lib/studio-types";
import type { Settings } from "@/lib/types";

type Assist = { platform: string; text: string; thread: string[] | null; first_comment: string; composer_url: string | null; note: string };

export function PublishPanel({ draft }: { draft: Draft }) {
  const toast = useToast();
  const [blocked, setBlocked] = useState<string[] | null>(null);
  const [reason, setReason] = useState("");
  const [assistOpen, setAssistOpen] = useState(false);
  const [hashnodeOpen, setHashnodeOpen] = useState(false);
  const [when, setWhen] = useState("");
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => get<Settings>("/settings") });

  const approve = useDraftMutation(draft.id, async (override_reason: string | null) => {
    try {
      return await post<Draft>(`/studio/drafts/${draft.id}/approve`, override_reason ? { override_reason } : {});
    } catch (e) {
      const r = gateReasons(e);
      if (r) {
        setBlocked(r);
        throw new Error("Draft can't reach Ready yet — see the reasons");
      }
      throw e;
    }
  });
  const schedule = useDraftMutation(
    draft.id,
    (v: { scheduled_for?: string; evergreen?: boolean }) => post<Draft>(`/studio/drafts/${draft.id}/schedule`, v),
    "Scheduled",
  );

  const s = draft.status;
  const ready = s === "ready" || s === "scheduled";
  return (
    <Card data-testid="publish-panel">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="card-title">Publish</h2>
        <Badge tone={s === "published" ? "good" : ready ? "accent" : "muted"}>{s}</Badge>
        {draft.post_within_24h && <Badge tone="warn">Post within 24 h</Badge>}
        {draft.evergreen && <Badge tone="info">Evergreen</Badge>}
        {draft.scheduled_for && <span className="text-xs text-muted">for {fmtDateTime(draft.scheduled_for)}</span>}
      </div>
      {draft.override?.reason && (
        <p className="mt-2 text-xs text-warn">
          Approved with override: “{draft.override.reason}” ({draft.override.overridden?.length ?? 0} issues)
        </p>
      )}
      {!!draft.current?.gate.length && s === "drafting" && (
        <ul className="mt-2 space-y-0.5 text-xs text-bad" aria-label="Blocking issues">
          {draft.current.gate.map((g, i) => (
            <li key={i}>• {g}</li>
          ))}
        </ul>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        {s === "drafting" && (
          <Button variant="primary" disabled={approve.isPending || !draft.current} onClick={() => approve.mutate(null)}>
            <CheckCircle2 size={14} aria-hidden /> Approve
          </Button>
        )}
        {ready && (
          <Button variant="primary" onClick={() => setAssistOpen(true)}>
            <Send size={14} aria-hidden /> Publish-assist
          </Button>
        )}
        {draft.platform === "hashnode" && (
          <a className={buttonClass("secondary")} href={`/api/studio/drafts/${encodeURIComponent(draft.id)}/export.md`} download>
            <FileDown size={14} aria-hidden /> Markdown
          </a>
        )}
        {draft.platform === "hashnode" && ready && settings.data?.flags["publish.hashnode_api"] && (
          <Button onClick={() => setHashnodeOpen(true)}>Publish to Hashnode</Button>
        )}
      </div>
      {ready && (
        <form
          className="mt-3 flex flex-wrap items-end gap-2 border-t border-border pt-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (when) schedule.mutate({ scheduled_for: new Date(when).toISOString() });
          }}
        >
          <Field label="Schedule for">
            <input type="datetime-local" className={inputClass} value={when} onChange={(e) => setWhen(e.target.value)} />
          </Field>
          <Button type="submit" disabled={!when || schedule.isPending}>
            <CalendarClock size={14} aria-hidden /> Schedule
          </Button>
          {!draft.evergreen && (
            <Button variant="ghost" disabled={schedule.isPending} onClick={() => schedule.mutate({ evergreen: true })}>
              Save as evergreen
            </Button>
          )}
        </form>
      )}

      <Dialog open={!!blocked} onClose={() => setBlocked(null)} title="Not ready yet">
        <p className="text-sm text-muted">These issues block Ready. Fix them, or approve anyway with a recorded reason.</p>
        <ul className="mt-2 space-y-1 text-sm" data-testid="gate-reasons">
          {(blocked ?? []).map((r, i) => (
            <li key={i} className="flex gap-1.5">
              <ShieldAlert size={14} className="mt-0.5 shrink-0 text-bad" aria-hidden />
              {r}
            </li>
          ))}
        </ul>
        <form
          className="mt-4 space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            approve.mutate(reason.trim(), {
              onSuccess: () => {
                setBlocked(null);
                setReason("");
                toast("Approved with override", "good");
              },
            });
          }}
        >
          <Field label="Override reason" hint="At least 5 characters; stored with the draft.">
            <input className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} minLength={5} required />
          </Field>
          <Button type="submit" variant="danger" disabled={reason.trim().length < 5 || approve.isPending}>
            Override with reason
          </Button>
        </form>
      </Dialog>

      {assistOpen && <AssistDialog draft={draft} onClose={() => setAssistOpen(false)} />}
      {hashnodeOpen && <HashnodeDialog draft={draft} onClose={() => setHashnodeOpen(false)} />}
    </Card>
  );
}

async function copy(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function AssistDialog({ draft, onClose }: { draft: Draft; onClose: () => void }) {
  const toast = useToast();
  const qc = useQueryClient();
  const [url, setUrl] = useState("");
  const q = useQuery({ queryKey: ["studio", "assist", draft.id], queryFn: () => get<Assist>(`/studio/drafts/${draft.id}/publish-assist`) });
  const posted = useMutation({
    mutationFn: () => post<{ draft: Draft }>(`/studio/drafts/${draft.id}/published`, { url: url.trim() }),
    onSuccess: (r) => {
      qc.setQueryData(draftKey(draft.id), (old: Draft | undefined) => ({ ...old, ...r.draft, versions: old?.versions }));
      qc.invalidateQueries({ queryKey: ["studio"] });
      toast("Marked as published", "good");
      onClose();
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const a = q.data;
  const composer = safeUrl(a?.composer_url);
  const doCopy = async (t: string, what: string) => toast((await copy(t)) ? `${what} copied` : "Copy failed — select the text manually", "info");
  return (
    <Dialog open onClose={onClose} title="Publish-assist" wide>
      {!a ? (
        <p className="text-sm text-muted">{q.error ? errMsg(q.error) : "Preparing…"}</p>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-muted">{a.note} SIGNAL never posts for you.</p>
          {a.thread?.length ? (
            <ol className="space-y-2" data-testid="assist-text">
              {a.thread.map((p, i) => (
                <li key={i} className="flex items-start gap-2 rounded-md border border-border p-2 text-sm">
                  <span className="min-w-0 flex-1 whitespace-pre-wrap break-words">{p}</span>
                  <Button size="sm" variant="ghost" aria-label={`Copy post ${i + 1}`} onClick={() => doCopy(p, `Post ${i + 1}`)}>
                    <Copy size={14} aria-hidden />
                  </Button>
                </li>
              ))}
            </ol>
          ) : (
            <pre data-testid="assist-text" className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md border border-border p-2 font-sans text-sm">
              {a.text}
            </pre>
          )}
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => doCopy(a.text, "Text")}>
              <Copy size={14} aria-hidden /> Copy text
            </Button>
            {a.first_comment && (
              <Button onClick={() => doCopy(a.first_comment, "First comment")}>
                <Copy size={14} aria-hidden /> Copy first comment
              </Button>
            )}
            {composer && (
              <a className={buttonClass("secondary")} href={composer} target="_blank" rel="noopener noreferrer">
                <ExternalLink size={14} aria-hidden /> Open composer
              </a>
            )}
          </div>
          <form
            className="flex flex-wrap items-end gap-2 border-t border-border pt-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (safeUrl(url.trim())) posted.mutate();
            }}
          >
            <Field label="Posted URL" className="min-w-0 flex-1">
              <input type="url" className={inputClass} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" required />
            </Field>
            <Button type="submit" variant="primary" disabled={!safeUrl(url.trim()) || posted.isPending}>
              Posted
            </Button>
          </form>
        </div>
      )}
    </Dialog>
  );
}

function HashnodeDialog({ draft, onClose }: { draft: Draft; onClose: () => void }) {
  const toast = useToast();
  const qc = useQueryClient();
  const pub = useMutation({
    mutationFn: () => post<{ url?: string }>(`/studio/drafts/${draft.id}/publish-api`, { confirm: true }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["studio"] });
      toast(r.url ? `Published: ${r.url}` : "Published to Hashnode", "good");
      onClose();
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  return (
    <Dialog open onClose={onClose} title="Publish to Hashnode?">
      <p className="text-sm">
        This posts the article to your Hashnode publication <strong>now</strong>, via the API. It is the only place SIGNAL
        posts on your behalf, and only with this confirmation.
      </p>
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="primary" disabled={pub.isPending} onClick={() => pub.mutate()}>
          {pub.isPending ? "Publishing…" : "Yes, publish this article"}
        </Button>
      </div>
    </Dialog>
  );
}
