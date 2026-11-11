"""Python FastAPI + LangGraph-style cyclic evidence guardrail worker.

Enforces deterministic citation provenance across biomedical/enterprise multi-step runs:
every synthesized claim must cite at least one retrieved source evidence node ID.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EvidenceNode:
    doc_id: str
    title: str
    snippet: str


@dataclass(frozen=True)
class ClaimWithCitations:
    statement: str
    cited_doc_ids: tuple[str, ...]


@dataclass
class SynthesisState:
    query: str
    evidence_pool: dict[str, EvidenceNode] = field(default_factory=dict)
    claims: list[ClaimWithCitations] = field(default_factory=list)
    guardrail_attempts: int = 0
    verified: bool = False
    rejected_citations: list[str] = field(default_factory=list)


def verify_citation_integrity(state: SynthesisState) -> SynthesisState:
    """Rejects phantom citations not grounded in the retrieved evidence_pool."""
    missing: list[str] = []
    if not state.claims:
        missing.append("EMPTY_CLAIMS")
    for idx, claim in enumerate(state.claims):
        if not claim.cited_doc_ids:
            missing.append(f"claim[{idx}]:NO_CITATIONS")
            continue
        for cid in claim.cited_doc_ids:
            if cid not in state.evidence_pool:
                missing.append(f"claim[{idx}]:UNKNOWN_DOC:{cid}")

    state.rejected_citations = missing
    state.verified = len(missing) == 0
    state.guardrail_attempts += 1
    return state


def run_bounded_evidence_loop(
    query: str,
    retrieved: list[EvidenceNode],
    propose_claims_fn,
    max_repairs: int = 2,
) -> SynthesisState:
    """Cyclic state machine: generate -> verify_citation_integrity -> repair -> bounded stop."""
    state = SynthesisState(
        query=query,
        evidence_pool={n.doc_id: n for n in retrieved},
    )
    for attempt in range(1, max_repairs + 2):
        state.claims = propose_claims_fn(state, attempt)
        verify_citation_integrity(state)
        if state.verified:
            return state
    return state
