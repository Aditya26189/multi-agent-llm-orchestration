"""
4 tools with explicit failure contracts.
- Every tool returns a ToolResult. Never raises exceptions to the caller.
- Failure contracts are in Python code — NOT in prompt strings.
- ToolAction enum drives retry logic — NOT the LLM.
- modify_input_fn modifies query between retries.

Gemini override: tool_sql_lookup and tool_self_reflect use google.generativeai
instead of AsyncOpenAI.
"""
import asyncio
import time
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
    RETRY_SAME         = "retry_same"        # TIMEOUT: transient, retry same input
    RETRY_REFORMULATE  = "retry_reformulate" # NO_RESULTS: broaden/rephrase, then retry
    SKIP_LOG_VIOLATION = "skip_log_violation"# INVALID_INPUT: log PolicyViolation, skip
    FALLBACK_TOOL      = "fallback_tool"     # EXEC_ERROR: route to self_reflect
    ABORT              = "abort"             # all retries exhausted


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


# ── Tool 3: NL → SQL Lookup (Gemini) ─────────────────────────────────────────

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
    gemini_model=None,
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

        if gemini_model is None:
            import google.generativeai as genai
            import os
            genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
            gemini_model = genai.GenerativeModel("gemini-2.0-flash")

        resp = await asyncio.to_thread(gemini_model.generate_content, prompt)
        sql = resp.text.strip().strip("```sql").strip("```").strip()

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


# ── Tool 4: Self-Reflection (Gemini) ──────────────────────────────────────────

async def tool_self_reflect(
    agent_id: str,
    context: "SharedContext",
    gemini_model=None,
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
        if gemini_model is None:
            import google.generativeai as genai
            import os
            genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
            gemini_model = genai.GenerativeModel("gemini-2.0-flash")

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

        resp = await asyncio.to_thread(gemini_model.generate_content, prompt)
        reflection = resp.text.strip()

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
            attempt_number=min(attempt, 3),
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
