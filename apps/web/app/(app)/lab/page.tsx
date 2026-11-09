"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Sparkles } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { PageTitle } from "@/components/shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, inputClass } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { get, post } from "@/lib/api";
import { errMsg } from "@/lib/hooks";
import { humanize } from "@/lib/labels";
import { IDEA_STATUSES, IDEA_TYPES, type Idea } from "@/lib/lab-types";

export default function LabPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["lab", "ideas"], queryFn: () => get<Idea[]>("/ideas") });
  const [adding, setAdding] = useState(false);
  const detect = useMutation({
    mutationFn: () => post<Idea[]>("/lab/sparks/detect"),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["lab"] });
      toast(r.length ? `${r.length} new spark${r.length > 1 ? "s" : ""}` : "No new sparks above the threshold", "good");
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const ideas = q.data ?? [];
  return (
    <div className="mx-auto max-w-[96rem]">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <PageTitle sub="Sparks from the news → shortlist → validate → build → ship. Two builds at a time.">Lab</PageTitle>
        <div className="flex gap-2">
          <Button onClick={() => setAdding(true)}>
            <Plus size={14} aria-hidden /> New idea
          </Button>
          <Button variant="primary" disabled={detect.isPending} onClick={() => detect.mutate()}>
            <Sparkles size={14} aria-hidden /> {detect.isPending ? "Detecting…" : "Detect sparks now"}
          </Button>
        </div>
      </div>
      {q.isLoading ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : (
        <div className="-mx-4 overflow-x-auto px-4 pb-2 md:mx-0 md:px-0">
          <div className="grid min-w-[1400px] grid-cols-8 gap-3">
            {IDEA_STATUSES.map((s) => {
              const col = ideas.filter((i) => i.status === s);
              return (
                <section key={s} aria-label={humanize(s)} data-testid={`lab-column-${s}`} className="min-h-48 min-w-0 rounded-[18px] border border-border bg-sidebar p-2.5">
                  <h2 className="mb-2 flex items-center justify-between px-1 font-mono text-[11px] font-medium uppercase tracking-wider text-muted">
                    {humanize(s)} <span className="chip num">{col.length}</span>
                  </h2>
                  <ul className="space-y-2">
                    {col.map((i) => (
                      <li key={i.id}>
                        <Link href={`/lab/${i.id}`} data-testid="idea-card" className="block rounded-xl border border-border bg-surface p-3 text-sm shadow-[var(--card-shadow)] transition-colors hover:border-accent">
                          <span className="flex flex-wrap items-center gap-1">
                            <Badge tone="muted">{humanize(i.type)}</Badge>
                            <span className="num text-xs font-semibold text-accent">{i.lab_score.toFixed(1)}</span>
                          </span>
                          <span className="mt-1.5 block font-semibold leading-snug">{i.title}</span>
                          {i.one_liner && <span className="mt-0.5 line-clamp-2 block text-xs text-muted">{i.one_liner}</span>}
                        </Link>
                      </li>
                    ))}
                  </ul>
                </section>
              );
            })}
          </div>
        </div>
      )}
      {adding && <NewIdea onClose={() => setAdding(false)} />}
    </div>
  );
}

function NewIdea({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [type, setType] = useState<string>("practical");
  const [title, setTitle] = useState("");
  const [oneLiner, setOneLiner] = useState("");
  const [problem, setProblem] = useState("");
  const add = useMutation({
    mutationFn: () => post<Idea>("/ideas", { type, title: title.trim(), one_liner: oneLiner.trim(), problem: problem.trim() }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["lab"] });
      toast("Idea added to the shortlist", "good");
      onClose();
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  return (
    <Dialog open onClose={onClose} title="New idea">
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (title.trim().length >= 3) add.mutate();
        }}
      >
        <Field label="Type">
          <select className={inputClass} value={type} onChange={(e) => setType(e.target.value)}>
            {IDEA_TYPES.map((t) => (
              <option key={t} value={t}>
                {humanize(t)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Title">
          <input className={inputClass} value={title} onChange={(e) => setTitle(e.target.value)} minLength={3} required />
        </Field>
        <Field label="One-liner">
          <input className={inputClass} value={oneLiner} onChange={(e) => setOneLiner(e.target.value)} />
        </Field>
        <Field label="Problem">
          <textarea className={inputClass} rows={3} value={problem} onChange={(e) => setProblem(e.target.value)} />
        </Field>
        <Button type="submit" variant="primary" disabled={title.trim().length < 3 || add.isPending}>
          Add idea
        </Button>
      </form>
    </Dialog>
  );
}
