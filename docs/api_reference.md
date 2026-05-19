# MEGA-AI API Reference

This document details the 5 core FastAPI endpoints, their required JSON schemas, expected HTTP status codes, and the lifecycle of the Server-Sent Events (SSE) stream.

## Base URL
All API endpoints are hosted locally at `http://localhost:8000`.
Interactive Swagger UI documentation is automatically generated at `http://localhost:8000/docs`.

> **Note:** The LogQuery UI (trace viewer, rewrite history, eval comparison) runs as a separate service at `http://localhost:8001`.

---

## 1. Submit Query (SSE Stream)
**POST** `/query`

Submits a new query to the system. Because MEGA-AI's multi-agent pipeline can take 10-20 seconds to execute, this endpoint immediately returns an HTTP 200 chunked response and streams updates via Server-Sent Events (SSE).

### Request
```bash
curl -X POST "http://localhost:8000/query" \
     -H "Content-Type: application/json" \
     -d '{"query": "What is the capital of France?"}'
```

**Note on adversarial test case tc_11 (prompt injection):**
The injection detector in `/query` blocks injections at the API layer before
they reach Celery. During evaluation, `EvaluationHarness` calls the pipeline
function directly (not via HTTP POST /query), so tc_11 tests the pipeline's
internal injection handling and agent-level robustness — not just the API
filter. Both layers are tested: the API filter via integration test, the
pipeline internals via the eval harness.

### Response Lifecycle & Fallback
### Response Lifecycle & Fallback
Note: Keep-alive ping events are not currently enabled. Reconnect via GET /jobs/{id}/trace if the stream drops.

**Stream Event Types:**
- `AGENT_START`: The Orchestrator has invoked a specific agent.
- `TOKEN`: Real-time token updates (emitted by Synthesis and Retrieval hop-2 only — other agents use JSON-mode which does not support streaming).
- `TOOL_CALL_START` / `TOOL_CALL_END`: Marks the beginning and end of sandbox executions (e.g., SQL lookup).
- `BUDGET_UPDATE`: Emitted asynchronously after the `ContextBudgetManager` registers token consumption.
- `HANDOFF`: The Orchestrator has output a `RoutingDecision`.
- `COMPRESSION_TRIGGERED`: An agent hit the 80% budget threshold; the system is actively compressing context.
- `DONE`: Pipeline execution is complete; payload contains the final string.
- `ERROR`: A hard policy violation or system crash occurred.

**Example SSE Trace:**
```text
id: 0
event: BUDGET_UPDATE
data: {"event_type": "BUDGET_UPDATE", "agent_id": "orchestrator", "used_tokens": 473, "max_tokens": 8192, "remaining_tokens": 7719, "pct_used": 5.8, "id": 0}

id: 0
event: HANDOFF
data: {"event_type": "HANDOFF", "next_agent": "decomposition", "reasoning": "...", "confidence": 1.0, "turn": 0, "id": 0}

id: 16
event: TOKEN
data: {"event_type": "TOKEN", "agent_id": "synthesis", "token": "Python is a high-level, interpreted, general-purpose programming language", "id": 16}

id: 24
event: done
data: {"event_type": "done", "job_id": "e08df389-9e8b-4a87-8445-7c8dfd885441", "final_answer": "Python is a high-level, interpreted, general-purpose programming language...", "provenance": [{"sentence": "Python is a high-level... [CHUNK:ee2f6813-47d5-4b51-b946-52cd65c101c5]", "source_agent": "synthesis", "source_chunk_id": null}], "id": 24}
```

### Error Response Format
All errors follow this machine-readable schema:
```json
{
  "error_code": "INJECTION_DETECTED",
  "message": "Query rejected: prompt injection pattern detected.",
  "job_id": null
}
```

---

## 2. Get Execution Trace
**GET** `/jobs/{job_id}/trace`

Fetches the complete, granular execution trace for a historical job directly from PostgreSQL. This is vital for debugging and is the primary data source for the LogQuery UI.

### Request
```bash
curl -X GET "http://localhost:8000/jobs/8fbe4a54-545c-49cc-8d8e-2c79e636f2ce/trace"
```

