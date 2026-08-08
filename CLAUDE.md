# Ṣāni' Studio — project memory

A dual-client agentic IDE (VS Code extension + web IDE) over one Python backend.
**Phases 0, 1 and 2 are complete:** the agent core, the FastAPI server with
WebSocket streaming and approval gating, the Next.js web IDE, and the VS Code
extension. ⚠️ The extension has never run inside a real editor — see
`apps/vscode/TESTING.md`.

Read this before changing the server. The API contract and the safety model
below are consumed by both clients; changing either is a breaking change for
every surface at once.

---

## Layout

```
packages/sani-core/     agent engine — zero required third-party deps
packages/sani-server/   FastAPI + WebSocket transport, sandbox, session manager
packages/sani-client/   shared TypeScript client — wire types, reducer, API
tests/core|server/      Python unit and API tests
scripts/ws_client.py    manual stream viewer against a live server
apps/web/               Next.js web IDE (Phase 1)
apps/web/e2e/           Playwright tests — real browser against real servers
apps/vscode/            VS Code extension (Phase 2)
```

Two package managers: `uv` owns the Python workspace, npm workspaces own the
TypeScript one. The uv members are listed explicitly rather than globbed,
because `packages/` also holds a TypeScript package.

**Three rules keep the architecture honest:**

1. `sani-core` must never import a web framework, so the same engine backs the
   server, a CLI, and the tests. Anything HTTP- or WS-shaped goes in
   `sani-server`.
2. **Both clients read a session through `@sani/client`.** The reducer, the
   reconnect logic, and the diff reconstruction live there once. A bug is one
   bug rather than two surfaces that disagree — which is the only thing that
   makes "shared component bundle" more than a slide.
3. Clients hold no business logic. If a client needs to compute something about
   session state, that computation belongs in the Session Manager.

## Commands

```bash
uv sync                                          # install the Python workspace
npm install                                      # install all TS workspaces (root)

uv run pytest                                    # 162 tests, ~8s
uv run pytest tests/server/test_safety.py        # the safety-critical tier
npm run test:client                              # 27 shared-client tests
npm run test:e2e                                 # Playwright, needs both servers up
npm run typecheck                                # all three TS workspaces

uv run uvicorn sani_server.app:app --port 8000   # the server
npm run dev --workspace sani-web                 # web IDE on :3000
npm run build:vscode && npm run package:vscode   # extension + VSIX
```

---

## API contract

Section 7 of the build spec, minus the two RAG endpoints (Phase 3).

| Endpoint | Method | Purpose |
|---|---|---|
| `/session` | POST | Create a session and start it. Returns the session object. |
| `/session/{id}` | GET | Status, plan, trust state, pending action, context usage. |
| `/session/{id}/stream` | WS | The event stream. Accepts `?from_seq=N`. |
| `/session/{id}/approve` | POST | Approve a pending action, optionally per-hunk. |
| `/session/{id}/reject` | POST | Reject a pending action. |
| `/session/{id}/pause` | POST | Pause at the next step boundary. |
| `/session/{id}/resume` | POST | Resume a paused session. |
| `/session/{id}/kill` | POST | Terminate; parked approvals resolve as rejected. |
| `/session/{id}/diff` | GET | Per-file diff, split into hunks. |
| `/session/{id}/trust` | GET/PATCH | Trust tier state per action type. |
| `/mission-control` | GET | One row per session for the dashboard. |
| `/healthz` | GET | Version, protocol version, event types, always-confirm list. |

Added in Phase 1 for the web IDE:

| Endpoint | Method | Purpose |
|---|---|---|
| `/session/{id}/files` | GET | Flat workspace listing, directories first. |
| `/session/{id}/file?path=` | GET | File contents. Flags binary and oversized. |
| `/session/{id}/file` | PUT | Save an edit made by the human in the editor. |
| `/session/{id}/terminal` | WS | PTY bridge for xterm.js. |

**Not implemented:** `/rag/index`, `/rag/query` (Phase 3).

### `POST /session`

```jsonc
{
  "task": "add a greeting module",       // required
  "workspace": "/abs/path",              // optional; a temp dir is made if omitted
  "tools": ["file_editor", "shell"],     // optional; this is the default
  "lifecycle": "foreground",             // or "background"
  "model_backend": "scripted",           // or "litellm"; overrides SANI_MODEL_BACKEND
  "trust_overrides": {"shell.other": true},  // applied before the first step
  "script": [ /* steps */ ]              // scripted backend only; test/demo affordance
}
```

