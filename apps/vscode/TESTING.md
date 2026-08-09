# Testing the extension

## What is verified

**The logic, thoroughly.** The extension's real behaviour — how a session's
events become UI state, reconnection and replay, reconstructing the pre-edit
file for the diff editor, locating agent-authored lines for the gutter — lives
in `@sani/client` and is covered by 27 tests:

```bash
npm run test:client        # from the repo root
```

Three of those run against a **live server over a real WebSocket**, using the
same `createApi` + `SessionStream` + `ws` path the extension host runs. They
skip themselves when no server is listening:

```bash
uv run uvicorn sani_server.app:app --port 8000   # then re-run test:client
```

**Compilation and types.** `npm run typecheck` and `npm run build` cover the
extension host bundle, the webview bundle, and the integration test bundle.

## What is now verified

**The extension has run inside a real VS Code.** `src/test/integration.test.ts`
was written, compiled, and wired up, but for a long time had never actually
executed: the environment it was built in did not permit downloading VS Code
from `update.code.visualstudio.com`. It has since been run for real, against a
downloaded VS Code 1.132.0 (Darwin arm64), with a live server on the other end
— all 7 tests pass:

```
✔ activates and contributes its commands
✔ blocks on an irreversible action, then completes once approved
✔ renders the agent's diff in the native diff editor
✔ rejecting leaves the file alone and still completes
✔ mission control opens and lists the sessions
✔ the extension sees the same v2 state the web IDE does
✔ replay opens the session history at a chosen keyframe
```

The parity test is the one that matters architecturally. Both clients read a
session through `@sani/client`, so risk assessments and critiques arrive in the
extension without the extension asking for them. If that test fails, the two
surfaces have started to drift -- which is the exact failure the shared-reducer
rule exists to prevent.

That covers the editor-facing glue that the unit tests cannot reach:
activation, command registration, the webview provider, the `vscode.diff`
call, and the decoration API.

**A real bug turned up in the process.** `@vscode/test-electron@2.5.2` (the
version this was pinned to) hardcodes the macOS launch path as
`Contents/MacOS/Electron`; VS Code renamed that binary to `Contents/MacOS/Code`
for 1.110+ stable builds, so every attempt to run this suite against a current
VS Code failed with `spawn .../Contents/MacOS/Electron ENOENT` before a single
test executed. Fixed by bumping to `@vscode/test-electron@^3.1.0`, which
resolves the executable name dynamically instead of assuming it.

Run it yourself:

```bash
uv run uvicorn sani_server.app:app --port 8000   # in one terminal
npm run build   --workspace sani-vscode
npm run test:vscode --workspace sani-vscode      # downloads VS Code on first run
```

It uses `xvfb-run`, so it works headless on Linux. On macOS or Windows drop the
`xvfb-run -a` prefix from the `test:vscode` script.

Two environment escapes exist for machine-specific problems, both opt-in so
nothing machine-specific is baked into the committed config:

```bash
# The extension defaults to :8000, which is commonly already taken.
SANI_TEST_SERVER_URL=http://127.0.0.1:8055 \
# A long checkout path pushes VS Code's default --user-data-dir past macOS's
# ~103-char Unix socket limit and fails with `listen EINVAL`.
SANI_TEST_USER_DATA_DIR=/tmp/svt \
  npm run test:vscode --workspace sani-vscode
```

The suite starts a real session in a throwaway workspace folder and asserts the
things worth asserting: that an always-confirm delete blocks, that the file is
still on disk while it is blocked, that approving through the command palette
unblocks it, that a rejection leaves the file alone and the session still
completes, and that the diff opens in the native editor with a correctly
reconstructed original.
