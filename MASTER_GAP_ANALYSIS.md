# MEGA-AI — MASTER GAP ANALYSIS
# Cross-reference: PS requirements vs Doc2 (claims) vs Doc3 (audit) vs Doc4 (fix prompt) vs Doc5 (fix prompt) vs Uploaded fix prompt
# Generated: May 10, 2026

---

## HOW TO READ THIS

- ✅ Implemented and verified
- ⚠️ Claimed but unverified or partially wrong
- ❌ Missing, broken, or not addressed by ANY fix prompt
- 🔁 Addressed in fix prompts (needs execution)
- ⚡ CONTRADICTION between fix prompts (must resolve before running agent)

---

# SECTION 1 — PS §1: MULTI-AGENT ORCHESTRATION

## 1.1 — Master orchestrator dynamically routes at runtime
**PS says:** "dynamically decides which sub-agents to invoke, in what order, and with what context window budget"
**Doc2 claims:** LangGraph StateGraph with LLM-based routing decisions ✅
**Doc3 found:** Deterministic fallback exists but silent END on unknown agent name ⚠️
**Fix prompts:** Doc4 Task 3.1, Doc5 Task 8, Uploaded Step 7 all fix the silent END 🔁
**Status:** 🔁 FIX EXISTS — execute it

## 1.2 — Routing decisions logged with justification
**PS says:** "Routing decisions must be logged with justification"
**Doc2 claims:** RoutingDecision objects with reasoning field ⚠️
**Doc3 found:** Routing decisions NOT persisted to DB — Redis only, lost after task ❌
**Fix prompts:** All three fix prompts add DB persistence for routing_decisions table 🔁
**Status:** 🔁 FIX EXISTS — execute it

## 1.3 — Decomposition agent with explicit dependency graphs
**PS says:** "breaks ambiguous queries into typed sub-tasks with explicit dependency graphs — dependent sub-tasks must not execute until dependencies resolve"
**Doc2 claims:** DependencyExecutor with asyncio.Event blocking and DFS cycle detection ✅
**Doc3:** Confirmed implemented correctly ✅
**Fix prompts:** All confirm working. Uploaded Step 10 adds topological sort as alternative.
**Status:** ✅ IMPLEMENTED — verify it still works after other changes

## 1.4 — Critique agent reviews output of EVERY OTHER agent
**PS says:** "reviews the output of every other agent"
**Doc2 claims:** Reviews retrieval + synthesis outputs ⚠️
**Doc3:** Not specifically audited
**Fix prompts:** NONE address whether critique reviews decomposition output
**Status:** ❌ NOT ADDRESSED IN ANY FIX PROMPT
**Action needed:** Open agents/critique.py. The critique prompt must reference decomposition sub-tasks, retrieval output, AND synthesis draft — all three. If it only reviews retrieval+synthesis, add decomposition output to the critique context.

## 1.5 — Retrieval agent: multi-hop reasoning across at least TWO retrieved chunks
**PS says:** "multi-hop reasoning across at least two retrieved chunks before forming an answer. Single-hop retrieval is not sufficient."
**Doc2 claims:** 2-hop with hop1→LLM→hop2_query→hop2 ⚠️
**Doc3:** Not end-to-end verified
**Fix prompts:** Doc4 Task 9.1, Doc5 Task 14, Uploaded Step 16 all verify/fix 2-hop logic 🔁
**Status:** 🔁 FIX EXISTS — execute it

## 1.6 — Retrieval agent cites which chunk contributed to which PART of answer
**PS says:** "must cite which chunk contributed to which part of the answer"
**Doc2 claims:** ProvenanceEntry with source_chunk_id ⚠️
**Doc3:** Notes unprefixed synthesis sentences have no chunk ID
**Fix prompts:** Doc4 Task 6.1, Doc5 Task 17, Uploaded Step 16 fix provenance completeness 🔁
**Status:** 🔁 FIX EXISTS — execute it. But verify that [CHUNK:id] citations appear mid-sentence, not just at end of answer.

## 1.7 — Synthesis agent produces provenance map linking EACH sentence to source agent AND source chunk
**PS says:** "provenance map linking each sentence to its source agent and source chunk"
**Doc2 claims:** ProvenanceEntry(sentence, source_agent, source_chunk_id) ✅
**Doc3:** 20-30% of synthesis sentences have no chunk attribution (source_chunk_id=None)
**Fix prompts:** Provenance fallback fix addressed in all three fix prompts 🔁
**Status:** 🔁 FIX EXISTS — note: synthesis-only sentences legitimately have source_chunk_id=None. The README must explain this. It is not a bug for synthesized reasoning.

## 1.8 — Agents must NOT call each other directly — orchestrator mediates all handoffs
**PS says:** "Agents must not call each other directly. The orchestrator mediates all handoffs."
**Doc2 claims:** All through SharedContext ⚠️
**Doc3:** Not audited
**Fix prompts:** Doc5 Task 10, Uploaded: run cross-import audit 🔁
**Status:** 🔁 FIX EXISTS — run this command before submission:
```bash
grep -r "from agents\." agents/ --include="*.py" | grep -v __pycache__ | grep -v "from agents.base"
```
Zero results = compliant.

