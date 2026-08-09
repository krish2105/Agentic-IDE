# Glass Cockpit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Ṣāni' Studio web IDE to Awwwards-tier visual quality and add nine legibility features that no shipping agentic IDE has.

**Architecture:** Client stays a pure renderer. All scoring, attribution, and replay folding is computed in `sani-core`, transported through additive event types (no `PROTOCOL_VERSION` bump), and consumed through the shared `@sani/client` reducer so the VS Code extension inherits the same state for free. 3D is code-split behind a runtime quality tier that degrades to a fully functional 2D product.

**Tech Stack:** Next.js 16 (App Router) · React 19 · Tailwind v4 · Motion v12 (`motion/react`) · React Three Fiber + drei · cmdk · Lenis · FastAPI · Python 3.12

## Global Constraints

- `sani-core` must never import a web framework. HTTP/WS shapes live in `sani-server`.
- Clients hold no business logic. Risk, provenance, critique, and replay folding are server-computed.
- Both clients read session state through `@sani/client` — one reducer, no duplicates.
- `seq` stays monotonic and gapless; the stream socket stays broadcast-only; `tool.proposed` fires for every action including auto-approved ones.
- New event types are additive only. `PROTOCOL_VERSION` stays `1`.
- The always-confirm tier may be extended, never reduced.
- `propose()` stays side-effect free — blast-radius computation must not execute anything.
- Reserved color channels: `--color-agent` = agent-authored only; `--color-attention` = needs the human; `--color-risk` = computed risk. No other use, in any theme.
- Only `transform` and `opacity` animate on scroll. `backdrop-filter` is surgical.
- Every animation gates behind `useReducedMotion()`; the product stays fully usable at quality tier `off`.
- Work surface holds 60fps on a mid-range laptop. When 3D and density conflict, density wins.

---

## Phase 0 — Foundation

### Task 0.1: Dependencies and quality-tier detection

**Files:**
- Modify: `apps/web/package.json`
- Create: `apps/web/lib/quality.ts`
- Test: `apps/web/lib/quality.test.ts`

**Interfaces:**
- Produces: `type QualityTier = "ultra" | "balanced" | "minimal" | "off"`, `detectQualityTier(env): QualityTier`, `QUALITY_STORAGE_KEY`

- [ ] Install `motion`, `@react-three/fiber`, `@react-three/drei`, `cmdk`, `lenis`, `three`, `@types/three`
- [ ] Write `detectQualityTier` as a pure function taking `{ reducedMotion, deviceMemory, hardwareConcurrency, webglTier, saveData }` so it is testable without a browser
- [ ] Reduced motion or `saveData` forces `minimal`; no WebGL forces `off`; low memory/cores caps at `minimal`
- [ ] Commit

### Task 0.2: Six-theme token system

**Files:**
- Modify: `apps/web/app/globals.css`
- Create: `apps/web/lib/themes.ts`

**Interfaces:**
- Produces: `THEMES: ThemeId[]`, `type ThemeId = "void" | "nebula" | "aurora" | "solar" | "mono" | "daylight"`, `THEME_META: Record<ThemeId, {label, hint}>`

- [ ] Define the neutral ramp, chrome hues, and three reserved channels per theme under `[data-theme="..."]`
- [ ] Keep `--color-agent` violet and `--color-attention` amber semantically identical across all six; re-tune lightness only for contrast
- [ ] Add `--ambient-hue`, `--ambient-intensity`, `--ambient-speed` driven by session status
- [ ] Commit

### Task 0.3: Theme provider and reactive ambient state

**Files:**
- Create: `apps/web/components/system/ThemeProvider.tsx`
- Create: `apps/web/lib/useAmbientState.ts`

**Interfaces:**
- Produces: `useTheme(): {theme, setTheme, quality, setQuality}`, `useAmbientState(status)` writing CSS vars

- [ ] Persist theme + quality to `localStorage`, hydrate without flash via an inline pre-paint script
- [ ] Map session status → ambient variables per spec §4.4
- [ ] Commit

### Task 0.4: Motion primitives

**Files:**
- Create: `apps/web/lib/motion.ts`

**Interfaces:**
- Produces: `rise`, `stagger`, `settle`, `attention`, `springs`, `useGatedMotion()`

- [ ] Export shared variants and spring configs so no component hand-rolls timings
- [ ] `useGatedMotion` returns inert variants when `useReducedMotion()` is true
- [ ] Commit

### Task 0.5: Glass UI primitives

**Files:**
- Create: `apps/web/components/ui/GlassPanel.tsx`
- Create: `apps/web/components/ui/Button.tsx`
- Create: `apps/web/components/ui/Kbd.tsx`

