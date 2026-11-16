# Architecture Assessment — VPS News App

**Product:** Private, single-user Berlin & Germany political news digest agent  
**Cadence:** Twice daily, Europe/Berlin  
**Stack:** Python 3.12, Supabase Postgres + pgvector, schedules via `pg_cron`, stage hand-off via Supabase Queues (`pgmq`). Railway workers do fetching, extraction, and model calls. Telegram, Playwright fallback, OpenAI embeddings (1536 articles, 512 claims), uv/ruff/mypy/pytest. DBOS is not used. Optional local Compose for dev only.

This assessment scrutinizes the build brief against the owner's intent: **unbiased near-realtime digests**, **strong sources**, **social opinions/trends** (later), and an **agentic-first platform** for future news-source agents under guardrails.

### Owner lock-ins

| Topic | Decision |
|-------|----------|
| Database | Supabase Postgres + pgvector |
| Compute | **Railway only** (no alternate prod host) |
| Social | Phase B+; MVP contracts/tiers only |
| Cadence / realtime | Digests-only MVP; alerts backlog |
| Embeddings | OpenAI `text-embedding-3-small` @ 1536 for articles, 512 for claims |
| Orchestration | `pg_cron` + `pgmq`. DBOS is dropped |
| Scope of docs | Full M0–M7 plan kept; Railway-only compute |

---

## 1. Scope assessment

### In scope (MVP product)

| Area | Notes |
|------|--------|
| Curated German/Berlin political source collection | RSS/Atom first; selective scrape where feeds fail |
| Story clustering (embeddings + pgvector) | Dedup + multi-outlet story objects |
| Perspective briefs by party / spectrum + citations | Label-aware, neutrality-eval'd |
| Divergence analysis | Explicit “where coverage differs” |
| Political events extraction | Structured events from coverage |
| Publish: Supabase + Telegram + HITL | Owner gates before send |
| Ratings → source reliability | Closed loop |
| Guardrails | Budgets, kill switch, prompt-injection hardening, citation validation |
| Railway workers + Supabase DB | Private single-user |

### Out of scope

| Area | Why |
|------|-----|
| Public multi-tenant / dashboard UI | Brief: dashboard out |
| Social-media firehose (MVP) | Stage to Phase B+ |
| Sub-minute breaking-news ticker | Conflicts with digest + HITL + cost |
| Self-hosted prod compute / alternate hosts | Owner: Railway only |
| Multi-region HA | Overkill for private single-user |

### Complexity & risk

| Risk | Severity | Why |
|------|----------|-----|
| Source acquisition fragility | High | Blocks, ToS, paywalls, layout churn |
| “Unbiased” as product claim | High | Needs evals + process, not a model knob |
| LLM cost & latency | Medium–High | Many paid steps per run |
| Railway worker restart | Medium | Always-on poller + DBOS resume required |
| Embedding dim lock-in | Medium | Record model/dim; plan reembed |
| Prompt injection via HTML | High | Treat all fetch text as untrusted data |

**Complexity verdict:** Medium–large private systems project. Hard parts are **source reliability + neutrality + citations**, not Telegram glue.

---

## 2. Critical review of fixed decisions

Legend: **Keep** / **Change** / **Defer**

### 2.1 DBOS on Supabase + Railway

| | |
|--|--|
| **Verdict** | **Change (16 Nov 2026).** Drop DBOS. Supabase stays the system of record. Railway workers still do fetching, extraction, and model calls. Schedules are `pg_cron`. Stage hand-off is Supabase Queues (`pgmq`), one queue per pipeline stage. DBOS would be a second system on the same database doing the same job. |
| **Rationale** | Postgres already has to store articles, claims, and vectors. Queues and cron on that database give retries and backpressure without a second orchestrator. This reverses the earlier lock on DBOS. |

### 2.2 Twice-daily vs “realtime”

| | |
|--|--|
| **Verdict** | **Keep** twice-daily digests. Product language: **near-realtime scheduled digests**. **Defer** continuous ingest; alerts = backlog. |

