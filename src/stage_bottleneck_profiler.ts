/**
 * Agentic Workflow Stage Bottleneck Profiler & Factory Optimizer.
 *
 * Measures, profiles, and analyzes multi-stage agentic software delivery pipelines
 * (spec design, code generation, linting, test synthesis, and self-healing loops)
 * to identify execution bottlenecks, token degradation, and cycle thrashing.
 */

export type StageName =
  | 'spec_generation'
  | 'code_synthesis'
  | 'static_analysis'
  | 'test_execution'
  | 'self_healing_repair';

export type BottleneckSeverity = 'HEALTHY' | 'WARN' | 'CRITICAL_BOTTLENECK';

export interface StageExecutionMetric {
  stage: StageName;
  durationMs: number;
  tokensConsumed: number;
  iterations: number;
  errorsEncountered: string[];
}

export interface StageBottleneckReport {
  stage: StageName;
  durationMs: number;
  tokensConsumed: number;
  iterations: number;
  durationPercent: number;
  severity: BottleneckSeverity;
  recommendedIntervention?: string;
}

export interface PipelineOptimizationSummary {
  totalDurationMs: number;
  totalTokens: number;
  bottleneckCount: number;
  primaryBottleneckStage?: StageName;
  stageReports: StageBottleneckReport[];
  healingSuccessRate: number;
}

export class StageBottleneckProfiler {
  private stages: StageExecutionMetric[] = [];

  public recordStage(metric: StageExecutionMetric): void {
    this.stages.push({ ...metric });
  }

  public analyzePipeline(): PipelineOptimizationSummary {
    const totalDurationMs = this.stages.reduce((acc, s) => acc + s.durationMs, 0);
    const totalTokens = this.stages.reduce((acc, s) => acc + s.tokensConsumed, 0);

    let maxDuration = -1;
    let primaryBottleneck: StageName | undefined;
    let bottleneckCount = 0;

    const stageReports: StageBottleneckReport[] = this.stages.map((s) => {
      const durationPercent = totalDurationMs > 0 ? (s.durationMs / totalDurationMs) * 100 : 0;
      let severity: BottleneckSeverity = 'HEALTHY';
      let recommendedIntervention: string | undefined;

      if (durationPercent > 45 || s.iterations >= 4) {
        severity = 'CRITICAL_BOTTLENECK';
        bottleneckCount++;
      } else if (durationPercent > 25 || s.iterations >= 2) {
        severity = 'WARN';
      }

      if (s.stage === 'self_healing_repair' && severity !== 'HEALTHY') {
        recommendedIntervention = 'Compact context window and enable speculative static analysis before re-running test harness.';
      } else if (s.stage === 'static_analysis' && severity !== 'HEALTHY') {
        recommendedIntervention = 'Cache AST dependencies and apply incremental type-checking.';
      } else if (s.stage === 'test_execution' && severity !== 'HEALTHY') {
        recommendedIntervention = 'Isolate failing sub-tests rather than executing full test suites on retry.';
      }

      if (s.durationMs > maxDuration && severity !== 'HEALTHY') {
        maxDuration = s.durationMs;
        primaryBottleneck = s.stage;
      }

      return {
        stage: s.stage,
        durationMs: s.durationMs,
        tokensConsumed: s.tokensConsumed,
        iterations: s.iterations,
        durationPercent: Math.round(durationPercent * 10) / 10,
        severity,
        recommendedIntervention,
      };
    });

    const repairStage = this.stages.find((s) => s.stage === 'self_healing_repair');
    const healingSuccessRate = repairStage && repairStage.iterations > 0
      ? Math.max(0, 1 - repairStage.errorsEncountered.length / (repairStage.iterations + 1))
      : 1.0;

    return {
      totalDurationMs,
      totalTokens,
      bottleneckCount,
      primaryBottleneckStage: primaryBottleneck,
      stageReports,
      healingSuccessRate: Math.round(healingSuccessRate * 100) / 100,
    };
  }
}
