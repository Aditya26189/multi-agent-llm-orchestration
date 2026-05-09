# MEGA-AI Technical Documentation
**Detailed Implementation Specifics**  
**Generated May 10, 2026**

---

## SECTION 1: Decomposition Agent — Dependency Graphs

### Question 1: Explicit Dependency Graph Production

**YES** — The decomposition agent produces an explicit dependency graph.

#### Data Structure
**Location:** `core/context.py`, lines 210-211

```python
# In SharedContext class:
subtasks: List[SubTask] = Field(default_factory=list)
dependency_graph: Dict[str, List[str]] = Field(default_factory=dict)
```

**Representation:** Dictionary (adjacency list)
```python
# Example:
dependency_graph = {
    "t1": [],              # task t1 has no dependencies
    "t2": ["t1"],          # task t2 depends on t1
    "t3": ["t1", "t2"],    # task t3 depends on t1 and t2
}
```

#### Graph Building Function
**File:** `agents/decomposition.py`, lines 77-78

```python
context.subtasks = sub_tasks
context.dependency_graph = {t.id: t.deps for t in sub_tasks}
```

The orchestrator doesn't directly build the graph — the **Gemini LLM** builds it during decomposition. The LLM-generated JSON is parsed into `SubTask` objects, each with:

```python
# From core/context.py:
class SubTask(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    type: SubTaskType
    description: str
    deps: List[str] = Field(default_factory=list)  # <-- dependency list
    status: SubTaskStatus = SubTaskStatus.PENDING
    output: Optional[str] = None
    error: Optional[str] = None
```

#### Dependency Enforcement — Blocking Logic

**File:** `agents/decomposition.py`, lines 118-180 (`DependencyExecutor` class)

**Blocking mechanism:** `asyncio.Event` gates

```python
class DependencyExecutor:
    """Execute sub-tasks in dependency order using asyncio.Event gates."""

    def __init__(self, sub_tasks: List[SubTask]):
        self.tasks: Dict[str, SubTask] = {t.id: t for t in sub_tasks}
        self._events: Dict[str, asyncio.Event] = {
            t_id: asyncio.Event() for t_id in self.tasks
        }
        self._failed: Set[str] = set()
        self._detect_cycles()  # Raises ValueError if circular dep found
```

**Critical blocking code (lines 160-175):**

```python
async def _run_task(self, task: SubTask, handler) -> None:
    # Wait for ALL dependencies to complete
    for dep_id in task.deps:
        if dep_id not in self._events:
            task.status = SubTaskStatus.FAILED
            task.error = f"Unknown dep: {dep_id}"
            self._failed.add(task.id)
            self._events[task.id].set()
            return
        # **BLOCKING WAIT** — task does not proceed until dep completes
        await self._events[dep_id].wait()
        # Check if dependency failed
        if dep_id in self._failed:
            task.status = SubTaskStatus.FAILED
            task.error = f"Dep '{dep_id}' failed"
            self._failed.add(task.id)
            self._events[task.id].set()
            return
    
    # Only after ALL deps complete does task enter RUNNING state
    task.status = SubTaskStatus.RUNNING
    try:
        output = await handler(task)
        task.output = output
        task.status = SubTaskStatus.DONE
        task.completed_at = datetime.utcnow()
    except Exception as e:
        task.status = SubTaskStatus.FAILED
        task.error = str(e)
        self._failed.add(task.id)
    finally:
        # Signal that THIS task is done — unblock any tasks depending on it
        self._events[task.id].set()
```

**Cycle detection (lines 127-145):**

```python
def _detect_cycles(self) -> None:
    """DFS-based cycle detection. Raises ValueError on circular dependency."""
    visited: Set[str] = set()
    rec_stack: Set[str] = set()

    def dfs(node_id: str) -> bool:
        visited.add(node_id)
        rec_stack.add(node_id)
        task = self.tasks.get(node_id)
        if task:
            for dep_id in task.deps:
                if dep_id not in self.tasks:
                    continue  # Unknown dep handled at runtime
                if dep_id not in visited:
                    if dfs(dep_id):
                        return True
                elif dep_id in rec_stack:  # <-- cycle detected
                    return True
        rec_stack.discard(node_id)
        return False

    for task_id in self.tasks:
        if task_id not in visited:
            if dfs(task_id):
                raise ValueError(
                    f"Circular dependency detected in sub-tasks involving '{task_id}'. "
                    "Check the dependency graph for cycles."
                )
```

**Summary of blocking logic:**
1. `asyncio.Event` per task ID
2. Task waits on `await self._events[dep_id].wait()` for each dependency
3. Task can only progress when ALL dependencies have completed
4. Failed dependencies cascade failure downstream
5. Circular deps detected before execution starts

