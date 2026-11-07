"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Button, buttonClass } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, inputClass } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { post } from "@/lib/api";
import { errMsg } from "@/lib/hooks";
import type { Asset } from "@/lib/studio-types";
import { assetSrc } from "./visuals";

/** Quote / stat card maker (§7.7). */
export function CardsTab() {
  const toast = useToast();
  const [kind, setKind] = useState<"quote_card" | "stat_card">("stat_card");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [source, setSource] = useState("");
  const [made, setMade] = useState<Asset[]>([]);
  const make = useMutation({
    mutationFn: () => post<Asset>("/studio/cards", { kind, title: title.trim(), body: body.trim(), source: source.trim() || null }),
    onSuccess: (a) => setMade((xs) => [a, ...xs]),
    onError: (e) => toast(errMsg(e), "bad"),
  });
  return (
    <div className="grid gap-4 md:grid-cols-[22rem_1fr]">
      <Card>
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (title.trim()) make.mutate();
          }}
        >
          <fieldset className="flex gap-4 text-sm">
            <legend className="mb-1 font-medium">Card type</legend>
            <label className="inline-flex items-center gap-1.5">
              <input type="radio" checked={kind === "stat_card"} onChange={() => setKind("stat_card")} /> Stat
            </label>
            <label className="inline-flex items-center gap-1.5">
              <input type="radio" checked={kind === "quote_card"} onChange={() => setKind("quote_card")} /> Quote
            </label>
          </fieldset>
          <Field label={kind === "stat_card" ? "Number / headline" : "Quote"}>
            <input className={inputClass} maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} required />
          </Field>
          <Field label="Supporting line">
            <textarea className={inputClass} maxLength={300} rows={3} value={body} onChange={(e) => setBody(e.target.value)} />
          </Field>
          <Field label="Source" hint="Shown on the card — always attribute numbers and quotes.">
            <input className={inputClass} value={source} onChange={(e) => setSource(e.target.value)} />
          </Field>
          <Button type="submit" variant="primary" disabled={!title.trim() || make.isPending}>
            {make.isPending ? "Rendering…" : "Make card"}
          </Button>
        </form>
      </Card>
      <div>
        {made.length === 0 ? (
          <p className="text-sm text-muted">Cards you make appear here.</p>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2">
            {made.map((a) => (
              <li key={a.id} className="space-y-1">
                {/* eslint-disable-next-line @next/next/no-img-element -- authenticated API asset */}
                <img src={assetSrc(a)} alt={typeof a.meta.alt === "string" ? a.meta.alt : "Card"} className="w-full rounded-md border border-border" />
                <a className={buttonClass("secondary", "sm")} href={assetSrc(a)} download>
                  Download PNG
                </a>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
