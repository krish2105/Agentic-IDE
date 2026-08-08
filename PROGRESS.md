# Ṣāni' Studio — progress

**Last updated:** 8 August 2026 · branch `claude/sani-fastapi-server-phase-0-56vmdc`

An agentic coding IDE on two surfaces — a web IDE and a VS Code extension —
over one Python backend. Built against the master spec's phased roadmap.

---

## Where it stands

**Every phase in Section 9 is built.**

| Phase | Scope | Status |
|---|---|---|
| **0** | Agent core, FastAPI server, WebSocket streaming, approval endpoint | ✅ |
| **1** | Web IDE — Monaco, file tree, sandbox, xterm.js, chat panel | ✅ |
| **2** | VS Code extension — sidebar, native diff, gutter marks | ⚠️ built, unproven in a real editor |
| **3** | Codebase RAG — tree-sitter chunking, retrieval injected into planning | ✅ |
| **3a** | Session tab strip, Mission Control | ✅ |
| **3b** | Redis persistence, cross-process reattach | ✅ |
| **3c** | Browser subagent — Playwright tool adapter | ✅ |
| **4** | Trust ladder UI, design system, image diffs | ✅ |
| — | *Extra:* agent shell routed through the sandbox | ✅ |

The Section 7 API contract is complete, including the two RAG endpoints.

---

## Verification

| Suite | Count | Runs against |
|---|---|---|
| Python | **223** | A real `redis-server`, a real Chromium, real WebSocket frames |
| Shared client | **27** | Real WebSocket to a live server for 3 of them |
| Playwright | **5** | Real Chromium, real Next build, real API server |
| VS Code integration | 5 | ⚠️ **never executed** — see below |

```bash
uv run pytest          # 223 tests, ~31s
npm run test:client    # 27 tests; 3 use a live server if one is running
npm run test:e2e       # 5 browser tests; both servers must be up
npm run typecheck      # all three TypeScript workspaces
```

The Python suite starts its own Redis and drives a real browser; both skip
cleanly when the binaries are absent.

---

## What each phase actually does

### The safety model (the core of the product)

- **Auto-approved from the start:** reading files, writing inside the
  workspace, running tests/lint, git commits, locked dependency installs.
- **Always confirms, at any trust level:** deleting files, git history
  rewrites, network commands, new dependencies, secrets, paths outside the
  workspace, and browser navigation off this machine.
- **Everything else** starts gated and earns autonomy after 3 consecutive
  manual approvals; one rejection revokes it.

Enforced at a single chokepoint immediately before execution, with the
always-confirm check running *before* the trust ladder is consulted. Tests
force every unlockable tier on and confirm each irreversible action still
stops. The seventh tier — browser navigation — was added in Phase 3c because
driving a browser to a remote URL has the same blast radius as `curl`.
Extending that tier is allowed; removing from it is not.

### Phase 3 — RAG

tree-sitter chunking by function and class, because a fixed window cuts a
function in half and the retrieved text then lacks either the signature saying
what it is or the body saying what it does.

Retrieval is **disclosed**: a session whose workspace is indexed emits
`rag.retrieved` with what it read, before the plan. Code silently steering a
plan is the same opacity the approval gate exists to stop.

The default embedder is **lexical, not semantic**, and the API says so. It
matches identifiers — most of the signal in code search — but will not connect
"authorise" to `check_permission`. It is the default because the suite has to
be reproducible with no API keys; LiteLLM embeddings sit behind a flag.

### Phase 3b — Redis persistence

Sessions outlive the process. A second server instance sharing one Redis reads
a session it never created, replays its full log, and streams it live.

The split that makes this work: the **store** holds runtime handles (executor,
sandbox, PTY) and stays in memory because those are process-local; the
**archive** holds the record and is what Redis backs.

A session interrupted by a restart is marked failed *with a reason* rather than
left looking live — a spinner for work that will never resume is a lie the user
cannot detect. Restored sessions are readable history; steering them returns
409.

### Phase 3c — Browser subagent

Implements the same `propose`/`execute`/`result` as every other adapter and
needed **no executor changes**. That is the architectural claim the
three-stretch-features argument rests on, and it held.

