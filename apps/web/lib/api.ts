// Thin client for the SIGNAL API, proxied same-origin at /api (next.config.ts rewrites).

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

function csrfToken(): string {
  if (typeof document === "undefined") return "";
  const m = document.cookie.match(/(?:^|;\s*)signal_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

export async function api<T = unknown>(
  path: string,
  init: { method?: string; body?: unknown; form?: FormData; signal?: AbortSignal } = {},
): Promise<T> {
  const method = init.method ?? (init.body !== undefined || init.form ? "POST" : "GET");
  const headers: Record<string, string> = {};
  if (method !== "GET") headers["x-csrf-token"] = csrfToken();
  let body: BodyInit | undefined;
  if (init.form) body = init.form;
  else if (init.body !== undefined) {
    headers["content-type"] = "application/json";
    body = JSON.stringify(init.body);
  }
  const res = await fetch(`/api${path}`, { method, headers, body, credentials: "include", signal: init.signal });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, msg);
  }
  const ct = res.headers.get("content-type") ?? "";
  return (ct.includes("application/json") ? res.json() : res.text()) as Promise<T>;
}

export const get = <T>(p: string) => api<T>(p);
export const post = <T>(p: string, body?: unknown) => api<T>(p, { method: "POST", body: body ?? {} });
export const put = <T>(p: string, body: unknown) => api<T>(p, { method: "PUT", body });
export const del = <T>(p: string) => api<T>(p, { method: "DELETE" });
