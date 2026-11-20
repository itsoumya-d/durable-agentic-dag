import json
import unittest
from agent_chat_systems import (
    Role,
    ToolDefinition,
    ConversationStateManager,
    MultiTurnAgentOrchestrator,
    TrajectoryRegressionEvaluator,
    LangfuseObservabilityBridge,
)


class TestAgentChatSystems(unittest.TestCase):

    def setUp(self):
        self.state_mgr = ConversationStateManager(max_token_budget=300, max_retained_messages=6)
        self.state_mgr.set_system_prompt("You are an AEC proposal synthesis AI agent.")

    def test_state_manager_compaction_and_serialization(self):
        for i in range(10):
            role = Role.USER if i % 2 == 0 else Role.ASSISTANT
            self.state_mgr.add_message(role, f"Message content turn {i} with some extra tokens to fill budget.")

        self.assertLessEqual(len(self.state_mgr.messages), 6)
        self.assertTrue(len(self.state_mgr.compaction_summaries) > 0)

        # Serialization roundtrip
        raw = self.state_mgr.serialize()
        restored = ConversationStateManager.deserialize(raw)
        self.assertEqual(restored.system_prompt.content, "You are an AEC proposal synthesis AI agent.")
        self.assertEqual(len(restored.messages), len(self.state_mgr.messages))

    def test_multi_turn_orchestrator_tool_execution(self):
        orchestrator = MultiTurnAgentOrchestrator(self.state_mgr, max_iterations=5)

        def search_rfp_docs(args):
            query = args.get("query", "")
            return {"matches": [f"AEC Spec for {query}", "Compliance Clause 14.2"]}

        orchestrator.register_tool(ToolDefinition(
            name="search_rfp",
            description="Search previous AEC RFP archives",
            parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            handler=search_rfp_docs
        ))

        step_counter = 0

        def mock_llm(messages):
            nonlocal step_counter
            step_counter += 1
            if step_counter == 1:
                return "Searching previous RFP archives...", [{"name": "search_rfp", "arguments": {"query": "HVAC retrofitting"}}]
            else:
                return "Found compliance clause 14.2 for HVAC retrofitting.", None

        turn_result = orchestrator.run_turn("Synthesize HVAC RFP section", mock_llm)
        self.assertEqual(turn_result["iterations"], 2)
        self.assertIn("Found compliance clause", turn_result["final_answer"])
        self.assertFalse(turn_result["circuit_breaker_active"])

    def test_cycle_detection_guardrail(self):
        orchestrator = MultiTurnAgentOrchestrator(self.state_mgr, max_iterations=5)

        def dummy_tool(args):
            return {"status": "ok"}

        orchestrator.register_tool(ToolDefinition(
            name="dummy",
            description="dummy",
            parameters_schema={},
            handler=dummy_tool
        ))

        # Model requests identical tool call twice
        def looping_llm(messages):
            return "Looping...", [{"name": "dummy", "arguments": {"key": "val"}}]

        turn_result = orchestrator.run_turn("Trigger loop", looping_llm)
        # Should detect cycle and record error in trajectory
        cycle_errors = [step for step in turn_result["trajectory"] if step.get("error") and "CycleDetected" in step["error"]]
        self.assertTrue(len(cycle_errors) > 0)

    def test_circuit_breaker_on_consecutive_failures(self):
        orchestrator = MultiTurnAgentOrchestrator(self.state_mgr, max_iterations=6)

        def failing_tool(args):
            raise ConnectionResetError("Remote API timeout")

        orchestrator.register_tool(ToolDefinition(
            name="faulty",
            description="faulty tool",
            parameters_schema={},
            handler=failing_tool
        ))

        for i in range(3):
            rec = orchestrator.execute_tool("faulty", {"i": i})
            self.assertIsNotNone(rec.error)

        self.assertTrue(orchestrator.circuit_open)
        rec4 = orchestrator.execute_tool("faulty", {"i": 4})
        self.assertIn("CircuitBreakerOpen", rec4.error)

    def test_trajectory_evaluator_and_groundedness(self):
        ref_docs = ["Kantiv builds intelligent proposal automation for architectural and engineering firms."]
        ans = "Kantiv builds intelligent proposal automation"
        score = TrajectoryRegressionEvaluator.evaluate_groundedness(ans, ref_docs)
        self.assertGreater(score, 0.8)

        trajectory_success = [{"step": 1, "action": "tool_call"}, {"step": 2, "action": "final_response"}]
        gcr = TrajectoryRegressionEvaluator.evaluate_gcr(trajectory_success)
        self.assertEqual(gcr, 1.0)

    def test_observability_bridge_trace(self):
        bridge = LangfuseObservabilityBridge("aec-chat-test")
        trace = bridge.record_trace(
            session_id="sess-1234",
            user_prompt="Explain structural engineering compliance",
            result={"final_answer": "Structural compliance verified", "iterations": 2},
            spans=[{"latency_ms": 120.5}, {"latency_ms": 45.2}]
        )
        self.assertEqual(trace["status"], "SUCCESS")
        self.assertEqual(trace["total_latency_ms"], 165.7)
        self.assertEqual(len(bridge.traces), 1)


if __name__ == "__main__":
    unittest.main()
