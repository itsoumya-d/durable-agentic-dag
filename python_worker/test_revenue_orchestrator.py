"""Unit tests for RevenueAgentWorkflow, durable checkpoints, and guardrails."""

import unittest
from revenue_orchestrator import GuardrailResult, RevenueAgentWorkflow, WorkflowCheckpoint


class TestRevenueOrchestrator(unittest.TestCase):

    def test_full_successful_workflow_execution(self):
        workflow = RevenueAgentWorkflow(workflow_id="wf-pe-101")
        sample_contract = """
        Master Services Agreement
        Account: Acme Corp
        ARR: $1,250,000.00
        Terms: Net 30, Multi-Year
        """

        # Step 1: Ingestion
        cp1 = workflow.ingest_contract(sample_contract, account_id="acct-acme-1")
        self.assertIn("ingest_contract", cp1.completed_steps)
        self.assertEqual(cp1.state["extracted_arr"], 1250000.0)
        self.assertGreater(cp1.total_tokens, 0)
        self.assertGreater(cp1.total_cost_usd, 0.0)

        # Step 2: Guardrails
        guard = workflow.evaluate_guardrails(min_confidence=0.8)
        self.assertTrue(guard.passed)
        self.assertEqual(guard.reason, "All guardrails passed")
        self.assertIn("evaluate_guardrails", workflow.checkpoint.completed_steps)

        # Step 3: Billing reconciliation
        cp2 = workflow.reconcile_billing(billed_arr=1200000.0)
        self.assertIn("reconcile_billing", cp2.completed_steps)
        self.assertEqual(cp2.state["arr_variance"], 50000.0)
        self.assertTrue(cp2.state["needs_adjustment"])

        # Step 4: Webhook dispatch
        dispatched_payloads = []
        def mock_webhook(url, payload):
            dispatched_payloads.append((url, payload))
            return True

        workflow.webhook_client = mock_webhook
        ok = workflow.dispatch_webhook("https://api.portfolio.com/webhook", secret_key="secret-123")
        self.assertTrue(ok)
        self.assertEqual(len(dispatched_payloads), 1)
        self.assertIn("signature", dispatched_payloads[0][1])
        self.assertEqual(workflow.checkpoint.current_step, "COMPLETED")

    def test_checkpoint_serialization_and_idempotent_resume(self):
        wf1 = RevenueAgentWorkflow(workflow_id="wf-resume-202")
        sample_contract = "ARR: $500,000.00\nTerms: Annual"
        wf1.ingest_contract(sample_contract, account_id="acct-resume")
        saved_json = wf1.checkpoint.to_json()

        # Resume in a fresh instance
        restored_cp = WorkflowCheckpoint.from_json(saved_json)
        wf2 = RevenueAgentWorkflow(workflow_id="wf-resume-202", checkpoint=restored_cp)

        # Re-running ingest_contract should skip execution idempotently
        tokens_before = wf2.checkpoint.total_tokens
        wf2.ingest_contract(sample_contract, account_id="acct-resume")
        self.assertEqual(wf2.checkpoint.total_tokens, tokens_before)

        # Continue from step 2
        guard = wf2.evaluate_guardrails()
        self.assertTrue(guard.passed)
        self.assertEqual(wf2.checkpoint.current_step, "reconcile_billing")

    def test_guardrail_escalation_on_low_confidence(self):
        workflow = RevenueAgentWorkflow(workflow_id="wf-unclear-303")
        unclear_doc = "Unstructured meeting notes without clear dollar numbers."
        workflow.ingest_contract(unclear_doc, account_id="acct-unclear")

        guard = workflow.evaluate_guardrails(min_confidence=0.85)
        self.assertFalse(guard.passed)
        self.assertTrue(guard.escalation_required)
        self.assertEqual(workflow.checkpoint.state["guardrail_status"], "ESCALATED")

    def test_webhook_retry_resilience(self):
        attempts = 0
        def flaky_webhook(url, payload):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ConnectionError("Transient timeout")
            return True

        workflow = RevenueAgentWorkflow(workflow_id="wf-retry-404", webhook_client=flaky_webhook)
        sample = "ARR: $200,000.00\nTerms: Annual"
        workflow.ingest_contract(sample, account_id="acct-retry")
        workflow.evaluate_guardrails()
        workflow.reconcile_billing(billed_arr=200000.0)

        ok = workflow.dispatch_webhook("https://api.crm.com/v1/event", secret_key="test-key", max_retries=3)
        self.assertTrue(ok)
        self.assertEqual(attempts, 3)
        self.assertTrue(workflow.checkpoint.state["webhook_dispatched"])


if __name__ == "__main__":
    unittest.main()