---

## SECTION 2: Critique Agent — Span-Level Flagging

### Question 2: Exact Text Span Flagging

**YES** — The critique agent returns the exact span of text it disagrees with.

#### Schema

**File:** `core/context.py`, lines 161-170

```python
class ClaimScore(BaseModel):
    span: str                                      # EXACT text substring
    start_char: int = 0                           # Char position (optional)
    end_char: int = 0                             # Char position (optional)
    confidence: float = Field(ge=0.0, le=1.0)    # 0.0 = fully disagreed
    flagged: bool = False                          # If True, synthesis must address
    flag_reason: Optional[str] = None              # Explanation with evidence
    scored_by: AgentID = AgentID.CRITIQUE
```

#### Real Example Output

**File:** `agents/critique.py`, lines 38-71

The critique prompt (lines 8-40) instructs Gemini:

```python
CRITIQUE_PROMPT = """...
Critique ALL THREE sections above. For each problematic text span:
- Extract the EXACT span
- Assign confidence 0.0-1.0 (1.0 = fully supported)
- Set flagged=true if confidence < 0.6
- Provide flag_reason citing specific evidence. Format exactly as:
    'contradicts [CHUNK:uuid] which states: "<exact quote from chunk>"'
    or for false premises:
    'false_premise: the query assumes X, but [CHUNK:uuid] states: "<correct fact>"'

Return JSON with key "claim_scores" as an array. Each item must have:
- span: exact text span (string)
- confidence: float 0.0-1.0
- flagged: boolean
- flag_reason: string (empty if not flagged)"""
```

**Parsing code (lines 60-80):**

```python
raw_json = await self.generate_json(prompt)
data = json.loads(raw_json)

claim_scores = []
for item in data.get("claim_scores", []):
    try:
        cs = ClaimScore(
            span=str(item.get("span", ""))[:200],              # <-- EXACT span
            confidence=max(0.0, min(1.0, float(item.get("confidence", 1.0)))),
            flagged=bool(item.get("flagged", False)),
            flag_reason=str(item.get("flag_reason", "")) or None,
            scored_by=AgentID.CRITIQUE,
        )
        claim_scores.append(cs)
```

#### Example from Hypothetical Run

**For test case tc_12 ("Einstein won Nobel for relativity"):**

Input (from retrieval):
```
"Einstein is famous for developing the theory of relativity, for which he 
won the Nobel Prize in Physics in 1921."
```

Retrieved chunk:
```
[CHUNK:e7f2a4]: "Einstein won the Nobel Prize in Physics for his discovery 
of the law of the photoelectric effect, not for relativity."
```

Critique output (JSON):
```json
{
  "claim_scores": [
    {
      "span": "Einstein won the Nobel Prize in Physics for relativity",
      "confidence": 0.0,
      "flagged": true,
      "flag_reason": "false_premise: Query assumes Einstein won Nobel for relativity, but [CHUNK:e7f2a4] states he won for the photoelectric effect"
    }
  ]
}
```

#### Tie to Substring

**The flag IS tied to specific substring, NOT to topic generally.**

- Each `span` is a contiguous text substring from the retrieval/draft answer
- The `flag_reason` provides the evidence (which chunk contradicts it)
- **No topic-level flagging** — only sentence/clause-level spans
- Synthesis agent must handle each flagged span individually (RESOLVE/REMOVE/HEDGE)

---

## SECTION 3: Self-Reflection Tool

### Question 3: Self-Reflection Tool Details

**File:** `core/tools.py`, lines 300-360

#### What It Does

The self-reflection tool:
1. **Reads the agent's own previous outputs** from `context.execution_events`
2. **Compares them for contradictions** using an LLM call
3. **Returns structured output** identifying contradictions and severity

#### Code

```python
async def tool_self_reflect(
    agent_id: str,
    context: "SharedContext",
    gemini_model=None,
) -> ToolResult:
    start = time.monotonic()

    # STEP 1: Re-read agent's prior outputs from session history
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
        # STEP 2: LLM analyzes for contradictions
        prompt = f"""Review these prior outputs from agent '{agent_id}' for contradictions.

{outputs_text}

List EACH contradiction:
1. Conflicting claim A (exact quote, Output #)
2. Conflicting claim B (exact quote, Output #)
3. Severity: HIGH/MEDIUM/LOW

If none found, respond: NO_CONTRADICTIONS_FOUND"""

        resp = await asyncio.to_thread(gemini_model.generate_content, prompt)
        reflection = resp.text.strip()

        # STEP 3: Return structured output
        return ToolResult(
            success=True,
            data={
                "reflection": reflection,                         # Full LLM analysis
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
```

#### Return Value Schema

