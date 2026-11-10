"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowLeft, ArrowRight, Check } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { useMe } from "@/components/shell";
import { Button } from "@/components/ui/button";
import { Field, inputClass } from "@/components/ui/field";
import { Toggle } from "@/components/ui/toggle";
import { ApiError, get, post } from "@/lib/api";
import { fromCron, parseTime, toCron, fmtTime } from "@/lib/cron";
import { errMsg } from "@/lib/hooks";
import type { Brief, Profile, Routine, Settings, Source, TopicEntry, Topics } from "@/lib/types";

// Top-level AI-engineering skills from config/skills.yaml (GET /skills arrives with GYM; static for now).
const SKILLS = [
  "LLM fundamentals",
  "Prompting & context engineering",
  "RAG & retrieval",
  "Embeddings & vector search",
  "Agents & tool use",
  "MCP and protocols",
  "Evals & testing of LLM apps",
  "Guardrails & safety",
  "Structured outputs",
  "Cost/latency optimisation",
  "Fine-tuning & adapters",
  "Inference & serving",
  "Multimodal",
];

const STEP_TITLES = [
  "About you",
  "Topics",
  "Skills",
  "Voice",
  "Baseline",
  "Sources",
  "Schedule",
  "Budget",
] as const;

const RINGS = ["core", "adjacent", "wide"] as const;
type RingSel = (typeof RINGS)[number] | "off";

type TopicRow = TopicEntry & { ring: RingSel };

export default function OnboardingPage() {
  const router = useRouter();
  const me = useMe();
  const authed = !!me.data;
  const profile = useQuery({ queryKey: ["profile"], queryFn: () => get<Profile>("/profile"), enabled: authed });
  const sources = useQuery({ queryKey: ["sources"], queryFn: () => get<Source[]>("/sources"), enabled: authed });
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => get<Settings>("/settings"), enabled: authed });
  const routines = useQuery({ queryKey: ["routines"], queryFn: () => get<Routine[]>("/routines"), enabled: authed });

  useEffect(() => {
    if (me.error instanceof ApiError && me.error.status === 401) router.replace("/login");
  }, [me.error, router]);

  const ready = profile.data && sources.data && settings.data && routines.data;
  return (
    <main className="mx-auto min-h-dvh max-w-2xl px-4 py-8">
      <p className="flex items-center gap-2 text-lg font-bold tracking-tight"><span className="glow h-[22px] w-[22px] rounded-[7px] bg-primary" aria-hidden />Signal</p>
      {ready ? (
        <Wizard profile={profile.data!} sources={sources.data!} settings={settings.data!} routines={routines.data!} />
      ) : profile.error ? (
        <p className="mt-6 text-sm text-bad">{errMsg(profile.error)}</p>
      ) : (
        <p className="mt-6 text-sm text-muted">Loading…</p>
      )}
    </main>
  );
}

function initialTopics(t: Topics): TopicRow[] {
  return RINGS.flatMap((r) => ((t[r] as TopicEntry[] | undefined) ?? []).map((x) => ({ ...x, ring: r as RingSel })));
}

