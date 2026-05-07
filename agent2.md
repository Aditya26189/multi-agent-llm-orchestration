═══════════════════════════════════════════════════════════════════════════════
## PHASE 6: TOOLS WITH EXPLICIT FAILURE CONTRACTS
═══════════════════════════════════════════════════════════════════════════════

### FILE: `core/tools.py`

RULES:
- Every tool returns a ToolResult. Never raises exceptions to the caller.
- Failure contracts are in Python code — NOT in prompt strings.
- ToolAction enum drives retry logic — NOT the LLM.
- modify_input_fn modifies query between retries — not the same input twice for NO_RESULTS.

```python
import asyncio
import time
import hashlib
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING
from pydantic import BaseModel

if TYPE_CHECKING:
    from core.context import SharedContext, ToolName


class ToolResult(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None   # TIMEOUT | NO_RESULTS | INVALID_INPUT | EXEC_ERROR
    error_message: Optional[str] = None
    latency_ms: float = 0.0
    tool_name: str = ""


class ToolAction(str, Enum):
    """Per-error-code dispatch — explicit Python, never in a prompt."""
    RETRY_SAME        = "retry_same"        # TIMEOUT: transient, retry same input
    RETRY_REFORMULATE = "retry_reformulate" # NO_RESULTS: broaden/rephrase, then retry
    SKIP_LOG_VIOLATION= "skip_log_violation"# INVALID_INPUT: log PolicyViolation, skip
    FALLBACK_TOOL     = "fallback_tool"     # EXEC_ERROR: route to self_reflect
    ABORT             = "abort"             # all retries exhausted


def handle_tool_failure(
    result: "ToolResult",
    tool_name: str,
    attempt: int,
    context: "SharedContext",
) -> ToolAction:
    """
    EXPLICIT per-error-code dispatch.
    This logic MUST stay in Python. It MUST NOT be in any prompt string.
    """
    from core.context import PolicyViolation

    if result.error_code == "TIMEOUT":
        return ToolAction.RETRY_SAME if attempt < 2 else ToolAction.ABORT

    elif result.error_code == "NO_RESULTS":
        return ToolAction.RETRY_REFORMULATE if attempt < 2 else ToolAction.ABORT

    elif result.error_code == "INVALID_INPUT":
        context.violations.append(PolicyViolation(
            agent_id="tool_runner",
            violation_type="schema_invalid",
            details=f"Tool '{tool_name}' received malformed input: {result.error_message}",
        ))
        return ToolAction.SKIP_LOG_VIOLATION  # never retry invalid input

    elif result.error_code == "EXEC_ERROR":
        return ToolAction.FALLBACK_TOOL if attempt < 2 else ToolAction.ABORT

    return ToolAction.ABORT


# ── Tool 1: Web Search Stub ────────────────────────────────────────────────────

class WebSearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    relevance_score: float


async def tool_web_search(
    query: str,
    max_results: int = 5,
    timeout_seconds: float = 5.0,
) -> ToolResult:
    start = time.monotonic()

    if not query or not query.strip():
        return ToolResult(
            success=False, error_code="INVALID_INPUT",
            error_message="Query must be non-empty", tool_name="web_search",
        )

    try:
        await asyncio.wait_for(asyncio.sleep(0.1), timeout=timeout_seconds)

        words = query.split()[:3]
        slug = "-".join(w.lower() for w in words)
        results = [
            WebSearchResult(
                title=f"Result {i+1}: {query[:50]}",
                url=f"https://stub-results.example.com/{slug}/{i+1}",
                snippet=f"Stub result {i+1} for query '{query[:40]}'. "
                        f"In production replace with SerpAPI/Bing.",
                relevance_score=round(1.0 - i * 0.12, 2),
            )
            for i in range(max_results)
        ]

        if not results:
            return ToolResult(
                success=False, error_code="NO_RESULTS",
                error_message=f"No results for: '{query}'", tool_name="web_search",
                latency_ms=(time.monotonic() - start) * 1000,
            )

        return ToolResult(
            success=True,
            data={"results": [r.model_dump() for r in results], "query": query},
            tool_name="web_search",
            latency_ms=(time.monotonic() - start) * 1000,
        )

    except asyncio.TimeoutError:
        return ToolResult(
            success=False, error_code="TIMEOUT",
            error_message=f"Search timed out after {timeout_seconds}s",
            tool_name="web_search",
            latency_ms=(time.monotonic() - start) * 1000,
        )


def broaden_web_query(kwargs: dict, error_code: str, attempt: int) -> dict:
    """Default modify_input_fn for web_search: broaden query on NO_RESULTS."""
    if error_code == "NO_RESULTS":
        q = kwargs.get("query", "")
        kwargs["query"] = " ".join(q.split()[:3])
        kwargs["max_results"] = kwargs.get("max_results", 5) + 3
    return kwargs


# ── Tool 2: Code Execution Sandbox ────────────────────────────────────────────

BLOCKED_PATTERNS = [
    "os.system", "subprocess", "shutil.rmtree", "__import__(",
    "exec(", "eval(", "open(", "socket.", "urllib",
]


async def tool_code_exec(
    code: str,
    timeout_seconds: float = 10.0,
) -> ToolResult:
    start = time.monotonic()

    if not code or not code.strip():
        return ToolResult(
            success=False, error_code="INVALID_INPUT",
            error_message="Code must be non-empty", tool_name="code_exec",
        )

    for pattern in BLOCKED_PATTERNS:
        if pattern in code:
            return ToolResult(
                success=False, error_code="INVALID_INPUT",
                error_message=f"Blocked pattern '{pattern}' found",
                tool_name="code_exec",
            )

    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                "python3", "-c", code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
            timeout=timeout_seconds,
        )
        stdout_b, stderr_b = await proc.communicate()
        latency = (time.monotonic() - start) * 1000
        stdout = stdout_b.decode("utf-8", errors="replace").strip()
        stderr = stderr_b.decode("utf-8", errors="replace").strip()

        if proc.returncode != 0:
            return ToolResult(
                success=False, error_code="EXEC_ERROR",
                error_message=f"Exit code {proc.returncode}",
                data={"stdout": stdout, "stderr": stderr, "exit_code": proc.returncode},
                tool_name="code_exec", latency_ms=latency,
            )

        return ToolResult(
            success=True,
            data={"stdout": stdout, "stderr": stderr, "exit_code": 0},
            tool_name="code_exec", latency_ms=latency,
        )

    except asyncio.TimeoutError:
        return ToolResult(
            success=False, error_code="TIMEOUT",
            error_message=f"Execution exceeded {timeout_seconds}s",
            tool_name="code_exec",
            latency_ms=(time.monotonic() - start) * 1000,
        )


# ── Tool 3: NL → SQL Lookup ───────────────────────────────────────────────────

SCHEMA_DESCRIPTION = """
Available tables (READ-ONLY, SELECT only):
- eval_results(test_case_id TEXT, category TEXT, answer_correctness FLOAT,
               citation_accuracy FLOAT, contradiction_resolution FLOAT,
               tool_efficiency FLOAT, budget_compliance FLOAT,
               critique_agreement FLOAT, composite_score FLOAT, timestamp TIMESTAMPTZ)
- jobs(job_id UUID, query TEXT, status TEXT, total_tokens_used INT, created_at TIMESTAMPTZ)
- execution_events(job_id UUID, agent_id TEXT, event_type TEXT,
                   latency_ms FLOAT, token_count INT, timestamp TIMESTAMPTZ)
"""


async def tool_sql_lookup(
    natural_language_query: str,
    db_session,
    llm_client,
) -> ToolResult:
    start = time.monotonic()

    if not natural_language_query or not natural_language_query.strip():
        return ToolResult(
            success=False, error_code="INVALID_INPUT",
            error_message="Query must be non-empty", tool_name="sql_lookup",
        )

    try:
        prompt = f"""Convert to PostgreSQL SQL (SELECT only, no mutations).
Schema: {SCHEMA_DESCRIPTION}
Query: {natural_language_query}
Return ONLY the SQL. No markdown, no explanation."""

        resp = await llm_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        sql = resp.choices[0].message.content.strip().strip("```sql").strip("```").strip()

        if not sql.upper().startswith("SELECT"):
            return ToolResult(
                success=False, error_code="INVALID_INPUT",
                error_message="Generated SQL is not a SELECT statement",
                data={"generated_sql": sql}, tool_name="sql_lookup",
                latency_ms=(time.monotonic() - start) * 1000,
            )

        from sqlalchemy import text
        result = await db_session.execute(text(sql))
        rows = result.mappings().all()

        if not rows:
            return ToolResult(
                success=False, error_code="NO_RESULTS",
                error_message="Query returned 0 rows",
                data={"sql": sql}, tool_name="sql_lookup",
                latency_ms=(time.monotonic() - start) * 1000,
            )

        return ToolResult(
            success=True,
            data={"rows": [dict(r) for r in rows[:50]], "sql": sql, "count": len(rows)},
            tool_name="sql_lookup",
            latency_ms=(time.monotonic() - start) * 1000,
        )

    except Exception as e:
        return ToolResult(
            success=False, error_code="EXEC_ERROR", error_message=str(e),
            tool_name="sql_lookup",
            latency_ms=(time.monotonic() - start) * 1000,
        )


# ── Tool 4: Self-Reflection ───────────────────────────────────────────────────

async def tool_self_reflect(
    agent_id: str,
    context: "SharedContext",
    llm_client,
) -> ToolResult:
    start = time.monotonic()

    prior_outputs = [
        e.output_received
        for e in context.execution_events
        if e.agent_id == agent_id and e.output_received
    ]

    if len(prior_outputs) < 2:
        return ToolResult(
            success=False, error_code="NO_RESULTS",
            error_message=f"Agent '{agent_id}' has fewer than 2 prior outputs",
            tool_name="self_reflect",
            latency_ms=(time.monotonic() - start) * 1000,
        )

    try:
        outputs_text = "\n\n---\n\n".join(
            f"[Output {i+1}]:\n{o}" for i, o in enumerate(prior_outputs)
        )
        prompt = f"""Review these prior outputs from agent '{agent_id}' for contradictions.

{outputs_text}

List EACH contradiction:
1. Conflicting claim A (exact quote, Output #)
2. Conflicting claim B (exact quote, Output #)
3. Severity: HIGH/MEDIUM/LOW

If none found, respond: NO_CONTRADICTIONS_FOUND"""

        resp = await llm_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        reflection = resp.choices[0].message.content.strip()

        return ToolResult(
            success=True,
            data={
                "reflection": reflection,
                "has_contradictions": "NO_CONTRADICTIONS_FOUND" not in reflection,
                "outputs_analyzed": len(prior_outputs),
            },
            tool_name="self_reflect",
            latency_ms=(time.monotonic() - start) * 1000,
        )

    except Exception as e:
        return ToolResult(
            success=False, error_code="EXEC_ERROR", error_message=str(e),
            tool_name="self_reflect",
            latency_ms=(time.monotonic() - start) * 1000,
        )


# ── Retry Wrapper ─────────────────────────────────────────────────────────────

async def execute_tool_with_retry(
    tool_fn,
    tool_name: str,
    agent_id: str,
    context: "SharedContext",
    tool_kwargs: Dict[str, Any],
    modify_input_fn: Optional[Callable] = None,
    max_retries: int = 2,
) -> ToolResult:
    """
    Wraps any tool call with retry logic.
    Each retry logged separately with its own ToolCallRecord.
    modify_input_fn(kwargs, error_code, attempt) -> kwargs
    — MUST modify input between retries (spec requirement).
    """
    from core.context import ToolCallRecord, ToolName

    current_kwargs = dict(tool_kwargs)
    result = None

    for attempt in range(1, max_retries + 2):
        record = ToolCallRecord(
            job_id=context.job_id,
            agent_id=agent_id,
            tool_name=ToolName(tool_name),
            attempt_number=attempt,
            input_data=dict(current_kwargs),
        )

        s = time.monotonic()
        result = await tool_fn(**current_kwargs)
        record.latency_ms = (time.monotonic() - s) * 1000
        record.output_data = result.data
        record.error_code = result.error_code
        context.tool_calls.append(record)

        if result.success:
            record.accepted = True
            return result

        action = handle_tool_failure(result, tool_name, attempt, context)

        if action in (ToolAction.SKIP_LOG_VIOLATION, ToolAction.ABORT):
            record.accepted = False
            return result

        if attempt >= max_retries + 1:
            record.accepted = False
            return result

        # Modify input before retry
        if modify_input_fn:
            current_kwargs = modify_input_fn(current_kwargs, result.error_code, attempt)
            record.retry_reason = f"Attempt {attempt} failed ({result.error_code}), modified input"
        else:
            record.retry_reason = f"Attempt {attempt} failed ({result.error_code}), retrying"

        record.accepted = False
        await asyncio.sleep(0.5 * attempt)

    return result
```

