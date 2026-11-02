"""Realtime hub: in-process fan-out (always) and cross-process Redis (when up)."""
import asyncio
import os

import pytest

from app.services.realtime import RealtimeHub


def test_realtime_local_fanout():
    async def run():
        hub = RealtimeHub()
        sub = await hub.subscribe({"device.1"})
        await hub.publish("device.1.temp_cpu", {"type": "metric", "value": 42})
        msg = sub.queue.get_nowait()
        assert msg["topic"] == "device.1.temp_cpu" and msg["value"] == 42
        # a non-matching topic is not delivered
        await hub.publish("device.2.temp_cpu", {"value": 1})
        assert sub.queue.empty()
        await hub.unsubscribe(sub)
        assert hub.client_count == 0

    asyncio.run(run())


def test_realtime_wildcard_and_prefix_match():
    async def run():
        hub = RealtimeHub()
        star = await hub.subscribe(set())  # empty == all
        pref = await hub.subscribe({"device.7"})
        await hub.publish("device.7.fan_rpm", {"value": 5000})
        assert star.queue.get_nowait()["value"] == 5000
        assert pref.queue.get_nowait()["value"] == 5000  # prefix match

    asyncio.run(run())


def test_realtime_redis_roundtrip():
    """Publish and receive through a real Redis, proving cross-process delivery.

    Skips cleanly when no Redis is reachable so the suite stays green anywhere.
    """
    redis = pytest.importorskip("redis")
    url = os.environ.get("RACKMON_TEST_REDIS_URL", "redis://127.0.0.1:6379/15")
    try:
        redis.from_url(url).ping()
    except Exception:
        pytest.skip("redis not reachable")

    async def run():
        hub = RealtimeHub()
        await hub.connect_redis(url, channel="rackmon:pytest")
        sub = await hub.subscribe({"*"})
        await hub.publish("device.9.temp_cpu", {"type": "metric", "value": 7})
        received = None
        for _ in range(30):  # allow the subscriber loop to receive
            if not sub.queue.empty():
                received = sub.queue.get_nowait()
                break
            await asyncio.sleep(0.1)
        await hub.disconnect_redis()
        assert received is not None and received["value"] == 7

    asyncio.run(run())
