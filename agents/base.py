"""
BaseAgent — Gemini override.
Uses google.genai.Client instead of AsyncOpenAI to prevent race conditions.
stream_response() uses client.models.generate_content_stream for token streaming.
"""
import asyncio
import os
import json
from abc import ABC, abstractmethod
from typing import Optional

from google import genai
from google.genai import types

from core.context import SharedContext
from core.budget import ContextBudgetManager
from core.streaming import RedisPublisher


class BaseAgent(ABC):
    def __init__(self, agent_id: str = None):
        self._agent_id = agent_id or "unknown"
        prefix = f"GOOGLE_API_KEY_{self._agent_id.upper()}"

        # Collect all keys: primary + _2, _3, _4, ...
        keys = []
        primary = os.environ.get(prefix) or os.environ.get("GOOGLE_API_KEY", "NOT_FOUND")
        keys.append(primary)
        n = 2
        while True:
            extra = os.environ.get(f"{prefix}_{n}")
            if not extra:
                break
            keys.append(extra)
            n += 1

        self._clients = [genai.Client(api_key=k) for k in keys]
        self._masked_keys = [f"...{k[-5:]}" for k in keys]
        self._key_index = 0  # round-robin counter

    @property
    def _client(self):
        """Always returns the current client in the rotation."""
        return self._clients[self._key_index % len(self._clients)]

    def _next_client(self):
        """Advance to the next key and return the client."""
        self._key_index = (self._key_index + 1) % len(self._clients)
        return self._clients[self._key_index]

    def _log_api_call(self, endpoint: str):
        key = self._masked_keys[self._key_index % len(self._masked_keys)]
        print(f"[{self._agent_id.upper()}] '{endpoint}' → key {key} (slot {self._key_index % len(self._clients) + 1}/{len(self._clients)})", flush=True)

    @abstractmethod
    async def run(
        self,
        context: SharedContext,
        budget_mgr: ContextBudgetManager,
        redis_pub: Optional[RedisPublisher] = None,
    ) -> None:
        """Execute this agent. Write outputs to context. Never call other agents."""
        ...

    async def generate(self, prompt: str) -> str:
        """Non-streaming Gemini call with rate limiting and backoff."""
        from core.rate_limiter import call_with_backoff
        self._log_api_call("generate_content")
        client = self._client
        self._next_client()  # rotate for next call
        resp = await call_with_backoff(
            client.models.generate_content,
            model="gemini-2.5-flash",
            contents=prompt,
        )
        return resp.text if hasattr(resp, "text") else ""

    async def generate_json(self, prompt: str, schema=None) -> str:
        """Gemini structured output with rate limiting and backoff."""
        from core.rate_limiter import call_with_backoff
        self._log_api_call("generate_content (JSON)")
        client = self._client
        self._next_client()  # rotate for next call
        config_dict = {"response_mime_type": "application/json"}
        if schema is not None:
            config_dict["response_schema"] = schema
            
        config = types.GenerateContentConfig(**config_dict)
        
        resp = await call_with_backoff(
            client.models.generate_content,
            model="gemini-2.5-flash",
            contents=prompt,
            config=config,
        )
        return resp.text if hasattr(resp, "text") else "{}"

    async def stream_response(
        self,
        prompt: str,
        context: SharedContext,
        redis_pub: Optional[RedisPublisher],
        agent_id: str,
        config: Optional[types.GenerateContentConfig] = None,
    ) -> str:
        """Stream tokens to SSE client via Redis, return full response string."""
        from core.rate_limiter import wait as rate_wait
        self._log_api_call("generate_content_stream")
        client = self._client
        self._next_client()  # rotate for next call
        await rate_wait()
        full = ""
        try:
            kwargs = {}
            if config is not None:
                kwargs["config"] = config
            response = await asyncio.to_thread(
                client.models.generate_content_stream,
                model="gemini-2.5-flash",
                contents=prompt,
                **kwargs,
            )
            for chunk in response:
                delta = chunk.text if hasattr(chunk, "text") else ""
                if delta:
                    full += delta
                    if redis_pub:
                        await redis_pub.publish_token(context.job_id, agent_id, delta)
        except Exception:
            self._log_api_call("generate_content (stream fallback)")
            full = await self.generate(prompt)
            if redis_pub and full:
                await redis_pub.publish_token(context.job_id, agent_id, full)
        return full