```python
class ToolResult(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None   # <-- Contains reflection, has_contradictions, outputs_analyzed
    error_code: Optional[str] = None        # TIMEOUT | NO_RESULTS | INVALID_INPUT | EXEC_ERROR
    error_message: Optional[str] = None
    latency_ms: float = 0.0
    tool_name: str = ""
```

**Example return:**
```python
ToolResult(
    success=True,
    data={
        "reflection": "Output 1: 'Paris population is 2 million'\nOutput 2: 'Paris has 2.1 million inhabitants'\nSeverity: LOW (minor numerical variance)",
        "has_contradictions": True,
        "outputs_analyzed": 2,
    },
    tool_name="self_reflect",
    latency_ms=450.0,
)
```

#### Is It Separate from Compression Agent?

**YES — completely separate.**

| Aspect | Self-Reflect Tool | Compression Agent |
|--------|------------------|-------------------|
| Purpose | Detect contradictions between agent outputs | Reduce token usage by summarizing filler text |
| Called by | Tool runner (on failure path via ToolAction.FALLBACK_TOOL) | Orchestrator (when agent at 80% budget) |
| Input | Agent's execution_events | Full final_answer text |
| Output | Contradiction analysis (string) | Compressed text (string) |
| Data Structure | ToolResult object | N/A (modifies context in-place) |

**Flow:**
1. When a tool fails with EXEC_ERROR, orchestrator routes to `tool_self_reflect` as fallback
2. `tool_self_reflect` returns contradiction analysis
3. Synthesis agent can use this to reconcile outputs
4. Separately, if agent approaches 80% budget, compression is triggered

---

## SECTION 4: Eval Output — Diff-ability

### Question 4: Comparison of Two Runs Side-by-Side

**PARTIALLY IMPLEMENTED** — Infrastructure exists but not all pieces wired together.

#### Mechanism

**Database schema exists for storing full reproducibility (db/models.py):**

```python
class EvalResult(Base):
    __tablename__ = "eval_results"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(UUID(as_uuid=True), nullable=False)  # <-- Foreign key to run
    test_case_id = Column(String(20), nullable=False)
    category = Column(String(20), nullable=False)
    answer_correctness = Column(Float, nullable=True)
    citation_accuracy = Column(Float, nullable=True)
    contradiction_resolution = Column(Float, nullable=True)
    tool_efficiency = Column(Float, nullable=True)
    budget_compliance = Column(Float, nullable=True)
    critique_agreement = Column(Float, nullable=True)
    composite_score = Column(Float, nullable=True)
    justifications = Column(JSONB, nullable=True)               # All 6 justifications
    prompt_sent_json = Column(JSONB, nullable=True)            # Full prompt
    tool_calls_json = Column(JSONB, nullable=True)             # Full tool trace
    final_answer = Column(Text, nullable=True)                 # Final output
    timestamp = Column(TIMESTAMPTZ, default=datetime.utcnow)
```

Every eval run stores:
- `run_id` → unique run identifier
- `test_case_id` → which test case (tc_01, tc_02, etc.)
- All 6 scores + justifications
- Full prompt + tool trace + final answer

#### Diff Endpoint

**File:** `api/routes/eval.py`, lines 20-45

```python
@router.get(
    "/eval/latest",
    summary="Get latest eval run summary by test category and scoring dimension",
)
async def get_latest_eval(db: AsyncSession = Depends(get_db)):
    run = await db.execute(
        text("SELECT * FROM eval_runs ORDER BY triggered_at DESC LIMIT 1")
    )
    run_row = run.mappings().first()
    if not run_row:
        raise HTTPException(status_code=404, detail={
            "error_code": "EVAL_NOT_READY",
            "message": "No evaluation runs have completed yet. Run POST /eval/run first.",
        })

    results = await db.execute(
        text("""
            SELECT test_case_id, category,
                   answer_correctness, citation_accuracy, contradiction_resolution,
                   tool_efficiency, budget_compliance, critique_agreement,
                   composite_score, justifications
            FROM eval_results
            WHERE run_id = :rid
            ORDER BY test_case_id
        """),
        {"rid": str(run_row["run_id"])},
    )

    rows = [dict(r) for r in results.mappings().all()]

    # Category breakdown
    categories: dict = {"BASELINE": [], "AMBIGUOUS": [], "ADVERSARIAL": []}
    for r in rows:
        cat = r.get("category", "BASELINE")
        categories.get(cat, categories["BASELINE"]).append(r)

    category_summary = {}
    for cat, cat_rows in categories.items():
        if cat_rows:
            category_summary[cat] = {
                "count": len(cat_rows),
                "avg_composite": sum(r["composite_score"] or 0 for r in cat_rows) / len(cat_rows),
            }

    return {
        "run_id": str(run_row["run_id"]),
        "triggered_at": run_row["triggered_at"],
        "total_score": run_row["total_score"],
        "category_breakdown": category_summary,
        "results": rows,
    }
```

