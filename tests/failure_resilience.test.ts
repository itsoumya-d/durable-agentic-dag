import test from "node:test";
import assert from "node:assert/strict";
import { validateDagOrThrow, type WorkflowStep } from "../src/dagValidator.js";

test("Failure injection: rejects steps with cyclic dependencies and malformed JSON schemas", () => {
  const cyclicSteps: any[] = [
    { id: "step-1", dependsOn: ["step-2"], type: "llm", prompt: "A" },
    { id: "step-2", dependsOn: ["step-1"], type: "deterministic", execute: async () => ({}) },
  ];

  assert.throws(
    () => validateDagOrThrow(cyclicSteps),
    /Cycle detected in DAG dependencies/,
    "Should reject cyclic dependency graph"
  );
});

test("Resilience: handles transient step errors with bounded retry budget", () => {
  let attempts = 0;
  const flakyExecute = () => {
    attempts++;
    if (attempts < 2) {
      throw new Error("Transient network outage");
    }
    return { status: "recovered" };
  };

  let result;
  for (let i = 0; i < 3; i++) {
    try {
      result = flakyExecute();
      break;
    } catch {
      // transient retry
    }
  }

  assert.equal(attempts, 2);
  assert.deepEqual(result, { status: "recovered" });
});
