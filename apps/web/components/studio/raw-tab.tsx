"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Trash2 } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, inputClass } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { Toggle } from "@/components/ui/toggle";
import { del, get, post, put } from "@/lib/api";
import { errMsg } from "@/lib/hooks";
import { fmtDate, humanize } from "@/lib/labels";
import type { RawMaterial } from "@/lib/studio-types";

const KINDS: RawMaterial["kind"][] = ["story", "quote", "number", "failure", "mentor", "opinion"];
const CONF: RawMaterial["confidentiality"][] = ["public", "vague-only", "private"];

type Form = { kind: RawMaterial["kind"]; text: string; people: string; date: string; can_name: boolean; confidentiality: RawMaterial["confidentiality"] };
const EMPTY: Form = { kind: "story", text: "", people: "", date: "", can_name: false, confidentiality: "public" };

export function RawTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["studio", "raw"], queryFn: () => get<RawMaterial[]>("/raw-materials") });
  const [form, setForm] = useState<Form>(EMPTY);
  const [editing, setEditing] = useState<string | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["studio", "raw"] });
  const save = useMutation({
    mutationFn: () => {
      const body = {
        kind: form.kind,
        text: form.text.trim(),
        people: form.people.split(",").map((x) => x.trim()).filter(Boolean),
        date: form.date || null,
        can_name: form.can_name,
        confidentiality: form.confidentiality,
      };
      return editing ? put(`/raw-materials/${editing}`, body) : post("/raw-materials", body);
    },
    onSuccess: () => {
      toast(editing ? "Updated" : "Added to your bank", "good");
      setForm(EMPTY);
      setEditing(null);
      refresh();
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const remove = useMutation({ mutationFn: (id: string) => del(`/raw-materials/${id}`), onSuccess: refresh, onError: (e) => toast(errMsg(e), "bad") });
  const set = (p: Partial<Form>) => setForm((f) => ({ ...f, ...p }));
  return (
    <div className="grid gap-4 md:grid-cols-[1fr_22rem]">
      <div>
        <p className="mb-3 text-sm text-muted">
          Your stories, quotes, numbers and failures — the only source of personal facts in drafts. Private entries are never
          used.
        </p>
        {(q.data ?? []).length === 0 && <p className="text-sm text-muted">Nothing here yet.</p>}
        <ul className="space-y-2" aria-label="Raw materials">
          {(q.data ?? []).map((r) => (
            <li key={r.id} data-testid="raw-material" className="bento p-3">
              <div className="flex items-start justify-between gap-2">
                <p className="min-w-0 whitespace-pre-wrap break-words text-sm">{r.text}</p>
                <div className="flex shrink-0">
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label="Edit"
                    onClick={() => {
                      setEditing(r.id);
                      setForm({ kind: r.kind, text: r.text, people: r.people.join(", "), date: r.date ?? "", can_name: r.can_name, confidentiality: r.confidentiality });
                    }}
                  >
                    <Pencil size={14} aria-hidden />
                  </Button>
                  <Button size="sm" variant="ghost" aria-label="Delete" onClick={() => remove.mutate(r.id)}>
                    <Trash2 size={14} aria-hidden />
                  </Button>
                </div>
              </div>
              <div className="mt-1.5 flex flex-wrap gap-1">
                <Badge tone="accent">{r.kind}</Badge>
                <Badge tone={r.confidentiality === "private" ? "bad" : r.confidentiality === "vague-only" ? "warn" : "muted"}>{r.confidentiality}</Badge>
                {r.can_name && <Badge tone="info">can name</Badge>}
                {r.people.map((p) => (
                  <Badge key={p} tone="muted">
                    {p}
                  </Badge>
                ))}
                {r.date && <Badge tone="muted">{fmtDate(r.date)}</Badge>}
                {r.origin && <Badge tone="muted">{humanize(r.origin)}</Badge>}
              </div>
            </li>
          ))}
        </ul>
      </div>
      <Card>
        <h2 className="mb-3 text-sm font-semibold">{editing ? "Edit entry" : "Add to the bank"}</h2>
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (form.text.trim().length >= 3) save.mutate();
          }}
        >
          <Field label="Kind">
            <select className={inputClass} value={form.kind} onChange={(e) => set({ kind: e.target.value as Form["kind"] })}>
              {KINDS.map((k) => (
                <option key={k}>{k}</option>
              ))}
            </select>
          </Field>
          <Field label="Text">
            <textarea className={inputClass} rows={4} value={form.text} onChange={(e) => set({ text: e.target.value })} required minLength={3} />
          </Field>
          <Field label="People" hint="Comma-separated.">
            <input className={inputClass} value={form.people} onChange={(e) => set({ people: e.target.value })} />
          </Field>
          <Field label="Date">
            <input type="date" className={inputClass} value={form.date} onChange={(e) => set({ date: e.target.value })} />
          </Field>
          <Field label="Confidentiality">
            <select className={inputClass} value={form.confidentiality} onChange={(e) => set({ confidentiality: e.target.value as Form["confidentiality"] })}>
              {CONF.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </Field>
          <Toggle showLabel label="People can be named" checked={form.can_name} onChange={(v) => set({ can_name: v })} />
          <div className="flex gap-2">
            <Button type="submit" variant="primary" disabled={form.text.trim().length < 3 || save.isPending}>
              {editing ? "Save" : "Add"}
            </Button>
            {editing && (
              <Button
                variant="ghost"
                onClick={() => {
                  setEditing(null);
                  setForm(EMPTY);
                }}
              >
                Cancel
              </Button>
            )}
          </div>
        </form>
      </Card>
    </div>
  );
}
