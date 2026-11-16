# Build Spec — VPS News App

Buildable product specification for implementation.  
Incorporates the original brief plus **accepted architecture revisions** from [architecture-assessment.md](./architecture-assessment.md).  
Plan/milestones: [build-plan.md](./build-plan.md). Context: [project-context.md](./project-context.md).

**Deviation markers:** Lines tagged `[DEVIATION]` differ from the original brief.

---

## 1. Product overview

### 1.1 Purpose

Private, single-user system that produces an **unbiased English-language political news digest** focused on **Germany and Berlin**, twice daily (`Europe/Berlin`), with:

- Multi-source collection and story clustering  
- Citation-backed factual spine  
- Perspective briefs by party/spectrum  
- Divergence analysis  
- Political events extraction  
- HITL approval via Telegram before publish  
- Ratings that feed source reliability  
- Platform contracts so later agents can act as news sources under guardrails  

### 1.2 Non-goals

- Public multi-tenant SaaS / web dashboard  
- Auto-publish without HITL  
- Treating social signals as factual reporting  
- Sub-minute realtime ticker `[DEVIATION: near-realtime scheduled digests]`  
- Social firehose in MVP `[DEVIATION: Phase B+]`  
- Self-hosted / alternate prod compute `[DEVIATION: Railway only]`  

### 1.3 Primary user

Owner only. Interfaces: Telegram bot + Railway/Supabase consoles.

---

## 2. System overview

```
┌──────────────────────── Railway ────────────────────────────┐
│  ingest worker │ digest worker │ telegram worker (DBOS)     │
└────────┬───────────────┬──────────────────┬─────────────────┘
         │               │                  │
         ▼               ▼                  ▼
┌────────────────── Supabase ──────────────────┐
│  Postgres + pgvector + DBOS tables + app data │
└───────────────────────▲──────────────────────┘
                        │ IngestAPI (auth; future agents)
   RSS/HTTP(S)          │ Anthropic │ OpenAI embeddings
   Playwright fallback  │           │
                        ▼
              Owner Telegram (HITL)

Dev (optional): local Compose / uv run against Supabase
```

**Cadence:** Twice daily, `Europe/Berlin` (configurable).  
**Freshness:** `ingest_lookback_hours` default 18.

---

## 3. Components

| Component | Responsibility |
|-----------|----------------|
| `config` | Env: TZ, budgets, models, dims, schedule, allowlists |
| `source_registry` | Curated sources, tiers, reliability, adapter type |
| `adapters.rss` | Default collector |
| `adapters.http` | Page fetch + readability |
| `adapters.playwright` | Fallback per source flag `[DEVIATION: not default]` |
| `ingest_api` | Authenticated ingest for future agents |
| `embedder` | `EmbeddingProvider` (OpenAI 1536) |
| `clusterer` | pgvector similarity → stories |
| `digest_brain` | Spine, perspectives, divergence, events via `LLMProvider` |
| `citations` | Validator: claims ↔ sources |
| `publisher` | Telegram send on approve |
| `hitl` | Approve / reject / rate |
| `trust` | Reliability aggregation, quarantine promotion |
| `budgets` | Token/fetch/playwright ledgers |
| `killswitch` | Global abort |
| `evals` | Neutrality label-swap + citation fixtures |
| `otel` | Trace IDs; collector optional |

---

## 4. Stack (normative)

| Layer | Choice |
|-------|--------|
| Language | Python 3.12 |
| Packaging | uv |
| Quality | ruff, mypy, pytest |
| Models / validation | Pydantic for configs and structured LLM I/O |
| Orchestration | DBOS on Supabase Postgres |
| Database | **Supabase Postgres + pgvector** |
| App host | **Railway** (prod); optional local Compose/`uv` for **dev only** |
| Messaging | Telegram Bot API long polling |
| LLM | Anthropic via `LLMProvider` |
| Embeddings | OpenAI `text-embedding-3-small`, dim **1536** |
| Browser | Playwright **fallback only** |
| Observability | Structured logs + OTel traces |

