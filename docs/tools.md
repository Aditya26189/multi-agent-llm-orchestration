# Tool System & Failure Contracts

The problem statement requires each tool to have a "defined failure contract:
what it returns on timeout, on empty results, and on malformed input."
All failure logic is implemented in Python (`core/tools.py`) as a `ToolAction`
enum dispatch. None of it lives in prompt strings.

## ToolAction Dispatch (core/tools.py)

```python
class ToolAction(str, Enum):
    RETRY_SAME         = "retry_same"         # TIMEOUT: transient, retry same input
    RETRY_REFORMULATE  = "retry_reformulate"  # NO_RESULTS: mutate input, then retry
    SKIP_LOG_VIOLATION = "skip_log_violation" # INVALID_INPUT: log PolicyViolation, skip
    FALLBACK_TOOL      = "fallback_tool"      # EXEC_ERROR: route to self_reflection
    ABORT              = "abort"              # All retries exhausted
```

The orchestrator receives the `ToolAction` result and dispatches accordingly.
This is the "explicit in code, not in a prompt" requirement from PS Section 2.

## Retry Pattern

Each tool allows up to 2 retries (3 total attempts). Each attempt is logged
as a **separate `ToolCallRecord`** with its own `attempt_number` (1, 2, or 3).
On `RETRY_REFORMULATE`, `modify_input_fn()` mutates the input before retry —
the same input is never sent twice on a `NO_RESULTS` failure.

```
Attempt 1 → failure → handle_tool_failure() → ToolAction
  RETRY_SAME:         attempt 2 with identical input
  RETRY_REFORMULATE:  modify_input_fn() first, then attempt 2 with new input
  SKIP_LOG_VIOLATION: log PolicyViolation, return immediately (no retry)
  FALLBACK_TOOL:      route to self_reflection tool
  ABORT:              return final ToolResult with error
```

---

## Tool 1 — web_search

**Purpose:** Returns structured search results with source URLs and relevance scores.
Currently a stub; replace with SerpAPI/Tavily for production.

| Condition | Error Code | ToolAction | Orchestrator Behaviour |
|-----------|-----------|------------|----------------------|
| Empty query string | `INVALID_INPUT` | `SKIP_LOG_VIOLATION` | Log PolicyViolation, skip tool |
| Timeout (>5 seconds) | `TIMEOUT` | `RETRY_SAME` | Retry up to 2× with same query |
| No results found | `NO_RESULTS` | `RETRY_REFORMULATE` | `broaden_web_query()`: truncate to first 3 words, increase max_results by 3 |
| All retries failed | `ABORT` | — | Route to `sql_lookup` as fallback |

**Return schema (success):**
```json
{
  "results": [
    {"title": "...", "url": "https://...", "snippet": "...", "relevance_score": 0.92}
  ],
  "query": "original query"
}
```

**Return schema (failure):**
```json
{"success": false, "error_code": "TIMEOUT", "latency_ms": 5100, "tool_name": "web_search"}
```

---

## Tool 2 — code_exec

**Purpose:** Execute Python snippets in a sandboxed subprocess. Returns stdout,
stderr, and exit code.

**Blocked patterns (INVALID_INPUT, never retried):**
`import os`, `subprocess`, `open(`, `importlib`, `pathlib`, `socket`,
`urllib`, `requests`, `__builtins__`, `exec(`, `eval(`

| Condition | Error Code | ToolAction | Orchestrator Behaviour |
|-----------|-----------|------------|----------------------|
| Blocked pattern in code | `INVALID_INPUT` | `SKIP_LOG_VIOLATION` | Log PolicyViolation, mark subtask UNRESOLVABLE |
| Empty code string | `INVALID_INPUT` | `SKIP_LOG_VIOLATION` | Same as above |
| Timeout (>10 seconds) | `TIMEOUT` | `RETRY_SAME` | Retry once |
| Runtime error (exit_code ≠ 0) | `EXEC_ERROR` | `RETRY_REFORMULATE` | Append stderr to prompt, retry once |
| Empty stdout (exit_code = 0) | — (success) | — | Accepted — empty output is valid |