Verification is DOM-based and deterministic, because a self-correct loop needs
a real assertion rather than a screenshot to squint at. Screenshots are still
captured, into the workspace where the file tree already shows them.

### Phase 3a + 4 — the UI

Session tab strip for parallel sessions, a Mission Control summary with a
durability indicator, image previews in the Diffs tab, and a trust ladder panel
that shows locked tiers rather than hiding them — autonomy the user cannot see
is indistinguishable from autonomy they did not consent to.

---

## Open debts — read before demoing

**Three things are written and wired but have never executed.** Each reports
its own unverified state rather than letting a caller assume otherwise:

1. **The VS Code extension in a real editor.** It compiles, typechecks and
   packages to a VSIX, and its logic is covered by the shared-client tests, but
   the integration suite needs to download VS Code and the build environment
   could not reach that host. Activation, command registration, the webview
   provider, the `vscode.diff` call and the decoration API are all unproven.
   One command fixes this on a normal machine — `apps/vscode/TESTING.md`.
2. **The Docker sandbox against a live daemon.** Reports `verified: false`.
3. **pgvector against Postgres.** Reports `verified: false`.

**Known limitations, all deliberate:**

- ⚠️ **No authentication, and the agent runs shell commands.** This is remote
  code execution if exposed. Localhost only.
- A restored session can be read but not resumed; reviving execution needs a
  worker process, which is not built.
- Image diffs show an "after" and no "before" — the server retains pre-edit
  text, not pre-edit bytes. The UI says so rather than faking a comparison.
- `pause` and `kill` take effect at the next step boundary.
- A failing tool call marks its step failed and the plan continues.
  Self-correction is not built.
- Context compaction is accounting plus a no-op hook; token counts are
  estimates and flagged as such.
- Monaco bundles a `dompurify` with one low and one moderate advisory.

---

## Two places the spec no longer matches reality

**Section 1's interview narrative needs rewriting.** It says the engine was
built first and then proven reusable by shipping it on two surfaces. That is
not what happened — the engine was not available, so the core and the transport
were designed together around one event contract. The accurate version is still
strong: the core imports no web framework, and both clients read sessions
through one shared reducer, so "shared component bundle" is a property of the
code rather than a line on a slide. Phase 3c is the sharper version of the same
claim — the browser tool slotted into the adapter interface with no executor
changes at all.

**Next.js 16, not the spec's Next.js 14.** Every 14.x release carries 20+
unpatched high-severity advisories whose fix is 16. For greenfield App Router
code that migration cost nothing.

---

## Architecture

```
packages/sani-core/     agent engine — planning, permissions, tools, execution
                        zero required third-party dependencies
packages/sani-core/rag/ chunking, embeddings, vector store, retrieval
packages/sani-server/   FastAPI + WebSocket, sandbox, Redis archive
packages/sani-client/   shared TypeScript client — both surfaces read a session
                        through the same reducer, so they cannot drift
apps/web/               Next.js web IDE
apps/vscode/            VS Code extension
```

Three rules hold it together:

1. **`sani-core` never imports a web framework.**
2. **Both clients read sessions through `@sani/client`.** A bug there is one
   bug, not two clients that disagree.
3. **Clients hold no business logic.**

Full API contract, event protocol and safety model: [CLAUDE.md](./CLAUDE.md).

---

## Running it

```bash
uv sync && npm install

uv run uvicorn sani_server.app:app --port 8000   # backend
npm run dev --workspace sani-web                 # web IDE on :3000
```

Optional: `SANI_SESSION_STORE=redis` for persistence, `SANI_SANDBOX=docker` for
container isolation, `SANI_MODEL_BACKEND=litellm` for real inference.

---

## Suggested next step

The build is feature-complete against the roadmap, so the highest-value work is
no longer features — it is **converting the three unverified components into
verified ones**, on a machine with normal network access. That is the
difference between demoing something you know works and something you believe
works.

After that, the two things that would make this deployable rather than
demoable: authentication, and a worker process so background sessions can
resume rather than only be read.