Commit: `feat(tools): 4 tools with failure contracts, ToolAction enum, retry wrapper with input mutation`

═══════════════════════════════════════════════════════════════════════════════
## PHASE 7: REDIS STREAMING
═══════════════════════════════════════════════════════════════════════════════

### FILE: `core/streaming.py`
```python
import json
import os
from typing import AsyncGenerator
import redis.asyncio as aioredis
from core.context import EventType


class RedisPublisher:
    """Publishes SSE events to Redis pub/sub channel for a job."""

    def __init__(self, redis_url: Optional[str] = None):
        self._url = redis_url or os.environ["REDIS_URL"]
        self._client: Optional[aioredis.Redis] = None

    async def connect(self):
        self._client = aioredis.from_url(self._url, decode_responses=True)

    async def disconnect(self):
        if self._client:
            await self._client.aclose()

    async def publish(self, job_id: str, event_data: dict) -> None:
        if not self._client:
            await self.connect()
        channel = f"job_events:{job_id}"
        await self._client.publish(channel, json.dumps(event_data))

    async def publish_token(self, job_id: str, agent_id: str, token: str) -> None:
        await self.publish(job_id, {
            "event_type": EventType.TOKEN.value,
            "agent_id": agent_id,
            "token": token,
        })

    async def publish_done(self, job_id: str, final_answer: str) -> None:
        await self.publish(job_id, {
            "event_type": EventType.DONE.value,
            "job_id": job_id,
            "final_answer": final_answer,
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
        # Handle race condition: client connects before worker starts publishing
        # We poll with a short timeout so we don't block forever
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
                yield {"event": event_type, "data": json.dumps(data)}

                if event_type in (EventType.DONE.value, EventType.ERROR.value):
                    break

            except json.JSONDecodeError:
                continue

    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
        await client.aclose()
```

