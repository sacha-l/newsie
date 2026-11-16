# newsie — feature log

Living backlog for the Berlin & Germany political digest app.  
Update this file when something ships or when you want to capture a new idea (no need to open a ticket first).

**Status:** `shipped` · `in_progress` · `planned` · `idea`

---

## Shipped (this repo)

| Feature | Status | Notes |
|--------|--------|--------|
| Offline demo pipeline (fixture sources, hash embeddings, stub LLM) | shipped | `uv run newsie demo` |
| Digest spine: collect → embed → cluster → draft | shipped | `src/newsie/pipeline.py` |
| Loop guardrails + budget ledger | shipped | `guardrails.py` |
| HITL approve path (no publish without approval) | shipped | `hitl.py` |
| Citation validation hook | shipped | `citations.py` |
| FastAPI web UI (fixture digest) | shipped | `uv run newsie web` |
| Live RSS ingest + HTTP adapter | shipped | `adapters/rss.py`, `http_adapter.py` |
| SQL persistence (Phase 2) | shipped | `sql_store.py`, `migrations/001_init.sql` |
| Agent ingest API (`agent_derived` tier enforced) | shipped | `ingest_api.py` |
| Seed source registry (YAML) | shipped | `data/seed_sources.yaml` |

---

## Planned (your queue)

### Social trends cron (Grok API)

- **Status:** planned  
- **Goal:** Scheduled job that queries social feeds and trends via the **Grok API** to add real-time-ish signal on news topics and **sentiment** alongside RSS ingest.  
- **Notes:**  
  - Runs on a cron schedule (align with digest TZ: `Europe/Berlin`; exact cadence TBD — likely between twice-daily digests or as a lighter poll).  
  - Output should land as structured insights (topic, sentiment sketch, sample posts/links) tied to story clusters or digest sections—not raw social HTML in the LLM context without normalization.  
  - Respect existing guardrails: budgets, kill switch, untrusted content, no auto-publish.  
- **Open decisions:** rate limits, which platforms Grok can see, retention in Supabase, how sentiment merges into M3 digest steps.

### Configure sources

- **Status:** planned  
- **Goal:** Owner-facing way to **add, edit, disable, and tag** sources without editing YAML by hand.  
- **Scope ideas:**  
  - CRUD on `sources` (URL, adapter type, tier, spectrum tags).  
  - Validate feed URL before save (dry-run ingest).  
  - Optional import/export of `seed_sources.yaml`.  
- **Depends on:** stable M1 ingest + DB registry (partially in repo via SQL + seed file).

### (add next)

- **Status:** idea  
- **Goal:** _your third bullet—fill in when ready._

---

## Backlog (architecture plan M0–M7)

From [docs/build-plan.md](./docs/build-plan.md). Not all are tracked as separate rows until we pick them up.

| Area | Milestone | Summary |
|------|-----------|---------|
| Railway workers + Supabase production wiring | M0 | Always-on ingest/digest/Telegram on Railway |
| Playwright fallback adapter | M1 | When RSS/HTTP is not enough |
| pgvector + OpenAI `text-embedding-3-small` | M2 | Production embeddings + clustering |
| Anthropic digest brain + full citation validator | M3 | Replace stub LLM in prod |
| Telegram HITL (approve / reject / rate) | M4 | Primary publish path |
| Ratings → source reliability loop | M5 | Feedback into weights |
| Hardening (budgets, injection tests, restore drill) | M6 | Prod safety |
| Agentic ingest/trust contracts | M7 | External agent sockets |

**Explicit backlog (post-MVP):** social collectors (Grok cron above), priority alerts, continuous listen mode, owner dashboard.

---

## How to use this file

1. Move a row from **Planned** → **Shipped** when the feature is merged and usable.  
2. Add bullets under **Open decisions** when you learn something in implementation.  
3. Keep one-line “Goal” statements so agents and future-you know the *why*.