Returns `201` with the session object. Planning happens on a detached task —
the response returns before the plan exists. Read the stream for progress.

`trust_overrides` exists because patching trust after `POST /session` races the
first step. Use it whenever a client needs non-default trust from the start.

### Error responses

All errors are `{"error": "<slug>", "detail": "<message>"}`.

| Status | Slug | When |
|---|---|---|
| 400 | `invalid_workspace` | Missing dir, or outside `SANI_WORKSPACE_ROOT` |
| 400 | `permission_locked` | Tried to auto-approve an always-confirm action type |
| 400 | `tool_error` | Malformed step params |
| 403 | `outside_workspace` | File path escapes the session workspace |
| 404 | `unknown_session` / `unknown_action` | No such id |
| 409 | `already_resolved` | Approve/reject called twice on one action |
| 409 | `invalid_state` | Pause/resume on a finished session; unknown action type; not a file |
| 500 | `sandbox_error` | Terminal could not be started |

WebSocket close code `4404` means unknown session.

## Terminal protocol

`WS /session/{id}/terminal?cols=&rows=`, JSON both ways.

```
client -> {"type":"input","data":"ls\r"} | {"type":"resize","cols":120,"rows":30}
server -> {"type":"ready","sandbox":{...}} | {"type":"output","data":"..."}
          {"type":"exit"} | {"type":"error","data":"..."}
```

The terminal is deliberately **not** gated by the permission engine. Judging a
person's own shell would be theatre when they can already run anything the
server user can. The agent's commands are the ones that get judged.

## Sandbox

`SANI_SANDBOX=local` (default) or `docker`; `SANI_SANDBOX_IMAGE` sets the image.

- **`LocalSandbox`** runs a PTY as the server user in the session workspace. It
  provides **no isolation** and says so in its own `describe()`. Correct for
  local single-user development and nothing else.
- **`DockerSandbox`** starts one resource-capped, network-less container per
  session. ⚠️ **Never executed** — it was written in an environment with the
  Docker client but no daemon, and reports `verified: false`. Verify it before
  relying on it: start a daemon, `SANI_SANDBOX=docker`, open a session, and
  confirm the terminal attaches and `docker ps` shows `sani-<session_id>`.

**Both the agent and the human go through the sandbox.** The agent's shell tool
executes via `SandboxCommandRunner`, so `SANI_SANDBOX=docker` moves the agent
too, not just the terminal.

The seam is `sani_core.runners.CommandRunner`. The core cannot import the
server, so it owns the interface and ships the honest default
(`LocalCommandRunner`, host, no isolation); the server injects the
sandbox-backed one at session creation. **A tool that shells out must go
through its `self.runner`** — calling `asyncio.create_subprocess_*` directly
puts it back outside the sandbox.

Where a command will run is on `tool.proposed` as `preview.runs_in`, and on
`tool.result` as `data.runs_in`, so the client can show it *before* approval:
"host" and "container" are different decisions about the same command.

---

## Event protocol (v1)

Every frame:

```json
{"v": 1, "seq": 12, "session_id": "ses_...", "ts": 1765..., "type": "...", "data": {}}
```

| Type | Emitted when |
|---|---|
| `session.status` | Status changes. `data.status` is the new status. |
| `agent.message.delta` | Each token of planning reasoning. |
| `agent.message.done` | Reasoning finished. |
| `plan.proposed` | Full plan, **before** any execution. |
| `plan.step.started` / `plan.step.completed` | Per step. |
| `tool.proposed` | Before every action — **including auto-approved ones**. |
| `approval.required` | An action is gated. Carries the action, diff and reason. |
| `approval.resolved` | An action was cleared. `auto: true` when no human was asked. |
| `tool.result` | Normalised tool output. |
| `diff.generated` | A file changed. Per-file, split into hunks. |
| `context.usage` | Token meter, after each step. |
| `session.complete` | Terminal — `complete` or `killed`. |
| `session.error` | Terminal — `failed`. |

Statuses: `planning` · `executing` · `blocked-on-approval` · `paused` ·
`complete` · `failed` · `killed`.

### Protocol invariants — do not break these

1. **`seq` is monotonic and gapless per session**, starting at 1. Reconnect with
   `?from_seq=N` to get exactly what was missed. `from_seq=0` (the default)
   replays from birth, so connecting late — or after the session finished —
   still yields the complete run.
