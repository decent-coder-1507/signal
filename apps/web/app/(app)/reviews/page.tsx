"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Check, FileDown, RefreshCw } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { DataView } from "@/components/data-view";
import { PageTitle } from "@/components/shell";
import { Badge } from "@/components/ui/badge";
import { Button, buttonClass } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { TabPanel, Tabs } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import { ApiError, get, post } from "@/lib/api";
import { errMsg } from "@/lib/hooks";
import { fmtDate, fmtDateTime } from "@/lib/labels";
import { missingSteps, nextStepIndex, sectionFor, stepTitle, type Review, type ReviewSection } from "@/lib/reviews";

type Kind = "weekly" | "monthly";

function ReviewsInner() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const kind: Kind = params.get("kind") === "monthly" ? "monthly" : "weekly";
  return (
    <>
      <Tabs
        label="Review type"
        tabs={[
          { id: "weekly", label: "Weekly" },
          { id: "monthly", label: "Monthly" },
        ]}
        value={kind}
        onChange={(k) => router.replace(`${pathname}?kind=${k}`, { scroll: false })}
      />
      <TabPanel id={kind}>
        <KindView key={kind} kind={kind} />
      </TabPanel>
    </>
  );
}

export default function ReviewsPage() {
  return (
    <div className="mx-auto max-w-5xl">
      <PageTitle sub="Guided, finishable reviews: a few steps, then you are done.">Reviews</PageTitle>
      <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
        <ReviewsInner />
      </Suspense>
    </div>
  );
}

