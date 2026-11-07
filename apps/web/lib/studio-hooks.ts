"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useToast } from "@/components/ui/toast";
import { ApiError, get } from "./api";
import { errMsg } from "./hooks";
import type { Draft } from "./studio-types";

export const draftKey = (id: string) => ["studio", "draft", id] as const;

export function useDraft(id: string) {
  return useQuery({ queryKey: draftKey(id), queryFn: () => get<Draft>(`/studio/drafts/${id}`) });
}

export function useDrafts() {
  return useQuery({ queryKey: ["studio", "drafts"], queryFn: () => get<Draft[]>("/studio/drafts") });
}

/** A mutation that returns the updated draft: writes it into the cache and refreshes Studio lists. */
export function useDraftMutation<V>(id: string, fn: (v: V) => Promise<Draft>, success?: string) {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: fn,
    onSuccess: (d) => {
      qc.setQueryData(draftKey(id), (old: Draft | undefined) => ({ ...old, ...d, versions: d.versions ?? old?.versions }));
      qc.invalidateQueries({ queryKey: ["studio", "drafts"] });
      qc.invalidateQueries({ queryKey: ["studio", "board"] });
      if (success) toast(success, "good");
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
}

/** Gate failures come back as 409 {detail: {message, reasons[]}}; api() stringifies non-string details. */
export function gateReasons(e: unknown): string[] | null {
  if (!(e instanceof ApiError) || e.status !== 409) return null;
  try {
    const d = JSON.parse(e.message) as { reasons?: string[] };
    return Array.isArray(d.reasons) ? d.reasons : null;
  } catch {
    return null;
  }
}
