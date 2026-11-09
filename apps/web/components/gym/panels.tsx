"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { RadarChart } from "@/components/radar-chart";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, Metric } from "@/components/ui/card";
import { inputClass } from "@/components/ui/field";
import { get, post } from "@/lib/api";
import { CITE_RE } from "@/lib/citations";
import { errMsg } from "@/lib/hooks";
import { humanize } from "@/lib/labels";
import type { LearnNext, Progress } from "@/lib/lab-types";
import { safeUrl } from "@/lib/safe-url";

/** "why" text cites [story_id] markers → numbered links to the story pages. */
function WhyText({ text, evidence }: { text: string; evidence: { id: string; title: string }[] }) {
  const out: React.ReactNode[] = [];
  let last = 0;
  let k = 0;
  const ids = evidence.map((e) => e.id.toLowerCase());
  for (const m of text.matchAll(new RegExp(CITE_RE.source, "g"))) {
    const at = m.index ?? 0;
    out.push(text.slice(last, at).replace(/\s+$/, ""));
    const id = m[2];
    const n = ids.indexOf(id.toLowerCase());
    const title = evidence[n]?.title ?? "story";
    out.push(
      <sup key={k++} className="cite">
        <Link href={`/stories/${id}`} title={title}>
          [{n >= 0 ? n + 1 : "↗"}]
        </Link>
      </sup>,
    );
    last = at + m[0].length;
  }
  out.push(text.slice(last));
  return <>{out}</>;
}