function KindView({ kind }: { kind: Kind }) {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["reviews", kind], queryFn: () => get<Review | null>(`/reviews/latest?kind=${kind}`) });
  const gen = useMutation({
    mutationFn: () => post<Review>(`/reviews/generate?kind=${kind}`),
    onSuccess: (r) => {
      qc.setQueryData(["reviews", kind], r);
      toast(`${kind === "weekly" ? "Weekly" : "Monthly"} review ready`, "good");
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  if (q.isLoading) return <p className="text-sm text-muted">Loading…</p>;
  const r = q.data;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted">
          {r ? `${fmtDate(r.period_start)} – ${fmtDate(r.period_end)}` : `No ${kind} review yet.`}
          {r?.completed_at && ` · completed ${fmtDateTime(r.completed_at)}`}
        </p>
        <div className="flex gap-2">
          {r && kind === "monthly" && (
            <a className={buttonClass("secondary", "sm")} href={`/api/reviews/${encodeURIComponent(r.id)}/pdf`} download>
              <FileDown size={14} aria-hidden /> PDF
            </a>
          )}
          <Button size="sm" variant={r ? "ghost" : "primary"} disabled={gen.isPending} onClick={() => gen.mutate()}>
            <RefreshCw size={14} aria-hidden /> {gen.isPending ? "Generating…" : r ? "Generate a new one" : `Generate ${kind} review`}
          </Button>
        </div>
      </div>
      {gen.isPending && <p className="text-sm text-muted">Running the {kind} routine — this takes a moment.</p>}
      {r && <Wizard key={r.id} review={r} kind={kind} />}
    </div>
  );
}

function Wizard({ review, kind }: { review: Review; kind: Kind }) {
  const qc = useQueryClient();
  const toast = useToast();
  const c = review.content;
  const [i, setI] = useState(() => nextStepIndex(c));
  const [accept, setAccept] = useState<string[]>([]);
  const step = c.flow[i];
  const section = sectionFor(c, step);
  const done = new Set(c.done_steps);
  const missing = missingSteps(c);
  const setReview = (r: Review) => qc.setQueryData(["reviews", kind], r);

  const mark = useMutation({
    mutationFn: () => post<Review & { angles_created: number }>(`/reviews/${review.id}/step`, { key: step, data: step === "content_plan" ? { accept } : {} }),
    onSuccess: (r) => {
      setReview(r);
      if (r.angles_created) {
        toast(`${r.angles_created} angles added to Studio`, "good");
        qc.invalidateQueries({ queryKey: ["studio"] });
      }
      if (i < c.flow.length - 1) setI(i + 1);
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const complete = useMutation({
    mutationFn: () => post<Review>(`/reviews/${review.id}/complete`),
    onSuccess: (r) => {
      setReview(r);
      qc.invalidateQueries({ queryKey: ["today"] });
      toast("Review complete", "good");
    },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 409) {
        try {
          const d = JSON.parse(e.message) as { missing?: string[] };
          toast(`Still to do: ${(d.missing ?? []).map((s) => stepTitle(s)).join(", ")}`, "bad");
          return;
        } catch {
          /* fall through */
        }
      }
      toast(errMsg(e), "bad");
    },
  });

  if (review.completed_at)
    return (
      <Card data-testid="review-completed" className="text-center">
        <p className="font-serif text-2xl font-semibold">Review completed</p>
        <p className="mt-1 text-sm text-muted">All {c.flow.length} steps done. See you next {kind === "weekly" ? "week" : "month"}.</p>
        <details className="mt-4 text-left">
          <summary className="cursor-pointer text-sm text-muted">Look back at this review</summary>
          <div className="mt-3 space-y-4">
            {c.flow.map((s) => (
              <SectionBody key={s} step={s} section={sectionFor(c, s)} accept={[]} onAccept={() => {}} readOnly />
            ))}
          </div>
        </details>
      </Card>
    );

  return (
    <div className="grid gap-4 md:grid-cols-[14rem_minmax(0,1fr)]">
      <nav aria-label="Review steps">
        <ol className="flex gap-1 overflow-x-auto md:flex-col">
          {c.flow.map((s, k) => (
            <li key={s} className="shrink-0">
              <button
                type="button"
                aria-current={k === i ? "step" : undefined}
                onClick={() => setI(k)}
                className={clsx(
                  "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm",
                  k === i ? "bg-surface-2 font-medium" : "text-muted hover:text-text",
                )}
              >
                <span
                  className={clsx(
                    "inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[10px]",
                    done.has(s) ? "border-good bg-good text-surface" : "border-border",
                  )}
                  aria-label={done.has(s) ? "done" : undefined}
                >
                  {done.has(s) ? <Check size={12} strokeWidth={3} /> : k + 1}
                </span>
                {stepTitle(s, sectionFor(c, s))}
              </button>
            </li>
          ))}
        </ol>
      </nav>
      <Card data-testid="review-step" data-step={step}>
        <div className="mb-3 flex items-baseline justify-between gap-2">
          <h2 className="font-serif text-xl font-semibold">{stepTitle(step, section)}</h2>
          <span className="text-xs text-muted">
            Step {i + 1} of {c.flow.length}
          </span>
        </div>
        <SectionBody
          step={step}
          section={section}
          accept={accept}
          onAccept={(id) => setAccept((xs) => (xs.includes(id) ? xs.filter((x) => x !== id) : [...xs, id]))}
          readOnly={done.has(step)}
        />
        <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-border pt-4">
          {i > 0 && (
            <Button variant="ghost" onClick={() => setI(i - 1)}>
              Back
            </Button>
          )}
          {!done.has(step) ? (
            <Button variant="primary" disabled={mark.isPending} onClick={() => mark.mutate()}>
              <Check size={14} aria-hidden />{" "}
              {step === "content_plan" && accept.length ? `Accept ${accept.length} & mark done` : "Mark done"}
            </Button>
          ) : (
            i < c.flow.length - 1 && (
              <Button onClick={() => setI(i + 1)}>Next</Button>
            )
          )}
          {missing.length === 0 && (
            <Button variant="primary" disabled={complete.isPending} onClick={() => complete.mutate()}>
              Finish review
            </Button>
          )}
          {missing.length > 0 && <span className="text-xs text-muted">{missing.length} step{missing.length > 1 ? "s" : ""} left</span>}
        </div>
      </Card>
    </div>
  );
}

function SectionBody({
  step,
  section,
  accept,
  onAccept,
  readOnly,
}: {
  step: string;
  section?: ReviewSection;
  accept: string[];
  onAccept: (storyId: string) => void;
  readOnly: boolean;
}) {
  if (!section) return <p className="text-sm text-muted">Nothing was generated for this step. You can still mark it done.</p>;
  const proposals = step === "content_plan" ? (section.proposals ?? section.items ?? []) : [];
  return (
    <div className="space-y-3 text-sm">
      {section.text && <p className="whitespace-pre-wrap leading-relaxed">{section.text}</p>}
      {proposals.length > 0 ? (
        <fieldset>
          <legend className="mb-1 font-medium">Proposed posts — tick the ones to start in Studio</legend>
          <ul className="space-y-1.5">
            {proposals.map((p, k) => (
              <li key={k}>
                <label className="flex items-start gap-2" data-testid="content-proposal">
                  <input
                    type="checkbox"
                    disabled={readOnly || !p.story_id}
                    checked={!!p.story_id && accept.includes(p.story_id)}
                    onChange={() => p.story_id && onAccept(p.story_id)}
                    className="mt-1"
                  />
                  <span>
                    {p.platform && <Badge tone="muted">{p.platform}</Badge>}{" "}
                    {p.href?.startsWith("/") ? (
                      <Link href={p.href} className="hover:underline">
                        {p.title}
                      </Link>
                    ) : (
                      p.title
                    )}
                  </span>
                </label>
              </li>
            ))}
          </ul>
        </fieldset>
      ) : (
        !!section.items?.length && (
          <ul className="space-y-1.5">
            {section.items.map((it, k) => (
              <li key={k}>
                {it.href?.startsWith("/") ? (
                  <Link href={it.href} className="font-medium hover:underline">
                    {it.title}
                  </Link>
                ) : (
                  <span className="font-medium">{it.title}</span>
                )}
                {it.sub && <span className="block text-xs text-muted">{it.sub}</span>}
              </li>
            ))}
          </ul>
        )
      )}
      {section.data != null && (
        <div className="rounded-md bg-surface-2 p-3 text-xs">
          <DataView data={section.data} />
        </div>
      )}
    </div>
  );
}
