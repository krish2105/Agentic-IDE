# Ṣāni' Studio — project memory

A dual-client agentic IDE (VS Code extension + web IDE) over one Python backend.
**Every phase in the roadmap is built:** the agent core, the FastAPI server,
the web IDE, the VS Code extension, codebase RAG, Redis-backed session
persistence, the browser subagent, and the trust/Mission Control UI. ⚠️ One
thing is written but unverified — `DockerSandbox` against a daemon. It says so
in its own `describe()`. (Two others used to be on this list. `PgVectorStore`
against Postgres was run against a live Postgres+pgvector and now has a real
test to prove it: `tests/core/test_pgvector_store.py`. The VS Code extension
was run inside a real VS Code and all 7 integration tests pass — see
`apps/vscode/TESTING.md`, which also documents a real `@vscode/test-electron`
version bug that surfaced only by actually running it.)

Read this before changing the server. The API contract and the safety model
below are consumed by both clients; changing either is a breaking change for
every surface at once.

---

## Layout

```
packages/sani-core/     agent engine — zero required third-party deps
packages/sani-server/   FastAPI + WebSocket transport, sandbox, session manager
packages/sani-client/   shared TypeScript client — wire types, reducer, API
packages/sani-core/rag/ chunking, embeddings, vector store, retrieval
tests/core|server/      Python unit and API tests
scripts/serve.sh        start the server with token, CORS and backend set
scripts/ws_client.py    manual stream viewer against a live server
apps/web/               Next.js web IDE (Phase 1)
apps/web/e2e/           Playwright tests — real browser against real servers
apps/vscode/            VS Code extension (Phase 2)
apps/web/components/    session tabs, trust ladder, image diffs (Phase 3a/4)
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

uv run pytest                                    # 361 tests, ~34s
uv run pytest tests/server/test_safety.py        # the safety-critical tier
npm run test:client                              # 45 shared-client tests (needs Node 22.6+)
npm run test:e2e                                 # 32 Playwright tests; both servers up
npm run typecheck                                # all three TS workspaces

./scripts/serve.sh                               # the server (token, CORS, backend)
uv run uvicorn sani_server.app:app --port 8000   # ...or bare, no auth
npm run dev --workspace sani-web                 # web IDE on :3000
npm run build:vscode && npm run package:vscode   # extension + VSIX
```

---

## API contract

Section 7 of the build spec, complete.

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
| `/session/{id}/file/raw?path=` | GET | File bytes with a content type, for images. |

Added in Phase 3 for RAG:

| Endpoint | Method | Purpose |
|---|---|---|
| `/rag/index` | POST | (Re)index a workspace. Takes `workspace` or `session_id`. |
| `/rag/query` | POST | Retrieve chunks. The same call the planner makes. |
| `/rag/status` | GET | What is indexed, and what is doing the indexing. |

Added in Phase 3 (v2) for replay:

| Endpoint | Method | Purpose |
|---|---|---|
| `/session/{id}/timeline` | GET | The replayable log plus computed keyframes. Takes `from_seq`. |
| `/provenance` | GET | Line-level attribution per workspace. Takes `workspace` or `session_id`. |
| `/race` | POST/GET | Start or list parallel agent races. |
| `/race/{id}` | GET | Per-racer progress board. |
| `/race/{id}/discard` | POST | End a race, optionally naming the racer you kept. |

The Section 7 contract is now complete.

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

`SANI_SANDBOX=local` (default), `docker`, or `sandbox-exec`; `SANI_SANDBOX_IMAGE`
sets the Docker image.

- **`LocalSandbox`** runs a PTY as the server user in the session workspace. It
  provides **no isolation** and says so in its own `describe()`. Correct for
  local single-user development and nothing else.
- **`DockerSandbox`** starts one resource-capped, network-less container per
  session. ⚠️ **Never executed** — it was written in an environment with the
  Docker client but no daemon, and reports `verified: false`. Verify it before
  relying on it: start a daemon, `SANI_SANDBOX=docker`, open a session, and
  confirm the terminal attaches and `docker ps` shows `sani-<session_id>`.