---

# SECTION 2 — PS §2: TOOL CALLING

## 2.1 — Web search stub returns structured results with SOURCE URLS AND RELEVANCE SCORES
**PS says:** "structured results with source URLs and relevance scores"
**Doc2 claims:** ToolResult with data dict ⚠️
**Doc3:** Not specifically audited
**Fix prompts:** NONE verify that relevance_score field is in web search results
**Status:** ❌ NOT ADDRESSED IN ANY FIX PROMPT
**Action needed:** Open core/tools.py or agents/tools.py. Find tool_web_search(). Its ToolResult.data must include structure like:
```python
{
  "results": [
    {"url": "https://...", "title": "...", "snippet": "...", "relevance_score": 0.87},
    ...
  ]
}
```
If relevance_score is absent, add it. For a stub, compute relevance_score as simple keyword overlap between query and snippet, normalized 0.0-1.0.

## 2.2 — Code execution sandbox returns stdout, stderr, AND exit code
**PS says:** "runs Python snippets and returns stdout, stderr, and exit code"
**Doc2:** Mentions tool exists but not the return schema
**Doc3:** Not audited
**Fix prompts:** NONE verify the code execution sandbox return schema
**Status:** ❌ NOT VERIFIED IN ANY FIX PROMPT
**Action needed:** Open the code execution tool. Verify ToolResult.data contains:
```python
{"stdout": "...", "stderr": "...", "exit_code": 0}
```
If missing, add. The PS requires all three fields.

## 2.3 — NL→SQL conversion done BY THE AGENT (LLM call)
**PS says:** "queries a local database via natural language converted to SQL by the agent"
**Doc2:** Mentions SQL lookup tool exists
**Doc3:** Not audited
**Fix prompts:** NONE verify the LLM actually generates SQL from NL
**Status:** ❌ NOT VERIFIED IN ANY FIX PROMPT
**Action needed:** Open the SQL lookup tool. There must be an LLM call that converts natural language to a SELECT statement. Pattern:
```python
nl_query = "how many documents were added last week"
sql_prompt = f"Convert to SQL for table 'documents': {nl_query}. Return only the SELECT statement."
sql = await agent_llm.generate(sql_prompt)
result = await db.execute(sql)
```
If hardcoded SQL — fix it. The PS specifically says "converted to SQL by the agent."
Also verify: READ-ONLY enforcement. The tool must reject non-SELECT statements.

## 2.4 — Self-reflection tool reads agent's OWN previous outputs within session
**PS says:** "the agent can call to re-read its own previous outputs within the session and identify contradictions"
**Doc2 claims:** Reads from context.execution_events filtered by agent_id ✅
**Doc3:** Confirmed implemented
**Fix prompts:** Verified as working
**Status:** ⚠️ PARTIAL — the PS says "the agent CAN CALL" it (proactive capability). Doc2 says it's triggered only when a tool fails with EXEC_ERROR (reactive). The self-reflection tool must also be callable proactively by any agent. Verify the orchestrator can route to self-reflection even without a tool failure.

## 2.5 — Each tool: defined failure contract (TIMEOUT, EMPTY RESULTS, MALFORMED INPUT)
**PS says:** "defined failure contract: what it returns on timeout, on empty results, and on malformed input"
**Doc2:** ToolResult with error_code field ⚠️
**Doc3:** Not all failure modes verified for all 4 tools
**Fix prompts:** Doc4 Task 4.4, Doc5 Task 13, Uploaded Step add timeout/empty/invalid to all 4 tools 🔁
**Status:** 🔁 FIX EXISTS — execute for ALL 4 tools (web_search, code_exec, sql_lookup, self_reflect)

## 2.6 — Orchestrator handles EACH failure mode DIFFERENTLY
**PS says:** "The orchestrator must handle each failure mode differently"
**Doc2:** ToolAction enum dispatch
**Doc3:** Not specifically audited
**Fix prompts:** NONE verify orchestrator uses DIFFERENT logic for TIMEOUT vs NO_RESULTS vs INVALID_INPUT
**Status:** ❌ NOT ADDRESSED IN ANY FIX PROMPT
**Action needed:** Open orchestrator routing logic. The response to a TIMEOUT should differ from NO_RESULTS and INVALID_INPUT. Example:
- TIMEOUT → retry same tool with same input after wait
- NO_RESULTS → retry tool with MODIFIED input
- INVALID_INPUT → skip this tool, use different tool or fallback
If the orchestrator handles all three the same way (e.g., always retry), this is a PS violation.

## 2.7 — Fallback logic EXPLICIT IN CODE, not in prompt instruction
**PS says:** "Fallback logic must be explicit in code, not embedded in a prompt instruction"
**Doc2 claims:** ToolAction enum with explicit Python dispatch ✅
**Doc3:** Confirmed for tool fallbacks
**Fix prompts:** All mention code-based fallback
**Status:** ✅ Assumed implemented — verify no fallback instructions hidden in any agent system prompt

