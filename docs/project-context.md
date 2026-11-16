# Project context — VPS News App

Lasting goals, constraints, and decisions.  
Details: [architecture-assessment.md](./architecture-assessment.md) · [build-plan.md](./build-plan.md) · [build-spec.md](./build-spec.md)

## Goals

- Private single-user **near-realtime** English digests of **German/Berlin political news** (2×/day, `Europe/Berlin`)
- **Unbiased by process:** citation-backed spine, labeled perspectives, divergence, evals, HITL
- **Agentic-first:** contracts so later agents can contribute as news sources under trust, provenance, budgets, neutrality
- Later: social opinions/trends as an explicit **signal tier**, not factual spine

## Constraints

- No public dashboard (out of scope)
- Python 3.12, DBOS, pgvector, Telegram HITL, Anthropic primary LLM
- Owner approval required before publish
- No application repo yet — docs only until build starts

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

Dashboard · social firehose · auto-publish · multi-tenant · HA multi-region · self-hosted prod compute
