"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { MessageCircleQuestion } from "lucide-react";
import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { inputClass } from "@/components/ui/field";
import { post } from "@/lib/api";
import { errMsg } from "@/lib/hooks";
import { humanize } from "@/lib/labels";
import { PLATFORMS, type ContentIdea, type Draft } from "@/lib/studio-types";

export type Seed = { seed_type: "story" | "item" | "free_text"; seed_id?: string; seed_text?: string; title?: string };

const Ctx = createContext<(seed: Seed | null) => void>(() => {});

/** App-wide "start a post" flow (§7.3): seed → 3–5 angles → pick angle + platforms → drafts → editor. */
export function AnglesProvider({ children }: { children: ReactNode }) {
  const [seed, setSeed] = useState<Seed | null>(null);
  const open = useCallback((s: Seed | null) => setSeed(s), []);
  return (
    <Ctx.Provider value={open}>
      {children}
      {seed && <AnglesDialog key={JSON.stringify(seed)} seed={seed} onClose={() => setSeed(null)} />}
    </Ctx.Provider>
  );
}

export function useStartPost() {
  return useContext(Ctx);
}

function AnglesDialog({ seed, onClose }: { seed: Seed; onClose: () => void }) {
  const [freeText, setFreeText] = useState(seed.seed_text ?? "");
  const [angles, setAngles] = useState<ContentIdea[] | null>(null);
  const needsText = seed.seed_type === "free_text" && !seed.seed_text;
  const load = useMutation({
    mutationFn: () =>
      post<ContentIdea[]>("/studio/angles", {
        seed_type: seed.seed_type,
        seed_id: seed.seed_id ?? null,
        seed_text: seed.seed_type === "free_text" ? freeText : "",
      }),
    onSuccess: setAngles,
  });
  const started = useRef(false);
  useEffect(() => {
    if (!needsText && !started.current) {
      started.current = true;
      load.mutate();
    }
  }, [needsText, load]);

  return (
    <Dialog open onClose={onClose} title={angles ? "Pick an angle" : seed.seed_type === "free_text" ? "New post from free text" : "Finding angles…"} wide>
      {seed.title && <p className="-mt-2 mb-3 text-sm text-muted">{seed.title}</p>}
      {needsText && !angles && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (freeText.trim()) load.mutate();
          }}
          className="space-y-3"
        >
          <label className="block text-sm">
            What do you want to write about?
            <textarea className={inputClass} rows={5} value={freeText} onChange={(e) => setFreeText(e.target.value)} required />
          </label>
          <Button type="submit" variant="primary" disabled={load.isPending || !freeText.trim()}>
            {load.isPending ? "Finding angles…" : "Find angles"}
          </Button>
        </form>
      )}
      {load.isPending && !needsText && <p className="text-sm text-muted">Thinking about angles that fit you…</p>}
      {load.error && <p role="alert" className="text-sm text-bad">{errMsg(load.error)}</p>}
      {angles && <AnglePicker ideas={angles} onDone={onClose} />}
    </Dialog>
  );
}

/** Choose one angle and the platforms to draft for; also used from Kanban idea cards. */
export function AnglePicker({ ideas, onDone }: { ideas: ContentIdea[]; onDone: () => void }) {
  const router = useRouter();
  const qc = useQueryClient();
  const [pick, setPick] = useState<string>(ideas[0]?.id ?? "");
  const chosen = ideas.find((i) => i.id === pick);
  const [platforms, setPlatforms] = useState<string[]>(() => (ideas[0]?.platforms ?? ["linkedin"]).filter((p) => p !== "hashnode"));
  const create = useMutation({
    mutationFn: () => post<Draft[]>("/studio/drafts", { content_idea_id: pick, platforms }),
    onSuccess: (ds) => {
      qc.invalidateQueries({ queryKey: ["studio"] });
      onDone();
      if (ds[0]) router.push(`/studio/drafts/${ds[0].id}`);
    },
  });
  const choose = (i: ContentIdea) => {
    setPick(i.id);
    setPlatforms(i.platforms.filter((p) => p !== "hashnode").length ? i.platforms.filter((p) => p !== "hashnode") : ["linkedin"]);
  };
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (pick && platforms.length) create.mutate();
      }}
    >
      <fieldset>
        <legend className="sr-only">Angles</legend>
        <ul className="space-y-2">
          {ideas.map((i) => (
            <li key={i.id}>
              <label
                data-testid="angle"
                data-angle-type={i.angle_type}
                data-needs-input={i.needs_input.length > 0 || undefined}
                className={clsx(
                  "block cursor-pointer rounded-lg border p-3",
                  pick === i.id ? "border-accent bg-accent/5" : "border-border hover:bg-surface-2",
                )}
              >
                <span className="flex items-start gap-2">
                  <input type="radio" name="angle" className="mt-1" checked={pick === i.id} onChange={() => choose(i)} />
                  <span className="min-w-0">
                    <span className="flex flex-wrap items-center gap-1">
                      <Badge tone="accent">{humanize(i.angle_type)}</Badge>
                      {i.risk !== "low" && <Badge tone={i.risk === "high" ? "bad" : "warn"}>{i.risk} risk</Badge>}
                      {i.needs_input.length > 0 && (
                        <Badge tone="info">
                          <MessageCircleQuestion size={11} className="mr-0.5" aria-hidden /> needs your input
                        </Badge>
                      )}
                    </span>
                    <span className="mt-1 block text-sm font-medium">{i.thesis}</span>
                    <span className="mt-0.5 block text-xs text-muted">{i.credibility}</span>
                  </span>
                </span>
              </label>
            </li>
          ))}
        </ul>
      </fieldset>
      <fieldset className="mt-4">
        <legend className="text-sm font-medium">Platforms</legend>
        <div className="mt-1 flex flex-wrap gap-1.5">
          {PLATFORMS.map((p) => (
            <label
              key={p.id}
              className="inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs has-[:checked]:border-accent has-[:checked]:bg-accent/10"
            >
              <input
                type="checkbox"
                checked={platforms.includes(p.id)}
                onChange={() => setPlatforms((xs) => (xs.includes(p.id) ? xs.filter((x) => x !== p.id) : [...xs, p.id]))}
              />
              {p.label}
              {p.id === "hashnode" && <span className="text-muted">(on request only)</span>}
              {chosen?.platforms.includes(p.id) && <span className="text-accent">· suggested</span>}
            </label>
          ))}
        </div>
      </fieldset>
      {create.error && <p role="alert" className="mt-3 text-sm text-bad">{errMsg(create.error)}</p>}
      <div className="mt-4 flex justify-end">
        <Button type="submit" variant="primary" disabled={!pick || !platforms.length || create.isPending}>
          {create.isPending ? "Drafting…" : `Draft ${platforms.length} ${platforms.length === 1 ? "post" : "posts"}`}
        </Button>
      </div>
    </form>
  );
}
