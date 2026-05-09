"""
Decomposition Agent — breaks query into typed SubTasks with dependency graph.
DependencyExecutor uses asyncio.Event gates for dependency ordering.
"""
import asyncio
import json
import time
from datetime import datetime
from typing import Dict, List, Set

from agents.base import BaseAgent
from core.context import SharedContext, SubTask, SubTaskStatus, SubTaskType, EventType
from core.budget import ContextBudgetManager
from core.streaming import RedisPublisher

DECOMP_PROMPT = """Break the following query into typed sub-tasks with explicit dependencies.

Query: {query}

Rules:
1. Maximum 6 sub-tasks. Never over-decompose simple queries.
2. Task types: factual_lookup | reasoning | code_execution | data_retrieval | summarization | verification
3. deps[] must list task ids that MUST complete before this task can start.
4. Tasks with empty deps[] can run in parallel.
5. Descriptions must be specific enough for a retrieval agent to act on.
6. If query is simple (single clear fact needed), use 1-2 tasks maximum.

Return JSON with key "sub_tasks" containing an array of task objects.
Each task object must have: id (short string), type (one of the types above), description (string), deps (array of task ids).

Example:
{{"sub_tasks": [{{"id": "t1", "type": "factual_lookup", "description": "Find the capital of France", "deps": []}}]}}"""


class DecompositionAgent(BaseAgent):
    async def run(
        self,
        context: SharedContext,
        budget_mgr: ContextBudgetManager,
        redis_pub=None,
    ) -> None:
        budget_mgr.declare_budget("decomposition", 3072)
        prompt = DECOMP_PROMPT.format(query=context.query)
        await budget_mgr.consume("decomposition", prompt)
        budget_mgr.assert_compliant("decomposition")

        if redis_pub:
            await redis_pub.publish(context.job_id, {
                "event_type": "AGENT_START", "agent_id": "decomposition"
            })

        start = time.monotonic()
        try:
            raw_json = await self.generate_json(prompt)
            data = json.loads(raw_json)
            latency = (time.monotonic() - start) * 1000

            sub_tasks = []
            for t in data.get("sub_tasks", []):
                try:
                    task = SubTask(
                        id=t.get("id", f"t{len(sub_tasks)+1}"),
                        type=SubTaskType(t.get("type", "factual_lookup")),
                        description=t.get("description", ""),
                        deps=t.get("deps", []),
                    )
                    sub_tasks.append(task)
                except Exception:
                    continue

            if not sub_tasks:
                # Fallback: single subtask
                sub_tasks = [SubTask(
                    id="t1",
                    type=SubTaskType.FACTUAL_LOOKUP,
                    description=context.query,
                    deps=[],
                )]

            context.subtasks = sub_tasks
            context.dependency_graph = {t.id: t.deps for t in sub_tasks}

            await budget_mgr.consume("decomposition", raw_json)
            context.add_event(
                agent_id="decomposition",
                event_type=EventType.AGENT_START,
                prompt_sent=prompt,
                output_received=raw_json,
                latency_ms=latency,
                token_count=budget_mgr.count_tokens(prompt),
            )

        except Exception as e:
            # Fallback
            context.subtasks = [SubTask(
                id="t1",
                type=SubTaskType.FACTUAL_LOOKUP,
                description=context.query,
                deps=[],
            )]
            context.dependency_graph = {"t1": []}
            context.add_event(
                agent_id="decomposition",
                event_type=EventType.ERROR,
                policy_violation=f"decomposition_failed: {str(e)[:100]}",
            )


class DependencyExecutor:
    """Execute sub-tasks in dependency order using asyncio.Event gates.

    Cycle detection runs a DFS BEFORE execution and raises ValueError
    to prevent deadlocks on circular dependencies (Section 7, Differentiator #13).
    """

    def __init__(self, sub_tasks: List[SubTask]):
        self.tasks: Dict[str, SubTask] = {t.id: t for t in sub_tasks}
        self._events: Dict[str, asyncio.Event] = {
            t_id: asyncio.Event() for t_id in self.tasks
        }
        self._failed: Set[str] = set()
        self._detect_cycles()  # Raises ValueError if circular dep found

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
                    elif dep_id in rec_stack:
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

    async def execute(self, handler) -> Dict[str, str]:
        """handler: async callable(subtask) -> str"""
        await asyncio.gather(
            *[self._run_task(t, handler) for t in self.tasks.values()],
            return_exceptions=True,
        )
        return {tid: t.output or "" for tid, t in self.tasks.items()}

    async def _run_task(self, task: SubTask, handler) -> None:
        for dep_id in task.deps:
            if dep_id not in self._events:
                task.status = SubTaskStatus.FAILED
                task.error = f"Unknown dep: {dep_id}"
                self._failed.add(task.id)
                self._events[task.id].set()
                return
            await self._events[dep_id].wait()
            if dep_id in self._failed:
                task.status = SubTaskStatus.FAILED
                task.error = f"Dep '{dep_id}' failed"
                self._failed.add(task.id)
                self._events[task.id].set()
                return

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
            self._events[task.id].set()
