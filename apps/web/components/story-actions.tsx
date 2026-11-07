"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bell, BookOpen, EyeOff, Hammer, PenLine, Star } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { post } from "@/lib/api";
import { useStartPost } from "@/components/studio/angles-dialog";
import { errMsg } from "@/lib/hooks";

export type ActionKind = "post" | "build" | "learn" | "watch" | "follow" | "ignore";

const LATER: Record<"build" | "learn", string> = {
  build: "Noted as a build idea — Lab arrives in a later milestone",
  learn: "Noted to learn — Gym arrives in a later milestone",
};

/** One handler for the story action buttons (§6.8/§14), shared by brief cards and the story page. */
export function useStoryAction() {
  const toast = useToast();
  const qc = useQueryClient();
  const startPost = useStartPost();
  return useMutation({
    mutationFn: async (v: { kind: ActionKind; id: string; title: string; followed?: boolean }) => {
      switch (v.kind) {
        case "post":
          // Opens the angles dialog (§7.3); also counts as today's action.
          startPost({ seed_type: "story", seed_id: v.id, title: v.title });
          await post("/feedback", { target_type: "story", target_id: v.id, kind: "used", context: { action: "post" } });
          await post("/habit/mark", { step: "action" });
          return null;
        case "build":
        case "learn":
          await post("/feedback", { target_type: "story", target_id: v.id, kind: "used", context: { action: v.kind } });
          await post("/habit/mark", { step: "action" });
          return LATER[v.kind];
        case "watch":
          await post("/watches", { query: v.title.slice(0, 500), urgency: "digest" });
          return `Watching: “${v.title}”`;
        case "follow": {
          const on = !v.followed;
          await post(`/stories/${v.id}/follow?on=${on}`);
          return on ? "Following this story — updates will be flagged" : "Unfollowed";
        }
        case "ignore":
          await post("/feedback", { target_type: "story", target_id: v.id, kind: "not_for_me", context: { action: "ignore" } });
          return "Ignored — less of this";
      }
    },
    onSuccess: (msg, v) => {
      if (msg) toast(msg, "good");
      if (v.kind === "watch") qc.invalidateQueries({ queryKey: ["watches"] });
      if (v.kind === "follow") qc.invalidateQueries({ queryKey: ["story", v.id] });
      if (["post", "build", "learn"].includes(v.kind)) qc.invalidateQueries({ queryKey: ["today"] });
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
}

const BUTTONS: { kind: ActionKind; label: string; icon: typeof PenLine; key?: string }[] = [
  { kind: "post", label: "Post", icon: PenLine, key: "p" },
  { kind: "build", label: "Build", icon: Hammer, key: "b" },
  { kind: "learn", label: "Learn", icon: BookOpen, key: "l" },
  { kind: "watch", label: "Watch", icon: Bell },
  { kind: "follow", label: "Follow", icon: Star },
  { kind: "ignore", label: "Ignore", icon: EyeOff, key: "x" },
];

export function StoryActionBar({
  id,
  title,
  followed: initial,
  leading,
}: {
  id: string;
  title: string;
  followed?: boolean;
  leading?: ReactNode;
}) {
  const act = useStoryAction();
  const [followed, setFollowed] = useState(!!initial);
  return (
    <div className="flex flex-wrap gap-1.5" role="group" aria-label="Story actions">
      {leading}
      {BUTTONS.map((b) => (
        <Button
          key={b.kind}
          size="sm"
          variant={b.kind === "follow" && followed ? "primary" : "secondary"}
          disabled={act.isPending}
          aria-keyshortcuts={b.key}
          aria-pressed={b.kind === "follow" ? !!followed : undefined}
          onClick={() =>
            act.mutate(
              { kind: b.kind, id, title, followed },
              { onSuccess: () => b.kind === "follow" && setFollowed(!followed) },
            )
          }
        >
          <b.icon size={14} aria-hidden />
          {b.kind === "follow" && followed ? "Following" : b.label}
        </Button>
      ))}
    </div>
  );
}
