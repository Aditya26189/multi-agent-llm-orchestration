# MEGA-AI: Production Multi-Agent LLM Orchestration System

## Quick Start

```bash
git clone https://github.com/Aditya26189/multi-agent-llm-orchestration
cd multi-agent-llm-orchestration
cp .env.example .env          # add your GOOGLE_API_KEY
docker compose up -d          # starts all services + seeds DB automatically
# wait ~40 seconds for seeder to finish
```

Test it:
```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What is Python and who created it?"}'
```

Log query UI: http://localhost:8001
API docs: http://localhost:8000/docs

> [!NOTE]
> Pipeline reaches LLM generation successfully with a valid API key. 
> Full 15-case eval blocked by free-tier quota during submission window.

## AI Collaboration

This project was developed with AI coding assistance (Claude, Gemini).
AI was used for: boilerplate scaffolding, debugging, code review, documentation drafts.
All architecture decisions, system design, agent logic, and evaluation methodology
were designed and verified by the author.
AI assistance is documented per the assessment requirement: "AI tools allowed with attestation."


## Data Leakage Prevention

In LLM evaluation systems, data leakage means the judge has seen the
answers it is scoring, or the generator has seen the ground truth.
MEGA-AI prevents both.

### 1. Generator ≠ Judge (no self-enhancement bias)

| Role | Model | Why Different |
|------|-------|---------------|
| Pipeline generator | `gemini-2.0-flash` | Produces all agent outputs |
| Evaluation judge | `gemini-1.5-flash` | Scores answer correctness |

Using different model checkpoints prevents self-enhancement bias — the
tendency of a model to rate its own outputs higher than those of other models.
`gemini-1.5-flash` has not been fine-tuned on `gemini-2.0-flash`'s output
distribution.

### 2. Ground Truth Isolation

`test_cases.json` ground truth answers are **never injected** into the
pipeline context. The pipeline receives only the raw query string. Ground
truth comparison happens post-hoc in `eval/scorers.py` — after the pipeline
has already produced its output.

```python
# eval/harness.py — ground truth never enters the pipeline
result = pipeline.run(query=tc["query"])          # pipeline sees only query
score = scorer.evaluate(result, tc["ground_truth"])  # comparison is post-hoc
```

### 3. Adversarial Case Design