Commit: `feat(streaming): RedisPublisher with pub/sub, SSE generator with disconnect and timeout handling`

═══════════════════════════════════════════════════════════════════════════════
## PHASE 8: AGENTS
═══════════════════════════════════════════════════════════════════════════════

### FILE: `agents/base.py`
```python
from abc import ABC, abstractmethod
from openai import AsyncOpenAI
import instructor
from core.context import SharedContext
from core.budget import ContextBudgetManager
from core.streaming import RedisPublisher


class BaseAgent(ABC):
    def __init__(self, openai_api_key: str):
        self._raw_client = AsyncOpenAI(api_key=openai_api_key)
        self._client = instructor.from_openai(self._raw_client)

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
        model: str,
        context: SharedContext,
        redis_pub: Optional[RedisPublisher],
        agent_id: str,
    ) -> str:
        """Stream tokens to SSE client via Redis, return full response string."""
        full = ""
        async with self._raw_client.chat.completions.stream(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        ) as stream:
            async for chunk in stream:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    full += delta
                    if redis_pub:
                        await redis_pub.publish_token(context.job_id, agent_id, delta)
        return full
```

### FILE: `agents/orchestrator.py`
```python
import time
from typing import Optional
import instructor
from openai import AsyncOpenAI
from core.context import (
    AgentID, SharedContext, RoutingDecision, PolicyViolation, EventType
)
from core.budget import ContextBudgetManager
from core.streaming import RedisPublisher

MAX_TOOL_CALLS_PER_JOB = 20
MAX_TURNS = 12

ORCHESTRATOR_SYSTEM = """You are the master orchestrator of a multi-agent LLM pipeline.
Decide which agent to invoke next based on the current pipeline state.

AVAILABLE AGENTS:
- decomposition: Breaks query into typed sub-tasks with dependency graph
- retrieval: Multi-hop RAG (min 2 hops). Requires decomposition to be done first.
- critique: Reviews ALL prior agent outputs. Requires retrieval to be done.
- synthesis: Merges outputs, resolves contradictions. Requires critique to be done.
- compression: Trigger only when an agent is near or over its token budget.

ROUTING LOGIC (follow unless strong reason to deviate):
1. turn=0 → decomposition
2. decomposition done, retrieval NOT done → retrieval
3. retrieval done, critique NOT done → critique
4. critique done, synthesis NOT done → synthesis
5. synthesis done → mark pipeline DONE

DEVIATIONS: allowed only with explicit reasoning. Example: skip retrieval for
a purely computational query. You MUST explain deviations in your reasoning field.

BUDGET RULE: If any agent is at >80% token budget, route to compression first."""

ORCHESTRATOR_USER_TEMPLATE = """Current pipeline state:
{state_json}

Return your routing decision as a RoutingDecision object."""


class Orchestrator:
    def __init__(self, openai_api_key: str):
        base = AsyncOpenAI(api_key=openai_api_key)
        self.client = instructor.from_openai(base)

    async def route(
        self,
        context: SharedContext,
        budget_mgr: ContextBudgetManager,
        redis_pub: Optional[RedisPublisher] = None,
    ) -> RoutingDecision:
        """Single LLM call → validated RoutingDecision. Falls back to deterministic."""

        # Hard limits
        if context.count_tool_calls() >= MAX_TOOL_CALLS_PER_JOB:
            context.violations.append(PolicyViolation(
                agent_id="orchestrator",
                violation_type="budget_overflow",
                details=f"MAX_TOOL_CALLS ({MAX_TOOL_CALLS_PER_JOB}) reached",
            ))
            return self._deterministic_fallback(context, "tool_limit_reached")

        if context.turn >= MAX_TURNS:
            return self._deterministic_fallback(context, "max_turns_reached")

        # Build state summary (concise for orchestrator budget)
        budget_warnings = [
            f"{k}: {v.used_tokens}/{v.max_tokens} ({v.used_tokens/v.max_tokens*100:.0f}%)"
            for k, v in budget_mgr.get_registry().items()
            if v.used_tokens > v.max_tokens * 0.8
        ]

        state = {
            "job_id": context.job_id,
            "query": context.query[:200],
            "turn": context.turn,
            "sub_tasks_done": [t.id for t in context.sub_tasks if t.status.value == "done"],
            "sub_tasks_pending": [t.id for t in context.sub_tasks if t.status.value == "pending"],
            "chunks_retrieved": len(context.retrieved_chunks),
            "claims_flagged": len(context.get_flagged_claims()),
            "final_answer_length": len(context.final_answer),
            "total_tool_calls": context.count_tool_calls(),
            "budget_warnings": budget_warnings,
            "agents_routed_to": [d.next_agent.value for d in context.routing_decisions],
            "violations": len(context.violations),
        }

        import json
        state_text = json.dumps(state, indent=2)
        prompt = ORCHESTRATOR_USER_TEMPLATE.format(state_json=state_text)

        budget_mgr.declare_budget("orchestrator", 2048)
        await budget_mgr.consume("orchestrator", prompt)

        start = time.monotonic()
        try:
            decision: RoutingDecision = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": ORCHESTRATOR_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                response_model=RoutingDecision,
                temperature=0,
                max_retries=2,
            )
            latency = (time.monotonic() - start) * 1000

            context.routing_decisions.append(decision)
            context.add_event(
                agent_id="orchestrator",
                event_type=EventType.HANDOFF,
                prompt_sent=prompt,
                output_received=decision.model_dump_json(),
                latency_ms=latency,
                token_count=budget_mgr.count_tokens(prompt),
            )

            if redis_pub:
                await redis_pub.publish(context.job_id, {
                    "event_type": "HANDOFF",
                    "next_agent": decision.next_agent.value,
                    "reasoning": decision.reasoning,
                    "confidence": decision.confidence,
                    "turn": context.turn,
                })

            context.turn += 1
            return decision

        except Exception as e:
            decision = self._deterministic_fallback(context, str(e)[:100])
            context.routing_decisions.append(decision)
            context.turn += 1
            return decision

    def _deterministic_fallback(self, context: SharedContext, reason: str) -> RoutingDecision:
        """State-machine fallback when LLM routing call fails."""
        has_run = context.has_agent_run

        if not has_run(AgentID.DECOMPOSITION):
            next_a = AgentID.DECOMPOSITION
        elif not has_run(AgentID.RETRIEVAL):
            next_a = AgentID.RETRIEVAL
        elif not has_run(AgentID.CRITIQUE):
            next_a = AgentID.CRITIQUE
        else:
            next_a = AgentID.SYNTHESIS

        return RoutingDecision(
            next_agent=next_a,
            reasoning=f"FALLBACK (reason={reason}): deterministic state machine.",
            budget_allocation={next_a.value: 4096},
            confidence=0.5,
        )
```

