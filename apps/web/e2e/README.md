# End-to-end tests

Real browser, real Next.js build, real FastAPI server, real agent session. The
Python suite proves the API contract; this proves the product.

Both servers must be running first — the tests do not start them, so a failure
here is always about the app rather than about process orchestration.

```bash
# terminal 1 — the API. SANI_CORS_ORIGINS must name the web origin exactly.
SANI_CORS_ORIGINS=http://127.0.0.1:3000 \
  uv run uvicorn sani_server.app:app --port 8000

# terminal 2 — the web IDE
cd apps/web && npm run build && npx next start -p 3000

# terminal 3
cd apps/web && npx playwright test
```

The three specs:

| File | Proves |
|---|---|
| `ide.spec.ts` | plan → gate → approve, the original product promise |
| `redesign.spec.ts` | risk scoring, replay, the cognition graph, themes, the race board |
| `a11y.spec.ts` | axe on every theme, keyboard operability, reduced motion, 375px |

`e2e/preflight.ts` runs before any of them and fails in about a second, naming
the fix, if either server is missing or CORS is wrong. It exists because every
environmental mistake here fails identically — a 60-second selector timeout
pointing at a component that was never the problem.

## Gotchas worth knowing before you debug something else

- **`NEXT_PUBLIC_SANI_SERVER` is inlined at build time.** Pointing the tests at
  a different API port means rebuilding, not just re-running `next start`. The
  specs sidestep this by seeding `localStorage` with `sani.serverUrl`, which is
  the app's real runtime-override path.
- **Never rebuild under a running `next start`.** Overwriting `.next` while the
  server holds it serves broken chunks and 500s on assets, which looks exactly
  like an application bug and is not one.
- **CORS defaults to port 3000, and getting it wrong is invisible.** The
  WebSocket is not CORS-checked, so the stream connects, the plan renders and
  the status pill updates while every `fetch` is silently blocked — the file
  tree, trust panel and diff list just come up empty, which reads as broken
  components. Preflight catches it now; it cost an afternoon before.
- **`allowedDevOrigins` in `next.config.mjs`.** Next 16 serves `/_next/static/*`
  in dev only to hosts it recognises, and `127.0.0.1` is not `localhost` as far
  as that check is concerned. A blocked host 403s every chunk, so the page
  server-renders and never hydrates: the DOM looks right and nothing works.
- **Run the a11y spec against a production build.** `axe` and the focus
  assertions are timing-sensitive and dev-mode double-rendering makes them
  flap.
- **Chromium version.** `playwright.config.ts` points at the preinstalled
  `/opt/pw-browsers/chromium-1194` when present, because it does not match the
  build Playwright 1.62 downloads by default.
- **Monaco drops fast keystrokes.** Type with a `delay`, and click
  `.monaco-editor .view-lines` rather than the hidden textarea, which the
  editor's own overlay intercepts.

Screenshots land in `e2e/screenshots/` on success and `test-results/` on
failure, alongside a trace: `npx playwright show-trace <path>`.
