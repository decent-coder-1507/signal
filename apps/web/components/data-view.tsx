import Link from "next/link";
import type { ReactNode } from "react";
import { humanize } from "@/lib/labels";
import { safeUrl } from "@/lib/safe-url";

/**
 * Readable rendering of arbitrary JSON produced by routine steps (review sections, run outputs): objects become
 * definition lists, arrays become lists, and title/href|url pairs become links (internal paths or http(s) only).
 */
export function DataView({ data, depth = 0 }: { data: unknown; depth?: number }): ReactNode {
  if (data == null || data === "") return <span className="text-muted">—</span>;
  if (typeof data === "string" || typeof data === "number" || typeof data === "boolean") {
    return <span className="whitespace-pre-wrap break-words">{String(data)}</span>;
  }
  if (depth > 4) return <span className="text-muted">…</span>;
  if (Array.isArray(data)) {
    if (!data.length) return <span className="text-muted">none</span>;
    return (
      <ul className="list-disc space-y-1 pl-5">
        {data.slice(0, 50).map((x, i) => (
          <li key={i}>
            <DataView data={x} depth={depth + 1} />
          </li>
        ))}
      </ul>
    );
  }
  const o = data as Record<string, unknown>;
  const title = typeof o.title === "string" ? o.title : typeof o.name === "string" ? o.name : null;
  const href = typeof o.href === "string" ? o.href : typeof o.url === "string" ? o.url : null;
  const internal = href && href.startsWith("/") && !href.startsWith("//") ? href : null;
  const external = href ? safeUrl(href) : undefined;
  const entries = Object.entries(o).filter(
    ([k, v]) => !["title", "name", "href", "url", "id", "story_id", "idea_id", "skill_id", "card_id"].includes(k) && !k.startsWith("_") && v != null && v !== "",
  );
  return (
    <div className="min-w-0">
      {title &&
        (internal ? (
          <Link href={internal} className="font-medium hover:underline">
            {title}
          </Link>
        ) : external ? (
          <a href={external} target="_blank" rel="noopener noreferrer" className="font-medium hover:underline">
            {title}
          </a>
        ) : (
          <span className="font-medium">{title}</span>
        ))}
      {entries.length > 0 && (
        <dl className={title ? "mt-0.5 space-y-0.5 text-muted" : "space-y-1"}>
          {entries.map(([k, v]) => (
            <div key={k} className="grid grid-cols-[minmax(6rem,auto)_1fr] gap-2">
              <dt className="text-muted">{humanize(k)}</dt>
              <dd className="min-w-0">
                <DataView data={v} depth={depth + 1} />
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}