### FILE: `agents/decomposition.py`
```python
import asyncio
import time
from typing import Dict, List, Set
import instructor
from openai import AsyncOpenAI
from pydantic import BaseModel
from core.context import SharedContext, SubTask, SubTaskStatus, EventType
from core.budget import ContextBudgetManager

DECOMP_PROMPT = """Break the following query into typed sub-tasks with explicit dependencies.

Query: {query}

Rules:
1. Maximum 6 sub-tasks. Never over-decompose simple queries.
2. Task types: factual_lookup | reasoning | code_execution | data_retrieval | summarization | verification
3. deps[] must list task ids that MUST complete before this task can start.
4. Tasks with empty deps[] can run in parallel.
5. Descriptions must be specific enough for a retrieval agent to act on.
6. If query is simple (single clear fact needed), use 1-2 tasks maximum.

Return JSON with key "sub_tasks" containing an array of task objects."""

class DecompositionOutput(BaseModel):
    sub_tasks: List[SubTask]


class DecompositionAgent:
    def __init__(self, openai_api_key: str):
        self.client = instructor.from_openai(AsyncOpenAI(api_key=openai_api_key))

    async def run(self, context: SharedContext, budget_mgr: ContextBudgetManager, redis_pub=None) -> None:
        budget_mgr.declare_budget("decomposition", 3072)
        prompt = DECOMP_PROMPT.format(query=context.query)
        await budget_mgr.consume("decomposition", prompt)
        budget_mgr.assert_compliant("decomposition")

        if redis_pub:
            await redis_pub.publish(context.job_id, {
                "event_type": "AGENT_START", "agent_id": "decomposition"
            })

        start = time.monotonic()
        result: DecompositionOutput = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_model=DecompositionOutput,
            temperature=0,
        )
        latency = (time.monotonic() - start) * 1000

        context.sub_tasks = result.sub_tasks
        context.dependency_graph = {t.id: t.deps for t in result.sub_tasks}

        await budget_mgr.consume("decomposition", result.model_dump_json())
        context.add_event(
            agent_id="decomposition", event_type=EventType.AGENT_START,
            prompt_sent=prompt, output_received=result.model_dump_json(),
            latency_ms=latency, token_count=budget_mgr.count_tokens(prompt),
        )


class DependencyExecutor:
    """Execute sub-tasks in dependency order using asyncio.Event gates."""

    def __init__(self, sub_tasks: List[SubTask]):
        self.tasks: Dict[str, SubTask] = {t.id: t for t in sub_tasks}
        self._events: Dict[str, asyncio.Event] = {
            t_id: asyncio.Event() for t_id in self.tasks
        }
        self._failed: Set[str] = set()

    async def execute(self, handler) -> Dict[str, str]:
        """handler: async callable(subtask) -> str"""
        await asyncio.gather(
            *[self._run_task(t, handler) for t in self.tasks.values()],
            return_exceptions=True,
        )
        return {tid: t.output or "" for tid, t in self.tasks.items()}

    async def _run_task(self, task: SubTask, handler) -> None:
        for dep_id in task.deps:
            if dep_id not in self._events:
                task.status = SubTaskStatus.FAILED
                task.error = f"Unknown dep: {dep_id}"
                self._failed.add(task.id)
                self._events[task.id].set()
                return
            await self._events[dep_id].wait()
            if dep_id in self._failed:
                task.status = SubTaskStatus.FAILED
                task.error = f"Dep '{dep_id}' failed"
                self._failed.add(task.id)
                self._events[task.id].set()
                return

        task.status = SubTaskStatus.RUNNING
        try:
            output = await handler(task)
            task.output = output
            task.status = SubTaskStatus.DONE
            from datetime import datetime
            task.completed_at = datetime.utcnow()
        except Exception as e:
            task.status = SubTaskStatus.FAILED
            task.error = str(e)
            self._failed.add(task.id)
        finally:
            self._events[task.id].set()
```

