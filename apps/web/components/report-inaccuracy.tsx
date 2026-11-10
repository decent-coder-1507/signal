"use client";

import { useMutation } from "@tanstack/react-query";
import clsx from "clsx";
import { Flag } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { post } from "@/lib/api";
import { errMsg, FEEDBACK_TOAST } from "@/lib/hooks";

/** What can be reported — mirrors FeedbackIn.target_type on the API. */
export type ReportTarget = "story" | "item" | "draft" | "idea" | "card" | "insight" | "brief" | "explainer" | "answer";

/**
 * "Report inaccuracy" for any generated output. Posts kind=wrong to /feedback, which stores the report and turns it
 * into a user_report eval case (shown in Ops → Evals).
 */
export function ReportInaccuracy({
  targetType,
  targetId,
  context,
  className,
  label = "Report inaccuracy",
}: {
  targetType: ReportTarget;
  targetId: string;
  context?: Record<string, unknown>;
  className?: string;
  label?: string;
}) {
  const toast = useToast();
  const report = useMutation({
    mutationFn: () => post("/feedback", { target_type: targetType, target_id: targetId, kind: "wrong", context: context ?? {} }),
    onSuccess: () => toast(FEEDBACK_TOAST.wrong, "good"),
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const done = report.isSuccess;
  return (
    <Button
      size="sm"
      variant="ghost"
      data-testid="report-inaccuracy"
      className={clsx("text-muted hover:text-bad", className)}
      disabled={report.isPending || done}
      aria-label={done ? "Reported as inaccurate" : label}
      onClick={() => report.mutate()}
    >
      <Flag size={13} aria-hidden /> {done ? "Reported" : label}
    </Button>
  );
}
