"""Process-local demo sessions (fine for local + warm serverless; cold starts re-run)."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from uuid import UUID, uuid4

from newsie.cli import build_demo_pipeline
from newsie.pipeline import DigestPipeline
from newsie.store import MemoryStore


@dataclass
class DemoSession:
    id: str
    store: MemoryStore
    pipeline: DigestPipeline
    draft_id: UUID | None = None
    publication_id: UUID | None = None
    last_status: str = "idle"
    messages: list[str] = field(default_factory=list)


class SessionRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._sessions: dict[str, DemoSession] = {}

    def get(self, session_id: str | None) -> DemoSession:
        with self._lock:
            if session_id and session_id in self._sessions:
                return self._sessions[session_id]
            sid = str(uuid4())
            pipeline, store = build_demo_pipeline()
            sess = DemoSession(id=sid, store=store, pipeline=pipeline)
            self._sessions[sid] = sess
            return sess


registry = SessionRegistry()
