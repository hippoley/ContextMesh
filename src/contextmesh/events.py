from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Iterator


@dataclass
class Subscription:
    id: str
    queue: queue.Queue


class EventBus:
    """Small in-process broadcast bus used by the v0.7 SSE control plane.

    This is intentionally dependency-free. A production deployment can replace it
    with Redis/NATS/Kafka without changing the public event contract.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: dict[str, queue.Queue] = {}

    def subscribe(self) -> Subscription:
        sub = Subscription(id=f"sub_{uuid.uuid4().hex[:12]}", queue=queue.Queue(maxsize=1024))
        with self._lock:
            self._subs[sub.id] = sub.queue
        return sub

    def unsubscribe(self, sub_id: str) -> None:
        with self._lock:
            self._subs.pop(sub_id, None)

    def publish(self, event: str, data: dict) -> None:
        payload = {"event": event, "ts": time.time(), **data}
        with self._lock:
            queues = list(self._subs.values())
        for q in queues:
            try:
                q.put_nowait(payload)
            except queue.Full:
                try:
                    q.get_nowait()
                    q.put_nowait(payload)
                except Exception:
                    pass

    def iter_sse(self, subscription: Subscription, *, heartbeat_seconds: float = 15.0, predicate: Callable[[dict], bool] | None = None) -> Iterator[str]:
        try:
            yield "event: ready\ndata: {}\n\n"
            while True:
                try:
                    item = subscription.queue.get(timeout=heartbeat_seconds)
                    if predicate is not None and not predicate(item):
                        continue
                    event = str(item.get("event", "message"))
                    yield f"event: {event}\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    yield ": heartbeat\n\n"
        finally:
            self.unsubscribe(subscription.id)