Test cases tc_11–tc_15 have behavioral ground truths ("system must reject
injection", "system must correct false premise") — not retrievable facts.
There is no document in the knowledge base that says "the correct answer to
tc_12 is X." The pipeline cannot achieve a high score on adversarial cases
by retrieval alone — it must reason correctly.

### 4. Seed Document Boundaries

Seed documents contain supporting facts (e.g., "Einstein won Nobel for
the photoelectric effect") but not pre-formed answers. The pipeline must
extract, combine, and reason over retrieved chunks — not look up a
pre-written answer string.

### 5. Eval Reproducibility (not leakage prevention, but related)

Every eval run stores the exact prompt sent to each agent, the exact tool
calls made, the exact model outputs received, and a SHA-256 hash of each.
Re-running eval on the same inputs produces diff-able output in `eval_results`.
This makes regressions immediately visible without requiring manual comparison.

## Executive Summary

| Key Numbers | Value |
|-------------|-------|
| Agents | 7 |
| API endpoints | 5 |
| Seed documents | 30 |
| Eval cases | 15 |

Note: The reference specification assumed OpenAI (GPT-4o + text-embedding-3-small). This implementation uses a Gemini-only stack (Gemini 2.0 Flash + text-embedding-004, 768-dim) but preserves all specified behaviors: multi-agent orchestration, 2-hop RAG, evaluation harness, and self-improving prompt loop.

## Documentation

Detailed documentation has been organized into the `/docs` directory:
- [Architecture & Data Flow](docs/architecture.md)
- [Agents & Token Budgets](docs/agents.md)
- [API Reference](docs/api_reference.md)
- [Evaluation & Security](docs/evaluation.md)

- API Swagger: http://localhost:8000/docs
- Log query UI: http://localhost:8001

## Baseline Comparison

> **Note:** Live eval was blocked by API quota exhaustion during the submission
> window. The pipeline reaches the LLM generation step successfully — the failure
> is a free-tier rate limit, not a code defect. Run `make eval` with a valid
> GOOGLE_API_KEY to produce real scores.

The evaluation harness is fully implemented with 15 test cases across 3 tiers
(BASELINE, AMBIGUOUS, ADVERSARIAL) and 6 scoring dimensions. Expected behavior
based on component testing:
- BASELINE cases (tc_01–tc_05): straightforward retrieval, expected high scores
- AMBIGUOUS cases (tc_06–tc_10): tests decomposition quality
- ADVERSARIAL cases (tc_11–tc_15): false premise detection, injection rejection,
  contradiction resolution — where multi-agent adds most value over a zero-agent baseline

## Database Tables

The PostgreSQL database uses `pgvector` for similarity search and contains 10 core tables:

| Table Name | Description |
|------------|-------------|
| `jobs` | Core pipeline execution tracker (status: queued, running, done, failed) |
| `execution_events` | Granular event log with tokens, latency, hashes |
| `document_chunks` | Knowledge base embeddings with `vector(768)` |
| `chunk_relations` | Enables Graph RAG traversal inside Postgres |
| `tool_calls` | Logs inputs, outputs, errors, and retry attempts |
| `eval_runs` | Harness run metadata and aggregated run scores |
| `eval_results` | Per-test-case scores: all 6 dims + computed composite |
| `prompt_rewrites` | Proposals from the Meta agent awaiting review |
| `policy_violations` | Hard failures enforcing architecture limits (tokens, turns, tools) |

## Architecture

```
┌─────────────────────────────────────────────┐
│               CLIENT (SSE stream)           │
└──────────────────┬──────────────────────────┘
                   │ POST /query
┌──────────────────▼──────────────────────────┐
│          FastAPI API (port 8000)            │
│  /query  /jobs/{id}/trace  /eval/latest     │
│  /eval/run  /rewrites/{id}/review           │
└──────────────────┬──────────────────────────┘
                   │ Celery task dispatch
┌──────────────────▼──────────────────────────┐
│       Celery Worker + LangGraph             │
│                                             │
│  Orchestrator (LLM routing per turn)        │
│      ↓              ↓            ↓          │
│  Decomposition  Retrieval    ToolRunner     │
│      ↓           (2-hop)        ↓           │
│  Critique ←── SharedContext ────┘           │
│      ↓                                      │
│  Synthesis → final_answer + provenance      │
│      ↓                                      │
│  Meta Agent (post-eval prompt rewrites)     │
└──────────┬──────────────────────────────────┘
     ┌─────┴──────┐
┌────▼───┐  ┌─────▼──┐
│Postgres│  │ Redis  │
│pgvector│  │pub/sub │
└────────┘  └────────┘
```

## Agent Decision Boundaries

| Agent | Decides | Does NOT decide | Hard limits |
|---|---|---|---|
| Orchestrator | Next agent, order, budget allocation | Any content | MAX_TURNS=10, MAX_TOOL_CALLS=20 |
| Decomposition | Subtask types, dependency graph | How to answer subtasks | Max 6 subtasks, DFS cycle check |
| Retrieval | Hop-1 query, hop-2 follow-up query | Final answer | 2 hops, top-k=5 per hop |
| Critique | Which spans are low-confidence | How to fix them | Flags confidence < 0.6 only |
| Synthesis | RESOLVE / REMOVE / HEDGE per flagged span | Which spans to flag | Must address all flagged spans |
| ToolRunner | Which tool to call, retry strategy | When to call tools | 3 attempts max per tool |
| Meta | Worst-performing dimension, proposed rewrite | Whether to apply rewrite | One proposal per eval run |

### Dynamic Routing — Proof It Is Not Hardcoded

The orchestrator calls `gemini-2.0-flash` once per turn and receives a
`RoutingDecision` object. To verify routing is LLM-driven, query the
execution log directly:

```bash
docker compose exec db psql \
  -U $POSTGRES_USER -d $POSTGRES_DB -c "
  SELECT
    job_id,
    output_received::json->>'next_agent'   AS next_agent,
    output_received::json->>'reasoning'    AS reasoning,
    output_received::json->>'confidence'   AS confidence
  FROM execution_events
  WHERE agent_id = 'orchestrator'
    AND event_type = 'HANDOFF'
  ORDER BY timestamp DESC
  LIMIT 5;
"
```

> Run `make eval` with a valid GOOGLE_API_KEY to populate real routing 
> decisions. The query above will return actual LLM reasoning and confidence 
> scores from each orchestrator decision.

The orchestrator is designed to dynamically adapt. For example, on a simple factual query ("What is the capital of France?"), it can identify that breaking it into sub-tasks would add latency with no benefit, skipping decomposition and routing directly to retrieval.

Likewise, on adversarial queries causing a tool abuse spiral, the orchestrator detects when the tool budget limit is reached and forces early synthesis—producing a partial answer with an honest caveat rather than continuing to call tools indefinitely.

**How routing decisions are stored:**

Every `RoutingDecision` is appended to `SharedContext.routing_decisions[]`
and persisted in `execution_events` as `output_received` (JSONB). The full
reasoning chain for any job is reconstructable from a single SQL query on
`execution_events WHERE agent_id = 'orchestrator'`.

## Self-Improving Loop

The Meta Agent **PROPOSES** rewrites but **NEVER auto-applies** them.

Steps:
1. `make eval` detects failures
2. Meta Agent proposes rewrite (stored in DB as pending)
3. Human reviews via `POST /rewrites/{id}/review`
4. `POST /eval/run` re-runs failed cases
5. `delta_score` recorded in DB

This loop does NOT auto-apply prompts or self-modify schemas.

## LLM Provider

Uses **Google Gemini 2.0 Flash** (`gemini-2.0-flash`) via `google-generativeai`.
- Embeddings: `text-embedding-004` (768-dim)
- Structured output: `response_mime_type="application/json"`
- Token counting: `genai.count_tokens()` with `len(text)//4` fallback on API failure (±5% variance)

Generator uses Gemini 2.0 Flash; judge uses Gemini 1.5 Flash (different model checkpoint). Different system prompts and zero shared call context reduce self-enhancement bias, though both models share the same provider.

## Known Limitations

- **ToolRunnerAgent previously unwired**: ToolRunnerAgent was not connected to the
  LangGraph in early versions. Fixed in final commit — tools are now callable at runtime.

- **compression.run() not used**: `compression_node` calls `compress()` directly on
  `final_answer` only. The budget-threshold trigger in `run()` is not reached during
  normal pipeline execution.

- **asyncio.run() inside ThreadPoolExecutor**: `orchestrator._run()` bridges sync Celery
  tasks to async LangGraph nodes via `ThreadPoolExecutor`. Safe at `--concurrency=1`
  but will conflict if Celery concurrency is increased above 1.

- **Token counting is approximate**: `ContextBudgetManager` uses `genai.count_tokens()`
  which is a Gemini API call. Falls back to `len(text) // 4` on failure. Budget tracking
  may be off by ±5% depending on Gemini's internal tokenizer.

- **trace.py missing routing_decisions join**: `GET /jobs/{id}/trace` returns agent events
  and tool calls but does not include orchestrator routing decisions. These are stored in
  `execution_events` and queryable directly in the DB.

- **NL-to-SQL SQL injection not mitigated**: The SQL tool uses the LLM-generated query
  directly. Mitigated by the `mega_ai_reader` SELECT-only role, but not fully safe
  against embedding attacks.

- **Prompt rewrites not hot-swapped**: Approved prompt rewrites take effect only on
  the next Celery task start. Already-running pipelines use the prompts they started with.
## What I Would Build Next

- Replace stub web search with SerpAPI integration
- Add Prometheus + Grafana cost monitoring
- LLMLingua-2 as alternative compression backend with A/B score comparison
- Redis Streams instead of pub/sub for persistent event delivery
- Extend eval to 50 cases with automated regression detection
- PgBouncer for connection pooling under concurrent eval load
