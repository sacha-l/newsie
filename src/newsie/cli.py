"""CLI entrypoints: demo, live, run, approve, web."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from newsie.adapters.fixture import FixtureAdapter
from newsie.adapters.registry import AdapterRouter
from newsie.config import Settings, get_settings
from newsie.guardrails import KillSwitch
from newsie.hitl import approve_draft, reject_draft
from newsie.llm import GrokProvider
from newsie.pipeline import DigestPipeline, seed_demo_sources, seed_live_sources
from newsie.sources import load_live_sources
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
    router = AdapterRouter(allow_fixture_fallback=False)
    llm = GrokProvider(settings.xai_api_key, settings.grok_model) if settings.xai_api_key else None
    pipeline = DigestPipeline(
        store,
        settings,
        adapter=router,
        llm=llm,
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
    source = store.sources["tagesschau"]
    print(f"tagesschau owner preference -> {source.owner_preference}")
    print(f"tagesschau reliability -> {source.reliability_score}")
    if pub.immutable_snapshot.get("balance_text"):
        print(pub.immutable_snapshot["balance_text"])
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


def cmd_validate_sources(args: argparse.Namespace) -> int:
    """Fetch each enabled feed and report text length, language, and truncation."""
    from newsie.adapters.base import FetchContext
    from newsie.adapters.http_adapter import fetch_article_page
    from newsie.adapters.rss import RssAdapter

    sources = [source for source in load_live_sources() if source.enabled]
    if args.source:
        sources = [source for source in sources if source.id == args.source]
    adapter = RssAdapter()
    ctx = FetchContext(
        deadline=datetime.now(UTC),
        max_articles=3,
        lookback_hours=72,
    )
    failures = 0
    for source in sources:
        print(f"== {source.id} ({source.spectrum.value}, {source.tier.value}) ==")
        try:
            items = adapter.fetch(source, ctx)[:3]
        except Exception as exc:
            print(f"  feed error: {exc}")
            failures += 1
            continue
        if not items:
            print("  no recent entries")
            failures += 1
            continue
        for item in items:
            page = fetch_article_page(item.url, rate_limit_per_hour=source.rate_limit_per_hour)
            if page is None:
                text = item.content_text
                method = "rss_summary"
                partial = True
            else:
                text = str(page["text"])
                method = str(page["method"])
                partial = bool(page["partial"])
            print(
                f"  {len(text)} chars  lang={_guess_lang(text)}  "
                f"method={method}  partial={partial}  {item.url}"
            )
    return 1 if failures else 0


def _guess_lang(text: str) -> str:
    sample = text.lower()
    german = sum(token in sample for token in (" und ", " der ", " die ", " das "))
    english = sum(token in sample for token in (" the ", " and ", " of "))
    return "de" if german >= english else "en"


def cmd_capture(args: argparse.Namespace) -> int:
    from newsie.corpus import capture_corpus

    payload = capture_corpus()
    articles = payload["articles"]
    stories = payload["stories"]
    errors = payload["fetch_errors"]
    print(
        f"Captured {len(articles) if isinstance(articles, list) else 0} articles"
        f" in {len(stories) if isinstance(stories, list) else 0} stories"
    )
    if isinstance(errors, list) and errors:
        print(f"Feeds with errors: {len(errors)}")
        for line in errors[:12]:
            print(f"  {line}")
    _ = args
    return 0


def cmd_report(_args: argparse.Namespace) -> int:
    from newsie.evals.metrics import beats_baseline, load_label_rows, score_label_rows

    path = Path(__file__).resolve().parents[2] / "data" / "gold" / "label_baseline.json"
    rows = load_label_rows(path)
    scored = score_label_rows(rows)
    print(f"Label file: {path}")
    print(
        "Constructed examples of the label rule, not the 100-sentence audit: "
        f"evidence {scored['evidence']:.2f}, outlet-count {scored['outlet_count']:.2f}, "
        f"evidence beats outlet-count: {beats_baseline(rows)}"
    )
    print(
        "Wire-copy rate and the 30-story clustering score still need a labelled live corpus. "
        "newsie.evals.metrics.wire_copy_rate and bcubed score a corpus when you have one."
    )
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

    p_check = sub.add_parser(
        "validate-sources",
        help="Fetch each feed, extract three articles, report length and truncation",
    )
    p_check.add_argument("--source", default=None, help="Check one source id")
    p_check.set_defaults(func=cmd_validate_sources)

    p_report = sub.add_parser(
        "report",
        help="Score the constructed label file and say which live audits are still open",
    )
    p_report.set_defaults(func=cmd_report)

    p_capture = sub.add_parser(
        "capture-corpus",
        help="Fetch the last 30 days of seed feeds and write data/corpus/month.json",
    )
    p_capture.set_defaults(func=cmd_capture)

    p_web = sub.add_parser("web", help="Serve web UI")
    p_web.add_argument("--host", default="127.0.0.1")
    p_web.add_argument("--port", type=int, default=8000)
    p_web.set_defaults(func=cmd_web)

    args = parser.parse_args(argv)
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
