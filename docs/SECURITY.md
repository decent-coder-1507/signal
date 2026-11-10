# Security review checklist (M10, §16.2–16.3)

Reviewed 2026-11-08. ✅ = implemented and covered by a test or a recorded check.

| Area | Control | Status / evidence |
|---|---|---|
| Auth | Single user, argon2 password hashes, optional TOTP | ✅ `signal_core/auth.py`; `tests/integration/test_api_auth.py` |
| Auth | Login rate limit (10/min/IP) + lockout after 5 failures (15 min) | ✅ `test_wrong_password_then_lockout` |
| Sessions | Signed HttpOnly SameSite=Lax cookie; `Secure` behind HTTPS (`SIGNAL_COOKIE_SECURE`) | ✅ ADR-008 |
| CSRF | Double-submit cookie + `x-csrf-token` on every cookie-authenticated write | ✅ `test_csrf_required_for_cookie_writes` |
| API token | sha256-hashed, rotatable; cannot change credentials; changing 2FA/token needs password (+ current TOTP) | ✅ `test_credential_changes_require_reauth_and_session` |
| Telegram (dormant since ADR-027) | Webhook secret header + single chat-id allowlist; long polling locally | ✅ `test_telegram_webhook_requires_secret`, other chats ignored |
| SSRF | Outbound fetches: http(s) only, public IPs only, redirects re-validated | ✅ ADR-017, `tests/unit/test_ssrf_guard.py` |
| XSS | Only http(s) URLs become hrefs (`safeUrl`); server drops non-http(s) item URLs at ingest; Markdown rendered to React nodes (no raw HTML) | ✅ `apps/web/lib/safe-url.ts` + test |
| XML | OPML parsed with defusedxml (no DTD/entities) | ✅ `test_opml_import` |
| Files | Assets served only from `data/assets` (path traversal blocked); uploads: PDF magic check, 20 MB cap | ✅ `routers/studio.py`, `routers/capture.py` |
| Secrets | Only in `.env` (git-ignored); `.env.example` documents keys; **no LLM API keys at all** (ADR-001) | ✅ |
| Secrets | Backups pass DB password via `PGPASSWORD` (never argv), errors scrubbed, dumps 0600 / dirs 0700; MCP config has no credentials and is 0600 | ✅ ADR-017/020 fixes |
| Privacy | Raw-material bank + VANCO context excluded from Ask and exports unless explicitly included; VANCO context is not sent to the LLM by default | ✅ `test_export_opens_cleanly_in_obsidian` |
| Privacy | No personal data in URLs or User-Agent (`SIGNAL/0.1 …`) | ✅ `test_user_agent_is_generic` |
| Publishing | Never auto-posts; Hashnode API only behind flag + token + Ready + per-post confirm | ✅ `test_hashnode_publish_requires_explicit_approval` |
| Truthfulness | Verbatim quote spans, claim→source fact-check, citation validator, URL whitelist, Ready gate | ✅ `signal_core/truth.py`, M2/M4 tests, evals |
| Dependencies | `pip-audit`: no known vulnerabilities (2026-11-08); `pnpm audit --prod`: no known vulnerabilities | ✅ also in CI (`.github/workflows/ci.yml`) |
| Ops | Structured JSON logs with run_id; Prometheus `/metrics`; dead-letter list; scheduler heartbeat alert | ✅ M10 |
| Residual risks | DNS rebinding between SSRF check and connect (no IP pinning); Runner mode is single-user only per Anthropic terms — do not host for others (ADR-001) | documented |
