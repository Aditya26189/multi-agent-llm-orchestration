# MEGA-AI Architecture

## Mermaid Diagram

```mermaid
graph TB
    Client["Client (curl / browser)"]
    API["FastAPI :8000\n/query /trace /eval\n/rewrites /eval/run"]
    Redis["Redis :6379\npub/sub + job queue"]
    Worker["Celery Worker\nrun_agent_pipeline"]
    DB["PostgreSQL :5432\npgvector(768)"]
    LogUI["LogQuery Flask :8001"]

    Client -->|POST /query| API
    API -->|submit task| Redis
    Redis -->|dequeue| Worker
    Worker -->|publish events| Redis
    Redis -->|SSE stream| Client
    Worker -->|persist context| DB
    API -->|read trace/eval| DB
    LogUI -->|read events| DB

    subgraph "SharedContext Blackboard"
        SC["SharedContext\n(job_id, query, sub_tasks\nchunks, claims, answer\nbudget_registry, violations)"]
    end

    subgraph "7 Agents (write to SharedContext only)"
        O["Orchestrator\nGemini JSON → RoutingDecision"]
        D["Decomposition\nSubTasks + DependencyGraph"]
        R["Retrieval\n2-hop pgvector + [CHUNK:id] citations"]
        C["Critique\nper-span ClaimScore + flagging"]
        S["Synthesis\nRESOLVE/REMOVE/HEDGE + provenance"]
        Comp["Compression\nlossless structured, lossy filler"]
        M["Meta\nPromptRewrite + difflib diff → DB"]
    end

    Worker --> O
    O -->|route| SC
    SC -->|next_agent| D
    SC -->|next_agent| R
    SC -->|next_agent| C
    SC -->|next_agent| S
    SC -->|budget 90%| Comp
    SC -->|eval failures| M
```

## Data Flow

1. Client `POST /query` → API creates `job_id`, submits Celery task
2. Celery task creates `SharedContext`, starts orchestrator loop
3. Orchestrator calls Gemini → `RoutingDecision` → next agent
4. Agent runs, writes outputs to `SharedContext`, publishes SSE events to Redis
5. Loop continues until synthesis complete or `MAX_TURNS` reached
6. Context persisted to PostgreSQL, `done` event published to Redis
7. Client receives final answer via SSE stream

## Key Design Decisions

### Why SharedContext (Blackboard Pattern)?
Agents do NOT call each other directly. This eliminates cascading failures, makes the execution trace fully reproducible, and allows any agent to be replaced without breaking others.

### Why asyncio.Lock in ContextBudgetManager?
The budget manager must be safe across concurrent sub-task execution in the DependencyExecutor. threading.Lock would deadlock inside an async event loop.

### Why len(text)//4 instead of tiktoken?
Gemini API does not expose token counts per-request. The heuristic is deterministic, dependency-free, and accurate enough for budget tracking (not billing).

### Why NEVER silently truncate?
Silent truncation hides data loss from the debugging trace. An explicit BudgetOverflowError forces the system to route to the Compression agent, which makes the compression decision auditable.
