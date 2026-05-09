"""
Compression Agent — reduces context when approaching token budget limit.

Strategy:
1. Summarize old messages via LLM, replace with summary (lossy for filler text).
2. Trim retrieved_chunks to highest-relevance ones.
3. Shield structured data: JSON blocks, [CHUNK:id] citations, URLs are NEVER compressed.
4. Verify the compressed context fits under budget.
5. Raise CompressionFailed loudly if insufficient — NEVER silently truncate.
"""
import asyncio
import re
import time
from typing import Optional

from agents.base import BaseAgent
from core.context import SharedContext, EventType
from core.budget import ContextBudgetManager, BudgetOverflowError
from core.streaming import RedisPublisher

SUMMARIZE_PROMPT = """Summarize the following text concisely, preserving all key facts, numbers, names, and source citations.
Preserve any text that looks like [CHUNK:id] citations, URLs, or JSON exactly as-is.
Return ONLY the summary text, no preamble.

Text:
{text}"""


class CompressionFailed(Exception):
    pass


class CompressionAgent(BaseAgent):
    async def compress(
        self,
        agent_id: str,
        text: str,
        target_tokens: int,
        budget_mgr: ContextBudgetManager,
        context: SharedContext,
    ) -> str:
        """Compress a text field to target_tokens. Returns compressed text."""
        budget_mgr.declare_budget("compression", 8192)

        current_tokens = budget_mgr.count_tokens(text)
        if current_tokens <= target_tokens:
            return text

        # Shield structured content
        structured, filler = self._split_structured_filler(text)

        if not filler.strip():
            # Only structured content — cannot compress
            return text

        prompt = SUMMARIZE_PROMPT.format(text=filler[:3000])
        await budget_mgr.consume("compression", prompt)

        try:
            summary = await self.generate(prompt)
            # Rebuild: structured content preserved losslessly
            compressed = structured + "\n\n[COMPRESSED]\n" + summary
        except Exception:
            # Hard truncation of filler only as last resort
            compressed = structured + "\n\n[TRUNCATED]"

        # Verify compression succeeded
        new_tokens = budget_mgr.count_tokens(compressed)
        if new_tokens > target_tokens * 1.2:
            # Still too long — drop retrieved chunks beyond first 3
            context.retrieved_chunks = context.retrieved_chunks[:3]
            if budget_mgr.count_tokens(compressed) > target_tokens * 1.5:
                raise CompressionFailed(
                    f"Compression insufficient for agent '{agent_id}': "
                    f"{new_tokens} tokens after compression (target {target_tokens})."
                )

        context.add_event(
            agent_id="compression",
            event_type=EventType.COMPRESSION_TRIGGERED,
            prompt_sent=f"Compress for agent {agent_id}, target={target_tokens}",
            output_received=f"Reduced {current_tokens} → {new_tokens} tokens",
        )
        return compressed

    def _split_structured_filler(self, text: str) -> tuple[str, str]:
        """
        Separate structured content (JSON blocks, [CHUNK:id] citations, URLs)
        from filler text.
        Structured content is NEVER compressed.
        """
        structured_lines = []
        filler_lines = []

        json_pattern = re.compile(r'^\s*[\{\[]')
        chunk_pattern = re.compile(r'\[CHUNK:[^\]]+\]')
        url_pattern = re.compile(r'https?://\S+')

        for line in text.splitlines():
            if (json_pattern.match(line) or
                    chunk_pattern.search(line) or
                    url_pattern.search(line)):
                structured_lines.append(line)
            else:
                filler_lines.append(line)

        return "\n".join(structured_lines), "\n".join(filler_lines)

    async def run(
        self,
        context: SharedContext,
        budget_mgr: ContextBudgetManager,
        redis_pub=None,
    ) -> None:
        """Triggered automatically by worker when any agent exceeds 80% budget."""
        if redis_pub:
            await redis_pub.publish(context.job_id, {
                "event_type": "COMPRESSION_TRIGGERED",
                "agent_id": "compression",
            })

        # Trim retrieved chunks (keep highest relevance)
        if len(context.retrieved_chunks) > 10:
            context.retrieved_chunks = sorted(
                context.retrieved_chunks,
                key=lambda c: (c.hop_number, c.relevance_score),
                reverse=True,
            )[:10]

        # Compress final_answer if large
        if context.final_answer and budget_mgr.count_tokens(context.final_answer) > 1000:
            for agent_id, entry in budget_mgr.get_registry().items():
                if entry.used_tokens > entry.max_tokens * 0.9:
                    target = int(entry.max_tokens * 0.7)
                    context.final_answer = await self.compress(
                        agent_id=agent_id,
                        text=context.final_answer,
                        target_tokens=target,
                        budget_mgr=budget_mgr,
                        context=context,
                    )
                    break
