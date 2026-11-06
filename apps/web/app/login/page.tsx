"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError, post } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await post<{ onboarded: boolean }>("/auth/login", { email, password, totp: totp || null });
      router.replace(r.onboarded ? "/" : "/onboarding");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach SIGNAL");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-dvh max-w-sm flex-col justify-center px-4">
      <h1 className="font-serif text-3xl font-semibold tracking-tight">SIGNAL</h1>
      <p className="mt-1 text-sm text-muted">Less, but better.</p>
      <form onSubmit={submit} className="mt-8 space-y-3" aria-label="Sign in">
        <label className="block text-sm">
          Email
          <input
            className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2"
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </label>
        <label className="block text-sm">
          Password
          <input
            className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        <label className="block text-sm">
          Authenticator code <span className="text-muted">(if enabled)</span>
          <input
            className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2"
            inputMode="numeric"
            autoComplete="one-time-code"
            value={totp}
            onChange={(e) => setTotp(e.target.value)}
          />
        </label>
        {error && (
          <p role="alert" className="text-sm text-bad">
            {error}
          </p>
        )}
        <button
          disabled={busy}
          className="w-full rounded-md bg-accent px-3 py-2 font-medium text-accent-contrast disabled:opacity-60"
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
