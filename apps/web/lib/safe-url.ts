// Any href built from API data goes through this http(s)-only allowlist (blocks javascript:, data:, etc.).
export function safeUrl(u?: string | null): string | undefined {
  if (!u) return undefined;
  try {
    const url = new URL(u);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : undefined;
  } catch {
    return undefined; // relative or malformed
  }
}
