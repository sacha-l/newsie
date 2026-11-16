# Build Plan — VPS News App

Aligned with the brief's M0–M7, revised per [architecture-assessment.md](./architecture-assessment.md).

Phases 1–5 are implemented in the tree. What still needs a live corpus, and is not marked done: a week of clean ingest, a measured wire-copy rate, clustering scored on 30 hand-checked stories, and the label rule beating an outlet-count baseline on 100 audited sentences. `newsie report` scores only the constructed label file.

---

## Guiding principles

1. **Guardrails before cleverness** — budgets, kill switch, untrusted-content handling, and HITL land early.  
2. **RSS-first, Playwright fallback** — earn scrape complexity.  
3. **Contracts before social agents** — ingest/trust/provenance stubs in Phase A; complete in M7.  
4. **Digest quality > faux realtime** — twice-daily primary; alerts later.  
5. **Boring managed ops** — Supabase backups + Railway always-on workers; restore drill is acceptance criteria.

---

## Phase map vs brief milestones

| Brief | Plan | Focus |
|-------|------|--------|
| M0 | **M0** Foundation | Repo, Supabase wiring, config/secrets, OTel-lite, kill switch, Railway stub; optional local Compose for dev |
| M1 | **M1** Ingest | Source registry, RSS adapters, optional Playwright, provenance, quarantine |
| M2 | **Phase 3** Origins and clustering | Stable story ids, origin detection, centroid assignment. Replaces the old corroboration score. |
| M3 | **Phases 4–5** Claims and synthesis | Claim extraction, evidence labels, span citations, per-story views. |
| M4 | **M4** Publish HITL | Telegram long polling on Railway, approve/reject/rate, publish records in Supabase |
| M5 | **M5** Reliability loop | Ratings → source weights; neutrality label-swap evals in CI/nightly |
| M6 | **M6** Hardening | Budgets enforced, prompt-injection tests, egress allowlist, restore drill |
| M7 | **M7** Agentic sockets | SourceAdapter / IngestAPI / TrustRegistry contract tests for future agents |
| — | **Backlog** | Social collectors, priority alerts, continuous listen, dashboard |

**Deviation:** Agent contracts stubbed from M1, completed M7. Prod topology = **Railway workers ↔ Supabase ↔ Telegram**.

---

## Milestone details

### M0 — Foundation

**Order of work**

1. Python 3.12 + uv project; ruff, mypy, pytest  
2. Supabase project: Postgres + pgvector; migrations apply remotely  
3. Optional local Compose / `uv run` against Supabase for dev  
4. Config via env (`DIGEST_TZ=Europe/Berlin`, budgets, `EMBEDDING_MODEL=text-embedding-3-small`, `EMBEDDING_DIM=1536`)  
5. DBOS wired to Supabase Postgres; empty workflow healthcheck  
6. Global **kill switch** (env/DB flag) checked by workflow entrypoints  
7. Structured logging + trace IDs  
8. Railway project stub (always-on worker placeholder)  
9. Document Supabase backup/PITR + restore drill  

**Depends on:** Supabase URL/keys + Railway account

**Acceptance**

- [ ] Migrations apply on Supabase; pgvector available  
- [ ] App runs locally against configured DB  
- [ ] Kill switch aborts a sample workflow  
- [ ] Restore drill documented  
- [ ] CI: lint + typecheck + unit tests green  

**Defer:** Playwright image, Telegram, Anthropic calls, social  

---

### M1 — Ingest (RSS-first)

**Order of work**

1. `sources` registry + seed YAML/SQL (spectrum-tagged)  
2. `SourceAdapter` protocol; `RssAdapter` implementation  
3. Fetch → normalize → content-hash → `articles` with provenance  
4. Quarantine path for empty/blocked/suspicious HTML  
5. Per-source rate limits + egress allowlist config  
6. Playwright adapter **stub + one pilot source** only if RSS insufficient  
7. DBOS workflow: `ingest_scheduled`  

**Depends on:** M0; start from spec seed list

**Acceptance**

- [ ] Majority of seed sources ingest without Playwright  
- [ ] Every article has URL, hash, retrieved_at, source_id, tier  
- [ ] Rate limit prevents stampede in test  
- [ ] Injection fixture treated as data  

**Defer:** Broad Playwright; social adapters  

---

### Phase 3 — Origins and clustering (replaces M2)

Stable story ids, a 72-hour window, origin detection before any counting, and centroid assignment. `corroboration_score` is retired. Membership lives in `story_articles`.

Done when the wire-copy rate has been measured and clustering has been scored on 30 hand-checked stories. The assignment code, `story_articles`, and `nearest_open_story` are in place. The measurement is not: there is no 30-story gold set yet.

### Phase 4 — Claims and evidence (replaces the first half of M3)

`claims.py`, `evidence.py`, the tables in `migrations/002_claims.sql`, and `label_claim`. The label is a plain function of origin counts. Social-signal items never count.

Done when labels beat an outlet-count baseline on 100 audited sentences. `label_claim` and `newsie report` are in place. The report's gold file is four constructed rows, not that audit.

### Phase 5 — Synthesis and validation (replaces the rest of M3)

Per-story spine from corroborated claims, views only from attributed statements, span citations, and a validator that checks the passage supports the sentence. Approval stores a per-sentence `citation_wrong` flag.

Done when a digest whose every factual sentence has a supported citation passes validation. The deterministic path and a model gloss that embeds its quote both do. A gloss that does not support its sentence is dropped.

Phases 1 and 2 (defect fixes, source list, full text, rate limits, balance report) are in the tree. A week of live ingest has not been run, and several party feed URLs are still unchecked. M4 to M6 stay as below, except that owner ratings no longer write `reliability_score` and the per-sentence flag is part of approval.