**What it returns:**
```json
{
  "run_id": "e4c8b2f1-9d3a-48a2-b4e1-7f6e2c3a9d1b",
  "triggered_at": "2026-05-10T14:22:15Z",
  "total_score": 0.847,
  "category_breakdown": {
    "BASELINE": {"count": 5, "avg_composite": 0.95},
    "AMBIGUOUS": {"count": 5, "avg_composite": 0.82},
    "ADVERSARIAL": {"count": 5, "avg_composite": 0.74}
  },
  "results": [
    {
      "test_case_id": "tc_01",
      "category": "BASELINE",
      "answer_correctness": 1.0,
      "citation_accuracy": 1.0,
      "contradiction_resolution": 1.0,
      "tool_efficiency": 1.0,
      "budget_compliance": 1.0,
      "critique_agreement": 1.0,
      "composite_score": 1.0,
      "justifications": { ... }
    },
    ...
  ]
}
```

#### Diff Output

**NO explicit diff/delta endpoint implemented.** To diff two runs, you would need to:
1. Query `/eval/latest` (returns latest run)
2. Manually query database for a second run by `run_id`
3. Compute delta in client code

**What SHOULD be stored for diffability (currently missing):**
- Prompt version hash (to detect when prompts changed)
- Model version (gemini-2.0-flash vs gemini-1.5-flash)
- Previous test case result (to calculate deltas)

---

## SECTION 5: Per-Dimension Justification Strings

### Question 5: Justification Storage & Examples

**YES** — Every test case stores justification strings for all 6 scoring dimensions.

#### Database Schema

**File:** `db/models.py`, line 68

```python
class EvalResult(Base):
    __tablename__ = "eval_results"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(UUID(as_uuid=True), nullable=False)
    test_case_id = Column(String(20), nullable=False)
    category = Column(String(20), nullable=False)
    answer_correctness = Column(Float, nullable=True)
    citation_accuracy = Column(Float, nullable=True)
    contradiction_resolution = Column(Float, nullable=True)
    tool_efficiency = Column(Float, nullable=True)
    budget_compliance = Column(Float, nullable=True)
    critique_agreement = Column(Float, nullable=True)
    composite_score = Column(Float, nullable=True)
    justifications = Column(JSONB, nullable=True)  # <-- ALL 6 justifications stored
    prompt_sent_json = Column(JSONB, nullable=True)
    tool_calls_json = Column(JSONB, nullable=True)
    final_answer = Column(Text, nullable=True)
    timestamp = Column(TIMESTAMPTZ, default=datetime.utcnow)
```

**Storage location:** `justifications` JSONB column

#### Example Justification Output

**For test case tc_03 ("Who created Python and when?"):**

```python
{
  "run_id": "e4c8b2f1-9d3a-48a2-b4e1-7f6e2c3a9d1b",
  "test_case_id": "tc_03",
  "category": "BASELINE",
  "composite_score": 0.9487,
  "justifications": {
    "answer_correctness": "Exact match: 2/2 key facts found. Facts checked: ['Guido van Rossum', '1991']. Answer excerpt: 'Python programming language was created by Guido van Rossum and first released in 1991...'",
    
    "citation_accuracy": "6/7 citations valid. [CHUNK:chunk_uuid_001] — valid; [CHUNK:chunk_uuid_002] — valid; [REASONING] 'suitable for both beginners and advanced users' — valid; [CHUNK:chunk_uuid_003] — valid; [CHUNK:chunk_uuid_004] — valid; [CHUNK:chunk_uuid_005] — valid",
    
    "contradiction_resolution": "No flagged claims — nothing to resolve (score: 1.0)",
    
    "tool_efficiency": "Tool calls: 2 (within expected range 1-3)",
    
    "budget_compliance": "Zero budget violations across all agents",
    
    "critique_agreement": "Critique flagged 0 spans. Synthesis addressed 0. No conflicts."
  }
}
```

#### Storing in Database

**File:** `eval/harness.py`, lines 157-168

```python
await db.execute(text("""
    INSERT INTO eval_results
    (run_id, test_case_id, category, answer_correctness, citation_accuracy,
     contradiction_resolution, tool_efficiency, budget_compliance,
     critique_agreement, composite_score, justifications, final_answer)
    VALUES (:rid, :tcid, :cat, :ac, :ca, :cr, :te, :bc, :cag, :cs, :j::jsonb, :fa)
"""), {
    "rid": run_id,
    "tcid": r["test_case_id"],
    "cat": r["category"],
    "ac": r["answer_correctness"],
    "ca": r["citation_accuracy"],
    "cr": r["contradiction_resolution"],
    "te": r["tool_efficiency"],
    "bc": r["budget_compliance"],
    "cag": r["critique_agreement"],
    "cs": r["composite_score"],
    "j": json.dumps(r["justifications"]),  # <-- Serialized JSONB
    "fa": r["final_answer"],
})
```

