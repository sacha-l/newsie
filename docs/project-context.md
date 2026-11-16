# Project context — VPS News App

Lasting goals, constraints, and decisions.  
Details: [architecture-assessment.md](./architecture-assessment.md) · [build-plan.md](./build-plan.md) · [build-spec.md](./build-spec.md)

## Goals

Newsie is an event-centred desk. See [product.md](./product.md).

- Private single-user English reading of **German/Berlin political events** (2×/day, `Europe/Berlin`)
- Group reporting by occurrence, not by a lone embedding, and record why an article joined
- Keep claims inspectable: passage, support relation, and an evidence state rather than a truth score
- Describe a collected sample. Do not infer ideology from a publisher, or public opinion from volume
- Human approval before anything is published
- Agentic ingest stays a quarantined source tier, never an authority for facts

## Constraints

- No public dashboard (out of scope)
- Python 3.12, pgvector, pg_cron, pgmq, Telegram HITL, model calls behind LLMProvider
- Owner approval required before publish
- The application in this repo is the MVP path: ingest, event resolution, a cited brief, and human approval

## Locked decisions (owner + architecture)

| Topic | Decision |
|-------|----------|
| Database | **Supabase Postgres + pgvector** (existing subscription) |
| Compute | **Railway** workers (ingest / digest / Telegram) only |
| Local/dev | Optional Compose / `uv run` against Supabase (not a prod path) |
| Social collectors | **Later (Phase B+)**; MVP lands tiers + ingest/trust contracts only |
| Cadence | Twice-daily digests; freshness at run time. Alerts = Phase B backlog |
| Collection | RSS/HTTP first; Playwright fallback only |
| LLM | Anthropic behind `LLMProvider` |
| Embeddings | **OpenAI `text-embedding-3-small` (1536-d)**; model/dim recorded; reembed workflow planned |
| Parties (default) | CDU/CSU, SPD, Grüne, FDP, Die Linke, AfD, BSW, Other/Institutional |
| Access | Telegram HITL + Railway/Supabase consoles |
| Agentic | SourceAdapter + IngestAPI + TrustRegistry + budgets (stubs → M7) |
| Milestones | Full **M0–M7** (see build-plan) |

## Still soft (non-blocking; stub until set)

- Exact seed outlet list (spec has a starter set)
- Monthly LLM/embed budget ceiling (enforce via config caps; tune after first week)
- Telegram bot token / Supabase project / Railway service when build starts

## Backlog (explicit)

Social collectors · priority alerts · continuous timeline · dashboard · second LLM provider

## Non-goals (MVP)

Publisher ideology scores · auto-publish · multi-tenant · a knowledge graph · treating article volume as public opinion
