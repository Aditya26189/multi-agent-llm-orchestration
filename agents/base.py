"""
BaseAgent — Gemini override.
Uses google.generativeai GenerativeModel("gemini-2.0-flash") instead of AsyncOpenAI.
stream_response() uses model.generate_content(prompt, stream=True) for token streaming.
"""
import asyncio
import os
from abc import ABC, abstractmethod
from typing import Optional

import google.generativeai as genai

from core.context import SharedContext
from core.budget import ContextBudgetManager
from core.streaming import RedisPublisher


class BaseAgent(ABC):
    def __init__(self):
        api_key = os.environ["GOOGLE_API_KEY"]
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel("gemini-2.0-flash")

    @abstractmethod
    async def run(
        self,
        context: SharedContext,
        budget_mgr: ContextBudgetManager,
        redis_pub: Optional[RedisPublisher] = None,
    ) -> None:
        """Execute this agent. Write outputs to context. Never call other agents."""
        ...

    async def stream_response(
        self,
        prompt: str,
        context: SharedContext,
        redis_pub: Optional[RedisPublisher],
        agent_id: str,
    ) -> str:
        """
        Stream tokens to SSE client via Redis, return full response string.
        Uses Gemini model.generate_content(prompt, stream=True).
        """
        full = ""
        try:
            response = await asyncio.to_thread(
                self._model.generate_content,
                prompt,
                stream=True,
            )
            for chunk in response:
                delta = chunk.text if hasattr(chunk, "text") else ""
                if delta:
                    full += delta
                    if redis_pub:
                        await redis_pub.publish_token(context.job_id, agent_id, delta)
        except Exception:
            # Fall back to non-streaming if streaming fails
            resp = await asyncio.to_thread(self._model.generate_content, prompt)
            full = resp.text if hasattr(resp, "text") else ""
            if redis_pub and full:
                await redis_pub.publish_token(context.job_id, agent_id, full)
        return full

    async def generate(self, prompt: str) -> str:
        """Non-streaming Gemini call."""
        resp = await asyncio.to_thread(self._model.generate_content, prompt)
        return resp.text if hasattr(resp, "text") else ""

    async def generate_json(self, prompt: str, schema=None) -> str:
        """
        Gemini structured output using response_mime_type='application/json'.
        If schema provided, uses response_schema. Returns raw JSON string.
        """
        generation_config = {"response_mime_type": "application/json"}
        if schema is not None:
            generation_config["response_schema"] = schema

        model = genai.GenerativeModel(
            "gemini-2.0-flash",
            generation_config=generation_config,
        )
        resp = await asyncio.to_thread(model.generate_content, prompt)
        return resp.text if hasattr(resp, "text") else "{}"
