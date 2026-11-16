"""Newsie Phase 1 web UI — fixture digest demo with HITL controls."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from newsie.hitl import HitlError, approve_draft, reject_draft
from newsie.web.session import DemoSession, registry

WEB_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

app = FastAPI(title="Newsie", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

COOKIE = "newsie_sid"


def _session(request: Request) -> DemoSession:
    return registry.get(request.cookies.get(COOKIE))


def _ctx(request: Request, sess: DemoSession, **extra: Any) -> dict[str, Any]:
    draft = sess.store.get_draft(sess.draft_id) if sess.draft_id else None
    pub = None
    if sess.publication_id:
        pub = sess.store.publications.get(sess.publication_id)
    stories = sess.store.list_stories()
    return {
        "request": request,
        "session_id": sess.id,
        "status": sess.last_status,
        "messages": sess.messages,
        "draft": draft,
        "publication": pub,
        "story_count": len(stories),
        "article_count": len(sess.store.list_articles()),
        "sample_banner": True,
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


@app.post("/run", response_class=HTMLResponse)
async def run_demo(request: Request) -> HTMLResponse:
    sess = _session(request)
    sess.messages = []
    # Fresh pipeline store each run for clean demo
    from newsie.cli import build_demo_pipeline

    pipeline, store = build_demo_pipeline()
    sess.pipeline = pipeline
    sess.store = store
    sess.publication_id = None
    result = pipeline.run()
    sess.last_status = result.run.status
    if result.errors:
        sess.messages = result.errors
        sess.draft_id = None
    elif result.draft is None:
        sess.messages = ["No draft produced"]
        sess.draft_id = None
    else:
        sess.draft_id = result.draft.id
        sess.messages = [
            f"Ingested {result.articles_ingested} articles → {result.stories} stories",
            f"Validation: {result.draft.validation_status}",
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
            sess.messages = [f"Published (demo) {pub.id}"]
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
        rel = sess.store.sources[source_id].reliability_score
        sess.messages = [f"Rated {source_id} → reliability {rel:.2f}"]
    resp = templates.TemplateResponse(request, "index.html", _ctx(request, sess))
    _set_cookie(resp, sess.id)
    return resp


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "app": "newsie"}
