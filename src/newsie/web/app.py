"""Newsie web UI — fixture demo + live RSS fetch with HITL controls."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from newsie.cli import build_demo_pipeline, build_live_pipeline
from newsie.domain import AdapterKind, Source, Spectrum
from newsie.events import build_event_board
from newsie.hitl import HitlError, approve_draft, reject_draft
from newsie.web.presentation import build_digest_view, build_sources_only_view
from newsie.web.session import DemoSession, registry

WEB_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

app = FastAPI(title="Newsie", version="0.2.0")
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

COOKIE = "newsie_sid"
_SOURCE_ID = re.compile(r"^[a-z0-9-]{2,40}$")


def _session(request: Request) -> DemoSession:
    return registry.get(request.cookies.get(COOKIE))


def _ctx(request: Request, sess: DemoSession, **extra: Any) -> dict[str, Any]:
    draft = sess.store.get_draft(sess.draft_id) if sess.draft_id else None
    pub = None
    if sess.publication_id:
        pub = sess.store.publications.get(sess.publication_id)
    stories = sess.store.list_stories()
    edition = (
        build_digest_view(sess.store, draft)
        if draft is not None
        else build_sources_only_view(sess.store)
    )
    return {
        "request": request,
        "session_id": sess.id,
        "status": sess.last_status,
        "messages": sess.messages,
        "draft": draft,
        "edition": edition,
        "publication": pub,
        "story_count": len(stories),
        "article_count": len(sess.store.list_articles()),
        "sample_banner": sess.mode == "demo",
        "mode": sess.mode,
        **extra,
    }


def _set_cookie(response: HTMLResponse, session_id: str) -> None:
    response.set_cookie(COOKIE, session_id, httponly=True, samesite="lax")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    sess = _session(request)
    resp = templates.TemplateResponse(request, "index.html", _ctx(request, sess))
    _set_cookie(resp, sess.id)
    return resp


@app.get("/events", response_class=HTMLResponse)
async def events_page(request: Request) -> HTMLResponse:
    sess = _session(request)
    draft = sess.store.get_draft(sess.draft_id) if sess.draft_id else None
    board = build_event_board(
        stories=sess.store.list_stories(),
        articles=sess.store.list_articles(),
        sources=sess.store.sources,
        draft=draft,
    )
    resp = templates.TemplateResponse(
        request, "events.html", {**_ctx(request, sess), "board": board}
    )
    _set_cookie(resp, sess.id)
    return resp


@app.post("/run", response_class=HTMLResponse)
async def run_demo(request: Request, mode: str = Form("demo")) -> HTMLResponse:
    sess = _session(request)
    sess.messages = []
    sess.publication_id = None
    sess.mode = "live" if mode == "live" else "demo"
    if sess.mode == "live":
        pipeline, store = build_live_pipeline()
    else:
        pipeline, store = build_demo_pipeline()
    sess.pipeline = pipeline
    sess.store = store
    result = pipeline.run()
    sess.last_status = result.run.status
    notes = list(result.fetch_errors)
    if result.errors:
        sess.messages = result.errors + notes
        sess.draft_id = None
    elif result.draft is None:
        sess.messages = ["No draft produced"] + notes
        sess.draft_id = None
    else:
        sess.draft_id = result.draft.id
        sess.messages = [
            f"Mode={sess.mode}",
            f"Ingested {result.articles_ingested} articles → {result.stories} stories",
            f"Validation: {result.draft.validation_status}",
            *notes[:8],
        ]
    resp = templates.TemplateResponse(request, "index.html", _ctx(request, sess))
    _set_cookie(resp, sess.id)
    return resp


@app.post("/approve", response_class=HTMLResponse)
async def approve(request: Request) -> HTMLResponse:
    sess = _session(request)
    sess.messages = []
    if not sess.draft_id:
        sess.messages = ["Run a digest first"]
    else:
        try:
            pub = approve_draft(sess.store, sess.draft_id, kill_switch=sess.pipeline.kill_switch)
            sess.publication_id = pub.id
            sess.last_status = "published"
            balance = str(pub.immutable_snapshot.get("balance_text") or "")
            sess.messages = [f"Published (demo HITL) {pub.id}", balance]
        except HitlError as exc:
            sess.messages = [str(exc)]
    resp = templates.TemplateResponse(request, "index.html", _ctx(request, sess))
    _set_cookie(resp, sess.id)
    return resp


@app.post("/reject", response_class=HTMLResponse)
async def reject(request: Request, reason: str = Form("owner_reject")) -> HTMLResponse:
    sess = _session(request)
    sess.messages = []
    if not sess.draft_id:
        sess.messages = ["Run a digest first"]
    else:
        reject_draft(sess.store, sess.draft_id, reason)
        sess.last_status = "rejected"
        sess.messages = [f"Rejected: {reason}"]
        sess.draft_id = None
    resp = templates.TemplateResponse(request, "index.html", _ctx(request, sess))
    _set_cookie(resp, sess.id)
    return resp


@app.post("/rate", response_class=HTMLResponse)
async def rate(
    request: Request,
    source_id: str = Form("tagesschau"),
    score: float = Form(1.2),
) -> HTMLResponse:
    sess = _session(request)
    if source_id not in sess.store.sources:
        sess.messages = [f"Unknown source: {source_id}"]
    else:
        sess.store.rate_source(source_id, score)
        source = sess.store.sources[source_id]
        sess.messages = [
            f"Rated {source_id} → owner preference {source.owner_preference:.2f}",
            f"Measured reliability stays {source.reliability_score:.2f}",
        ]
    resp = templates.TemplateResponse(request, "index.html", _ctx(request, sess))
    _set_cookie(resp, sess.id)
    return resp


@app.post("/sources", response_class=HTMLResponse)
async def add_source(
    request: Request,
    source_id: str = Form(...),
    name: str = Form(...),
    homepage_url: str = Form(...),
    feed_url: str = Form(""),
    spectrum: str = Form("centre"),
) -> HTMLResponse:
    sess = _session(request)
    cleaned = source_id.strip().lower()
    try:
        placement = Spectrum(spectrum)
    except ValueError:
        placement = None
    bad_id = _SOURCE_ID.fullmatch(cleaned) is None
    bad_home = not homepage_url.startswith("http")
    if bad_id or placement is None or bad_home:
        sess.messages = ["Source needs an id like tagesspiegel, a name, and an http homepage"]
    else:
        sess.store.upsert_source(
            Source(
                id=cleaned,
                name=name.strip() or cleaned,
                homepage_url=homepage_url.strip(),
                feed_url=feed_url.strip() or None,
                adapter=AdapterKind.RSS,
                spectrum=placement,
                spectrum_basis="Added from the editorial desk",
                enabled=True,
            )
        )
        sess.messages = [f"Source {cleaned} saved"]
    resp = templates.TemplateResponse(request, "index.html", _ctx(request, sess))
    _set_cookie(resp, sess.id)
    return resp


@app.post("/sources/disable", response_class=HTMLResponse)
async def disable_source(request: Request, source_id: str = Form(...)) -> HTMLResponse:
    sess = _session(request)
    source = sess.store.sources.get(source_id)
    if source is None:
        sess.messages = [f"Unknown source: {source_id}"]
    else:
        sess.store.upsert_source(source.model_copy(update={"enabled": False}))
        sess.messages = [f"Disabled {source_id}"]
    resp = templates.TemplateResponse(request, "index.html", _ctx(request, sess))
    _set_cookie(resp, sess.id)
    return resp


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "app": "newsie"}
