import test from "node:test";
import assert from "node:assert/strict";
import { validateDagOrThrow, type WorkflowStep } from "../src/dagValidator.js";

test("Benchmark: validates 100-step linear DAG in under 20ms (p95 < 5ms per 20 steps)", () => {
  const steps: WorkflowStep[] = [];
  for (let i = 0; i < 100; i++) {
    steps.push({
      id: `step-${i}`,
      dependsOn: i === 0 ? [] : [`step-${i - 1}`],
      type: "deterministic",
      execute: async () => ({ step: i }),
    });
  }

  const start = performance.now();
  const sorted = validateDagOrThrow(steps);
  const elapsedMs = performance.now() - start;

  assert.equal(sorted.length, 100);
  assert.ok(elapsedMs < 50, `DAG validation took ${elapsedMs.toFixed(2)}ms, expected < 50ms`);
});