export function LearnNextPanel({ onExplain }: { onExplain: (topic: string) => void }) {
  const q = useQuery({ queryKey: ["gym", "learn-next"], queryFn: () => get<LearnNext>("/gym/learn-next"), staleTime: 5 * 60_000 });
  if (q.isLoading) return <p className="text-sm text-muted">Working out what to learn next…</p>;
  if (q.error) return <p className="text-sm text-bad">{errMsg(q.error)}</p>;
  const d = q.data!;
  return (
    <div className="space-y-4">
      {d.items.map((it, i) => (
        <Card key={it.skill_id}>
          <div className="flex flex-wrap items-center gap-2">
            <span className="num text-xs font-semibold text-muted">{String(i + 1).padStart(2, "0")}</span>
            <span className="text-[17px] font-semibold tracking-tight">{it.skill}</span>
            {it.plan.time_estimate && <Badge tone="muted">{it.plan.time_estimate}</Badge>}
          </div>
          <p className="mt-1 text-sm">
            <WhyText text={it.why} evidence={it.evidence} />
          </p>
          <dl className="mt-3 space-y-2 text-sm">
            <div>
              <dt className="label">Explainer</dt>
              <dd className="flex flex-wrap items-center gap-2">
                {it.plan.explainer_topic}
                <Button size="sm" onClick={() => onExplain(it.plan.explainer_topic)}>
                  Read explainer
                </Button>
              </dd>
            </div>
            {it.plan.resources.length > 0 && (
              <div>
                <dt className="label">Resources</dt>
                <dd>
                  <ul className="list-disc pl-5">
                    {it.plan.resources.map((r) => (
                      <li key={r.id} className="break-words">
                        {safeUrl(r.url) ? (
                          <a href={safeUrl(r.url)} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2">
                            {r.title}
                          </a>
                        ) : (
                          r.title
                        )}
                      </li>
                    ))}
                  </ul>
                </dd>
              </div>
            )}
            {it.plan.practical && (
              <div>
                <dt className="label">Practical</dt>
                <dd>{it.plan.practical}</dd>
              </div>
            )}
            {it.plan.done_definition && (
              <div>
                <dt className="label">Done when</dt>
                <dd>{it.plan.done_definition}</dd>
              </div>
            )}
            {it.ignore_instead && (
              <div>
                <dt className="label">Skip instead</dt>
                <dd className="text-muted">{it.ignore_instead}</dd>
              </div>
            )}
          </dl>
        </Card>
      ))}
      {d.ignore.length > 0 && (
        <Card>
          <h2 className="card-title">Safe to ignore for now</h2>
          <ul className="mt-1 list-disc pl-5 text-sm text-muted">
            {d.ignore.map((x, i) => (
              <li key={i}>{x}</li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

type Quiz = { id: string; title: string; questions: { card_id: string; question: string; options: string[] }[] };

export function QuizPanel() {
  const [answers, setAnswers] = useState<string[]>([]);
  const make = useMutation({ mutationFn: () => post<Quiz>("/quizzes?n=10"), onSuccess: (q) => setAnswers(q.questions.map(() => "")) });
  const attempt = useMutation({
    mutationFn: () => post<{ score: number; answers: string[] }>(`/quizzes/${make.data!.id}/attempt`, { answers }),
  });
  const qz = make.data;
  const res = attempt.data;
  return (
    <div className="mx-auto max-w-2xl space-y-4">
      {!qz ? (
        <Card className="text-center">
          <p className="text-sm text-muted">Ten questions from your cards — retrieval practice beats re-reading.</p>
          <Button className="mt-3" variant="primary" disabled={make.isPending} onClick={() => make.mutate()}>
            {make.isPending ? "Building quiz…" : "Start a quiz"}
          </Button>
          {make.error && <p className="mt-2 text-sm text-bad">{errMsg(make.error)}</p>}
        </Card>
      ) : qz.questions.length === 0 ? (
        <Card>
          <p className="text-sm text-muted">No cards to quiz on yet. Read an explainer first.</p>
        </Card>
      ) : (
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            attempt.mutate();
          }}
        >
          <h2 className="text-xl font-semibold tracking-tight">{qz.title}</h2>
          {qz.questions.map((q, i) => {
            const right = res && res.answers[i] && answers[i].trim().toLowerCase() === res.answers[i].trim().toLowerCase();
            return (
              <Card key={q.card_id + i}>
                <p className="text-sm font-medium">
                  {i + 1}. {q.question}
                </p>
                {q.options.length > 1 ? (
                  <fieldset className="mt-2 space-y-1">
                    <legend className="sr-only">Options for question {i + 1}</legend>
                    {q.options.map((o) => (
                      <label key={o} className="flex items-start gap-2 text-sm">
                        <input
                          type="radio"
                          name={`q${i}`}
                          disabled={!!res}
                          checked={answers[i] === o}
                          onChange={() => setAnswers((a) => a.map((x, j) => (j === i ? o : x)))}
                        />
                        {o}
                      </label>
                    ))}
                  </fieldset>
                ) : (
                  <input
                    aria-label={`Answer ${i + 1}`}
                    className={inputClass}
                    disabled={!!res}
                    value={answers[i] ?? ""}
                    onChange={(e) => setAnswers((a) => a.map((x, j) => (j === i ? e.target.value : x)))}
                  />
                )}
                {res && (
                  <p className={right ? "mt-2 text-sm text-good" : "mt-2 text-sm text-bad"}>
                    {right ? "Correct" : `Answer: ${res.answers[i]}`}
                  </p>
                )}
              </Card>
            );
          })}
          {res ? (
            <div className="flex items-center gap-3">
              <p className="num text-3xl font-semibold" data-testid="quiz-score">
                {Math.round(res.score * 100)}%
              </p>
              <Button
                onClick={() => {
                  attempt.reset();
                  make.reset();
                }}
              >
                New quiz
              </Button>
            </div>
          ) : (
            <Button type="submit" variant="primary" disabled={attempt.isPending}>
              Submit answers
            </Button>
          )}
        </form>
      )}
    </div>
  );
}

const SPLIT_LABEL: Record<string, string> = { fundamental: "Fundamentals", evolving: "Evolving", "tool-specific": "Tool-specific (churn)" };

export function ProgressPanel() {
  const q = useQuery({ queryKey: ["gym", "progress"], queryFn: () => get<Progress>("/gym/progress") });
  const p = q.data;
  if (!p) return <p className="text-sm text-muted">Loading…</p>;
  const stats: [string, string, string?][] = [
    ["Retention (30 d)", p.retention == null ? "—" : `${Math.round(p.retention * 100)}`, p.retention == null ? undefined : "%"],
    ["Cards reviewed (30 d)", String(p.cards_reviewed_30d)],
    ["Concepts this month", String(p.concepts_this_month)],
    ["Due now", String(p.due_now)],
  ];
  return (
    <div className="grid grid-cols-2 gap-3.5 lg:grid-cols-4">
      <Card invert className="col-span-2 flex flex-col justify-between lg:col-span-1">
        <dl>
          <dt className="text-[12.5px] font-medium text-[var(--invert-muted)]">Learning streak</dt>
          <dd className="num mt-1.5 text-[40px] font-semibold leading-none text-[var(--invert-mark)]">
            {p.learning_streak}
            <span className="ml-1.5 font-sans text-sm font-normal tracking-normal text-[var(--invert-muted)]">
              day{p.learning_streak === 1 ? "" : "s"}
            </span>
          </dd>
        </dl>
        <div className="mt-4 flex h-2.5 items-end gap-1" aria-hidden title="Last 7 days">
          {Array.from({ length: 7 }, (_, i) => (
            <i
              key={i}
              className="flex-1 rounded-[3px]"
              style={{
                height: "100%",
                background: i < Math.min(7, p.learning_streak) ? "var(--invert-mark)" : "var(--invert-track)",
              }}
            />
          ))}
        </div>
      </Card>
      <Card className="col-span-2 lg:col-span-3">
        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {stats.map(([k, v, unit]) => (
            <Metric key={k} label={k} value={v} unit={unit} />
          ))}
        </dl>
      </Card>
      <Card className="col-span-2">
        <h2 className="card-title mb-2">Skill radar</h2>
        <RadarChart
          label="Current vs target by domain"
          axes={p.radar.map((r) => r.domain)}
          max={5}
          series={[
            { name: "current", values: p.radar.map((r) => r.current), color: "var(--accent)" },
            { name: "target", values: p.radar.map((r) => r.target), color: "var(--info)", dashed: true },
          ]}
        />
      </Card>
      <div className="col-span-2">
        <Card data-testid="time-split" className="h-full">
          <h2 className="card-title mb-1">Where your learning goes (this month)</h2>
          <p className="mb-3 text-xs text-muted">Target 50 / 30 / 20 — fundamentals outlast tools.</p>
          <ul className="space-y-3">
            {Object.entries(p.target_split).map(([k, target]) => {
              const actual = p.time_split[k] ?? 0;
              return (
                <li key={k}>
                  <div className="flex justify-between text-sm">
                    <span>{SPLIT_LABEL[k] ?? humanize(k)}</span>
                    <span className="num text-muted">
                      {actual}% <span className="font-sans text-xs tracking-normal">/ target {target}%</span>
                    </span>
                  </div>
                  <div className="relative mt-1 h-2 rounded-full bg-surface-2">
                    <div className="glow h-full rounded-full bg-signal" style={{ width: `${Math.min(100, actual)}%` }} />
                    <div className="absolute top-[-3px] h-[14px] w-0.5 bg-text" style={{ left: `${target}%` }} title={`target ${target}%`} />
                  </div>
                </li>
              );
            })}
          </ul>
        </Card>
      </div>
    </div>
  );
}
