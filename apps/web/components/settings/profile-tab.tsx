"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, inputClass } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { get, put } from "@/lib/api";
import { errMsg } from "@/lib/hooks";
import type { Profile } from "@/lib/types";

export function useProfile() {
  return useQuery({ queryKey: ["profile"], queryFn: () => get<Profile>("/profile") });
}

export function useSaveProfile() {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: (body: Partial<Profile>) => put<Profile>("/profile", body),
    onSuccess: (p) => {
      qc.setQueryData(["profile"], p);
      toast("Profile saved", "good");
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
}

const lines = (s: string) =>
  s
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean);
const commas = (s: string) =>
  s
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);

export function ProfileTab() {
  const q = useProfile();
  if (!q.data) return <p className="text-sm text-muted">Loading…</p>;
  return <ProfileForm key={q.data.version} p={q.data} />;
}

function ProfileForm({ p }: { p: Profile }) {
  const save = useSaveProfile();
  const [role, setRole] = useState(p.role);
  const [goals, setGoals] = useState(p.goals.join("\n"));
  const [stack, setStack] = useState(p.stack.join(", "));
  const [blockedE, setBlockedE] = useState(p.blocked_entities.join(", "));
  const [blockedK, setBlockedK] = useState(p.blocked_keywords.join(", "));
  return (
    <Card>
      <form
        className="space-y-4"
        aria-label="Profile"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate({
            role,
            goals: lines(goals),
            stack: commas(stack),
            blocked_entities: commas(blockedE),
            blocked_keywords: commas(blockedK),
          });
        }}
      >
        <Field label="Role">
          <input className={inputClass} value={role} onChange={(e) => setRole(e.target.value)} />
        </Field>
        <Field label="Goals" hint="One per line.">
          <textarea className={inputClass} rows={4} value={goals} onChange={(e) => setGoals(e.target.value)} />
        </Field>
        <Field label="Stack" hint="Comma-separated.">
          <input className={inputClass} value={stack} onChange={(e) => setStack(e.target.value)} />
        </Field>
        <Field label="Blocked entities" hint="Never show stories about these (comma-separated).">
          <input className={inputClass} value={blockedE} onChange={(e) => setBlockedE(e.target.value)} />
        </Field>
        <Field label="Blocked keywords" hint="Comma-separated.">
          <input className={inputClass} value={blockedK} onChange={(e) => setBlockedK(e.target.value)} />
        </Field>
        <div className="flex items-center gap-3">
          <Button type="submit" variant="primary" disabled={save.isPending}>
            Save profile
          </Button>
          <span className="text-xs text-muted">Version {p.version}</span>
        </div>
      </form>
    </Card>
  );
}