### M2 — Cluster

Superseded by Phase 3 above. The notes below are the old plan.

**Order of work**

1. `EmbeddingProvider` + OpenAI `text-embedding-3-small`  
2. Store `embedding_model`, `embedding_dim=1536`, vector, `embedded_at`  
3. Clustering → `stories` + `story_articles`  
4. Corroboration score (≥2 reporting-tier sources)  
5. Reembed workflow stub  

**Depends on:** M1; OpenAI API key

**Acceptance**

- [ ] Duplicates merge in fixtures  
- [ ] Wrong-dim insert fails loudly  
- [ ] Cluster run is resumable DBOS workflow  

---

### M3 — Digest brain

Superseded by Phases 4 and 5 above.

**Order of work**

1. `LLMProvider` (Anthropic primary)  
2. Steps: factual spine → perspectives → divergence → events  
3. **Citation validator**  
4. Neutrality prompt contracts + party label set  
5. Persist `digest_drafts`  
6. Token budget accounting per step  

**Depends on:** M2; default party set in spec

**Acceptance**

- [ ] Draft has spine + perspectives + divergence + events  
- [ ] Validator rejects fabricated citations in tests  
- [ ] Budget overrun aborts remaining paid steps  
- [ ] Label-swap smoke harness exists (full eval in M5)  

---

### M4 — Publish + HITL (Telegram)

**Order of work**

1. Telegram bot long polling on Railway  
2. Commands: preview, approve, reject (reason), rate  
3. On approve: publish + immutable snapshot in Supabase  
4. Schedule twice daily `Europe/Berlin`  

**Depends on:** M3; bot token; Railway deploy

**Acceptance**

- [ ] No auto-send without approve  
- [ ] Approve once; reject keeps draft + reason  
- [ ] Schedule testable with clock injection  
- [ ] Ratings persisted  
- [ ] Worker survives restart and resumes DBOS work  

---

### M5 — Reliability & neutrality loop

**Order of work**

1. Ratings → `source_reliability`  
2. Ranking uses reliability + corroboration  
3. Nightly/CI label-swap + citation evals  
4. Strike / demote policy  

**Depends on:** M4

**Acceptance**

- [ ] Low-rated sources demote in next ranking (test)  
- [ ] Neutrality eval gate documented  
- [ ] Reliability summary via Telegram command  

---

### M6 — Hardening

**Order of work**

1. Enforce budgets end-to-end  
2. Prompt-injection regression suite  
3. Deny-by-default egress allowlist for fetchers  
4. Ops runbook: kill switch, Supabase restore, Railway secrets  

**Depends on:** M0–M5 stable

**Acceptance**

- [ ] Kill switch + budget breach in integration tests  
- [ ] Injection suite green  
- [ ] Allowlist blocks out-of-list host in test  
- [ ] Runbook covers Supabase + Railway failure modes  

---

### M7 — Agentic platform sockets

**Order of work**

1. Finalize SourceAdapter, IngestAPI, TrustRegistry, BudgetLedger docs + tests  
2. Fixture agent ingests into quarantine  
3. Owner-gated promotion: quarantine → probation → trusted  
4. Agents cannot publish or self-trust  

**Depends on:** M1 stubs + M5 trust data

**Acceptance**

- [ ] Fixture agent article in quarantine with provenance  
- [ ] Cannot publish without HITL  
- [ ] Cannot raise its own trust  
- [ ] Contract tests in CI  

---

## Foundational guardrails (land early)

| Guardrail | Lands in |
|-----------|----------|
| Kill switch | M0 |
| Secrets via env | M0 |
| Untrusted content policy | M1 |
| Rate limits / allowlists | M1 |
| Provenance + content hash | M1 |
| Embedding model/dim metadata | M2 |
| Token/step budgets | M3 (hard enforce M6) |
| Citation validator | M3 |
| HITL gate | M4 |
| Neutrality evals | M5 |
| Agent quarantine | M7 (API stub M1) |

---

## Explicitly deferred

| Item | Until |
|------|--------|
| Dashboard UI | Out of scope |
| Social collectors | Phase B+ after M7 |
| Priority alerts / continuous timeline | Phase B+ |
| Second LLM provider | After interface in M3 |
| Playwright-for-all-sources | Per-source necessity only |
| Self-hosted / alternate prod compute | Out — Railway only |

---

## Dependency graph

```
M0 Foundation (Supabase + Railway stub)
 └── M1 Ingest ──┬── M2 Cluster ── M3 Digest brain ── M4 HITL publish (Railway)
                 │                                      └── M5 Reliability/evals
                 └── (stubs) ──────────────────────────────── M7 Agent sockets
M0/M4/M5 ─────────────────────────────────────────────────── M6 Hardening
```

---

## Open questions

### Resolved

| Topic | Decision |
|-------|----------|
| Database | Supabase Postgres + pgvector |
| Compute | Railway workers only |
| Social | Phase B+ |
| Realtime | Digests-only MVP; alerts backlog |
| Embeddings | OpenAI `text-embedding-3-small` @ 1536 |
| Parties | Spec default set |
| Milestones | Full M0–M7 |

### Needed at implementation start

1. Supabase project URL + credentials  
2. Railway project  
3. Telegram bot token  
4. Anthropic API key  
5. OpenAI API key (embeddings)  

### Optional tuning

- Must-include / must-exclude outlets beyond seed  
- Numeric monthly € caps  

---

## Definition of "build started"

Build starts when M0 branch work begins in an application repository. **This Project task delivers docs only** — see [build-spec.md](./build-spec.md).
