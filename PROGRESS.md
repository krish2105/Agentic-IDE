# Ṣāni' Studio — progress

**Last updated:** 8 August 2026 · branch `claude/sani-fastapi-server-phase-0-56vmdc`

An agentic coding IDE on two surfaces — a web IDE and a VS Code extension —
over one Python backend. Built against the master spec's phased roadmap
(Section 9).

---

## Where it stands

| Phase | Scope | Status |
|---|---|---|
| **0** | Agent core, FastAPI server, WebSocket streaming, approval endpoint | ✅ Done |
| **1** | Web IDE — Monaco, file tree, sandbox, xterm.js, chat panel | ✅ Done |
| **2** | VS Code extension — sidebar, native diff, gutter marks | ⚠️ Built, unproven in a real editor |
| — | *Extra:* agent shell routed through the sandbox | ✅ Done |
| **3** | Codebase RAG — pgvector + tree-sitter | ⬜ Not started |
| **3a** | Session Manager — parallel sessions, Mission Control v1 | 🟡 Partly done |
| **3b** | Redis job queue — background persistence, reattach | 🟡 Groundwork done |
| **3c** | Browser subagent — Playwright adapter, vision routing | ⬜ Not started |
| **4** | Trust ladder UI, design polish, image diffs, demo recordings | 🟡 Partly done |

**Roughly 3,600 lines of Python, 3,000 of TypeScript, 1,600 of Python tests.**

---

## What works today

Start the backend, open the web IDE, describe a task. You get a plan **before**
anything runs, watch each step execute, and get stopped when the agent tries
something irreversible. Approve or reject — per diff hunk if you want. The
editor, file tree and terminal all point at the same workspace the agent is
editing.

### The safety model

This is the core of the product, not a feature bolted on.

- **Auto-approved from the start:** reading files, writing inside the
  workspace, running tests/lint, git commits, locked dependency installs.
- **Always requires confirmation, at any trust level:** deleting files, git
  history rewrites, network commands, new dependencies, touching secrets, any
  path outside the workspace.
- **Everything else** starts gated and earns auto-approval after 3 consecutive
  manual approvals. One rejection revokes it.

Enforced at a single chokepoint immediately before execution, and the
always-confirm check runs *before* the trust ladder is consulted — so a
corrupted or maliciously-set trust state cannot unlock it. There are tests that
force every unlockable tier on and confirm each irreversible action still stops.

### The event protocol

One versioned, gapless event stream per session. Both clients render it and
nothing else. Reconnect with `?from_seq=N` and the server replays exactly what
was missed — the client drops any overlap, so replay is idempotent.

This is what Phase 3b's background sessions will reattach through. It was
cheap to build in Phase 0 and would have been expensive to retrofit.

---

## Verification

| Suite | Count | What it proves |
|---|---|---|
| Python | **162** | Core logic, API contract, safety tier, real WebSocket frames |
| Shared client | **27** | Event reducer, reconnect/replay, diff reconstruction |
| — of those, live | 3 | Real server over a real WebSocket |
| Playwright | **3** | Real Chromium, real Next build, real server |
| VS Code integration | 5 | ⚠️ **Written but never executed** — see below |

```bash
uv run pytest          # 162 tests, ~8s, no network
npm run test:client    # 27 tests; 3 use a live server if one is running
npm run test:e2e       # 3 browser tests; both servers must be up
npm run typecheck      # all three TypeScript workspaces
```

The Playwright suite drives the actual product: create a session, watch the
plan stream in, get blocked by an irreversible delete, approve it, see the file
land in Monaco and the terminal. Screenshots are committed in
`apps/web/e2e/screenshots/`.

---

## What is left

### Phase 3 — Codebase RAG (not started)
pgvector + tree-sitter chunking by function/class, retrieval injected into the
planning step. The largest genuinely new piece of work remaining.

### Phase 3a — Session Manager (partly done)
The server already runs multiple sessions in parallel and `/mission-control`
returns one row per session. **Left:** a session tab strip in the web IDE, and
a richer Mission Control view than the current list.

### Phase 3b — Background sessions (groundwork done)
Sessions sit behind a `SessionStore` protocol with an in-memory implementation,
and the event log already supports reattach-after-disconnect. **Left:** the
Redis-backed store and worker, so sessions survive the server process and
notify on completion.

