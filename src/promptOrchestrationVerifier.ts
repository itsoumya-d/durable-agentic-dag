import { z } from 'zod';

export const PromptIterationSchema = z.object({
  iterationId: z.string().min(1),
  featureKey: z.string().min(1),
  intent: z.string().min(1),
  systemPrompt: z.string().optional(),
  userPrompt: z.string().min(1),
  breakingPoints: z.array(z.string()).default([]),
  steeringInterventions: z.array(z.string()).default([]),
  codeArtifact: z.string(),
  testArtifact: z.string().optional().default(''),
  status: z.enum(['initial', 'steered', 'verified']).default('initial'),
});

export type PromptIteration = z.infer<typeof PromptIterationSchema>;

export const AnomalyKindSchema = z.enum([
  'hallucinated_dependency',
  'shallow_error_handling',
  'unguarded_null_dereference',
  'happy_path_only',
  'vacuous_assertion',
]);

export type AnomalyKind = z.infer<typeof AnomalyKindSchema>;

export const DetectedAnomalySchema = z.object({
  kind: AnomalyKindSchema,
  severity: z.enum(['low', 'medium', 'high', 'critical']),
  description: z.string(),
  lineHint: z.string().optional(),
});

export type DetectedAnomaly = z.infer<typeof DetectedAnomalySchema>;

export const VerificationReportSchema = z.object({
  verdict: z.enum(['PASS', 'NEEDS_STEERING', 'BLOCKED']),
  productionReadinessScore: z.number().min(0).max(100),
  anomalies: z.array(DetectedAnomalySchema),
  steeringPromptDraft: z.string().optional(),
});

export type VerificationReport = z.infer<typeof VerificationReportSchema>;

/**
 * Prompt lineage and steering trajectory logger.
 * Measures how prompts break, how interventions converge, and whether AI-directed code stabilized.
 */
export function summarizeSteeringTrajectory(iterations: PromptIteration[]): {
  totalTurns: number;
  unresolvedBreakingPoints: string[];
  totalInterventions: number;
  isStabilized: boolean;
} {
  const allSteers = iterations.flatMap((it) => it.steeringInterventions);
  const last = iterations[iterations.length - 1];

  return {
    totalTurns: iterations.length,
    unresolvedBreakingPoints: last ? last.breakingPoints : [],
    totalInterventions: allSteers.length,
    isStabilized: last ? last.status === 'verified' && last.breakingPoints.length === 0 : false,
  };
}

/**
 * Adversarial Failure Hunter:
 * Scans AI-generated code and test suites to catch hallucinations, logic gaps,
 * and superficial test suites before production deployment.
 */
