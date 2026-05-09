"""
Celery pipeline task.

Architecture:
- Orchestrator decides next agent via LLM routing (NOT hardcoded sequence)
- Each agent writes to SharedContext — never calls other agents directly
- BudgetManager auto-triggers compression at 80% budget usage
- All events published to Redis → SSE client sees real-time updates

Gemini override: asyncio.run() instead of get_event_loop().run_until_complete()
                 GOOGLE_API_KEY for model access
"""
import asyncio
import os

from worker.celery_app import app
from core.context import SharedContext, AgentID, JobStatus, EventType
from core.budget import ContextBudgetManager, BudgetOverflowError
from core.streaming import RedisPublisher
from agents.orchestrator import Orchestrator, MAX_TURNS, build_pipeline
from agents.decomposition import DecompositionAgent
from agents.retrieval import RetrievalAgent
from agents.critique import CritiqueAgent
from agents.synthesis import SynthesisAgent
from agents.compression import CompressionAgent

GOOGLE_KEY = os.environ["GOOGLE_API_KEY"]
REDIS_URL   = os.environ["REDIS_URL"]
DB_URL      = os.environ["DATABASE_URL"]


@app.task(
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=600,
    time_limit=660,
    queue="heavy_tasks",
)
def run_agent_pipeline(self, query: str, job_id: str) -> dict:
    """
    Main pipeline task.
    Uses asyncio.run() — NOT get_event_loop().run_until_complete() (Gemini override).
    """
    return asyncio.run(_run_pipeline_async(query, job_id))


async def _run_pipeline_async(query: str, job_id: str) -> dict:
    redis_pub = RedisPublisher(REDIS_URL)
    await redis_pub.connect()

    context = SharedContext(job_id=job_id, query=query, status=JobStatus.RUNNING)
    budget_mgr = ContextBudgetManager(context, redis_pub)

    orchestrator = Orchestrator()
    compression_agent = CompressionAgent()

    # Create DB session for retrieval
    from db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        agents = {
            AgentID.DECOMPOSITION: DecompositionAgent(),
            AgentID.RETRIEVAL:     RetrievalAgent(),
            AgentID.CRITIQUE:      CritiqueAgent(),
            AgentID.SYNTHESIS:     SynthesisAgent(),
            AgentID.COMPRESSION:   compression_agent,
        }

        try:
            # ── MAIN PIPELINE LOOP ─────────────────────────────────────────────
            pipeline = build_pipeline(
                orchestrator=orchestrator,
                agents_map=agents,
                budget_mgr=budget_mgr,
                redis_pub=redis_pub,
                compression_agent=compression_agent
            )
            
            # Run LangGraph pipeline synchronously as required by Celery context
            final_state = await pipeline.ainvoke(context)

            # Auto-trigger compression if any agent near budget limit
            for agent_id, entry in budget_mgr.get_registry().items():
                if entry.used_tokens > entry.max_tokens * 0.80:
                    await redis_pub.publish(final_state.job_id, {
                        "event_type": "COMPRESSION_TRIGGERED",
                        "agent_id": agent_id,
                        "used": entry.used_tokens,
                        "max": entry.max_tokens,
                        "id": final_state.next_seq(),
                    })

                    if agent_id == "retrieval":
                        if final_state.retrieved_chunks:
                            chunks_text = "\n\n".join(
                                f"[CHUNK:{c.id}]: {c.text}"
                                for c in final_state.retrieved_chunks
                            )
                            compressed = await compression_agent.compress(
                                agent_id=agent_id,
                                text=chunks_text,
                                target_tokens=int(entry.max_tokens * 0.70),
                                budget_mgr=budget_mgr,
                                context=final_state,
                            )
                            final_state.retrieval_reasoning = compressed

                    elif agent_id in ("synthesis", "critique"):
                        if final_state.final_answer and len(final_state.final_answer) > 200:
                            final_state.final_answer = await compression_agent.compress(
                                agent_id=agent_id,
                                text=final_state.final_answer,
                                target_tokens=int(entry.max_tokens * 0.70),
                                budget_mgr=budget_mgr,
                                context=final_state,
                            )

                    elif agent_id == "decomposition":
                        for task in final_state.subtasks:
                            if len(task.description) > 200:
                                task.description = task.description[:200] + "..."

            # ── PIPELINE COMPLETE ──────────────────────────────────────────────
            if final_state.status != JobStatus.DONE:
                final_state.status = JobStatus.DONE

            await redis_pub.publish_done(final_state.job_id, final_state.final_answer)

            # Persist to DB
            await _save_context_to_db(final_state)

            return {
                "job_id": final_state.job_id,
                "status": "done",
                "final_answer": final_state.final_answer,
                "context": final_state,
            }

        except Exception as e:
            context.status = JobStatus.FAILED
            await redis_pub.publish_error(context.job_id, str(e))
            await _save_context_to_db(context)
            raise

        finally:
            await redis_pub.disconnect()