### 2.3 Social media

| | |
|--|--|
| **Verdict** | **Defer** collectors to Phase B+. **Keep** tiers + ingest/trust contracts in MVP. Stand-in: outlet/party emphasis + divergence. |

### 2.4 Playwright

| | |
|--|--|
| **Verdict** | **Change:** RSS/HTTP first; Playwright per-source fallback only. |

### 2.5 Anthropic / embeddings

| | |
|--|--|
| **Verdict** | **Keep** Anthropic behind `LLMProvider`. **Locked** OpenAI `text-embedding-3-small` @ 1536 behind `EmbeddingProvider`; store model/dim; reembed workflow. |

### 2.6 Telegram long polling

| | |
|--|--|
| **Verdict** | **Keep.** Fits private HITL on Railway without public HTTPS. |

### 2.7 Hosting

| | |
|--|--|
| **Verdict** | **Locked:** Railway workers ↔ Supabase ↔ Telegram. Optional local Compose/`uv` for **dev only**. |
| **Risk** | Vendor outage / secret leak — kill switch, least-privilege DB role, Railway secrets. |

### 2.8 OTel / HITL reliability

| | |
|--|--|
| **OTel** | **Keep** trace IDs; collector optional. |
| **HITL + ratings** | **Keep** as core loop for operational neutrality. |

---

## 3. Verdict summary

### Keep

- Private single-user, HITL Telegram gate  
- Twice-daily Europe/Berlin digests  
- Cluster → perspectives → divergence → events  
- DBOS replaced by pg_cron + Supabase Queues; budgets, kill switch, citation validation stay  
- pgvector + OpenAI 1536 embeddings  
- Anthropic via `LLMProvider`  
- Railway + Supabase  
- Full M0–M7 (agent sockets in M7)  
- Dashboard out of scope  

### Change vs brief

| Brief | Revision |
|-------|----------|
| Playwright-default | RSS/HTTP first |
| “Realtime” | Near-realtime scheduled digests |
| Self-host / ambiguous compute | **Railway workers only** + Supabase DB |
| Social absent | Contracts/tiers now; collectors later |
| Embedding dim implicit | OpenAI 1536 + metadata + reembed |
| Monolithic agent | Platform contracts stubs → M7 |

### Defer / backlog

- Social collectors  
- Priority alerts / continuous timeline  
- Dashboard  
- Second LLM provider  
- Fancy observability beyond OTel-lite  

---

## 4. Agentic-first foundation (kept for M7)

Later agents become **news sources** under guardrails — not unsupervised publishers.

| Contract | Purpose |
|----------|---------|
| `SourceAdapter` | Pull articles/signals with rate limits + allowlists |
| `IngestAPI` | Authenticated ingest with provenance; quarantine by default |
| `TrustRegistry` | Reliability / strikes; agents cannot self-raise trust |
| `BudgetLedger` | Per-run and per-agent caps; kill switch |
| `NeutralityPolicy` | Labeled perspectives; social/agent tiers never silent factual spine |

---

## 5. Sources & quality

1. Seed curated DE/Berlin reporting + official + labeled party opinion  
2. RSS-first; HTTP readability; Playwright only when needed  
3. Corroboration: ≥2 reporting-tier sources preferred for digest inclusion  
4. Ingest German; digest English; citations stay grounded  
5. Owner ratings adjust `source_reliability`  

Social opinions/trends: Phase B+ as `social_signal` tier only.

---

## 6. Phases

- **Phase A (M0–M7):** Digest core on Railway + Supabase + Telegram; agent contract stubs → M7  
- **Phase B:** Alerts + first social/curated-channel adapters  
- **Phase C:** Wider social; mature reembed ops  

---

## 7. Bottom line

Ship a **near-realtime, RSS-first, contract-ready digest platform** on **Supabase (DBOS + pgvector) + Railway + Telegram**. Keep full M0–M7. Social firehose and continuous realtime stay backlog — not silent omissions.
