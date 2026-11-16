# VPS News App

Private, single-user **Berlin & Germany political news digest** — twice daily (`Europe/Berlin`), English output, HITL approval on Telegram.

**Topology:** Railway workers ↔ Supabase Postgres (+ pgvector) ↔ Telegram HITL

## Architecture

```mermaid
flowchart TB
  subgraph sources [Sources]
    RSS[RSS_Atom_feeds]
    HTTP[HTTP_readability]
    PW[Playwright_fallback]
  end

  subgraph railway [Railway]
    Ingest[Ingest_worker]
    Digest[Digest_worker]
    TgWorker[Telegram_worker]
  end

  subgraph supabase [Supabase]
    DB[(Postgres_pgvector_pgmq)]
  end

  subgraph external [External_APIs]
    Anthropic[Anthropic_LLM]
    OpenAI[OpenAI_embeddings]
  end

  Owner[Owner]
  Telegram[Telegram_Bot]

  RSS --> Ingest
  HTTP --> Ingest
  PW --> Ingest
  Ingest --> DB
  Digest --> DB
  Digest --> Anthropic
  Digest --> OpenAI
  TgWorker --> DB
  TgWorker --> Telegram
  Telegram --> Owner
  Owner -->|"approve_reject_rate"| Telegram
```

## Digest pipeline

```mermaid
flowchart LR
  Collect[Collect_RSS_first] --> Embed[Embed_1536]
  Embed --> Cluster[Cluster_stories]
  Cluster --> Spine[Factual_spine]
  Spine --> Perspectives[Perspectives_by_party]
  Perspectives --> Divergence[Divergence]
  Divergence --> Events[Political_events]
  Events --> Validate[Citation_validate]
  Validate --> Preview[Telegram_preview]
  Preview --> HITL{Owner_HITL}
  HITL -->|approve| Publish[Publish]
  HITL -->|reject| Draft[Keep_draft]
  Publish --> Rate[Ratings_reliability]
```

## Docs

| Doc | Purpose |
|-----|---------|
| [project-context.md](./project-context.md) | Locked goals and decisions |
| [architecture-assessment.md](./architecture-assessment.md) | Critical review and rationale |
| [build-plan.md](./build-plan.md) | M0–M7 plan and acceptance |
| [build-spec.md](./build-spec.md) | Buildable product spec |

## Stack (locked)

- **Compute:** Railway (ingest / digest / Telegram workers)
- **DB:** Supabase Postgres + pgvector + DBOS
- **LLM:** Anthropic · **Embeddings:** OpenAI `text-embedding-3-small` (1536)
- **Collection:** RSS/HTTP first; Playwright fallback
- **Guardrails:** budgets, kill switch, citation validation, untrusted-content handling, HITL
