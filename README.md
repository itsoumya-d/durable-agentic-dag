# durable-agentic-dag

Polyglot **TypeScript/Node.js + Python** reference orchestrator for multi-hour, auditable agentic workflows with static DAG validation, checkpoint/resume execution, OpenTelemetry-style token cost attribution, and strict citation provenance guardrails.

## Architecture & Core Guarantees
- `src/dagValidator.ts`: Zod + Kahn's topological sort rejecting cycles, dangling dependencies, and ungrounded LLM steps statically **before** model tokens are spent.
- `src/durableEngine.ts`: Restate-inspired checkpoint journal keyed by `runId + stepId`; resumes across worker preemptions without re-executing completed steps, paired with bounded transient retry budgets and step-level latency/token USD cost attribution.
- `python_worker/evidence_graph.py`: LangGraph-style cyclic repair state machine rejecting any synthesized scientific claim lacking a verified evidence node ID (`verify_citation_integrity`).

## Honest Scope & Non-Goals
- Uses deterministic test harnesses in CI (`npm test` + `python -m unittest`) without external LLM API keys or proprietary datasets.
- Built purely as an open architectural reference; claims zero external user metrics.

## Run Locally
```bash
npm install && npm run build && npm test
python3 -m unittest discover -s python_worker -p "test_*.py" -v
```
