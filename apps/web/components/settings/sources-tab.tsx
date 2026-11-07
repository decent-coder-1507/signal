"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Download, FlaskConical, Upload } from "lucide-react";
import { Fragment, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, inputClass } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { Toggle } from "@/components/ui/toggle";
import { api, get, post, put } from "@/lib/api";
import { errMsg } from "@/lib/hooks";
import { fmtDateTime } from "@/lib/labels";
import type { Source } from "@/lib/types";

type TestResult = {
  ok: boolean;
  entries?: number;
  sample?: { title: string; url: string; published_at: string | null }[];
  error?: string;
};

const TYPES = ["rss", "hn", "arxiv", "github", "github_trending", "hf", "youtube", "podcast", "reddit", "producthunt", "x", "email_in"];

export function SourcesTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["sources"], queryFn: () => get<Source[]>("/sources") });
  const [tests, setTests] = useState<Record<string, TestResult>>({});
  const refresh = () => qc.invalidateQueries({ queryKey: ["sources"] });

  const toggle = useMutation({
    mutationFn: (v: { id: string; enabled: boolean }) => put<Source>(`/sources/${v.id}`, { enabled: v.enabled }),
    onSuccess: refresh,
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const test = useMutation({
    mutationFn: (id: string) => post<TestResult>(`/sources/${id}/test`),
    onSuccess: (r, id) => setTests((t) => ({ ...t, [id]: r })),
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const fetchNow = useMutation({
    mutationFn: (id: string) => post<{ status: string; found: number; new: number; error: string | null }>(`/sources/${id}/fetch`),
    onSuccess: (r) => {
      refresh();
      toast(r.error ? `Fetch ${r.status}: ${r.error}` : `Fetched ${r.found} entries, ${r.new} new`, r.error ? "bad" : "good");
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });

  const sources = q.data ?? [];
  const flagged = sources.filter((s) => s.health?.flagged);

  return (
    <div className="space-y-4">
      {flagged.length > 0 && (
        <p className="flex items-start gap-2 rounded-md border border-warn/40 bg-warn/10 px-3 py-2 text-sm">
          <AlertTriangle size={16} className="mt-0.5 shrink-0 text-warn" aria-hidden />
          {flagged.length} source{flagged.length > 1 ? "s need" : " needs"} attention — fix or disable.
        </p>
      )}
      <Card className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="border-b border-border text-left text-xs text-muted">
              <tr>
                <th className="px-3 py-2 font-medium">Name</th>
                <th className="px-3 py-2 font-medium">Type</th>
                <th className="px-3 py-2 font-medium">Tier</th>
                <th className="px-3 py-2 font-medium">Ring</th>
                <th className="px-3 py-2 font-medium">Items</th>
                <th className="px-3 py-2 font-medium">Enabled</th>
                <th className="px-3 py-2 font-medium">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {sources.map((s) => (
                <Fragment key={s.id}>
                  <tr className="border-b border-border last:border-0">
                    <td className="px-3 py-2">
                      <span className="font-medium">{s.name}</span>
                      {s.health?.flagged && (
                        <span className="ml-1.5">
                          <Badge tone="warn" title={String(s.health.flagged)}>
                            fix or disable
                          </Badge>
                        </span>
                      )}
                      <span className="block text-xs text-muted">Last fetched {fmtDateTime(s.last_fetched_at)}</span>
                    </td>
                    <td className="px-3 py-2 text-muted">{s.type}</td>
                    <td className="px-3 py-2 tabular-nums">{s.tier}</td>
                    <td className="px-3 py-2">{s.ring}</td>
                    <td className="px-3 py-2 tabular-nums">{s.items ?? 0}</td>
                    <td className="px-3 py-2">
                      <Toggle
                        label={`Enable ${s.name}`}
                        checked={s.enabled}
                        onChange={(v) => toggle.mutate({ id: s.id, enabled: v })}
                      />
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right">
                      <Button size="sm" variant="ghost" onClick={() => test.mutate(s.id)} disabled={test.isPending}>
                        <FlaskConical size={14} aria-hidden /> Test
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => fetchNow.mutate(s.id)} disabled={fetchNow.isPending}>
                        <Download size={14} aria-hidden /> Fetch now
                      </Button>
                    </td>
                  </tr>
                  {tests[s.id] && (
                    <tr className="border-b border-border bg-surface-2">
                      <td colSpan={7} className="px-3 py-2 text-xs">
                        {tests[s.id].ok ? (
                          <>
                            <p className="font-medium">{tests[s.id].entries} entries found. Sample:</p>
                            <ul className="mt-1 list-disc pl-5">
                              {(tests[s.id].sample ?? []).map((x) => (
                                <li key={x.url} className="break-words">
                                  {x.title}
                                </li>
                              ))}
                            </ul>
                          </>
                        ) : (
                          <p className="text-bad">{tests[s.id].error}</p>
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <div className="grid gap-4 md:grid-cols-2">
        <AddSource onAdded={refresh} />
        <OpmlImport onDone={refresh} />
      </div>
    </div>
  );
}

function AddSource({ onAdded }: { onAdded: () => void }) {
  const toast = useToast();
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [type, setType] = useState("rss");
  const [tier, setTier] = useState(2);
  const [ring, setRing] = useState("core");
  const add = useMutation({
    mutationFn: () => post<Source>("/sources", { name, url: url || null, type, tier, ring }),
    onSuccess: (s) => {
      toast(`Added ${s.name}`, "good");
      setName("");
      setUrl("");
      onAdded();
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  return (
    <Card>
      <h2 className="mb-2 text-sm font-semibold">Add a source</h2>
      <form
        className="space-y-3"
        aria-label="Add source"
        onSubmit={(e) => {
          e.preventDefault();
          add.mutate();
        }}
      >
        <Field label="Name">
          <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} required />
        </Field>
        <Field label="Feed URL">
          <input className={inputClass} type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" />
        </Field>
        <div className="grid grid-cols-3 gap-2">
          <Field label="Type">
            <select className={inputClass} value={type} onChange={(e) => setType(e.target.value)}>
              {TYPES.map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </Field>
          <Field label="Tier">
            <select className={inputClass} value={tier} onChange={(e) => setTier(Number(e.target.value))}>
              <option value={1}>1</option>
              <option value={2}>2</option>
              <option value={3}>3</option>
            </select>
          </Field>
          <Field label="Ring">
            <select className={inputClass} value={ring} onChange={(e) => setRing(e.target.value)}>
              <option value="core">core</option>
              <option value="adjacent">adjacent</option>
              <option value="wide">wide</option>
            </select>
          </Field>
        </div>
        <Button type="submit" variant="primary" disabled={add.isPending || !name.trim()}>
          Add source
        </Button>
      </form>
    </Card>
  );
}

function OpmlImport({ onDone }: { onDone: () => void }) {
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const imp = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.set("file", file!);
      return api<Record<string, number>>("/sources/import-opml", { method: "POST", form });
    },
    onSuccess: (r) => {
      toast(`Imported: ${Object.entries(r).map(([k, v]) => `${v} ${k}`).join(", ")}`, "good");
      onDone();
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  return (
    <Card>
      <h2 className="mb-2 text-sm font-semibold">Import OPML</h2>
      <p className="mb-3 text-sm text-muted">Bring your feeds from another reader. Duplicates are skipped.</p>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (file) imp.mutate();
        }}
      >
        <label className="block text-sm">
          <span className="sr-only">OPML file</span>
          <input
            type="file"
            accept=".opml,.xml,text/xml,application/xml"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="block w-full text-sm file:mr-3 file:rounded-md file:border file:border-border file:bg-surface-2 file:px-3 file:py-1.5 file:text-sm"
          />
        </label>
        <Button type="submit" disabled={!file || imp.isPending}>
          <Upload size={14} aria-hidden /> Import
        </Button>
      </form>
    </Card>
  );
}
