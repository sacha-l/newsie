"""In-process stage hand-off.

Postgres deployments use pgmq (see migrations/003_postgres.sql). This queue is
the same ack contract for tests and for a process that runs every stage itself.
"""

from __future__ import annotations


class StageQueue:
    def __init__(self) -> None:
        self._next = 1
        self.pending: dict[int, str] = {}
        self.acked: list[str] = []

    def send(self, stage: str) -> int:
        message_id = self._next
        self._next += 1
        self.pending[message_id] = stage
        return message_id

    def read(self) -> tuple[int, str] | None:
        if not self.pending:
            return None
        message_id = min(self.pending)
        return message_id, self.pending[message_id]

    def ack(self, message_id: int) -> None:
        stage = self.pending.pop(message_id, None)
        if stage is not None:
            self.acked.append(stage)