## 2.8 — Tool calls logged: input, output, latency, AND WHETHER AGENT ACCEPTED OR REJECTED
**PS says:** "Tool calls must be logged with input, output, latency, and whether the agent accepted or rejected the tool output after receiving it"
**Doc2:** ExecutionEventSchema has fields ⚠️
**Doc3:** tool_accepted field not in DB schema
**Fix prompts:** Doc4 Task 4.1, Doc5 Task 10, Uploaded Step 9 all add tool_accepted/rejected logging 🔁
**Status:** 🔁 FIX EXISTS — execute it

## 2.9 — Re-call with MODIFIED INPUT, up to 2 retries, EACH RETRY LOGGED SEPARATELY
**PS says:** "re-call the tool with a modified input, up to two retries, with each retry logged separately"
**Doc2:** Retry logic exists ⚠️
**Doc3:** Not verified that input is actually modified between retries
**Fix prompts:** Doc4 Task 4.3, Doc5 Task 13, Uploaded Step verify modified input 🔁
**Status:** 🔁 FIX EXISTS — the KEY requirement is that retry attempt 2 uses a DIFFERENT query than attempt 1. The tool_call_log must show different input_data for attempt_number=1 vs 2.

---

# SECTION 3 — PS §3: CONTEXT WINDOW MANAGEMENT

## 3.1 — Budget manager tracks token consumption per agent PER TURN
**PS says:** "tracks token consumption per agent per turn"
**Doc2 claims:** Static budget declaration, consume() method ⚠️
**Doc3:** Static budgets, not per-turn
**Fix prompts:** NONE address the "per turn" aspect of budget tracking
**Status:** ❌ NOT ADDRESSED — the current implementation uses a single cumulative budget per agent for the entire job, not per-turn. PS says "per turn." This may require adding a turn counter to BudgetEntry and resetting used_tokens per turn. However, this is a significant refactor. Minimum viable: document it as a known limitation.

## 3.2 — Each agent declares max context budget BEFORE execution
**PS says:** "Each agent must declare its maximum context budget before execution"
**Doc2 claims:** declare_budget() called at start ✅
**Fix prompts:** Confirmed implemented
**Status:** ✅ IMPLEMENTED — verify declare_budget() is called before ANY agent runs, not after

## 3.3 — Budget manager exposes method any agent can call to CHECK REMAINING BUDGET before adding content
**PS says:** "The context manager must expose a method that any agent can call to check remaining budget before adding to its context"
**Doc2 claims:** check_remaining() method exists ✅
**Fix prompts:** Confirmed implemented
**Status:** ✅ IMPLEMENTED

## 3.4 — Agents that overflow: CAUGHT AND LOGGED AS POLICY VIOLATION (not silently truncated)
**PS says:** "Agents that ignore budget constraints and overflow must be caught and logged as a policy violation, not silently truncated"
**Doc2 claims:** BudgetOverflowError raised ⚠️
**Doc3:** Gap: assert_compliant() not always called before agent execution
**Fix prompts:** Doc4 Task 5.1, Doc5 Task 9, Uploaded Step 8 add budget enforcement wrapper 🔁
**Status:** 🔁 FIX EXISTS — execute the wrapper that guarantees assert_compliant() is called for every agent

## 3.5 — Compression: lossless for structured data, lossy for filler
**PS says:** "lossless for structured data (tool outputs, scores, citations) and lossy only for conversational filler"
**Doc2 claims:** _split_structured_filler() with regex patterns ✅
**Doc3:** Confirmed implemented
**Fix prompts:** Doc4 Task 9.2, Doc5 Task 15, Uploaded Step 17 verify compression 🔁
**Status:** 🔁 FIX EXISTS — run the verify test to confirm structured data is shielded

---

# SECTION 4 — PS §4: EVALUATION PIPELINE

## 4.1 — 15 test cases through FULL PIPELINE
**PS says:** "runs 15 test cases through the full pipeline"
**Doc2 claims:** 15 test cases defined in test_cases.json ⚠️
**Doc3:** NEVER ACTUALLY RUN — all scores are fabricated ❌
**Fix prompts:** Doc4 Task 2.1, Doc5 Task 3, Uploaded Step 4 all require running real harness 🔁
**Status:** 🔁 MOST CRITICAL EXECUTION ITEM — after rate_limiter fix, run the harness

## 4.2 — Multi-dimensional scoring: 6 dimensions each with NUMERIC SCORE AND JUSTIFICATION STRING
**PS says:** "Each dimension must produce a numeric score with a written justification string, not just a number"
**Doc2 claims:** All 6 dimensions return (float, str) tuples ✅
**Doc3:** Confirmed implemented for all 6
**Status:** ✅ IMPLEMENTED — verify with real run that justifications are specific (not generic templates)

## 4.3 — Adversarial case: critique-synthesis disagreement must RESOLVE, not surface to user
**PS says:** "queries designed to cause the critique agent to disagree with the synthesis agent and produce a contradiction that the system must resolve rather than surface to the user"
**Doc2 claims:** Synthesis has RESOLVE/REMOVE/HEDGE logic ⚠️
**Doc3:** tc_14 not verified end-to-end
**Fix prompts:** NONE verify that contradictions are always resolved internally and NEVER returned to user as "the system disagrees about X"
**Status:** ❌ NOT ADDRESSED IN ANY FIX PROMPT
**Action needed:** In agents/synthesis.py, verify the final_answer text NEVER contains phrases like "the critique agent disagreed" or "there is a contradiction" visible to the end user. All conflicts must be resolved or hedged silently.