- **`SandboxExecSandbox`** runs commands under a macOS Seatbelt profile via
  `sandbox-exec` — no daemon, no image, no per-session process. It denies all
  filesystem writes and all network access by default, then re-opens writes to
  exactly the session workspace and a per-sandbox scratch directory (exported
  as `TMPDIR`, so ordinary tools have somewhere to put temp files). **Verified
  in this environment** — `tests/server/test_sandbox_exec.py` runs its live
  tests for real whenever the suite executes on Darwin with `sandbox-exec`
  present, and skips them otherwise (same pattern `test_redis_sessions.py`
  uses for `redis-server`). Darwin only, and unlike Docker it has **no
  memory/CPU/process-count ceiling** — Seatbelt confines *where* a command can
  read, write, and connect, not how much of the machine it can consume.

**Both the agent and the human go through the sandbox.** The agent's shell tool
executes via `SandboxCommandRunner`, so switching `SANI_SANDBOX` moves the
agent too, not just the terminal.

The seam is `sani_core.runners.CommandRunner`. The core cannot import the
server, so it owns the interface and ships the honest default
(`LocalCommandRunner`, host, no isolation); the server injects the
sandbox-backed one at session creation. **A tool that shells out must go
through its `self.runner`** — calling `asyncio.create_subprocess_*` directly
puts it back outside the sandbox.

Where a command will run is on `tool.proposed` as `preview.runs_in`, and on
`tool.result` as `data.runs_in`, so the client can show it *before* approval:
"host" and "container" are different decisions about the same command.

## Session persistence (Phase 3b)

`SANI_SESSION_STORE=memory` (default) or `redis`; `SANI_REDIS_URL` sets the URL.

The split matters: the **store** keeps runtime handles (executor task, sandbox,
PTY) and is always in memory, because those are process-local by nature. The
**archive** keeps the record — a session snapshot and the ordered event log —
and is what Redis backs. Without an archive the server behaves exactly as it
did in Phase 0.

With Redis: a session survives the process, a second server instance can replay
and live-stream a session it never created, and a restart marks anything that
was mid-flight as `failed` with a reason rather than leaving it looking live.
Restored sessions are `detached` — readable history with no executor, so
pause/resume/approve return 409.

**Two writes are awaited, everything else is queued.** Event writes go through a
single ordered writer per session (concurrent writes to one list arrive out of
order, and a replayed log with holes is worse than a slow one). Both the log
flush and the snapshot are awaited on the terminal event, because another
process may read the session the instant it sees `session.complete`.

## Codebase RAG (Phase 3)

`SANI_EMBEDDINGS=hashing` (default) or `litellm`;
`SANI_VECTOR_STORE=memory` (default) or `pgvector`.

Chunking is tree-sitter by function and class, because a fixed window cuts a
function in half and the retrieved text then lacks either the signature or the
body. Code outside a definition is swept into its own chunks, with runs bounded
by definitions rather than blank lines.

**The default embedder is lexical, not semantic**, and `describe()` and
`/rag/status` both say so. It matches identifiers — most of the signal in code
search — but will not connect "authorise" to `check_permission`. It is the
default because the suite must be reproducible with no API keys.

`PgVectorStore` is verified against a real Postgres 17 + pgvector —
`tests/core/test_pgvector_store.py` runs it for real whenever one is
reachable on `localhost:5432` and skips otherwise, the same "skip, don't fake"
rule `test_redis_sessions.py` uses for `redis-server`. Install it with
`uv sync --extra pgvector`.

Retrieval is per workspace, not per session, and is applied automatically to
any session whose workspace is indexed. It emits `rag.retrieved` before
`plan.proposed` — code silently steering a plan is the same opacity the
approval gate exists to stop. It is also best-effort: an index failure returns
empty rather than failing the run.

## Browser subagent (Phase 3c)

`BrowserTool` implements the same `propose`/`execute`/`result` as every other
adapter and needed **no executor changes** — that is the architectural claim the
three-stretch-features argument rests on.

Ops: `goto`, `click`, `fill`, `text`, `assert_text`, `screenshot`. Verification
is DOM-based and deterministic, because a self-correct loop needs a real
assertion rather than a screenshot to squint at. Vision-model interpretation is
the quota-dependent part of Section 3c and is not claimed as tested.

