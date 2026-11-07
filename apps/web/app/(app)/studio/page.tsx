"use client";

import { Plus } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { PageTitle } from "@/components/shell";
import { useStartPost } from "@/components/studio/angles-dialog";
import { BoardTab } from "@/components/studio/board-tab";
import { CalendarTab } from "@/components/studio/calendar-tab";
import { CardsTab } from "@/components/studio/cards-tab";
import { RawTab } from "@/components/studio/raw-tab";
import { SeriesTab } from "@/components/studio/series-tab";
import { VoiceTab } from "@/components/studio/voice-tab";
import { Button } from "@/components/ui/button";
import { TabPanel, Tabs } from "@/components/ui/tabs";

const TABS = [
  { id: "pipeline", label: "Pipeline" },
  { id: "calendar", label: "Calendar" },
  { id: "series", label: "Series" },
  { id: "raw", label: "Raw-material bank" },
  { id: "voice", label: "Voice" },
  { id: "cards", label: "Quote & stat cards" },
] as const;
type TabId = (typeof TABS)[number]["id"];

function StudioInner() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const raw = params.get("tab");
  const tab: TabId = TABS.some((t) => t.id === raw) ? (raw as TabId) : "pipeline";
  return (
    <>
      <Tabs label="Studio sections" tabs={[...TABS]} value={tab} onChange={(id) => router.replace(`${pathname}?tab=${id}`, { scroll: false })} />
      <TabPanel id={tab}>
        {tab === "pipeline" && <BoardTab />}
        {tab === "calendar" && <CalendarTab />}
        {tab === "series" && <SeriesTab />}
        {tab === "raw" && <RawTab />}
        {tab === "voice" && <VoiceTab />}
        {tab === "cards" && <CardsTab />}
      </TabPanel>
    </>
  );
}

export default function StudioPage() {
  const start = useStartPost();
  return (
    <div className="mx-auto max-w-7xl">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <PageTitle sub="Angles → drafts → Ready → publish-assist. Never auto-posted.">Studio</PageTitle>
        <Button variant="primary" onClick={() => start({ seed_type: "free_text" })}>
          <Plus size={14} aria-hidden /> New from free text
        </Button>
      </div>
      <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
        <StudioInner />
      </Suspense>
    </div>
  );
}
