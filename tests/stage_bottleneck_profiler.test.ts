import test from 'node:test';
import assert from 'node:assert/strict';
import { StageBottleneckProfiler } from '../src/stage_bottleneck_profiler.js';

test('StageBottleneckProfiler detects healthy pipeline with balanced stage durations', () => {
  const profiler = new StageBottleneckProfiler();
  profiler.recordStage({
    stage: 'spec_generation',
    durationMs: 1200,
    tokensConsumed: 450,
    iterations: 1,
    errorsEncountered: [],
  });
  profiler.recordStage({
    stage: 'code_synthesis',
    durationMs: 2000,
    tokensConsumed: 1800,
    iterations: 1,
    errorsEncountered: [],
  });
  profiler.recordStage({
    stage: 'static_analysis',
    durationMs: 800,
    tokensConsumed: 200,
    iterations: 1,
    errorsEncountered: [],
  });
  profiler.recordStage({
    stage: 'test_execution',
    durationMs: 1500,
    tokensConsumed: 300,
    iterations: 1,
    errorsEncountered: [],
  });

  const summary = profiler.analyzePipeline();
  assert.equal(summary.bottleneckCount, 0);
  assert.equal(summary.totalDurationMs, 5500);
  assert.equal(summary.totalTokens, 2750);
  assert.equal(summary.healingSuccessRate, 1.0);
});

test('StageBottleneckProfiler detects critical bottleneck in self-healing repair loop', () => {
  const profiler = new StageBottleneckProfiler();
  profiler.recordStage({
    stage: 'code_synthesis',
    durationMs: 1500,
    tokensConsumed: 1000,
    iterations: 1,
    errorsEncountered: [],
  });
  profiler.recordStage({
    stage: 'self_healing_repair',
    durationMs: 6500,
    tokensConsumed: 8200,
    iterations: 5,
    errorsEncountered: ['AssertionError', 'TypeError', 'SyntaxError'],
  });

  const summary = profiler.analyzePipeline();
  assert.equal(summary.bottleneckCount, 1);
  assert.equal(summary.primaryBottleneckStage, 'self_healing_repair');

  const repairReport = summary.stageReports.find((r) => r.stage === 'self_healing_repair');
  assert.ok(repairReport);
  assert.equal(repairReport.severity, 'CRITICAL_BOTTLENECK');
  assert.ok(repairReport.recommendedIntervention?.includes('Compact context window'));
  assert.ok(summary.healingSuccessRate < 1.0);
});
