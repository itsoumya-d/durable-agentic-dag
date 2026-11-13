"""Multi-step agentic revenue workflow orchestrator with durable checkpoints and guardrails."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class StepStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ESCALATED = "ESCALATED"


@dataclass
class WorkflowCheckpoint:
    workflow_id: str
    current_step: str
    completed_steps: List[str] = field(default_factory=list)
    state: Dict[str, Any] = field(default_factory=dict)
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    updated_at: float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str) -> "WorkflowCheckpoint":
        raw = json.loads(data)
        return cls(**raw)


@dataclass
class GuardrailResult:
    passed: bool
    confidence_score: float
    reason: str
    escalation_required: bool = False


class RevenueAgentWorkflow:
    """Production-grade agentic workflow for private equity revenue operations and contract audits."""

    def __init__(
        self,
        workflow_id: str,
        checkpoint: Optional[WorkflowCheckpoint] = None,
        webhook_client: Optional[Callable[[str, Dict[str, Any]], bool]] = None,
    ) -> None:
        self.workflow_id = workflow_id
        self.checkpoint = checkpoint or WorkflowCheckpoint(
            workflow_id=workflow_id,
            current_step="ingest_contract",
        )
        self.webhook_client = webhook_client or self._default_webhook_client
        self.step_history: List[Dict[str, Any]] = []

    def _default_webhook_client(self, url: str, payload: Dict[str, Any]) -> bool:
        return True

    def ingest_contract(self, raw_text: str, account_id: str) -> WorkflowCheckpoint:
        """Step 1: Extract ARR, contract start date, and terms from unstructured text."""
        if "ingest_contract" in self.checkpoint.completed_steps:
            return self.checkpoint

        self.checkpoint.current_step = "ingest_contract"
        # Deterministic extraction logic simulating frontier LLM schema extraction
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        arr_val = 0.0
        contract_terms = "standard"

        for line in lines:
            if "ARR:" in line:
                try:
                    val_str = line.split("ARR:")[1].strip().replace("$", "").replace(",", "")
                    arr_val = float(val_str)
                except ValueError:
                    arr_val = 0.0
            elif "Terms:" in line:
                contract_terms = line.split("Terms:")[1].strip()

        # Attribute tokens and cost
        tokens = len(raw_text.split()) + 64
        cost = (tokens / 1000.0) * 0.003

        self.checkpoint.state["account_id"] = account_id
        self.checkpoint.state["extracted_arr"] = arr_val
        self.checkpoint.state["contract_terms"] = contract_terms
        self.checkpoint.state["extraction_confidence"] = 0.95 if arr_val > 0 else 0.40
        self.checkpoint.total_tokens += tokens
        self.checkpoint.total_cost_usd += round(cost, 6)
        self.checkpoint.completed_steps.append("ingest_contract")
        self.checkpoint.current_step = "evaluate_guardrails"
        self.checkpoint.updated_at = time.time()
        return self.checkpoint

    def evaluate_guardrails(self, min_confidence: float = 0.80) -> GuardrailResult:
        """Step 2: Guardrail check on extraction confidence and ARR sanity bounds."""
        confidence = float(self.checkpoint.state.get("extraction_confidence", 0.0))
        arr = float(self.checkpoint.state.get("extracted_arr", 0.0))

        if confidence < min_confidence:
            res = GuardrailResult(
                passed=False,
                confidence_score=confidence,
                reason=f"Extraction confidence {confidence:.2f} is below required threshold {min_confidence:.2f}",
                escalation_required=True,
            )
            self.checkpoint.state["guardrail_status"] = "ESCALATED"
            return res

        if arr <= 0 or arr > 50_000_000:
            res = GuardrailResult(
                passed=False,
                confidence_score=confidence,
                reason=f"ARR value ${arr:,.2f} outside expected operational bounds ($0 - $50M)",
                escalation_required=True,
            )
            self.checkpoint.state["guardrail_status"] = "ESCALATED"
            return res

        res = GuardrailResult(passed=True, confidence_score=confidence, reason="All guardrails passed")
        self.checkpoint.state["guardrail_status"] = "PASSED"
        if "evaluate_guardrails" not in self.checkpoint.completed_steps:
            self.checkpoint.completed_steps.append("evaluate_guardrails")
        self.checkpoint.current_step = "reconcile_billing"
        self.checkpoint.updated_at = time.time()
        return res

    def reconcile_billing(self, billed_arr: float) -> WorkflowCheckpoint:
        """Step 3: Reconcile contracted ARR with actual ERP/billing data."""
        if "reconcile_billing" in self.checkpoint.completed_steps:
            return self.checkpoint

        self.checkpoint.current_step = "reconcile_billing"
        contracted_arr = float(self.checkpoint.state.get("extracted_arr", 0.0))
        variance = contracted_arr - billed_arr
        variance_pct = (variance / contracted_arr) if contracted_arr > 0 else 0.0

        self.checkpoint.state["billed_arr"] = billed_arr
        self.checkpoint.state["arr_variance"] = variance
        self.checkpoint.state["arr_variance_pct"] = round(variance_pct, 4)
        self.checkpoint.state["needs_adjustment"] = abs(variance) > 100.0

        self.checkpoint.completed_steps.append("reconcile_billing")
        self.checkpoint.current_step = "dispatch_webhook"
        self.checkpoint.updated_at = time.time()
        return self.checkpoint

    def dispatch_webhook(
        self,
        webhook_url: str,
        secret_key: str,
        max_retries: int = 3,
    ) -> bool:
        """Step 4: Dispatch HMAC-signed notification to CRM/portfolio dashboard."""
        if "dispatch_webhook" in self.checkpoint.completed_steps:
            return True

        self.checkpoint.current_step = "dispatch_webhook"
        payload = {
            "workflow_id": self.workflow_id,
            "account_id": self.checkpoint.state.get("account_id"),
            "extracted_arr": self.checkpoint.state.get("extracted_arr"),
            "billed_arr": self.checkpoint.state.get("billed_arr"),
            "variance": self.checkpoint.state.get("arr_variance"),
            "timestamp": int(time.time()),
        }

        # Calculate HMAC signature
        raw_body = json.dumps(payload, sort_keys=True)
        sig = hmac.new(secret_key.encode("utf-8"), raw_body.encode("utf-8"), hashlib.sha256).hexdigest()
        payload["signature"] = sig

        success = False
        for attempt in range(1, max_retries + 1):
            try:
                if self.webhook_client(webhook_url, payload):
                    success = True
                    break
            except Exception:
                time.sleep(0.01 * attempt)

        if success:
            self.checkpoint.state["webhook_dispatched"] = True
            self.checkpoint.completed_steps.append("dispatch_webhook")
            self.checkpoint.current_step = "COMPLETED"
            self.checkpoint.updated_at = time.time()
            return True
        else:
            self.checkpoint.state["webhook_dispatched"] = False
            self.checkpoint.current_step = "FAILED"
            return False
