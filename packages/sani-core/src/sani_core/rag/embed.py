"""Embeddings.

The default is a deterministic lexical embedder with no dependencies and no
network. That is a real trade-off and worth naming: it matches on identifiers
and tokens, not on meaning, so "how do we check permissions" will find
``check_permission`` but not ``authorise``. For code search that is less bad
than it sounds -- identifiers carry most of the signal in a codebase -- but it
is not a semantic model and should not be described as one.

It is the default because the whole test suite has to be reproducible and the
project has a zero-paid-keys constraint. ``SANI_EMBEDDINGS=litellm`` swaps in a
real embedding model when one is available.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from abc import ABC, abstractmethod

EMBEDDINGS_ENV_VAR = "SANI_EMBEDDINGS"
EMBEDDING_MODEL_ENV_VAR = "SANI_EMBEDDING_MODEL"
DEFAULT_EMBEDDING_MODEL = "gemini/text-embedding-004"

#: Enough buckets that unrelated identifiers rarely collide, small enough that
#: a few thousand chunks stay comfortably in memory.
DEFAULT_DIMENSIONS = 512

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def tokenize(text: str) -> list[str]:
    """Lowercased identifier tokens, plus their camelCase/snake_case parts.

    ``parseHTTPResponse`` and ``parse_http_response`` should retrieve each
    other; splitting both into the same parts is what makes that work.
    """
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(text):
        lowered = raw.lower()
        tokens.append(lowered)
        parts = [p for chunk in _CAMEL_RE.split(raw) for p in chunk.split("_") if p]
        if len(parts) > 1:
            tokens.extend(part.lower() for part in parts)
    return tokens


class Embedder(ABC):
    name: str = "embedder"
    dimensions: int = DEFAULT_DIMENSIONS

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    def describe(self) -> dict:
        return {"name": self.name, "dimensions": self.dimensions, "semantic": False}


class HashingEmbedder(Embedder):
    """Hashed bag-of-tokens with sublinear term frequency, L2 normalised.

    Deterministic across processes and runs, which is what lets the RAG tests
    assert on actual ranking rather than on "something came back".
    """

    name = "hashing"

    def __init__(self, dimensions: int = DEFAULT_DIMENSIONS) -> None:
        self.dimensions = dimensions

    def _bucket(self, token: str) -> int:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        return int.from_bytes(digest, "big") % self.dimensions

    def embed_one(self, text: str) -> list[float]:
        counts: dict[int, float] = {}
        for token in tokenize(text):
            bucket = self._bucket(token)
            counts[bucket] = counts.get(bucket, 0.0) + 1.0

        vector = [0.0] * self.dimensions
        for bucket, count in counts.items():
            # Sublinear scaling: a token repeated twenty times is not twenty
            # times as informative as one used once.
            vector[bucket] = 1.0 + math.log(count)

        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return vector

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_one(text) for text in texts]


class LiteLLMEmbedder(Embedder):
    """Real embeddings via LiteLLM. Not covered by tests -- quota dependent."""

    name = "litellm"

    def __init__(self, model: str | None = None) -> None:
        self.model = model or os.environ.get(
            EMBEDDING_MODEL_ENV_VAR, DEFAULT_EMBEDDING_MODEL
        )
        self.dimensions = 0  # discovered from the first response

    async def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            import litellm
        except ImportError as exc:  # pragma: no cover - optional extra
            raise RuntimeError(
                "SANI_EMBEDDINGS=litellm requires the litellm extra: "
                "uv sync --extra litellm"
            ) from exc

        response = await litellm.aembedding(model=self.model, input=texts)
        vectors = [item["embedding"] for item in response["data"]]
        if vectors:
            self.dimensions = len(vectors[0])
        return vectors

    def describe(self) -> dict:
        return {"name": self.name, "model": self.model, "dimensions": self.dimensions,
                "semantic": True}


def cosine(a: list[float], b: list[float]) -> float:
    """Both sides are stored normalised, so this is just the dot product."""
    return sum(x * y for x, y in zip(a, b))


def build_embedder(kind: str | None = None) -> Embedder:
    resolved = (kind or os.environ.get(EMBEDDINGS_ENV_VAR, "hashing")).lower()
    if resolved == "hashing":
        return HashingEmbedder()
    if resolved == "litellm":
        return LiteLLMEmbedder()
    raise ValueError(f"unknown embedder {resolved!r} (expected 'hashing' or 'litellm')")
