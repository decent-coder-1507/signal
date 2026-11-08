"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Bell, Plus, Send, Trash2 } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { CitationList, CitedText } from "@/components/cited-text";
import { PageTitle } from "@/components/shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { inputClass } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { csrfToken, del, get, post } from "@/lib/api";
import { citationIndex, type Citation } from "@/lib/citations";
import { errMsg } from "@/lib/hooks";
import { fmtDate, fmtDateTime } from "@/lib/labels";
import { SseParser, sseJson } from "@/lib/sse";

type AskCitation = { id: string; kind: string; title: string; url: string | null; date: string | null };
type Msg = {
  id?: string;
  role: "user" | "assistant";
  content: string;
  citations?: AskCitation[];
  not_in_kb?: boolean;
  offer_watch?: string;
  mode?: string;
  streaming?: boolean;
};
type Thread = { id: string; title: string; updated_at: string };
type Done = { thread_id: string; message_id: string; citations: AskCitation[]; mode: string; not_in_kb: boolean; offer_watch?: string };

const NOT_IN_KB = "Not in your knowledge base yet.";
const SLASH = [
  { cmd: "/compare", hint: "/compare A vs B — side-by-side from your sources" },
  { cmd: "/timeline", hint: "/timeline topic — what happened, in order" },
  { cmd: "/explain", hint: "/explain concept — a GYM-style explainer" },
  { cmd: "/whatchanged", hint: "/whatchanged topic — since you last looked" },
];

function toCitations(cs: AskCitation[] | undefined): Citation[] {
  return (cs ?? []).map((c) => ({ id: c.id, url: c.url, title: c.title, source: [c.kind, c.date ? fmtDate(c.date) : null].filter(Boolean).join(" · ") }));
}

/** POST /ask with stream:true and consume the SSE reply (token chunks, then a done event with metadata). */
async function streamAsk(question: string, threadId: string | null, onToken: (t: string) => void): Promise<Done> {
  const res = await fetch("/api/ask", {
    method: "POST",
    credentials: "include",
    headers: { "content-type": "application/json", "x-csrf-token": csrfToken(), accept: "text/event-stream" },
    body: JSON.stringify({ question, thread_id: threadId, stream: true }),
  });
  if (!res.ok || !res.body) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* not json */
    }
    throw new Error(msg || "Ask failed");
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  const parser = new SseParser();
  let done: Done | null = null;
  const handle = (evs: { event: string; data: string }[]) => {
    for (const e of evs) {
      if (e.event === "token") {
        const t = sseJson<string>(e.data);
        onToken(typeof t === "string" ? t : String(t));
      } else if (e.event === "done") done = sseJson<Done>(e.data) as Done;
    }
  };
  for (;;) {
    const { value, done: end } = await reader.read();
    if (end) break;
    handle(parser.feed(dec.decode(value, { stream: true })));
  }
  handle(parser.end());
  if (!done) throw new Error("The answer stream ended early");
  return done;
}

