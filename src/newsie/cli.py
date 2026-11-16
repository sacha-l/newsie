"""CLI entrypoints: demo, live, run, approve, web."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from uuid import UUID

from newsie.adapters.fixture import FixtureAdapter
from newsie.adapters.registry import AdapterRouter
from newsie.config import Settings, get_settings
from newsie.guardrails import KillSwitch
from newsie.hitl import approve_draft, reject_draft
from newsie.pipeline import DigestPipeline, seed_demo_sources, seed_live_sources
from newsie.store_factory import create_store


def build_demo_pipeline(settings: Settings | None = None) -> tuple[DigestPipeline, Any]:
    settings = settings or get_settings()
    settings = settings.model_copy(update={"demo_mode": True})
    store = create_store(settings, force_memory=True)
    seed_demo_sources(store)
    pipeline = DigestPipeline(
        store,
        settings,
        adapter=FixtureAdapter(),
        kill_switch=KillSwitch(engaged=settings.kill_switch),
    )
    return pipeline, store


def build_live_pipeline(settings: Settings | None = None) -> tuple[DigestPipeline, Any]:
    settings = settings or get_settings()
    settings = settings.model_copy(update={"demo_mode": False})
    store = create_store(settings)
    seed_live_sources(store)
    router = AdapterRouter(allow_fixture_fallback=True)
    pipeline = DigestPipeline(
        store,
        settings,
        adapter=router,
        kill_switch=KillSwitch(engaged=settings.kill_switch),
    )
    return pipeline, store


def cmd_demo(_: argparse.Namespace) -> int:
    pipeline, store = build_demo_pipeline()
    result = pipeline.run()
    print("=== Newsie demo run ===")
    print(f"status: {result.run.status}")
    print(f"articles_ingested: {result.articles_ingested}")
    print(f"stories: {result.stories}")
    print(f"budget: {json.dumps(result.run.budget_snapshot)}")
    if result.errors:
        print(f"errors: {result.errors}")
        return 1
    if result.draft is None:
        print("no draft")
        return 1
    print(f"draft_id: {result.draft.id}")
    print(f"validation: {result.draft.validation_status}")
    print()
    print(result.draft.english_render_md)
    print()
    print("--- HITL ---")
    pub = approve_draft(store, result.draft.id, kill_switch=pipeline.kill_switch)
    print(f"published: {pub.id} at {pub.approved_at.isoformat()}")
    store.rate_source("tagesschau", 1.2)
    print(f"tagesschau reliability -> {store.sources['tagesschau'].reliability_score}")
    return 0


def cmd_live(_: argparse.Namespace) -> int:
    pipeline, store = build_live_pipeline()
    result = pipeline.run()
    print("=== Newsie LIVE run ===")
    print(f"status: {result.run.status}")
    print(f"articles_ingested: {result.articles_ingested}")
    print(f"stories: {result.stories}")
    if result.fetch_errors:
        print("fetch_notes:")
        for e in result.fetch_errors:
            print(f"  - {e}")
    if result.errors:
        print(f"errors: {result.errors}")
        return 1
    if result.draft is None:
        print("no draft")
        return 1
    print(f"draft_id: {result.draft.id}")
    print(f"validation: {result.draft.validation_status}")
    print()
    print(result.draft.english_render_md[:4000])
    return 0


def cmd_run(_: argparse.Namespace) -> int:
    return cmd_demo(_)


def cmd_approve(args: argparse.Namespace) -> int:
    pipeline, store = build_demo_pipeline()
    result = pipeline.run()
    if result.draft is None:
        print("no draft to approve", file=sys.stderr)
        return 1
    draft_id = UUID(args.draft_id) if args.draft_id else result.draft.id
    if args.reject:
        reject_draft(store, result.draft.id, args.reject)
        print(f"rejected: {result.draft.id}")
        return 0
    target = result.draft.id if args.draft_id is None else draft_id
    if target != result.draft.id:
        target = result.draft.id
    pub = approve_draft(store, target, kill_switch=pipeline.kill_switch)
    print(f"approved publication {pub.id}")
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    import uvicorn

    print(f"Newsie web UI → http://{args.host}:{args.port}")
    uvicorn.run("newsie.web.app:app", host=args.host, port=args.port, reload=False)
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="newsie", description="Newsie political news digest")
    sub = parser.add_subparsers(dest="command", required=True)

    p_demo = sub.add_parser("demo", help="Offline fixture digest + HITL approve")
    p_demo.set_defaults(func=cmd_demo)

    p_live = sub.add_parser("live", help="Fetch real RSS sources and build digest")
    p_live.set_defaults(func=cmd_live)

    p_run = sub.add_parser("run", help="Alias for demo")
    p_run.set_defaults(func=cmd_run)

    p_approve = sub.add_parser("approve", help="Approve (or reject) a demo draft")
    p_approve.add_argument("--draft-id", default=None)
    p_approve.add_argument("--reject", default=None, help="Reject with reason")
    p_approve.set_defaults(func=cmd_approve)

    p_web = sub.add_parser("web", help="Serve web UI")
    p_web.add_argument("--host", default="127.0.0.1")
    p_web.add_argument("--port", type=int, default=8000)
    p_web.set_defaults(func=cmd_web)

    args = parser.parse_args(argv)
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
