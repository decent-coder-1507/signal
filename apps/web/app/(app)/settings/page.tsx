"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { FlagsTab } from "@/components/settings/flags-tab";
import { ProfileTab } from "@/components/settings/profile-tab";
import { RoutinesTab } from "@/components/settings/routines-tab";
import { SecurityTab } from "@/components/settings/security-tab";
import { SourcesTab } from "@/components/settings/sources-tab";
import { TopicsTab } from "@/components/settings/topics-tab";
import { WatchesTab } from "@/components/settings/watches-tab";
import { PageTitle } from "@/components/shell";
import { TabPanel, Tabs } from "@/components/ui/tabs";

const TABS = [
  { id: "profile", label: "Profile" },
  { id: "topics", label: "Topics & weights" },
  { id: "sources", label: "Sources" },
  { id: "routines", label: "Routines" },
  { id: "watches", label: "Watches" },
  { id: "security", label: "Security" },
  { id: "flags", label: "Feature flags" },
] as const;
type TabId = (typeof TABS)[number]["id"];

function SettingsInner() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const raw = params.get("tab");
  const tab: TabId = TABS.some((t) => t.id === raw) ? (raw as TabId) : "profile";
  return (
    <>
      <Tabs
        label="Settings sections"
        tabs={[...TABS]}
        value={tab}
        onChange={(id) => router.replace(`${pathname}?tab=${id}`, { scroll: false })}
      />
      <TabPanel id={tab}>
        {tab === "profile" && <ProfileTab />}
        {tab === "topics" && <TopicsTab />}
        {tab === "sources" && <SourcesTab />}
        {tab === "routines" && <RoutinesTab />}
        {tab === "watches" && <WatchesTab />}
        {tab === "security" && <SecurityTab />}
        {tab === "flags" && <FlagsTab />}
      </TabPanel>
    </>
  );
}

export default function SettingsPage() {
  return (
    <div className="mx-auto max-w-4xl">
      <PageTitle sub="Profile, topics, sources, routines, watches, security and flags">Settings</PageTitle>
      <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
        <SettingsInner />
      </Suspense>
    </div>
  );
}