function AskInner() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const qc = useQueryClient();
  const tid = params.get("t");
  const threads = useQuery({ queryKey: ["ask", "threads"], queryFn: () => get<Thread[]>("/chat-threads") });
  const removeThread = useMutation({
    mutationFn: (id: string) => del(`/chat-threads/${id}`),
    onSuccess: (_d, id) => {
      qc.invalidateQueries({ queryKey: ["ask", "threads"] });
      if (id === tid) router.replace(pathname);
    },
  });
  return (
    <div className="grid gap-4 lg:grid-cols-[15rem_minmax(0,1fr)]">
      <aside className="min-w-0">
        <Button size="sm" className="mb-2 w-full" onClick={() => router.replace(pathname)}>
          <Plus size={14} aria-hidden /> New chat
        </Button>
        <ul className="flex gap-1 overflow-x-auto lg:flex-col" aria-label="Threads">
          {(threads.data ?? []).map((t) => (
            <li key={t.id} className="group flex min-w-40 items-center lg:min-w-0">
              <Link
                href={`${pathname}?t=${t.id}`}
                aria-current={t.id === tid ? "page" : undefined}
                className={clsx("min-w-0 flex-1 truncate rounded-md px-2 py-1.5 text-sm", t.id === tid ? "bg-surface-2 font-medium" : "text-muted hover:text-text")}
                title={`${t.title} · ${fmtDateTime(t.updated_at)}`}
              >
                {t.title}
              </Link>
              <button type="button" aria-label={`Delete ${t.title}`} onClick={() => removeThread.mutate(t.id)} className="p-1 text-muted opacity-0 hover:text-bad group-hover:opacity-100 focus:opacity-100">
                <Trash2 size={13} aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      </aside>
      <Chat key={tid ?? "new"} threadId={tid} onThread={(id) => router.replace(`${pathname}?t=${id}`, { scroll: false })} />
    </div>
  );
}

function Chat({ threadId, onThread }: { threadId: string | null; onThread: (id: string) => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const existing = useQuery({
    queryKey: ["ask", "thread", threadId],
    queryFn: () => get<{ id: string; messages: Msg[] }>(`/chat-threads/${threadId}`),
    enabled: !!threadId,
  });
  const [local, setLocal] = useState<Msg[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const msgs = [...(existing.data?.messages ?? []), ...local];

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [msgs.length, local]);

  async function send(question: string) {
    if (!question.trim() || busy) return;
    setBusy(true);
    setQ("");
    const before = local;
    setLocal((m) => [...m, { role: "user", content: question }, { role: "assistant", content: "", streaming: true }]);
    const patchLast = (f: (m: Msg) => Msg) => setLocal((ms) => ms.map((m, i) => (i === ms.length - 1 ? f(m) : m)));
    try {
      let text = "";
      const done = await streamAsk(question, threadId, (t) => {
        text += t;
        patchLast((m) => ({ ...m, content: m.content + t }));
      });
      const finish = (m: Msg): Msg => ({ ...m, id: done.message_id, citations: done.citations, not_in_kb: done.not_in_kb, offer_watch: done.offer_watch, mode: done.mode, streaming: false });
      patchLast(finish);
      qc.invalidateQueries({ queryKey: ["ask", "threads"] });
      if (!threadId) {
        // Seed the new thread's cache with what is on screen so the reload after streaming does not flash.
        const msgs: Msg[] = [...before, { role: "user", content: question }, finish({ role: "assistant", content: text })];
        qc.setQueryData(["ask", "thread", done.thread_id], { id: done.thread_id, messages: msgs });
        onThread(done.thread_id);
      }
    } catch (e) {
      patchLast((m) => ({ ...m, content: errMsg(e), streaming: false }));
      toast(errMsg(e), "bad");
    } finally {
      setBusy(false);
    }
  }

  const hints = q.startsWith("/") ? SLASH.filter((s) => s.cmd.startsWith(q.split(" ")[0])) : [];

  return (
    <section className="flex min-h-[60dvh] min-w-0 flex-col">
      <div className="flex-1 space-y-4" aria-live="polite">
        {msgs.length === 0 && (
          <div className="rounded-lg border border-dashed border-border p-6 text-sm text-muted">
            <p>Ask anything about what SIGNAL has seen — answers cite your stored items, never the open web.</p>
            <ul className="mt-2 space-y-0.5 text-xs">
              {SLASH.map((s) => (
                <li key={s.cmd}>
                  <code>{s.hint}</code>
                </li>
              ))}
            </ul>
          </div>
        )}
        {msgs.map((m, i) => (m.role === "user" ? <UserMsg key={m.id ?? `u${i}`} text={m.content} /> : <Answer key={m.id ?? `a${i}`} m={m} />))}
        <div ref={bottom} />
      </div>
      <form
        className="sticky bottom-20 mt-4 rounded-lg border border-border bg-surface p-2 shadow-sm md:bottom-4"
        onSubmit={(e) => {
          e.preventDefault();
          void send(q);
        }}
      >
        {hints.length > 0 && (
          <ul className="mb-1 space-y-0.5" aria-label="Slash commands">
            {hints.map((h) => (
              <li key={h.cmd}>
                <button type="button" className="w-full rounded px-2 py-1 text-left text-xs text-muted hover:bg-surface-2" onClick={() => setQ(h.cmd + " ")}>
                  {h.hint}
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="flex items-end gap-2">
          <label className="sr-only" htmlFor="ask-input">
            Question
          </label>
          <textarea
            id="ask-input"
            rows={1}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send(q);
              }
            }}
            placeholder="Ask SIGNAL…  (/ for commands)"
            className={inputClass + " mt-0 max-h-40 resize-none border-0 focus:outline-none"}
          />
          <Button type="submit" variant="primary" aria-label="Ask" disabled={!q.trim() || busy}>
            <Send size={16} aria-hidden />
          </Button>
        </div>
      </form>
    </section>
  );
}

function UserMsg({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <p className="max-w-[85%] whitespace-pre-wrap rounded-lg bg-surface-2 px-3 py-2 text-sm">{text}</p>
    </div>
  );
}

function Answer({ m }: { m: Msg }) {
  const toast = useToast();
  const qc = useQueryClient();
  const idx = citationIndex(toCitations(m.citations));
  const notInKb = m.not_in_kb ?? m.content.includes(NOT_IN_KB);
  const body = m.content.replace(NOT_IN_KB, "").trim();
  const watch = useMutation({
    mutationFn: () => post("/watches", { query: (m.offer_watch ?? "").slice(0, 500), urgency: "digest" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["watches"] });
      toast("Watch created — you will hear when it shows up", "good");
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const turn = useMutation({
    mutationFn: (target: "post" | "idea" | "card" | "note") =>
      post<{ target: string; idea_id?: string; content_idea_ids?: string[] }>(`/ask/messages/${m.id}/turn-into`, { target }),
    onSuccess: (r) => {
      const msg: Record<string, string> = {
        post: `${r.content_idea_ids?.length ?? 0} post angles added to the Studio pipeline`,
        idea: "Added to the Lab shortlist",
        card: "Flashcard added to your review queue",
        note: "Saved to your notes",
      };
      toast(msg[r.target] ?? "Done", "good");
      qc.invalidateQueries({ queryKey: ["studio"] });
      qc.invalidateQueries({ queryKey: ["lab"] });
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  return (
    <article className="rounded-lg border border-border bg-surface p-4" data-testid="answer">
      {m.mode && !["answer", "ask"].includes(m.mode) && <Badge tone="muted">{m.mode}</Badge>}
      <div className="prose-signal space-y-2 text-[15px] leading-relaxed">
        {body
          ? body.split(/\n{2,}/).map((p, i) => (
              <p key={i} className="whitespace-pre-wrap">
                <CitedText text={p} index={idx} />
              </p>
            ))
          : m.streaming && <p className="text-muted">Thinking…</p>}
      </div>
      {!m.streaming && notInKb && (
        <div className="mt-3 flex flex-wrap items-center gap-2 rounded-md border border-warn/40 bg-warn/10 px-3 py-2 text-sm" data-testid="not-in-kb">
          <span className="flex-1">Not in your knowledge base yet — SIGNAL won&apos;t guess.</span>
          {m.offer_watch && (
            <Button size="sm" disabled={watch.isPending || watch.isSuccess} onClick={() => watch.mutate()}>
              <Bell size={14} aria-hidden /> {watch.isSuccess ? "Watching" : "Create watch"}
            </Button>
          )}
        </div>
      )}
      {idx.size > 0 && (
        <div className="mt-3 border-t border-border pt-2">
          <CitationList index={idx} />
        </div>
      )}
      {m.id && !m.streaming && !notInKb && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5" role="group" aria-label="Turn into">
          <span className="text-xs text-muted">Turn into…</span>
          {(["post", "idea", "card", "note"] as const).map((t) => (
            <Button key={t} size="sm" variant="ghost" disabled={turn.isPending} onClick={() => turn.mutate(t)}>
              {t[0].toUpperCase() + t.slice(1)}
            </Button>
          ))}
        </div>
      )}
    </article>
  );
}

export default function AskPage() {
  return (
    <div className="mx-auto max-w-5xl">
      <PageTitle sub="Chat over your own knowledge base. Every claim cites what you have read.">Ask SIGNAL</PageTitle>
      <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
        <AskInner />
      </Suspense>
    </div>
  );
}
