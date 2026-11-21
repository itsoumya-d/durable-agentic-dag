"""Semantic Search & Grounded RAG Retrieval Engine with Hybrid RRF Ranking.

Architectural reference implementation for:
  - Token-bounded semantic chunking with document provenance preservation.
  - In-memory dense embedding vector index with cosine similarity ranking.
  - BM25 lexical inverted index with length normalization.
  - Reciprocal Rank Fusion (RRF) combining dense and lexical scoring channels.
  - RAG context precision guardrail verifying citation grounding against indexed chunks.
"""

from __future__ import annotations
import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Set


@dataclass
class DocumentChunk:
    chunk_id: str
    doc_id: str
    text: str
    embedding: Optional[List[float]] = None
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class RetrievalResult:
    chunk_id: str
    doc_id: str
    text: str
    score: float
    rank_dense: Optional[int] = None
    rank_sparse: Optional[int] = None
    rrf_score: Optional[float] = None
    metadata: Dict[str, str] = field(default_factory=dict)


class SemanticChunker:
    """Splits source texts into sliding-window chunks with preserved provenance."""

    def __init__(self, max_chunk_words: int = 50, overlap_words: int = 10):
        if max_chunk_words <= 0:
            raise ValueError("max_chunk_words must be > 0")
        if overlap_words < 0 or overlap_words >= max_chunk_words:
            raise ValueError("overlap_words must be >= 0 and < max_chunk_words")
        self.max_chunk_words = max_chunk_words
        self.overlap_words = overlap_words

    def chunk_document(self, doc_id: str, text: str, metadata: Optional[Dict[str, str]] = None) -> List[DocumentChunk]:
        words = text.strip().split()
        if not words:
            return []

        chunks: List[DocumentChunk] = []
        step = self.max_chunk_words - self.overlap_words
        idx = 0
        chunk_idx = 0

        while idx < len(words):
            chunk_slice = words[idx : idx + self.max_chunk_words]
            chunk_text = " ".join(chunk_slice)
            chunk_id = f"{doc_id}-chunk-{chunk_idx}"
            chunks.append(
                DocumentChunk(
                    chunk_id=chunk_id,
                    doc_id=doc_id,
                    text=chunk_text,
                    metadata=dict(metadata or {}),
                )
            )
            idx += step
            chunk_idx += 1

        return chunks


