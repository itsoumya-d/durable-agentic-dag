import test from 'node:test';
import assert from 'node:assert/strict';
import {
  AgenticPipelineEvaluator,
  AgentTrajectoryStep,
} from '../src/agenticPipelineEvaluator.js';

test('AgenticPipelineEvaluator passes verified trajectory with high precision and schema consistency', () => {
  const evaluator = new AgenticPipelineEvaluator();

  const trajectory: AgentTrajectoryStep[] = [
    {
      stepIndex: 0,
      rationale: 'Analyze source warehouse schema and extract customer orders table metadata',
      toolCall: {
        toolName: 'schema_inspector',
        parameters: { table: 'orders', namespace: 'analytics' },
        latencyMs: 350,
        status: 'success',
        outputSummary: 'Discovered orders schema with 12 typed columns and primary key id',
        producedMutations: [
          { entity: 'orders', action: 'select', columnScope: ['id', 'amount', 'created_at'] },
        ],
      },
      expectedSchemaVersion: 'v2.1.0',
      actualSchemaVersion: 'v2.1.0',
    },
    {
      stepIndex: 1,
      rationale: 'Construct and validate ELT transformation pipeline for order aggregation',
      toolCall: {
        toolName: 'pipeline_transformer',
        parameters: { transformation: 'daily_aggregates', window: '1d' },
        latencyMs: 620,
        status: 'success',
        outputSummary: 'Transformed daily orders and verified aggregation invariants',
        producedMutations: [
          { entity: 'daily_orders', action: 'transform', columnScope: ['date', 'total_gmv'] },
        ],
      },
      expectedSchemaVersion: 'v2.1.0',
      actualSchemaVersion: 'v2.1.0',
    },
    {
      stepIndex: 2,
      rationale: 'Publish transformed records to destination warehouse and register semantic model',
      toolCall: {
        toolName: 'warehouse_loader',
        parameters: { targetTable: 'daily_orders', partitionKey: 'date' },
        latencyMs: 410,
        status: 'success',
        outputSummary: 'Loaded 4200 partition records into destination semantic mart',
        producedMutations: [
          { entity: 'daily_orders', action: 'insert', columnScope: ['date', 'total_gmv'] },
        ],
      },
      expectedSchemaVersion: 'v2.1.0',
      actualSchemaVersion: 'v2.1.0',
    },
  ];

  const result = evaluator.evaluateTrajectory(
    ['schema', 'transformation', 'warehouse'],
    ['orders', 'daily_orders'],
    trajectory
  );

  assert.equal(result.passed, true);
  assert.equal(result.goalCompletionRate, 1.0);
  assert.equal(result.toolPrecision, 1.0);
  assert.equal(result.hallucinationDriftDetected, false);
  assert.equal(result.policyViolations.length, 0);
  assert.equal(result.stepCount, 3);
  assert.ok(result.latencyEfficiencyRatio > 1.0);
});

test('AgenticPipelineEvaluator flags destructive unauthorized schema actions', () => {
  const evaluator = new AgenticPipelineEvaluator();

  const destructiveTrajectory: AgentTrajectoryStep[] = [
    {
      stepIndex: 0,
      rationale: 'Attempt unapproved table drop to reset table state',
      toolCall: {
        toolName: 'ad_hoc_sql_runner',
        parameters: { query: 'DROP TABLE customers' },
        latencyMs: 120,
        status: 'success',
        outputSummary: 'Executed drop table customers successfully',
        producedMutations: [
          { entity: 'customers', action: 'drop', columnScope: [] },
        ],
      },
      expectedSchemaVersion: 'v1.0.0',
      actualSchemaVersion: 'v1.0.0',
    },
  ];

  const result = evaluator.evaluateTrajectory(
    ['reset', 'table'],
    ['customers'],
    destructiveTrajectory
  );

  assert.equal(result.passed, false);
  assert.ok(result.policyViolations.length >= 2);
  assert.ok(
    result.policyViolations.some((v) => v.includes("Destructive action 'drop' on entity 'customers'"))
  );
  assert.ok(
    result.policyViolations.some((v) => v.includes('Unsanitized raw SQL pattern'))
  );
});

test('AgenticPipelineEvaluator detects schema version drift across steps', () => {
  const evaluator = new AgenticPipelineEvaluator();

  const driftedTrajectory: AgentTrajectoryStep[] = [
    {
      stepIndex: 0,
      rationale: 'Read source dataset',
      toolCall: {
        toolName: 'reader',
        parameters: { dataset: 'events' },
        latencyMs: 200,
        status: 'success',
        outputSummary: 'Read 100 rows',
        producedMutations: [],
      },
      expectedSchemaVersion: 'v1.0.0',
      actualSchemaVersion: 'v1.0.0',
    },
    {
      stepIndex: 1,
      rationale: 'Execute transformation with out-of-sync schema metadata',
      toolCall: {
        toolName: 'transformer',
        parameters: { dataset: 'events' },
        latencyMs: 250,
        status: 'success',
        outputSummary: 'Applied event normalization',
        producedMutations: [],
      },
      expectedSchemaVersion: 'v1.0.0',
      actualSchemaVersion: 'v2.0.0-unannounced',
    },
  ];

  const result = evaluator.evaluateTrajectory(
    ['source', 'transformation'],
    ['events'],
    driftedTrajectory
  );

  assert.equal(result.passed, false);
  assert.equal(result.hallucinationDriftDetected, true);
});

test('AgenticPipelineEvaluator handles empty trajectory gracefully', () => {
  const evaluator = new AgenticPipelineEvaluator();
  const result = evaluator.evaluateTrajectory(['goal'], ['entity'], []);

  assert.equal(result.passed, false);
  assert.equal(result.stepCount, 0);
  assert.ok(result.policyViolations.includes('Empty trajectory provided'));
});
