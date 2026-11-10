# Benchmark label spot check (ADR-026)

Thirty randomly chosen relevance labels written by Claude (`bench_label_items`, balanced tier) for the real-data benchmark. They are model judgements used only to measure SIGNAL's engines and are never shown as facts in the product. Please mark each row `y` (you agree) or `n` (you don't), and add a note if useful. If more than about 5 of 30 are `n`, the labeller prompt needs work before the benchmark numbers are trusted.

Scale: 3 must-read · 2 relevant · 1 tangential · 0 irrelevant. Ring: core / adjacent / wide / none.

| # | Item title | Source | Date | Label | Ring | Labeller's reason | agree? (y/n) |
|---|---|---|---|---|---|---|---|
| 1 | Flint-interactive: A language for creating interactive data visualizations | Microsoft Research | 2026-10-22 | 1 tangential | core | Visualization language for AI agents; niche, tangential to his focus. |  |
| 2 | Formally verifying agent-written full-stack web apps with PDD Kit | Microsoft Research | 2026-11-05 | 3 must-read | core | Formal verification of agent-written code to avoid line-by-line review; directly addresses coding agent code review. |  |
| 3 | Amazon will let you text Alexa your shopping list | The Verge AI | 2026-11-06 | 0 irrelevant | wide | Consumer Alexa shopping-by-text feature; product news with no engineering relevance. |  |
| 4 | LoopVQ: Sub 1-bit KV Cache Quantization for Looped Transformers | HF Daily Papers | 2026-11-03 | 2 relevant | core | Sub-1-bit KV cache quantization for looped transformers; directly inference/quantization, though architecture-specific. |  |
| 5 | Set per-user budgets on AI Gateway | Vercel Blog | 2026-08-31 | 1 tangential | core | Minor AI Gateway per-user budget changelog; mentions coding agent spend control but product feature. |  |
| 6 | Open source project fools AI scrapers with poisoned font | The Register AI | 2026-07-30 | 1 tangential | wide | Poisoned font against LLM scrapers; mildly interesting novelty, not his core work. |  |
| 7 | Random Is Almost Enough? Stable and Low-Cost Benchmark Compression via BestRand | HF Daily Papers | 2026-10-30 | 2 relevant | core | Cheap, stable benchmark compression for model evaluation; practical for eval cost. |  |
| 8 | Cutting our inference bill by 68% by being obsessive about optimization | Cloudflare Blog | 2026-10-19 | 3 must-read | core | Concrete AI code reviewer inference cost cut 68% via prompt caching and model routing; directly production LLM engineering. |  |
| 9 | ClusterMAX 3.0: The Industry Standard GPU Cloud Rating System Returns | SemiAnalysis | 2026-09-23 | 2 relevant | adjacent | GPU cloud provider ratings covering reliability, performance and security; useful for choosing GPU infrastructure. |  |
| 10 | Everything is an AI scam now | Hacker News Best | 2026-11-04 | 1 tangential | wide | Opinion title on AI scams; no text, thin. |  |
| 11 | Experts say the new Democratic congressional majority will likely seek to rebuild CISA, prioritize AI security | Techmeme | 2026-11-06 | 1 tangential | adjacent | US politics on CISA and AI security policy; general, not engineering-focused. |  |
| 12 | Online Learning with Ordered Experts (via Two-point Feedback) | arXiv cs.CL/LG/AI/SE/IR | 2026-11-05 | 0 irrelevant | wide | Theoretical online learning with ordered experts; no engineering relevance. |  |
| 13 | Autobase 2.12 released | PostgreSQL News | 2026-11-05 | 1 tangential | core | Postgres management tool release with monitoring dashboards; minor changelog, tangential to his Postgres stack. |  |
| 14 | AI Engineer 2025 - Improving RecSys & Search with LLM techniques | Eugene Yan | 2025-06-04 | 1 tangential | core | 2025 talk summary on LLMs in recsys and search; one-line, dated, only partly relevant. |  |
| 15 | A statement from Dario Amodei on Anthropic's commitment to American AI leadership | Anthropic News | 2025-10-21 | 0 irrelevant | adjacent | Political statement on American AI leadership; no engineering content. |  |
| 16 | How to Match LLM Patterns to Problems | Eugene Yan | 2023-08-13 | 1 tangential | core | 2023 LLM patterns post; dated and thin summary. |  |
| 17 | Southeast Asia’s digital economy to hit $368 billion | Google AI Blog | 2026-10-21 | 0 irrelevant | wide | Southeast Asia digital economy report; not relevant to AI engineering. |  |
| 18 | Gemini 3.1 Pro: A smarter model for your most complex tasks | Google DeepMind Blog | 2026-02-19 | 2 relevant | core | Gemini 3.1 Pro model release; LLM release relevant though text is thin marketing. |  |
| 19 | How GLM5.3 Sparse Attention Affects HBM Memory Usage | SemiAnalysis | 2026-09-28 | 3 must-read | core | Sparse attention, KV cache offloading and HBM usage in GLM-5.3; directly about inference serving. |  |
| 20 | Axiom Math wants to keep AI slop out of mathematics | TechCrunch AI | 2026-11-05 | 1 tangential | wide | Startup's AI agents formally verify math proofs; niche domain, tangential to production LLM engineering. |  |
| 21 | Meta shakes up the frontiers, open and closed | Interconnects | 2026-10-17 | 3 must-read | core | Meta Muse Spark Open, Reflection Beam, Mistral Large 4: major open-weight model releases shifting the frontier. |  |
| 22 | Baidu Releases ERNIE 5.5 Flash Base: A 280B MoE Base Model With 14B Active Parameters | MarkTechPost | 2026-11-05 | 2 relevant | core | Baidu releases 280B MoE base checkpoint, 14B active; open-weights LLM release useful for fine-tuning. |  |
| 23 | Part 6: An operating system for coding agents: the disciplined build | Stack Overflow Blog | 2026-10-07 | 3 must-read | core | Practical configs and rules to keep coding agent quality across long-lived repos; directly actionable. |  |
| 24 | Measuring the Impact of Personalized Recommendations | Netflix Tech Blog | 2026-10-14 | 1 tangential | wide | Recommender system causal measurement at Netflix; ML-adjacent but outside his focus. |  |
| 25 | 'It's just vape, nail, charity shops': Can anything save UK high street? | Hacker News Top | 2026-11-04 | 0 irrelevant | none | UK high street retail article; not tech. |  |
| 26 | How Commerce.com and Cloudflare are getting storefronts ready for AI agents | Cloudflare Blog | 2026-10-21 | 2 relevant | core | WebMCP for agent shopping across 100k stores; relevant to MCP and agent tooling. |  |
| 27 | AI for Food Allergies | Hugging Face Blog | 2025-10-16 | 0 irrelevant | wide | AI for food allergies; off-focus domain application, no text. |  |
| 28 | How Amazon Marketplace evaluates content quality with Amazon SageMaker AI | AWS Machine Learning Blog | 2026-11-05 | 1 tangential | core | Amazon internal content-quality ML pipeline on SageMaker; classical ML, not his focus. |  |
| 29 | Estuary Expands PostgreSQL CDC with Targeted Backfills and Scalable Discovery | PostgreSQL News | 2026-10-28 | 1 tangential | core | Postgres CDC connector vendor update; somewhat promotional, mildly relevant to backend data pipelines. |  |
| 30 | What I learned from looking at 900 most popular open source AI tools | Chip Huyen | 2024-03-14 | 1 tangential | core | Old 2024 survey of open-source AI repos; only updated note points to a repo list. Mildly useful. |  |