## 4.4 — Exact prompts sent to EACH AGENT stored in eval_results
**PS says:** "exact prompt sent to each agent" stored per eval run
**Doc2 claims:** prompt_sent_json column in eval_results ⚠️
**Doc3:** Not verified which agents' prompts are stored
**Fix prompts:** NONE specifically verify that prompts for ALL agents (not just the final synthesis) are stored
**Status:** ❌ NOT ADDRESSED IN ANY FIX PROMPT
**Action needed:** The eval_results.prompt_sent_json must store prompts for ALL 4+ agents in that run, not just the orchestrator's final prompt. Either store as JSONB dict keyed by agent_id, or link to execution_events table.

## 4.5 — Re-running eval produces DIFF-ABLE output so regressions are visible
**PS says:** "Re-running the eval on the same inputs must produce a diff-able output so regressions are immediately visible"
**Doc2 claims:** Partial — DB schema exists, no diff endpoint ⚠️
**Doc3:** No diff endpoint
**Fix prompts:** Doc4 Task 8.1 adds /eval/compare endpoint, but then says "if over 5 endpoints, put in logquery" 🔁
**Status:** ⚡ CONTRADICTION — /eval/compare makes 6 endpoints which violates PS §7 ("exactly 5"). 
**Resolution:** PUT /eval/compare in the logquery service (port 8001), NOT in the main API. Add it to logquery/app.py instead. This satisfies both PS §4 (diff-ability) and PS §7 (exactly 5 endpoints).

---

# SECTION 5 — PS §5: SELF-IMPROVING PROMPT LOOP

## 5.1 — Meta-agent identifies worst-performing prompt BY DIMENSION
**PS says:** "identifies the worst-performing prompt in the pipeline by dimension"
**Doc2:** Not mentioned in original implementation
**Doc3:** Not implemented
**Fix prompts:** Doc4 Task 7.1, Doc5 Task 11, Uploaded Step 14 all implement meta-agent 🔁
**Status:** 🔁 FIX EXISTS — execute it

## 5.2 — Proposed rewrite stored BUT NOT AUTOMATICALLY APPLIED
**PS says:** "proposed rewrite must be stored but not automatically applied"
**Fix prompts:** All implement this correctly with status='pending'
**Status:** ✅ ADDRESSED IN FIX PROMPTS

## 5.3 — Human approval/rejection endpoint
**PS says:** "A separate endpoint must allow a human to approve or reject the rewrite"
**Fix prompts:** Doc4 Task 7.2, Doc5 Task 12, Uploaded Step 15 all implement POST /rewrites/{id}/review 🔁
**Status:** 🔁 FIX EXISTS — this is endpoint #4 of exactly 5

## 5.4 — If approved: re-run eval on ONLY PREVIOUSLY FAILED CASES using NEW PROMPT
**PS says:** "If approved, the system must re-run the eval on only the previously failed cases using the new prompt"
**Fix prompts:** All implement the re-eval endpoint 🔁
**Status:** ⚡ CRITICAL UNADDRESSED GAP — all fix prompts implement the re-eval TRIGGER but NONE implement the actual mechanism of APPLYING the approved prompt. The agent system prompts are module-level Python constants. How does the approved prompt override the module constant at runtime?
**Action needed:** 
```python
# In worker/tasks.py or harness.py, before running agents:
if rewrite_id:
    rewrite = await db.get(PromptRewrite, rewrite_id)
    if rewrite and rewrite.status == "approved":
        # Override the agent's prompt at runtime
        import agents.retrieval as ret_module  # or whichever agent
        setattr(ret_module, rewrite.target_prompt_constant, rewrite.proposed_prompt)
```
This needs to be explicitly coded. Without it, re-eval runs with the ORIGINAL prompt, not the approved one. The feature is completely non-functional without this.

## 5.5 — Log DELTA IN PERFORMANCE after approved re-eval
**PS says:** "log the delta in performance"
**Doc2:** delta_score column mentioned
**Fix prompts:** NONE show code that COMPUTES and STORES the delta after re-eval completes
**Status:** ❌ NOT ADDRESSED IN ANY FIX PROMPT
**Action needed:** After re-eval completes, compute delta and store:
```python
# At end of targeted_reeval run in harness:
if rewrite_id:
    # Get prev scores for same test cases
    prev_scores = await get_scores_for_cases(db, prev_run_id, failed_ids)
    new_scores = await get_scores_for_cases(db, new_run_id, failed_ids)
    delta = avg(new_scores) - avg(prev_scores)
    await db.execute(
        "UPDATE prompt_rewrites SET delta_score=:d WHERE id=:id",
        {"d": delta, "id": rewrite_id}
    )
    await db.commit()
```