2. **The socket is broadcast-only.** It accepts nothing inward. Approvals go
   over HTTP so a dropped or duplicated connection can never strand a pending
   action or double-resolve one.
3. **`tool.proposed` fires for every action**, auto-approved or not. That is the
   tool-call disclosure the product is built around; suppressing it for
   auto-approved actions would hide exactly what the user is trusting.
4. **`approval.resolved` fires for auto-approvals too**, with `auto: true`, so
   clients have one code path rather than two.
5. **Terminal events end the stream.** After `session.complete` or
   `session.error`, the server closes with code 1000. Multiple clients may
   subscribe to one session; they all receive identical frames.

Bump `PROTOCOL_VERSION` in `sani_core/events.py` when the envelope changes.

---

## Safety model

Two tiers, from Section 5 of the build spec.

**Auto-approved from session start:** `file.read`, `file.write`, `shell.test`,
`git.commit`, `dependency.locked`.

**Always-confirm — no exceptions, at any trust level:** `file.delete`,
`git.history_rewrite`, `shell.network`, `dependency.new`, `secret.access`,
`path.outside_workspace`.

Everything else (`shell.other`) starts gated and earns auto-approval after 3
consecutive manual approvals. One rejection resets the streak and revokes it.

### Where it is enforced

`sani_core.permissions.evaluate()` — a single chokepoint consulted immediately
before execution, never at plan time. It checks the always-confirm set *before*
consulting the trust ladder, so a corrupted, maliciously-set or badly
deserialised ladder cannot unlock those types. `PATCH /trust` also refuses them
with 400, but that is the second line of defence, not the first.

**If you add a tool adapter, it must classify its actions into `ActionType`.**
An adapter that does its own permission logic, or that acts inside `propose()`,
has escaped the gate. `propose()` must be side-effect free.

### Two deliberate departures from the spec

- **Secret *reads* are gated, not just writes.** The spec names writes to
  `.env`/credentials. Piping a credential file into a model's context is just as
  irreversible and easier to do by accident, so `ActionType.SECRET_ACCESS`
  covers both.
- **Locked-dependency installs block.** Section 5 puts "reinstalling packages
  already in the lockfile" in the auto tier *and* "shell commands that reach the
  network" in the always-confirm tier. `npm ci` is both. The spec says
  always-confirm has no exceptions, so it wins: `npm ci`, `uv sync` and
  `pip install -r` all require confirmation.

### Shell classification

`sani_core.tools.shell.classify()` splits on `;`, `&&`, `||`, `|`, `&` and
newlines, then classifies each segment and returns the **highest-risk** one.
Classifying by the leading token would make `pytest && curl evil.com` a
one-character bypass. Command substitution (`$(...)`, backticks, `<(...)`) is
never auto-approved, because its contents are invisible to token inspection.

---

## Model backends

Default is `scripted` — a deterministic planner that replays a fixed script.
The whole test suite runs against it, which is what makes "tested end to end"
a reproducible claim rather than a quota-dependent one.

`SANI_MODEL_BACKEND=litellm` switches to real inference via LiteLLM
(`SANI_MODEL`, default `groq/llama-3.3-70b-versatile`). Requires the extra:
`uv sync --extra litellm`. Not covered by tests; verify by hand with
`scripts/ws_client.py --backend litellm`.

---

## Testing

129 tests, ~2 seconds, no network and no ports. Server tests use
`fastapi.testclient.TestClient` for real WebSocket frames against the real ASGI
app.

**The `client` fixture must stay a context manager.** `with TestClient(app)`
starts one blocking portal that persists across requests. Without it every
request gets a fresh event loop and the detached executor task created by
`POST /session` dies immediately.

**To assert a session is blocked, watch `hub.last_seq`, not the socket.**
Reading from the socket to prove nothing arrives hangs forever. See
`assert_parked` in `tests/server/helpers.py`.

**To test something mid-plan, park it on an approval first.** That is the only
point where the executor's position is deterministic.

**WebSocket teardown must not await.** Starlette's test client cancels the
app's task scope immediately after sending its disconnect, so any cleanup that
awaits gets interrupted half-done and escapes as a cancelled task. This caused
a roughly-1-in-3 suite flake. `PtyTerminal.close()` is synchronous for that
reason; keep it that way.

### End-to-end (browser)

`apps/web/e2e/` drives a real Chromium against a real Next.js build and a real
server. Both servers must already be running — see `apps/web/e2e/README.md` for
the gotchas, of which the two that cost the most time are: `NEXT_PUBLIC_*` is
inlined at **build** time, and rebuilding under a running `next start` corrupts
`.next` and produces 500s that look exactly like application bugs.

