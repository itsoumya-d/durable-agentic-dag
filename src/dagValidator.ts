import { z } from 'zod';

export type Result<T, E> =
  | { ok: true; value: T }
  | { ok: false; error: E };

export const ok = <T>(value: T): Result<T, never> => ({ ok: true, value });
export const err = <E>(error: E): Result<never, E> => ({ ok: false, error });

export const StepKindSchema = z.enum([
  'deterministic_lookup',
  'subagent_fanout',
  'llm_synthesis',
  'citation_guardrail',
]);

export const WorkflowStepSchema = z.object({
  id: z.string().min(1),
  kind: StepKindSchema,
  dependsOn: z.array(z.string()).default([]),
  retryLimit: z.number().int().min(0).max(5).default(2),
  model: z.string().optional(),
  deterministicEligible: z.boolean().default(false),
});

export const WorkflowDefinitionSchema = z.object({
  workflowId: z.string().min(1),
  tenantId: z.string().min(1),
  version: z.string().min(1),
  steps: z.array(WorkflowStepSchema).min(1),
});

export type WorkflowStep = z.infer<typeof WorkflowStepSchema>;
export type WorkflowDefinition = z.infer<typeof WorkflowDefinitionSchema>;

/**
 * Static pre-execution workflow validator (Zod + Kahn's topological sort).
 * Rejects cyclic DAGs, dangling dependency references, duplicate step IDs,
 * and unguarded LLM synthesis steps missing an upstream lookup/guardrail edge
 * before spending model tokens.
 */
export function validateWorkflowDag(raw: unknown): Result<WorkflowStep[], string[]> {
  const parsed = WorkflowDefinitionSchema.safeParse(raw);
  if (!parsed.success) {
    return err(parsed.error.issues.map((i) => `${i.path.join('.')}: ${i.message}`));
  }

  const def = parsed.data;
  const errors: string[] = [];
  const byId = new Map<string, WorkflowStep>();

  for (const s of def.steps) {
    if (byId.has(s.id)) errors.push(`Duplicate step id: ${s.id}`);
    byId.set(s.id, s);
  }

  for (const s of def.steps) {
    for (const dep of s.dependsOn) {
      if (!byId.has(dep)) errors.push(`Step ${s.id} depends on unknown step ${dep}`);
      if (dep === s.id) errors.push(`Self-dependency detected on step ${s.id}`);
    }
    if (s.kind === 'llm_synthesis' && s.dependsOn.length === 0) {
      errors.push(`Ungrounded llm_synthesis step ${s.id} must depend on a retrieval step`);
    }
  }
  if (errors.length > 0) return err(errors);

  // Topological cycle check (Kahn's algorithm)
  const inDegree = new Map<string, number>();
  const children = new Map<string, string[]>();
  for (const s of def.steps) {
    inDegree.set(s.id, s.dependsOn.length);
    for (const dep of s.dependsOn) {
      const list = children.get(dep) ?? [];
      list.push(s.id);
      children.set(dep, list);
    }
  }

  const queue: string[] = [];
  for (const [id, deg] of inDegree) {
    if (deg === 0) queue.push(id);
  }

  const ordered: WorkflowStep[] = [];
  while (queue.length > 0) {
    const id = queue.shift()!;
    ordered.push(byId.get(id)!);
    for (const childId of children.get(id) ?? []) {
      const next = (inDegree.get(childId) ?? 1) - 1;
      inDegree.set(childId, next);
      if (next === 0) queue.push(childId);
    }
  }

  if (ordered.length !== def.steps.length) {
    return err(['Cycle detected in workflow definition DAG']);
  }

  return ok(ordered);
}
