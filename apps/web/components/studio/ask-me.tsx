"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, inputClass } from "@/components/ui/field";
import { Toggle } from "@/components/ui/toggle";
import { post } from "@/lib/api";
import { useDraftMutation } from "@/lib/studio-hooks";
import type { Draft } from "@/lib/studio-types";

/** Ask-me (§7.4): personal details only ever come from his own answers, saved to the bank with consent. */
export function AskMe({ draft }: { draft: Draft }) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [save, setSave] = useState(true);
  const [canName, setCanName] = useState(false);
  const submit = useDraftMutation(
    draft.id,
    (skip: boolean) =>
      post<Draft>(`/studio/drafts/${draft.id}/answer`, { answers: skip ? {} : answers, save_to_bank: save, can_name: canName, skip }),
    "Drafting with your answers",
  );
  const filled = draft.pending_questions.some((_, i) => (answers[String(i)] ?? "").trim());
  return (
    <Card className="mx-auto max-w-2xl" data-testid="ask-me">
      <h2 className="font-serif text-xl font-semibold">A few questions first</h2>
      <p className="mt-1 text-sm text-muted">
        This angle needs a real detail from you. SIGNAL never invents personal experience; your answers are the only source
        for it.
      </p>
      <form
        className="mt-4 space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (filled) submit.mutate(false);
        }}
      >
        {draft.pending_questions.map((q, i) => (
          <Field key={i} label={q.question} hint={q.why}>
            <textarea
              className={inputClass}
              rows={3}
              value={answers[String(i)] ?? ""}
              onChange={(e) => setAnswers((a) => ({ ...a, [String(i)]: e.target.value }))}
            />
          </Field>
        ))}
        <div className="space-y-2 rounded-md bg-surface-2 p-3">
          <Toggle showLabel label="Save to my raw-material bank" checked={save} onChange={setSave} />
          <p className="text-xs text-muted">Off: used for this draft only and kept private.</p>
          <Toggle showLabel label="People in it can be named" checked={canName} onChange={setCanName} />
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="submit" variant="primary" disabled={!filled || submit.isPending}>
            {submit.isPending ? "Drafting…" : "Use my answers"}
          </Button>
          <Button variant="ghost" disabled={submit.isPending} onClick={() => submit.mutate(true)}>
            Skip — don&apos;t use personal experience
          </Button>
        </div>
      </form>
    </Card>
  );
}
