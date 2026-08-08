# End-to-end tests

Real browser, real Next.js build, real FastAPI server, real agent session. The
Python suite proves the API contract; this proves the product.

Both servers must be running first — the tests do not start them, so a failure
here is always about the app rather than about process orchestration.

```bash
# terminal 1 — API on the port the web build was compiled against
uv run uvicorn sani_server.app:app --port 8000

# terminal 2 — the web IDE
cd apps/web && npm run build && npx next start -p 3000

# terminal 3
cd apps/web && npx playwright test
```

## Gotchas worth knowing before you debug something else

- **`NEXT_PUBLIC_SANI_SERVER` is inlined at build time.** Pointing the tests at
  a different API port means rebuilding, not just re-running `next start`.
- **Never rebuild under a running `next start`.** Overwriting `.next` while the
  server holds it serves broken chunks and 500s on assets, which looks exactly
  like an application bug and is not one.
- **CORS is pinned to port 3000.** Use `SANI_CORS_ORIGINS` for anything else.
- **Chromium version.** `playwright.config.ts` points at the preinstalled
  `/opt/pw-browsers/chromium-1194` when present, because it does not match the
  build Playwright 1.62 downloads by default.
- **Monaco drops fast keystrokes.** Type with a `delay`, and click
  `.monaco-editor .view-lines` rather than the hidden textarea, which the
  editor's own overlay intercepts.

Screenshots land in `e2e/screenshots/` on success and `test-results/` on
failure, alongside a trace: `npx playwright show-trace <path>`.
