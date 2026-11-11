import test from 'node:test';
import assert from 'node:assert/strict';
import { validateWorkflowDag } from '../src/dagValidator.js';
import { DurableWorkflowEngine, TransientStepFailure } from '../src/durableEngine.js';

test('Static DAG validator rejects cycles and ungrounded LLM steps pre-run', () => {
  const cyclic = validateWorkflowDag({
    workflowId: 'wf-cycle',
    tenantId: 't-bio',
    version: 'v1',
    steps: [
      { id: 'a', kind: 'deterministic_lookup', dependsOn: ['b'] },
      { id: 'b', kind: 'subagent_fanout', dependsOn: ['a'] },
    ],
  });
  assert.equal(cyclic.ok, false);
  if (!cyclic.ok) {
    assert.match(cyclic.error.join(' '), /Cycle detected/);
  }

  const ungrounded = validateWorkflowDag({
    workflowId: 'wf-ungrounded',
    tenantId: 't-bio',
    version: 'v1',
    steps: [{ id: 'synth', kind: 'llm_synthesis', dependsOn: [] }],
  });
  assert.equal(ungrounded.ok, false);
  if (!ungrounded.ok) {
    assert.match(ungrounded.error.join(' '), /Ungrounded/);
  }
});

test('Durable workflow checkpoints skip completed steps upon resume and attribute tokens/cost', async () => {
  const engine = new DurableWorkflowEngine();
  const definition = {
    workflowId: 'wf-target-validation',
    tenantId: 't-pharma',
    version: '2026.11',
    steps: [
      { id: 'fetch-trials', kind: 'deterministic_lookup' as const, dependsOn: [], retryLimit: 1, deterministicEligible: true },
      { id: 'subagent-safety', kind: 'subagent_fanout' as const, dependsOn: ['fetch-trials'], retryLimit: 1, deterministicEligible: false },
      { id: 'cite-guard', kind: 'citation_guardrail' as const, dependsOn: ['subagent-safety'], retryLimit: 0, deterministicEligible: true },
    ],
  };

  let failOnce = true;
  let fetchInvocations = 0;

  await assert.rejects(
    engine.executeRun('run-100', definition, async (step) => {
      if (step.id === 'fetch-trials') {
        fetchInvocations += 1;
        return { data: { docs: ['nct-001'] }, citations: ['nct-001'], service: 'ts-orchestrator' };
      }
      if (step.id === 'subagent-safety' && failOnce) {
        failOnce = false;
        throw new Error('Worker pod preempted mid-fanout');
      }
      return { data: {}, citations: ['nct-001'] };
    }),
  );

  // Resume the exact same runId cleanly: fetch-trials MUST replay checkpoint with zero re-execution
  let safetyAttempts = 0;
  const resumed = await engine.executeRun('run-100', definition, async (step, upstream) => {
    if (step.id === 'fetch-trials') {
      fetchInvocations += 1;
      throw new Error('Must NOT re-run checkpointed step fetch-trials');
    }
    if (step.id === 'subagent-safety') {
      safetyAttempts += 1;
      if (safetyAttempts === 1) throw new TransientStepFailure('Rate limit on attempt 1');
      assert.ok(upstream['fetch-trials']);
      return {
        data: { signals: ['AE-QTc'] },
        citations: ['nct-001'],
        promptTokens: 1200,
        completionTokens: 320,
        estimatedUsd: 0.0042,
        service: 'py-evidence-worker',
      };
    }
    return { data: { verified: true }, citations: ['nct-001'], service: 'py-evidence-worker' };
  });

  assert.equal(resumed.status, 'completed');
  assert.equal(fetchInvocations, 1);
  assert.equal(safetyAttempts, 2);

  const summary = engine.summarizeRunCost('run-100');
  assert.equal(summary.totalTokens, 1520);
  assert.equal(summary.totalUsd, 0.0042);
  assert.equal(summary.replayedSteps, 1);
});
