"use client";

import { PageTitle, useMe } from "@/components/shell";

export default function TodayPage() {
  const me = useMe();
  return (
    <div>
      <PageTitle sub="Brief → one action → cards">Today</PageTitle>
      <p className="text-sm text-muted">Signed in as {me.data?.email}. Your first brief appears here once sources are ingested.</p>
    </div>
  );
}