## 5.6 — Every rewrite, approval/rejection, performance delta stored with TIMESTAMPS AND QUERYABLE
**PS says:** "Every proposed rewrite, every approval or rejection, and every performance delta must be stored with timestamps and be queryable"
**Fix prompts:** All create prompt_rewrites table with status/reviewed_at 🔁
**Status:** ❌ PARTIALLY UNADDRESSED — there is NO GET endpoint to LIST all rewrites with their status. PS says "queryable." You need:
```
GET /rewrites  — list all rewrites, status, timestamps, delta_score
```
BUT PS says exactly 5 endpoints. This means /rewrites list must go in the logquery service (port 8001), not the main API. Add it to logquery/app.py.

---

# SECTION 6 — PS §6: STREAMING AND OBSERVABILITY

## 6.1 — All agent outputs streamed token by token via SSE
**PS says:** "All agent outputs must be streamed token by token"
**Doc2:** Redis pub/sub → SSE streaming ⚠️
**Fix prompts:** Assume SSE works
**Status:** ⚠️ UNVERIFIED — most LLM SDKs stream at response chunk level, not true per-token. Verify your SSE handler is using Gemini streaming mode (generate_content(..., stream=True)) and emitting each chunk as it arrives, not buffering the full response.

## 6.2 — Client sees WHICH AGENT is currently writing
**PS says:** "The client must be able to see which agent is currently writing"
**Fix prompts:** AGENT_START events in SSE
**Status:** ✅ ADDRESSED — each agent publishes AGENT_START to Redis before writing

## 6.3 — Client sees WHAT TOOL CALLS ARE IN FLIGHT in real time
**PS says:** "what tool calls are in flight... all in real time as the pipeline executes"
**Fix prompts:** Doc4 Task 4.2, Doc5 Task 10, Uploaded Step 9 add TOOL_START/TOOL_END Redis events 🔁
**Status:** ⚡ PARTIALLY ADDRESSED — the fix prompts ADD Redis publish calls for TOOL_START/TOOL_END, but NONE verify that the SSE handler in api/routes.py actually FORWARDS these events to the client. The SSE endpoint must subscribe to all event types including TOOL_START. Verify the SSE handler does not filter out tool events.

## 6.4 — Client sees CURRENT CONTEXT BUDGET REMAINING in real time
**PS says:** "current context budget remaining... in real time as the pipeline executes"
**Doc2:** BUDGET_UPDATE events published to Redis
**Fix prompts:** Doc4 Task 5.1 adds budget_update to Redis publish
**Status:** ⚡ SAME GAP AS 6.3 — Redis publish exists but verify SSE handler forwards BUDGET_UPDATE events to client stream

## 6.5 — Structured logging schema: timestamp, agent ID, event type, input hash, output hash, latency, token count, policy violations
**PS says:** All these fields required
**Doc2 claims:** ExecutionEventSchema has all these ✅
**Fix prompts:** DB schema in all fix prompts includes all fields 🔁
**Status:** ✅ ADDRESSED — verify all fields are non-null in actual DB rows after a run

## 6.6 — Logs must be QUERYABLE
**PS says:** "Logs must be queryable"
**Doc2:** logquery service on port 8001 ✅
**Fix prompts:** NONE update logquery/app.py to query the NEW execution_events DB table
**Status:** ❌ NOT ADDRESSED IN ANY FIX PROMPT
**Action needed:** After adding DB persistence (Step 3), the logquery Flask app at logquery/app.py still queries the old in-memory or Redis data. Update it to query the new DB tables:
```python
@app.route("/trace")
def trace():
    job_id = request.args.get("job_id")
    # Query DB instead of Redis:
    conn = get_db_connection()
    events = conn.execute(
        "SELECT * FROM execution_events WHERE job_id=? ORDER BY timestamp", 
        (job_id,)
    ).fetchall()
    return render_template("trace.html", events=events)
```

## 6.7 — Single endpoint returns FULL EXECUTION TRACE for job ID, IN ORDER
**PS says:** "reconstructing the exact sequence of agent decisions, tool calls, and handoffs in order"
**Doc2:** /jobs/{id}/trace endpoint ⚠️
**Fix prompts:** Doc4 Task 3.2, Doc5 Task 2G all fix the trace endpoint to query from DB 🔁
**Status:** 🔁 FIX EXISTS — the trace endpoint must return events, routing_decisions, AND tool_calls in unified chronological order. Verify the response sorts by timestamp across all three tables.

---

# SECTION 7 — PS §7: API — EXACTLY 5 ENDPOINTS

## THE 5 REQUIRED ENDPOINTS:
1. POST /query → streaming SSE
2. GET /jobs/{job_id}/trace → execution trace
3. GET /eval/latest → summary by category and scoring dimension
4. POST /rewrites/{id}/review → approve or reject
5. POST /eval/run → trigger targeted re-eval

**⚡ CRITICAL: PS says EXACTLY 5. Any endpoint beyond these 5 violates the spec.**

**What fix prompts are adding beyond 5:**
- Doc4 adds /eval/compare → MUST GO TO logquery (port 8001), NOT main API
- Doc5 adds /eval/compare → SAME: logquery only
- GET /rewrites (list) → logquery only