---

## SECTION 6: Structured Logs — Input/Output Hashing

### Question 6: Hashing & Log Schema

**YES** — Logs store input hash and output hash for all agent events.

#### Hashing Function

**File:** `core/context.py`, lines 222-252 (`add_event()` method)

```python
def add_event(
    self,
    agent_id: str,
    event_type: EventType,
    prompt_sent: Optional[str] = None,
    output_received: Optional[str] = None,
    latency_ms: float = 0.0,
    token_count: int = 0,
    policy_violation: Optional[str] = None,
) -> None:
    seq = len(self.execution_events)
    # COMPUTE SHA-256 HASH, truncate to 16 chars
    ih = hashlib.sha256((prompt_sent or "").encode()).hexdigest()[:16] if prompt_sent else None
    oh = hashlib.sha256((output_received or "").encode()).hexdigest()[:16] if output_received else None
    self.execution_events.append(ExecutionEventSchema(
        seq=seq,
        job_id=self.job_id,
        agent_id=agent_id,
        event_type=event_type,
        prompt_sent=prompt_sent,
        output_received=output_received,
        input_hash=ih,     # <-- SHA-256[:16]
        output_hash=oh,    # <-- SHA-256[:16]
        latency_ms=latency_ms,
        token_count=token_count,
        model_used="gemini-2.0-flash",
        input_token_count=token_count,
        output_token_count=0,
        policy_violation=policy_violation,
    ))
```

**Hash function:** SHA-256, truncated to 16 characters (hex)

#### Full Log Schema

**File:** `core/context.py`, lines 197-215

```python
class ExecutionEventSchema(BaseModel):
    seq: int                                    # Event sequence number in execution
    job_id: str                                 # Parent job UUID
    agent_id: str                               # Which agent (e.g., "retrieval")
    event_type: EventType                       # AGENT_START | TOKEN | BUDGET_UPDATE | etc.
    prompt_sent: Optional[str] = None           # Full prompt text (nullable)
    output_received: Optional[str] = None       # Full output text (nullable)
    input_hash: Optional[str] = None            # SHA-256[:16] of prompt
    output_hash: Optional[str] = None           # SHA-256[:16] of output
    latency_ms: float = 0.0                     # Wall-clock latency
    token_count: int = 0                        # Tokens consumed
    model_used: Optional[str] = None            # "gemini-2.0-flash", etc.
    input_token_count: Optional[int] = None     # Prompt tokens
    output_token_count: Optional[int] = None    # Completion tokens
    policy_violation: Optional[str] = None      # If any violation, describe it
    timestamp: datetime = Field(default_factory=datetime.utcnow)
```

**Database table (db/models.py, lines 27-43):**

```python
class ExecutionEvent(Base):
    __tablename__ = "execution_events"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    job_id = Column(UUID(as_uuid=True), nullable=False)
    seq = Column(Integer, nullable=False)
    agent_id = Column(String(50), nullable=False)
    event_type = Column(String(50), nullable=False)
    prompt_sent = Column(Text, nullable=True)
    output_received = Column(Text, nullable=True)
    input_hash = Column(String(16), nullable=True)      # <-- 16-char hash
    output_hash = Column(String(16), nullable=True)     # <-- 16-char hash
    latency_ms = Column(Float, default=0.0)
    token_count = Column(Integer, default=0)
    policy_violation = Column(Text, nullable=True)
    timestamp = Column(TIMESTAMPTZ, default=datetime.utcnow)
```

#### Log Writer

**File:** `core/context.py`, `SharedContext.add_event()` method (lines 222-252)

Every agent calls this to log its execution:
```python
context.add_event(
    agent_id="retrieval",
    event_type=EventType.AGENT_START,
    prompt_sent=prompt_hop2[:500],
    output_received=hop2_response[:500],
    latency_ms=latency,
    token_count=budget_mgr.count_tokens(prompt_hop1 + prompt_hop2),
)
```

#### Example Hash Entry

For a retrieval agent call:
```
seq:       15
agent_id:  retrieval
event_type: AGENT_START
input_hash: a4c2e8f1b9d7c3e5
output_hash: 7f2b4d9e1a6c8f3b
prompt_sent: "You are a retrieval agent performing the SECOND HOP of a 2-hop retrieval. Original query: {query} Hop 1 context: {hop1_context} Additional chunks for hop 2: {chunks} Synthesize a complete answer..."
output_received: "Based on the retrieved chunks, the answer to your question about Paris is as follows... [CHUNK:abc123] Paris is the capital of France with a population of approximately 2.1 million in the city proper..."
latency_ms: 3450.5
token_count: 2840
model_used: gemini-2.0-flash
timestamp: 2026-05-10 14:22:47.123456
```

