import unittest
from python_worker.workflow_queue_broker import WorkflowQueueBroker


class TestWorkflowQueueBroker(unittest.TestCase):
    def setUp(self):
        self.broker = WorkflowQueueBroker(base_retry_delay_seconds=2.0, max_retry_delay_seconds=30.0)

    def test_enqueue_and_priority_leasing(self):
        self.broker.enqueue("wf_1", "stage_a", {"val": 1}, priority=5, current_epoch=100.0)
        self.broker.enqueue("wf_2", "stage_b", {"val": 2}, priority=20, current_epoch=101.0)
        self.broker.enqueue("wf_3", "stage_c", {"val": 3}, priority=10, current_epoch=102.0)

        leased = self.broker.lease_batch(max_batch_size=2, current_epoch=105.0)
        self.assertEqual(len(leased), 2)
        self.assertEqual(leased[0].workflow_id, "wf_2")  # priority 20
        self.assertEqual(leased[1].workflow_id, "wf_3")  # priority 10
        self.assertEqual(leased[0].state, "in_flight")
        self.assertEqual(leased[1].state, "in_flight")

    def test_idempotency_deduplication(self):
        msg1 = self.broker.enqueue("wf_1", "ingest", {"step": 1}, idempotency_key="idempotent_key_abc")
        msg2 = self.broker.enqueue("wf_1", "ingest", {"step": 1}, idempotency_key="idempotent_key_abc")

        self.assertEqual(msg1.message_id, msg2.message_id)
        metrics = self.broker.get_metrics()
        self.assertEqual(metrics["total"], 1)

    def test_acknowledge_completed_flow(self):
        msg = self.broker.enqueue("wf_1", "stage_a", {"key": "data"})
        self.broker.lease_batch(max_batch_size=1)
        ok = self.broker.acknowledge(msg.message_id)

        self.assertTrue(ok)
        metrics = self.broker.get_metrics()
        self.assertEqual(metrics["completed"], 1)
        self.assertEqual(metrics["in_flight"], 0)

    def test_exponential_backoff_and_dlq_routing(self):
        msg = self.broker.enqueue("wf_1", "compute", {"val": 10}, max_retries=3, current_epoch=100.0)
        leased = self.broker.lease_batch(max_batch_size=1, current_epoch=100.0)
        self.assertEqual(len(leased), 1)

        # Attempt 1 fail -> delay = 2.0 * (2^0) = 2.0 -> backoff until 102.0
        retried1 = self.broker.fail_and_retry(msg.message_id, "transient network glitch", current_epoch=100.0)
        self.assertEqual(retried1.attempt_count, 1)
        self.assertEqual(retried1.state, "queued")
        self.assertEqual(retried1.backoff_until_epoch, 102.0)

        # Before backoff expires, lease returns nothing
        self.assertEqual(len(self.broker.lease_batch(max_batch_size=1, current_epoch=101.0)), 0)

        # After backoff expires, lease succeeds
        leased2 = self.broker.lease_batch(max_batch_size=1, current_epoch=103.0)
        self.assertEqual(len(leased2), 1)

        # Attempt 2 fail -> delay = 2.0 * (2^1) = 4.0 -> backoff until 107.0
        self.broker.fail_and_retry(msg.message_id, "downstream timeout", current_epoch=103.0)
        self.broker.lease_batch(max_batch_size=1, current_epoch=108.0)

        # Attempt 3 fail -> max_retries reached -> dead lettered
        retried3 = self.broker.fail_and_retry(msg.message_id, "fatal schema drift", current_epoch=108.0)
        self.assertEqual(retried3.state, "dead_lettered")
        self.assertEqual(retried3.attempt_count, 3)

        metrics = self.broker.get_metrics()
        self.assertEqual(metrics["dead_lettered"], 1)

        # Reprocess DLQ recovers message
        reprocessed = self.broker.reprocess_dlq(msg.message_id)
        self.assertEqual(reprocessed, 1)
        self.assertEqual(self.broker.get_metrics()["queued"], 1)


if __name__ == "__main__":
    unittest.main()