export function huntAnomalies(
  code: string,
  tests: string,
  allowedDeps: string[] = ['zod', 'node:crypto', 'node:path', 'node:fs', 'tsx', 'typescript']
): DetectedAnomaly[] {
  const anomalies: DetectedAnomaly[] = [];

  // 1. Hunt Hallucinated Dependencies (imports/requires not in allowed list or standard packages)
  const importRegex = /(?:import\s+(?:(?:[\w*\s{},]+)\s+from\s+)?['"]([^'"]+)['"]|require\s*\(\s*['"]([^'"]+)['"]\s*\))/g;
  for (const match of code.matchAll(importRegex)) {
    const pkg = match[1] || match[2];
    if (!pkg || pkg.startsWith('.') || pkg.startsWith('/')) continue;
    const basePkg: string = (pkg.startsWith('@') ? pkg.split('/').slice(0, 2).join('/') : pkg.split('/')[0]) || pkg;
    if (!allowedDeps.includes(basePkg) && !['node:test', 'assert', 'node:assert'].includes(basePkg)) {
      anomalies.push({
        kind: 'hallucinated_dependency',
        severity: 'high',
        description: `Unapproved or hallucinated dependency: "${pkg}"`,
        lineHint: match[0],
      });
    }
  }

  // 2. Hunt Shallow Error Handling (empty catch blocks)
  if (/catch\s*(?:\([^)]*\))?\s*\{\s*\}/m.test(code)) {
    anomalies.push({
      kind: 'shallow_error_handling',
      severity: 'critical',
      description: 'Shallow error handling detected: empty catch block suppresses runtime failure',
    });
  }

  // 3. Hunt Unguarded Null Dereferences / unsafe non-null assertions on unknown inputs
  if (/\b(?:data|item|payload|result|res)\.[a-zA-Z0-9_]+\.[a-zA-Z0-9_]+(?!\?)/.test(code) && !code.includes('zod')) {
    anomalies.push({
      kind: 'unguarded_null_dereference',
      severity: 'medium',
      description: 'Deep object property access without optional chaining or schema validation guard',
    });
  }

  // 4. Hunt Vacuous Assertions in Test Suite (expect(true).toBe(true) or trivial passes)
  if (
    /assert\.(?:strictEqual|equal|ok)\s*\(\s*true\s*,\s*true\s*\)/.test(tests) ||
    /expect\s*\(\s*true\s*\)\.to(?:Be|Equal)\s*\(\s*true\s*\)/.test(tests)
  ) {
    anomalies.push({
      kind: 'vacuous_assertion',
      severity: 'critical',
      description: 'Vacuous assertion found in tests (tautological pass bypassing logic verification)',
    });
  }

  // 5. Hunt Happy-Path Only (no edge case, error, failure, empty or boundary test scenarios)
  const hasNegativeTests =
    /(?:reject|throw|error|invalid|failure|empty|boundary|null|undefined|malformed|timeout)/i.test(tests);
  if (tests.length > 0 && !hasNegativeTests) {
    anomalies.push({
      kind: 'happy_path_only',
      severity: 'high',
      description: 'Test suite exercises only happy-path scenarios; zero adversarial boundary cases detected',
    });
  }

  return anomalies;
}

/**
 * Verification Verdict Engine:
 * Generates surgical verdict (PASS, NEEDS_STEERING, BLOCKED) and constructs
 * targeted steering prompts to direct AI back on track when failures are detected.
 */
export function verifyProductionReadiness(
  iteration: PromptIteration,
  allowedDeps?: string[]
): VerificationReport {
  const anomalies = huntAnomalies(iteration.codeArtifact, iteration.testArtifact, allowedDeps);

  const criticalCount = anomalies.filter((a) => a.severity === 'critical').length;
  const highCount = anomalies.filter((a) => a.severity === 'high').length;
  const mediumCount = anomalies.filter((a) => a.severity === 'medium').length;

  let score = 100 - criticalCount * 40 - highCount * 25 - mediumCount * 10;
  if (score < 0) score = 0;

  let verdict: 'PASS' | 'NEEDS_STEERING' | 'BLOCKED' = 'PASS';
  if (criticalCount > 0 || score < 50) {
    verdict = 'BLOCKED';
  } else if (highCount > 0 || mediumCount > 0 || iteration.breakingPoints.length > 0) {
    verdict = 'NEEDS_STEERING';
  }

  let steeringPromptDraft: string | undefined;
  if (verdict !== 'PASS') {
    const issues = anomalies.map((a) => `- [${a.severity.toUpperCase()}] [${a.kind}] ${a.description}`).join('\n');
    steeringPromptDraft = [
      `Steering directive for feature: "${iteration.featureKey}"`,
      `The previous AI code output generated ${anomalies.length} quality anomaly(ies) needing immediate correction:`,
      issues,
      iteration.breakingPoints.length > 0
        ? `Additionally address active breaking points: ${iteration.breakingPoints.join('; ')}`
        : '',
      `Refactor the implementation to eliminate shallow handlers, replace unapproved packages, and add boundary edge tests.`,
    ]
      .filter(Boolean)
      .join('\n');
  }

  return {
    verdict,
    productionReadinessScore: score,
    anomalies,
    steeringPromptDraft,
  };
}
