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
— all 5 tests pass:

```
✔ activates and contributes its commands
✔ blocks on an irreversible action, then completes once approved
✔ renders the agent's diff in the native diff editor
✔ rejecting leaves the file alone and still completes
✔ mission control opens and lists the sessions
```

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

Two things are specific to *where* your checkout happens to sit, not to the
extension, and may need a workaround only you'd apply locally, not commit:
- If port 8000 is already taken, `sani.serverUrl` in VS Code settings can
  point the extension at another port.
- If your checkout's absolute path is long, VS Code's default
  `--user-data-dir` (nested under it) can exceed the ~103-character limit on a
  Unix domain socket path and fail with `listen EINVAL`. Pass a shorter
  `--user-data-dir` via `launchArgs` in `.vscode-test.mjs` if you hit this.

The suite starts a real session in a throwaway workspace folder and asserts the
things worth asserting: that an always-confirm delete blocks, that the file is
still on disk while it is blocked, that approving through the command palette
unblocks it, that a rejection leaves the file alone and the session still
completes, and that the diff opens in the native editor with a correctly
reconstructed original.