**⚡ CONFLICT IN FIX PROMPTS:**
- Doc5 Task 12 and final verification check for /eval/rerun-failures
- Doc4 uses /eval/run for the same purpose
- Uploaded doc uses /eval/rerun-failures in final check
**Resolution:** Use POST /eval/run for endpoint #5. ONE name, consistently.

**Error response format:**
**PS says:** "Error responses must include a machine-readable error code, a human-readable message, and the job ID if applicable"
**Fix prompts:** Some endpoints show this pattern, others don't
**Status:** ⚠️ VERIFY every endpoint returns errors in this exact format:
```json
{"error_code": "NOT_FOUND", "message": "Job xyz not found", "job_id": "xyz"}
```

**All endpoints must be DOCUMENTED:**
**Status:** ✅ FastAPI auto-generates OpenAPI docs at /docs — this satisfies the requirement if all endpoints have proper docstrings and response_model annotations.

---

# SECTION 8 — PS §8: CONTAINERIZATION

## 8.1 — docker compose up starts everything with ZERO MANUAL STEPS
**Status:** ⚠️ UNVERIFIED — the uploaded prompt Step 11 final check verifies this. Run it.

## 8.2 — Four required services
**PS says:** API server, background worker, database, lightweight log query interface
**Status:** ✅ All 4 present (api, worker, db, logquery). Redis and seeder are reasonable additions.

## 8.3 — Environment variables ONLY for config, NO hardcoded credentials
**Fix prompts:** Final verification includes grep check for hardcoded secrets
**Status:** ✅ VERIFY with:
```bash
grep -r "password\|api_key\|secret" . --include="*.py" | grep -v "os.environ\|os.getenv\|\.env" | grep -v "#"
```

---

# SECTION 9 — PS §9: GITHUB REPOSITORY

## 9.1 — Architecture diagram (text or image)
**PS says:** "architecture diagram as a text or image file"
**Fix prompts:** NONE create an architecture diagram
**Status:** ❌ NOT ADDRESSED IN ANY FIX PROMPT
**Action needed:** Add to README.md a text-based architecture diagram:
```
┌─────────────────────────────────────────────────┐
│                   CLIENT                        │
│                (SSE Stream)                     │
└─────────────────┬───────────────────────────────┘
                  │ POST /query
┌─────────────────▼───────────────────────────────┐
│              FastAPI (port 8000)                │
│   /query  /jobs/trace  /eval  /rewrites         │
└─────────────────┬───────────────────────────────┘
                  │ Celery task
┌─────────────────▼───────────────────────────────┐
│           Celery Worker + LangGraph             │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │
│  │Orchestr. │→ │Decompose │→ │  Retrieval   │  │
│  └──────────┘  └──────────┘  └──────────────┘  │
│       ↑              ↓              ↓           │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │
│  │Synthesis │← │Critique  │← │  SharedCtx   │  │
│  └──────────┘  └──────────┘  └──────────────┘  │
└─────────────────┬───────────────────────────────┘
         ┌────────┴────────┐
┌────────▼────┐   ┌────────▼────┐
│ PostgreSQL  │   │    Redis    │
│ + pgvector  │   │  (pub/sub)  │
└─────────────┘   └─────────────┘
```

## 9.2 — Description of EVERY AGENT and its DECISION BOUNDARIES
**PS says:** "a description of every agent and its decision boundaries"
**Fix prompts:** NONE add agent decision boundary descriptions to README
**Status:** ❌ NOT ADDRESSED IN ANY FIX PROMPT
**Action needed:** Add to README a section like:

```markdown
## Agent Decision Boundaries

### Orchestrator
Decides: which agent to invoke next, in what order, with what token budget
Does NOT decide: what content to generate (delegates to sub-agents)
Limits: MAX_TURNS=10, MAX_TOOL_CALLS=20 per job

### Decomposition Agent
Decides: how many sub-tasks to create (1-5), what dependencies exist between them
Does NOT decide: how to answer sub-tasks (delegates to retrieval)
Limits: will not create circular dependencies (DFS cycle detection)

### Retrieval Agent
Decides: what to search for (hop1 query), what follow-up to search for (hop2 query)
Does NOT decide: what the final answer is (outputs raw retrieved content)
Limits: 2 hops maximum, top-K=3 chunks per hop

### Critique Agent
Decides: which specific text spans are low-confidence, what the flag reason is
Does NOT decide: how to fix flagged spans (delegates to synthesis)
Limits: only flags spans with confidence < 0.6

### Synthesis Agent
Decides: how to resolve flagged spans (RESOLVE/REMOVE/HEDGE)
Does NOT decide: which spans to flag (from critique agent)
Limits: must address every flagged span before returning final answer

### Meta Agent
Decides: which dimension had worst performance, which agent is responsible
Does NOT decide: whether to apply the rewrite (human must approve)
Limits: proposes one rewrite per eval run
```

## 9.3 — Known limitations with HONEST ASSESSMENT
**Fix prompts:** All add a limitations section to README 🔁
**Status:** 🔁 FIX EXISTS — execute it. Make sure it's honest about ALL known gaps.

