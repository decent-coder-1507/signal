"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useToast } from "@/components/ui/toast";
import { ApiError, get, post } from "./api";
import type { Brief, FeedbackKind, Today } from "./types";

export function errMsg(e: unknown): string {
  return e instanceof ApiError ? e.message : e instanceof Error ? e.message : "Something went wrong";
}

export function useLatestBrief() {
  return useQuery({ queryKey: ["brief", "latest"], queryFn: () => get<Brief | null>("/briefs/latest") });
}

export function useToday() {
  return useQuery({ queryKey: ["today"], queryFn: () => get<Today>("/today") });
}

export const FEEDBACK_TOAST: Record<FeedbackKind, string> = {
  useful: "Marked useful — more like this",
  not_for_me: "Skipped — less of this",
  more: "More like this",
  less: "Less like this",
  wrong: "Reported as inaccurate — thanks, it feeds the evals",
  known: "Noted: you already knew this",
  opened: "Opened",
  saved: "Saved",
  used: "Recorded",
};

export function useFeedback() {
  const toast = useToast();
  return useMutation({
    mutationFn: (v: { id: string; kind: FeedbackKind; context?: Record<string, unknown>; silent?: boolean }) =>
      post("/feedback", { target_type: "story", target_id: v.id, kind: v.kind, context: v.context ?? {} }),
    onSuccess: (_d, v) => {
      if (!v.silent) toast(FEEDBACK_TOAST[v.kind], "good");
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
}

export function useGenerateBrief() {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: () => post<Brief>("/briefs/generate", { kind: "daily" }),
    onSuccess: (b) => {
      qc.setQueryData(["brief", "latest"], b);
      qc.invalidateQueries({ queryKey: ["today"] });
      toast(`Brief ready: ${b.content.stories.length} stories`, "good");
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
}

export function useCompleteBrief() {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: (v: { id: string; minimum: boolean }) => post(`/briefs/${v.id}/complete`, { minimum: v.minimum }),
    onSuccess: (_d, v) => {
      qc.invalidateQueries({ queryKey: ["brief"] });
      qc.invalidateQueries({ queryKey: ["today"] });
      toast(v.minimum ? "2-minute mode counted for today" : "Brief done — today's first step is complete", "good");
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
}

export function useHabitMark() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (step: "brief" | "action" | "cards" | "minimum") => post("/habit/mark", { step }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["today"] }),
  });
}
