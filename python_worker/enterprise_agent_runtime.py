"""Enterprise Multi-Agent Coordination Runtime & ERP Policy Rule Engine.

Designed for autonomous agent execution across enterprise ERP workflows,
procurement operations, and compliance enforcement.
"""

from dataclasses import dataclass, field
import hashlib
import json
import time
from typing import Any, Callable, Dict, List, Optional


@dataclass
class AgentToolCall:
    tool_name: str
    arguments: Dict[str, Any]
    output: Optional[Any] = None
    duration_ms: float = 0.0
    status: str = "PENDING"


@dataclass
class AgentExecutionStep:
    agent_id: str
    step_id: str
    action: str
    tool_calls: List[AgentToolCall] = field(default_factory=list)
    latency_ms: float = 0.0
    tokens_used: int = 0
    status: str = "COMPLETED"


@dataclass
class PolicyRule:
    rule_id: str
    description: str
    condition: Callable[[Dict[str, Any]], bool]
    severity: str  # "BLOCK" or "ESCALATE"


class ERPPolicyRuleEngine:
    """Enforces deterministic enterprise compliance and financial guardrails."""

    def __init__(self):
        self.rules: List[PolicyRule] = []
        self._register_default_rules()

    def _register_default_rules(self):
        # 1. Procurement threshold requiring human approval
        self.add_rule(
            PolicyRule(
                rule_id="POL-001",
                description="Procurement transactions over $50,000 require human-in-the-loop dual authorization",
                condition=lambda payload: float(payload.get("amount", 0.0)) > 50000.0 and not payload.get("dual_approved", False),
                severity="ESCALATE"
            )
        )
        # 2. Strict vendor sanctions & verification check
        self.add_rule(
            PolicyRule(
                rule_id="POL-002",
                description="Vendors must have an active and verified ERP supplier status",
                condition=lambda payload: payload.get("vendor_status") != "ACTIVE_VERIFIED",
                severity="BLOCK"
            )
        )
        # 3. Currency and ledger reconciliation
        self.add_rule(
            PolicyRule(
                rule_id="POL-003",
                description="Transaction currency must match ERP entity accounting ledger currency",
                condition=lambda payload: payload.get("currency") not in ("USD", "EUR", "INR", "GBP", "SGD"),
                severity="BLOCK"
            )
        )

    def add_rule(self, rule: PolicyRule):
        self.rules.append(rule)

    def evaluate(self, transaction: Dict[str, Any]) -> Dict[str, Any]:
        violations = []
        requires_escalation = False

        for rule in self.rules:
            if rule.condition(transaction):
                violations.append({
                    "rule_id": rule.rule_id,
                    "description": rule.description,
                    "severity": rule.severity
                })
                if rule.severity == "ESCALATE":
                    requires_escalation = True
                elif rule.severity == "BLOCK":
                    return {
                        "allowed": False,
                        "escalate": False,
                        "violations": violations,
                        "status": "REJECTED_BY_POLICY"
                    }

        if requires_escalation:
            return {
                "allowed": False,
                "escalate": True,
                "violations": violations,
                "status": "REQUIRES_HUMAN_ESCALATION"
            }

        return {
            "allowed": True,
            "escalate": False,
            "violations": [],
            "status": "APPROVED"
        }


class EnterpriseAgentRuntime:
    """Orchestrates multi-agent execution, tool dispatch, and audit logging."""

    def __init__(self, policy_engine: Optional[ERPPolicyRuleEngine] = None):
        self.policy_engine = policy_engine or ERPPolicyRuleEngine()
        self.execution_traces: List[AgentExecutionStep] = []
        self.idempotency_store: Dict[str, Dict[str, Any]] = {}

    def generate_idempotency_key(self, payload: Dict[str, Any]) -> str:
        serialized = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def execute_procurement_workflow(self, workflow_payload: Dict[str, Any]) -> Dict[str, Any]:
        idem_key = self.generate_idempotency_key(workflow_payload)
        if idem_key in self.idempotency_store:
            return {
                **self.idempotency_store[idem_key],
                "cached": True,
                "idempotency_key": idem_key
            }

        start_time = time.perf_counter()
        step = AgentExecutionStep(
            agent_id="agent:procurement_lead_v1",
            step_id=f"step_{len(self.execution_traces) + 1}",
            action="evaluate_and_dispatch"
        )

        # 1. Policy check
        policy_result = self.policy_engine.evaluate(workflow_payload)
        step.tool_calls.append(AgentToolCall(
            tool_name="policy_engine.evaluate",
            arguments={"amount": workflow_payload.get("amount"), "vendor": workflow_payload.get("vendor_id")},
            output=policy_result,
            duration_ms=1.5,
            status="SUCCESS"
        ))

        if not policy_result["allowed"]:
            step.latency_ms = (time.perf_counter() - start_time) * 1000.0
            step.tokens_used = 280
            step.status = policy_result["status"]
            self.execution_traces.append(step)

            result = {
                "success": False,
                "status": policy_result["status"],
                "violations": policy_result["violations"],
                "escalate": policy_result["escalate"],
                "idempotency_key": idem_key,
                "cached": False
            }
            self.idempotency_store[idem_key] = result
            return result

        # 2. ERP Transaction Simulation
        erp_dispatch_call = AgentToolCall(
            tool_name="erp_gateway.post_purchase_order",
            arguments={
                "vendor_id": workflow_payload.get("vendor_id"),
                "amount": workflow_payload.get("amount"),
                "currency": workflow_payload.get("currency")
            },
            output={"erp_doc_id": f"PO-{int(time.time())}", "status": "COMMITTED"},
            duration_ms=4.2,
            status="SUCCESS"
        )
        step.tool_calls.append(erp_dispatch_call)

        step.latency_ms = (time.perf_counter() - start_time) * 1000.0
        step.tokens_used = 450
        step.status = "SUCCESS"
        self.execution_traces.append(step)

        result = {
            "success": True,
            "status": "COMMITTED",
            "erp_doc_id": erp_dispatch_call.output["erp_doc_id"],
            "violations": [],
            "escalate": False,
            "idempotency_key": idem_key,
            "cached": False
        }
        self.idempotency_store[idem_key] = result
        return result
