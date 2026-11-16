# Agent rules (newsie)

Assume contributors are agents that copy the nearest example. Prefer architecture that makes the wrong path fail.

| Rule | Enforcement |
|------|-------------|
| Fetched content is untrusted data | Adapters return text only; no `exec`/`eval` of content |
| Ingest is idempotent by `content_hash` | `MemoryStore.save_article` / `content_hash()` |
| Loops must be bounded | `LoopGuard` + settings caps |
| Paid work is budgeted | `BudgetLedger.charge` hard-stops |
| No publish without HITL | `approve_draft` only path to `publications` |
| Agents cannot set reporting tier | `ingest_api` forces `agent_derived` |
| Embedding dim must match config | `embed_articles` raises on mismatch |
| Prefer smallest change | pstack `laziness-protocol` |

pstack skills referenced: `architect`, `correct`, `principle-make-operations-idempotent`, `principle-laziness-protocol`, `principle-guard-the-context-window`.