Screenshots land in `.sani/artifacts` **inside** the workspace, so the file tree
and file API already surface them. `ToolAdapter.aclose()` exists because this
tool holds a whole Chromium; the executor calls it whenever a session ends.

---

## Authentication

`SANI_AUTH_TOKEN` unset (default) leaves the server open; set, it requires
`Authorization: Bearer <token>` on every route except `/healthz`.

**It is pure ASGI middleware, deliberately.** FastAPI dependencies and
`BaseHTTPMiddleware` never see WebSocket connections, so guarding only the HTTP
routes would leave `/stream` and `/terminal` open — and `/terminal` is a shell.
Anything that authenticates this server must sit below the protocol split.

Browsers cannot set headers on a WebSocket handshake, so sockets accept
`?token=`. That puts the token in access logs; the alternative was an
unauthenticated terminal. `rawFileUrl` does the same, for `<img src>`.

`/healthz` reports `auth.required` so a client can tell "no token needed" from
"your token was wrong".

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
| `rag.retrieved` | Code was read from the index, **before** planning. |
| `risk.assessed` | Blast radius for an action, **before** `approval.required`. |
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

### Replay (v2)

`GET /session/{id}/timeline` returns the same log the stream replays from, so
the scrubber and a reconnecting client can never disagree about what happened.
Keyframes -- the handful of seqs worth jumping between -- are computed in
`sani_core.replay`, **not** in a client: two surfaces deciding independently
what "mattered" in a run is two chances to decide differently.

The client folds history through the *same* `reduceEvent` it uses live
(`foldTo` in `@sani/client`). A replay that folded its own way would be a
second definition of what a session is, free to drift, and the bug would
surface as "the scrubber disagrees with the live view".

While scrubbing, `pending` is forced to null. An approval from the past is
history, not a live decision, and must never render actionable buttons.

6. **New event *types* are additive, not breaking.** `rag.retrieved` was added
   in Phase 3 without a version bump: the envelope is unchanged and clients
   ignore types they do not know (there is a test for that). Bump
   `PROTOCOL_VERSION` in `sani_core/events.py` only when the envelope changes.

---

## Safety model

Two tiers, from Section 5 of the build spec.

**Auto-approved from session start:** `file.read`, `file.write`, `shell.test`,
`git.commit`, `dependency.locked`.

**Always-confirm — no exceptions, at any trust level:** `file.delete`,
`git.history_rewrite`, `shell.network`, `dependency.new`, `secret.access`,
`path.outside_workspace`, and `browser.navigate_external`.

That last one is a seventh, added in Phase 3c. Section 5's list predates the
browser tool; driving a browser to a remote URL has the same blast radius as
`curl`. **Extending this tier is allowed, removing from it is not.**

Everything else (`shell.other`, `browser.action`) starts gated and earns
auto-approval after 3 consecutive manual approvals. One rejection resets the
streak and revokes it.

`TrustLadder.from_dict` re-derives `auto_approve` through the always-confirm
check rather than trusting the stored flag. Once a snapshot has been through
Redis it is untrusted input, and that is the one place a corrupted record could
otherwise widen the tier.

### Parallel agent race (v2)

`POST /race` runs N agents at one task, each in its own **git worktree** so they
cannot see each other's edits and the losers are discarded by deleting a
directory rather than unpicking a merge.

**The workspace must be a git repository**, and that is refused plainly rather
than degrading to something that looks like it worked — a user who thinks their
agents are isolated when they are not is worse off than one told no.

Every racer is a normal session behind the same approval gate and risk scoring.
Parallelism must never become a way to launder autonomy past the thing that
makes this product trustworthy; there is a test asserting the always-confirm
tier is intact inside a racer.

**Winner selection is deliberately not automated.** Choosing the best solution
is the judgement the human is here for. Merging is not done for you either —
that is history-touching and belongs behind the gate, not a side effect of
closing a dialog.

⚠️ **The agent does not commit, so a racer's work is uncommitted in its
worktree — the branch tip does not contain it.** Keeping a racer therefore
removes the *losers'* worktrees and branches but leaves the winner's worktree in
place: deleting it would delete the very thing that was kept, and telling
someone to "merge the branch" would send them to an empty ref. The UI says
`uncommitted` and names the worktree path for this reason.

