"""Phase 3: chunking, embeddings and retrieval."""

from __future__ import annotations

import pytest
from sani_core.rag import CodebaseIndex, HashingEmbedder, chunk_source, cosine, tokenize
from sani_core.rag.chunker import language_for
from sani_core.rag.store import MemoryVectorStore, build_vector_store

PYTHON_SOURCE = '''\
"""A module docstring."""
import os
from pathlib import Path

CONSTANT = 42


def check_permission(action, ladder):
    """Decide whether an action needs approval."""
    if action in ALWAYS_CONFIRM:
        return True
    return not ladder.auto_approve


class TrustLadder:
    """Per-action-type trust."""

    def record_approval(self, action):
        self.streak += 1
'''


# ---- chunking ---------------------------------------------------------------


def test_chunks_follow_definitions_not_line_counts():
    chunks = chunk_source("perms.py", PYTHON_SOURCE)
    named = {c.name: c for c in chunks if c.name}

    assert "check_permission" in named
    assert "TrustLadder" in named
    # A function chunk carries its whole body, so the retrieved text explains
    # itself rather than trailing off mid-statement.
    assert "return not ladder.auto_approve" in named["check_permission"].text
    assert named["check_permission"].kind == "function_definition"


def test_a_nested_method_stays_inside_its_class():
    chunks = chunk_source("perms.py", PYTHON_SOURCE)
    klass = next(c for c in chunks if c.name == "TrustLadder")
    assert "record_approval" in klass.text
    assert not any(c.name == "record_approval" for c in chunks)


def test_imports_and_constants_are_still_retrievable():
    chunks = chunk_source("perms.py", PYTHON_SOURCE)
    module_chunks = [c for c in chunks if c.kind == "module"]
    joined = "\n".join(c.text for c in module_chunks)
    assert "import os" in joined
    assert "CONSTANT = 42" in joined


def test_imports_separated_by_blank_lines_are_one_chunk_not_many():
    """Blank lines must not shatter a preamble into unretrievable slivers."""
    source = "import a\n\nimport b\n\nimport c\n\n\ndef go():\n    return 1\n"
    module_chunks = [c for c in chunk_source("m.py", source) if c.kind == "module"]
    assert len(module_chunks) == 1
    assert {"import a", "import b", "import c"} <= set(module_chunks[0].text.split("\n"))


@pytest.mark.parametrize(
    "path,expected",
    [("a.py", "python"), ("a.ts", "typescript"), ("a.tsx", "tsx"), ("a.go", "go")],
)
def test_language_detection(path, expected):
    assert language_for(path) == expected


def test_an_unknown_language_still_produces_chunks():
    chunks = chunk_source("notes.txt", "line one\nline two\n")
    assert chunks and chunks[0].kind == "text"


def test_typescript_definitions_are_found():
    source = (
        "import { z } from 'zod';\n\n"
        "export function total(items: Item[]): number {\n"
        "  return items.length;\n}\n\n"
        "export class Cart {\n  add(i: Item) {\n    this.items.push(i);\n  }\n}\n"
    )
    names = {c.name for c in chunk_source("cart.ts", source) if c.name}
    assert {"total", "Cart"} <= names


def test_an_empty_file_produces_nothing():
    assert chunk_source("empty.py", "") == []


# ---- embeddings -------------------------------------------------------------


def test_tokenize_splits_camel_and_snake_case_the_same_way():
    """parseHTTPResponse and parse_http_response must retrieve each other."""
    camel = set(tokenize("parseHTTPResponse"))
    snake = set(tokenize("parse_http_response"))
    assert "parse" in camel and "parse" in snake
    assert camel & snake


def test_embeddings_are_deterministic():
    embedder = HashingEmbedder()
    assert embedder.embed_one("def check_permission") == embedder.embed_one(
        "def check_permission"
    )


