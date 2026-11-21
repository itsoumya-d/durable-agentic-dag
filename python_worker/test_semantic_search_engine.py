import unittest
from python_worker.semantic_search_engine import (
    SemanticChunker,
    DocumentChunk,
    DenseEmbeddingIndex,
    BM25KeywordIndex,
    HybridRRFRetriever,
    RAGPipelineGuardrail,
    RetrievalResult,
)


class TestSemanticSearchEngine(unittest.TestCase):
    def setUp(self):
        self.chunker = SemanticChunker(max_chunk_words=10, overlap_words=3)
        self.doc_text = (
            "Scalable semantic search systems require hybrid retrieval indexing combining dense embeddings "
            "with BM25 lexical inverted indices and reciprocal rank fusion to eliminate hallucinations."
        )

    def test_semantic_chunker_overlap_and_metadata(self):
        chunks = self.chunker.chunk_document("doc-austria", self.doc_text, metadata={"source": "karriere"})
        self.assertGreaterEqual(len(chunks), 2)
        self.assertEqual(chunks[0].chunk_id, "doc-austria-chunk-0")
        self.assertEqual(chunks[0].metadata["source"], "karriere")
        # Ensure overlap exists between chunk 0 and chunk 1
        c0_words = chunks[0].text.split()
        c1_words = chunks[1].text.split()
        self.assertEqual(c0_words[-3:], c1_words[:3])

    def test_chunker_validation(self):
        with self.assertRaises(ValueError):
            SemanticChunker(max_chunk_words=0)
        with self.assertRaises(ValueError):
            SemanticChunker(max_chunk_words=10, overlap_words=10)

    def test_dense_embedding_cosine_similarity(self):
        index = DenseEmbeddingIndex()
        c1 = DocumentChunk("c1", "d1", "AI agentic workflows", embedding=[1.0, 0.0, 0.0])
        c2 = DocumentChunk("c2", "d1", "Database reliability", embedding=[0.0, 1.0, 0.0])
        c3 = DocumentChunk("c3", "d1", "Agent orchestration", embedding=[0.8, 0.2, 0.0])

        index.add_chunks([c1, c2, c3])

        # Query vector aligned with c1 and c3
        query = [0.9, 0.1, 0.0]
        results = index.search(query, top_k=2)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].chunk_id, "c1")
        self.assertEqual(results[1].chunk_id, "c3")
        self.assertGreater(results[0].score, 0.9)

    def test_bm25_lexical_scoring(self):
        bm25 = BM25KeywordIndex()
        c1 = DocumentChunk("c1", "d1", "PostgreSQL database indexing and query optimization")
        c2 = DocumentChunk("c2", "d2", "Kubernetes cluster orchestration and container deployment")
        c3 = DocumentChunk("c3", "d3", "PostgreSQL connection pooling and MVCC vacuum tuning")

        bm25.index_chunks([c1, c2, c3])
        results = bm25.search("PostgreSQL vacuum optimization", top_k=3)

        self.assertEqual(len(results), 2)
        # c3 has both 'PostgreSQL' and 'vacuum', c1 has 'PostgreSQL' and 'optimization'
        ids = [r.chunk_id for r in results]
        self.assertIn("c1", ids)
        self.assertIn("c3", ids)
        self.assertNotIn("c2", ids)

    def test_reciprocal_rank_fusion_hybrid(self):
        dense = DenseEmbeddingIndex()
        sparse = BM25KeywordIndex()

        c1 = DocumentChunk("c1", "d1", "GenAI semantic search RAG", embedding=[1.0, 0.0])
        c2 = DocumentChunk("c2", "d2", "Distributed indexing systems", embedding=[0.5, 0.5])
        c3 = DocumentChunk("c3", "d3", "PostgreSQL enterprise database", embedding=[0.0, 1.0])

        dense.add_chunks([c1, c2, c3])
        sparse.index_chunks([c1, c2, c3])

        retriever = HybridRRFRetriever(dense, sparse, rrf_k=60)
        # Query matching c1 both lexically and densely
        query_text = "GenAI semantic search"
        query_vec = [1.0, 0.0]

        results = retriever.retrieve(query_text, query_vec, top_k=3)
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0].chunk_id, "c1")
        self.assertIsNotNone(results[0].rrf_score)
        self.assertEqual(results[0].rank_dense, 1)
        self.assertEqual(results[0].rank_sparse, 1)

    def test_rag_pipeline_guardrail_citation_integrity(self):
        guardrail = RAGPipelineGuardrail(min_citation_overlap=0.4)

        retrieved = [
            RetrievalResult("doc-1-chunk-0", "doc-1", "webLyzard specializes in visual media analytics and semantic intelligence.", score=0.9),
            RetrievalResult("doc-1-chunk-1", "doc-1", "Hybrid RAG combines dense embeddings with lexical BM25 indices.", score=0.85),
        ]

        # Valid citation with ground truth overlap
        claim_valid = "Visual media analytics is powered by semantic intelligence [doc-1-chunk-0]."
        citations = guardrail.extract_citations(claim_valid)
        self.assertEqual(citations, ["doc-1-chunk-0"])

        is_valid, overlap, reason = guardrail.verify_groundedness(
            claim_sentence=claim_valid,
            cited_chunk_id="doc-1-chunk-0",
            retrieved_chunks=retrieved,
        )
        self.assertTrue(is_valid)
        self.assertGreaterEqual(overlap, 0.4)

        # Hallucinated citation not in context
        is_valid_fake, _, reason_fake = guardrail.verify_groundedness(
            claim_sentence="Some ungrounded claim [doc-999-chunk-0].",
            cited_chunk_id="doc-999-chunk-0",
            retrieved_chunks=retrieved,
        )
        self.assertFalse(is_valid_fake)
        self.assertIn("was not present", reason_fake)

        # Low overlap citation
        is_low, overlap_low, _ = guardrail.verify_groundedness(
            claim_sentence="Astronomy telescopes view faraway supernovas in interstellar space.",
            cited_chunk_id="doc-1-chunk-0",
            retrieved_chunks=retrieved,
        )
        self.assertFalse(is_low)
        self.assertLess(overlap_low, 0.4)


if __name__ == "__main__":
    unittest.main()