### 4.1 Supabase

- System of record for app data + DBOS  
- Enable pgvector  
- Pooler connection from Railway; least-privilege worker role  
- PITR/backups; restore drill in M0  

### 4.2 Railway

- Always-on service(s) for Telegram polling + DBOS workers  
- Secrets: Anthropic, OpenAI, Telegram, Supabase URL/key, kill switch  
- Playwright only if a source requires it  

---

## 5. Data model notes

```
sources (
  id, name, homepage_url, feed_url,
  adapter: rss|http|playwright|agent,
  tier: reporting|official|opinion|social_signal|agent_derived,
  spectrum_tags[], language, enabled,
  reliability_score, strike_count,
  trust_state: quarantine|probation|trusted|disabled,
  rate_limit_per_hour
)

articles (
  id, source_id, url, canonical_url, title, byline,
  published_at, retrieved_at, content_text, content_hash,
  lang, tier_at_ingest, raw_metadata jsonb, quarantine_reason
)

article_embeddings (
  article_id, embedding vector(1536),
  embedding_model, embedding_dim, embedded_at
)

stories (id, fingerprint, first_seen_at, last_seen_at, corroboration_score, title_hint, status)
story_articles (story_id, article_id, similarity)

digest_runs (id, scheduled_for, started_at, finished_at, status, kill_switch_hit, budget_snapshot jsonb)
digest_drafts (
  id, run_id, story_ids[],
  spine_md, perspectives_json, divergence_md, events_json,
  citations_json, english_render_md, validation_status, created_at
)
publications (id, draft_id, approved_at, telegram_message_ids[], immutable_snapshot jsonb)

owner_actions (id, at, kind, payload jsonb)
source_ratings (source_id, at, score, note)

agent_registrations (id, name, token_hash, trust_state, budget_caps jsonb, created_at)
ingest_batches (id, agent_id, accepted, rejected, at)

budget_ledger (id, at, dimension, amount, run_id, agent_id null)
kill_switch (id=1, engaged bool, reason, engaged_at)
```

---

## 6. Workflows

### 6.1 `scheduled_digest` (DBOS)

1. Check kill switch  
2. Ingest enabled sources  
3. Embed new articles  
4. Cluster / update stories  
5. Select top stories  
6. Per story (budget-capped): spine → perspectives → divergence → events  
7. Validate citations  
8. Assemble draft  
9. Telegram preview → await HITL  

### 6.2 `hitl_approve`

Re-check kill switch + validation → send → write `publications` snapshot.

### 6.3 `ingest_agent_push` (M7)

Auth agent → validate → force non-reporting tier → quarantine → budget ledger.

### 6.4 `reembed_all` (ops)

Write new model/dim vectors; swap config pointer after completion.

---

## 7. Agent / platform contracts

### 7.1 `SourceAdapter`

```python
class SourceAdapter(Protocol):
    def fetch(self, source: Source, ctx: FetchContext) -> list[ArticleCandidate]: ...
```

### 7.2 Ingest API

`POST /v1/ingest/articles` with bearer token; provenance required; agents cannot set `tier=reporting`, cannot publish, cannot self-trust.

### 7.3 Trust promotion

Owner-only; automated demote on strikes.

### 7.4 Neutrality

- Spine: reporting/official tiers only  
- Perspectives labeled by party/spectrum  
- Social/agent tiers under explicit signal sections only  
- Label-swap evals for release  

Default parties: `CDU/CSU, SPD, Grüne, FDP, Die Linke, AfD, BSW, Other/Institutional`

---

## 8. Security

| Control | Spec |
|---------|------|
| Trust boundary | Fetched content = untrusted data |
| Secrets | Railway/env; not in git |
| Egress | Deny-by-default allowlist for sources + LLM/embed APIs |
| Kill switch | DB + env; checked at workflow start and before publish |
| Budgets | Hard stop on caps |
| HITL | No publish without approve |
| Prompt injection | Regression fixtures |
| Citation integrity | Validator before approve |

