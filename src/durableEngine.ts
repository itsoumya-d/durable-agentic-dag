import crypto from 'node:crypto';
import { WorkflowDefinition, WorkflowStep, validateWorkflowDag } from './dagValidator.js';

export interface TelemetrySpan {
  traceId: string;
  runId: string;
  tenantId: string;
  stepId: string;
  service: 'ts-orchestrator' | 'py-evidence-worker';
  durationMs: number;
  promptTokens: number;
  completionTokens: number;
  estimatedUsd: number;
  replayedCheckpoint: boolean;
}

export interface StepOutput {
  data: Record<string, unknown>;
  citations: string[];
  promptTokens?: number;
  completionTokens?: number;
  estimatedUsd?: number;
  service?: 'ts-orchestrator' | 'py-evidence-worker';
}

export interface RunCheckpointRecord {
  runId: string;
  tenantId: string;
  status: 'running' | 'completed' | 'abandoned';
  completedSteps: Map<string, StepOutput>;
  attempts: Map<string, number>;
  spans: TelemetrySpan[];
}

export class TransientStepFailure extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'TransientStepFailure';
  }
}

export type StepExecutor = (
  step: WorkflowStep,
  upstreamOutputs: Record<string, StepOutput>,
  idempotencyKey: string,
) => Promise<StepOutput>;

/**
 * Restate-inspired durable execution engine:
 * - Static DAG validation rejects invalid graphs pre-run
 * - Persists completed step outputs in a checkpoint journal keyed by runId+stepId
 * - On crash/restart resumption, skips already-completed steps with zero duplicate model spend
 * - Tracks per-step OTel-compatible spans + token-cost attribution for pricing decisions
 */
export class DurableWorkflowEngine {
  private readonly journal = new Map<string, RunCheckpointRecord>();

  getRecord(runId: string): RunCheckpointRecord | undefined {
    return this.journal.get(runId);
  }

  async executeRun(
    runId: string,
    definition: WorkflowDefinition,
    executor: StepExecutor,
  ): Promise<RunCheckpointRecord> {
    const validated = validateWorkflowDag(definition);
    if (!validated.ok) {
      throw new Error(`Invalid workflow DAG: ${validated.error.join('; ')}`);
    }

    const traceId = crypto.createHash('sha256').update(runId).digest('hex').slice(0, 32);
    let record = this.journal.get(runId);
    if (!record) {
      record = {
        runId,
        tenantId: definition.tenantId,
        status: 'running',
        completedSteps: new Map(),
        attempts: new Map(),
        spans: [],
      };
      this.journal.set(runId, record);
    } else if (record.tenantId !== definition.tenantId) {
      throw new Error('TENANT_ISOLATION_VIOLATION');
    }

    record.status = 'running';
    for (const step of validated.value) {
      const prior = record.completedSteps.get(step.id);
      if (prior) {
        record.spans.push({
          traceId,
          runId,
          tenantId: definition.tenantId,
          stepId: step.id,
          service: prior.service ?? 'ts-orchestrator',
          durationMs: 0,
          promptTokens: 0,
          completionTokens: 0,
          estimatedUsd: 0,
          replayedCheckpoint: true,
        });
        continue;
      }

      const upstream: Record<string, StepOutput> = {};
      for (const dep of step.dependsOn) {
        const depOut = record.completedSteps.get(dep);
        if (!depOut) throw new Error(`Missing upstream checkpoint for ${dep}`);
        upstream[dep] = depOut;
      }

      const idempotencyKey = `${runId}:${step.id}:${definition.version}`;
      const maxAttempts = step.retryLimit + 1;
      let done = false;
      for (let attempt = 1; attempt <= maxAttempts; attempt++) {
        record.attempts.set(step.id, (record.attempts.get(step.id) ?? 0) + 1);
        const started = performance.now();
        try {
          const result = await executor(step, upstream, idempotencyKey);
          const durationMs = Math.max(1, Math.round(performance.now() - started));
          record.completedSteps.set(step.id, result);
          record.spans.push({
            traceId,
            runId,
            tenantId: definition.tenantId,
            stepId: step.id,
            service: result.service ?? 'ts-orchestrator',
            durationMs,
            promptTokens: result.promptTokens ?? 0,
            completionTokens: result.completionTokens ?? 0,
            estimatedUsd: result.estimatedUsd ?? 0,
            replayedCheckpoint: false,
          });
          done = true;
          break;
        } catch (err) {
          if (!(err instanceof TransientStepFailure) || attempt === maxAttempts) {
            if (err instanceof TransientStepFailure && attempt < maxAttempts) continue;
            throw err;
          }
        }
      }
      if (!done) {
        record.status = 'abandoned';
        throw new Error(`Step ${step.id} abandoned`);
      }
    }

    record.status = 'completed';
    return record;
  }

  summarizeRunCost(runId: string): { totalUsd: number; totalTokens: number; replayedSteps: number } {
    const rec = this.journal.get(runId);
    if (!rec) throw new Error(`Unknown run ${runId}`);
    let totalUsd = 0;
    let totalTokens = 0;
    let replayedSteps = 0;
    for (const s of rec.spans) {
      totalUsd += s.estimatedUsd;
      totalTokens += s.promptTokens + s.completionTokens;
      if (s.replayedCheckpoint) replayedSteps += 1;
    }
    return {
      totalUsd: Number(totalUsd.toFixed(6)),
      totalTokens,
      replayedSteps,
    };
  }
}
