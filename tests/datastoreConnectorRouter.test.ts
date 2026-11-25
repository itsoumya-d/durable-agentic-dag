import test from 'node:test';
import assert from 'node:assert/strict';
import {
  BranchingWorkflowRouter,
  normalizeDatastoreRecord
} from '../src/datastoreConnectorRouter.js';

test('normalizeDatastoreRecord adapts Dataverse, SQL Server, and SFDC payloads into canonical schema', () => {
  const dv = normalizeDatastoreRecord('DATAVERSE', {
    cr4a1_workflowid: 'dv-01',
    cr4a1_accountcode: 'ACC-10',
    cr4a1_amount: 12500,
    statecode: 'new',
    cr4a1_region: 'NZ',
    sla_target_ms: 500,
    observed_ms: 210
  });
  assert.equal(dv.sourceKind, 'DATAVERSE');
  assert.equal(dv.amountUsd, 12500);

  assert.throws(() =>
    normalizeDatastoreRecord('SQL_SERVER', { WorkflowGuid: '', CustomerCode: 'X', TotalAmount: -5 })
  );
});

test('BranchingWorkflowRouter evaluates multi-branch rules and detects bottleneck source', () => {
  const router = new BranchingWorkflowRouter([
    { branchId: 'high-value', targetQueue: 'finance-approval', field: 'amountUsd', operator: 'gt', value: 10000 },
    { branchId: 'escalated', targetQueue: 'tier2-ops', field: 'status', operator: 'eq', value: 'ESCALATED' },
    { branchId: 'anz', targetQueue: 'anz-desk', field: 'region', operator: 'in', value: ['NZ', 'AU'] }
  ]);

  const sfdc = router.ingestAndRoute('SFDC', {
    Id: 'sf-100',
    AccountId: '001XX',
    Amount: 25000,
    StageName: 'ESCALATED',
    Territory__c: 'NZ',
    SlaTargetMs__c: 400,
    ObservedMs__c: 920
  });
  assert.deepEqual(sfdc.matchedBranches, ['high-value', 'escalated', 'anz']);
  assert.equal(sfdc.slaBreached, true);

  const sql = router.ingestAndRoute('SQL_SERVER', {
    WorkflowGuid: 'sql-200',
    CustomerCode: 'CUST-8',
    TotalAmount: 450,
    WorkflowState: 'IN_PROGRESS',
    RegionCode: 'US',
    SlaTargetMs: 500,
    ExecutionMs: 120
  });
  assert.deepEqual(sql.targetQueues, ['default-fulfillment']);
  assert.equal(sql.slaBreached, false);

  const summary = router.analyzeBottlenecks();
  assert.equal(summary.totalProcessed, 2);
  assert.equal(summary.breachCount, 1);
  assert.equal(summary.breachRate, 0.5);
  assert.equal(summary.bottleneckSource, 'SFDC');
});