Capped at 6 racers: reviewing eight divergent solutions costs more human
attention than the parallelism saves.

### Provenance (v2)

`sani_core.provenance` answers "which lines did the agent write, which did
you". It is **derived from the diffs the agent already emitted**, not tracked in
a parallel structure — the diffs are the record, and this is a projection of
them, so the two cannot disagree.

Attribution is stored per line, not as ranges. Ranges are more compact but far
harder to remap correctly, and remapping correctness is the whole feature;
ranges are derived on the way out for the UI.

**The honesty rule:** attribution that silently drifts is worse than none,
because it still looks authoritative. So a human editing around agent code
carries the attribution forward (a human adding an import above a function has
not un-written that function) but pays a confidence decay, and past a floor the
claim is dropped entirely rather than guessed at.

Per workspace, not per session — several sessions edit one repo over time, and
the reviewer's question is about the repo.

### Self-critique (v2)

`sani_core.critic` reviews a diff before it reaches the human, targeting the
documented top failure of 2026 agentic coding: output that *looks* right.

Advisory and off by default. It cannot approve, reject or delay anything, it
costs a second inference that shows up in the meter, and `ScriptedCritic` keeps
the suite reproducible with no API key — the same reasoning as the scripted
planner.

### Blast radius (v2)

`sani_core.risk.assess()` scores a proposed action before anything runs: what
it reaches, how much changes, whether it can be undone. It rides on
`risk.assessed`, emitted immediately before `approval.required` so a client can
render the stakes and the request together.

**It is advisory and must stay that way.** It never gates, never widens the
always-confirm tier, and never auto-approves — `permissions.evaluate()` remains
the only chokepoint. There is a test asserting a score changes no decision.

It runs on the proposal only, because `propose()` is side-effect free: nothing
in `risk.py` may execute, fetch, or mutate anything.

The factors are the feature; the score is only their summary. A bare number is
something to click past, which is the failure this exists to prevent.

### Cost (v2)

`sani_core.pricing` turns the token meter into money, shipped on
`context.usage` rather than its own event — they are the same measurement, and
splitting them would let a client show tokens and spend from different moments.

**An unpriced model reports `total_usd: null`, never `0.0`.** Zero would read as
"this was free", which is a different and wrong claim. Totals built from
estimated token counts are flagged `estimated` and rendered with a `~`.

### Presence (v2)

Watcher counts ride on `GET /session/{id}` and the mission-control rows, **not**
on the event stream. The log is history — what the agent did, replayable
forever. Who happens to be watching is ephemeral state about right now, and
putting it in the log would make a replay re-enact viewers arriving and
leaving. There is a test asserting presence never reaches the log.

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

**`scripts/serve.sh` is how the server should be started.** It reads the auth
token and the Groq key from files under `~/.sani/` (generating the token if
absent), picks the backend from whether `~/.sani/groq-key` exists, sets CORS,
and prints which backend it chose. Secrets stay out of shell history and out of
rc files, and the three settings that fail *invisibly* when wrong — token, CORS,
backend — stop being reassembled by hand on every restart.

**The scripted backend ignoring your task is the single most confusing thing
here.** Ask it for a readme and it will report a plan about a greeting module,
because it replays a fixed script; nothing errors and nothing says why. The
banner now names the backend for exactly that reason. A missing key defaults to
`scripted` rather than failing, because the suite must run with no credentials —
but that trade is only defensible if the choice is visible.

A bad key is not silent: the planning call fails and the session ends `failed`
with the provider's own message (`GroqException - Invalid API Key`), which is
the useful signal.

---

## Testing

361 Python tests, ~34 seconds, no network and no ports. Server tests use
`fastapi.testclient.TestClient` for real WebSocket frames against the real ASGI
app. Plus 45 shared-client tests, 32 Playwright tests, and 7 VS Code
integration tests.

**`npm run test:client` needs Node 22+** — it runs `node --test
--experimental-strip-types`. On Node 20 it fails with `bad option`, which looks
like a broken script and is not one.

