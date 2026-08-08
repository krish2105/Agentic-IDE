"""Split a codebase into retrievable chunks.

Spec Section 3 asks for tree-sitter chunking by function and class, and the
reason is worth stating: a fixed-size window cuts a function in half, so the
retrieved text is missing either the signature that says what it is or the body
that says what it does. Syntactic boundaries keep a chunk self-explanatory.

Files whose language has no grammar available fall back to overlapping line
windows -- worse retrieval, but degraded coverage rather than a crash.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: File extension -> tree-sitter language name.
LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".php": "php",
    ".sh": "bash",
}

#: Node types worth keeping as their own chunk, across the grammars above.
CHUNK_NODE_TYPES = frozenset(
    {
        "function_definition",
        "function_declaration",
        "function_item",
        "method_definition",
        "method_declaration",
        "class_definition",
        "class_declaration",
        "class_specifier",
        "struct_item",
        "impl_item",
        "interface_declaration",
        "type_alias_declaration",
        "enum_declaration",
        "module",
        "decorated_definition",
        "lexical_declaration",
        "export_statement",
    }
)

#: Node types that carry a readable name for the chunk.
NAME_FIELDS = ("name", "declarator", "pattern")

MAX_CHUNK_LINES = 120
WINDOW_LINES = 60
WINDOW_OVERLAP = 10
MAX_FILE_BYTES = 400_000


@dataclass(slots=True)
class Chunk:
    path: str
    text: str
    start_line: int
    end_line: int
    kind: str = "block"
    name: str | None = None

    @property
    def id(self) -> str:
        return f"{self.path}:{self.start_line}-{self.end_line}"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "path": self.path,
            "name": self.name,
            "kind": self.kind,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "text": self.text,
        }

    @property
    def label(self) -> str:
        """What a planner sees above the snippet."""
        where = f"{self.path}:{self.start_line + 1}"
        return f"{where} ({self.kind} {self.name})" if self.name else where


def grammars_available() -> bool:
    """Whether tree-sitter parsing is usable in this install.

    Without it every file falls back to line windows, which still works but
    retrieves noticeably worse. Silently degrading would leave someone
    wondering why results got vague after a deploy.
    """
    try:
        from tree_sitter_language_pack import get_parser

        get_parser("python")
        return True
    except Exception:
        return False


def language_for(path: str | Path) -> str | None:
    return LANGUAGE_BY_SUFFIX.get(Path(path).suffix.lower())


def _window_chunks(relpath: str, text: str, kind: str = "window") -> list[Chunk]:
    lines = text.splitlines()
    if not lines:
        return []

    chunks: list[Chunk] = []
    step = max(WINDOW_LINES - WINDOW_OVERLAP, 1)
    for start in range(0, len(lines), step):
        window = lines[start : start + WINDOW_LINES]
        if not window or not "".join(window).strip():
            continue
        chunks.append(
            Chunk(
                path=relpath,
                text="\n".join(window),
                start_line=start,
                end_line=start + len(window) - 1,
                kind=kind,
            )
        )
        if start + WINDOW_LINES >= len(lines):
            break
    return chunks


def _named_node(node):
    """Unwrap a decorated definition to the thing being defined.

    ``@dataclass class Foo`` parses as a decorated_definition whose own name
    field is empty; the label a reader needs is on the inner node.
    """
    if node.type in ("decorated_definition", "export_statement"):
        for child in node.children:
            if child.type in CHUNK_NODE_TYPES and child.type != node.type:
                return child
    return node


def _node_name(node, source: bytes) -> str | None:
    node = _named_node(node)
    for field in NAME_FIELDS:
        try:
            child = node.child_by_field_name(field)
        except Exception:
            child = None
        if child is not None:
            return source[child.start_byte : child.end_byte].decode(
                "utf-8", errors="replace"
            ).strip()
    return None


def chunk_source(relpath: str, text: str) -> list[Chunk]:
    """Chunk one file, preferring syntactic boundaries."""
    language = language_for(relpath)
    if language is None:
        return _window_chunks(relpath, text, kind="text")

    try:
        from tree_sitter_language_pack import get_parser

        parser = get_parser(language)
    except Exception:
        # No grammar for this language in this install: degrade, do not fail.
        return _window_chunks(relpath, text)

    source = text.encode("utf-8", errors="replace")
    try:
        tree = parser.parse(source)
    except Exception:
        return _window_chunks(relpath, text)

    chunks: list[Chunk] = []
    covered: set[int] = set()

    def visit(node, depth: int = 0) -> None:
        # The root node carries the whole file, so it is never a chunk itself.
        if node.type in CHUNK_NODE_TYPES and node.parent is not None:
            start, end = node.start_point[0], node.end_point[0]
            # Multi-line, or a single line long enough to be worth retrieving
            # on its own -- a one-line arrow export is real code, `export {}`
            # is noise.
            if end > start or (node.end_byte - node.start_byte) >= 40:
                body = source[node.start_byte : node.end_byte].decode(
                    "utf-8", errors="replace"
                )
                name = _node_name(node, source)
                if end - start > MAX_CHUNK_LINES:
                    # A very long function still beats a window, but not by
                    # enough to justify handing a planner 900 lines.
                    for piece in _window_chunks(relpath, body, kind=node.type):
                        piece.start_line += start
                        piece.end_line += start
                        piece.name = name
                        chunks.append(piece)
                else:
                    chunks.append(
                        Chunk(
                            path=relpath,
                            text=body,
                            start_line=start,
                            end_line=end,
                            kind=_named_node(node).type,
                            name=name,
                        )
                    )
                covered.update(range(start, end + 1))
                return  # nested definitions stay inside their parent chunk

        for child in node.children:
            visit(child, depth + 1)

    visit(tree.root_node)

    # Anything outside a definition -- imports, constants, top-level script --
    # is still worth retrieving. Runs are bounded by *covered* lines rather
    # than by blank ones, so a blank line between imports does not shatter them
    # into a dozen one-line chunks that retrieve badly.
    lines = text.splitlines()
    run_start: int | None = None
    for index in range(len(lines) + 1):
        uncovered = index < len(lines) and index not in covered
        if uncovered and run_start is None:
            run_start = index
            continue
        if uncovered or run_start is None:
            continue

        body_lines = lines[run_start:index]
        # Trim the blank lines that sit against a definition boundary.
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)
            run_start += 1
        while body_lines and not body_lines[-1].strip():
            body_lines.pop()

        if body_lines:
            chunks.append(
                Chunk(
                    path=relpath,
                    text="\n".join(body_lines),
                    start_line=run_start,
                    end_line=run_start + len(body_lines) - 1,
                    kind="module",
                )
            )
        run_start = None

    if not chunks:
        return _window_chunks(relpath, text)
    return sorted(chunks, key=lambda c: c.start_line)
