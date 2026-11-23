import unittest
from python_worker.gtm_agent_evaluator import GTMAgentEvaluator, CallSignal, CallPrepBriefing, AgentGradingRubric


class TestGTMAgentEvaluator(unittest.TestCase):
    def setUp(self):
        self.sample_transcript = (
            "We had a sync with the VP of Engineering yesterday. "
            "They mentioned budget of $75,000 is approved for Q3. "
            "However, the team is frustrated with current manual work and latency bottlenecks. "
            "They are also evaluating an alternative competitor vendor if we cannot deliver on time."
        )

    def test_synthesize_call_signals(self):
        briefing = GTMAgentEvaluator.synthesize_call_signals(
            account_id="acct_84920",
            opportunity_stage="Technical Evaluation",
            transcript_text=self.sample_transcript,
        )

        self.assertIsInstance(briefing, CallPrepBriefing)
        self.assertEqual(briefing.account_id, "acct_84920")
        self.assertEqual(briefing.opportunity_stage, "Technical Evaluation")
        self.assertGreater(len(briefing.key_signals), 0)

        signal_types = {s.signal_type for s in briefing.key_signals}
        self.assertIn("budget", signal_types)
        self.assertIn("decision_maker", signal_types)
        self.assertIn("pain_point", signal_types)
        self.assertIn("competitor", signal_types)

        self.assertGreaterEqual(briefing.deal_health_score, 0.0)
        self.assertLessEqual(briefing.deal_health_score, 1.0)
        self.assertGreater(len(briefing.suggested_action_items), 0)

    def test_grade_agent_draft_grounded(self):
        ground_truth = (
            "Customer VP of Engineering approved $75,000 budget. "
            "High priority on latency reduction and automated pipeline execution."
        )
        draft = (
            "Hello, following up on our discussion regarding latency reduction "
            "and automated pipeline execution within your approved budget. "
            "Would you like to schedule a call next week?"
        )

        rubric = GTMAgentEvaluator.grade_agent_draft(draft, ground_truth, min_pass_score=0.75)
        self.assertIsInstance(rubric, AgentGradingRubric)
        self.assertFalse(rubric.hallucination_detected)
        self.assertTrue(rubric.passed)
        self.assertGreaterEqual(rubric.composite_quality_score, 0.75)

    def test_grade_agent_draft_hallucination_or_unrelated(self):
        ground_truth = "We only sell standard database backup services in North America."
        draft = "We provide quantum orbital satellite propulsion systems across Jupiter."

        rubric = GTMAgentEvaluator.grade_agent_draft(draft, ground_truth, min_pass_score=0.80)
        self.assertTrue(rubric.hallucination_detected)
        self.assertFalse(rubric.passed)

    def test_enforce_hitl_guardrail(self):
        passing_rubric = AgentGradingRubric(
            factuality_score=0.95,
            tone_alignment_score=0.90,
            actionability_score=0.95,
            composite_quality_score=0.93,
            hallucination_detected=False,
            passed=True,
            audit_trace="Pass",
        )
        decision_pass = GTMAgentEvaluator.enforce_hitl_guardrail(passing_rubric)
        self.assertEqual(decision_pass["decision"], "auto_send")
        self.assertFalse(decision_pass["requires_human_approval"])

        failing_rubric = AgentGradingRubric(
            factuality_score=0.30,
            tone_alignment_score=0.70,
            actionability_score=0.50,
            composite_quality_score=0.45,
            hallucination_detected=True,
            passed=False,
            audit_trace="Fail",
        )
        decision_fail = GTMAgentEvaluator.enforce_hitl_guardrail(failing_rubric)
        self.assertEqual(decision_fail["decision"], "route_to_rep_review")
        self.assertTrue(decision_fail["requires_human_approval"])


if __name__ == "__main__":
    unittest.main()
