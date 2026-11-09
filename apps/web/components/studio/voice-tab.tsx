"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Trash2 } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, inputClass } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { del, get, post, put } from "@/lib/api";
import { errMsg } from "@/lib/hooks";
import { fmtDateTime, humanize } from "@/lib/labels";
import type { ReferencePost, Voice } from "@/lib/studio-types";

export const CALIBRATION_MIN = 5;

export function VoiceTab() {
  const voice = useQuery({ queryKey: ["voice"], queryFn: () => get<Voice>("/voice") });
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <ReferencePosts />
      {voice.data ? <VoiceForm key={voice.data.version} v={voice.data} /> : <p className="text-sm text-muted">Loading…</p>}
    </div>
  );
}

function VoiceForm({ v }: { v: Voice }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [banned, setBanned] = useState(v.banned_phrases.join("\n"));
  const [emoji, setEmoji] = useState(v.emoji_set.join(" "));
  const [note, setNote] = useState("");
  const save = useMutation({
    mutationFn: () =>
      put<Voice>("/voice", {
        banned_phrases: banned.split("\n").map((x) => x.trim()).filter(Boolean),
        emoji_set: emoji.split(/\s+/).filter(Boolean),
        note: note.trim() || "edited in Studio",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["voice"] });
      toast("Saved as a new voice version", "good");
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  return (
    <div className="space-y-4">
      <Card>
        <h2 className="card-title mb-2">Voice v{v.version}</h2>
        <dl className="space-y-1 text-xs">
          {Object.entries(v.rules)
            .filter(([k]) => !["banned_patterns", "banned_chars"].includes(k))
            .map(([k, val]) => (
              <div key={k} className="flex gap-2">
                <dt className="w-32 shrink-0 text-muted">{humanize(k)}</dt>
                <dd className="min-w-0 break-words">{typeof val === "string" ? val : JSON.stringify(val)}</dd>
              </div>
            ))}
        </dl>
        <form
          className="mt-4 space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <Field label="Banned phrases" hint="One per line. Drafts containing these are flagged.">
            <textarea className={inputClass} rows={6} value={banned} onChange={(e) => setBanned(e.target.value)} />
          </Field>
          <Field label="Emoji set" hint="Space-separated; the only emoji drafts may use.">
            <input className={inputClass} value={emoji} onChange={(e) => setEmoji(e.target.value)} />
          </Field>
          <Field label="Change note">
            <input className={inputClass} value={note} onChange={(e) => setNote(e.target.value)} placeholder="What changed and why" />
          </Field>
          <Button type="submit" variant="primary" disabled={save.isPending}>
            Save new version
          </Button>
        </form>
      </Card>
      <Card>
        <h2 className="card-title mb-2">History</h2>
        <ol className="space-y-1 text-sm">
          {[...v.history].reverse().map((h) => (
            <li key={h.version} className="flex justify-between gap-2">
              <span>
                v{h.version} {h.note && <span className="text-muted">· {h.note}</span>}
              </span>
              <span className="shrink-0 text-xs text-muted">{fmtDateTime(h.created_at)}</span>
            </li>
          ))}
        </ol>
      </Card>
    </div>
  );
}

function ReferencePosts() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["reference-posts"], queryFn: () => get<ReferencePost[]>("/reference-posts") });
  const [text, setText] = useState("");
  const [platform, setPlatform] = useState("linkedin");
  const refresh = () => qc.invalidateQueries({ queryKey: ["reference-posts"] });
  const add = useMutation({
    mutationFn: () => post<{ own_posts: number; voice_calibrated: boolean }>("/reference-posts", { platform, text: text.trim(), is_own: true }),
    onSuccess: (r) => {
      setText("");
      refresh();
      toast(r.voice_calibrated ? "Voice calibrated" : `${r.own_posts} of ${CALIBRATION_MIN} posts added`, "good");
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const remove = useMutation({ mutationFn: (id: string) => del(`/reference-posts/${id}`), onSuccess: refresh });
  const own = (q.data ?? []).filter((r) => r.is_own).length;
  return (
    <div className="space-y-4">
      {own < CALIBRATION_MIN && (
        <p data-testid="voice-not-calibrated" className="flex items-start gap-2 rounded-md border border-warn/40 bg-warn/10 px-3 py-2 text-sm">
          <AlertTriangle size={16} className="mt-0.5 shrink-0 text-warn" aria-hidden />
          Voice not calibrated — add {CALIBRATION_MIN - own} more of your own posts so drafts sound like you.
        </p>
      )}
      <Card>
        <h2 className="card-title mb-2">Reference posts ({own} yours)</h2>
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (text.trim().length >= 20) add.mutate();
          }}
        >
          <Field label="Paste a post you wrote" hint="At least 20 characters.">
            <textarea className={inputClass} rows={4} value={text} onChange={(e) => setText(e.target.value)} />
          </Field>
          <div className="flex flex-wrap gap-2">
            <select aria-label="Platform" className="min-h-10 rounded-[10px] border border-border-strong bg-surface px-2 text-sm" value={platform} onChange={(e) => setPlatform(e.target.value)}>
              <option value="linkedin">LinkedIn</option>
              <option value="x">X</option>
              <option value="instagram">Instagram</option>
              <option value="hashnode">Hashnode</option>
            </select>
            <Button type="submit" disabled={text.trim().length < 20 || add.isPending}>
              Add post
            </Button>
          </div>
        </form>
        <ul className="mt-3 space-y-2">
          {(q.data ?? []).map((r) => (
            <li key={r.id} className="rounded-md border border-border p-2 text-sm">
              <div className="flex items-start justify-between gap-2">
                <p className="line-clamp-4 min-w-0 whitespace-pre-wrap break-words">{r.text}</p>
                <Button size="sm" variant="ghost" aria-label="Delete reference post" onClick={() => remove.mutate(r.id)}>
                  <Trash2 size={14} aria-hidden />
                </Button>
              </div>
              <div className="mt-1 flex gap-1">
                <Badge tone="muted">{r.platform}</Badge>
                {!r.is_own && <Badge tone="info">inspiration</Badge>}
              </div>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
