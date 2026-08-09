# Ṣāni' Studio

An agentic coding IDE built on one Python backend, serving two surfaces: a VS Code
extension and a standalone web IDE.

The design bet is **visible autonomy rather than maximal autonomy**. The plan is
shown before it runs, every tool call is disclosed at the decision point — including
the ones that were auto-approved — and trust is earned per action type rather than
granted globally. A fixed always-confirm tier covers every irreversible action no
matter how much trust a session has accumulated, and that tier can be extended but
never reduced.

```
378 Python tests  ·  68 shared-client  ·  32 Playwright  ·  7 VS Code integration
```

Every one of those runs against the real thing: a real Redis, a real Docker
daemon, a real Chromium, a real downloaded VS Code. Nothing in this repo is
described as verified on the strength of a mock.

---

## Quick start

Two terminals. No token, no tunnel, nothing to paste.

```bash
uv sync --extra litellm          # Python workspace
npm install                      # all three TypeScript workspaces
```

```bash
SANI_NO_AUTH=1 ./scripts/serve.sh   # loopback only, so no token to paste
```

```bash
npm run dev --workspace sani-web    # web IDE on :3000
```

Open `http://localhost:3000`, describe a task, and watch the plan arrive before
anything runs. Interactive API docs at `http://127.0.0.1:8060/docs`.

`SANI_NO_AUTH=1` drops the bearer token for local use: the socket is loopback, so
there is nothing to authenticate, and requiring a token there costs two clipboard
pastes for no gain. It refuses to start if a tunnel is running — that is precisely
when the token is the only thing between the internet and a shell. Drop the flag
and `serve.sh` generates and requires one.

`serve.sh` exists because three settings on this server fail *invisibly* when
wrong — the auth token, the CORS origins, and the model backend — and each
failure looks like something else entirely. It reads secrets from files under
`~/.sani/`, infers the backend from whether a Groq key is present and the session
store from whether Redis answers, and prints what it chose.

