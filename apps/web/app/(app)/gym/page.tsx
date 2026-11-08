"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { CardsPanel } from "@/components/gym/card-review";
import { ExplainerPanel, isDepth } from "@/components/gym/explainer";
import { LearnNextPanel, ProgressPanel, QuizPanel } from "@/components/gym/panels";
import { SkillMap } from "@/components/gym/skill-map";
import { PageTitle } from "@/components/shell";
import { TabPanel, Tabs } from "@/components/ui/tabs";

const TABS = [
  { id: "map", label: "Skill map" },
  { id: "learn", label: "Learn next" },
  { id: "explain", label: "Explainers" },
  { id: "cards", label: "Cards" },
  { id: "quiz", label: "Quiz" },
  { id: "progress", label: "Progress" },
] as const;
type TabId = (typeof TABS)[number]["id"];

function GymInner() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const raw = params.get("tab");
  const tab: TabId = TABS.some((t) => t.id === raw) ? (raw as TabId) : "map";
  const topic = params.get("topic") ?? "";
  const story = params.get("story") ?? undefined;
  const rawDepth = params.get("depth");
  const depth = isDepth(rawDepth) ? rawDepth : "engineer";
  const go = (id: TabId, extra = "") => router.replace(`${pathname}?tab=${id}${extra}`, { scroll: false });
  return (
    <>
      <Tabs label="Gym sections" tabs={[...TABS]} value={tab} onChange={(id) => go(id)} />
      <TabPanel id={tab}>
        {tab === "map" && <SkillMap />}
        {tab === "learn" && <LearnNextPanel onExplain={(t) => go("explain", `&topic=${encodeURIComponent(t)}`)} />}
        {tab === "explain" && <ExplainerPanel key={`${topic}|${depth}|${story ?? ""}`} initialTopic={topic} initialDepth={depth} storyId={story} />}
        {tab === "cards" && <CardsPanel />}
        {tab === "quiz" && <QuizPanel />}
        {tab === "progress" && <ProgressPanel />}
      </TabPanel>
    </>
  );
}

export default function GymPage() {
  return (
    <div className="mx-auto max-w-6xl">
      <PageTitle sub="Skills that compound: fundamentals first, then what the news says is rising.">Gym</PageTitle>
      <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
        <GymInner />
      </Suspense>
    </div>
  );
}
