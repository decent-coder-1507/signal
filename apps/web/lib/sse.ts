// Minimal Server-Sent Events parser for fetch() streams (EventSource cannot POST or send CSRF headers).

export type SseEvent = { event: string; data: string };

/** Incremental parser: feed decoded text chunks, get complete events back (blank line terminates an event). */
export class SseParser {
  private buf = "";

  feed(chunk: string): SseEvent[] {
    this.buf += chunk.replace(/\r\n?/g, "\n");
    const out: SseEvent[] = [];
    let i: number;
    while ((i = this.buf.indexOf("\n\n")) >= 0) {
      const block = this.buf.slice(0, i);
      this.buf = this.buf.slice(i + 2);
      const ev = parseBlock(block);
      if (ev) out.push(ev);
    }
    return out;
  }

  /** Flush a trailing event that was not followed by a blank line. */
  end(): SseEvent[] {
    const rest = this.buf;
    this.buf = "";
    const ev = rest.trim() ? parseBlock(rest) : null;
    return ev ? [ev] : [];
  }
}

function parseBlock(block: string): SseEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) continue;
    const c = line.indexOf(":");
    const field = c < 0 ? line : line.slice(0, c);
    let value = c < 0 ? "" : line.slice(c + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  if (!data.length && event === "message") return null;
  return { event, data: data.join("\n") };
}

export function parseAll(text: string): SseEvent[] {
  const p = new SseParser();
  return [...p.feed(text), ...p.end()];
}

/** JSON.parse that tolerates non-JSON payloads (returns the raw string). */
export function sseJson<T = unknown>(data: string): T | string {
  try {
    return JSON.parse(data) as T;
  } catch {
    return data;
  }
}
