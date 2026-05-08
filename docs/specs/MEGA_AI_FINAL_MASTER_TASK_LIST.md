# MEGA-AI: FINAL MASTER TASK LIST
> **Deadline:** Sunday 2026-05-10, 12:59 PM IST  
> **Total work estimate:** ~9 hours across 48 hours of buffer  
> **Source of truth:** All plan files + entire conversation history + master instruction prompt  

---

## ⚠️ GROUND TRUTH TECH STACK — NEVER DEVIATE

| Component | ✅ Correct Choice | ❌ Common Wrong Answer |
|-----------|------------------|----------------------|
| LLM (gen) | `gemini-2.0-flash` | `gpt-4o` |
| LLM (judge) | `gemini-1.5-flash` | Prometheus-2 (needs local GPU) |
| Embedding | `text-embedding-004`, 768-dim | `text-embedding-3-small`, 1536-dim |
| Token encoding | `o200k_base` (tiktoken) | `cl100k_base` |
| pgvector image | `pgvector/pgvector:0.8.2-pg16` | `ankane/pgvector:v0.6.0` or `v0.8.2` |
| API key var | `GOOGLE_API_KEY` | `OPENAI_API_KEY` |
| LLM client | `google.generativeai` / `genai` | `openai.AsyncOpenAI` |
| Orchestration | LangGraph StateGraph (thin wrapper) | plain while loop |
| Budget lock | `asyncio.Lock` (async-safe) | `threading.RLock` (wrong in async) |
| Compression | Custom LLM summarizer | Telegraph English (stub/fake) |
| SSE | `fastapi.sse.EventSourceResponse` + `try/except ImportError` fallback to `sse_starlette` | raw generators |
| Celery | `visibility_timeout=3600`, `acks_late=True`, `soft_time_limit=600`, queue `heavy_tasks` | default config |

---

## 🔴 PHASE 1 — INSTANT KILLS *(30 min | Submission-breaking if missed)*

> These will cause `docker compose up` to fail OR score 0 on submission.

### P1.1 — docker-compose.yml: Fix pgvector image
```yaml
db:
  image: pgvector/pgvector:0.8.2-pg16   # NOT ankane/pgvector:v0.8.2
```

### P1.2 — docker-compose.yml: Zero hardcoded credentials
```yaml
# WRONG (kills submission):
POSTGRES_PASSWORD: password
DATABASE_URL: postgresql://admin:password@db/megaai

# CORRECT:
POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
DATABASE_URL: ${DATABASE_URL}
```

### P1.3 — .env.example: Swap OpenAI → Google
```bash
GOOGLE_API_KEY=your-gemini-key-here      # NOT sk-...
DATABASE_URL=postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db/${POSTGRES_DB}
REDIS_URL=redis://redis:6379/0
POSTGRES_DB=megaai
POSTGRES_USER=megaai_user
POSTGRES_PASSWORD=changeme_before_deploy
```

### P1.4 — .gitignore: Verify .env is listed
```bash
git ls-files | grep "^\.env$"   # MUST return ZERO results
```

### P1.5 — scripts/seed_kb.py: Remove ALL DDL
The seed script must ONLY INSERT. No `CREATE TABLE`, `CREATE INDEX`, `CREATE EXTENSION`.  
These belong exclusively in Alembic migration `001_initial_schema.py`.

### P1.6 — Makefile seed target: alembic runs BEFORE seed
```makefile
seed:
	alembic upgrade head
	python scripts/seed_kb.py
```

