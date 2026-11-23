import test from 'node:test';
import assert from 'node:assert';
import {
  summarizeSteeringTrajectory,
  huntAnomalies,
  verifyProductionReadiness,
  PromptIteration,
} from '../src/promptOrchestrationVerifier.js';

test('PromptSteeringTracker aggregates iteration lineage and measures stabilization', () => {
  const history: PromptIteration[] = [
    {
      iterationId: 'turn-1',
      featureKey: 'auth-rbac',
      intent: 'Generate RBAC permission check middleware',
      userPrompt: 'Write an RBAC middleware with JWT check',
      breakingPoints: ['Hallucinated nonexistent library jsonwebtoken-v2', 'Omitted token expiry handling'],
      steeringInterventions: ['Steered to standard node:crypto and Zod payload validation'],
      codeArtifact: 'import jwt from "jsonwebtoken-v2";',
      testArtifact: '',
      status: 'initial',
    },
    {
      iterationId: 'turn-2',
      featureKey: 'auth-rbac',
      intent: 'Refactor RBAC middleware with standard crypto verification',
      userPrompt: 'Fix imports and add boundary test cases for expired tokens',
      breakingPoints: [],
      steeringInterventions: ['Added HMAC signature verification and timing safe equal'],
      codeArtifact: 'import crypto from "node:crypto"; import { z } from "zod";',
      testArtifact: 'assert.throws(() => verify(invalidToken));',
      status: 'verified',
    },
  ];

  const summary = summarizeSteeringTrajectory(history);
  assert.strictEqual(summary.totalTurns, 2);
  assert.strictEqual(summary.totalInterventions, 2);
  assert.strictEqual(summary.unresolvedBreakingPoints.length, 0);
  assert.strictEqual(summary.isStabilized, true);
});

test('AdversarialFailureHunter detects hallucinated dependencies and empty catch blocks', () => {
  const badCode = `
    import phantomLib from "phantom-super-ai-agent";
    function processPayment(data) {
      try {
        phantomLib.charge(data);
      } catch (e) {
      }
    }
  `;
  const badTests = `
    test("works", () => {
      expect(true).toBe(true);
    });
  `;

  const anomalies = huntAnomalies(badCode, badTests);
  const kinds = anomalies.map((a) => a.kind);

  assert.ok(kinds.includes('hallucinated_dependency'));
  assert.ok(kinds.includes('shallow_error_handling'));
  assert.ok(kinds.includes('vacuous_assertion'));
  assert.ok(kinds.includes('happy_path_only'));
});

test('VerificationVerdictEngine blocks code with critical defects and generates steering prompts', () => {
  const iteration: PromptIteration = {
    iterationId: 'iter-defect-1',
    featureKey: 'payment-sync',
    intent: 'Reconcile settlement records',
    userPrompt: 'Draft settlement parser',
    breakingPoints: ['Fails on currency mismatch'],
    steeringInterventions: [],
    codeArtifact: 'try { doSync(); } catch (err) {}',
    testArtifact: 'assert.ok(true, true);',
    status: 'initial',
  };

  const report = verifyProductionReadiness(iteration);
  assert.strictEqual(report.verdict, 'BLOCKED');
  assert.ok(report.productionReadinessScore < 50);
  assert.ok(report.steeringPromptDraft !== undefined);
  assert.ok(report.steeringPromptDraft.includes('Steering directive for feature: "payment-sync"'));
  assert.ok(report.steeringPromptDraft.includes('shallow_error_handling'));
});

test('VerificationVerdictEngine passes verified iteration with rigorous boundary tests', () => {
  const iteration: PromptIteration = {
    iterationId: 'iter-clean-1',
    featureKey: 'event-router',
    intent: 'Route events with schema verification',
    userPrompt: 'Implement router with Zod schema and boundary error tests',
    breakingPoints: [],
    steeringInterventions: ['Enforced exhaustive enum validation'],
    codeArtifact: `
      import { z } from "zod";
      export const EventSchema = z.object({ id: z.string().min(1), type: z.string() });
      export function route(payload: unknown) {
        return EventSchema.parse(payload);
      }
    `,
    testArtifact: `
      test("rejects invalid payload and empty ID", () => {
        assert.throws(() => route({ id: "" }), /String must contain at least 1/);
      });
    `,
    status: 'verified',
  };

  const report = verifyProductionReadiness(iteration);
  assert.strictEqual(report.verdict, 'PASS');
  assert.strictEqual(report.productionReadinessScore, 100);
  assert.strictEqual(report.anomalies.length, 0);
  assert.strictEqual(report.steeringPromptDraft, undefined);
});
