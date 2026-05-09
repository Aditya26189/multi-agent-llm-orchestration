import asyncio
import json
import time
from typing import Optional

from core.context import SharedContext, AgentID, EventType, ToolCallRecord, ToolName
from core.budget import ContextBudgetManager
from core.streaming import RedisPublisher
from core.tools import execute_tool_with_retry, tool_web_search, tool_code_exec, tool_sql_lookup, tool_self_reflect, broaden_web_query

class ToolRunnerAgent:
    def __init__(self, db):
        self._db = db

    async def run(
        self,
        context: SharedContext,
        budget_mgr: ContextBudgetManager,
        redis_pub: Optional[RedisPublisher] = None,
    ) -> None:
        if redis_pub:
            await redis_pub.publish(context.job_id, {
                "event_type": "AGENT_START", "agent_id": "tool_runner"
            })
        
        # Check last routing decision for tool calls
        if not context.routing_decisions:
            return
        
        last_decision = context.routing_decisions[-1]
        last_event = None
        for event in reversed(context.execution_events):
            if event.agent_id == "orchestrator":
                last_event = event
                break
        
        if not last_event or not last_event.output_received:
            return
            
        try:
            data = json.loads(last_event.output_received)
            tool_calls = data.get("tool_calls", [])
        except json.JSONDecodeError:
            tool_calls = []

        for call in tool_calls:
            tool_name = call.get("name")
            kwargs = call.get("kwargs", {})
            
            tool_fn = None
            modify_input_fn = None
            if tool_name == "tool_web_search":
                tool_fn = tool_web_search
                modify_input_fn = broaden_web_query
            elif tool_name == "tool_code_exec":
                tool_fn = tool_code_exec
            elif tool_name == "tool_sql_lookup":
                kwargs["db_session"] = self._db
                tool_fn = tool_sql_lookup
            elif tool_name == "tool_self_reflect":
                kwargs["agent_id"] = kwargs.get("agent_id", "orchestrator")
                kwargs["context"] = context
                tool_fn = tool_self_reflect
            
            if tool_fn:
                # Add tool_call_start and end events for SSE
                if redis_pub:
                    await redis_pub.publish(context.job_id, {"event_type": "TOOL_CALL_START", "tool": tool_name})
                    
                result = await execute_tool_with_retry(
                    tool_fn=tool_fn,
                    tool_name=tool_name,
                    agent_id="tool_runner",
                    context=context,
                    tool_kwargs=kwargs,
                    modify_input_fn=modify_input_fn,
                    max_retries=2
                )
                
                # Append result to context so orchestrator can read it
                if result and result.data:
                    context.add_event(
                        agent_id="tool_runner",
                        event_type=EventType.AGENT_START,
                        prompt_sent=json.dumps(kwargs),
                        output_received=json.dumps(result.data),
                        latency_ms=result.latency_ms,
                    )
                
                if redis_pub:
                    await redis_pub.publish(context.job_id, {"event_type": "TOOL_CALL_END", "tool": tool_name, "success": result.success})
