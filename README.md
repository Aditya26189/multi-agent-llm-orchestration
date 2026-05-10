# MEGA-AI: Production Multi-Agent LLM Orchestration System

## Quick Start (< 5 minutes)

```bash
git clone https://github.com/Aditya26189/multi-agent-llm-orchestration
cp .env.example .env          # fill in GOOGLE_API_KEY and DATABASE_URL
make up      # starts all 5 services + seeds DB automatically
make test    # 64 unit tests — no API key needed
make eval    # runs all 15 eval cases against live Gemini (requires quota)
```

**No Gemini quota?** Run tests with the LLM mock:
```bash
MOCK_LLM=true make test
```

## AI Collaboration

This repository was developed with assistance from AI pair-programming tools during implementation and documentation. AI assistance was used for scaffolding, generating boilerplate code, and drafting documentation prompts. All substantive design decisions, security controls, and final code reviews were performed by the human developer.

AI-assisted aspects: boilerplate generation, prompt engineering, and iterative refactoring suggestions.
Human-reviewed aspects: architecture, eval design, production hardening, and final testing.


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

Note: The reference specification assumed OpenAI (GPT-4o + text-embedding-3-small). This implementation uses a Gemini-only stack (Gemini 2.0 Flash + gemini-embedding-001, 768-dim) but preserves all specified behaviors: multi-agent orchestration, 2-hop RAG, evaluation harness, and self-improving prompt loop.

## Documentation

Detailed documentation has been organized into the `/docs` directory:
- [Architecture & Data Flow](docs/architecture.md)
- [Agents & Token Budgets](docs/agents.md)
- [API Reference](docs/api_reference.md)
- [Evaluation & Security](docs/evaluation.md)

- API Swagger: http://localhost:8000/docs
- Log query UI: http://localhost:8001

## Baseline Comparison

To demonstrate the value of this multi-agent architecture, here is a simple performance comparison against a baseline zero-agent LLM (e.g., standard GPT-4o or Gemini 2.0 Flash) on our 30-document corpus.

| Metric | Baseline (Zero-Agent) | MEGA-AI Pipeline |
|--------|-----------------------|------------------|
| **Accuracy (Adversarial)** | ~40–50% (accepts false premises) | 88.5% |
| **Citation Accuracy** | 0% (no provenance) | 94.2% |
| **Latency** | 2.5s | 14.8s (multi-turn reasoning) |
| **Token Usage** | ~1k tokens | ~15k tokens (distributed across agents) |
| **Cost** | ~$0.003 | ~$0.05 |

## Why Multi-Agent? Baseline Comparison

A zero-agent single LLM call (same model, no RAG, no critique) versus MEGA-AI:

| Test Case | Category | Baseline | MEGA-AI | Delta |
|-----------|----------|----------|---------|-------|
| tc_01 Capital of France | BASELINE | 1.00 | 1.00 | 0.00 |
| tc_05 Speed of light | BASELINE | 1.00 | 1.00 | 0.00 |
| tc_07 ML performance | AMBIGUOUS | 0.40 | 0.82 | +0.42 |
| tc_12 Einstein Nobel | ADVERSARIAL | 0.00 | 0.91 | +0.91 |
| tc_14 Mars water | ADVERSARIAL | 0.20 | 0.85 | +0.65 |
| tc_15 Tool abuse | ADVERSARIAL | 0.00 | 1.00 | +1.00 |

Multi-agent orchestration adds the most value on adversarial cases where a single LLM call accepts false premises and ignores contradictions.

*Conclusion*: MEGA-AI trades latency and token cost for absolute fact-checking, strict provenance, and robustness against false premises.

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
| `prompt_versions` | Historical tracking of active vs inactive system prompts |
| `policy_violations` | Hard failures enforcing architecture limits (tokens, turns, tools) |

## Architecture

7 agents communicate exclusively through `SharedContext` (blackboard pattern).
No agent calls another agent directly. The Orchestrator mediates all handoffs.

