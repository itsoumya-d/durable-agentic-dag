"""Unit and regression tests for PaymentReconciliationPipeline."""

import unittest
from datetime import datetime, timezone

try:
    from payment_reconciliation_pipeline import (
        DimensionalTransactionFact,
        GatewayEvent, PaymentEvent,
        GatewayProvider,
        NormalizedTransaction,
        PaymentReconciliationPipeline,
        ReconciliationStatus,
        SettlementBatch,
        TransactionStatus,
        mask_identifier,
    )
except ImportError:
    from python_worker.payment_reconciliation_pipeline import (
        DimensionalTransactionFact,
        GatewayEvent, PaymentEvent,
        GatewayProvider,
        NormalizedTransaction,
        PaymentReconciliationPipeline,
        ReconciliationStatus,
        SettlementBatch,
        TransactionStatus,
        mask_identifier,
    )


class TestPaymentReconciliationPipeline(unittest.TestCase):
    def setUp(self) -> None:
        self.pipeline = PaymentReconciliationPipeline(fee_tolerance_cents=5, salt="test_salt_123")
        self.now = datetime.now(timezone.utc)

    def test_mask_identifier_deterministic_and_obfuscated(self) -> None:
        raw_email = "shopper_berlin@example.com"
        masked1 = mask_identifier(raw_email, salt="test_salt_123")
        masked2 = mask_identifier(raw_email, salt="test_salt_123")
        masked_diff_salt = mask_identifier(raw_email, salt="other_salt_456")

        self.assertTrue(masked1.startswith("id_hmac_"))
        self.assertEqual(masked1, masked2)
        self.assertNotEqual(masked1, masked_diff_salt)
        self.assertNotIn("example.com", masked1)

    def test_normalize_stripe_payload(self) -> None:
        event = PaymentEvent(
            event_id="evt_stripe_101",
            gateway=GatewayProvider.STRIPE,
            event_type="payment_intent.succeeded",
            timestamp=self.now,
            raw_payload={
                "id": "pi_3N998877",
                "merchant_id": "merch_berlin_tech",
                "amount": 15000,
                "currency": "eur",
                "status": "succeeded",
                "fee": 250,
                "customer_email": "payer@berlin.de"
            }
        )

        tx = self.pipeline.normalize_event(event)
        self.assertEqual(tx.transaction_id, "pi_3N998877")
        self.assertEqual(tx.merchant_id, "merch_berlin_tech")
        self.assertEqual(tx.amount_cents, 15000)
        self.assertEqual(tx.currency, "EUR")
        self.assertEqual(tx.status, TransactionStatus.CAPTURED)
        self.assertEqual(tx.fee_cents, 250)
        self.assertTrue(tx.anonymized_payer_ref.startswith("id_hmac_"))

    def test_normalize_adyen_payload(self) -> None:
        event = PaymentEvent(
            event_id="evt_adyen_202",
            gateway=GatewayProvider.ADYEN,
            event_type="AUTHORISATION",
            timestamp=self.now,
            raw_payload={
                "id": "adyen_psp_445566",
                "merchant_id": "merch_berlin_tech",
                "value": 8500,
                "currency": "EUR",
                "status": "authorized",
                "shopper_reference": "cust_uuid_99"
            }
        )

        tx = self.pipeline.normalize_event(event)
        self.assertEqual(tx.transaction_id, "adyen_psp_445566")
        self.assertEqual(tx.amount_cents, 8500)
        self.assertEqual(tx.status, TransactionStatus.AUTHORIZED)

    def test_reconcile_exact_settlement_match(self) -> None:
        tx = NormalizedTransaction(
            transaction_id="tx_rec_001",
            merchant_id="merch_01",
            gateway=GatewayProvider.STRIPE,
            amount_cents=10000,
            currency="EUR",
            status=TransactionStatus.CAPTURED,
            created_at=self.now,
            fee_cents=150
        )

        batch = SettlementBatch(
            settlement_id="stl_batch_001",
            gateway=GatewayProvider.STRIPE,
            batch_reference="BATCH-EUR-01",
            settled_at=self.now,
            gross_amount_cents=10000,
            net_amount_cents=9850,
            fee_amount_cents=150,
            transaction_ids=["tx_rec_001"]
        )

        results, metrics = self.pipeline.reconcile_transactions([tx], [batch])
        self.assertEqual(metrics["matched_exact"], 1)
        self.assertEqual(metrics["discrepancies"], 0)
        self.assertEqual(results[0].status, ReconciliationStatus.MATCHED)

    def test_reconcile_missing_settlement_detected(self) -> None:
        tx = NormalizedTransaction(
            transaction_id="tx_unsettled_002",
            merchant_id="merch_01",
            gateway=GatewayProvider.CHECKOUT,
            amount_cents=5000,
            currency="EUR",
            status=TransactionStatus.CAPTURED,
            created_at=self.now,
            fee_cents=75
        )

        results, metrics = self.pipeline.reconcile_transactions([tx], [])
        self.assertEqual(metrics["missing_settlements"], 1)
        self.assertEqual(metrics["discrepancies"], 1)
        self.assertEqual(results[0].status, ReconciliationStatus.MISSING_SETTLEMENT)
        self.assertEqual(results[0].difference_cents, 5000)

    def test_reconcile_fee_variance_detected(self) -> None:
        tx = NormalizedTransaction(
            transaction_id="tx_fee_diff_003",
            merchant_id="merch_01",
            gateway=GatewayProvider.STRIPE,
            amount_cents=20000,
            currency="EUR",
            status=TransactionStatus.CAPTURED,
            created_at=self.now,
            fee_cents=200
        )

        batch = SettlementBatch(
            settlement_id="stl_batch_002",
            gateway=GatewayProvider.STRIPE,
            batch_reference="BATCH-EUR-02",
            settled_at=self.now,
            gross_amount_cents=20000,
            net_amount_cents=19500,
            fee_amount_cents=500,
            transaction_ids=["tx_fee_diff_003"]
        )

        results, metrics = self.pipeline.reconcile_transactions([tx], [batch])
        self.assertEqual(metrics["fee_variances"], 1)
        self.assertEqual(results[0].status, ReconciliationStatus.FEE_VARIANCE)
        self.assertEqual(results[0].difference_cents, 300)

    def test_dimensional_fact_generation_and_quality_gates(self) -> None:
        tx = NormalizedTransaction(
            transaction_id="tx_fact_004",
            merchant_id="merch_01",
            gateway=GatewayProvider.STRIPE,
            amount_cents=12000,
            currency="EUR",
            status=TransactionStatus.CAPTURED,
            created_at=self.now,
            fee_cents=180
        )

        batch = SettlementBatch(
            settlement_id="stl_batch_003",
            gateway=GatewayProvider.STRIPE,
            batch_reference="BATCH-EUR-03",
            settled_at=self.now,
            gross_amount_cents=12000,
            net_amount_cents=11820,
            fee_amount_cents=180,
            transaction_ids=["tx_fact_004"]
        )

        results, _ = self.pipeline.reconcile_transactions([tx], [batch])
        facts = self.pipeline.build_dimensional_facts([tx], results)

        self.assertEqual(len(facts), 1)
        f = facts[0]
        self.assertEqual(f.gross_cents, 12000)
        self.assertEqual(f.fee_cents, 180)
        self.assertEqual(f.net_cents, 11820)
        self.assertTrue(f.is_settled)
        self.assertEqual(f.reconciled_status, "matched")

        # Quality assertion gate pass
        gate_res = self.pipeline.run_quality_assertion_gate(facts)
        self.assertTrue(gate_res["passed"])
        self.assertEqual(gate_res["violation_count"], 0)

    def test_quality_assertion_gate_flags_anomalies(self) -> None:
        bad_fact = DimensionalTransactionFact(
            fact_id="fact_anomaly_1",
            transaction_id="tx_bad_01",
            merchant_id="merch_01",
            gateway_name="stripe",
            gross_cents=-500,
            fee_cents=50,
            net_cents=-550,
            currency="EUR",
            is_settled=False,
            reconciled_status="unreconciled",
            event_timestamp=self.now
        )

        gate_res = self.pipeline.run_quality_assertion_gate([bad_fact])
        self.assertFalse(gate_res["passed"])
        self.assertGreater(gate_res["violation_count"], 0)


if __name__ == "__main__":
    unittest.main()
