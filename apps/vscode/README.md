# Ṣāni' Studio — VS Code extension

Agentic coding sessions inside VS Code, over the same backend as the web IDE.

Everything native stays native (spec Section 6). Diffs open in VS Code's own
diff editor rather than a webview reimplementation, agent-authored lines are
marked in the gutter, and the sidebar carries the same Chat / Plan / Diffs dock
as the web client — from the same shared reducer, so the two surfaces cannot
drift in how they read a session.

## What it does

- **Sidebar** in the activity bar: Chat, Plan, Diffs, and the approval card.
- **Approval gating.** Irreversible actions stop and wait for you, with
  per-hunk accept for file writes. Approve or reject from the sidebar or the
  command palette.
- **Native diffs.** `Ṣāni': Show Diff for File` opens the real diff editor. The
  "before" side is reconstructed from the current file plus the hunks the
  server sent, so no extra round trip is needed.
- **Gutter marks** on agent-authored lines, in the accent reserved for agent
  origin.
- **Status bar** showing session status and the context meter; it turns amber
  when something needs your approval.
- **Mission Control** listing every session, foreground and background.

## Setup

The extension is a client. Start the server first:

```bash
uv run uvicorn sani_server.app:app --port 8000
```

Then set `sani.serverUrl` if it is not on the default port. ⚠️ The server has
no authentication and can run shell commands — keep it on localhost.

## Development

```bash
npm install            # from the repo root; this is an npm workspace
npm run build --workspace sani-vscode
npm run package --workspace sani-vscode   # produces sani-studio.vsix
```

Press F5 in VS Code to launch an Extension Development Host.

## Commands

| Command | Purpose |
|---|---|
| `Ṣāni': New Session` | Start a session in the open folder |
| `Ṣāni': Attach to Session` | Pick up an existing session |
| `Ṣāni': Mission Control` | List all sessions |
| `Ṣāni': Approve` / `Reject` | Resolve the pending action |
| `Ṣāni': Show Diff for File` | Open an agent diff natively |
| `Ṣāni': Pause` / `Resume` / `Kill` | Lifecycle control |

## Settings

| Setting | Default | Purpose |
|---|---|---|
| `sani.serverUrl` | `http://127.0.0.1:8000` | Base URL of the Ṣāni' server |
| `sani.showGutterMarks` | `true` | Mark agent-authored lines in the gutter |

See [TESTING.md](./TESTING.md) for what is verified and what is not.