### P1.7 — scripts/seed_kb.py: Exactly 30 documents
```python
print(f"Seeded {len(SEED_DOCUMENTS)} documents")   # must output "Seeded 30 documents"
```
**10 documents to ADD** (covering multi-hop + adversarial topics):
1. Einstein / photoelectric effect (Nobel Prize 1921 — NOT relativity)
2. Canada independence (sovereign state, never annexed by USA)
3. Mars water evidence — chunk A (supporting liquid water exists)
4. Mars water evidence — chunk B (contradicting: only subsurface brines, not liquid)
5. LangGraph StateGraph overview
6. pgvector HNSW indexing
7. GPS relativistic corrections (uses GR + SR, Einstein's relativity)
8. GDPR enforcement penalties and scope
9. ML bias and fairness fundamentals
10. Quantum computing cryptography implications

---

## 🔴 PHASE 2 — SCHEMA & DATABASE *(45 min | Everything depends on this)*

### P2.1 — alembic/versions/001_initial_schema.py: Verify ALL are present
- `CREATE EXTENSION IF NOT EXISTS vector` ← must be FIRST
- `CREATE EXTENSION IF NOT EXISTS "uuid-ossp"`
- `jobs` table with `status CHECK IN ('queued','running','done','failed')`
- `execution_events` table with `seq INT NOT NULL`
- `document_chunks` table with `embedding vector(768)` ← **768 NOT 1536**
- `chunk_relations` table (enables Vector Graph RAG traversal without Neo4j)
- `tool_calls` table with `attempt_number INT CHECK BETWEEN 1 AND 3`
- `eval_runs` table (separate from `eval_results`)
- `eval_results` table with UNIQUE index on `(run_id, test_case_id)`
- `prompt_rewrites` table with `status CHECK IN ('pending','approved','rejected')`
- `prompt_versions` table
- `policy_violations` table
- HNSW index: `WITH (m=16, ef_construction=64)` on `document_chunks.embedding`
- GIN index on `tool_calls.input_json`

### P2.2 — Fix composite_score formula (weighted, not equal)
```sql
-- WRONG (equal weights):
(answer_correctness + citation_accuracy + ...) / 6.0

-- CORRECT (weighted):
GENERATED ALWAYS AS (
  COALESCE(answer_correctness,0)*0.30 +
  COALESCE(citation_accuracy,0)*0.15 +
  COALESCE(contradiction_resolution,0)*0.20 +
  COALESCE(tool_efficiency,0)*0.15 +
  COALESCE(budget_compliance,0)*0.10 +
  COALESCE(critique_agreement,0)*0.10
) STORED
```

### P2.3 — Replace ALL OpenAI client instantiations
Every file importing `openai` must be updated to use `google.generativeai`.  
Search: `grep -r "from openai" . --include="*.py"` → must return ZERO results.

### P2.4 — Fix all embedding calls
```python
# WRONG:
resp = await client.embeddings.create(input=text, model="text-embedding-3-small")

# CORRECT:
import google.generativeai as genai
result = genai.embed_content(model="models/text-embedding-004", content=text)
embedding = result['embedding']   # 768-dim list
```

---

## 🔴 PHASE 3 — CORE MODULES *(60 min | Foundation of all agents)*

### P3.1 — core/context.py: Exact SharedContext field names
```python
job_id: str
query: str
turn: int = 0
status: Literal["pending","running","done","failed","paused"]
subtasks: list[SubTask]
dependency_graph: dict[str, list[str]]
retrieved_chunks: list[Chunk]
retrieval_reasoning: str
claim_scores: list[ClaimScore]
final_answer: str
provenance_map: list[ProvenanceEntry]
budget_registry: dict[str, BudgetEntry]
tool_calls: list[ToolCallRecord]
routing_decisions: list[RoutingDecision]
violations: list[PolicyViolation]
metadata: dict[str, Any]
```

### P3.2 — core/context.py: Required @property decorators
```python
# BudgetEntry
@property
def remaining(self) -> int:
    return max(0, self.max_tokens - self.used_tokens)

@property
def utilisation(self) -> float:
    return self.used_tokens / self.max_tokens

# ToolCallRecord
@property
def input_hash(self) -> str:
    return hashlib.sha256(str(self.input_data).encode()).hexdigest()[:16]

# ProvenanceEntry
source_chunk_id: Optional[str] = None   # None is valid for REASONING sentences
```

### P3.3 — core/budget.py: Lock type + tokenizer + warning threshold
```python
self.lock = asyncio.Lock()           # NOT threading.RLock
self.enc = tiktoken.get_encoding("o200k_base")   # NOT cl100k_base

# Budget warning at 80%:
if entry.used_tokens / entry.max_tokens >= 0.80:
    # emit BUDGET_UPDATE warning
```

### P3.4 — core/budget.py: consume() emits BUDGET_UPDATE SSE every call
```python
async def consume(self, agent_id: str, text: str) -> None:
    async with self.lock:
        # ... count tokens, update entry ...
        if self.redis_pub:
            await self.redis_pub.publish(self.context.job_id,
                event_type="BUDGET_UPDATE",
                agent_id=agent_id,
                used_tokens=entry.used_tokens,
                max_tokens=entry.max_tokens,
                remaining=entry.remaining,
                pct_used=round(entry.used_tokens / entry.max_tokens * 100, 1)
            )
```

### P3.5 — core/tools.py: Full code execution blocklist
```python
BLOCKED = [
    "import os", "import sys", "import subprocess", "open(",
    "importlib", "pathlib", "socket", "urllib", "requests",
    "__builtins__", "__import__", "exec(", "eval("
]
```

### P3.6 — core/tools.py: SQL tool uses read-only PostgreSQL role
```python
# NL-to-SQL tool: use mega_readonly role, never admin credentials
READONLY_DB_URL = os.environ.get("READONLY_DATABASE_URL")
# This role has SELECT-only permissions — no DDL/DML possible
```

---

## 🔴 PHASE 4 — LANGGRAPH WRAPPER *(45 min | Critical architectural signal)*

### P4.1 — agents/orchestrator.py: Must use LangGraph StateGraph
```python
from langgraph.graph import StateGraph, END

def build_graph():
    graph = StateGraph(SharedContext)
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("decomposition", decomposition_node)
    graph.add_node("retrieval", retrieval_node)
    graph.add_node("critique", critique_node)
    graph.add_node("synthesis", synthesis_node)
    graph.add_node("compression", compression_node)
    graph.add_node("meta", meta_node)
    graph.add_conditional_edges("orchestrator", route_decision)
    graph.set_entry_point("orchestrator")
    return graph.compile()
```
Your existing LLM routing logic + deterministic fallback chain lives **inside** `orchestrator_node`.  
LangGraph is the wrapper — not a replacement for your routing logic.

### P4.2 — agents/orchestrator.py: HANDOFF SSE event shape
```python
await redis_pub.publish(context.job_id,
    event_type="HANDOFF",
    next_agent=decision.next_agent,
    reasoning=decision.reasoning,
    confidence=decision.confidence
)
```

### P4.3 — agents/orchestrator.py: Hard limits enforced
```python
MAX_TURNS = 10
MAX_TOOL_CALLS_PER_JOB = 20

if context.turn >= MAX_TURNS:
    context.status = "failed"
    break
if context.count_tool_calls() >= MAX_TOOL_CALLS_PER_JOB:
    context.violations.append(PolicyViolation(violation_type="tool_abuse", ...))
    # force synthesis
```

### P4.4 — agents/decomposition.py: DFS cycle detection + asyncio.Event DAG
```python
# Cycle detection BEFORE execution
def detect_cycles(tasks: list[SubTask]) -> bool:
    visited, rec_stack = set(), set()
    def dfs(task_id):
        visited.add(task_id); rec_stack.add(task_id)
        for dep in task_map[task_id].deps:
            if dep not in visited:
                if dfs(dep): return True
            elif dep in rec_stack: return True
        rec_stack.discard(task_id)
        return False
    return any(dfs(t.id) for t in tasks if t.id not in visited)

# DependencyExecutor: asyncio.Event gates, NOT asyncio.gather
class DependencyExecutor:
    def __init__(self, tasks):
        self.events = {t.id: asyncio.Event() for t in tasks}

    async def run_task(self, task, handler):
        for dep_id in task.deps:
            await self.events[dep_id].wait()   # blocks until dep done
        # ... run task ...
        self.events[task.id].set()
```

---

## 🟠 PHASE 5 — AGENTS *(75 min | Score multipliers)*

### P5.1 — agents/retrieval.py: Gemini embeddings + parse_provenance regex
```python
# Embedding: text-embedding-004, 768-dim
result = genai.embed_content(model="models/text-embedding-004", content=text)
embedding = result['embedding']   # 768-dim

# parse_provenance regex:
pattern = re.compile(r'Using \[CHUNK:([a-f0-9\-]{8,36}|NONE)\] because ([^.]+)\. ([^[]+)')
```

### P5.2 — agents/critique.py: Full context slice + false premise detection
Critique **must** receive ALL prior outputs:
- `subtasks_json` — all SubTask objects with outputs
- `retrieval_answer` — context.retrieval_reasoning
- `draft_answer` — context.final_answer (pre-synthesis)
- `chunks` — top 8 retrieved chunks (text[:300])

System prompt must include:
```
If the query contains a false premise, set confidence=0.0,
flag_reason="false_premise: [explain what is wrong]"
```
`flag_reason` must cite exact chunk: `"contradicts [CHUNK:id] which states: ..."`

### P5.3 — agents/synthesis.py: resolution_log schema
```python
# Each resolved item:
resolution_log.append({
    "span": original_span,
    "action": "RESOLVED" | "REMOVED" | "HEDGED",
    "chunk_cited": chunk_id_or_None
})
```

### P5.4 — agents/compression.py: Target correct field per agent
```python
# After retrieval → compress retrieved_chunks text
# After synthesis → compress final_answer
if triggered_by == "retrieval":
    target = context.retrieval_reasoning
elif triggered_by == "synthesis":
    target = context.final_answer
```

### P5.5 — agents/meta.py: Write prompt_versions on approval + delta_score
```python
# On APPROVED rewrite: write to prompt_versions table
# delta_score: populated after targeted re-eval run completes
```

---

## 🟠 PHASE 6 — API & STREAMING *(60 min)*

### P6.1 — api/routes/query.py: Injection check BEFORE Celery
```python
@router.post("/query")
async def submit_query(request: Request, body: QueryRequest):
    detection = detect_prompt_injection(body.query)
    if detection.is_injection:
        raise HTTPException(400, detail={
            "code": "INJECTION_DETECTED",
            "message": f"Rejected: {detection.detected_pattern}",
            "job_id": None
        })
    # THEN dispatch
    task = run_agent_pipeline.apply_async(args=[body.query], queue="heavy_tasks")
```

### P6.2 — api/routes/query.py: Subscribe BEFORE dispatch (race condition fix)
```python
pubsub = redis_client.pubsub()
await pubsub.subscribe(f"job_events:{job_id}")   # SUBSCRIBE FIRST
task = run_agent_pipeline.apply_async(...)        # THEN dispatch
```

### P6.3 — api/routes/query.py: SSE with disconnect check + ImportError fallback
```python
try:
    from fastapi.sse import EventSourceResponse, ServerSentEvent
except ImportError:
    from sse_starlette.sse import EventSourceResponse, ServerSentEvent

async def event_gen():
    async for msg in pubsub.listen():
        if await request.is_disconnected():
            break
        yield ServerSentEvent(data=json.dumps(msg))

return EventSourceResponse(event_gen(), ping=15)
```

### P6.4 — api/routes/rewrites.py: 409 on double-approval
```python
if rewrite.status != "pending":
    raise HTTPException(409, detail={
        "code": "REWRITE_ALREADY_REVIEWED",
        "message": f"Rewrite already has status: {rewrite.status}"
    })
```

### P6.5 — core/streaming.py: SSE events include id: field for ordered replay
```python
yield ServerSentEvent(
    id=str(seq_counter),
    event=event_type,
    data=json.dumps(payload)
)
```

### P6.6 — api/main.py: /health route
```python
@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}
```

---

## 🟡 PHASE 7 — WORKER & CELERY *(30 min)*

### P7.1 — worker/celery_app.py: Full correct Celery config
```python
app.conf.update(
    broker_transport_options={"visibility_timeout": 3600},
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    result_serializer="json",
)
```

### P7.2 — worker/tasks.py: Task decorator with ALL required params
```python
@app.task(bind=True, acks_late=True, reject_on_worker_lost=True,
          soft_time_limit=600, time_limit=660, queue="heavy_tasks")
def run_agent_pipeline(self, query: str, job_id: str) -> dict:
    ...
```

### P7.3 — docker-compose.yml: Worker command with -Q heavy_tasks
```yaml
command: celery -A worker.celery_app worker --loglevel=info -Q heavy_tasks --concurrency=2
```

### P7.4 — worker/tasks.py: Compression triggers at 80% (not 90%)
```python
for agent_id, entry in budget_mgr.get_registry().items():
    if entry.used_tokens / entry.max_tokens >= 0.80:
        # trigger compression agent
```

### P7.5 — core/cost.py: Gemini pricing tracked per job
```python
INPUT_COST_PER_TOKEN  = 0.00000035   # gemini-2.0-flash
OUTPUT_COST_PER_TOKEN = 0.00000105

total_cost = (input_tokens * INPUT_COST_PER_TOKEN) + (output_tokens * OUTPUT_COST_PER_TOKEN)
# Write to jobs.total_cost_usd at pipeline end
```

---

## 🟡 PHASE 8 — EVAL PIPELINE *(60 min)*

### P8.1 — eval/harness.py: Different generator vs judge model
```python
GENERATOR_MODEL = "gemini-2.0-flash"    # produces answers
JUDGE_MODEL     = "gemini-1.5-flash"    # scores answers (anti-bias)
# Judge prompt must include anti-verbosity Chain-of-Thought instruction
```

### P8.2 — eval/scorers.py: All 6 dimensions return (score, justification)
| Dim | Weight | Key Logic |
|-----|--------|-----------|
| A. Answer Correctness | 30% | Key-fact substring match; injection=1.0 if REJECTED |
| B. Citation Accuracy | 15% | chunk_id in retrieved set + ≥3 word overlap; LLM entailment check |
| C. Contradiction Resolution | 20% | Flagged span removed OR hedge phrase within ±80 chars |
| D. Tool Efficiency | 15% | actual ≤ expected_max → 1.0; else penalty = (excess/max) |
| E. Budget Compliance | 10% | 0 violations=1.0; 1=0.5; 2+=0.0 |
| F. Critique Agreement | 10% | Flagged spans addressed (removed/hedged) by synthesis |

### P8.3 — eval/test_cases.json: Exactly 15 cases
- `tc_01–tc_05`: BASELINE (Paris, boiling point, Python creator, Great Wall, speed of light)
- `tc_06–tc_10`: AMBIGUOUS (GDPR, ML performance, "fix the network error", quantum computing, supply chain)
- `tc_11–tc_15`: ADVERSARIAL (prompt injection, false Einstein Nobel, false US annexation of Canada, Mars water contradiction, tool abuse spiral)

Each case needs:
- `scoring_hints` per dimension
- `expected_min_tool_calls` + `expected_max_tool_calls`

### P8.4 — eval/baseline.py: Zero-agent comparison baseline
```python
# ~20 lines: single Gemini call, no agents, same 15 test cases
# Add to README: table showing Baseline vs MEGA-AI delta score
```

### P8.5 — eval/adversarial.py: Both injection defense layers
- **Layer 1 (Spotlighting):** Wrap query in `USER_DATA_BEGIN ... USER_DATA_END` before Celery
- **Layer 2 (RoMA ParseData):** After every tool call, validate output format via LLM extraction — discard non-conforming data, log as `INJECTION_DETECTED` policy violation
- **Regex patterns (Layer 2.5):** 12 compiled patterns with `re.IGNORECASE`

---

## 🟢 PHASE 9 — README & DOCS *(45 min | Polish)*

### P9.1 — README.md must contain ALL of:
- Quick start: `git clone → cp .env.example .env → make up → make seed → make eval`
- Mermaid architecture diagram (LangGraph nodes → SharedContext → Celery → Redis → SSE)
- Per-agent table: inputs from context, outputs written to context
- **Known Limitations (exact wording):**
  1. "Reference spec assumed OpenAI; this repo uses Gemini-only stack (gemini-2.0-flash + text-embedding-004) but preserves all specified behaviors"
  2. "Token variance ±15% (tiktoken o200k_base calibrated for GPT-4o, not Gemini)"
  3. "Generator: gemini-2.0-flash. Judge: gemini-1.5-flash (different checkpoint — self-enhancement bias mitigated by different generation + explicit anti-verbosity CoT)"
  4. "Telegraph English compression not used — stub replaced with auditable LLM summarizer"
  5. "Prometheus-2 not used — avoids local GPU requirement for take-home assessment"

### P9.2 — README.md DB table: Fix duplicate eval_runs row
The second `eval_runs` row in the table should be `eval_results`.

### P9.3 — ARCHITECTURE.md: Full Mermaid diagram
Must show all 7 agents, SharedContext blackboard, Celery worker, Redis pub/sub, SSE event types, and PostgreSQL.

---

## 🟢 PHASE 10 — TESTS *(60 min)*

### P10.1 — tests/conftest.py: Mock at google.generativeai level
```python
@pytest.fixture
def mock_genai_client():
    with patch("google.generativeai.GenerativeModel") as mock:
        ...

@pytest.fixture
def base_shared_context():
    return SharedContext(query="test query")
```

### P10.2 — tests/test_budget.py
- Budget overflow raises `PolicyViolationError`
- `consume()` emits `BUDGET_UPDATE` SSE event
- `remaining` property returns `max(0, max_tokens - used_tokens)`
- `asyncio.Lock` is used (not `threading.RLock`)

### P10.3 — tests/test_tools.py
- Each tool returns correct error code: `TIMEOUT`, `NO_RESULTS`, `INVALID_INPUT`, `EXEC_ERROR`
- Retry modifies input on `NO_RESULTS` (`broaden_web_query` truncates to first 3 words)
- Code exec blocks `import os` pattern correctly

### P10.4 — tests/test_orchestrator.py
- LangGraph `StateGraph` builds without error (call `build_graph()`)
- Fallback chain activates when LLM routing call fails
- `MAX_TURNS` stops the loop at 10

### P10.5 — tests/test_eval.py
- All 6 scorers return `{"score": float, "justification": str}` shape
- `EvaluationHarness` stores results in DB with `(run_id, test_case_id)` unique constraint

---

## ✅ PHASE 11 — FINAL VERIFICATION *(30 min | Run before git push)*

### Infrastructure checks (all must pass)
```bash
V1:  grep -r "ankane/pgvector" .                      # ZERO results
V2:  grep -r "OPENAI_API_KEY" . --include="*.py"      # ZERO results
V3:  grep -r "password" docker-compose.yml            # ZERO results
V4:  grep -r "sk-" . --include="*.py"                 # ZERO results
V5:  grep -r "cl100k_base" .                          # ZERO results
V6:  grep -r "CREATE TABLE" scripts/seed_kb.py        # ZERO results
V7:  grep -r "asyncio.Lock" core/budget.py            # MUST EXIST
V8:  git ls-files | grep "^\.env$"                   # ZERO results
V9:  grep -r "StateGraph" agents/orchestrator.py      # MUST EXIST
```

### Docker & functional checks
```bash
V10: docker compose up --build --wait                  # exits 0, all 5 services healthy
V11: make seed                                         # prints "Seeded 30 documents"
V12: make test                                         # all tests passing
V13: make eval                                         # 15 rows in eval_results table
```

### API smoke tests
```bash
V14: curl -N -X POST localhost:8000/query \
         -H "Content-Type: application/json" \
         -d '"query":"capital of France"'             # TOKEN events in stream
V15: curl localhost:8000/jobs/<id>/trace              # events ordered by seq ASC
V16: curl localhost:8000/eval/latest                  # category_breakdown + by_dimension present
V17: curl -X POST localhost:8000/eval/run \
         -d '"failed_case_ids":["tc01"]'              # returns run_id + status:queued
```

### Git hygiene
```bash
V18: git log --oneline | wc -l                        # ≥ 26 commits
V19: git log --all --full-history -- .env             # ZERO results
V20: git log --oneline | head -5                      # conventional commit format visible
```

---

## ⏱️ TIME BUDGET

| Phase | Tasks | Est. Time | Priority |
|-------|-------|-----------|----------|
| P1 — Instant Kills | 7 | 30 min | 🔴 CRITICAL |
| P2 — Schema & DB | 4 | 45 min | 🔴 CRITICAL |
| P3 — Core Modules | 6 | 60 min | 🔴 CRITICAL |
| P4 — LangGraph | 4 | 45 min | 🔴 CRITICAL |
| P5 — Agents | 5 | 75 min | 🟠 HIGH |
| P6 — API & Streaming | 6 | 60 min | 🟠 HIGH |
| P7 — Worker & Celery | 5 | 30 min | 🟡 MEDIUM |
| P8 — Eval Pipeline | 5 | 60 min | 🟡 MEDIUM |
| P9 — Docs | 3 | 45 min | 🟢 POLISH |
| P10 — Tests | 5 | 60 min | 🟢 POLISH |
| P11 — Verification | 20 checks | 30 min | ✅ MANDATORY |
| **TOTAL** | **60 tasks** | **~9 hours** | |

**You have ~48 hours. 9 hours of real work. The rest is sleep, buffer, and fixing the inevitable one broken container.**

> **Critical path:** P1 → P2 → P3 → P4 (these four determine if it even runs)  
> **Score multipliers:** P5 → P6 → P7 → P8 (these determine your eval score)  
> **Polish layer:** P9 → P10 → P11 (these determine first-place vs. top-3)

---

## 🏆 20 DIFFERENTIATORS — VERIFY EACH IS IN YOUR CODE

| # | Differentiator | File | Verification |
|---|---------------|------|-------------|
| 1 | `o200k_base` encoding (not `cl100k_base`) | `core/budget.py` | `grep "o200k_base"` |
| 2 | `chunk_relations` table (Vector Graph RAG) | `alembic/001_initial_schema.py` | `grep "chunk_relations"` |
| 3 | GIN index on `tool_calls.input_json` | `alembic/001_initial_schema.py` | `grep "GIN"` |
| 4 | `asyncio.Event` DAG executor (not `gather`) | `agents/decomposition.py` | `grep "asyncio.Event"` |
| 5 | `execute_tool_with_retry` + `modify_input_fn` | `core/tools.py` | `grep "modify_input_fn"` |
| 6 | `BUDGET_UPDATE` SSE after every `consume()` | `core/budget.py` | `grep "BUDGET_UPDATE"` |
| 7 | Critique receives ALL prior outputs | `agents/critique.py` | inspect context slice |
| 8 | Compression at 80% (preemptive) | `worker/tasks.py` | `grep "0.80"` |
| 9 | RoMA ParseData on tool outputs | `core/tools.py` | `grep "roma\|parse_data"` |
| 10 | `soft_time_limit=600` + `heavy_tasks` queue | `worker/tasks.py` | `grep "soft_time_limit"` |
| 11 | `ping=15` on `EventSourceResponse` | `api/routes/query.py` | `grep "ping=15"` |
| 12 | SHA-256 on `execution_events` | `core/context.py` | `grep "sha256"` |
| 13 | DFS cycle detection in `DependencyExecutor` | `agents/decomposition.py` | `grep "detect_cycles"` |
| 14 | Baseline comparison in README | `eval/baseline.py` + README | file exists |
| 15 | `cost_usd` tracked per job | `core/cost.py` + `worker/tasks.py` | `grep "total_cost_usd"` |
| 16 | `PromptRewrite.diff_lines` as typed `DiffLine` | `agents/meta.py` | `grep "DiffLine"` |
| 17 | Generator ≠ judge model (anti-bias) | `eval/harness.py` | `grep "JUDGE_MODEL"` |
| 18 | Exact model string pinned | everywhere | `grep "gemini-2.0-flash"` |
| 19 | Read-only PostgreSQL role for SQL tool | `core/tools.py` | `grep "readonly"` |
| 20 | `COMPRESSION_TRIGGERED` as distinct SSE event | `core/streaming.py` | `grep "COMPRESSION_TRIGGERED"` |
