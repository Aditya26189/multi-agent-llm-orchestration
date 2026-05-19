"""
Redis streaming for SSE events.
RedisPublisher publishes events to Redis pub/sub channel for a job.
sse_event_generator subscribes and yields SSE events to the client.
"""
import json
import os
from typing import AsyncGenerator, Optional
import redis.asyncio as aioredis
from core.context import EventType

try:
    from fastapi.sse import ServerSentEvent
except ImportError:
    from sse_starlette.sse import ServerSentEvent


class RedisPublisher:
    """Publishes SSE events to Redis pub/sub channel for a job."""

    def __init__(self, redis_url: Optional[str] = None):
        self._url = redis_url or os.environ["REDIS_URL"]
        self._client: Optional[aioredis.Redis] = None
        self._seq = 0

    async def connect(self):
        self._pool = aioredis.ConnectionPool.from_url(self._url, decode_responses=True)
        self._client = aioredis.Redis(connection_pool=self._pool)

    async def disconnect(self):
        if self._client:
            await self._client.aclose()
        if hasattr(self, "_pool") and self._pool:
            await self._pool.disconnect()

    async def publish(self, job_id: str, event_data: dict) -> None:
        if not self._client:
            await self.connect()
        channel = f"job_events:{job_id}"
        if "id" not in event_data:
            event_data["id"] = self._seq
            self._seq += 1
        await self._client.publish(channel, json.dumps(event_data, default=str))

    async def publish_token(self, job_id: str, agent_id: str, token: str) -> None:
        await self.publish(job_id, {
            "event_type": EventType.TOKEN.value,
            "agent_id": agent_id,
            "token": token,
        })

    async def publish_done(self, job_id: str, final_answer: str, provenance: Optional[list] = None) -> None:
        await self.publish(job_id, {
            "event_type": EventType.DONE.value,
            "job_id": job_id,
            "final_answer": final_answer,
            "provenance": provenance or [],
        })

    async def publish_error(self, job_id: str, message: str) -> None:
        await self.publish(job_id, {
            "event_type": EventType.ERROR.value,
            "job_id": job_id,
            "message": message,
        })


async def sse_event_generator(
    job_id: str,
    redis_url: str,
    request,
) -> AsyncGenerator:
    """
    Subscribes to Redis pub/sub and yields SSE events.
    Handles: client disconnect, worker crash, Redis restart.
    """
    import asyncio

    client = aioredis.from_url(redis_url, decode_responses=True)
    pubsub = client.pubsub()
    channel = f"job_events:{job_id}"

    await pubsub.subscribe(channel)

    try:
        deadline = asyncio.get_event_loop().time() + 300  # 5 min max

        async for message in pubsub.listen():
            # Check client disconnect
            if hasattr(request, "is_disconnected") and await request.is_disconnected():
                break

            # Check timeout
            if asyncio.get_event_loop().time() > deadline:
                yield {"event": "error", "data": json.dumps({"message": "timeout"})}
                break

            if message["type"] != "message":
                continue

            try:
                data = json.loads(message["data"])
                event_type = data.get("event_type", "message")
                yield ServerSentEvent(
                    data=json.dumps(data),
                    event=event_type,
                    id=str(data.get("id", "")),
                )

                if event_type in (EventType.DONE.value, EventType.ERROR.value):
                    break

            except json.JSONDecodeError:
                continue

    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
        await client.aclose()
