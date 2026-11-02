"""In-process publish/subscribe hub for real-time delivery.

For a single-node deployment this is all that is required. In a horizontally
scaled deployment the same interface is backed by Redis pub/sub so that a metric
polled by one worker reaches WebSocket clients attached to another (see the
architecture in the project spec, §6). Swapping the backend does not change the
router or poller code.
"""
from __future__ import annotations

import asyncio
from typing import Any


class Subscriber:
    def __init__(self, topics: set[str]) -> None:
        self.topics = topics
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)

    def matches(self, topic: str) -> bool:
        if not self.topics or "*" in self.topics:
            return True
        if topic in self.topics:
            return True
        # Prefix match, e.g. subscribing to "device.42" gets "device.42.temp_cpu"
        return any(
            topic == t or topic.startswith(t + ".") or t.startswith(topic + ".")
            for t in self.topics
        )


class RealtimeHub:
    def __init__(self) -> None:
        self._subscribers: set[Subscriber] = set()
        self._lock = asyncio.Lock()
        # Optional Redis pub/sub for cross-process fan-out (multi-replica).
        self._redis: Any = None
        self._redis_task: asyncio.Task | None = None
        self._channel = "rackmon:realtime"

    async def connect_redis(self, url: str, channel: str = "rackmon:realtime") -> None:
        """Enable cross-replica fan-out via Redis pub/sub. Idempotent.

        Once connected, ``publish`` sends only to Redis; a background subscriber
        in *every* replica (including this one) receives the message and does the
        local queue fan-out, so each client is delivered to exactly once. Any
        Redis error degrades gracefully to in-process delivery.
        """
        if self._redis is not None:
            return
        import redis.asyncio as aioredis  # lazy: only needed when configured

        self._channel = channel
        self._redis = aioredis.from_url(url)
        sub_conn = aioredis.from_url(url)
        pubsub = sub_conn.pubsub()
        await pubsub.subscribe(self._channel)

        async def _listen() -> None:
            import json

            try:
                async for msg in pubsub.listen():
                    if msg.get("type") != "message":
                        continue
                    try:
                        data = json.loads(msg["data"])
                        await self._local_publish(data["topic"], data["payload"])
                    except Exception:  # pragma: no cover - malformed message
                        continue
            except asyncio.CancelledError:  # pragma: no cover - shutdown
                pass

        self._redis_task = asyncio.create_task(_listen())

    async def disconnect_redis(self) -> None:
        if self._redis_task is not None:
            self._redis_task.cancel()
            self._redis_task = None
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:  # pragma: no cover
                pass
            self._redis = None

    async def subscribe(self, topics: set[str]) -> Subscriber:
        sub = Subscriber(topics)
        async with self._lock:
            self._subscribers.add(sub)
        return sub

    async def unsubscribe(self, sub: Subscriber) -> None:
        async with self._lock:
            self._subscribers.discard(sub)

    @property
    def client_count(self) -> int:
        return len(self._subscribers)

    async def _local_publish(self, topic: str, payload: dict[str, Any]) -> None:
        """Fan an already-assembled payload out to local subscribers."""
        async with self._lock:
            targets = [s for s in self._subscribers if s.matches(topic)]
        for sub in targets:
            try:
                sub.queue.put_nowait(payload)
            except asyncio.QueueFull:
                # Slow consumer: drop oldest to keep the stream live.
                try:
                    sub.queue.get_nowait()
                    sub.queue.put_nowait(payload)
                except Exception:
                    pass

    async def publish(self, topic: str, message: dict[str, Any]) -> None:
        """Fan a message out to every matching subscriber.

        With Redis configured this crosses replica boundaries; otherwise it is a
        direct in-process fan-out. Same call site either way.
        """
        payload = {"topic": topic, **message}
        if self._redis is not None:
            import json

            try:
                await self._redis.publish(
                    self._channel, json.dumps({"topic": topic, "payload": payload})
                )
                return
            except Exception:  # pragma: no cover - degrade to local on Redis error
                pass
        await self._local_publish(topic, payload)


hub = RealtimeHub()
