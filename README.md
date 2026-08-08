# Ṣāni' Studio

An agentic coding IDE built on one Python backend, targeting two surfaces: a
VS Code extension and a standalone web IDE.

The design bet is *visible* autonomy rather than maximal autonomy — the plan is
shown before it runs, every tool call is disclosed at the decision point, and
trust is earned per action type rather than granted globally. A fixed
always-confirm tier covers every irreversible action regardless of how much
trust a session has accumulated.

## Status

**Phases 0 and 1 complete.** Agent core, FastAPI server with WebSocket
streaming and approval gating, and a working web IDE. 162 Python tests plus 3
Playwright end-to-end tests that drive a real browser against real servers.

| Phase | Scope | Status |
|---|---|---|
| 0 | Agent core, FastAPI server, WebSocket streaming, approval endpoint | ✅ |
| 1 | Web IDE — Monaco, file tree, sandbox, xterm.js, chat panel | ✅ |
| 2 | VS Code extension — webview chat, native diff integration | — |
| 3 | Codebase RAG — pgvector + tree-sitter | — |
| 3a–3c | Session Manager, background agents, browser subagent | — |
| 4 | Trust ladder UI, design system, image diffs | — |

## Quick start

```bash
# backend
uv sync
uv run uvicorn sani_server.app:app --port 8000

# web IDE
cd apps/web && npm install && npm run dev
```

Open `http://localhost:3000`, describe a task, and watch the plan arrive before
anything runs. Interactive API docs at `http://127.0.0.1:8000/docs`.

Prefer a terminal? `uv run python scripts/ws_client.py --workspace /tmp/demo`
streams the same session and prompts for approvals inline.

⚠️ There is no authentication and the shell tool executes commands. Run it on
localhost only.

## Tests

```bash
uv run pytest                        # 150 tests, ~3s, no network
cd apps/web && npx playwright test   # 3 e2e tests, real browser + real servers
```

## Architecture

```
packages/sani-core/     agent engine — planning, permissions, tools, execution
packages/sani-server/   FastAPI + WebSocket transport, sandbox, session manager
apps/web/               Next.js web IDE — Monaco, xterm.js, chat/plan/diffs dock
apps/vscode/            VS Code extension (Phase 2)
```

`sani-core` has no required third-party dependencies and imports no web
framework, so the same engine backs the server, a CLI, and the tests.

See [CLAUDE.md](./CLAUDE.md) for the full API contract, event protocol, and
safety model.
