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

## What is not verified here

⚠️ **The extension has never run inside a real VS Code.** `src/test/integration.test.ts`
is written, compiled, and wired up, but `@vscode/test-electron` downloads VS
Code from `update.code.visualstudio.com`, which the network policy of the
environment this was built in does not permit. The test has therefore never
executed.

That leaves the editor-facing glue unproven: activation, command registration,
the webview provider, the `vscode.diff` call, and the decoration API. The logic
underneath them is tested; the wiring to VS Code is not.

Run it on any machine with normal network access:

```bash
uv run uvicorn sani_server.app:app --port 8000   # in one terminal
npm run build   --workspace sani-vscode
npm run test:vscode --workspace sani-vscode      # downloads VS Code on first run
```

It uses `xvfb-run`, so it works headless on Linux. On macOS or Windows drop the
`xvfb-run -a` prefix from the `test:vscode` script.

The suite starts a real session in a throwaway workspace folder and asserts the
things worth asserting: that an always-confirm delete blocks, that the file is
still on disk while it is blocked, that approving through the command palette
unblocks it, that a rejection leaves the file alone and the session still
completes, and that the diff opens in the native editor with a correctly
reconstructed original.

Treat the extension as unproven against a real editor until that run is green.