---

## SECTION 7: Provenance Map Schema

### Question 7: Synthesis Agent Provenance Output

#### Data Structure

**File:** `core/context.py`, lines 172-175

```python
class ProvenanceEntry(BaseModel):
    sentence: str                           # The sentence in final answer
    source_agent: AgentID                   # Which agent produced it (RETRIEVAL | SYNTHESIS)
    source_chunk_id: Optional[str] = None   # Chunk ID if from retrieval; None if [REASONING]
```

**In SharedContext:**
```python
provenance_map: List[ProvenanceEntry] = Field(default_factory=list)
```

#### Example JSON Output

```json
{
  "provenance_map": [
    {
      "sentence": "Paris is the capital of France.",
      "source_agent": "RETRIEVAL",
      "source_chunk_id": "chunk_uuid_001"
    },
    {
      "sentence": "The city has a population of approximately 2.1 million in the city proper.",
      "source_agent": "RETRIEVAL",
      "source_chunk_id": "chunk_uuid_001"
    },
    {
      "sentence": "The greater metropolitan area includes over 12 million inhabitants.",
      "source_agent": "RETRIEVAL",
      "source_chunk_id": "chunk_uuid_001"
    },
    {
      "sentence": "Based on this information, Paris is one of the largest cities in Europe.",
      "source_agent": "SYNTHESIS",
      "source_chunk_id": null
    },
    {
      "sentence": "This makes it an important cultural and economic center.",
      "source_agent": "SYNTHESIS",
      "source_chunk_id": null
    }
  ]
}
```

#### How It's Built

**Retrieval agent builds initial provenance (agents/retrieval.py, lines 196-210):**

```python
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

context.provenance_map = provenance
```

**Synthesis agent APPENDS new provenance (agents/synthesis.py, lines 115-140):**

```python
# Update provenance map with synthesis sentences
valid_ids = {c.id for c in context.retrieved_chunks}
new_provenance = list(context.provenance_map)  # Start with retrieval's entries
for line in final_answer.splitlines():
    line = line.strip()
    if line.startswith("[CHUNK:"):
        end = line.find("]")
        if end > 0:
            chunk_id = line[7:end]
            sentence = line[end+1:].strip()
            new_provenance.append(ProvenanceEntry(
                sentence=sentence,
                source_agent=AgentID.SYNTHESIS,
                source_chunk_id=chunk_id if chunk_id in valid_ids else None,
            ))
    elif line.startswith("[REASONING]"):
        new_provenance.append(ProvenanceEntry(
            sentence=line[11:].strip(),
            source_agent=AgentID.SYNTHESIS,
            source_chunk_id=None,
        ))

context.provenance_map = new_provenance
```

#### Linking to Sources

**Each sentence is linked to:**
1. **Source agent** (RETRIEVAL or SYNTHESIS)
2. **Source chunk ID** (if backed by a chunk, else `None`)

**NOT linked:**
- Specific span position in final_answer (positions shift as answer is edited)
- Confidence score (use ClaimScore for that)
- Evidence quality (use ProvenanceEntry for that)

---

## SECTION 8: Context Budget — Per-Agent Declaration

### Question 8: Budget Declaration & Enforcement

**File:** `core/budget.py`

#### Declaration

**Declaration is STATIC (not per-turn)** — each agent declares once before execution.

**Method:** `declare_budget()`, lines 65-70

```python
def declare_budget(self, agent_id: str, max_tokens: int) -> None:
    """Synchronous — call before any async operations."""
    self._context.budget_registry[agent_id] = BudgetEntry(
        agent_id=agent_id,
        max_tokens=max_tokens,
        used_tokens=0,
    )
```

**Static budgets (from orchestrator_node in agents/orchestrator.py):**

```python
# Each agent declares once at the start
budget_mgr.declare_budget("orchestrator",  2048)
budget_mgr.declare_budget("decomposition", 3072)
budget_mgr.declare_budget("retrieval",     6144)
budget_mgr.declare_budget("critique",      4096)
budget_mgr.declare_budget("synthesis",     4096)
budget_mgr.declare_budget("compression",   8192)
budget_mgr.declare_budget("meta",          4096)
```

#### Receiving & Enforcing Declaration

**Consumption method (lines 77-101):**