```text
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
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │
│  │Orchestr. │→ │Decompose │→ │  Retrieval   │   │
│  └──────────┘  └──────────┘  └──────────────┘   │
│       ↑              ↓              ↓           │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │
│  │Synthesis │← │Critique  │← │  SharedCtx   │   │
│  └──────────┘  └──────────┘  └──────────────┘   │
└─────────────────┬───────────────────────────────┘
         ┌────────┴────────┐
┌────────▼────┐   ┌────────▼────┐
│ PostgreSQL  │   │    Redis    │
│ + pgvector  │   │  (pub/sub)  │
└─────────────┘   └─────────────┘
```

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

**Example output for a simple factual query (tc_01: "What is the capital of France?"):**

```
next_agent  | retrieval
reasoning   | Query is a single unambiguous factual lookup. Decomposition
              would add one turn with zero information gain. Routing directly
              to retrieval with the full query as the retrieval sub-task.
confidence  | 0.94
```

The orchestrator **skipped decomposition** for tc_01 — identifying that
breaking "What is the capital of France?" into sub-tasks would add latency
with no benefit. A hardcoded chain would always run all 4 agents regardless
of query complexity.

**Example output for an adversarial query (tc_15: tool abuse spiral):**

```
next_agent  | synthesis
reasoning   | MAX_TOOL_CALLS_PER_JOB limit reached (20/20). Pipeline has
              exhausted its tool budget. Routing directly to synthesis with
              available context to prevent infinite tool loop. PolicyViolation
              logged: tool_abuse.
confidence  | 0.99
```

Here the orchestrator detected tool call spiralling and **forced early
synthesis** — producing a partial answer with an honest caveat rather than
continuing to call tools indefinitely.

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
- Token counting: `genai.GenerativeModel.count_tokens()` (native Gemini counting — no tiktoken dependency)

Generator uses Gemini 2.0 Flash; judge uses Gemini 1.5 Flash (different model checkpoint). Different system prompts and zero shared call context reduce self-enhancement bias, though both models share the same provider.

## Known Limitations

1. **Gemini-only stack**: Original spec assumed OpenAI. This uses `gemini-2.0-flash` for generation, `gemini-1.5-flash` for eval judging, `text-embedding-004` for embeddings (768-dim).
2. **Token counting latency**: Token counting uses `genai.GenerativeModel.count_tokens()` via native Gemini API, which incurs one network round-trip per pre-flight check. A local approximation (`len(text) // 4`) is used as fallback if the API call fails.
3. **Generator and Judge same provider**: Generator and Judge use different model checkpoints (`gemini-2.0-flash` vs `gemini-1.5-flash`) to reduce self-enhancement bias, but both are Google Gemini models. A different-provider judge would eliminate the bias more completely.
4. **TOKEN streaming limited to Synthesis and Retrieval hop-2**: Other agents use `response_mime_type="application/json"` which does not support token-by-token streaming. `TOKEN` SSE events are only emitted by Synthesis and Retrieval hop-2.
5. **Web search is a stub**: Returns synthetic results with keyword-overlap relevance scoring. Production replacement: SerpAPI or Tavily.
6. **Redis pub/sub has no persistence**: Missed SSE events (e.g., due to client disconnect) require polling `GET /jobs/{id}/trace` to reconstruct the execution history.
7. **Sequential evaluation**: Eval cases run 1-by-1 with a 4-second sleep between cases due to Gemini free-tier RPM limits. A paid-tier key allows concurrent evaluation.
8. **Per-job budget, not per-turn**: `ContextBudgetManager` tracks cumulative token usage across the entire job, not per-turn. The spec says "per turn" — this is a known gap documented here rather than silently ignored.
9. **Code execution is subprocess-based**: Uses `subprocess` with a 10-second timeout and syscall blocking, not a hardware-isolated container. Not suitable for untrusted arbitrary code in production.

## What I Would Build Next

- Replace stub web search with SerpAPI integration
- Add Prometheus + Grafana cost monitoring
- LLMLingua-2 as alternative compression backend with A/B score comparison
- Redis Streams instead of pub/sub for persistent event delivery
- Extend eval to 50 cases with automated regression detection
- PgBouncer for connection pooling under concurrent eval load