- [ ] `GlassPanel` takes `elevation` and applies `backdrop-filter` only at elevation ≥ 2
- [ ] `Button` variants: `primary | ghost | danger | attention`, real `<button>`, visible focus ring
- [ ] Commit

### Task 0.6: Command palette

**Files:**
- Create: `apps/web/components/system/CommandPalette.tsx`
- Create: `apps/web/lib/commands.ts`
- Modify: `apps/web/app/layout.tsx`

**Interfaces:**
- Produces: `useCommandPalette()`, `registerCommands(cmds)`

- [ ] `cmdk` dialog on ⌘K/Ctrl+K with fuzzy search and grouped sections
- [ ] Static commands: theme switch, quality tier, new session, mission control
- [ ] Session-scoped commands registered dynamically by the session page
- [ ] Commit

---

## Phase 1 — Decision surfaces

### Task 1.1: Ambient shader background
`apps/web/components/three/AmbientField.tsx` — two-layer fragment shader reading `--ambient-*`; CSS-gradient fallback at `minimal`/`off`; lazy-loaded.

### Task 1.2: Hero 3D scene
`apps/web/components/three/HeroField.tsx` — volumetric node field, camera settle on load, `frameloop="demand"` once idle.

### Task 1.3: Landing / session launcher rebuild
`apps/web/app/page.tsx` — kinetic headline, glass launcher, connection panel restyled, Mission Control preview.

### Task 1.4: Mission Control 3D
`apps/web/components/three/MissionControl3D.tsx` — sessions as objects; z = recency, emissive = activity, halo = awaiting approval, scale = context used. 2D bento fallback.

### Task 1.5: Shared-element transition
`layoutId` morph from session object → session view; status bar and session tabs rebuilt.

---

## Phase 2 — Work surface

### Task 2.1: Shell and dock chrome
Rebuild `StatusBar`, `SessionTabs`, `RightDock` on the new primitives.

### Task 2.2: File tree and editor pane
Agent-touched files carry the violet channel; Monaco theme generated from active theme tokens.

### Task 2.3: Approval card — the money shot
`ApprovalCard` rebuilt: risk dial slot, per-hunk checkboxes, `runs_in` badge, reject consequence line.

### Task 2.4: Diff view and terminal
Per-hunk controls, agent-line gutter, xterm theme bound to tokens.

---

## Phase 3 — Tier 1 features

### Task 3.1: Replay — server
`GET /session/{id}/timeline`: indexed log + keyframes (approvals, failures, writes) + file-state-at-seq folding, computed server-side.

### Task 3.2: Replay — shared client
`replayToSeq(n)` in `@sani/client`; reuse the existing reducer, no duplicate fold logic.

### Task 3.3: Replay — UI
Scrubber, playback speeds, keyframe markers, deep link to `?seq=N`.

### Task 3.4: Cost and token economics
Extend `context.usage` with real LiteLLM token counts + pricing; live burn-rate meter; drop the `len/4` estimate where real counts exist.

### Task 3.5: Multiplayer observer mode
`presence.changed` event, `POST /session/{id}/share` minting scoped read-only tokens, presence bar, explicit approval delegation.

---

## Phase 4 — Risk and cognition

### Task 4.1: Risk engine in core
`sani_core/risk.py` — `RiskAssessment` from a proposed action. Factors: action tier, reversibility, file count, LOC delta, test coverage of touched paths, workspace escape, network reach. Pure and unit-testable.

### Task 4.2: `risk.assessed` event
Emitted alongside `approval.required`; wired through the reducer.

### Task 4.3: Blast-radius UI
Risk dial with expandable reasoning inside the approval card.

### Task 4.4: Agent cognition graph
`apps/web/components/three/CognitionGraph.tsx` — force-directed plan DAG; nodes light on `plan.step.started`; RAG beams from `rag.retrieved`. 2D SVG fallback. Capped at 45fps, paused when hidden.

---

## Phase 5 — Provenance and critique

### Task 5.1: Provenance store
Line-range attribution per file updated on `diff.generated`; persisted with the session archive; range-mapped on human saves with decaying confidence.

### Task 5.2: Provenance API and event
`GET /provenance?workspace=`, `provenance.updated`.

### Task 5.3: Provenance UI
Monaco decorations for the open file; workspace treemap for the overview.

### Task 5.4: Self-critique pass
`Critic` adapter in core with a scripted fallback so tests stay deterministic; `critique.emitted`; advisory only — never auto-approves.

---

## Phase 6 — Parallel agent race (cuttable)

Worktree orchestration, race coordinator, per-worktree sandboxes, side-by-side solution diffing, race visualisation in Mission Control 3D.

---

## Phase 7 — Hardening

Performance passes against the 60fps contract · keyboard/a11y audit · `prefers-reduced-motion` verified at every tier · Playwright coverage of new surfaces · web/VS Code parity check · `CLAUDE.md` update.
