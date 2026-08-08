# Ṣāni' Studio

An agentic coding IDE built on one Python backend, targeting two surfaces: a
VS Code extension and a standalone web IDE.

The design bet is *visible* autonomy rather than maximal autonomy — the plan is
shown before it runs, every tool call is disclosed at the decision point, and
trust is earned per action type rather than granted globally. A fixed
always-confirm tier covers every irreversible action regardless of how much
trust a session has accumulated.

## Status

**Phase 0 complete.** Agent core and FastAPI server with WebSocket streaming
and approval gating. 129 tests. No frontend yet.

| Phase | Scope | Status |
|---|---|---|
| 0 | Agent core, FastAPI server, WebSocket streaming, approval endpoint | ✅ |
| 1 | Web IDE — Monaco, file tree, Docker sandbox, xterm.js | — |
| 2 | VS Code extension — webview chat, native diff integration | — |
| 3 | Codebase RAG — pgvector + tree-sitter | — |
| 3a–3c | Session Manager, background agents, browser subagent | — |
| 4 | Trust ladder UI, design system, image diffs | — |

## Quick start

```bash
uv sync
uv run pytest
uv run uvicorn sani_server.app:app --port 8000
```

Then watch a session run, approving gated actions as they come up:

```bash
uv run python scripts/ws_client.py --workspace /tmp/demo
```

Interactive API docs at `http://127.0.0.1:8000/docs`.

⚠️ Phase 0 has no authentication and the shell tool executes commands. Run it
on localhost only.

## Architecture

```
packages/sani-core/     agent engine — planning, permissions, tools, execution
packages/sani-server/   FastAPI + WebSocket transport, session manager
apps/                   web IDE (Phase 1), VS Code extension (Phase 2)
```

`sani-core` has no required third-party dependencies and imports no web
framework, so the same engine backs the server, a CLI, and the tests.

See [CLAUDE.md](./CLAUDE.md) for the full API contract, event protocol, and
safety model.
