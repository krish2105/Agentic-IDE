# Running Ṣāni' Studio

How to stand it up, how to use every feature, and where you must not put it.

---

## Read this first

⚠️ **The server has no authentication and the agent executes shell commands.**
Anyone who can reach the API can run arbitrary code as the user running the
server, read any file the workspace check allows, and open a shell over a
WebSocket. There is no token, no session cookie, no rate limit.

That single fact governs the whole deployment story: **bind it to localhost, or
put your own authentication in front of it.** There is no configuration flag
that makes public exposure safe, and `SANI_SANDBOX=docker` does not change the
answer — it reduces what the *agent* can reach, not who can reach the *API*.

The rest of this document assumes you accept that and are running it as a local
developer tool, which is what it is.

---

## 1. Prerequisites

| Need | Why | Required? |
|---|---|---|
| Python 3.11+ and [`uv`](https://docs.astral.sh/uv/) | The backend | yes |
| Node 20+ and npm | Web IDE, VS Code extension, shared client | yes for the UI |
| `redis-server` | Session persistence across restarts | optional |
| Docker daemon | Container sandbox | optional, unverified |
| Postgres + pgvector | Durable vector store | optional, unverified |

```bash
git clone https://github.com/krish2105/Agentic-IDE
cd Agentic-IDE
uv sync        # Python workspace
npm install    # all three TypeScript workspaces, from the root
```

---

## 2. The 60-second start

Two terminals.

```bash
# terminal 1 — backend
uv run uvicorn sani_server.app:app --port 8000

# terminal 2 — web IDE
npm run dev --workspace sani-web
```

Open `http://localhost:3000`, type a task, pick a workspace folder, press
Start. Interactive API docs live at `http://127.0.0.1:8000/docs`.

**Prefer a terminal?** `uv run python scripts/ws_client.py --workspace /tmp/demo`
streams the same session and prompts for approvals inline. Useful for
demonstrating that the clients really are interchangeable consumers of one
contract.

Check what you're running:

```bash
curl -s localhost:8000/healthz | python3 -m json.tool
```

That reports the protocol version, every event type, the always-confirm list,
and whether sessions are durable.

---

## 3. Using every feature

### Plan preview and approval gating

Start a session and the plan arrives **before** anything executes. Low-risk
steps run automatically; irreversible ones stop and wait for you.

- **Chat** — the running narrative: what the agent read, what it proposed, what
  each tool returned.
- **Plan** — every step with live status.
- **Diffs** — per-file, with agent-authored lines in the accent colour.
- **Trust** — what the agent may do unasked.

When a gated action appears, the approval card shows the action type, the
reason, and for a file write a **per-hunk checkbox list**. Untick a hunk and
the button changes to *Approve 1 of 2 hunks* — only the ticked hunks are
written. Rejecting is not a failure: the step is marked rejected and the plan
continues.

### The trust ladder

The **Trust** tab has two sections.

*Earns trust* — toggle any of these on, or let the agent earn them: three
consecutive manual approvals promotes an action type automatically, and a
counter shows progress (`1/3`). One rejection revokes it.

*Always asks* — seven action types that **cannot** be switched on at any trust
level. They render with no toggle at all, because the server refuses the
request and offering a switch that cannot work is worse than not offering one:

```
file.delete · path.outside_workspace · secret.access · shell.network
dependency.new · git.history_rewrite · browser.navigate_external
```

### Editor, file tree, terminal

Monaco with tabs, `Ctrl/Cmd+S` to save back to the workspace. Files the agent
touched are marked with the accent colour in the tree and on the tab. An open
tab reloads when the agent rewrites the file underneath it — **unless you have
unsaved edits**, in which case yours are kept.

The terminal at the bottom is a real PTY in the session workspace. It is
deliberately *not* permission-gated: judging your own shell would be theatre
when you can already run anything the server user can.

### Codebase RAG

Index a repo, and any session on that workspace retrieves from it during
planning:

```bash
curl -X POST localhost:8000/rag/index \
  -H 'Content-Type: application/json' -d '{"workspace":"/path/to/repo"}'

curl -X POST localhost:8000/rag/query -H 'Content-Type: application/json' \
  -d '{"workspace":"/path/to/repo","query":"how are permissions checked","limit":3}'
```

Retrieval is **disclosed**: the stream emits `rag.retrieved` listing exactly
what the agent read, before the plan, and the Chat tab shows it as an
expandable entry. Code silently steering a plan is the same opacity the
approval gate exists to prevent.

> The default embedder is **lexical, not semantic**. It matches identifiers —
> most of the signal in code search — but will not connect "authorise" to
> `check_permission`. `curl localhost:8000/rag/status?workspace=...` reports
> `"semantic": false` rather than letting you assume otherwise.

### Browser subagent

Give a session the browser tool and it drives a real Chromium:

```bash
curl -X POST localhost:8000/session -H 'Content-Type: application/json' -d '{
  "task": "check the landing page renders",
  "workspace": "/path/to/repo",
  "tools": ["browser"],
  "trust_overrides": {"browser.action": true},
  "script": [
    {"description":"open","tool":"browser","params":{"op":"goto","url":"http://localhost:3000"}},
    {"description":"verify","tool":"browser","params":{"op":"assert_text","text":"Ṣāni"}},
    {"description":"capture","tool":"browser","params":{"op":"screenshot","name":"landing"}}
  ]}'
```

Ops: `goto`, `click`, `fill`, `text`, `assert_text`, `screenshot`. Screenshots
land in `.sani/artifacts/` inside the workspace, so they show up in the file
tree and can be fetched at `/session/{id}/file/raw?path=...`.

Navigating to a **non-local URL** always stops for approval — same blast radius
as `curl`.

### Parallel sessions and Mission Control

Every session appears on the landing page with its status, current step,
elapsed time and an approval badge. Open two and a **tab strip** appears above
the editor so you can switch without losing either.

### Session persistence

```bash
redis-server --port 6379 &
SANI_SESSION_STORE=redis uv run uvicorn sani_server.app:app --port 8000
```

Now sessions outlive the process. Verified behaviour:

- Restart the server and past sessions are still there, with their plans, diffs
  and full event logs replayable from `?from_seq=0`.
- A **second server instance** on the same Redis can read and live-stream a
  session it never created.
- A restored session is **read-only history** — `pause`, `resume` and `approve`
  return `409`, because its executor died with the process that owned it.
- A graceful shutdown records the session as `killed`. A hard crash leaves it
  `failed` with `"session interrupted by a server restart"`. Neither leaves a
  spinner running for work that will never resume.

### Real models instead of the scripted planner

```bash
uv sync --extra litellm
SANI_MODEL_BACKEND=litellm SANI_MODEL=groq/llama-3.3-70b-versatile \
  uv run uvicorn sani_server.app:app --port 8000
```

The default is a deterministic scripted planner, which is what makes the test
suite reproducible without an API key.

### VS Code extension

```bash
npm run build:vscode && npm run package:vscode
code --install-extension apps/vscode/sani-studio.vsix
```

Set `sani.serverUrl` if the backend is not on `127.0.0.1:8000`. The sidebar
carries the same Chat/Plan/Diffs dock; diffs open in **VS Code's own diff
editor** and agent-authored lines get gutter marks.

⚠️ This extension has never run inside a real editor — see
`apps/vscode/TESTING.md`.

---

## 4. Configuration

Every setting, with its default.

| Variable | Default | What it does |
|---|---|---|
| `SANI_MODEL_BACKEND` | `scripted` | `scripted` or `litellm` |
| `SANI_MODEL` | `groq/llama-3.3-70b-versatile` | LiteLLM planner model |
| `SANI_SESSION_STORE` | `memory` | `memory` or `redis` |
| `SANI_REDIS_URL` | `redis://127.0.0.1:6379/0` | Redis connection |
| `SANI_SANDBOX` | `local` | `local` or `docker` |
| `SANI_SANDBOX_IMAGE` | `python:3.11-slim` | Container image |
| `SANI_TERMINAL_SHELL` | `/bin/bash` | Shell for the PTY |
| `SANI_WORKSPACE_ROOT` | unset | Confines every workspace beneath this path |
| `SANI_CORS_ORIGINS` | `localhost:3000` | Comma-separated allowed origins |
| `SANI_EMBEDDINGS` | `hashing` | `hashing` or `litellm` |
| `SANI_EMBEDDING_MODEL` | `gemini/text-embedding-004` | LiteLLM embedding model |
| `SANI_VECTOR_STORE` | `memory` | `memory` or `pgvector` |
| `SANI_PG_DSN` | unset | Postgres DSN for pgvector |
| `SANI_BROWSER_EXECUTABLE` | auto-detected | Chromium path override |
| `NEXT_PUBLIC_SANI_SERVER` | `http://127.0.0.1:8000` | **Build-time**, web IDE only |

**`NEXT_PUBLIC_SANI_SERVER` is inlined when the web app is built.** Changing
the API port means rebuilding, not just restarting.

**Set `SANI_WORKSPACE_ROOT` for anything but casual local use.** Unset, any
existing directory is an acceptable workspace (minus a small list of system
paths — a typo guard, not a security boundary).

---

## 5. Deploying it somewhere

### The honest version

The spec assumed Vercel for the frontend and Fly.io for the backend. The
frontend half is fine: it is a client that talks to whatever API URL you build
it against. **The backend half is not deployable to the public internet as it
stands**, and no amount of configuration changes that.

Three arrangements that are actually defensible:

**A. Localhost only — recommended.** What everything above describes. Nothing
listens beyond your machine.

**B. A private machine plus a tunnel.** Run the backend on a VM bound to
`127.0.0.1`, reach it over SSH port-forwarding or a private overlay network
(Tailscale, WireGuard). Nothing is published; authentication is your tunnel's.

```bash
ssh -N -L 8000:127.0.0.1:8000 you@your-vm
```

**C. Behind an authenticating reverse proxy.** Only if you add real auth. At
minimum you need: an identity check on every HTTP route *and* on both WebSocket
upgrades (`/stream` and `/terminal` — a proxy that only guards HTTP leaves the
terminal wide open), per-user workspace isolation via `SANI_WORKSPACE_ROOT`,
and `SANI_SANDBOX=docker` so the agent's shell is contained. That is a real
piece of work, not a config change, and it is the single largest thing standing
between this and a hostable product.

### If you do run it on a server

```bash
# systemd-style: bind loopback, confine workspaces, persist sessions
SANI_SESSION_STORE=redis \
SANI_WORKSPACE_ROOT=/srv/sani/workspaces \
SANI_SANDBOX=docker \
uv run uvicorn sani_server.app:app --host 127.0.0.1 --port 8000
```

Then build the web IDE against whatever URL the browser will actually use:

```bash
NEXT_PUBLIC_SANI_SERVER=https://sani.internal.example npm run build --workspace sani-web
npx next start -p 3000
```

and set `SANI_CORS_ORIGINS` to that frontend's origin.

---

## 6. Verify it yourself

```bash
uv run pytest          # 223 tests — real Redis, real Chromium
npm run test:client    # 27 tests — 3 hit a live server if one is running
npm run test:e2e       # 5 browser tests — both servers must be up first
npm run typecheck      # all three TypeScript workspaces
```

**Three components are built but have never executed.** Each reports its own
unverified state rather than letting you assume otherwise:

| Component | How to verify | Reports |
|---|---|---|
| VS Code extension | `npm run test:vscode --workspace sani-vscode` | see TESTING.md |
| Docker sandbox | `SANI_SANDBOX=docker`, then `docker ps` for `sani-<id>` | `verified: false` |
| pgvector store | `SANI_VECTOR_STORE=pgvector` with `SANI_PG_DSN` | `verified: false` |

If you are demoing this, running those three is the highest-value hour you can
spend — it converts "believed to work" into "known to work".

---

## 7. Troubleshooting

**Web IDE says it cannot reach the server.** The API is down, or the web app
was built against a different URL. `NEXT_PUBLIC_SANI_SERVER` is baked in at
build time — rebuild after changing it.

**Requests blocked by CORS.** The web IDE is on a port other than 3000. Set
`SANI_CORS_ORIGINS` to its exact origin.

**500s on assets right after a rebuild.** You rebuilt while `next start` was
running, which corrupts `.next`. Stop the server, rebuild, start it again. This
looks exactly like an application bug and is not one.

**Terminal will not attach.** With `SANI_SANDBOX=docker`, check the daemon is
up and the image can be pulled. The `ready` frame reports which sandbox
answered.

**Playwright cannot find a browser.** Set `SANI_BROWSER_EXECUTABLE` to your
Chromium binary; the bundled version Playwright expects may not be the one
installed.

**`/rag/query` returns nothing.** The workspace was never indexed, or your
wording shares no identifiers with the code — the default embedder is lexical.
Check `/rag/status`.
