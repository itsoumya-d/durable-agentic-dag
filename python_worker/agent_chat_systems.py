"""Agent Chat & Multi-Turn System Runtime.

Production-grade agentic chat orchestration, conversation state management,
trajectory regression evaluation, and OpenTelemetry / Langfuse observability integration.
"""

from __future__ import annotations
import dataclasses
import enum
import hashlib
import json
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


class Role(str, enum.Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclasses.dataclass
class ToolDefinition:
    name: str
    description: str
    parameters_schema: Dict[str, Any]
    handler: Callable[[Dict[str, Any]], Dict[str, Any]]
    timeout_seconds: float = 5.0


@dataclasses.dataclass
class ToolCallRecord:
    call_id: str
    tool_name: str
    arguments: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0


@dataclasses.dataclass
class AgentMessage:
    role: Role
    content: str
    tool_calls: Optional[List[ToolCallRecord]] = None
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)
    timestamp: float = dataclasses.field(default_factory=time.time)

    def estimated_tokens(self) -> int:
        base = len(self.content) // 4 + 4
        if self.tool_calls:
            for tc in self.tool_calls:
                base += len(json.dumps(tc.arguments)) // 4 + 10
        return base


class ConversationStateManager:
    """Manages multi-turn conversation memory, sliding window budgeting, and state serialization."""

    def __init__(self, max_token_budget: int = 4096, max_retained_messages: int = 20):
        self.max_token_budget = max_token_budget
        self.max_retained_messages = max_retained_messages
        self.messages: List[AgentMessage] = []
        self.system_prompt: Optional[AgentMessage] = None
        self.compaction_summaries: List[str] = []

    def set_system_prompt(self, prompt: str) -> None:
        self.system_prompt = AgentMessage(role=Role.SYSTEM, content=prompt)

    def add_message(self, role: Role, content: str, tool_calls: Optional[List[ToolCallRecord]] = None, metadata: Optional[Dict[str, Any]] = None) -> None:
        msg = AgentMessage(role=role, content=content, tool_calls=tool_calls, metadata=metadata or {})
        self.messages.append(msg)
        self.prune_and_compact()

    def get_full_context(self) -> List[AgentMessage]:
        ctx: List[AgentMessage] = []
        if self.system_prompt:
            ctx.append(self.system_prompt)
        ctx.extend(self.messages)
        return ctx

    def total_tokens(self) -> int:
        tok = self.system_prompt.estimated_tokens() if self.system_prompt else 0
        tok += sum(m.estimated_tokens() for m in self.messages)
        return tok

    def prune_and_compact(self) -> None:
        """Prunes conversation to respect token budget while preserving recent user/assistant turns."""
        if len(self.messages) <= self.max_retained_messages and self.total_tokens() <= self.max_token_budget:
            return

        while len(self.messages) > 4 and (len(self.messages) > self.max_retained_messages or self.total_tokens() > self.max_token_budget):
            evicted = self.messages.pop(0)
            summary = f"[{evicted.role.value}] {evicted.content[:80]}"
            self.compaction_summaries.append(summary)

    def serialize(self) -> str:
        return json.dumps({
            "system_prompt": self.system_prompt.content if self.system_prompt else None,
            "messages": [
                {
                    "role": m.role.value,
                    "content": m.content,
                    "metadata": m.metadata,
                    "timestamp": m.timestamp,
                    "tool_calls": [
                        {
                            "call_id": tc.call_id,
                            "tool_name": tc.tool_name,
                            "arguments": tc.arguments,
                            "result": tc.result,
                            "error": tc.error,
                            "execution_time_ms": tc.execution_time_ms,
                        }
                        for tc in (m.tool_calls or [])
                    ] if m.tool_calls else None
                }
                for m in self.messages
            ],
            "compaction_summaries": self.compaction_summaries
        }, indent=2)

    @classmethod
    def deserialize(cls, raw: str) -> "ConversationStateManager":
        data = json.loads(raw)
        mgr = cls()
        if data.get("system_prompt"):
            mgr.set_system_prompt(data["system_prompt"])
        mgr.compaction_summaries = data.get("compaction_summaries", [])
        for m in data.get("messages", []):
            tc_list = None
            if m.get("tool_calls"):
                tc_list = [
                    ToolCallRecord(
                        call_id=tc["call_id"],
                        tool_name=tc["tool_name"],
                        arguments=tc["arguments"],
                        result=tc.get("result"),
                        error=tc.get("error"),
                        execution_time_ms=tc.get("execution_time_ms", 0.0)
                    )
                    for tc in m["tool_calls"]
                ]
            mgr.messages.append(AgentMessage(
                role=Role(m["role"]),
                content=m["content"],
                tool_calls=tc_list,
                metadata=m.get("metadata", {}),
                timestamp=m.get("timestamp", time.time())
            ))
        return mgr


