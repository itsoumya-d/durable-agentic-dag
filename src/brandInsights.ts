import crypto from 'node:crypto';
import { z } from 'zod';

export const SurveyResponseSchema = z.object({
  brand: z.string().min(1),
  category: z.string().min(1),
  respondentId: z.string().min(1),
  promptedAwareness: z.boolean(),
  considerationScore: z.number().min(1).max(5),
  npsScore: z.number().min(0).max(10),
  feedback: z.string().default(''),
});

export type SurveyResponse = z.infer<typeof SurveyResponseSchema>;

export interface BrandHealthIndex {
  brand: string;
  sampleSize: number;
  awarenessPercentage: number;
  averageConsideration: number;
  netPromoterScore: number;
  sentimentPolarity: number;
  confidenceInterval: number;
  generatedAt: string;
}

export type RiskTier = 'low' | 'medium' | 'high';

export interface ApprovalGateRequest {
  gateId: string;
  runId: string;
  stepId: string;
  proposedAction: string;
  riskTier: RiskTier;
  payloadSummary: Record<string, unknown>;
  createdAt: string;
  status: 'pending' | 'approved' | 'rejected';
}

export interface ApprovalDecision {
  gateId: string;
  approved: boolean;
  approvedBy: string;
  approvalToken: string;
  reason?: string;
}

export class BrandSentimentAnalyzer {
  static synthesize(responses: SurveyResponse[]): BrandHealthIndex {
    const first = responses[0];
    if (!first) {
      throw new Error('cannot synthesize metrics from empty survey response set');
    }

    const brand = first.brand;
    const sampleSize = responses.length;

    // 1. Awareness Rate
    const awareCount = responses.filter((r) => r.promptedAwareness).length;
    const awarenessPct = Math.round((awareCount / sampleSize) * 1000) / 10;

    // 2. Consideration Average (1-5 scale)
    const totalConsideration = responses.reduce((acc, r) => acc + r.considerationScore, 0);
    const avgConsideration = Math.round((totalConsideration / sampleSize) * 100) / 100;

    // 3. Net Promoter Score (NPS): % Promoters (9-10) - % Detractors (0-6)
    const promoters = responses.filter((r) => r.npsScore >= 9).length;
    const detractors = responses.filter((r) => r.npsScore <= 6).length;
    const nps = Math.round(((promoters - detractors) / sampleSize) * 100);

    // 4. Sentiment Polarity Lexicon Evaluation
    let sentimentSum = 0;
    const positiveWords = ['love', 'great', 'innovative', 'reliable', 'exceptional', 'fast', 'recommend', 'clean'];
    const negativeWords = ['slow', 'bad', 'disappointing', 'expensive', 'unusable', 'clunky', 'poor', 'hate'];

    for (const r of responses) {
      const words = r.feedback.toLowerCase().split(/\s+/);
      let score = 0;
      for (const w of words) {
        if (positiveWords.includes(w)) score += 1;
        if (negativeWords.includes(w)) score -= 1;
      }
      sentimentSum += score > 0 ? 1 : score < 0 ? -1 : 0;
    }

    const sentimentPolarity = Math.round((sentimentSum / sampleSize) * 100) / 100;
    const standardError = Math.round((1 / Math.sqrt(sampleSize)) * 1.96 * 100) / 100;

    return {
      brand,
      sampleSize,
      awarenessPercentage: awarenessPct,
      averageConsideration: avgConsideration,
      netPromoterScore: nps,
      sentimentPolarity,
      confidenceInterval: standardError,
      generatedAt: new Date().toISOString(),
    };
  }
}

export class AgenticApprovalGate {
  private readonly gates = new Map<string, ApprovalGateRequest>();
  private readonly secretKey: string;

  constructor(secretKey: string = 'internal-agent-secret') {
    this.secretKey = secretKey;
  }

  createGate(
    runId: string,
    stepId: string,
    proposedAction: string,
    riskTier: RiskTier,
    summary: Record<string, unknown> = {},
  ): ApprovalGateRequest {
    const gateId = `gate_${crypto.randomBytes(8).toString('hex')}`;
    const req: ApprovalGateRequest = {
      gateId,
      runId,
      stepId,
      proposedAction,
      riskTier,
      payloadSummary: summary,
      createdAt: new Date().toISOString(),
      status: 'pending',
    };
    this.gates.set(gateId, req);
    return req;
  }

  generateToken(gateId: string, approver: string): string {
    return crypto.createHmac('sha256', this.secretKey).update(`${gateId}:${approver}`).digest('hex');
  }

  resolveGate(decision: ApprovalDecision): { canExecute: boolean; reason: string } {
    const gate = this.gates.get(decision.gateId);
    if (!gate) {
      return { canExecute: false, reason: 'gate not found' };
    }

    if (gate.status !== 'pending') {
      return { canExecute: false, reason: `gate already ${gate.status}` };
    }

    // High risk actions require cryptographic approval verification
    if (gate.riskTier === 'high') {
      const expectedToken = this.generateToken(decision.gateId, decision.approvedBy);
      if (decision.approvalToken !== expectedToken) {
        return { canExecute: false, reason: 'invalid or unsigned approval token for high risk action' };
      }
    }

    if (!decision.approved) {
      gate.status = 'rejected';
      return { canExecute: false, reason: decision.reason || 'rejected by reviewer' };
    }

    gate.status = 'approved';
    return { canExecute: true, reason: 'approved by human reviewer' };
  }
}