**Real inference** needs a [Groq](https://console.groq.com/keys) key. Without
one the planner replays a fixed demo script and *ignores your task* — a confident
plan about something you did not ask for, which is the single most confusing
thing here. The startup banner names the backend for exactly that reason.

```bash
umask 077; printf %s 'gsk_your_key' > ~/.sani/groq-key
```

Prefer a terminal? `uv run python scripts/ws_client.py --workspace /tmp/demo`
streams the same session and prompts for approvals inline.

> ⚠️ **The shell tool executes commands.** Unset, `SANI_AUTH_TOKEN` leaves the
> server open, which is only acceptable on loopback. `scripts/tunnel.sh` refuses
> to expose a server that has authentication off.

---

## What it does

| | |
|---|---|
| **Plan before execution** | The plan streams in token by token and is shown in full before any tool runs |
| **Full tool-call disclosure** | `tool.proposed` fires for every action, including auto-approved ones |
| **Two-tier permissions** | An always-confirm tier that cannot be unlocked, and a trust ladder that promotes after 3 consecutive approvals and revokes on one rejection |
| **Blast-radius scoring** | What an action reaches, how much changes, whether it can be undone — shown *with* the request, never instead of it |
| **Per-hunk approval** | Approve part of a diff and reject the rest |
| **Replay** | Scrub any finished session; keyframes are computed server-side so the scrubber and a reconnecting client cannot disagree |
| **Provenance** | Line-level "who wrote this", derived from the diffs rather than tracked separately, with confidence decay rather than silent drift |
| **Parallel races** | N agents on one task in isolated git worktrees, each behind the same approval gate |
| **Self-critique** | An optional second opinion on a diff before it reaches you — advisory, and it cannot gate anything |
| **Cost** | Real spend alongside the token meter. An unpriced model reports `null`, never `$0.00` |
| **Codebase RAG** | tree-sitter chunking by function and class; retrieval is disclosed before planning |
| **Browser subagent** | DOM-based, deterministic verification rather than a screenshot to squint at |
| **Sandboxing** | Local, Docker-per-session, or macOS Seatbelt — the agent *and* the human go through the same one |

Six themes, a 3D Mission Control, and a quality ladder down to `off` — which is a
first-class design target, not a degraded mode. WCAG AA contrast is asserted by
machine on every theme, on both the landing page and a session blocked on
approval.

---

## Architecture

```
packages/sani-core/     agent engine — planning, permissions, tools, execution,
                        replay, risk, provenance, pricing. No web framework.
packages/sani-server/   FastAPI + WebSocket transport, sandboxes, Redis archive,
                        git worktrees for races
packages/sani-client/   shared TypeScript client — wire types, reducer, reconnect,
                        diff reconstruction
apps/web/               Next.js 16 web IDE — Monaco, xterm.js, chat/plan/graph/
                        diffs/trust dock, replay scrubber
apps/vscode/            VS Code extension — sidebar, native diff, gutter marks
```

Three rules keep it honest:

1. **`sani-core` never imports a web framework**, so the same engine backs the
   server, a CLI and the tests. That is what makes "reusable core" testable
   rather than asserted.
2. **Both clients read a session through `@sani/client`** — one reducer, one
   reconnect path, one diff reconstruction. A bug is one bug rather than two
   surfaces that quietly disagree.
3. **Clients hold no business logic.** If a client needs to compute something
   about session state, that computation belongs in the Session Manager.

The permission chokepoint is a single function consulted immediately before
execution, never at plan time. It checks the always-confirm set *before* the
trust ladder, so a corrupted or maliciously-set ladder cannot unlock those types.

---

## Tests

```bash
uv run pytest                   # 378 tests, ~30s, no network and no ports
npm run test:client             # 68 shared-client tests (needs Node 22+)
npm run test:e2e                # 32 Playwright tests; both servers must be up
npm run typecheck               # all three TypeScript workspaces
cd apps/vscode && npx vscode-test   # 7 integration tests in a real VS Code
```

The Python suite is fully reproducible with no API keys, because the default
planner is deterministic. Tests that need a real dependency **skip rather than
fake it** — `redis-server`, a reachable Docker daemon, Postgres + pgvector,
`sandbox-exec` — so a green run never overstates what was exercised.

The end-to-end suite drives a real Chromium against a real Next.js build and a
real server: `ide.spec.ts` (plan → gate → approve), `redesign.spec.ts` (risk,
replay, cognition graph, themes, races) and `a11y.spec.ts` (axe on every theme,
keyboard operability, reduced motion, 375px).

---

## Deployment

```bash
./scripts/install-service.sh    # launchd job: starts at login, restarts on crash
./scripts/tunnel.sh             # expose over HTTPS (random hostname)
./scripts/named-tunnel.sh sani.example.com   # a hostname that survives restarts
```

The frontend deploys to Vercel unchanged; the backend stays on your machine
behind an HTTPS tunnel, because it runs commands there. See
[DEPLOYMENT.md](./DEPLOYMENT.md) for the full arrangement and, more usefully, the
failure modes — a hosted page calling loopback, a CORS mismatch that breaks only
half the app, and mixed content are each invisible in a different way.

---

## Known limits

Stated plainly, because a tool that overstates its own guarantees is worse than
one that admits them.

- **Authentication is one shared bearer token.** No per-user identity, no
  revocation short of a restart. Enough for your own machine behind a tunnel; not
  enough for other people.
- **The sandbox reduces blast radius; it is not a security boundary.**
  `LocalSandbox` provides no isolation and says so in its own `describe()`.
  Seatbelt confines *where* a command reads, writes and connects — not how much
  of the machine it consumes.
- **A restored session can be read, not resumed.** Reviving execution needs a
  worker process, which is not built.
- **`pause` and `kill` take effect at the next step boundary.** A tool call
  already running finishes rather than being interrupted mid-write.
- **Context compaction is accounting plus a no-op hook.** Token counts are
  `len/4` estimates and are flagged `estimated`.
- **A failing tool call fails its step; the plan continues.** Self-correction is
  a later phase. An unknown tool is the deliberate exception and fails the
  session, because that signals a configuration error rather than a bad guess.
- **Image diffs show an "after" and no "before."** The server retains pre-edit
  text for diffing, not pre-edit bytes, and the UI says so rather than rendering
  the same picture twice.

---

## Documentation

- [DEPLOYMENT.md](./DEPLOYMENT.md) — how to run it, use every feature, and where
  it must not be exposed
- [CLAUDE.md](./CLAUDE.md) — the full API contract, event protocol, safety model,
  and the reasoning behind the decisions that look odd
- [PROGRESS.md](./PROGRESS.md) — what is done and what is left
- [apps/vscode/TESTING.md](./apps/vscode/TESTING.md) — running the extension
  suite against a real editor
- [apps/web/e2e/README.md](./apps/web/e2e/README.md) — the end-to-end harness and
  the environment mistakes that all fail identically

---

## A note on verification

Five claims in this project were once "written but not executed". Every one has
now met the real thing, and every one repaid the effort by exposing a bug that
reading the code could not have found:

| Claim | What running it found |
|---|---|
| `PgVectorStore` | a missing extra the docs already told you to install |
| VS Code extension | a test runner hardcoding a macOS binary path that had been renamed |
| `SandboxExecSandbox` | a Seatbelt profile that denied `/bin/sh` |
| Redis persistence | four ordering bugs — a *completed* session restored as `failed` |
| `DockerSandbox` | a bind mount that silently mounts an empty directory on macOS |

None were visible to review. All were obvious within a minute of execution.
"Unverified" was never a formality.
