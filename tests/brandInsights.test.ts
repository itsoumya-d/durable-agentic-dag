import test from 'node:test';
import assert from 'node:assert/strict';
import {
  BrandSentimentAnalyzer,
  AgenticApprovalGate,
  SurveyResponse,
} from '../src/brandInsights.js';

test('BrandSentimentAnalyzer correctly computes NPS, consideration and sentiment polarity', () => {
  const responses: SurveyResponse[] = [
    {
      brand: 'Acme Brand',
      category: 'Beverages',
      respondentId: 'resp_1',
      promptedAwareness: true,
      considerationScore: 5,
      npsScore: 10, // Promoter
      feedback: 'I love this product, it is fast and exceptional',
    },
    {
      brand: 'Acme Brand',
      category: 'Beverages',
      respondentId: 'resp_2',
      promptedAwareness: true,
      considerationScore: 4,
      npsScore: 9, // Promoter
      feedback: 'Great quality and clean design',
    },
    {
      brand: 'Acme Brand',
      category: 'Beverages',
      respondentId: 'resp_3',
      promptedAwareness: false,
      considerationScore: 2,
      npsScore: 4, // Detractor
      feedback: 'Very slow and disappointing experience',
    },
    {
      brand: 'Acme Brand',
      category: 'Beverages',
      respondentId: 'resp_4',
      promptedAwareness: true,
      considerationScore: 3,
      npsScore: 8, // Passive
      feedback: 'Average overall, nothing exceptional',
    },
  ];

  const metrics = BrandSentimentAnalyzer.synthesize(responses);

  assert.equal(metrics.brand, 'Acme Brand');
  assert.equal(metrics.sampleSize, 4);
  assert.equal(metrics.awarenessPercentage, 75.0); // 3 out of 4 aware
  assert.equal(metrics.averageConsideration, 3.5); // (5+4+2+3)/4 = 3.5
  // NPS: (2 promoters - 1 detractor) / 4 = 1/4 = 25%
  assert.equal(metrics.netPromoterScore, 25);
  // Polarity: resp 1 (+1), resp 2 (+1), resp 3 (-1), resp 4 (+1 exceptional) -> net positive
  assert.ok(metrics.sentimentPolarity > 0);
});

test('AgenticApprovalGate enforces cryptographic token verification for high risk gates', () => {
  const gateService = new AgenticApprovalGate('test-agent-secret-key');

  const gate = gateService.createGate(
    'run_123',
    'step_export_bi',
    'Publish raw brand health data to external BI warehouse',
    'high',
    { records: 1000 },
  );

  assert.equal(gate.status, 'pending');

  // Attempt resolution with invalid token
  const invalidResult = gateService.resolveGate({
    gateId: gate.gateId,
    approved: true,
    approvedBy: 'lead_engineer',
    approvalToken: 'invalid_forged_token',
  });

  assert.equal(invalidResult.canExecute, false);
  assert.match(invalidResult.reason, /invalid or unsigned approval token/);

  // Resolution with valid cryptographic HMAC token
  const validToken = gateService.generateToken(gate.gateId, 'lead_engineer');
  const validResult = gateService.resolveGate({
    gateId: gate.gateId,
    approved: true,
    approvedBy: 'lead_engineer',
    approvalToken: validToken,
  });

  assert.equal(validResult.canExecute, true);

  // Subsequent resolution attempt is rejected
  const replayResult = gateService.resolveGate({
    gateId: gate.gateId,
    approved: false,
    approvedBy: 'lead_engineer',
    approvalToken: validToken,
  });

  assert.equal(replayResult.canExecute, false);
  assert.match(replayResult.reason, /already approved/);
});
