"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Copy, KeyRound, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { useMe } from "@/components/shell";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, inputClass } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { post } from "@/lib/api";
import { errMsg } from "@/lib/hooks";

export function SecurityTab() {
  return (
    <div className="space-y-4">
      <ApiToken />
      <Totp />
    </div>
  );
}

function ApiToken() {
  const me = useMe();
  const qc = useQueryClient();
  const toast = useToast();
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [token, setToken] = useState<string | null>(null);
  const has = !!me.data?.has_api_token;
  const rotate = useMutation({
    mutationFn: () =>
      post<{ token: string }>("/auth/api-token", { password, current_totp: me.data?.totp_enabled ? code : null }),
    onSuccess: (r) => {
      setToken(r.token);
      setPassword("");
      setCode("");
      qc.invalidateQueries({ queryKey: ["me"] });
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  return (
    <Card>
      <h2 className="flex items-center gap-1.5 text-sm font-semibold">
        <KeyRound size={16} aria-hidden /> API token
      </h2>
      <p className="mt-1 text-sm text-muted">
        Used by the bookmarklet and the Telegram bridge. {has ? "A token exists; creating a new one revokes it." : "No token yet."}
      </p>
      {token ? (
        <div className="mt-3 space-y-2" data-testid="api-token">
          <p className="text-sm font-medium text-warn">Copy it now — it will not be shown again.</p>
          <div className="flex items-center gap-2">
            <code className="min-w-0 flex-1 break-all rounded-md border border-border bg-surface-2 px-2 py-1.5 font-mono text-xs">
              {token}
            </code>
            <Button
              size="sm"
              onClick={() => {
                navigator.clipboard?.writeText(token).then(() => toast("Copied", "good"));
              }}
            >
              <Copy size={14} aria-hidden /> Copy
            </Button>
          </div>
          <Button size="sm" variant="ghost" onClick={() => setToken(null)}>
            Done
          </Button>
        </div>
      ) : (
        <form
          className="mt-3 flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            rotate.mutate();
          }}
        >
          <Field label="Confirm password" className="min-w-0 flex-1">
            <input
              type="password"
              autoComplete="current-password"
              className={inputClass}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </Field>
          {me.data?.totp_enabled && (
            <Field label="Authenticator code">
              <input inputMode="numeric" className={inputClass + " w-32"} value={code} onChange={(e) => setCode(e.target.value)} required />
            </Field>
          )}
          <Button type="submit" variant="primary" disabled={rotate.isPending || !password}>
            {has ? "Rotate token" : "Create token"}
          </Button>
        </form>
      )}
    </Card>
  );
}

function Totp() {
  const me = useMe();
  const qc = useQueryClient();
  const toast = useToast();
  const [password, setPassword] = useState("");
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");
  const start = useMutation({
    mutationFn: () => post<{ secret: string; otpauth_uri: string }>("/auth/totp/setup", { password }),
    onSuccess: setSetup,
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const confirm = useMutation({
    mutationFn: () => post("/auth/totp/setup", { password, secret: setup!.secret, code }),
    onSuccess: () => {
      toast("Two-factor sign-in enabled", "good");
      setSetup(null);
      setPassword("");
      setCode("");
      qc.invalidateQueries({ queryKey: ["me"] });
    },
    onError: (e) => toast(errMsg(e), "bad"),
  });
  const enabled = me.data?.totp_enabled;
  return (
    <Card>
      <h2 className="flex items-center gap-1.5 text-sm font-semibold">
        <ShieldCheck size={16} aria-hidden /> Two-factor sign-in (TOTP)
      </h2>
      {enabled ? (
        <p className="mt-1 text-sm text-good">Enabled. Sign-in asks for your authenticator code.</p>
      ) : !setup ? (
        <form
          className="mt-3 flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            start.mutate();
          }}
        >
          <p className="w-full text-sm text-muted">Optional. Adds an authenticator code to sign-in.</p>
          <Field label="Confirm password" className="min-w-0 flex-1">
            <input
              type="password"
              autoComplete="current-password"
              className={inputClass}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </Field>
          <Button type="submit" disabled={start.isPending || !password}>
            Set up
          </Button>
        </form>
      ) : (
        <form
          className="mt-3 space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            confirm.mutate();
          }}
        >
          <p className="text-sm">Add this key to your authenticator app, then enter the 6-digit code it shows.</p>
          <code className="block break-all rounded-md border border-border bg-surface-2 px-2 py-1.5 font-mono text-xs">{setup.secret}</code>
          {/* the only non-http(s) link we render: pyotp's otpauth:// URI, checked by scheme */}
          {setup.otpauth_uri.startsWith("otpauth://") && (
            <a href={setup.otpauth_uri} className="text-xs text-accent underline">
              Open in authenticator app
            </a>
          )}
          <div className="flex flex-wrap items-end gap-2">
            <Field label="Code">
              <input inputMode="numeric" className={inputClass + " w-32"} value={code} onChange={(e) => setCode(e.target.value)} required />
            </Field>
            <Button type="submit" variant="primary" disabled={confirm.isPending || code.length < 6}>
              Enable
            </Button>
            <Button variant="ghost" onClick={() => setSetup(null)}>
              Cancel
            </Button>
          </div>
        </form>
      )}
    </Card>
  );
}
