# MEGA-AI API Reference

This document details the 5 core FastAPI endpoints, their required JSON schemas, expected HTTP status codes, and the lifecycle of the Server-Sent Events (SSE) stream.

## Base URL
All API endpoints are hosted locally at `http://localhost:8000`. 
Interactive Swagger UI documentation is automatically generated at `http://localhost:8000/docs`.

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

### Response Lifecycle & Fallback
The server implements a **keep-alive fallback**. Because LangGraph loops might block for several seconds during heavy LLM generation, the API emits an empty `ping` event every 15 seconds to prevent client-side HTTP timeouts (like those enforced by Nginx or browser fetch APIs).

**Stream Event Types:**
- `AGENT_START`: The Orchestrator has invoked a specific agent.
- `TOKEN`: Real-time token usage updates.
- `TOOL_CALL_START` / `TOOL_CALL_END`: Marks the beginning and end of sandbox executions (e.g., SQL lookup).
- `BUDGET_UPDATE`: Emitted asynchronously after the `ContextBudgetManager` registers token consumption.
- `HANDOFF`: The Orchestrator has output a `RoutingDecision`.
- `COMPRESSION_TRIGGERED`: An agent hit the 80% budget threshold; the system is actively compressing context.
- `DONE`: Pipeline execution is complete; payload contains the final string.
- `ERROR`: A hard policy violation or system crash occurred.

**Example SSE Trace:**
```text
event: ping
data: {}

event: AGENT_START
data: {"agent_id": "orchestrator", "job_id": "8fbe4a54-..."}

event: HANDOFF
data: {"next_agent": "decomposition", "reasoning": "Needs sub-tasks", "confidence": 0.98}

event: BUDGET_UPDATE
data: {"agent_id": "orchestrator", "used": 542, "remaining": 2530}

event: DONE
data: {"final_answer": "Paris is the capital of France."}
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
Returns a JSON array of `ExecutionEventSchema` objects ordered by sequence ID.
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

---

## 3. Latest Evaluation Results
**GET** `/eval/latest`

Retrieves the results of the most recent evaluation harness run (`eval_runs` joined with `eval_results`).

### Request
```bash
curl -X GET "http://localhost:8000/eval/latest"
```

### Response (200 OK)
```json
{
  "run_id": "a1b2c3d4-...",
  "total_score": 0.83,
  "finished_at": "2026-05-08T21:00:00Z",
  "model_used": "gemini-2.0-flash",
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
  "detail": {
    "code": "REWRITE_ALREADY_REVIEWED",
    "message": "Rewrite b3c4d5e6 has already been approved.",
    "job_id": null
  }
}
```
- `404 Not Found`: 
```json
{
  "detail": {
    "code": "REWRITE_NOT_FOUND",
    "message": "No rewrite with ID b3c4d5e6",
    "job_id": null
  }
}
```

---

## 5. Re-run Evaluation
**POST** `/eval/run`

Triggers a manual, asynchronous execution of the evaluation harness. Optionally accepts a list of failed test case IDs to isolate testing. This endpoint queues the job and returns immediately.

### Request
```bash
curl -X POST "http://localhost:8000/eval/run" \
     -H "Content-Type: application/json" \
     -d '{"failed_case_ids": ["tc_12", "tc_14"]}'
```

### Response (202 Accepted)
```json
{ 
  "run_id": "uuid", 
  "status": "queued", 
  "case_count": 2 
}
```
Results are retrieved via `GET /eval/latest` after completion.
