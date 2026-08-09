"""SSE realtime broadcast — push board/compare updates to the wallboard.

Any mutation (ingest tick) notifies subscribers; the UI re-fetches the
changed projection. This is the realtime slice (TB-005): slow-moving markets
should appear to update INSTANTLY on ingest, not on the next 5s poll.

Single in-process pub/sub (one uvicorn worker). Scale-out (Redis) is a
Stage-3 concern if the screen ever runs multi-worker.
"""
import asyncio
from collections import deque
from typing import AsyncIterator

_QUEUE_MAX = 128
_subscribers: set[asyncio.Queue] = set()


def notify(topic: str) -> None:
    """Publish a change; drop subscribers that are too slow (backpressure)."""
    stale = []
    for q in _subscribers:
        try:
            q.put_nowait(f"event: {topic}\ndata: {{}}\n\n")
        except asyncio.QueueFull:
            stale.append(q)
    for q in stale:
        _subscribers.discard(q)


async def stream() -> AsyncIterator[str]:
    """SSE generator: yields an initial snapshot ping, then live events."""
    q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAX)
    _subscribers.add(q)
    try:
        yield "event: snapshot\ndata: {}\n\n"
        while True:
            try:
                yield await asyncio.wait_for(q.get(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"  # comment-only line keeps the connection alive
    finally:
        _subscribers.discard(q)


def subscriber_count() -> int:
    return len(_subscribers)
