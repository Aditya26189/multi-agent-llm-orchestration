# Guide: MEGA-AI Multi-Agent System

This guide is designed to help you explain the **MEGA-AI** project. It covers the high-level elevator pitch, the architecture, core engineering challenges, and how you resolved complex production issues.

---

## 1. The 30-Second Elevator Pitch
> *"MEGA-AI is a production-grade, asynchronous multi-agent orchestration system built to solve complex research and retrieval tasks. Instead of using a rigid, sequential RAG pipeline, it uses an LLM-driven StateGraph orchestrator to dynamically route queries between 7 specialized agents (Decomposition, Retrieval, Critique, Synthesis, Compression, Meta, and Tool Runner) sharing a centralized state blackboard. It is fully asynchronous, powered by Celery, Redis, and PostgreSQL with pgvector, and features strict token budget enforcement, round-robin API key rotation, and a self-improving prompt optimization loop."*

---

## 2. Key Architecture Details
When asked about the system design, use this breakdown:

* **Orchestration Pattern (LangGraph StateGraph):** 
  * The system does not use hardcoded sequence chains. A central **Orchestrator** agent receives the query context and outputs a JSON `RoutingDecision` deciding the next agent, reasoning, and confidence.
  * All agents are decoupled; they **never invoke each other**. Instead, they read from and write to a centralized, thread-safe Pydantic model (`SharedContext`).
* **The Background Engine (Celery + Redis + Postgres):**
  * heavy LLM generation tasks can take 15–20 seconds. The FastAPI gateway accepts the query, assigns a UUID, queues the task via Celery, and immediately returns a Server-Sent Events (SSE) stream.
  * Redis acts as the task queue and Pub/Sub channel for streaming token-by-token generation and agent state changes.
  * PostgreSQL persists the execution traces (`execution_events`, `routing_decisions`, `tool_calls`, `policy_violations`) for debugging and evaluation.
* **Graph RAG (pgvector):**
  * Retrieval is performed using a 2-hop search against a 768-dimensional database index (using Google's `text-embedding-004`).
  * **Hop-1** fetches the base documents.
  * An intermediate LLM call generates a refined query based on Hop-1 context.
  * **Hop-2** queries the vector store again to retrieve deep context and injects exact `[CHUNK:uuid]` citation markers.

---

## 3. Engineering Challenges & How You Solved Them
Interviewers love hearing about hard bugs you debugged and resolved. Here are the four primary challenges you conquered in this project:

### Challenge A: The "Event Loop Is Closed" Connection Leak
* **The Problem:** In a Celery worker environment, each task runs inside a freshly generated event loop created by `asyncio.run()`. Initially, the Redis connection pool was declared globally at the module import level. When the first task finished, its event loop closed. When the second task began, it attempted to reuse the global Redis client, causing a fatal crash: `RuntimeError: Event loop is closed`.
* **The Solution:** You refactored `RedisPublisher` to instantiate connection pools and client instances locally within the task's context and wrapped them in robust `try...finally` blocks to explicitly close the connections and disconnect the pool upon task completion.

### Challenge B: Context Budget Overflows & Token Mitigation
* **The Problem:** Parallel execution of agent tasks can cause token accumulation that exceeds the context window, leading to high latency, increased costs, or truncation errors.
* **The Solution:** 
  * You implemented a `ContextBudgetManager` that tracks tokens consumed by each agent.
  * It protects the budget registry using an `asyncio.Lock` to prevent race conditions during concurrent subtask executions.
  * Instead of silently truncating (which hides details from audit logs), it raises a `BudgetOverflowError` and logs a `policy_violations` event, automatically routing the state to the **Compression Agent** to perform structured lossless/lossy compression.

### Challenge C: Gemini API Rate-Limiting & Overload Resilience
* **The Problem:** The Gemini API free tier enforces a strict 15 Requests Per Minute (RPM) limit. Running evaluation harnesses or high-concurrency requests quickly resulted in `429 Resource Exhausted` or `503 Service Overloaded` errors.
* **The Solution:**
  * **Multi-Key Rotation:** Configured each agent to read multiple API keys from environment variables and rotate them round-robin on every generation call.
  * **Robust Backoff:** HARDENED `call_with_backoff` to catch `503`, `unavailable`, and `overloaded` status codes, executing exponential backoff (`(2 ** attempt) * 5` seconds sleep) paired with key rotation.

### Challenge D: Citation Post-Processing & Provenance Separation
* **The Problem:** The Synthesis agent outputs citation tags (`[CHUNK:uuid]`) and thoughts (`[REASONING]`) inline. Displaying these raw tags to the user makes the output unreadable, yet stripping them completely loses the audit trail.
* **The Solution:**
  * Added a regex-based `clean_final_answer()` method to the shared context to clean up the user-facing answer text.
  * Modified the streaming publisher to output clean prose as the `final_answer` and deliver the structured `provenance` mapping list as a separate metadata field.

---

## 4. The Self-Improving Prompt Loop
If asked about advanced LLM features:
1. **Evaluation:** When the `EvaluationHarness` runs the 15 test cases, it rates them across 6 dimensions.
2. **Analysis:** If the score drops below a threshold, the **Meta Agent** scans the Postgres `execution_events` to locate the point of failure.
3. **Proposal:** It generates a prompt rewrite in `difflib` patch format and saves it as pending.
4. **Hot-Swapping:** An administrator approves it via `POST /rewrites/{rewrite_id}/review`. The next time Celery starts a pipeline task, it dynamically hot-swaps the prompt variables at runtime using python `setattr` overrides, without needing a container restart.

---

## 5. Potential Interview Questions and Answers

#### Q: Why did you use LangGraph instead of a simple sequential script?
> *"LangGraph allows us to build cyclical agent workflows. In a production system, agents need to loop back. For example, if the Critique agent finds an error, the pipeline must loop back to Synthesis to fix it. LangGraph provides the graph state wrapper, but we kept the routing logic inside our Orchestrator class to prevent framework lock-in."*

#### Q: How did you ensure thread-safety when agents run concurrently?
> *"We protected the token counting registry inside `ContextBudgetManager` with an `asyncio.Lock`. Since multiple subtasks can execute concurrently in Python's async loop, using a standard thread lock would block the entire event loop. The async lock ensures only one task updates budget counters at a time."*

#### Q: How does the system handle SQL injection in the NL-to-SQL tool?
> *"At the API gateway, we implement Layer 1 regex checks to block malicious input. Inside the database, the tool runner queries Postgres using a restricted database user role (`mega_ai_reader`) that only has SELECT privileges on specific tables, preventing data mutation even if a malicious query gets generated."*