### Response (200 OK)
Returns a unified JSON array of events across `execution_events`, `routing_decisions`, and `tool_calls`, ordered chronologically by timestamp.
```json
[
  {
    "seq": 0,
    "job_id": "8fbe4a54-...",
    "agent_id": "orchestrator",
    "event_type": "AGENT_START",
    "latency_ms": 12.4,
    "token_count": 0,
    "timestamp": "2026-05-08T20:55:39Z"
  },
  {
    "seq": 1,
    "job_id": "8fbe4a54-...",
    "agent_id": "orchestrator",
    "event_type": "HANDOFF",
    "output_received": "{\"next_agent\": \"retrieval\"}",
    "latency_ms": 1450.2,
    "token_count": 420,
    "timestamp": "2026-05-08T20:55:41Z"
  }
]
```

### Error Response (404)
```json
{
  "error_code": "JOB_NOT_FOUND",
  "message": "No job found with ID: 8fbe4a54-...",
  "job_id": "8fbe4a54-..."
}
```

---

## 3. Latest Evaluation Results
**GET** `/eval/latest`

Retrieves the results of the most recent evaluation harness run (`eval_runs` joined with `eval_results`).

### Request
```bash
curl -X GET "http://localhost:8000/eval/latest"
```

### Response (200 OK)
> Example response format. Actual scores depend on eval run results.
```json
{
  "run_id": "a1b2c3d4-...",
  "total_score": 0.83,
  "finished_at": "2026-05-08T21:00:00Z",
  "model_used": "gemini-2.5-flash",
  "results": [
    {
      "test_case_id": "tc_01",
      "category": "BASELINE",
      "composite_score": 1.0,
      "answer_correctness": 1.0,
      "tool_efficiency": 1.0
    }
  ]
}
```

### Error Response (404 — no runs yet)
```json
{
  "error_code": "EVAL_NOT_READY",
  "message": "No evaluation runs have completed yet. Run POST /eval/run first.",
  "job_id": null,
  "timestamp": "2026-05-10T00:00:00Z"
}
```

---

## 4. Review Prompt Rewrite
**POST** `/rewrites/{rewrite_id}/review`

Approves or rejects a system prompt rewrite proposed by the Meta agent.

**Security:** Implements a strict `409 Conflict` database constraint to prevent double-approvals (which could corrupt prompt versioning).

### Request
```bash
curl -X POST "http://localhost:8000/rewrites/b3c4d5e6/review" \
     -H "Content-Type: application/json" \
     -d '{"approved": true, "reviewer_note": "Looks good"}'
```

### Response
- `200 OK`: `{"rewrite_id": "b3c4d5e6", "new_status": "approved", "message": "Rewrite approved. Run POST /eval/run to test the improved prompt."}`
- `409 Conflict`:
```json
{
  "error_code": "REWRITE_ALREADY_REVIEWED",
  "message": "Rewrite b3c4d5e6 already has status: approved",
  "job_id": null
}
```
- `404 Not Found`:
```json
{
  "error_code": "REWRITE_NOT_FOUND",
  "message": "No prompt rewrite with ID: b3c4d5e6",
  "job_id": null
}
```

---

## 5. Re-run Evaluation
**POST** `/eval/run`

Triggers a background evaluation run. Returns immediately; poll `GET /eval/latest` to see results when complete.

**Optional request body:**
```json
{"failed_case_ids": ["tc_01", "tc_02"], "use_latest_prompts": true}
```
Omit body to run all 15 test cases.

**Response (200 OK):**
```json
{"message": "Evaluation started in background."}
```

**Notes:**
- Evaluation runs asynchronously via `asyncio.create_task`
- Each test case takes ~4 seconds (Gemini free tier rate limit)
- Full 15-case run takes approximately 60-90 seconds
- Results stored in `eval_results` table, queryable via `GET /eval/latest`
- Use `MOCK_LLM=true` environment variable to bypass Gemini API calls during development (uses deterministic stub responses)

**tc_11 execution note:** The adversarial injection test case is routed through the pipeline's internal injection handler (not the API-layer filter) when triggered by the harness, testing both layers independently.

---

## LogQuery Service (port 8001)

The following analytical endpoints live in the separate LogQuery service and do **not** count toward the main API's 5-endpoint limit:

| Endpoint | Description |
|---|---|
| `GET /` | Execution trace viewer UI |
| `GET /rewrites` | List all prompt rewrites with status, timestamps, delta_score |
| `GET /eval/compare?run_a=&run_b=` | Side-by-side score comparison between two eval runs |
| `GET /trace?job_id=` | Full chronological event trace for a specific job |