async def _save_context_to_db(context: SharedContext) -> None:
    """Persist full context to PostgreSQL for trace reconstruction."""
    from db.session import AsyncSessionLocal
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

    engine = create_async_engine(DB_URL)
    AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    from core.cost import CostCalculator
    cost_calc = CostCalculator()
    total_cost = sum(
        cost_calc.calculate(
            model=event.model_used or "",
            input_tokens=event.input_token_count or 0,
            output_tokens=event.output_token_count or 0,
        )
        for event in context.execution_events
        if hasattr(event, "model_used")
    )

    async with AsyncSessionLocal() as db:
        # Upsert job
        await db.execute(text("""
            INSERT INTO jobs (job_id, query, status, completed_at, total_tokens_used, total_cost_usd, model_used)
            VALUES (:jid, :q, :s, NOW(), :tok, :cost, :model)
            ON CONFLICT (job_id) DO UPDATE SET
                status = EXCLUDED.status,
                completed_at = EXCLUDED.completed_at,
                total_tokens_used = EXCLUDED.total_tokens_used,
                total_cost_usd = EXCLUDED.total_cost_usd
        """), {
            "jid": context.job_id,
            "q": context.query,
            "s": context.status.value,
            "tok": sum(e.token_count for e in context.execution_events),
            "cost": total_cost,
            "model": "gemini-2.0-flash",
        })

        # Insert execution events
        for event in context.execution_events:
            try:
                await db.execute(text("""
                    INSERT INTO execution_events
                    (job_id, seq, agent_id, event_type, prompt_sent, output_received,
                     input_hash, output_hash, latency_ms, token_count, policy_violation, timestamp)
                    VALUES (:jid, :seq, :aid, :et, :ps, :or_, :ih, :oh, :lat, :tok, :pv, :ts)
                    ON CONFLICT DO NOTHING
                """), {
                    "jid": context.job_id,
                    "seq": event.seq,
                    "aid": event.agent_id,
                    "et": event.event_type.value if hasattr(event.event_type, "value") else event.event_type,
                    "ps": event.prompt_sent,
                    "or_": event.output_received,
                    "ih": event.input_hash,
                    "oh": event.output_hash,
                    "lat": event.latency_ms,
                    "tok": event.token_count,
                    "pv": event.policy_violation,
                    "ts": event.timestamp,
                })
            except Exception:
                continue

        # Insert tool calls
        for tc in context.tool_calls:
            try:
                import json
                await db.execute(text("""
                    INSERT INTO tool_calls
                    (job_id, agent_id, tool_name, attempt_number, input_json, output_json,
                     latency_ms, accepted, error_code, retry_reason, timestamp)
                    VALUES (:jid, :aid, :tn, :an, :ij::jsonb, :oj::jsonb,
                            :lat, :acc, :ec, :rr, :ts)
                """), {
                    "jid": context.job_id,
                    "aid": tc.agent_id,
                    "tn": tc.tool_name.value,
                    "an": tc.attempt_number,
                    "ij": json.dumps(tc.input_data, default=str),
                    "oj": json.dumps(tc.output_data or {}, default=str),
                    "lat": tc.latency_ms,
                    "acc": tc.accepted,
                    "ec": tc.error_code,
                    "rr": tc.retry_reason,
                    "ts": tc.timestamp,
                })
            except Exception:
                continue

        # Insert routing decisions
        for rd in context.routing_decisions:
            try:
                await db.execute(text("""
                    INSERT INTO routing_decisions
                    (job_id, turn, next_agent, reasoning, confidence, timestamp)
                    VALUES (:jid, :turn, :na, :rea, :conf, :ts)
                """), {
                    "jid": context.job_id,
                    "turn": context.turn,
                    "na": rd.next_agent.value if hasattr(rd.next_agent, "value") else rd.next_agent,
                    "rea": rd.reasoning,
                    "conf": rd.confidence,
                    "ts": rd.decided_at,
                })
            except Exception:
                continue

        # Insert policy violations
        for v in context.violations:
            try:
                await db.execute(text("""
                    INSERT INTO policy_violations
                    (id, job_id, agent_id, violation_type, details, tokens_over_budget, timestamp)
                    VALUES (:id, :jid, :aid, :vt, :det, :tob, :ts)
                """), {
                    "id": v.violation_id,
                    "jid": context.job_id,
                    "aid": v.agent_id,
                    "vt": v.violation_type,
                    "det": v.details,
                    "tob": v.tokens_over_budget,
                    "ts": v.timestamp,
                })
            except Exception:
                continue

        await db.commit()
    await engine.dispose()
