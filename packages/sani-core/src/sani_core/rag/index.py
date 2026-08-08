"""The codebase index: walk, chunk, embed, store, retrieve."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from ..workspace import IGNORED_DIR_NAMES, build_tree, is_probably_binary
from .chunker import MAX_FILE_BYTES, Chunk, chunk_source, grammars_available
from .embed import Embedder, build_embedder
from .store import Match, VectorStore, build_vector_store

#: How many chunks a planner gets. Retrieval is only useful if the result still
#: leaves room for the task; a dozen functions is already a lot of context.
DEFAULT_TOP_K = 6

#: Chunks longer than this are truncated in the planner prompt. The full text
#: is still returned by /rag/query for a human to read.
PROMPT_CHUNK_CHARS = 1200


@dataclass
class IndexStats:
    files: int = 0
    chunks: int = 0
    skipped: int = 0
    elapsed_s: float = 0.0

    def to_dict(self) -> dict:
        return {
            "files": self.files,
            "chunks": self.chunks,
            "skipped": self.skipped,
            "elapsed_s": round(self.elapsed_s, 3),
        }


@dataclass
class CodebaseIndex:
    """One index per workspace.

    Rebuilt wholesale rather than incrementally: a workspace is small enough
    that a full re-index costs a second, and an incremental index that drifts
    out of sync with the files is a worse failure than a slow one.
    """

    embedder: Embedder = field(default_factory=build_embedder)
    store: VectorStore = field(default_factory=build_vector_store)
    stats_by_workspace: dict[str, IndexStats] = field(default_factory=dict)

    async def index(self, workspace: Path | str) -> IndexStats:
        started = time.time()
        root = Path(workspace).resolve()
        key = str(root)

        chunks: list[Chunk] = []
        stats = IndexStats()

        for entry in build_tree(root):
            if entry["type"] != "file":
                continue
            path = root / entry["path"]
            if entry["size"] and entry["size"] > MAX_FILE_BYTES:
                stats.skipped += 1
                continue
            if is_probably_binary(path):
                stats.skipped += 1
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                stats.skipped += 1
                continue
            if not text.strip():
                continue

            file_chunks = chunk_source(entry["path"], text)
            chunks.extend(file_chunks)
            stats.files += 1

        vectors = await self.embedder.embed([chunk.text for chunk in chunks]) if chunks else []
        await self.store.replace(key, chunks, vectors)

        stats.chunks = len(chunks)
        stats.elapsed_s = time.time() - started
        self.stats_by_workspace[key] = stats
        return stats

    async def query(
        self, workspace: Path | str, question: str, limit: int = DEFAULT_TOP_K
    ) -> list[Match]:
        if not question.strip():
            return []
        vectors = await self.embedder.embed([question])
        return await self.store.query(str(Path(workspace).resolve()), vectors[0], limit)

    async def stats(self, workspace: Path | str) -> dict:
        key = str(Path(workspace).resolve())
        stored = await self.store.stats(key)
        recorded = self.stats_by_workspace.get(key)
        return {
            **stored,
            "last_index": recorded.to_dict() if recorded else None,
            "embedder": self.embedder.describe(),
            "store": self.store.describe(),
            # False means every file was chunked by line window rather than by
            # function or class -- install the rag extra.
            "syntax_aware": grammars_available(),
        }

    async def context_for(
        self, workspace: Path | str, task: str, limit: int = DEFAULT_TOP_K
    ) -> str:
        """Retrieved code, formatted for a planner prompt.

        Empty string when nothing matched, so a caller can treat "no index" and
        "no relevant code" identically -- both mean plan without it.
        """
        matches = await self.query(workspace, task, limit)
        if not matches:
            return ""

        blocks = []
        for match in matches:
            body = match.chunk.text
            if len(body) > PROMPT_CHUNK_CHARS:
                body = body[:PROMPT_CHUNK_CHARS] + "\n… (truncated)"
            blocks.append(f"--- {match.chunk.label}\n{body}")
        return "\n\n".join(blocks)


__all__ = [
    "DEFAULT_TOP_K",
    "Chunk",
    "CodebaseIndex",
    "IndexStats",
    "Match",
    "build_embedder",
    "build_vector_store",
]