## 9.4 — What self-improving loop DOES AND DOES NOT DO
**Fix prompts:** Addressed in limitations section
**Status:** ✅ ADDRESSED IN FIX PROMPTS

## 9.5 — What you would build next
**Fix prompts:** Addressed in all three
**Status:** ✅ ADDRESSED IN FIX PROMPTS

---

# SECTION 10 — ASSESSMENT CRITERIA (not PS but evaluated)

## 10.1 — "Can a stranger run this in 5 minutes?"
**Fix prompts:** README improvements mentioned
**Status:** ❌ NONE ADD A CLEAR QUICK-START SECTION
**Action needed:** Add to top of README:
```markdown
## Quick Start (5 minutes)

1. Clone the repo
2. Copy `.env.example` to `.env` and add your `GOOGLE_API_KEY`
3. Run: `docker compose up -d`
4. Wait ~30 seconds for seeding to complete
5. Test: `curl -X POST http://localhost:8000/query -H "Content-Type: application/json" -d '{"query": "What is Python?"}'`
6. View logs: http://localhost:8001
```

## 10.2 — "Does the git history tell a story?"
**Fix prompts:** NONE address commit strategy
**Status:** ❌ NOT ADDRESSED IN ANY FIX PROMPT
**Action needed:** Every fix you execute should be a SEPARATE commit with a meaningful message:
```
git commit -m "fix: add core/rate_limiter.py — fixes ImportError in retrieval agent"
git commit -m "fix: persist execution_events to PostgreSQL — enables /jobs/trace"
git commit -m "feat: real eval harness run — 15 test cases with genuine scores"
git commit -m "fix: citation scoring uses keyword content match, not just ID presence"
```
NOT: `git commit -m "final fixes"` or one giant commit.

## 10.3 — "Pragmatism vs Over-engineering"
**Status:** ✅ FINE — complexity is PS-mandated, not self-imposed

## 10.4 — "Reproducibility and Code Quality"
**Status:** ⚠️ NEEDS REAL EVAL RESULTS IN DB — currently no reproducible outputs exist

---

# SECTION 11 — CONTRADICTIONS BETWEEN FIX PROMPTS (RESOLVE BEFORE RUNNING)

## C1 — Table name inconsistency
- Doc4 uses: `prompt_rewrites`
- Uploaded fix verification checks for: `prompt_rewrite_log`
**Resolution:** Use `prompt_rewrites` (more consistent with code naming convention)
**Action:** Search all files and use ONE name everywhere.

## C2 — Re-eval endpoint name inconsistency
- Doc4: POST /eval/run
- Doc5 Task 12: POST /eval/run
- Uploaded final verification checks for: /eval/rerun-failures
**Resolution:** Use POST /eval/run (this is endpoint #5 per PS §7)

## C3 — Citation scoring depth inconsistency
- Doc4 Task 2.3: "simple chunk-ID existence check is fine — don't over-engineer"
- Doc5 Task 4: Use `_content_match()` with keyword overlap
- Uploaded Step 5: Use keyword overlap
**Resolution:** Use keyword overlap `_content_match()` — it's documented as implemented in Doc5 and is the better behavior. Doc4's "don't over-engineer" note was overridden by later prompts.

## C4 — Rate limiter function name inconsistency
- Doc5 (internal) creates `call_with_retry()`
- Doc4 creates `call_with_retry()`
- Uploaded doc creates `call_with_backoff()`
**Resolution:** Use `call_with_backoff` — this matches the uploaded prompt which is the most recent. But agents/retrieval.py only imports `wait as rate_wait`, not the retry wrapper. Both functions must exist. Use `call_with_backoff` as the name.

## C5 — /eval/compare endpoint placement
- Doc4: adds to main API but says "if over 5, put in logquery"
- Doc5: adds to main API
**Resolution:** PUT IN LOGQUERY (port 8001) — PS §7 says EXACTLY 5 endpoints. This is non-negotiable.

---

# FINAL MASTER TODO LIST
# Organized by priority — give this to your AI agent in ORDER

## PRIORITY 0: RESOLVE CONTRADICTIONS FIRST (before giving to agent)
- [ ] Pick ONE table name: `prompt_rewrites`
- [ ] Pick ONE endpoint name: POST /eval/run
- [ ] Pick ONE citation scorer: keyword overlap (_content_match)
- [ ] Pick ONE rate limiter retry name: call_with_backoff
- [ ] Confirm /eval/compare goes to logquery, NOT main API

## PRIORITY 1: CRITICAL BLOCKERS (nothing works without these)
- [ ] Create core/rate_limiter.py (all three prompts have correct code)
- [ ] Fix embedding dimension mismatch — check actual model output
- [ ] Add DB persistence for execution_events (migration 002)
- [ ] Add DB persistence for routing_decisions (migration 002)
- [ ] Add DB persistence for tool_call_log (migration 002)
- [ ] Create core/event_store.py
- [ ] Call log_event() in every agent node wrapper
- [ ] Call log_routing_decision() in orchestrator after every route
- [ ] Call log_tool_call() after every tool call
- [ ] Fix /jobs/{id}/trace to query from DB (not Redis)
- [ ] RUN THE EVAL HARNESS — 15 real test cases
- [ ] Verify real scores in DB (not fabricated)

## PRIORITY 2: PS VIOLATIONS (will fail evaluation without these)
- [ ] Critique agent must review decomposition output too (PS §1.4)
- [ ] Web search tool must return relevance_score per result (PS §2.1)
- [ ] Code execution tool must return stdout + stderr + exit_code (PS §2.2)
- [ ] SQL lookup tool: verify NL→SQL via LLM, not hardcoded (PS §2.3)
- [ ] Orchestrator: DIFFERENT logic for TIMEOUT vs NO_RESULTS vs INVALID_INPUT (PS §2.6)
- [ ] Adversarial tc_14: contradiction must RESOLVE internally, never surface to user (PS §4.3)
- [ ] All agent prompts stored in eval_results.prompt_sent_json (PS §4.4)
- [ ] Meta-agent: implement prompt override mechanism at runtime for approved rewrites (PS §5.4)
- [ ] Compute and store delta_score after targeted re-eval completes (PS §5.5)
- [ ] Add GET /rewrites list to LOGQUERY service (PS §5.6 "queryable")
- [ ] Verify SSE handler forwards TOOL_START events (PS §6.3)
- [ ] Verify SSE handler forwards BUDGET_UPDATE events (PS §6.4)
- [ ] Update logquery/app.py to query new execution_events DB table (PS §6.6)
- [ ] Add /eval/compare to LOGQUERY service, NOT main API (PS §7 exactly 5)
- [ ] Add architecture diagram to README (PS §9.1)
- [ ] Add agent decision boundaries description to README (PS §9.2)

## PRIORITY 3: BROKEN IMPLEMENTATIONS (fix prompts cover these — execute)
- [ ] Fix silent END routing — log PolicyViolation on unknown agent (Doc4 Task 3.1)
- [ ] Fix citation scoring — add _content_match() keyword overlap (Doc5 Task 4)
- [ ] Fix budget enforcement — add _run_with_budget_guard wrapper (Doc5 Task 9)
- [ ] Add judge system prompt to gemini-1.5-flash (Doc4 Task 2.2)
- [ ] Remove SchemaValidationError references — replace with error_code="INVALID_INPUT" (Doc5 Task 5)
- [ ] Add tool_accepted/rejected fields to DB and logging (Doc4 Task 4.1)
- [ ] Add TOOL_START Redis publish before each tool call (Doc4 Task 4.2)
- [ ] Verify retry uses MODIFIED input, log each attempt separately (Doc4 Task 4.3)
- [ ] Add all 3 failure modes to all 4 tools (Doc4 Task 4.4)
- [ ] Verify/fix 2-hop retrieval with genuinely different hop2 query (Doc4 Task 9.1)
- [ ] Verify compression shields [CHUNK:id] citations from lossy summarization (Doc4 Task 9.2)
- [ ] Run cross-agent import audit, fix any direct agent→agent calls (Doc5 Task 10.1)
- [ ] Fix reproducibility claim — temperature=0.0 is not seed=42 (Doc5 Task 6)

## PRIORITY 4: DOCUMENTATION (evaluator reads README)
- [ ] Add Quick Start (5-minute setup) to top of README
- [ ] Add architecture diagram to README
- [ ] Add agent decision boundaries section to README
- [ ] Add honest Known Limitations section (include the per-turn budget gap)
- [ ] Add self-improving loop "does and does not do" section
- [ ] Add "what to build next" section
- [ ] Add AI usage disclosure to README (per assessment attestation requirement)

## PRIORITY 5: PROCESS (assessed by evaluator)
- [ ] Make a separate git commit for EACH fix with a meaningful message
- [ ] Final docker compose down -v && docker compose up -d test
- [ ] Run final verification checklist from Uploaded prompt

---

# EVIDENCE SOURCES FOR EACH CLAIM

| Claim | Source |
|-------|--------|
| rate_limiter.py missing | Doc3 "Failure 1", Doc2 Section 10 shows it's from a prompt file |
| Citation scoring broken | Doc3 Section 3 lines 50-51, explicit score_citation_accuracy code |
| Silent END routing | Doc3 Section 1 line 244, agents/orchestrator.py |
| Logs not persisted | Doc3 Section 2 "No execution logs persisted in codebase" |
| Eval never run | Doc3 "Final Recommendation", Doc2 "Hypothetical" labels |
| Missing rate_limiter confirmed | Doc3 "Failure 1: Missing rate_limiter.py" with exact import line |
| 5 endpoints required | PS §7 "Expose exactly five endpoints" |
| Critique reviews every other agent | PS §1 "reviews the output of every other agent" |
| Relevance scores required | PS §2 "structured results with source URLs and relevance scores" |
| NL→SQL by agent | PS §2 "natural language converted to SQL by the agent" |
| Delta score gap | PS §5 "log the delta in performance" — no code in any fix prompt |
| Prompt override gap | PS §5 "re-run eval using the new prompt" — no runtime override in fix prompts |
| Architecture diagram | PS §9 "architecture diagram as a text or image file" |
| Decision boundaries | PS §9 "description of every agent and its decision boundaries" |