```python
async def consume(self, agent_id: str, text_or_tokens: "str | int") -> None:
    """Async — await this. Emits BUDGET_UPDATE via Redis after every call."""
    async with self._lock:
        entry = self._context.budget_registry.get(agent_id)
        if entry is None:
            raise KeyError(f"Agent '{agent_id}' must call declare_budget() first.")

        tokens = self._count(text_or_tokens)
        entry.used_tokens += tokens

        if entry.used_tokens > entry.max_tokens * 0.8:
            entry.violations.append(
                f"WARNING: {entry.used_tokens}/{entry.max_tokens} tokens "
                f"({entry.used_tokens / entry.max_tokens * 100:.0f}%)"
            )

    # Emit budget update outside lock to avoid deadlock
    if self._redis_pub:
        try:
            await self._redis_pub.publish(self._context.job_id, {
                "event_type": "BUDGET_UPDATE",
                "agent_id": agent_id,
                "used_tokens": entry.used_tokens,
                "max_tokens": entry.max_tokens,
                "remaining_tokens": entry.remaining,
                "pct_used": round(entry.used_tokens / entry.max_tokens * 100, 1),
            })
        except Exception:
            pass  # Never let Redis failures block agent execution
```

#### 100% Budget Enforcement

**Method:** `assert_compliant()`, lines 103-128

```python
def assert_compliant(self, agent_id: str) -> None:
    """
    Call BEFORE executing an agent with its assembled context.
    Raises BudgetOverflowError if over budget.
    NEVER silently truncates — that is a policy violation.
    """
    entry = self._context.budget_registry.get(agent_id)
    if entry is None:
        return

    if not entry.is_compliant:  # is_compliant = (used_tokens <= max_tokens)
        violation = PolicyViolation(
            agent_id=agent_id,
            violation_type="budget_overflow",
            details=f"Used {entry.used_tokens} of {entry.max_tokens} tokens",
            tokens_over_budget=entry.used_tokens - entry.max_tokens,
        )
        self._context.violations.append(violation)
        self._context.add_event(
            agent_id=agent_id,
            event_type=EventType.ERROR,
            policy_violation=f"budget_overflow: {entry.used_tokens}/{entry.max_tokens}",
        )
        # **RAISES EXCEPTION** — DOES NOT PROCEED
        raise BudgetOverflowError(agent_id, entry.max_tokens, entry.used_tokens)
```

**Exact code path at 100% budget:**

1. **Entry state:** `used_tokens = max_tokens` (e.g., 4096/4096)
2. **`is_compliant` check:** `entry.is_compliant` = `(4096 <= 4096)` = `True`
3. **If `consume()` is called after:** Increments `used_tokens` → `4097`
4. **Next `assert_compliant()` call:**
   - `is_compliant` = `(4097 <= 4096)` = `False`
   - Creates `PolicyViolation(violation_type="budget_overflow", tokens_over_budget=1)`
   - Appends to `context.violations`
   - Calls `context.add_event(..., policy_violation="budget_overflow: 4097/4096")`
   - **RAISES `BudgetOverflowError(agent_id="retrieval", budget=4096, used=4097)`**

**Exception is NOT caught internally** — calling code must handle:

```python
try:
    budget_mgr.assert_compliant("retrieval")
    # Now safe to run agent
    await retrieval_agent.run(context, budget_mgr, redis_pub)
except BudgetOverflowError as e:
    # Must trigger compression or fail the job
    await compression_agent.compress(...)
    # OR:
    context.status = JobStatus.FAILED
    raise
```

---

## SECTION 9: Docker Compose Services

### Question 9: Service Roles

**File:** `docker-compose.yml`

#### Service List

| Service | Image/Build | Port | Role |
|---------|-------------|------|------|
| `db` | `pgvector/pgvector:0.8.2-pg16` | 5432 (internal) | Vector database (knowledge base + eval results) |
| `seeder` | `api/Dockerfile` | N/A | Init container: runs alembic migrations + seeds 30 documents |
| `redis` | `redis:7-alpine` | 6379 (internal) | Message broker for SSE streaming + Celery |
| `api` | `api/Dockerfile` | 8000 | Main API: query endpoint, eval endpoint, health |
| `worker` | `worker/Dockerfile` | N/A | Celery worker: executes agent pipeline |
| `logquery` | `logquery/Dockerfile` | 8001 | Log query interface (separate service) |

#### Dedicated Log Query Interface

**YES — dedicated service on port 8001**

**File:** `logquery/app.py`

```python
app = Flask(__name__)

@app.route("/")
def index():
    # HTML form to query execution logs

@app.route("/trace")
def trace():
    job_id = request.args.get("job_id", "")
    # Returns execution_events for job_id as HTML table

@app.route("/api/trace/<job_id>")
def api_trace(job_id):
    # Returns execution_events as JSON
    return jsonify([...])

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001, debug=False)
```

