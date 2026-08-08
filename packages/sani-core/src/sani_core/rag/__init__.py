"""Codebase RAG (spec Section 3, Phase 3).

tree-sitter chunking by function and class, embeddings behind an interface, and
a vector store behind another. The defaults are deterministic and dependency-
light so the whole thing is testable without a database or an API key; both
seams have a production implementation behind an environment variable.
"""

from .chunker import Chunk, chunk_source, language_for
from .embed import Embedder, HashingEmbedder, build_embedder, cosine, tokenize
from .index import DEFAULT_TOP_K, CodebaseIndex, IndexStats
from .store import Match, MemoryVectorStore, VectorStore, build_vector_store

__all__ = [
    "DEFAULT_TOP_K",
    "Chunk",
    "CodebaseIndex",
    "Embedder",
    "HashingEmbedder",
    "IndexStats",
    "Match",
    "MemoryVectorStore",
    "VectorStore",
    "build_embedder",
    "build_vector_store",
    "chunk_source",
    "cosine",
    "language_for",
    "tokenize",
]
