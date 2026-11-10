"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { CostsTab, DeadLettersTab, EvalsTab, HealthTab, LedgerTab, RunsTab, SourceHealthTab } from "@/components/ops/tabs";
import { QualityTab } from "@/components/ops/quality-tab";
import { PageTitle } from "@/components/shell";
import { TabPanel, Tabs } from "@/components/ui/tabs";

const TABS = [
  { id: "health", label: "Health" },
  { id: "runs", label: "Runs" },
  { id: "ledger", label: "LLM ledger" },
  { id: "costs", label: "Costs" },
  { id: "evals", label: "Evals" },
  { id: "quality", label: "Engine quality" },
  { id: "sources", label: "Source health" },
  { id: "dead", label: "Dead letters" },
] as const;
type TabId = (typeof TABS)[number]["id"];

function OpsInner() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const raw = params.get("tab");
  const tab: TabId = TABS.some((t) => t.id === raw) ? (raw as TabId) : "health";
  return (
    <>
      <Tabs label="Ops sections" tabs={[...TABS]} value={tab} onChange={(id) => router.replace(`${pathname}?tab=${id}`, { scroll: false })} />
      <TabPanel id={tab}>
        {tab === "health" && <HealthTab />}
        {tab === "runs" && <RunsTab />}
        {tab === "ledger" && <LedgerTab />}
        {tab === "costs" && <CostsTab />}
        {tab === "evals" && <EvalsTab />}
        {tab === "quality" && <QualityTab />}
        {tab === "sources" && <SourceHealthTab />}
        {tab === "dead" && <DeadLettersTab />}
      </TabPanel>
    </>
  );
}

export default function OpsPage() {
  return (
    <div className="mx-auto max-w-6xl">
      <PageTitle sub="Runs, LLM ledger, costs, evals, engine quality and source health">Ops</PageTitle>
      <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
        <OpsInner />
      </Suspense>
    </div>
  );
}