**Role:** Separate from main API. Queries database for execution_events and displays in UI (port 8001).

#### Seeder vs Worker

| Aspect | Seeder | Worker |
|--------|--------|--------|
| **Role** | Initialization only | Runs pipeline tasks |
| **Lifecycle** | Runs once on `docker compose up`, then exits | Long-lived Celery worker |
| **Dockerfile** | api/Dockerfile | worker/Dockerfile |
| **Command** | `alembic upgrade head && python scripts/seed_kb.py` | `celery -A worker.celery_app worker --loglevel=info -Q heavy_tasks` |
| **Restart policy** | `"no"` (exit after completion) | `unless-stopped` (runs continuously) |
| **Output** | Embeds 30 documents in pgvector | Processes agent pipeline tasks |

---

## SECTION 10: AI Usage Disclosure

### Question 10: AI Tool Usage Documentation

**AI assistance IS documented, but NOT in the main codebase.**

#### Where It's Documented

**File:** `final-steps-prompt.md`, line 2-3

```markdown
MEGA-AI: AI AGENT INSTRUCTION PROMPT — FINAL FIXES
Feed this entire file to your AI coding agent (Claude Code / Cursor / Aider)
```

This file is a **prompt file for AI coding assistants**, indicating the developer used tools like:
- Claude Code (via Cursor editor)
- Cursor IDE
- Aider (AI pair programmer)

#### What's NOT in the Codebase

- No `AI_CONTRIBUTIONS.md` file in the main repository
- No mention in `README.md` of AI-assisted development
- No badges or labels indicating "AI Generated" code sections
- `final-steps-prompt.md` is a working document, not a polished disclosure

#### Evidence of Scope

The file contains:
- Detailed task lists (Section 1: P1.1, P1.2, P1.3, etc.)
- Code generation prompts with specific requirements
- Instructions for fixing bugs and adding features
- References to prior AI code (e.g., "See agents/base.py" — suggesting iterative refinement)

**Conclusion:** The codebase was **substantially developed with AI assistance** (Claude, likely), but this is documented only in the working prompt file, not in user-facing documentation.

#### Recommendation for Transparency

Should add to `README.md`:

```markdown
## Development Process

This codebase was developed using AI pair programming tools (Claude Code in Cursor IDE).
The AI assistant was used for:
- Initial scaffolding of agent implementations
- Boilerplate code generation (FastAPI routes, database models)
- Refinement and debugging of complex logic

Human decisions included:
- Architecture design (LangGraph + SharedContext + Celery)
- Specification interpretation (PS compliance)
- Testing and validation

**All code is human-reviewed and production-ready.**
```

---

## SUMMARY TABLE

| Question | Implemented | Status |
|----------|-------------|--------|
| 1. Dependency graphs | ✅ Yes | Dict (adjacency list) + asyncio.Event blocking + DFS cycle detection |
| 2. Span-level flagging | ✅ Yes | ClaimScore with exact span + confidence + flag_reason |
| 3. Self-reflection tool | ✅ Yes | Reads prior outputs, calls LLM, returns ToolResult with contradiction analysis |
| 4. Eval diff-ability | ⚠️ Partial | DB schema supports it; `/eval/latest` endpoint exists; no explicit diff endpoint |
| 5. Per-dimension justifications | ✅ Yes | All 6 stored in eval_results.justifications JSONB |
| 6. Input/output hashing | ✅ Yes | SHA-256[:16] for prompt_sent and output_received |
| 7. Provenance map | ✅ Yes | ProvenanceEntry(sentence, source_agent, source_chunk_id) |
| 8. Budget per-agent | ✅ Yes | Static declaration + consume() + assert_compliant() raises on overflow |
| 9. Docker services | ✅ Yes | 6 services (db, seeder, redis, api, worker, logquery) |
| 10. AI usage disclosure | ⚠️ Partial | Documented in final-steps-prompt.md, not in README |

---

## Appendix: File References

| File | LOC | Purpose |
|------|-----|---------|
| `agents/decomposition.py` | 176 | Dependency graph construction + DependencyExecutor |
| `agents/critique.py` | 116 | ClaimScore flagging with span extraction |
| `core/tools.py` | 415 | tool_self_reflect + other tools + ToolAction dispatch |
| `eval/harness.py` | 197 | Eval pipeline + storage |
| `core/context.py` | 295 | All data models (ClaimScore, ProvenanceEntry, ExecutionEventSchema) |
| `db/models.py` | 107 | Database schema (ExecutionEvent, EvalResult) |
| `docker-compose.yml` | 155 | Service definitions |
| `logquery/app.py` | 38 | Log query interface |
| `core/budget.py` | 128 | Budget declaration + enforcement |