**Return schema (success):**
```json
{"stdout": "4\n", "stderr": "", "exit_code": 0}
```

**Return schema (timeout):**
```json
{"success": false, "error_code": "TIMEOUT", "data": {"stdout": "", "stderr": "TimeoutExpired", "exit_code": 124}}
```

---

## Tool 3 — sql_lookup

**Purpose:** Convert natural language to SQL and query PostgreSQL.
Runs under `mega_ai_reader` (SELECT-only PostgreSQL role) — no DDL/DML possible.

**NL→SQL mechanism:** The agent makes an LLM call to convert the natural language query into a `SELECT` statement. Pattern:
```python
sql_prompt = f"Convert to SQL for the 'document_chunks' table: {nl_query}. Return only the SELECT statement."
sql = await agent_llm.generate(sql_prompt)
# Validated to start with SELECT before execution
```

| Condition | Error Code | ToolAction | Orchestrator Behaviour |
|-----------|-----------|------------|------------------------|
| Empty NL query | `INVALID_INPUT` | `SKIP_LOG_VIOLATION` | Log PolicyViolation, skip |
| LLM generates non-SELECT SQL | `INVALID_INPUT` | `SKIP_LOG_VIOLATION` | Log PolicyViolation, skip |
| DB connection timeout | `TIMEOUT` | `RETRY_SAME` | Retry once |
| Query returns 0 rows | `NO_RESULTS` | `RETRY_REFORMULATE` | Append "try broader criteria" to NL prompt, retry |
| SQL syntax error from DB | `EXEC_ERROR` | `RETRY_REFORMULATE` | Append DB error to NL prompt, retry with simpler SQL request |
| All retries failed | `ABORT` | — | Synthesis proceeds without structured data |

**Security note:** The `mega_ai_reader` PostgreSQL role is created in `scripts/seed_kb.py`
with `GRANT SELECT ON ALL TABLES`. The tool validates generated SQL starts with
`SELECT` before execution, providing two layers of write protection.

---

## Tool 4 — self_reflection

**Purpose:** Agent reads its own prior outputs within the session and identifies
contradictions. Accesses local `SharedContext` only — no network call.

| Condition | Error Code | ToolAction | Orchestrator Behaviour |
|-----------|-----------|------------|----------------------|
| Fewer than 2 prior outputs | NO_RESULTS | Accepted — synthesis proceeds |
| Agent ID not in context | REFLECTION_KEY_NOT_FOUND | SKIP_LOG_VIOLATION, no retry |
| LLM error | EXEC_ERROR | FALLBACK_TOOL — route to orchestrator |
| No contradictions found | — (success) | — | `{"has_contradictions": false}` — synthesis proceeds |
| Contradictions found | — (success) | — | `{"has_contradictions": true, "reflection": "..."}` — critique re-evaluates |

**Why self_reflection is the EXEC_ERROR fallback for other tools:**
When `tool_web_search` or `tool_code_exec` fails with `EXEC_ERROR` after retries,
the orchestrator routes to `self_reflection` to check if prior outputs already
contain enough information to synthesize without the failed tool. This prevents
unnecessary tool spiralling while still attempting to satisfy the user's query.

---

## Forensic Queryability

The `tool_calls` table has a GIN index on `input_json`:
```sql
CREATE INDEX idx_tool_calls_input ON tool_calls USING GIN (input_json);
```

This enables forensic queries like:
```sql
-- Which jobs called web_search with a query containing "France"?
SELECT job_id, attempt_number, latency_ms, accepted
FROM tool_calls
WHERE tool_name = 'web_search'
  AND input_json @> '{"query": "France"}';
```

All tool calls across all jobs are permanently auditable.
