"use client";

import { useMutation } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { inputClass } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { errMsg } from "@/lib/hooks";

const INTENTS = [
  { id: "read_later", label: "Read later" },
  { id: "post", label: "Post" },
  { id: "build", label: "Build" },
  { id: "learn", label: "Learn" },
] as const;

/** Quick capture (§11.2): a URL or a pasted note → POST /capture (multipart). */
export function CaptureBox({ initial = "", initialTitle = "" }: { initial?: string; initialTitle?: string }) {
  const [value, setValue] = useState(initial);
  const [intent, setIntent] = useState<string>("read_later");
  const toast = useToast();
  const cap = useMutation({
    mutationFn: async () => {
      const v = value.trim();
      const form = new FormData();
      if (/^https?:\/\/\S+$/i.test(v)) form.set("url", v);
      else form.set("text", v);
      if (initialTitle) form.set("title", initialTitle);
      form.set("intent", intent);
      return api<{ title: string }>("/capture", { method: "POST", form });
    },
    onSuccess: (r) => {
      setValue("");
      toast(`Captured: ${r.title || "item"}`, "good");
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  return (
    <form
      aria-label="Capture"
      className="space-y-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (value.trim()) cap.mutate();
      }}
    >
      <label className="sr-only" htmlFor="capture-input">
        URL or note to capture
      </label>
      <textarea
        id="capture-input"
        rows={2}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Paste a URL or a note…"
        className={inputClass + " mt-0 resize-y"}
      />
      <div className="flex flex-wrap items-center gap-2">
        <label className="sr-only" htmlFor="capture-intent">
          Intent
        </label>
        <select
          id="capture-intent"
          value={intent}
          onChange={(e) => setIntent(e.target.value)}
          className="min-h-10 rounded-[10px] border border-border-strong bg-surface px-2 text-sm"
        >
          {INTENTS.map((i) => (
            <option key={i.id} value={i.id}>
              {i.label}
            </option>
          ))}
        </select>
        <Button type="submit" variant="secondary" disabled={!value.trim() || cap.isPending}>
          <Plus size={14} aria-hidden /> {cap.isPending ? "Capturing…" : "Capture"}
        </Button>
      </div>
    </form>
  );
}