### Phase 3c — Browser subagent (not started)
A Playwright-backed tool adapter. It implements the same three methods
(`propose` / `execute` / `result`) as the file and shell tools and needs no
executor changes — that was the point of the adapter interface. Also needs
vision-capable model routing, which depends on free-tier quota.

### Phase 4 — Polish (partly done)
Dark-first design system and the single-accent rule are in and enforced.
**Left:** a trust ladder UI (the API exists, nothing renders it), image diff
previews, and demo recordings.

---

## Open debts — read before demoing

**Two things are written and wired but have never executed:**

1. **The VS Code extension in a real editor.** It compiles, typechecks and
   packages to a VSIX, and its logic is covered by the shared-client tests. But
   the integration suite needs to download VS Code, which the build environment
   could not reach. That leaves activation, command registration, the webview
   provider, the `vscode.diff` call and the decoration API unproven. One command
   fixes this on any normal machine — see `apps/vscode/TESTING.md`.

2. **The Docker sandbox against a live daemon.** Written in an environment with
   the Docker client but no daemon. It reports `verified: false` in its own
   description rather than letting anything assume otherwise. The local sandbox
   (no isolation, and it says so) is the tested default.

**Known limitations, all deliberate:**

- ⚠️ **No authentication, and the agent can run shell commands.** This is remote
  code execution if exposed. Localhost only. Do not deploy it anywhere
  reachable until auth exists.
- Sessions live in memory and die with the server process (Redis is 3b).
- The event log is unbounded — fine for demo-length sessions.
- `pause` and `kill` take effect at the next step boundary; a tool call already
  running finishes rather than being interrupted mid-write.
- A failing tool call marks its step failed and the plan continues.
  Self-correction is a later phase.
- Context compaction is accounting plus a no-op hook; token counts are
  estimates and flagged as such.
- Monaco bundles a `dompurify` with one low and one moderate advisory. No
  upstream fix exists.

---

## Two places the spec no longer matches reality

**Section 1's interview narrative needs rewriting.** It says the agent engine
was built first and then proven reusable by shipping it on two surfaces. That
is not what happened — the engine was not available, so the core and the
transport were designed together around one event contract. The accurate and
still-strong version: the core is dependency-free and imports no web framework,
which is what makes the reusability claim testable rather than asserted. Both
clients now read sessions through one shared reducer, so "shared component
bundle" is a fact about the code rather than a line on a slide.

**Next.js 16, not the spec's Next.js 14.** Every 14.x release, including the
latest, carries 20+ unpatched high-severity advisories whose fix is Next 16.
For greenfield App Router code that migration cost nothing. Still App Router,
now on React 19.

---

## Architecture

```
packages/sani-core/     agent engine — planning, permissions, tools, execution
                        zero required third-party dependencies
packages/sani-server/   FastAPI + WebSocket, sandbox, session manager
packages/sani-client/   shared TypeScript client — both surfaces read a session
                        through the same reducer, so they cannot drift
apps/web/               Next.js web IDE — Monaco, xterm.js, chat/plan/diffs
apps/vscode/            VS Code extension — sidebar, native diff, gutter marks
```

Three rules hold it together:

1. **`sani-core` never imports a web framework.** The same engine backs the
   server, a CLI and the tests.
2. **Both clients read sessions through `@sani/client`.** A bug there is one
   bug, not two clients that disagree.
3. **Clients hold no business logic.** If a client needs to compute something
   about session state, that belongs in the Session Manager.

Full API contract, event protocol and safety model: [CLAUDE.md](./CLAUDE.md).

---

## Running it

```bash
uv sync && npm install

uv run uvicorn sani_server.app:app --port 8000   # backend
npm run dev --workspace sani-web                 # web IDE on :3000
```

Open `http://localhost:3000`. For the extension:
`npm run build:vscode && npm run package:vscode`, then install the VSIX.

Prefer a terminal? `uv run python scripts/ws_client.py --workspace /tmp/demo`
streams a session and prompts for approvals inline.

---

## Suggested next step

**Phase 3 (RAG)** is the biggest remaining feature and benefits both clients at
once, since retrieval happens server-side during planning.

Cheaper and worth doing first if you have a machine with normal network access:
run the two unexecuted test suites. That converts the project's two standing
"written but unproven" caveats into either green checkmarks or a short bug list
— and it is the difference between demoing something you know works and
something you believe works.
