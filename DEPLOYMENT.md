# Running Ṣāni' Studio

How to stand it up, how to use every feature, and where you must not put it.

---

## Read this first

⚠️ **The agent executes shell commands.** Anyone who can reach the API without
a token can run arbitrary code as the user running the server and open a shell
over a WebSocket.

The server now supports authentication — set **`SANI_AUTH_TOKEN`** and every
HTTP route and both WebSocket upgrades require a bearer token. **If the server
is reachable by anything other than your own machine, set it.** Leaving it
unset keeps the old behaviour (open), which is fine on loopback and nowhere
else.

`SANI_SANDBOX=docker` is not a substitute: it limits what the *agent* reaches,
not who reaches the *API*.

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
| `SANI_AUTH_TOKEN` | unset (open) | Bearer token required on every route and both WebSockets |
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

**`NEXT_PUBLIC_SANI_SERVER` is only a default.** It is inlined at build time,
but the UI can point somewhere else at runtime — click the server URL in the
Mission Control header, or *Change connection* on the error banner. The value
is stored in that browser, so one hosted build can serve any backend without a
rebuild.

**Set `SANI_WORKSPACE_ROOT` for anything but casual local use.** Unset, any
existing directory is an acceptable workspace (minus a small list of system
paths — a typo guard, not a security boundary).

---

## 5. Deploying it somewhere

### Why a hosted frontend shows "cannot reach the server"

Deploy `apps/web` to Vercel and it will say that immediately. Three separate
reasons, and fixing one without the others changes nothing:

1. **The bundle points at loopback.** `NEXT_PUBLIC_SANI_SERVER` is inlined at
   build time. Built without it, the page calls `http://127.0.0.1:8000` — which
   in a visitor's browser means *their own machine*. No server you start
   anywhere will satisfy it.
2. **CORS only allows `localhost:3000`.** Your Vercel origin is not on the list.
3. **Nothing is listening on the public internet**, because the backend is on
   your laptop.

The page now diagnoses which of these it is instead of always telling you to
run uvicorn.

### The arrangement that actually works

Frontend on Vercel, backend on your machine, reached over an HTTPS tunnel, with
a token. Four steps.

**1 — Start the backend with a token.**

```bash
export SANI_AUTH_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
echo "$SANI_AUTH_TOKEN"          # you will paste this into the UI

SANI_CORS_ORIGINS=https://your-app.vercel.app \
SANI_WORKSPACE_ROOT=$HOME/code \
uv run uvicorn sani_server.app:app --host 127.0.0.1 --port 8000
```

**2 — Expose it over HTTPS.** A plain `http://` tunnel will not work: the page
is HTTPS and the browser blocks mixed content.

```bash
cloudflared tunnel --url http://127.0.0.1:8000
# or: ngrok http 8000
```

Both print an `https://…` URL. Whatever it is, set `SANI_CORS_ORIGINS` to your
Vercel origin (step 1) — not to the tunnel URL.

**3 — Point the UI at it.** No rebuild needed. Open your Vercel app, click the
server URL in the Mission Control header (or *Change connection* on the error
banner), paste the tunnel URL and the token, save.

**4 — Confirm.** The banner disappears and the header shows your tunnel host.

To bake in the default instead, set `NEXT_PUBLIC_SANI_SERVER` in Vercel's
environment variables and redeploy — but the runtime setting still wins, which
is what makes one build usable against a tunnel URL that changes every restart.

### Understand what you have just done

That tunnel publishes a code-execution service to the internet, protected by
one shared token. That is a real step up from no auth, and it is still not a
multi-user system:

- One token for everybody; no per-user identity, no revocation short of
  restarting with a new token.
- The token rides in the query string for WebSockets, because browsers cannot
  set headers on a handshake. It will appear in tunnel access logs.
- No rate limiting, and the workspace check is the only containment on the
  file API.

Reasonable: your own machine, your own repos, a tunnel you shut down when you
are done. Not reasonable: leaving it up, or handing the URL to other people.
For that you want per-user auth, `SANI_WORKSPACE_ROOT` per user, and
`SANI_SANDBOX=docker`.

### Other arrangements

**Localhost only — still the best option.** Run the web IDE locally too and
none of the above applies.

**Private network.** Backend bound to `127.0.0.1`, reached over SSH forwarding
or Tailscale. Nothing is published and the tunnel is the authentication.

```bash
ssh -N -L 8000:127.0.0.1:8000 you@your-vm
```

**A real server.** Bind loopback, confine workspaces, persist sessions, and put
an authenticating proxy in front that guards **both WebSocket upgrades**, not
just the HTTP routes — a proxy that only covers HTTP leaves `/terminal` open.

```bash
SANI_AUTH_TOKEN=... \
SANI_SESSION_STORE=redis \
SANI_WORKSPACE_ROOT=/srv/sani/workspaces \
SANI_SANDBOX=docker \
uv run uvicorn sani_server.app:app --host 127.0.0.1 --port 8000
```

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

**Web IDE says it cannot reach the server.** Read the banner — it now names
the cause. "Your own machine" means a hosted page is calling loopback: use a
tunnel URL. "Blocks the request" means HTTP backend behind an HTTPS page: use
an `https://` tunnel. "Rejected this request" means the token is missing or
wrong. Click *Change connection* to fix any of them without redeploying.

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