### FILE: `agents/retrieval.py`
Build this file with these exact behaviours:

1. **Hop 1**: embed `context.query`, vector search pgvector, call LLM with chunks, extract `SECOND_HOP_QUERY:` from response.
2. **Hop 2**: embed the second hop query, vector search again, call gpt-4o with hop1 context + new chunks.
3. **Parsing**: extract `[CHUNK:id]` and `[REASONING]` prefixes from final answer into `ProvenanceEntry` objects.
4. **Store**: `context.retrieved_chunks`, `context.retrieval_reasoning`, `context.final_answer` (draft), `context.provenance_map`.

Use the prompts from the plan (RETRIEVAL_PROMPT_HOP1 and RETRIEVAL_PROMPT_HOP2 verbatim).

The vector search SQL:
```sql
SELECT id, content, source_url,
       1 - (embedding <=> :emb::vector) AS relevance
FROM document_chunks
ORDER BY embedding <=> :emb::vector
LIMIT :limit
```

### FILE: `agents/critique.py`
Use this EXACT prompt (fixes the formatting bug from the plan):
```python
CRITIQUE_PROMPT = """You are a rigorous fact-checking critique agent.

Review the outputs of ALL agents in this pipeline:

DECOMPOSITION OUTPUT (sub-tasks):
{subtasks_json}

RETRIEVAL CITATIONS:
{retrieval_answer}

DRAFT ANSWER (pre-synthesis):
{draft_answer}

SOURCE CHUNKS (ground truth):
{chunks}

Critique ALL THREE sections above. For each problematic text span:
- Extract the EXACT span
- Assign confidence 0.0-1.0 (1.0 = fully supported)
- Set flagged=true if confidence < 0.6
- Provide flag_reason citing specific evidence

DO NOT flag without positive evidence. DO NOT evaluate holistically."""
```