class DenseEmbeddingIndex:
    """In-memory vector store computing cosine similarity over dense embeddings."""

    def __init__(self):
        self._chunks: Dict[str, DocumentChunk] = {}

    def add_chunk(self, chunk: DocumentChunk) -> None:
        if not chunk.embedding:
            raise ValueError(f"Chunk {chunk.chunk_id} lacks embedding vector")
        self._chunks[chunk.chunk_id] = chunk

    def add_chunks(self, chunks: List[DocumentChunk]) -> None:
        for c in chunks:
            self.add_chunk(c)

    @staticmethod
    def _cosine_similarity(v1: List[float], v2: List[float]) -> float:
        if len(v1) != len(v2):
            raise ValueError(f"Vector dimension mismatch: {len(v1)} vs {len(v2)}")
        dot = sum(a * b for a, b in zip(v1, v2))
        norm1 = math.sqrt(sum(a * a for a in v1))
        norm2 = math.sqrt(sum(b * b for b in v2))
        if norm1 == 0.0 or norm2 == 0.0:
            return 0.0
        return dot / (norm1 * norm2)

    def search(self, query_vector: List[float], top_k: int = 5) -> List[RetrievalResult]:
        if top_k <= 0:
            return []
        scored: List[Tuple[float, DocumentChunk]] = []
        for chunk in self._chunks.values():
            if chunk.embedding is not None:
                sim = self._cosine_similarity(query_vector, chunk.embedding)
                scored.append((sim, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        results: List[RetrievalResult] = []
        for rank, (score, chunk) in enumerate(scored[:top_k], start=1):
            results.append(
                RetrievalResult(
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    text=chunk.text,
                    score=round(score, 6),
                    rank_dense=rank,
                    metadata=chunk.metadata,
                )
            )
        return results


class BM25KeywordIndex:
    """Okapi BM25 sparse keyword inverted index."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._chunks: Dict[str, DocumentChunk] = {}
        self._doc_lengths: Dict[str, int] = {}
        self._avg_doc_len: float = 0.0
        self._inverted_index: Dict[str, Set[str]] = {}
        self._term_frequencies: Dict[str, Dict[str, int]] = {}

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        return re.findall(r"\b[a-zA-Z0-9_\-]+\b", text.lower())

    def index_chunks(self, chunks: List[DocumentChunk]) -> None:
        for c in chunks:
            tokens = self._tokenize(c.text)
            self._chunks[c.chunk_id] = c
            self._doc_lengths[c.chunk_id] = len(tokens)
            tf_map: Dict[str, int] = {}
            for t in tokens:
                tf_map[t] = tf_map.get(t, 0) + 1
                if t not in self._inverted_index:
                    self._inverted_index[t] = set()
                self._inverted_index[t].add(c.chunk_id)
            self._term_frequencies[c.chunk_id] = tf_map

        total_tokens = sum(self._doc_lengths.values())
        self._avg_doc_len = total_tokens / max(len(self._chunks), 1)

    def search(self, query: str, top_k: int = 5) -> List[RetrievalResult]:
        query_tokens = self._tokenize(query)
        if not query_tokens or not self._chunks:
            return []

        N = len(self._chunks)
        scores: Dict[str, float] = {cid: 0.0 for cid in self._chunks}

        for term in query_tokens:
            posting_list = self._inverted_index.get(term, set())
            n_t = len(posting_list)
            if n_t == 0:
                continue
            # Standard Lucene/BM25 IDF
            idf = math.log(1.0 + (N - n_t + 0.5) / (n_t + 0.5))
            for cid in posting_list:
                f_t = self._term_frequencies[cid].get(term, 0)
                d_len = self._doc_lengths[cid]
                denom = f_t + self.k1 * (1.0 - self.b + self.b * (d_len / max(self._avg_doc_len, 1e-6)))
                scores[cid] += idf * (f_t * (self.k1 + 1.0)) / max(denom, 1e-6)

        scored = [(s, self._chunks[cid]) for cid, s in scores.items() if s > 0.0]
        scored.sort(key=lambda x: x[0], reverse=True)

        results: List[RetrievalResult] = []
        for rank, (score, chunk) in enumerate(scored[:top_k], start=1):
            results.append(
                RetrievalResult(
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    text=chunk.text,
                    score=round(score, 6),
                    rank_sparse=rank,
                    metadata=chunk.metadata,
                )
            )
        return results


class HybridRRFRetriever:
    """Reciprocal Rank Fusion (RRF) combining Dense and BM25 search results."""

    def __init__(self, dense_index: DenseEmbeddingIndex, sparse_index: BM25KeywordIndex, rrf_k: int = 60):
        self.dense_index = dense_index
        self.sparse_index = sparse_index
        self.rrf_k = rrf_k

    def retrieve(self, query_text: str, query_vector: List[float], top_k: int = 5) -> List[RetrievalResult]:
        dense_results = self.dense_index.search(query_vector, top_k=top_k * 2)
        sparse_results = self.sparse_index.search(query_text, top_k=top_k * 2)

        rrf_scores: Dict[str, float] = {}
        items: Dict[str, DocumentChunk] = {}
        rank_dense_map: Dict[str, int] = {}
        rank_sparse_map: Dict[str, int] = {}

        for r in dense_results:
            rank = r.rank_dense or 1
            rank_dense_map[r.chunk_id] = rank
            rrf_scores[r.chunk_id] = rrf_scores.get(r.chunk_id, 0.0) + (1.0 / (self.rrf_k + rank))
            items[r.chunk_id] = DocumentChunk(r.chunk_id, r.doc_id, r.text, metadata=r.metadata)

        for r in sparse_results:
            rank = r.rank_sparse or 1
            rank_sparse_map[r.chunk_id] = rank
            rrf_scores[r.chunk_id] = rrf_scores.get(r.chunk_id, 0.0) + (1.0 / (self.rrf_k + rank))
            if r.chunk_id not in items:
                items[r.chunk_id] = DocumentChunk(r.chunk_id, r.doc_id, r.text, metadata=r.metadata)

        ranked = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]

        final_results: List[RetrievalResult] = []
        for chunk_id, fused_score in ranked:
            c = items[chunk_id]
            final_results.append(
                RetrievalResult(
                    chunk_id=c.chunk_id,
                    doc_id=c.doc_id,
                    text=c.text,
                    score=round(fused_score, 6),
                    rank_dense=rank_dense_map.get(chunk_id),
                    rank_sparse=rank_sparse_map.get(chunk_id),
                    rrf_score=round(fused_score, 6),
                    metadata=c.metadata,
                )
            )
        return final_results


class RAGPipelineGuardrail:
    """Verifies that generated RAG synthesis is grounded in retrieved context citations."""

    def __init__(self, min_citation_overlap: float = 0.4):
        self.min_citation_overlap = min_citation_overlap

    @staticmethod
    def extract_citations(response: str) -> List[str]:
        # Extracts citation patterns like [doc_id-chunk-0] or [chunk_id]
        matches = re.findall(r"\[([a-zA-Z0-9_\-]+-chunk-\d+)\]", response)
        return list(dict.fromkeys(matches))

    def verify_groundedness(
        self,
        claim_sentence: str,
        cited_chunk_id: str,
        retrieved_chunks: List[RetrievalResult],
    ) -> Tuple[bool, float, str]:
        matched = [c for c in retrieved_chunks if c.chunk_id == cited_chunk_id]
        if not matched:
            return False, 0.0, f"Citation [{cited_chunk_id}] was not present in retrieved context chunks"

        context_text = matched[0].text
        claim_tokens = set(re.findall(r"\b[a-zA-Z0-9_\-]{3,}\b", claim_sentence.lower()))
        context_tokens = set(re.findall(r"\b[a-zA-Z0-9_\-]{3,}\b", context_text.lower()))

        if not claim_tokens:
            return False, 0.0, "Claim sentence contains no extractable semantic tokens"

        overlap = len(claim_tokens & context_tokens) / len(claim_tokens)
        if overlap >= self.min_citation_overlap:
            return True, round(overlap, 4), f"Claim grounded ({overlap:.1%} lexical overlap)"
        return False, round(overlap, 4), f"Grounding failed: overlap {overlap:.1%} < threshold {self.min_citation_overlap:.1%}"