function Wizard({
  profile,
  sources,
  settings,
  routines,
}: {
  profile: Profile;
  sources: Source[];
  settings: Settings;
  routines: Routine[];
}) {
  const router = useRouter();
  const qc = useQueryClient();
  const [step, setStep] = useState(0);
  const [role, setRole] = useState(profile.role ?? "");
  const [goals, setGoals] = useState((profile.goals ?? []).join("\n"));
  const [stack, setStack] = useState((profile.stack ?? []).join(", "));
  const [topics, setTopics] = useState<TopicRow[]>(() => initialTopics(profile.topics ?? {}));
  const [skills, setSkills] = useState<Record<string, number>>({});
  const [voice, setVoice] = useState("");
  const [srcOn, setSrcOn] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(sources.map((s) => [s.id, s.enabled])),
  );
  const daily = routines.find((r) => r.name === "daily_brief");
  const preset = fromCron(daily?.cron ?? "30 7 * * 1-5");
  const [time, setTime] = useState(
    preset.kind === "weekdays" || preset.kind === "daily" ? fmtTime(preset.hour, preset.minute) : "07:30",
  );
  const [days, setDays] = useState<"weekdays" | "daily">(preset.kind === "daily" ? "daily" : "weekdays");
  const [budget, setBudget] = useState(String(settings.budget_monthly_usd ?? 30));
  const [error, setError] = useState<string | null>(null);

  const goalList = goals
    .split("\n")
    .map((g) => g.trim())
    .filter(Boolean);
  const valid = [role.trim().length > 0 && goalList.length > 0, true, true, true, true, true, !!parseTime(time), Number(budget) >= 0];

  const finish = useMutation({
    mutationFn: async () => {
      const t = parseTime(time)!;
      const topicsOut: Topics = { ...profile.topics };
      for (const r of RINGS) {
        topicsOut[r] = topics
          .filter((x) => x.ring === r)
          .map(({ ring: _ring, ...rest }) => {
            void _ring;
            return rest;
          });
      }
      const changed = Object.fromEntries(
        sources.filter((s) => srcOn[s.id] !== s.enabled).map((s) => [s.id, srcOn[s.id]]),
      );
      // Voice calibration: each pasted post becomes an own reference post (separated by a line with ---).
      const refs = voice
        .split(/^\s*---\s*$/m)
        .map((x) => x.trim())
        .filter((x) => x.length >= 20);
      for (const text of refs) await post("/reference-posts", { platform: "linkedin", text, is_own: true });
      await post("/onboarding/complete", {
        role: role.trim(),
        goals: goalList,
        stack: stack
          .split(",")
          .map((x) => x.trim())
          .filter(Boolean),
        topics: topicsOut,
        skills,
        sources_enabled: changed,
        daily_brief_cron: toCron({ kind: days, hour: t.hour, minute: t.minute }),
        budget_monthly_usd: Number(budget) || null,
      });
      return post<Brief>("/briefs/generate", { kind: "daily" });
    },
    onSuccess: (b) => {
      qc.setQueryData(["brief", "latest"], b);
      qc.invalidateQueries({ queryKey: ["me"] });
      qc.invalidateQueries({ queryKey: ["profile"] });
      qc.invalidateQueries({ queryKey: ["today"] });
      router.replace("/brief");
    },
    onError: (e) => setError(errMsg(e)),
  });

  const last = step === STEP_TITLES.length - 1;

  return (
    <div className="mt-6">
      <nav aria-label="Setup progress" className="mb-6">
        <p className="text-xs text-muted">
          Step {step + 1} of {STEP_TITLES.length}
        </p>
        <ol className="mt-2 flex gap-1">
          {STEP_TITLES.map((t, i) => (
            <li
              key={t}
              title={t}
              className={clsx("h-1.5 flex-1 rounded-full", i <= step ? "glow bg-signal" : "bg-border-strong")}
              aria-current={i === step ? "step" : undefined}
            >
              <span className="sr-only">{t}</span>
            </li>
          ))}
        </ol>
      </nav>

      <form
        aria-label={STEP_TITLES[step]}
        className="bento p-5 md:p-7"
        onSubmit={(e) => {
          e.preventDefault();
          if (!valid[step]) return;
          if (last) finish.mutate();
          else setStep(step + 1);
        }}
      >
        <h1 className="text-[26px] font-bold tracking-[-0.025em]">{STEP_TITLES[step]}</h1>

        <div className="mt-4 space-y-4">
          {step === 0 && (
            <>
              <Intro>Tell SIGNAL who it is working for. This shapes “why it matters to you” on every story.</Intro>
              <Field label="Role">
                <input className={inputClass} value={role} onChange={(e) => setRole(e.target.value)} required />
              </Field>
              <Field label="Goals" hint="One per line.">
                <textarea className={inputClass} rows={4} value={goals} onChange={(e) => setGoals(e.target.value)} required />
              </Field>
              <Field label="Stack" hint="Comma-separated, e.g. python, typescript, postgres">
                <input className={inputClass} value={stack} onChange={(e) => setStack(e.target.value)} />
              </Field>
            </>
          )}

          {step === 1 && (
            <>
              <Intro>Core topics lead your brief; adjacent ones appear when they clear a higher bar. Weights tune how much each matters.</Intro>
              <ul className="space-y-2">
                {topics.map((t, i) => (
                  <li key={t.name} className="rounded-xl border border-border bg-surface p-3.5">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-sm font-medium">{t.name}</span>
                      <select
                        aria-label={`${t.name} ring`}
                        value={t.ring}
                        onChange={(e) =>
                          setTopics((xs) => xs.map((x, j) => (j === i ? { ...x, ring: e.target.value as RingSel } : x)))
                        }
                        className="rounded-md border border-border bg-surface px-2 py-1 text-xs"
                      >
                        <option value="core">Core</option>
                        <option value="adjacent">Adjacent</option>
                        <option value="wide">Wide</option>
                        <option value="off">Off</option>
                      </select>
                    </div>
                    <div className="mt-2 flex items-center gap-3">
                      <input
                        type="range"
                        min={0}
                        max={1.5}
                        step={0.05}
                        aria-label={`${t.name} weight`}
                        disabled={t.ring === "off"}
                        value={t.weight}
                        onChange={(e) =>
                          setTopics((xs) => xs.map((x, j) => (j === i ? { ...x, weight: Number(e.target.value) } : x)))
                        }
                        className="min-w-0 flex-1 accent-[var(--accent)]"
                      />
                      <span className="w-10 text-right text-xs tabular-nums text-muted">{t.weight.toFixed(2)}</span>
                    </div>
                  </li>
                ))}
              </ul>
            </>
          )}

          {step === 2 && (
            <>
              <Intro>Rate yourself 0 (new to it) to 5 (could teach it). GYM uses this to pick what to learn next.</Intro>
              <ul className="space-y-2">
                {SKILLS.map((s) => (
                  <li key={s} className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-2">
                    <span className="text-sm">{s}</span>
                    <div role="radiogroup" aria-label={s} className="flex gap-1">
                      {[0, 1, 2, 3, 4, 5].map((n) => (
                        <button
                          key={n}
                          type="button"
                          role="radio"
                          aria-checked={(skills[s] ?? -1) === n}
                          onClick={() => setSkills((m) => ({ ...m, [s]: n }))}
                          className={clsx(
                            "h-8 w-8 rounded-md border text-xs",
                            (skills[s] ?? -1) === n ? "border-accent bg-accent text-accent-contrast" : "border-border",
                          )}
                        >
                          {n}
                        </button>
                      ))}
                    </div>
                  </li>
                ))}
              </ul>
            </>
          )}

          {step === 3 && (
            <>
              <Intro>Paste a few posts you have written that sound like you. STUDIO learns your voice from them.</Intro>
              <Field label="Reference posts" hint="Separate posts with a line containing only ---. Five or more calibrate your voice; add more later in Studio → Voice.">
                <textarea className={inputClass} rows={8} value={voice} onChange={(e) => setVoice(e.target.value)} />
              </Field>
            </>
          )}

          {step === 4 && (
            <Intro>
              Baseline metrics (your last 10 posts) let SIGNAL show whether your content is improving. This step is coming in
              Analytics — skip it for now.
            </Intro>
          )}

          {step === 5 && (
            <>
              <Intro>
                The starter pack is on. Switch off anything you do not want; OPML import and custom feeds live in Settings →
                Sources.
              </Intro>
              <ul className="bento divide-y divide-border overflow-hidden">
                {sources.map((s) => (
                  <li key={s.id} className="flex items-center justify-between gap-3 px-3 py-2">
                    <span className="min-w-0 text-sm">
                      <span className="block truncate">{s.name}</span>
                      <span className="text-xs text-muted">
                        {s.type} · tier {s.tier} · {s.ring}
                      </span>
                    </span>
                    <Toggle
                      label={`Enable ${s.name}`}
                      checked={!!srcOn[s.id]}
                      onChange={(v) => setSrcOn((m) => ({ ...m, [s.id]: v }))}
                    />
                  </li>
                ))}
              </ul>
            </>
          )}

          {step === 6 && (
            <>
              <Intro>When should your daily brief be ready? Times are in your timezone (Asia/Kolkata).</Intro>
              <div className="flex flex-wrap gap-3">
                <Field label="Brief time">
                  <input type="time" className={inputClass} value={time} onChange={(e) => setTime(e.target.value)} required />
                </Field>
                <Field label="Days">
                  <select className={inputClass} value={days} onChange={(e) => setDays(e.target.value as "weekdays" | "daily")}>
                    <option value="weekdays">Weekdays</option>
                    <option value="daily">Every day</option>
                  </select>
                </Field>
              </div>
              <div className="rounded-xl border border-border bg-surface p-3.5 text-sm">
                <p className="font-medium">Channels</p>
                <p className="mt-1 text-muted">The brief always appears here in the app. Turn on browser notifications later in Settings → Channels.</p>
              </div>
            </>
          )}

          {step === 7 && (
            <>
              <Intro>
                SIGNAL runs on your Claude subscription, with no API keys. The budget caps estimated monthly usage. When it is
                reached, SIGNAL falls back to cheaper or deterministic modes.
              </Intro>
              <Field label="Monthly budget (USD)">
                <input
                  type="number"
                  min={0}
                  step={1}
                  className={inputClass + " max-w-40"}
                  value={budget}
                  onChange={(e) => setBudget(e.target.value)}
                />
              </Field>
              <p className="text-sm text-muted">Finishing generates your first brief right away.</p>
            </>
          )}
        </div>

        {error && (
          <p role="alert" className="mt-4 text-sm text-bad">
            {error}
          </p>
        )}

        <div className="sticky bottom-0 mt-8 flex items-center justify-between gap-2 border-t border-border bg-bg py-3">
          <Button variant="ghost" disabled={step === 0 || finish.isPending} onClick={() => setStep(step - 1)}>
            <ArrowLeft size={14} aria-hidden /> Back
          </Button>
          <Button type="submit" variant="primary" disabled={!valid[step] || finish.isPending}>
            {last ? (
              <>
                <Check size={14} aria-hidden /> {finish.isPending ? "Generating your first brief…" : "Finish"}
              </>
            ) : (
              <>
                Next <ArrowRight size={14} aria-hidden />
              </>
            )}
          </Button>
        </div>
      </form>
    </div>
  );
}

function Intro({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted">{children}</p>;
}
