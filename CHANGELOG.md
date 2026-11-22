# Changelog

All notable changes to `durable-agentic-dag` are documented here.

## [1.2.0] - 2026-11-23
### Added
- Fintech Model Context Protocol (MCP) server & automated workflow engine.
- Protocol-compliant tool endpoints: `query_sme_transactions`, `triage_cardholder_dispute`, `evaluate_credit_policy_guardrail`, `escalate_case_to_ops`.
- Deterministic credit and spend policy guardrails enforcing risk caps and automated SLA escalation.
- Resource schemas for SME spend management policy playbooks and active automation telemetry.
- Comprehensive test suite with 8 unit tests validating tool routing, risk gating, and audit logging.

## [1.1.0] - 2026-11-21
### Added
- Semantic search engine with token-bounded semantic chunking.
- Dense vector embedding index with cosine similarity search.
- BM25 lexical inverted index with length normalization.
- Reciprocal Rank Fusion (RRF) hybrid retrieval algorithm.
- RAG citation provenance guardrail verifying claim grounding against context.

## [1.0.0] - 2026-11-20
### Added
- Initial release of durable agentic workflow DAG orchestrator.
- Static cycle detection via Kahn's algorithm and Zod schema validation.
- Restate-inspired checkpoint journals and step-level token cost attribution.
