"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { CronBuilder } from "@/components/settings/cron-builder";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, inputClass } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { del, get, post } from "@/lib/api";
import { describeCron, looksLikeCron, toCron, type CronPreset } from "@/lib/cron";
import { errMsg } from "@/lib/hooks";
import { PLATFORMS, PLATFORM_LABEL, type SeriesRow } from "@/lib/studio-types";

export function SeriesTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["studio", "series"], queryFn: () => get<SeriesRow[]>("/series") });
  const [name, setName] = useState("");
  const [platform, setPlatform] = useState("linkedin");
  const [preset, setPreset] = useState<CronPreset>({ kind: "weekly", dow: 5, hour: 9, minute: 0 });
  const [template, setTemplate] = useState("");
  const [slot, setSlot] = useState("");
  const refresh = () => qc.invalidateQueries({ queryKey: ["studio"] });
  const add = useMutation({
    mutationFn: () => post("/series", { name: name.trim(), platform, cadence: toCron(preset), template, slot }),
    onSuccess: () => {
      toast("Series created", "good");
      setName("");
      setTemplate("");
      setSlot("");
      refresh();
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const remove = useMutation({ mutationFn: (id: string) => del(`/series/${id}`), onSuccess: refresh, onError: (e) => toast(errMsg(e), "bad") });
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div className="space-y-2">
        {(q.data ?? []).length === 0 && <p className="text-sm text-muted">No series yet — e.g. “Friday AI-engineering lesson”.</p>}
        <ul className="space-y-2">
          {(q.data ?? []).map((s) => (
            <li key={s.id} className="rounded-lg border border-border bg-surface p-3">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="font-medium">{s.name}</p>
                  <p className="text-xs text-muted">
                    {describeCron(s.cadence)}
                    {s.slot && ` · ${s.slot}`}
                  </p>
                </div>
                <div className="flex items-center gap-1">
                  <Badge tone="muted">{PLATFORM_LABEL[s.platform] ?? s.platform}</Badge>
                  <Button size="sm" variant="ghost" aria-label={`Delete series ${s.name}`} onClick={() => remove.mutate(s.id)}>
                    <Trash2 size={14} aria-hidden />
                  </Button>
                </div>
              </div>
              {s.template && <p className="mt-1 whitespace-pre-wrap text-sm text-muted">{s.template}</p>}
            </li>
          ))}
        </ul>
      </div>
      <Card>
        <h2 className="mb-3 text-sm font-semibold">New series</h2>
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            add.mutate();
          }}
        >
          <Field label="Name">
            <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} required />
          </Field>
          <Field label="Platform">
            <select className={inputClass} value={platform} onChange={(e) => setPlatform(e.target.value)}>
              {PLATFORMS.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </Field>
          <CronBuilder value={preset} onChange={setPreset} />
          <Field label="Template" hint="Structure every post in the series follows.">
            <textarea className={inputClass} rows={3} value={template} onChange={(e) => setTemplate(e.target.value)} />
          </Field>
          <Field label="Slot label" hint="e.g. Friday morning">
            <input className={inputClass} value={slot} onChange={(e) => setSlot(e.target.value)} />
          </Field>
          <Button type="submit" variant="primary" disabled={!name.trim() || !looksLikeCron(toCron(preset)) || add.isPending}>
            Create series
          </Button>
        </form>
      </Card>
    </div>
  );
}
