"""
Unit tests for Fintech MCP Server & Automated Workflow Engine.
Validates tool registration, schema conformance, dispute triage,
deterministic policy guardrails, and audit logging.
"""

import json
import unittest
from python_worker.fintech_mcp_server import FintechMCPServer


class TestFintechMCPServer(unittest.TestCase):
    def setUp(self):
        self.server = FintechMCPServer()

    def test_list_tools_conformance(self):
        tools = self.server.list_tools()
        names = [t["name"] for t in tools]
        self.assertIn("query_sme_transactions", names)
        self.assertIn("triage_cardholder_dispute", names)
        self.assertIn("evaluate_credit_policy_guardrail", names)
        self.assertIn("escalate_case_to_ops", names)
        self.assertEqual(len(tools), 4)

    def test_query_sme_transactions(self):
        res = self.server.call_tool("query_sme_transactions", {"account_id": "acc_sme_987", "limit": 2})
        self.assertFalse(res["isError"])
        data = json.loads(res["content"][0]["text"])
        self.assertEqual(data["account_id"], "acc_sme_987")
        self.assertEqual(len(data["transactions"]), 2)
        self.assertGreater(data["total_count"], 0)

    def test_triage_dispute_low_risk_auto_refund(self):
        payload = {
            "transaction_id": "tx_london_101",
            "dispute_reason": "unauthorized card transaction detected",
            "amount": 85.50,
            "cardholder_tenure_months": 18
        }
        res = self.server.call_tool("triage_cardholder_dispute", payload)
        self.assertFalse(res["isError"])
        data = json.loads(res["content"][0]["text"])
        self.assertEqual(data["decision"], "AUTO_REFUND_PROVISIONAL")
        self.assertFalse(data["escalation_needed"])
        self.assertEqual(data["provisional_credit_gbp"], 85.50)
        self.assertGreaterEqual(data["confidence"], 0.90)

    def test_triage_dispute_high_value_escalates(self):
        payload = {
            "transaction_id": "tx_london_999",
            "dispute_reason": "unrecognized payment",
            "amount": 2500.00,
            "cardholder_tenure_months": 2
        }
        res = self.server.call_tool("triage_cardholder_dispute", payload)
        self.assertFalse(res["isError"])
        data = json.loads(res["content"][0]["text"])
        self.assertEqual(data["decision"], "REQUIRE_MANUAL_REVIEW")
        self.assertTrue(data["escalation_needed"])
        self.assertEqual(data["provisional_credit_gbp"], 0.0)

    def test_credit_policy_guardrail_pass_and_fail(self):
        # Pass low risk tier increase
        res_pass = self.server.call_tool("evaluate_credit_policy_guardrail", {
            "account_id": "acc_sme_1",
            "requested_limit_increase": 15000.0,
            "risk_tier": "LOW"
        })
        data_pass = json.loads(res_pass["content"][0]["text"])
        self.assertTrue(data_pass["guardrail_passed"])
        self.assertIsNone(data_pass["rejection_reason"])

        # Fail high risk tier excessive increase
        res_fail = self.server.call_tool("evaluate_credit_policy_guardrail", {
            "account_id": "acc_sme_2",
            "requested_limit_increase": 8000.0,
            "risk_tier": "HIGH"
        })
        data_fail = json.loads(res_fail["content"][0]["text"])
        self.assertFalse(data_fail["guardrail_passed"])
        self.assertIn("exceeds HIGH risk cap", data_fail["rejection_reason"])

    def test_escalate_case_to_ops(self):
        res = self.server.call_tool("escalate_case_to_ops", {
            "case_id": "case_fraud_404",
            "priority": "P1",
            "reason": "Anomalous velocity spike across multi-currency corporate cards"
        })
        self.assertFalse(res["isError"])
        data = json.loads(res["content"][0]["text"])
        self.assertEqual(data["priority"], "P1")
        self.assertEqual(data["sla_target_hours"], 1)
        self.assertEqual(data["routed_queue"], "fintech_ops_p1")

    def test_resources_read_and_missing(self):
        resources = self.server.list_resources()
        self.assertEqual(len(resources), 2)
        r = self.server.read_resource("fintech://playbooks/sme_spend_policy")
        self.assertEqual(r["content"]["auto_dispute_threshold_gbp"], 150.00)

        with self.assertRaises(KeyError):
            self.server.read_resource("fintech://playbooks/non_existent")

    def test_audit_logging_and_validation(self):
        # Invalid missing required parameter
        with self.assertRaises(ValueError):
            self.server.call_tool("query_sme_transactions", {})

        # Successful tool call appends audit record
        self.server.call_tool("query_sme_transactions", {"account_id": "acc_audit_test"})
        self.assertGreaterEqual(len(self.server.audit_log), 1)
        last_log = self.server.audit_log[-1]
        self.assertEqual(last_log["tool"], "query_sme_transactions")
        self.assertEqual(last_log["status"], "SUCCESS")
        self.assertIn("duration_ms", last_log)


if __name__ == "__main__":
    unittest.main()
