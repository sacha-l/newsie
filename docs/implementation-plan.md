# Implementation plan — newsie (spec → testable URL)

**Goal:** Finish the locked build spec, then ship a **Vercel-hosted web UI** so you can click-test the digest demo.  
**Codebase today:** `/agent/newsie` (CLI spine + offline demo + 16 tests).  
**Prod topology (locked):** Railway workers ↔ Supabase ↔ Telegram HITL.  
**Test URL path:** thin web app on **Vercel** (demo/HITL UI only — not a replacement for Railway workers).

---

## Already done (baseline)

| Spec piece | Status |
|------------|--------|
| Domain models (Pydantic) | Done |
| Config / budgets / kill switch / LoopGuard | Done |
| Fixture + RSS adapters | Done (HTTP/Playwright stubbed) |
| Hash embeddings + OpenAI interface | Done (live OpenAI optional) |
| Cluster + rank | Done (in-memory; not pgvector yet) |
| Digest stub (spine / perspectives / divergence / events) | Done (Anthropic live optional) |
| Citation validator | Done |
| HITL approve/reject + ratings | Done (in-memory; not Telegram) |
| Agent ingest quarantine API | Done (library, no HTTP server) |
| CLI `newsie demo` | Done |
| Tests (16) | Green |

---

## Gap vs full spec (ordered)

### Phase 1 — Testable web UI on Vercel (immediate “app URL”)

**Why first:** You asked for a URL to test; CLI-only cannot deploy to Vercel as-is.

| Work | Detail |
|------|--------|
| `web/` Next.js (App Router) UI | Brand-light digest viewer: Run demo → show spine/perspectives/divergence/events → Approve / Reject / Rate |
| API routes | `POST /api/demo/run`, `POST /api/hitl/approve`, `POST /api/hitl/reject`, `POST /api/hitl/rate` |
| Python bridge | Vercel Python serverless **or** port demo orchestration into a thin Node shim that shells `uv run` locally only — **chosen approach:** **Next.js UI + TypeScript reimplementation of the *demo* path only** calling shared JSON fixtures, **OR** single Python ASGI (FastAPI) + Vercel Python runtime. **Decision: FastAPI + static/HTMX-or-Jinja UI packaged for Vercel Python**, keeping one language and reusing `newsie` package. |
| Sample data label | UI marks “Sample / offline demo” when no live keys |
| Deploy | `vercel` project `newsie` (needs `VERCEL_TOKEN` or `vercel login`) |
| Tests | API + UI smoke tests; keep existing Python tests |

**Acceptance:** Public or project Vercel URL; one click runs fixture digest; approve works; no secrets required for demo.

**Risk:** No `VERCEL_TOKEN` in this environment → owner login / token required; fallback = Cursor `publish-app` if Vercel blocked.

### Phase 2 — Persistence (Supabase)

| Work | Detail |
|------|--------|
| SQL migrations | Tables from build-spec §5 + `pgvector` |
| Store adapter | Replace/extend `MemoryStore` with Postgres |
| Wire `DATABASE_URL` | Supabase pooler |
| Reembed / embedding rows | model + dim metadata |

**Acceptance:** Demo run persists articles/stories/drafts; restart still sees data.

### Phase 3 — Live providers

| Work | Detail |
|------|--------|
| OpenAI embeddings | Use when `OPENAI_API_KEY` set |
| Anthropic digest | Structured outputs behind `LLMProvider` |
| RSS live ingest | Seed list from `data/seed_sources.yaml` |
| HTTP adapter | Readability fallback |
| Playwright | Opt-in per source only |

**Acceptance:** With keys, one live ingest+digest produces validated draft.

### Phase 4 — Telegram HITL + Railway

| Work | Detail |
|------|--------|
| Telegram long-poll worker | Approve / reject / rate commands |
| Railway services | Always-on worker(s) |
| Schedule | 2×/day `Europe/Berlin` |
| Kill switch / budgets | Enforced on live path |

**Acceptance:** Unapproved digests never send; approve sends once.

### Phase 5 — Hardening + agent sockets (M6–M7)

| Work | Detail |
|------|--------|
| Injection suite | HTML/RSS fixtures |
| Egress allowlist | Config-driven |
| HTTP IngestAPI | Bearer auth, quarantine |
| Neutrality evals | Label-swap CI job |
| OTel-lite | Trace IDs |

**Defer:** Social collectors, alerts, dashboard (already out of scope).

---

## Immediate execution sequence (after you approve this plan)

1. Add FastAPI web app under `/agent/newsie/web` (or `src/newsie/web`) wrapping existing pipeline.  
2. Local preview on `127.0.0.1`.  
3. Commit locally.  
4. Deploy to Vercel (`vercel --prod` or project link); if auth missing, stop and give exact login steps — **do not invent a URL**.  
5. Return the real HTTPS URL + how to click-test.  
6. Continue Phases 2–5 only after Phase 1 URL works (or you say proceed without Vercel).

### Phase 1 status (2026-11-16)

- **Done:** FastAPI UI at `src/newsie/web`, CLI `newsie web`, tests, local + temporary Vercel.
- **Local URL:** `http://127.0.0.1:8000` (when `uv run newsie web` is running).
- **Vercel note:** anonymous `*.tmp.now` often **403 in browsers** — claim deployment or use local.

### Phase 2 + live fetch status

- **Done:** Real RSS via httpx (browser-like headers, 403/429 retries), HTTP page adapter, `AdapterRouter`, `newsie live`, seed YAML.
- **Done:** SQLAlchemy `SqlStore` (SQLite default / Postgres-ready), `migrations/001_init.sql` for Supabase+pgvector.
- **Web:** **Run live RSS** button + fetch error notes in UI.

---

## Explicit non-goals for Phase 1

- Full Railway/Telegram production cutover  
- Live Anthropic spend on the public demo URL (fixtures only unless you add keys)  
- Multi-tenant dashboard  
- Rewriting the CLI spine  

---

## Blockers to call out

1. **Vercel auth** — environment has no `VERCEL_TOKEN` / logged-in CLI yet.  
2. **GitHub remote** — still local-only; Vercel can deploy from CLI without GitHub, or from Git after you push.  
3. Spec says **Railway** for workers; Vercel is **test UI only**.

---

## Success metric

You open one HTTPS link → run sample digest → see perspectives → approve → see “published (demo)” — without installing Python locally.