---

## 9. Sourcing strategy

| Class | Tier | Examples (illustrative) |
|-------|------|-------------------------|
| Public broadcasters | reporting | Tagesschau/ARD, ZDF, Deutschlandfunk, rbb |
| National press | reporting | Seed mix across spectrum |
| Berlin local | reporting | Tagesspiegel, Berliner Zeitung, rbb Berlin |
| Official | official | Bundesregierung, Bundestag, Berlin Senate |
| Party communications | opinion | Party sites/feeds (labeled) |

**Collection:** RSS → HTTP+readability → Playwright if configured.  
**Ranking:** `freshness * corroboration * reliability * tier_weight`.  
**Phase B+:** social adapters, priority alerts — out of M0–M7 acceptance.

---

## 10. Config defaults

| Key | Default |
|-----|---------|
| `DIGEST_TZ` | `Europe/Berlin` |
| `DIGEST_CRON` | ~07:30 and ~18:30 local (configurable) |
| `INGEST_LOOKBACK_HOURS` | `18` |
| `MAX_STORIES_PER_DIGEST` | `8` |
| `EMBEDDING_MODEL` | `text-embedding-3-small` |
| `EMBEDDING_DIM` | `1536` |
| `PLAYWRIGHT_ENABLED` | `false` globally; per-source opt-in |
| `DATABASE_URL` | Supabase Postgres (pooler) |

---

## 11. Milestones (M0–M7)

| Milestone | Done when |
|-----------|-----------|
| M0 | Supabase+pgvector+DBOS health; Railway stub; kill switch; restore drill; CI green |
| M1 | RSS ingest + provenance + rate limits; Playwright optional pilot |
| M2 | OpenAI 1536 embeddings + clustering + corroboration |
| M3 | Full draft artifacts + citation validator + budgets accounted |
| M4 | Telegram HITL on Railway + schedule + Supabase publish records |
| M5 | Ratings→reliability; neutrality evals gating releases |
| M6 | Hard budgets, injection suite, egress allowlist; ops runbook |
| M7 | Agent ingest + trust isolation contract tests |

---

## 12. Definition of done (MVP through M7 core path)

1. Twice-daily English digests of DE/Berlin politics from curated sources  
2. Spine + perspectives + divergence + events with validated citations  
3. Owner must approve in Telegram before send  
4. Reject/rate flows persist and affect reliability  
5. Kill switch and budget hard-stops work  
6. Prompt-injection and citation fixtures pass  
7. IngestAPI accepts a fixture agent into quarantine without publish rights  
8. Ops: Supabase restore documented and drilled once  
9. Prod path: **Railway workers ↔ Supabase DB ↔ Telegram**  

---

## 13. Deviations from original brief

| Brief | Spec |
|-------|------|
| Playwright-centric collection | RSS/HTTP first; Playwright fallback |
| Ambiguous / self-host compute | **Railway workers + Supabase DB** |
| Social not specified | Tiers + contracts now; collectors Phase B+ |
| Realtime wording | Near-realtime scheduled digests; alerts backlog |
| Anthropic direct | Behind `LLMProvider` |
| Embedding dim implicit | OpenAI 1536 + reembed workflow |
| Monolithic pipeline | Agentic contracts M1→M7 |

---

## 14. Engineer quickstart (M0)

1. Create app repo; Python 3.12 + uv  
2. Wire Supabase: pgvector, migrations, `DATABASE_URL`  
3. Optional local Compose/`uv run` against Supabase  
4. Config + kill switch  
5. DBOS sample workflow on Supabase  
6. Stub Railway service (healthcheck)  
7. ruff/mypy/pytest in CI  
8. `ops/RESTORE.md` for Supabase restore  
9. Do not block M0 on Playwright, social, or Anthropic  

**Ready to build** once secrets/project IDs are available (see [build-plan.md](./build-plan.md)).
