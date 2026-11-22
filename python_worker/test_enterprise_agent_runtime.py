"""Unit and integration tests for EnterpriseAgentRuntime and ERPPolicyRuleEngine."""

import unittest
from python_worker.enterprise_agent_runtime import EnterpriseAgentRuntime, ERPPolicyRuleEngine, PolicyRule


class TestEnterpriseAgentRuntime(unittest.TestCase):

    def setUp(self):
        self.policy_engine = ERPPolicyRuleEngine()
        self.runtime = EnterpriseAgentRuntime(self.policy_engine)

    def test_approved_transaction_workflow(self):
        payload = {
            "vendor_id": "VEND-1001",
            "vendor_status": "ACTIVE_VERIFIED",
            "amount": 12500.0,
            "currency": "USD",
            "dual_approved": False
        }
        res = self.runtime.execute_procurement_workflow(payload)
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "COMMITTED")
        self.assertIn("PO-", res["erp_doc_id"])
        self.assertFalse(res["cached"])

        # Test idempotency caching
        cached_res = self.runtime.execute_procurement_workflow(payload)
        self.assertTrue(cached_res["cached"])
        self.assertEqual(cached_res["idempotency_key"], res["idempotency_key"])

    def test_policy_escalation_on_high_value(self):
        payload = {
            "vendor_id": "VEND-1002",
            "vendor_status": "ACTIVE_VERIFIED",
            "amount": 75000.0,  # exceeds $50k threshold
            "currency": "USD",
            "dual_approved": False
        }
        res = self.runtime.execute_procurement_workflow(payload)
        self.assertFalse(res["success"])
        self.assertTrue(res["escalate"])
        self.assertEqual(res["status"], "REQUIRES_HUMAN_ESCALATION")
        self.assertEqual(len(res["violations"]), 1)
        self.assertEqual(res["violations"][0]["rule_id"], "POL-001")

    def test_policy_blocking_on_unverified_vendor(self):
        payload = {
            "vendor_id": "VEND-SUSPECT",
            "vendor_status": "PENDING_AUDIT",
            "amount": 5000.0,
            "currency": "USD",
            "dual_approved": False
        }
        res = self.runtime.execute_procurement_workflow(payload)
        self.assertFalse(res["success"])
        self.assertFalse(res["escalate"])
        self.assertEqual(res["status"], "REJECTED_BY_POLICY")
        self.assertEqual(res["violations"][0]["rule_id"], "POL-002")

    def test_execution_trace_provenance(self):
        payload = {
            "vendor_id": "VEND-1003",
            "vendor_status": "ACTIVE_VERIFIED",
            "amount": 2400.0,
            "currency": "USD",
            "dual_approved": False
        }
        self.runtime.execute_procurement_workflow(payload)
        self.assertEqual(len(self.runtime.execution_traces), 1)
        trace = self.runtime.execution_traces[0]
        self.assertEqual(trace.agent_id, "agent:procurement_lead_v1")
        self.assertEqual(len(trace.tool_calls), 2)
        self.assertEqual(trace.tool_calls[0].tool_name, "policy_engine.evaluate")
        self.assertEqual(trace.tool_calls[1].tool_name, "erp_gateway.post_purchase_order")


if __name__ == "__main__":
    unittest.main()