class MultiTurnAgentOrchestrator:
    """Multi-turn agent loop with tool-calling schemas, cycle detection, and circuit breaking."""

    def __init__(self, state_manager: ConversationStateManager, max_iterations: int = 10):
        self.state_manager = state_manager
        self.max_iterations = max_iterations
        self.tools: Dict[str, ToolDefinition] = {}
        self.consecutive_failures: int = 0
        self.circuit_open: bool = False
        self.execution_spans: List[Dict[str, Any]] = []

    def register_tool(self, tool: ToolDefinition) -> None:
        self.tools[tool.name] = tool

    def execute_tool(self, name: str, args: Dict[str, Any]) -> ToolCallRecord:
        call_id = hashlib.sha256(f"{name}:{time.time()}:{json.dumps(args, sort_keys=True)}".encode()).hexdigest()[:12]
        rec = ToolCallRecord(call_id=call_id, tool_name=name, arguments=args)

        if self.circuit_open:
            rec.error = "CircuitBreakerOpen: Tool invocation rejected due to consecutive failures"
            return rec

        if name not in self.tools:
            rec.error = f"ToolNotFound: {name}"
            return rec

        tool = self.tools[name]
        t0 = time.perf_counter()
        try:
            res = tool.handler(args)
            dt_ms = (time.perf_counter() - t0) * 1000.0
            rec.result = res
            rec.execution_time_ms = round(dt_ms, 2)
            self.consecutive_failures = 0
        except Exception as e:
            dt_ms = (time.perf_counter() - t0) * 1000.0
            rec.error = str(e)
            rec.execution_time_ms = round(dt_ms, 2)
            self.consecutive_failures += 1
            if self.consecutive_failures >= 3:
                self.circuit_open = True
        return rec

    def run_turn(
        self,
        user_input: str,
        model_completion_fn: Callable[[List[AgentMessage]], Tuple[str, Optional[List[Dict[str, Any]]]]]
    ) -> Dict[str, Any]:
        """Runs an autonomous multi-step turn with tool-calling and cycle guardrails."""
        self.state_manager.add_message(Role.USER, user_input)
        call_signatures_seen: Set[str] = set()

        iterations = 0
        final_answer = ""
        trajectory: List[Dict[str, Any]] = []

        while iterations < self.max_iterations:
            iterations += 1
            ctx = self.state_manager.get_full_context()
            t0 = time.perf_counter()
            content, tool_requests = model_completion_fn(ctx)
            latency_ms = (time.perf_counter() - t0) * 1000.0

            self.execution_spans.append({
                "iteration": iterations,
                "type": "llm_completion",
                "latency_ms": round(latency_ms, 2),
                "has_tool_calls": bool(tool_requests)
            })

            if not tool_requests:
                final_answer = content
                self.state_manager.add_message(Role.ASSISTANT, content)
                trajectory.append({"step": iterations, "action": "final_response", "content": content})
                break

            # Execute tool requests
            executed_records: List[ToolCallRecord] = []
            for req in tool_requests:
                t_name = req["name"]
                t_args = req["arguments"]
                sig = f"{t_name}:{json.dumps(t_args, sort_keys=True)}"

                if sig in call_signatures_seen:
                    rec = ToolCallRecord(
                        call_id=hashlib.sha256(sig.encode()).hexdigest()[:12],
                        tool_name=t_name,
                        arguments=t_args,
                        error="CycleDetected: Duplicate tool call with identical arguments in single turn"
                    )
                else:
                    call_signatures_seen.add(sig)
                    rec = self.execute_tool(t_name, t_args)

                executed_records.append(rec)
                trajectory.append({
                    "step": iterations,
                    "action": "tool_call",
                    "tool": t_name,
                    "error": rec.error,
                    "result_present": rec.result is not None
                })

            self.state_manager.add_message(Role.ASSISTANT, content or "Invoking tools...", tool_calls=executed_records)

            for rec in executed_records:
                tool_msg_content = json.dumps(rec.result) if rec.result is not None else f"Error: {rec.error}"
                self.state_manager.add_message(Role.TOOL, tool_msg_content, metadata={"call_id": rec.call_id, "tool_name": rec.tool_name})

        return {
            "final_answer": final_answer,
            "iterations": iterations,
            "trajectory": trajectory,
            "circuit_breaker_active": self.circuit_open,
            "total_messages_in_state": len(self.state_manager.messages)
        }


class TrajectoryRegressionEvaluator:
    """Evaluates agent trajectory correctness, groundedness, and Goal Completion Rate."""

    @staticmethod
    def evaluate_groundedness(output: str, reference_documents: List[str]) -> float:
        if not reference_documents or not output:
            return 0.0

        out_words = set(output.lower().split())
        doc_words = set(" ".join(reference_documents).lower().split())
        if not out_words:
            return 0.0

        overlap = len(out_words.intersection(doc_words))
        return round(overlap / len(out_words), 4)

    @staticmethod
    def evaluate_gcr(trajectory: List[Dict[str, Any]], expected_terminal_action: str = "final_response") -> float:
        if not trajectory:
            return 0.0
        last = trajectory[-1]
        has_errors = any(step.get("error") for step in trajectory)
        if last.get("action") == expected_terminal_action and not has_errors:
            return 1.0
        elif last.get("action") == expected_terminal_action and has_errors:
            return 0.5
        return 0.0


class LangfuseObservabilityBridge:
    """Generates Langfuse/OpenTelemetry compliant execution traces and token/cost metrics."""

    def __init__(self, project_name: str = "kantiv-chat-agents"):
        self.project_name = project_name
        self.traces: List[Dict[str, Any]] = []

    def record_trace(
        self,
        session_id: str,
        user_prompt: str,
        result: Dict[str, Any],
        spans: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        trace_id = hashlib.sha256(f"{session_id}:{time.time()}".encode()).hexdigest()[:16]
        total_latency = sum(s.get("latency_ms", 0.0) for s in spans)

        trace = {
            "trace_id": trace_id,
            "project": self.project_name,
            "session_id": session_id,
            "prompt": user_prompt,
            "final_answer": result.get("final_answer"),
            "iterations": result.get("iterations"),
            "total_latency_ms": round(total_latency, 2),
            "spans_count": len(spans),
            "status": "SUCCESS" if result.get("final_answer") else "STALLED"
        }
        self.traces.append(trace)
        return trace
