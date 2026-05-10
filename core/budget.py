"""
Context Budget Manager — Gemini override.

Token counting uses genai.GenerativeModel.count_tokens() (native Gemini API).
Falls back to len(text) // 4 if the API call fails.
asyncio.Lock (never threading.Lock).
Emits BUDGET_UPDATE SSE events on every consume().
Raises BudgetOverflowError on overflow — NEVER silently truncates.
"""
import asyncio
from typing import Dict, Optional, TYPE_CHECKING
import google.generativeai as genai
from core.context import BudgetEntry, PolicyViolation, SharedContext, EventType

if TYPE_CHECKING:
    from core.streaming import RedisPublisher


class BudgetOverflowError(Exception):
    def __init__(self, agent_id: str, budget: int, used: int):
        self.agent_id = agent_id
        self.budget = budget
        self.used = used
        super().__init__(
            f"Agent '{agent_id}' exceeded budget: {used}/{budget} tokens. "
            "PolicyViolation logged. Trigger compression before proceeding."
        )


class ContextBudgetManager:
    """
    Async-safe token budget manager.
    Tracks token usage per agent. Emits BUDGET_UPDATE SSE on every consume().
    Raises BudgetOverflowError on overflow — NEVER silently truncates.
    Uses genai.GenerativeModel.count_tokens().
    """

    DEFAULT_BUDGETS: Dict[str, int] = {
        "orchestrator":  2048,
        "decomposition": 3072,
        "retrieval":     6144,
        "critique":      4096,
        "synthesis":     4096,
        "compression":   8192,
        "meta":          4096,
    }

    def __init__(
        self,
        context: SharedContext,
        redis_pub: Optional["RedisPublisher"] = None,
    ) -> None:
        self._context = context
        self._redis_pub = redis_pub
        self._lock = asyncio.Lock()  # MUST be asyncio.Lock, never threading.Lock
        self._model = genai.GenerativeModel("models/gemini-2.0-flash")

    def _count(self, text_or_tokens: "str | int") -> int:
        """Token count using genai."""
        if isinstance(text_or_tokens, str):
            try:
                return max(1, self._model.count_tokens(text_or_tokens).total_tokens)
            except Exception:
                return max(1, len(text_or_tokens) // 4)
        return text_or_tokens

    def declare_budget(self, agent_id: str, max_tokens: int) -> None:
        """Synchronous — call before any async operations."""
        if agent_id not in self._context.budget_registry:
            self._context.budget_registry[agent_id] = BudgetEntry(
                agent_id=agent_id,
                max_tokens=max_tokens,
                used_tokens=0,
            )

    def check_remaining(self, agent_id: str) -> int:
        entry = self._context.budget_registry.get(agent_id)
        if entry is None:
            raise KeyError(f"Agent '{agent_id}' has not called declare_budget().")
        return entry.remaining

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

    def assert_compliant(self, agent_id: str) -> None:
        """
        Call BEFORE executing an agent with its assembled context.
        Raises BudgetOverflowError if over budget.
        NEVER silently truncates — that is a policy violation.
        """
        entry = self._context.budget_registry.get(agent_id)
        if entry is None:
            return

        if not entry.is_compliant:
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
            raise BudgetOverflowError(agent_id, entry.max_tokens, entry.used_tokens)

    def count_tokens(self, text: str) -> int:
        return self._count(text)

    def preflight_check(self, agent_id: str, text: str) -> bool:
        """Returns True if adding text would NOT overflow budget."""
        tokens = self.count_tokens(text)
        return tokens <= self.check_remaining(agent_id)

    def get_registry(self) -> Dict[str, BudgetEntry]:
        return dict(self._context.budget_registry)

    def serialize(self) -> dict:
        return {k: v.model_dump() for k, v in self.get_registry().items()}