### ⚠️ `ModuleNotFoundError: No module named 'sani_server'` — it is macOS, not uv

Diagnosed properly after roughly eight rebuilds. **The `.venv` tree gets macOS's
`UF_HIDDEN` flag set on it, and CPython's `site.addpackage` silently skips
hidden `.pth` files.** The editable installs stop being found; nothing reports
an error.

It is maximally deceptive: the `.pth` files exist, contain the right absolute
path, and that path exists. `site.addsitedir()` called by hand still refuses to
add it. Only `os.lstat(...).st_flags` shows why.

```bash
ls -lO .venv/lib/python3.12/site-packages | head    # "hidden" in column 5
chflags -R nohidden .venv                           # the actual fix, instant
```

**Do not `rm -rf .venv && uv sync` for this.** It appears to work only because
fresh files are not hidden yet, and the flag comes back — which is exactly why
it kept recurring. `chflags` repairs it in place with no reinstall.

The flag was applied *after* the venv was created, minutes later, to all 149
files at once. The cause was iCloud: the checkout used to live under
`~/Desktop`, and iCloud Desktop-and-Documents sync is on for this machine.

**The repo now lives in `~/Projects/`, which iCloud does not sync.** Keep it out
of `~/Desktop` and `~/Documents` — both are mirrored. A venv cannot survive in
an iCloud-synced directory anyway: sync also evicts files to make space and
rewrites them, which a virtualenv full of absolute paths and binaries will not
tolerate.

If the symptom ever returns, check the flag first (`ls -lO`) before touching the
environment. A fresh `uv sync` will "fix" it and mislead you.

**The `client` fixture must stay a context manager.** `with TestClient(app)`
starts one blocking portal that persists across requests. Without it every
request gets a fresh event loop and the detached executor task created by
`POST /session` dies immediately.

**To assert a session is blocked, watch `hub.last_seq`, not the socket.**
Reading from the socket to prove nothing arrives hangs forever. See
`assert_parked` in `tests/server/helpers.py`.

**To test something mid-plan, park it on an approval first.** That is the only
point where the executor's position is deterministic.

**`SessionStream.connect()` clears a prior `dispose()`.** React runs effects
mount → cleanup → mount in development, and the adapter memoises the stream per
session id, so the same object is disposed and then reconnected. Treating
dispose as permanent made that second connect a silent no-op and left the whole
session view blank -- in dev only, which is where it hides longest. There is a
regression test.

**WebSocket teardown must not await.** Starlette's test client cancels the
app's task scope immediately after sending its disconnect, so any cleanup that
awaits gets interrupted half-done and escapes as a cancelled task. This caused
a roughly-1-in-3 suite flake. `PtyTerminal.close()` is synchronous for that
reason; keep it that way.

### End-to-end (browser)

`apps/web/e2e/` drives a real Chromium against a real Next.js build and a real
server: `ide.spec.ts` (plan → gate → approve), `redesign.spec.ts` (risk,
replay, cognition graph, themes, race) and `a11y.spec.ts` (axe on every theme,
keyboard, reduced motion, 375px). Both servers must already be running.

**Every environment mistake here fails identically** — a 60-second selector
timeout naming a component that was never at fault. `e2e/preflight.ts` runs
first and turns the two common ones into a one-second error that states the
fix:

- **CORS silently breaks only half the app.** The server allows `:3000` by
  default; the WebSocket is *not* CORS-checked, so with the wrong origin the
  stream connects and the plan renders while every `fetch` is blocked. The file
  tree, trust panel and diffs come up empty and look like three broken
  components. Pass `SANI_CORS_ORIGINS=<web origin>`.
- **`allowedDevOrigins` in `next.config.mjs`.** Next 16 serves
  `/_next/static/*` in dev only to hosts it recognises, and `127.0.0.1` is not
  `localhost` to that check. A blocked host 403s every chunk, so the page
  server-renders and never hydrates — correct-looking DOM, nothing works.

See `apps/web/e2e/README.md` for the rest, of which the two that cost the most
time are: `NEXT_PUBLIC_*` is inlined at **build** time, and rebuilding under a
running `next start` corrupts `.next` and produces 500s that look exactly like
application bugs. Run `a11y.spec.ts` against a production build — dev-mode
double-rendering makes the focus and axe assertions flap.