In `CritiqueAgent.run()`, build the prompt like this:
```python
chunks_text = "\n\n".join(
    f"[CHUNK:{c.id}]: {c.text[:300]}"
    for c in context.retrieved_chunks[:8]
)
prompt = CRITIQUE_PROMPT.format(
    subtasks_json=json.dumps([t.model_dump() for t in context.sub_tasks], indent=2),
    retrieval_answer=context.retrieval_reasoning,
    draft_answer=context.final_answer,
    chunks=chunks_text,
)
```

### FILE: `agents/synthesis.py`
The `score_contradiction_resolution` logic MUST use the fixed version (not the buggy `span not in final_answer` check). Synthesis must:
1. Log each flagged claim resolution as RESOLVE / REMOVE / HEDGE
2. Update `context.final_answer` with the resolved answer
3. Update `context.provenance_map`
4. Update `context.contradictions_resolved`

### FILE: `agents/compression.py`
Implement as described in plan FIX #4 and the compression agent spec.
Key: `_split_structured_filler()` must shield JSON blocks, `[CHUNK:id]` citations, URLs.

### FILE: `agents/meta.py`
```python
import difflib
from datetime import datetime
from typing import List, Optional
import json
from pydantic import BaseModel, Field
import uuid


class DiffLine(BaseModel):
    line_type: str  # "ADD" | "REMOVE" | "CONTEXT"
    content: str


class PromptRewrite(BaseModel):
    rewrite_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    proposed_at: datetime = Field(default_factory=datetime.utcnow)
    agent_id: str
    target_dimension: str
    original_prompt: str
    proposed_prompt: str
    diff_lines: List[DiffLine] = Field(default_factory=list)
    justification: str
    failure_cases: List[str] = Field(default_factory=list)
    expected_improvement: str
    status: str = "PENDING"
    reviewed_at: Optional[datetime] = None
    reviewer_note: Optional[str] = None
    delta_score: Optional[dict] = None

    def generate_diff(self) -> None:
        diff = list(difflib.ndiff(
            self.original_prompt.splitlines(),
            self.proposed_prompt.splitlines(),
        ))
        self.diff_lines = []
        for line in diff:
            if line.startswith("+ "):
                self.diff_lines.append(DiffLine(line_type="ADD", content=line[2:]))
            elif line.startswith("- "):
                self.diff_lines.append(DiffLine(line_type="REMOVE", content=line[2:]))
            elif line.startswith("  "):
                self.diff_lines.append(DiffLine(line_type="CONTEXT", content=line[2:]))


META_PROMPT = """You are the meta-agent responsible for improving pipeline prompts.

Read these evaluation failure cases:
{failure_cases_json}

The worst-performing dimension is: {worst_dimension}
The agent responsible for this dimension is: {agent_id}
The current prompt for that agent is:
---
{current_prompt}
---

Propose a rewritten version of this prompt that would fix the failures.
Be specific. Address each failure case explicitly.

Return JSON with keys:
- proposed_prompt: the new prompt text
- justification: why these changes will fix the failures
- expected_improvement: what score improvement you expect and why"""


class MetaAgent:
    def __init__(self, openai_api_key: str):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=openai_api_key)

    async def propose_rewrite(
        self,
        failure_cases: list,
        worst_dimension: str,
        agent_id: str,
        current_prompt: str,
    ) -> PromptRewrite:
        prompt = META_PROMPT.format(
            failure_cases_json=json.dumps(failure_cases[:5], indent=2),
            worst_dimension=worst_dimension,
            agent_id=agent_id,
            current_prompt=current_prompt[:2000],
        )
        resp = await self.client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content)

        rewrite = PromptRewrite(
            agent_id=agent_id,
            target_dimension=worst_dimension,
            original_prompt=current_prompt,
            proposed_prompt=data.get("proposed_prompt", current_prompt),
            justification=data.get("justification", ""),
            expected_improvement=data.get("expected_improvement", ""),
            failure_cases=[str(c.get("test_case_id", "")) for c in failure_cases],
        )
        rewrite.generate_diff()
        return rewrite
```

Commit: `feat(agents): all 7 agents — orchestrator, decomp, retrieval, critique, synthesis, compression, meta`