"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { CaptureBox } from "@/components/capture-box";
import { PageTitle } from "@/components/shell";
import { Card } from "@/components/ui/card";

// Target of the manifest's share_target (Android "Share to SIGNAL").
function Inner() {
  const p = useSearchParams();
  const url = p.get("url") ?? "";
  const text = p.get("text") ?? "";
  const title = p.get("title") ?? "";
  // Many apps put the shared link inside `text`.
  const link = url || (text.match(/https?:\/\/\S+/)?.[0] ?? "");
  return (
    <Card>
      <CaptureBox initial={link || text} initialTitle={title} />
    </Card>
  );
}

export default function CapturePage() {
  return (
    <div className="mx-auto max-w-xl">
      <PageTitle sub="Save a link or a note for later, a post, a build or learning.">Capture</PageTitle>
      <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
        <Inner />
      </Suspense>
    </div>
  );
}