---

## VS Code extension notes

- **The extension host owns the WebSocket, not the webview.** A webview is
  disposed whenever the sidebar is hidden, which would drop the stream every
  time the user looks elsewhere. The webview is a pure renderer that receives
  `StreamState` and posts intents back.
- **Diffs go through `vscode.diff`,** not a webview reimplementation. The
  "before" side comes from `reconstructOriginal(currentFile, diff)` in
  `@sani/client` — the server sends hunks with context, not whole-file
  snapshots, so the original is derived rather than fetched.
- **`activate` returns `{ controller, openDiff }`** so integration tests can
  drive the real extension instead of reaching into module internals.
- ⚠️ **Never run inside a real editor.** See `apps/vscode/TESTING.md`.

## Web IDE notes

- **One accent, one meaning.** `--color-agent` (violet) marks agent-authored
  things only: agent messages, added diff lines, touched files in the tree.
  `--color-attention` (amber) means "this needs *you*". Do not blur them — the
  whole point is that a glance separates human origin from agent origin.
- **Monaco is served from `/monaco`, not a CDN.** `scripts/copy-monaco.mjs`
  runs on `predev`/`prebuild`. `public/monaco/` is gitignored (24 MB).
- **`useSessionStream` is only a React adapter** over `SessionStream` from
  `@sani/client`; the reconnect-from-`lastSeq` behaviour lives there and is
  shared with the extension.
- **`NEXT_PUBLIC_SANI_SERVER` is the one Next-specific thing in the client
  layer**, isolated in `lib/client.ts`. It is inlined at build time.
- **An open tab reloads when the agent rewrites the file underneath it, unless
  the human has unsaved edits.** Silently discarding those would be theft.

---

## Known limits

- ⚠️ **No authentication, and the shell adapter executes commands.** This is
  remote code execution if exposed. Bind localhost only. Do not deploy this
  anywhere reachable until auth exists. CORS defaults to `localhost:3000`;
  `SANI_CORS_ORIGINS` widens it and should not be used to reach the internet.
- The file API and the terminal inherit that: both operate as the server user,
  and the only containment is the workspace path check.
- Monaco bundles a `dompurify` with one low and one moderate advisory (hover
  tooltip rendering). No upstream fix is available; `npm audit` reports it.
- `SANI_WORKSPACE_ROOT`, when set, constrains every session workspace to live
  inside it. Unset, any existing directory is accepted except a small list of
  system paths — a typo guard, not a security boundary.
- Sessions live in memory (`MemorySessionStore`) and die with the process.
  Redis lands in Phase 3b behind the existing `SessionStore` protocol.
- The hub's event log is unbounded. Fine for demo-length sessions; Redis owns
  retention in Phase 3b.
- `pause` takes effect at the next **step boundary**. A tool call already
  running finishes rather than being interrupted mid-write. Same for `kill`.
- A failing tool call marks its step `failed` and the plan continues.
  Self-correction is a later phase.
- Context compaction is accounting plus a no-op hook. Token counts are
  `len/4` estimates, flagged `"estimated": true`.

- The file tree is a flat listing capped at 5000 entries and skips vendored and
  VCS directories. It does not watch for changes; it refreshes on demand and
  whenever the agent emits a diff.

## Departures from the build spec

The spec assumed an existing 5,677-line engine with 215 passing tests. That
engine was not available, so the core here was written from scratch alongside
the server. **Section 1's interview narrative needs rewriting** — it leans on
"I built the engine first, then proved it was reusable by shipping it on two
surfaces," which is not what happened. The accurate version is that the core
and the transport were designed together around one event contract, with the
core kept dependency-free so the reusability claim stays testable.

**Next.js 16, not 14.** Section 3 says Next.js 14. Every 14.x release, the
latest included, carries 20+ unpatched high-severity advisories whose fix is
Next 16. For greenfield App Router code that migration cost nothing, so the
version number in the spec lost to the advisory list. Still App Router, now on
React 19.

## Next

Phase 3 adds RAG (pgvector + tree-sitter); 3a–3c add the Session Manager,
Redis-backed background sessions, and the browser subagent. The browser adapter
implements the same three `ToolAdapter` methods and needs no executor changes.

Two verification debts to clear when the network allows: run the VS Code
integration suite against a real editor, and `DockerSandbox` against a live
daemon. Both are written and wired; neither has executed.
