"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Download, Search, Trash2 } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { openSearch } from "@/components/search-palette";
import { PageTitle } from "@/components/shell";
import { Badge } from "@/components/ui/badge";
import { Button, buttonClass } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, inputClass } from "@/components/ui/field";
import { TabPanel, Tabs } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import { Toggle } from "@/components/ui/toggle";
import { del, get, post } from "@/lib/api";
import { errMsg } from "@/lib/hooks";
import { fmtDateTime, humanize } from "@/lib/labels";
import { safeUrl } from "@/lib/safe-url";

type Saved = { id: string; title: string; url: string; intent: string | null; saved_at: string };
type Note = {
  id: string;
  kind: "note" | "highlight";
  text: string;
  tags: string[];
  collection: string | null;
  target_type: string | null;
  target_id: string | null;
  created_at: string;
};

const TABS = [
  { id: "saved", label: "Saved" },
  { id: "notes", label: "Notes & highlights" },
  { id: "export", label: "Export" },
] as const;
type TabId = (typeof TABS)[number]["id"];

function LibraryInner() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const raw = params.get("tab");
  const tab: TabId = TABS.some((t) => t.id === raw) ? (raw as TabId) : "saved";
  return (
    <>
      <Tabs label="Library sections" tabs={[...TABS]} value={tab} onChange={(id) => router.replace(`${pathname}?tab=${id}`, { scroll: false })} />
      <TabPanel id={tab}>
        {tab === "saved" && <SavedTab />}
        {tab === "notes" && <NotesTab />}
        {tab === "export" && <ExportTab />}
      </TabPanel>
    </>
  );
}

export default function LibraryPage() {
  return (
    <div className="mx-auto max-w-4xl">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <PageTitle sub="Everything you saved, noted and highlighted — and a way out (export).">Library</PageTitle>
        <Button onClick={openSearch}>
          <Search size={14} aria-hidden /> Search <kbd className="text-xs text-muted">Ctrl K</kbd>
        </Button>
      </div>
      <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
        <LibraryInner />
      </Suspense>
    </div>
  );
}

function SavedTab() {
  const q = useQuery({ queryKey: ["library", "saved"], queryFn: () => get<Saved[]>("/library/saved") });
  if (q.isLoading) return <p className="text-sm text-muted">Loading…</p>;
  const rows = q.data ?? [];
  if (!rows.length) return <p className="text-sm text-muted">Nothing saved yet. Capture a link from Today or the share sheet.</p>;
  return (
    <ul className="space-y-2">
      {rows.map((r) => (
        <li key={r.id} className="bento p-3">
          {safeUrl(r.url) ? (
            <a href={safeUrl(r.url)} target="_blank" rel="noopener noreferrer" className="font-medium hover:underline">
              {r.title}
            </a>
          ) : (
            <span className="font-medium">{r.title}</span>
          )}
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted">
            {r.intent && <Badge tone="accent">{humanize(r.intent)}</Badge>}
            <span>{fmtDateTime(r.saved_at)}</span>
          </div>
        </li>
      ))}
    </ul>
  );
}

function NotesTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const [collection, setCollection] = useState("");
  const q = useQuery({
    queryKey: ["library", "notes", collection],
    queryFn: () => get<Note[]>(`/notes${collection ? `?collection=${encodeURIComponent(collection)}` : ""}`),
  });
  const [text, setText] = useState("");
  const [kind, setKind] = useState<"note" | "highlight">("note");
  const [tags, setTags] = useState("");
  const [coll, setColl] = useState("");
  const [makeCard, setMakeCard] = useState(false);
  const refresh = () => qc.invalidateQueries({ queryKey: ["library", "notes"] });
  const add = useMutation({
    mutationFn: () =>
      post<{ id: string; card_id: string | null }>("/notes", {
        text: text.trim(),
        kind,
        tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
        collection: coll.trim() || null,
        make_card: makeCard,
      }),
    onSuccess: (r) => {
      setText("");
      refresh();
      toast(r.card_id ? "Saved — and a flashcard was added" : "Saved", "good");
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const remove = useMutation({ mutationFn: (id: string) => del(`/notes/${id}`), onSuccess: refresh, onError: (e) => toast(errMsg(e), "bad") });
  const notes = q.data ?? [];
  const collections = Array.from(new Set(notes.map((n) => n.collection).filter(Boolean))) as string[];
  return (
    <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="min-w-0">
        {(collections.length > 0 || collection) && (
          <div className="mb-3 flex flex-wrap gap-1" role="group" aria-label="Collections">
            {["", ...collections].map((c) => (
              <button
                key={c || "all"}
                type="button"
                aria-pressed={collection === c}
                onClick={() => setCollection(c)}
                className={`min-h-8 rounded-full border px-3 text-xs ${collection === c ? "border-accent bg-accent/10 text-accent" : "border-border text-muted"}`}
              >
                {c || "All"}
              </button>
            ))}
          </div>
        )}
        {notes.length === 0 ? (
          <p className="text-sm text-muted">No notes yet.</p>
        ) : (
          <ul className="space-y-2" aria-label="Notes">
            {notes.map((n) => (
              <li key={n.id} className="bento p-3">
                <div className="flex items-start justify-between gap-2">
                  <p className={`min-w-0 whitespace-pre-wrap break-words text-sm ${n.kind === "highlight" ? "border-l-2 border-accent pl-2" : ""}`}>{n.text}</p>
                  <Button size="sm" variant="ghost" aria-label="Delete note" onClick={() => remove.mutate(n.id)}>
                    <Trash2 size={14} aria-hidden />
                  </Button>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-1 text-xs text-muted">
                  <Badge tone={n.kind === "highlight" ? "accent" : "muted"}>{n.kind}</Badge>
                  {n.collection && <Badge tone="info">{n.collection}</Badge>}
                  {n.tags.map((t) => (
                    <Badge key={t} tone="muted">
                      #{t}
                    </Badge>
                  ))}
                  {n.target_type && <span>on {n.target_type}</span>}
                  <span>{fmtDateTime(n.created_at)}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
      <Card>
        <h2 className="mb-3 text-sm font-semibold">New note</h2>
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (text.trim()) add.mutate();
          }}
        >
          <fieldset className="flex gap-4 text-sm">
            <legend className="sr-only">Kind</legend>
            <label className="inline-flex items-center gap-1.5">
              <input type="radio" checked={kind === "note"} onChange={() => setKind("note")} /> Note
            </label>
            <label className="inline-flex items-center gap-1.5">
              <input type="radio" checked={kind === "highlight"} onChange={() => setKind("highlight")} /> Highlight
            </label>
          </fieldset>
          <Field label="Text">
            <textarea className={inputClass} rows={4} value={text} onChange={(e) => setText(e.target.value)} required />
          </Field>
          <Field label="Tags" hint="Comma-separated.">
            <input className={inputClass} value={tags} onChange={(e) => setTags(e.target.value)} />
          </Field>
          <Field label="Collection">
            <input className={inputClass} value={coll} onChange={(e) => setColl(e.target.value)} list="collections" />
            <datalist id="collections">
              {collections.map((c) => (
                <option key={c} value={c} />
              ))}
            </datalist>
          </Field>
          <Toggle showLabel label="Also make a flashcard" checked={makeCard} onChange={setMakeCard} />
          <Button type="submit" variant="primary" disabled={!text.trim() || add.isPending}>
            Save
          </Button>
        </form>
      </Card>
    </div>
  );
}

function ExportTab() {
  const [priv, setPriv] = useState(false);
  const qs = priv ? "?include_private=true" : "";
  const links = [
    { href: `/api/export/markdown.zip${qs}`, label: "Markdown vault (.zip)", note: "Stories, notes, explainers, drafts as Obsidian-friendly Markdown." },
    { href: `/api/export/json${qs}`, label: "Full JSON export", note: "Everything, machine-readable." },
    { href: "/api/export/metrics.csv", label: "Metrics (.csv)", note: "Publications and their metrics." },
  ];
  return (
    <div className="space-y-4">
      <Card>
        <Toggle showLabel label="Include private material" checked={priv} onChange={setPriv} />
        {priv && (
          <p className="mt-2 flex items-start gap-2 rounded-md border border-warn/40 bg-warn/10 px-3 py-2 text-sm">
            <AlertTriangle size={16} className="mt-0.5 shrink-0 text-warn" aria-hidden />
            The export will contain private raw material and confidential notes. Store it somewhere only you can read.
          </p>
        )}
      </Card>
      <ul className="grid gap-3 sm:grid-cols-3">
        {links.map((l) => (
          <li key={l.label}>
            <Card className="flex h-full flex-col">
              <p className="text-sm font-medium">{l.label}</p>
              <p className="mt-1 flex-1 text-xs text-muted">{l.note}</p>
              <a className={buttonClass("secondary", "sm", "mt-3 w-fit")} href={l.href} download>
                <Download size={14} aria-hidden /> Download
              </a>
            </Card>
          </li>
        ))}
      </ul>
    </div>
  );
}
