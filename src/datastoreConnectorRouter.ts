import { z } from 'zod';

export type DatastoreKind = 'DATAVERSE' | 'SQL_SERVER' | 'SFDC';

export const CanonicalRecordSchema = z.object({
  recordId: z.string().min(1),
  sourceKind: z.enum(['DATAVERSE', 'SQL_SERVER', 'SFDC']),
  accountKey: z.string().min(1),
  amountUsd: z.number().nonnegative(),
  status: z.enum(['NEW', 'IN_PROGRESS', 'ESCALATED', 'CLOSED']),
  region: z.string().min(1),
  slaTargetMs: z.number().positive(),
  observedMs: z.number().nonnegative()
});

export type CanonicalWorkflowRecord = z.infer<typeof CanonicalRecordSchema>;

export interface BranchRule {
  branchId: string;
  targetQueue: string;
  field: keyof CanonicalWorkflowRecord;
  operator: 'gt' | 'eq' | 'in';
  value: string | number | readonly string[];
}

export interface RoutingOutcome {
  recordId: string;
  sourceKind: DatastoreKind;
  matchedBranches: string[];
  targetQueues: string[];
  slaBreached: boolean;
}

export interface ProcessBottleneckSummary {
  totalProcessed: number;
  breachCount: number;
  breachRate: number;
  bySource: Record<DatastoreKind, { count: number; avgMs: number; maxMs: number; breaches: number }>;
  bottleneckSource: DatastoreKind | null;
}

const ADAPTER_MAPPINGS: Record<
  DatastoreKind,
  (raw: Record<string, unknown>) => Record<string, unknown>
> = {
  DATAVERSE: (r) => ({
    recordId: r.cr4a1_workflowid ?? r.id,
    sourceKind: 'DATAVERSE',
    accountKey: r.cr4a1_accountcode ?? r.account_id,
    amountUsd: Number(r.cr4a1_amount ?? 0),
    status: String(r.statecode ?? 'NEW').toUpperCase(),
    region: String(r.cr4a1_region ?? 'APAC'),
    slaTargetMs: Number(r.sla_target_ms ?? 1000),
    observedMs: Number(r.observed_ms ?? 0)
  }),
  SQL_SERVER: (r) => ({
    recordId: r.WorkflowGuid ?? r.RecordId,
    sourceKind: 'SQL_SERVER',
    accountKey: r.CustomerCode,
    amountUsd: Number(r.TotalAmount ?? 0),
    status: String(r.WorkflowState ?? 'NEW').toUpperCase(),
    region: String(r.RegionCode ?? 'APAC'),
    slaTargetMs: Number(r.SlaTargetMs ?? 1000),
    observedMs: Number(r.ExecutionMs ?? 0)
  }),
  SFDC: (r) => ({
    recordId: r.Id,
    sourceKind: 'SFDC',
    accountKey: r.AccountId,
    amountUsd: Number(r.Amount ?? 0),
    status: String(r.StageName ?? 'NEW').toUpperCase(),
    region: String(r.Territory__c ?? 'APAC'),
    slaTargetMs: Number(r.SlaTargetMs__c ?? 1000),
    observedMs: Number(r.ObservedMs__c ?? 0)
  })
};

export function normalizeDatastoreRecord(
  kind: DatastoreKind,
  raw: Record<string, unknown>
): CanonicalWorkflowRecord {
  const mapped = ADAPTER_MAPPINGS[kind](raw);
  return CanonicalRecordSchema.parse(mapped);
}

function ruleMatches(record: CanonicalWorkflowRecord, rule: BranchRule): boolean {
  const actual = record[rule.field];
  if (rule.operator === 'eq') return actual === rule.value;
  if (rule.operator === 'gt') return typeof actual === 'number' && typeof rule.value === 'number' && actual > rule.value;
  if (rule.operator === 'in') return Array.isArray(rule.value) && rule.value.includes(String(actual));
  return false;
}

export class BranchingWorkflowRouter {
  private readonly rules: BranchRule[];
  private readonly processed: CanonicalWorkflowRecord[] = [];

  constructor(rules: BranchRule[]) {
    this.rules = rules;
  }

  public ingestAndRoute(kind: DatastoreKind, raw: Record<string, unknown>): RoutingOutcome {
    const rec = normalizeDatastoreRecord(kind, raw);
    this.processed.push(rec);

    const matched = this.rules.filter((r) => ruleMatches(rec, r));
    return {
      recordId: rec.recordId,
      sourceKind: rec.sourceKind,
      matchedBranches: matched.map((m) => m.branchId),
      targetQueues: matched.length > 0 ? matched.map((m) => m.targetQueue) : ['default-fulfillment'],
      slaBreached: rec.observedMs > rec.slaTargetMs
    };
  }

  public analyzeBottlenecks(): ProcessBottleneckSummary {
    const init = () => ({ count: 0, totalMs: 0, maxMs: 0, breaches: 0 });
    const acc: Record<DatastoreKind, ReturnType<typeof init>> = {
      DATAVERSE: init(),
      SQL_SERVER: init(),
      SFDC: init()
    };

    for (const r of this.processed) {
      const bucket = acc[r.sourceKind];
      bucket.count += 1;
      bucket.totalMs += r.observedMs;
      bucket.maxMs = Math.max(bucket.maxMs, r.observedMs);
      if (r.observedMs > r.slaTargetMs) bucket.breaches += 1;
    }

    let bottleneckSource: DatastoreKind | null = null;
    let worstAvg = -1;
    const bySource = {} as ProcessBottleneckSummary['bySource'];
    let breachCount = 0;

    for (const kind of ['DATAVERSE', 'SQL_SERVER', 'SFDC'] as const) {
      const b = acc[kind];
      const avgMs = b.count > 0 ? Math.round(b.totalMs / b.count) : 0;
      breachCount += b.breaches;
      bySource[kind] = { count: b.count, avgMs, maxMs: b.maxMs, breaches: b.breaches };
      if (b.count > 0 && avgMs > worstAvg) {
        worstAvg = avgMs;
        bottleneckSource = kind;
      }
    }

    const total = this.processed.length;
    return {
      totalProcessed: total,
      breachCount,
      breachRate: total > 0 ? Number((breachCount / total).toFixed(4)) : 0,
      bySource,
      bottleneckSource
    };
  }
}