**Axe scans must wait for finite animations to settle.** An element caught
mid-fade fails contrast on colours that are fine once it lands, so an unsettled
scan reports the animation rather than the palette. Infinite animations (the
amber approval pulse, the ambient field) are excluded from the wait or it never
returns.

**Contrast is measured against `.glass-elevated`, not against a token.** That
panel is `--t-raised` at 72% with `saturate(1.4)`, so it composites lighter
than any solid surface — ink tuned against `--t-raised` still failed on the
approval card, which is the one thing a person must be able to read. `a11y.spec.ts`
checks all six themes on both the landing page and a blocked session.

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
- **Verified inside a real editor.** All 7 integration tests pass against a
  downloaded VS Code. Needs `@vscode/test-electron@^3.1.0` — the `2.5.2` this
  was originally pinned to hardcodes the macOS launch path as
  `Contents/MacOS/Electron`, which current VS Code stable builds renamed to
  `Contents/MacOS/Code`. See `apps/vscode/TESTING.md`.
- **`sani.authToken` is not optional once the server leaves loopback.** The
  extension shipped with only `sani.serverUrl` and a description claiming the
  server has no authentication — so against any server with `SANI_AUTH_TOKEN` it
  401'd on every request, including the WebSocket. `createApi` already threaded a
  token onto both the headers and the socket's `?token=`; the extension just
  never passed one. Run the suite against an authenticated server with
  `SANI_TEST_SERVER_URL` and `SANI_TEST_AUTH_TOKEN`.
- **The test runner needs a short `--user-data-dir`.** VS Code puts its IPC
  socket inside it, and macOS caps Unix domain socket paths at ~103 chars, so a
  default under a deep checkout dies with `listen EINVAL: invalid argument` —
  an error naming the socket rather than the cause. `.vscode-test.mjs` now
  defaults to a `/tmp` path instead of making it opt-in.
- **The extension inherits v2 for free.** Risk assessments and critiques
  arrive through `@sani/client`'s reducer without the extension asking for
  them; the webview only had to render them. There is a parity test — if it
  fails, the two surfaces have started to drift, which is exactly what the
  shared-reducer rule exists to prevent.

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

- ⚠️ **The shell adapter executes commands.** `SANI_AUTH_TOKEN` gates every
  route and both WebSocket upgrades; **unset means open**, which is only
  acceptable on loopback. One shared token, no per-user identity, no
  revocation short of a restart — enough for your own machine behind a tunnel,
  not enough for other people. CORS defaults to `localhost:3000`.
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
  Self-correction is a later phase. **This now holds for a tool that
  *raises* as well as one that returns a failed result** — it previously
  only covered the latter, so a plan whose first step read a filename the
  model guessed wrong discarded every valid step after it. An unknown tool
  is the deliberate exception and still fails the session: it is structural,
  and the useful signal is "your tool configuration is wrong".
- Context compaction is accounting plus a no-op hook. Token counts are
  `len/4` estimates, flagged `"estimated": true`.

- The file tree is a flat listing capped at 5000 entries and skips vendored and
  VCS directories. It does not watch for changes; it refreshes on demand and
  whenever the agent emits a diff.
- **Image diffs show an "after" and no "before."** The server retains pre-edit
  *text* for diffing, not pre-edit bytes, so a modified image cannot be shown
  side by side. The UI says so rather than rendering the same picture twice.
- A restored (`detached`) session cannot be resumed. Reviving execution needs a
  worker process, which is not built.

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

One verification debt left, written and wired, not executed:

1. `DockerSandbox` against a live daemon.

It reports its own unverified state rather than letting a caller assume
otherwise. (Two others used to be on this list. `PgVectorStore` against
Postgres is now verified — see `tests/core/test_pgvector_store.py`. The VS
Code integration suite now runs against a real downloaded VS Code and all 7
tests pass — see `apps/vscode/TESTING.md`.) Beyond that: a worker process so a
restored session can resume rather than only be read, and auth — without it
none of this can be exposed.
