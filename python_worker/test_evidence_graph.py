import unittest
from python_worker.evidence_graph import (
    ClaimWithCitations,
    EvidenceNode,
    run_bounded_evidence_loop,
)


class EvidenceGraphTest(unittest.TestCase):
    def test_cyclic_repair_catches_phantom_citation_and_converges(self):
        pool = [
            EvidenceNode("pmid-101", "BRCA1 Target Validation", "CRISPR screen confirms dependency."),
            EvidenceNode("nct-202", "Phase II Biomarker Study", "Tolerance established in cohort B."),
        ]

        def propose(state, attempt):
            if attempt == 1:
                # Hallucinated citation on initial generation pass
                return [ClaimWithCitations("BRCA1 drives progression", ("pmid-999",))]
            return [ClaimWithCitations("BRCA1 drives progression", ("pmid-101", "nct-202"))]

        final_state = run_bounded_evidence_loop("BRCA1 safety", pool, propose, max_repairs=2)
        self.assertTrue(final_state.verified)
        self.assertEqual(final_state.guardrail_attempts, 2)
        self.assertEqual(final_state.rejected_citations, [])

    def test_uncited_claims_never_pass_guardrail(self):
        pool = [EvidenceNode("pmid-101", "Study", "Text")]
        state = run_bounded_evidence_loop(
            "Query",
            pool,
            lambda _s, _a: [ClaimWithCitations("Unsupported statement", ())],
            max_repairs=1,
        )
        self.assertFalse(state.verified)
        self.assertIn("claim[0]:NO_CITATIONS", state.rejected_citations)


if __name__ == "__main__":
    unittest.main()
