# SIGNAL — user guide

SIGNAL turns the tech firehose into four things: **RADAR** (what matters, and why), **STUDIO** (posts in your voice, with zero invented facts), **LAB** (what to build or try) and **GYM** (skills that compound). Ten minutes a day.

## Your daily loop (≈ 10 min)
1. **07:30**: the app's bell and **Today** page show that your brief is ready (and, if you turned them on, a browser notification).
2. **Brief** (`/brief`): 5–7 stories, never more. Keys: `j`/`k` move, `u` useful, `x` skip, `p` post, `b` build, `l` learn, `o` open. Each story has badges (Core/Adjacent, UPDATE, hype verdict, durability) and "Why it matters to you". Press **Mark brief done**.
3. **One action**: Post (Studio), Build (Lab) or Learn (Gym).
4. **Cards**: review the flashcards that are due (Gym → Cards).
Short on time? **2-minute mode** on Today (read the top 3 one-liners) still counts. Streaks have 2 freezes a month, and nobody nags you.

## Screens
| Screen | What it does |
|---|---|
| **Today** | Progress ring (brief → action → cards), streak, brief summary, post suggestion, build spark, learn item, cards due, "This month" outputs, capture box |
| **Brief** | The daily, weekend or "While you were away" brief, quick hits, triggered watches, feedback buttons |
| **Story page** | What happened, with footnoted citations, why it matters to you, what changes, hype check, durability, moat note, open questions, timeline of sources, "Why am I seeing this?" scores, regenerate, report inaccuracy |
| **Studio** | Pipeline Kanban, calendar with weekly goals, series, raw-material bank, voice settings and reference posts, quote/stat cards. The **draft editor** has angles, ask-me questions, live AI-tell highlights and counters, a strict scorecard, fact-check per claim, versions with diff, repurpose, approve (Ready gate), schedule and publish-assist |
| **Lab** | Idea Kanban (spark → shortlisted → validating → building → shipped), idea page with evidence, prior art, scores, build-brief zip for Claude Code, and a build log that can seed posts |
| **Gym** | Skill map with self-ratings, learn-next with plans, explainers (plain / engineer / deep), full-screen card review (FSRS), weekly quiz, progress and the fundamentals/churn split |
| **Moat Radar** | Monthly: what's commoditising vs appreciating, 3 things to know, learn and stop, where defensibility moves, and a predictions scorecard |
| **Ask** | Chat with everything you've ingested, with citations. It says "Not in your knowledge base" when it doesn't know. Supports /compare, /timeline, /explain, /whatchanged, and "turn into" post / idea / card / note |
| **Library** | Saved items, notes and highlights (→ flashcards), and export (Obsidian vault, JSON, CSV) |
| **Reviews** | Guided weekly (Sunday) and monthly (1st) reviews, with a PDF for the monthly |
| **Analytics** | Your posts vs your baseline, breakdowns by hook, length and time, one-variable experiments, and monthly learnings that you accept into a new voice version |
| **Settings** | Profile, topics and weights, sources (health, OPML), routines (cron builder), watches, channels (in-app, browser notifications, email) and quiet hours, security (password, 2FA, API token), feature flags |
| **Ops** | Health, runs, LLM ledger, costs vs budget, evals, engine quality (benchmark), source health, dead letters |

## Writing with Studio (the never-invent rule)
- Every factual line in a draft must trace to a stored source or to your **raw-material bank**. Personal stories come only from what you saved or typed into the ask-me questions. If you skip a question, the draft won't pretend you have that experience.
- A draft can't reach **Ready** while it has banned phrases or em dashes, unsupported or uncited claims, high safety flags, or copied passages. You can override with a written reason; the reason is stored.
- SIGNAL never posts for you. Publish-assist copies the text and opens the composer; you post, then paste the URL so metrics can be tracked at +48 h and +7 d.

## Capture from anywhere
Paste a URL or note on Today or `/capture`, use the PWA share target (install SIGNAL first), or call `POST /api/capture` with your API token (Settings → Security) from a bookmarklet.

## Everything happens in the app
- **Notifications** are in-app: the bell shows a new brief, weekly/monthly review, instant watch hits and due cards. Email digests (weekly/monthly) are optional in Settings → Channels.
- **Browser notifications** (Settings → Channels): a per-device opt-in. While a SIGNAL tab or the installed app is open, new briefs, watch hits and due cards also pop up as system notifications. Nothing goes through a third-party push service.
- **Install SIGNAL** as an app: Chrome/Edge offer it on Today ("Install SIGNAL" card), or use the browser's install menu. Dismiss the card to hide it.
- **Demo data badge:** the sidebar (and the mobile top bar) says **Demo data** when SIGNAL runs in mock mode on fictional fixtures, and shows a small **Live** dot otherwise. **Degraded** appears when the latest brief was assembled with some analysis unavailable.

## When something looks wrong
- Use **Report inaccuracy** on any generated block: brief story cards, story insights, explainers, Ask answers, Lab ideas and the draft fact-check. It feeds the evals set (Ops → Evals counts the reports). "Why am I seeing this?" shows every sub-score behind a story's rank.
- **How this brief was made** (bottom of the Brief page): sources scanned, items in the window, how many passed the prefilter, stories considered and shown, the AI calls and models used for that brief's run, citations verified, degraded yes/no and when it was generated (IST).
- **Ops → Engine quality** shows the latest real-data benchmark (prefilter, clustering, ranking, Ask) and your label spot-check agreement. **Run benchmark** recomputes it in the background (a few minutes).

## Security
- Change the admin password in **Settings → Security** (current password required, at least 12 characters). A banner reminds you while the password is still the `.env.example` placeholder.
