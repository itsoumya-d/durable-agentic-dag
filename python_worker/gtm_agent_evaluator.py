from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Sequence

SignalType = Literal["budget", "churn_risk", "competitor", "decision_maker", "pain_point"]


@dataclass(frozen=True)
class CallSignal:
    signal_type: SignalType
    extracted_text: str
    confidence: float


@dataclass(frozen=True)
class CallPrepBriefing:
    account_id: str
    opportunity_stage: str
    key_signals: tuple[CallSignal, ...]
    suggested_action_items: tuple[str, ...]
    deal_health_score: float


@dataclass(frozen=True)
class AgentGradingRubric:
    factuality_score: float
    tone_alignment_score: float
    actionability_score: float
    composite_quality_score: float
    hallucination_detected: bool
    passed: bool
    audit_trace: str


class GTMAgentEvaluator:
    """
    Applied AI evaluation engine for GTM intelligence workflows.
    Synthesizes sales signals, grades agent-drafted outputs against grounded context,
    and enforces human-in-the-loop (HITL) review guardrails before downstream actions execute.
    """

    SIGNAL_PATTERNS = {
        "budget": re.compile(r"\b(\$\d+[\d,]*|\d+k\s*arr|\d+\s*seats?|budget\s*(?:is|of|approved))\b", re.IGNORECASE),
        "churn_risk": re.compile(r"\b(unhappy|considering leaving|cancel|expensive|frustrated|looking elsewhere)\b", re.IGNORECASE),
        "competitor": re.compile(r"\b(competitor|alternative|evaluating other|rfp with|vendor)\b", re.IGNORECASE),
        "decision_maker": re.compile(r"\b(vp|director|cto|cfo|head of|procurement|signing authority)\b", re.IGNORECASE),
        "pain_point": re.compile(r"\b(bottleneck|manual work|delayed|friction|outage|latency)\b", re.IGNORECASE),
    }

    @classmethod
    def synthesize_call_signals(
        cls,
        account_id: str,
        opportunity_stage: str,
        transcript_text: str,
    ) -> CallPrepBriefing:
        extracted: List[CallSignal] = []
        sentences = [s.strip() for s in re.split(r"[.\n]+", transcript_text) if s.strip()]

        for s in sentences:
            for sig_type, pattern in cls.SIGNAL_PATTERNS.items():
                m = pattern.search(s)
                if m:
                    extracted.append(
                        CallSignal(
                            signal_type=sig_type,  # type: ignore
                            extracted_text=s[:160],
                            confidence=0.92,
                        )
                    )

        # Calculate deal health: deduct for churn risk / competitors, add for decision makers / budget
        health = 0.70
        action_items: List[str] = []

        has_churn = any(sig.signal_type == "churn_risk" for sig in extracted)
        has_budget = any(sig.signal_type == "budget" for sig in extracted)
        has_decision_maker = any(sig.signal_type == "decision_maker" for sig in extracted)

        if has_churn:
            health -= 0.35
            action_items.append("Escalate renewal retention risk to account manager before next cadence")
        if has_budget:
            health += 0.15
            action_items.append("Prepare pricing proposal aligned with verified budget band")
        if not has_decision_maker:
            health -= 0.10
            action_items.append("Identify and map economic buyer before advancing stage")

        final_health = max(0.0, min(1.0, round(health, 2)))

        return CallPrepBriefing(
            account_id=account_id,
            opportunity_stage=opportunity_stage,
            key_signals=tuple(extracted),
            suggested_action_items=tuple(action_items),
            deal_health_score=final_health,
        )

    STOP_WORDS = {
        "a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "with", "by", "from",
        "of", "that", "this", "these", "those", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "would", "should", "could",
        "will", "shall", "can", "may", "might", "must", "hello", "hi", "dear", "thanks",
        "regarding", "following", "within", "your", "our", "their", "like", "next", "week",
    }

    @classmethod
    def grade_agent_draft(
        cls,
        draft_text: str,
        ground_truth_context: str,
        min_pass_score: float = 0.80,
    ) -> AgentGradingRubric:
        # Lexical grounding verification on content tokens
        context_tokens = {
            t for t in re.findall(r"\b[a-zA-Z]{3,}\b", ground_truth_context.lower())
            if t not in cls.STOP_WORDS
        }
        draft_content_tokens = [
            t for t in re.findall(r"\b[a-zA-Z]{3,}\b", draft_text.lower())
            if t not in cls.STOP_WORDS
        ]

        if not draft_content_tokens or not context_tokens:
            return AgentGradingRubric(
                factuality_score=0.0,
                tone_alignment_score=0.0,
                actionability_score=0.0,
                composite_quality_score=0.0,
                hallucination_detected=True,
                passed=False,
                audit_trace="Empty draft or ground truth context provided",
            )

        grounded_count = sum(1 for t in draft_content_tokens if t in context_tokens)
        grounding_ratio = grounded_count / len(draft_content_tokens)

        # Metrics scoring
        factuality = round(min(1.0, grounding_ratio * 1.2), 2)
        has_greeting = bool(re.search(r"\b(hi|hello|dear|thanks)\b", draft_text, re.IGNORECASE))
        tone = 0.95 if has_greeting else 0.80

        has_call_to_action = bool(re.search(r"\b(schedule|discuss|call|demo|review|time next week)\b", draft_text, re.IGNORECASE))
        actionability = 0.95 if has_call_to_action else 0.70

        hallucination = grounding_ratio < 0.40
        composite = round((factuality * 0.5) + (tone * 0.25) + (actionability * 0.25), 2)
        passed = composite >= min_pass_score and not hallucination

        trace = f"Grounding: {round(grounding_ratio, 2)}, Composite: {composite}, Pass: {passed}"

        return AgentGradingRubric(
            factuality_score=factuality,
            tone_alignment_score=tone,
            actionability_score=actionability,
            composite_quality_score=composite,
            hallucination_detected=hallucination,
            passed=passed,
            audit_trace=trace,
        )

    @staticmethod
    def enforce_hitl_guardrail(
        rubric: AgentGradingRubric,
        auto_send_threshold: float = 0.85,
    ) -> Dict[str, Any]:
        if rubric.hallucination_detected or rubric.composite_quality_score < auto_send_threshold:
            return {
                "decision": "route_to_rep_review",
                "reason": "Agent output failed quality threshold or ungrounded claims detected",
                "requires_human_approval": True,
                "score": rubric.composite_quality_score,
            }
        return {
            "decision": "auto_send",
            "reason": "Output verified against rubric and exceeds autonomous delivery threshold",
            "requires_human_approval": False,
            "score": rubric.composite_quality_score,
        }
