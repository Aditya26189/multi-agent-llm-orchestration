"""
Retrieval Agent — 2-hop pgvector search with [CHUNK:id] citations.

Hop 1: embed query → vector search → LLM extracts SECOND_HOP_QUERY
Hop 2: embed 2nd-hop query → vector search → LLM synthesizes with citations
Citations stored in context.provenance_map as ProvenanceEntry objects.
"""
import asyncio
import json
import os
import time
from typing import List, Optional

from google import genai
from google.genai import types
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents.base import BaseAgent
from core.context import (
    SharedContext, Chunk, ProvenanceEntry, AgentID, EventType
)
from core.budget import ContextBudgetManager
from core.streaming import RedisPublisher

RETRIEVAL_PROMPT_HOP1 = """You are a retrieval agent performing the FIRST HOP of a 2-hop retrieval.

Query: {query}

Retrieved chunks:
{chunks}

Your tasks:
1. Identify which chunks are most relevant to the query.
2. Extract key information that partially answers the query.
3. On a NEW LINE, write: SECOND_HOP_QUERY: <refined query for the second hop>

Be specific in your SECOND_HOP_QUERY — it should seek information NOT covered by hop 1."""

RETRIEVAL_PROMPT_HOP2 = """You are a retrieval agent performing the SECOND HOP of a 2-hop retrieval.

Original query: {query}
Hop 1 context: {hop1_context}

Additional chunks for hop 2:
{chunks}

Synthesize a complete answer using BOTH hop 1 and hop 2 information.
For every sentence you write, cite the source using [CHUNK:chunk_id] format.
For sentences derived from your own reasoning (not a chunk), use [REASONING].

Format:
[CHUNK:id] <sentence from that chunk>
[REASONING] <sentence from your reasoning>"""

VECTOR_SEARCH_SQL = """
SELECT id, content, source_url,
       1 - (embedding <=> :emb::vector(768)) AS relevance
FROM document_chunks
ORDER BY embedding <=> :emb::vector(768)
LIMIT :limit
"""


class RetrievalAgent(BaseAgent):
    def __init__(self):
        super().__init__(agent_id="retrieval")
        self._db_url = os.environ["DATABASE_URL"]
        # self._client is already initialized by BaseAgent with the correct API key

    async def _embed(self, text: str) -> List[float]:
        """Gemini embedding model with retrieval_query task type."""
        from core.rate_limiter import call_with_backoff
        self._log_api_call("embed_content")
        client = self._client
        result = await call_with_backoff(
            client.models.embed_content,
            model="models/gemini-embedding-001",
            contents=text,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=768,
            ),
        )
        return result.embeddings[0].values

    async def _vector_search(self, query: str, limit: int = 5, hop: int = 1):
        embedding = await self._embed(query)
        emb_literal = "[" + ",".join(str(x) for x in embedding) + "]"

        sql = f"""
            SELECT id, content, source_url,
                1 - (embedding <=> '{emb_literal}'::vector(768)) AS relevance
            FROM document_chunks
            ORDER BY embedding <=> '{emb_literal}'::vector(768)
            LIMIT :limit
        """
        
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.pool import NullPool
        
        # Create an isolated engine with NullPool per call to prevent asyncpg InterfaceErrors
        # when running across multiple Celery worker event loops.
        engine = create_async_engine(self._db_url, poolclass=NullPool)
        
        try:
            async with AsyncSession(engine) as db:
                rows = await db.execute(text(sql), {"limit": limit})
                result = rows.fetchall()
        finally:
            await engine.dispose()

        return [
            Chunk(
                id=str(row.id),
                text=row.content,
                source_url=row.source_url,
                relevance_score=float(row.relevance),
                hop_number=hop,
            )
            for row in result
        ]

    async def _formulate_followup(self, query: str, chunks: list) -> str:
        """LLM determines missing information and formulates 2nd hop query."""
        prompt = f"Query: {query}\nFound so far: {[c.text[:200] for c in chunks]}\nWhat is missing? Return ONLY the search query."
        res = await self.generate(prompt)
        return res.strip() if res else query

    async def run(
        self,
        context: SharedContext,
        budget_mgr: ContextBudgetManager,
        redis_pub=None,
    ) -> None:
        budget_mgr.declare_budget("retrieval", 6144)

        if redis_pub:
            await redis_pub.publish(context.job_id, {
                "event_type": "AGENT_START", "agent_id": "retrieval"
            })

        start = time.monotonic()

        # ── HOP 1 ──────────────────────────────────────────────────────────────
        hop1_chunks = await self._vector_search(context.query, limit=5, hop=1)

        if not hop1_chunks:
            context.retrieval_reasoning = "No documents found in knowledge base."
            context.final_answer = "Insufficient knowledge base for retrieval."
            return

        chunks_text = "\n\n".join(
            f"[CHUNK:{c.id}]: {c.text[:400]}" for c in hop1_chunks
        )
        prompt_hop1 = RETRIEVAL_PROMPT_HOP1.format(
            query=context.query,
            chunks=chunks_text,
        )
        await budget_mgr.consume("retrieval", prompt_hop1)
        budget_mgr.assert_compliant("retrieval")

        hop1_response = await self.generate(prompt_hop1)

        # Extract second hop query using _formulate_followup
        second_hop_query = await self._formulate_followup(context.query, hop1_chunks)

        # ── HOP 2 ──────────────────────────────────────────────────────────────
        hop2_chunks = await self._vector_search(second_hop_query, limit=5, hop=2)
        all_chunks = hop1_chunks + hop2_chunks

        chunks_text_2 = "\n\n".join(
            f"[CHUNK:{c.id}]: {c.text[:400]}" for c in hop2_chunks
        )
        prompt_hop2 = RETRIEVAL_PROMPT_HOP2.format(
            query=context.query,
            hop1_context=hop1_response[:800],
            chunks=chunks_text_2,
        )
        await budget_mgr.consume("retrieval", prompt_hop2)

        # ── HOP 2 — with token streaming ────────────────────────────────────────────
        hop2_response = await self.stream_response(
            prompt_hop2,
            context,
            redis_pub,
            "retrieval",
            config=types.GenerateContentConfig(temperature=0.0),
        )
        latency = (time.monotonic() - start) * 1000

        # ── Parse citations into provenance_map ────────────────────────────────
        provenance = []
        valid_ids = {c.id for c in all_chunks}
        for line in hop2_response.splitlines():
            line = line.strip()
            if line.startswith("[CHUNK:"):
                end = line.find("]")
                if end > 0:
                    chunk_id = line[7:end]
                    sentence = line[end+1:].strip()
                    provenance.append(ProvenanceEntry(
                        sentence=sentence,
                        source_agent=AgentID.RETRIEVAL,
                        source_chunk_id=chunk_id if chunk_id in valid_ids else None,
                    ))
            elif line.startswith("[REASONING]"):
                sentence = line[11:].strip()
                provenance.append(ProvenanceEntry(
                    sentence=sentence,
                    source_agent=AgentID.RETRIEVAL,
                    source_chunk_id=None,
                ))

        context.retrieved_chunks = all_chunks
        context.retrieval_reasoning = hop1_response
        context.final_answer = hop2_response
        context.provenance_map = provenance

        context.add_event(
            agent_id="retrieval",
            event_type=EventType.AGENT_START,
            prompt_sent=prompt_hop2[:500],
            output_received=hop2_response[:500],
            latency_ms=latency,
            token_count=budget_mgr.count_tokens(prompt_hop1 + prompt_hop2),
        )
