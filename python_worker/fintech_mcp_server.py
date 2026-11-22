"""
Model Context Protocol (MCP) Server & Automated Workflow Engine
for Fintech SME Spend Management, Dispute Triage & Policy Enforcement.

Engineered for production conversational enterprise workflows:
- Protocol-compliant MCP tool and resource endpoints
- Deterministic credit and spend policy guardrails
- Automated case management triage and SLA-aware human-in-the-loop escalation
- Audit trace logging with token and latency attribution
"""

import json
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple


class FintechMCPServer:
    """Production MCP server handling fintech tools and resources."""

    def __init__(self, server_name: str = "capitalontap-fintech-mcp", version: str = "1.2.0"):
        self.server_name = server_name
        self.version = version
        self.tools: Dict[str, Dict[str, Any]] = {}
        self.resources: Dict[str, Dict[str, Any]] = {}
        self.audit_log: List[Dict[str, Any]] = []
        self._register_default_tools()
        self._register_default_resources()

    def _register_default_tools(self):
        self.register_tool(
            name="query_sme_transactions",
            description="Query and filter SME cardholder transactions by merchant, category, amount, and time range.",
            input_schema={
                "type": "object",
                "properties": {
                    "account_id": {"type": "string"},
                    "min_amount": {"type": "number"},
                    "max_amount": {"type": "number"},
                    "category": {"type": "string"},
                    "limit": {"type": "integer", "default": 20}
                },
                "required": ["account_id"]
            },
            handler=self._handle_query_transactions
        )

        self.register_tool(
            name="triage_cardholder_dispute",
            description="Triage SME card dispute, classify chargeback risk, and determine automated resolution path.",
            input_schema={
                "type": "object",
                "properties": {
                    "transaction_id": {"type": "string"},
                    "dispute_reason": {"type": "string"},
                    "amount": {"type": "number"},
                    "cardholder_tenure_months": {"type": "integer"}
                },
                "required": ["transaction_id", "dispute_reason", "amount"]
            },
            handler=self._handle_triage_dispute
        )

        self.register_tool(
            name="evaluate_credit_policy_guardrail",
            description="Evaluate deterministic compliance and risk guardrails before executing credit adjustments.",
            input_schema={
                "type": "object",
                "properties": {
                    "account_id": {"type": "string"},
                    "requested_limit_increase": {"type": "number"},
                    "risk_tier": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]}
                },
                "required": ["account_id", "requested_limit_increase", "risk_tier"]
            },
            handler=self._handle_evaluate_guardrail
        )

        self.register_tool(
            name="escalate_case_to_ops",
            description="Route ambiguous or high-risk case to human operations with full execution trace and context.",
            input_schema={
                "type": "object",
                "properties": {
                    "case_id": {"type": "string"},
                    "priority": {"type": "string", "enum": ["P1", "P2", "P3"]},
                    "reason": {"type": "string"},
                    "context_summary": {"type": "string"}
                },
                "required": ["case_id", "priority", "reason"]
            },
            handler=self._handle_escalate_case
        )

    def _register_default_resources(self):
        self.register_resource(
            uri="fintech://playbooks/sme_spend_policy",
            name="SME Spend Management Policy Playbook",
            mime_type="application/json",
            content={
                "policy_version": "2026.4",
                "auto_dispute_threshold_gbp": 150.00,
                "high_risk_categories": ["crypto", "gambling", "unregistered_wire"],
                "sla_hours": {"P1": 1, "P2": 4, "P3": 24}
            }
        )
        self.register_resource(
            uri="fintech://metrics/active_automations",
            name="Active AI Automation Performance Metrics",
            mime_type="application/json",
            content={
                "weekly_active_workflows": 4820,
                "autonomous_resolution_rate": 0.814,
                "mean_latency_ms": 32.5,
                "sla_adherence_percent": 99.8
            }
        )

    def register_tool(self, name: str, description: str, input_schema: Dict[str, Any], handler: Any):
        self.tools[name] = {
            "name": name,
            "description": description,
            "inputSchema": input_schema,
            "handler": handler
        }

    def register_resource(self, uri: str, name: str, mime_type: str, content: Any):
        self.resources[uri] = {
            "uri": uri,
            "name": name,
            "mimeType": mime_type,
            "content": content
        }

    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "inputSchema": t["inputSchema"]
            }
            for t in self.tools.values()
        ]

    def list_resources(self) -> List[Dict[str, Any]]:
        return [
            {
                "uri": r["uri"],
                "name": r["name"],
                "mimeType": r["mimeType"]
            }
            for r in self.resources.values()
        ]

    def read_resource(self, uri: str) -> Dict[str, Any]:
        if uri not in self.resources:
            raise KeyError(f"Resource '{uri}' not found")
        return self.resources[uri]

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.perf_counter()
        if name not in self.tools:
            raise ValueError(f"Tool '{name}' is not registered on this MCP server")

        tool = self.tools[name]
        schema = tool["inputSchema"]
        required = schema.get("required", [])
        for req in required:
            if req not in arguments:
                raise ValueError(f"Missing required parameter '{req}' for tool '{name}'")

        # Execute handler
        result = tool["handler"](arguments)
        duration_ms = (time.perf_counter() - start_time) * 1000

        # Log audit record
        audit_event = {
            "event_id": str(uuid.uuid4()),
            "timestamp": time.time(),
            "tool": name,
            "arguments": arguments,
            "duration_ms": round(duration_ms, 2),
            "status": "SUCCESS"
        }
        self.audit_log.append(audit_event)

        return {
            "content": [{"type": "text", "text": json.dumps(result)}],
            "isError": False,
            "metadata": {
                "server": self.server_name,
                "latency_ms": round(duration_ms, 2)
            }
        }

    def _handle_query_transactions(self, args: Dict[str, Any]) -> Dict[str, Any]:
        account_id = args["account_id"]
        limit = args.get("limit", 20)
        # Mock deterministic transactions
        mock_txs = [
            {"tx_id": f"tx_{account_id}_01", "merchant": "AWS Cloud Services", "amount": 1420.50, "category": "cloud_infra"},
            {"tx_id": f"tx_{account_id}_02", "merchant": "Google Workspace", "amount": 240.00, "category": "software"},
            {"tx_id": f"tx_{account_id}_03", "merchant": "WeWork London Moorgate", "amount": 850.00, "category": "real_estate"},
        ]
        return {
            "account_id": account_id,
            "transactions": mock_txs[:limit],
            "total_count": len(mock_txs)
        }

    def _handle_triage_dispute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        amount = float(args["amount"])
        tenure = int(args.get("cardholder_tenure_months", 12))
        reason = args["dispute_reason"].lower()

        # Deterministic triage heuristic
        is_low_value = amount <= 150.00
        is_tenured = tenure >= 6
        unauthorized = "unauthorized" in reason or "fraud" in reason

        if is_low_value and is_tenured and unauthorized:
            decision = "AUTO_REFUND_PROVISIONAL"
            confidence = 0.96
            escalation_needed = False
        else:
            decision = "REQUIRE_MANUAL_REVIEW"
            confidence = 0.72
            escalation_needed = True

        return {
            "transaction_id": args["transaction_id"],
            "decision": decision,
            "confidence": confidence,
            "escalation_needed": escalation_needed,
            "provisional_credit_gbp": amount if decision == "AUTO_REFUND_PROVISIONAL" else 0.0
        }

    def _handle_evaluate_guardrail(self, args: Dict[str, Any]) -> Dict[str, Any]:
        increase = float(args["requested_limit_increase"])
        risk_tier = args["risk_tier"]

        max_allowed_map = {"LOW": 25000.0, "MEDIUM": 10000.0, "HIGH": 2000.0}
        max_allowed = max_allowed_map.get(risk_tier, 0.0)

        passed = increase <= max_allowed
        return {
            "account_id": args["account_id"],
            "requested_increase": increase,
            "risk_tier": risk_tier,
            "max_allowed_increase": max_allowed,
            "guardrail_passed": passed,
            "rejection_reason": None if passed else f"Requested increase exceeds {risk_tier} risk cap of £{max_allowed:,.2f}"
        }

    def _handle_escalate_case(self, args: Dict[str, Any]) -> Dict[str, Any]:
        case_id = args["case_id"]
        priority = args["priority"]
        sla_hours = {"P1": 1, "P2": 4, "P3": 24}.get(priority, 24)

        return {
            "case_id": case_id,
            "priority": priority,
            "sla_target_hours": sla_hours,
            "routed_queue": f"fintech_ops_{priority.lower()}",
            "status": "ESCALATED_TO_HUMAN"
        }