def test_similar_code_scores_higher_than_unrelated_code():
    embedder = HashingEmbedder()
    query = embedder.embed_one("check permission before running an action")
    related = embedder.embed_one("def check_permission(action, ladder): return True")
    unrelated = embedder.embed_one("import matplotlib; plt.scatter(x, y)")

    assert cosine(query, related) > cosine(query, unrelated)


def test_vectors_are_normalised_so_length_does_not_dominate():
    embedder = HashingEmbedder()
    short = embedder.embed_one("permission")
    long = embedder.embed_one("permission " * 200)
    assert abs(sum(v * v for v in short) - 1.0) < 1e-9
    assert abs(sum(v * v for v in long) - 1.0) < 1e-9


def test_an_empty_string_embeds_without_dividing_by_zero():
    assert HashingEmbedder().embed_one("") == [0.0] * 512


# ---- index ------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "auth.py").write_text(PYTHON_SOURCE)
    (tmp_path / "plotting.py").write_text(
        "import matplotlib.pyplot as plt\n\n\n"
        "def draw_scatter(x, y):\n    plt.scatter(x, y)\n    plt.show()\n"
    )
    (tmp_path / "notes.md").write_text("# Notes\n\nNothing to see.\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.js").write_text("module.exports = 1;\n")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00binary")
    return tmp_path


async def test_indexing_walks_the_workspace_and_skips_the_noise(repo):
    index = CodebaseIndex()
    stats = await index.index(repo)

    assert stats.files == 3  # auth.py, plotting.py, notes.md
    assert stats.chunks > 3
    assert stats.skipped == 1  # the binary

    status = await index.stats(repo)
    assert status["indexed"] is True


async def test_retrieval_finds_the_right_file(repo):
    index = CodebaseIndex()
    await index.index(repo)

    matches = await index.query(repo, "how do we decide if an action needs approval")
    assert matches
    assert matches[0].chunk.path == "auth.py"
    assert matches[0].score > 0

    other = await index.query(repo, "draw a scatter plot of the data")
    assert other[0].chunk.path == "plotting.py"


async def test_results_are_ranked_and_capped(repo):
    index = CodebaseIndex()
    await index.index(repo)

    matches = await index.query(repo, "permission action ladder", limit=2)
    assert len(matches) <= 2
    assert matches == sorted(matches, key=lambda m: m.score, reverse=True)


async def test_a_query_matching_nothing_returns_nothing(repo):
    """Padding a planner's context with irrelevant text is worse than silence."""
    index = CodebaseIndex()
    await index.index(repo)
    assert await index.query(repo, "zzzqqq nonexistent tokens xyzzy") == []
    assert await index.context_for(repo, "zzzqqq nonexistent tokens xyzzy") == ""


async def test_context_for_labels_each_snippet_with_its_location(repo):
    index = CodebaseIndex()
    await index.index(repo)

    context = await index.context_for(repo, "check permission")
    assert "auth.py:" in context
    assert "check_permission" in context


async def test_reindexing_replaces_rather_than_accumulates(repo):
    index = CodebaseIndex()
    await index.index(repo)
    first = (await index.stats(repo))["chunks"]

    await index.index(repo)
    assert (await index.stats(repo))["chunks"] == first

    (repo / "auth.py").unlink()
    await index.index(repo)
    assert await index.query(repo, "check permission ladder") == [] or all(
        match.chunk.path != "auth.py" for match in await index.query(repo, "check permission")
    )


async def test_an_unindexed_workspace_queries_empty_rather_than_raising(tmp_path):
    assert await CodebaseIndex().query(tmp_path, "anything") == []


def test_store_selection_and_honesty():
    assert isinstance(build_vector_store("memory"), MemoryVectorStore)
    assert build_vector_store("memory").describe()["verified"] is True
    # See tests/core/test_pgvector_store.py for the real, live-Postgres check.
    assert build_vector_store("pgvector").describe()["verified"] is True
    with pytest.raises(ValueError, match="unknown vector store"):
        build_vector_store("faiss")


def test_the_embedder_does_not_claim_to_be_semantic():
    assert HashingEmbedder().describe()["semantic"] is False
