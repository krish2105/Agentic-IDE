# Ṣāni' Studio v2 — "Glass Cockpit"

**Design + implementation plan · 2026-08-09**
Full-stack redesign and feature expansion. 6–8 weeks. Local-first, cloud-capable.

---

## 1. Executive summary

Ṣāni' Studio today is a technically strong agentic IDE wearing a developer-grade
interface. The engine — trust ladder, always-confirm tier, gapless event log,
tool-call disclosure before every action — is genuinely differentiated. The
surface does not communicate any of it.

This plan does two things at once:

1. **Rebuilds the interface** to the standard of an Awwwards-tier product, with
   real 3D, orchestrated motion, a multi-theme system, and state-reactive color.
2. **Adds nine features** that the market research says nobody currently ships
   well — most of which the existing architecture already supports and simply
   never surfaced.

The strategic bet is stated in §2 and it drives every decision below: **do not
compete on autonomy. Compete on legibility.**

---

## 2. Strategic thesis

### What the market is doing

| Product | 2026 headline |
|---|---|
| Cursor 3 "Glass" | 8 parallel agents across worktree/cloud/SSH; editor demoted below an Agents Window |
| Cursor v5 | Shadow Workspace — test in a background container before applying |
| Windsurf 2 | Cascade + "Flow State", 0-latency agentic loops |
| Zed | Rust-native speed, Claude Code as agentic companion |

Every one of them is racing on **autonomy**: more agents, faster loops, less
human in the path.

### What the market is missing

The 2026 research is unusually consistent on the counter-trend:

- Adoption is at a record high and **trust has collapsed** — "the trust paradox."
- **Agent decisions are opaque.** No audit trail means bad outcomes can't be
  debugged after the fact.
- The top developer frustration is **not** obviously bad output. It's code that
  *looks correct* while containing subtle errors.
- Traditional monitoring misses the characteristic agent failure: a tool call
  that succeeds, is misinterpreted, and poisons every subsequent turn.
- Design consensus: *"The interface is no longer the product; it is the
  governance layer that decides whether people adopt the agent or abandon it."*

### The position

Competitors are bolting governance onto autonomy engines. Ṣāni' already **is** a
governance engine — the safety model predates the UI and is enforced at a single
chokepoint (`sani_core.permissions.evaluate()`), not sprinkled through adapters.

So: **the first IDE where you can see the agent think, scrub backwards through
what it did, and feel trust accumulate.** Autonomy is table stakes. Legibility is
the moat.

This also resolves the interview-narrative problem flagged in `CLAUDE.md` — the
honest story stops being "I built an engine and shipped it twice" and becomes
"I identified that the industry optimised autonomy while trust collapsed, and
built the instrument panel for it."

### The concept: Glass Cockpit

Aviation replaced dozens of mechanical dials with integrated glass displays.
Pilots trust the glass cockpit not because it shows *more* data but because it
shows **state** — attitude, energy, intent, and what the automation is about to
do next. That is exactly this product's job.

Every design decision below traces back to that metaphor: layered translucent
instrument panels, damped physical motion, depth used to encode status, and an
absolute refusal to hide what the automation is doing.

---

## 3. Non-negotiable constraints

These come from `CLAUDE.md` and hold for every line of this plan.

1. **`sani-core` never imports a web framework.** All new engine logic lands in
   core; all HTTP/WS shapes land in `sani-server`.
2. **Clients hold no business logic.** Risk scores, blast radius, provenance and
   critique verdicts are **computed server-side** and streamed. The client
   renders. This is not negotiable and it is what keeps the VS Code extension and
   the web IDE from drifting.
3. **Both clients read a session through `@sani/client`.** Any new state goes
   into the shared reducer, once.
4. **Protocol invariants hold.** `seq` stays monotonic and gapless; the socket
   stays broadcast-only; `tool.proposed` fires for *every* action; terminal
   events end the stream.
5. **New event types are additive** — no `PROTOCOL_VERSION` bump. Every feature
   below is designed to exploit this rather than fight it.
6. **The always-confirm tier may be extended, never reduced.** No feature here
   creates a bypass.
7. **`propose()` stays side-effect free.** Blast-radius computation must not
   execute anything.

---

## 4. Design system

### 4.1 Concept language

| Axis | Direction |
|---|---|
| Surface | Layered translucent glass panels over a deep field; depth is real z-space, not shadows |
| Motion | Instrument-grade: damped springs, never linear; things settle, they don't stop |
| Type | Technical grotesque display + monospace for all data. Kinetic weight on hero moments only |
| Density | Cinematic at decision surfaces (Mission Control, launch, approval), ruthlessly dense at work surfaces (editor, terminal) |
| Color | Semantic before decorative — see the sacred rule below |

### 4.2 The sacred color rule (preserved, strengthened)

The existing rule is the product's core claim and survives every theme:

- `--color-agent` (violet) marks **agent-authored things only** — agent messages,
  added diff lines, agent-touched files, provenance overlays.
- `--color-attention` (amber) means **this needs you** — and nothing else.

v2 adds a third reserved channel:

- `--color-risk` (graduated amber→red) is reserved for **computed risk**, used
  only by blast-radius and critique surfaces.

Three reserved channels, no exceptions. Everything else draws from the neutral
ramp and the active theme's chrome hues.

### 4.3 Theme system

Six hand-tuned themes, switched via `data-theme` on `<html>`, all Tailwind v4
`@theme` token layers. Agent violet and attention amber are re-tuned per theme
for contrast but never re-assigned.

| Theme | Base | Character |
|---|---|---|
| **Void** (default) | near-black `#0b0d12` | Refined evolution of today's palette |
| **Nebula** | deep indigo | Cooler, more saturated, higher drama |
| **Aurora** | teal-black | Cold cyan chrome; violet agent pops hardest here |
| **Solar** | warm brown-black | Low-blue, evening-friendly |
| **Mono** | pure neutral | Grayscale chrome, *only* agent violet and attention amber carry hue — maximum semantic clarity, the connoisseur's choice |
| **Daylight** | warm off-white | A genuinely good light theme, which dev tools rarely ship |

Theme changes cross-fade over ~400ms via CSS custom property transitions on a
wrapper, not a hard repaint.

### 4.4 Reactive state color

The ambient layer breathes with session status. This is subtle — it changes the
*temperature of the room*, never the semantic channels.

| Status | Ambient behaviour |
|---|---|
| idle / complete | Still. Cool. Slow drift. |
| planning | Slow violet convection in the shader field |
| executing | Faster drift; subtle directional flow |
| blocked-on-approval | Amber breathing + a soft vignette pulling focus to the approval card |
| failed | One red bloom, then settle to a dim ember |
| killed | Desaturate to near-monochrome |

Implemented as uniforms on the ambient shader plus a CSS variable on the shell.
Fully disabled under `prefers-reduced-motion` and at quality tier Minimal.

### 4.5 Typography

- **Display / UI:** a variable technical grotesque with real character. Primary
  recommendation **Bricolage Grotesque Variable** (free, genuinely distinctive,
  variable width + weight for kinetic moments). Fallback recommendation: Geist.
- **Data / code / terminal:** **Geist Mono** or **JetBrains Mono** variable.
- All sizing via `clamp()` on a fluid scale — no breakpoint jumps.
- Kinetic type (weight/width interpolation on scroll or state) is restricted to
  the hero and Mission Control section headers. Never in the work surface.

### 4.6 Motion primitives

A small vocabulary, applied consistently, all built on Motion v12 (`motion/react`):

| Primitive | Use |
|---|---|
| `rise` | Panels/cards entering: y+12 → 0, opacity 0 → 1, spring |
| `stagger` | Lists (files, plan steps, sessions), 28ms child delay |
| `settle` | Value changes: brief scale overshoot then damped return |
| `attention` | Amber pulse for pending approvals — the only looping animation allowed |
| `morph` | Shared-element transition (session card → full session view) via `layoutId` |
| `scrub` | Scroll- or timeline-linked, driven by `useTransform` + `useSpring` |

Rules: only `transform` and `opacity` animate on scroll. `backdrop-filter` is
used surgically on nav/modals/approval cards, never on large scrolling regions.
Everything gates behind `useReducedMotion()`.

---

## 5. 3D architecture

The user asked for 3D on every surface. That is honoured through a **tiered
budget** so "everywhere" never means "unusable."

### 5.1 Quality tiers

Auto-detected at boot via a GPU capability probe (renderer string, max texture
size, a 200ms frame-time sample) plus `prefers-reduced-motion`. User-overridable
and persisted.

| Tier | Hero | Mission Control | Cognition graph | Ambient |
|---|---|---|---|---|
| **Ultra** | Full volumetric scene, post-processing | 3D navigable space, depth-of-field | 3D force graph, bloom | Animated shader mesh |
| **Balanced** (default) | Simplified scene, no post | 3D, no DOF, fewer particles | 3D graph, no bloom | Cheap 2-layer shader |
| **Minimal** | Static gradient + CSS parallax | 2D card grid with motion | 2D SVG graph | CSS gradient only |
| **Off** | Static | Static grid | Static SVG | Flat color |

`Minimal` is also the automatic `prefers-reduced-motion` target. The product is
fully functional and still handsome at **Off** — that is the progressive
enhancement contract.

### 5.2 The four 3D surfaces

**A. Hero / launch (R3F, full scene)**
The signature moment. A slowly-rotating volumetric field where each drifting
node is a past session, dimly lit; the camera settles as the page loads and the
task input focuses. Establishes the metaphor in three seconds.

**B. Mission Control 3D (R3F, navigable)**
The centrepiece and the most novel surface. Sessions become objects in space:

- **Depth (z)** = recency
- **Emissive intensity** = activity
- **Clustering** = workspace
- **Amber halo + attention pulse** = awaiting your approval
- **Scale** = context consumed

Orbit/pan to navigate; click a session and the camera flies in while the card
`morph`s (shared `layoutId`) into the full session view. Falls back to an
animated 2D bento grid at Minimal.

**C. Agent cognition graph (R3F, lightweight, in-workspace)**
A live force-directed graph of the executing plan. Nodes are steps; they
illuminate as `plan.step.started` arrives and lock in on `completed`. Tool calls
pulse along edges. RAG retrieval draws beams from the retrieved chunks into the
node that consumed them — visualising `rag.retrieved`, which currently has no UI
at all despite being emitted before every plan.

This is the "watch the agent think" feature. Rendered in a right-dock tab, capped
at 45fps, paused when the tab is hidden.

**D. Ambient shader (fragment shader, everywhere)**
A cheap two-layer gradient mesh behind the shell, driven by the reactive-state
uniforms from §4.4. This is what makes the whole app feel alive rather than
static. Auto-degrades to a CSS gradient.

### 5.3 Performance contract

- 3D is **always** lazy-loaded and code-split; the shell renders and is
  interactive before any WebGL initialises.
- One `<Canvas>` per surface, never more than one mounted at a time.
- `frameloop="demand"` wherever the scene is not continuously animating.
- Hard budget: **workspace surfaces must hold 60fps on a mid-range laptop with
  the cognition graph open and a session streaming.** If they don't, the graph
  drops to 2D — the work surface wins every tradeoff.

---

## 6. Feature specifications

Nine features. Each lists what it is, why it's novel, the server work, the client
work, and the honest cost.

### 6.1 Time-Travel Session Replay ⭐ flagship

**What.** Scrub any session backward and forward like video. Watch files mutate,
plans branch, approvals land, diffs accumulate. Play at 1×/2×/8×. Jump to any
approval, failure, or file write. Share a deep link to `seq=N`.

**Why it's novel.** No shipping agentic IDE has this. Post-hoc auditability is
the single most-cited gap in the 2026 research, and the answer everywhere else is
a text log.

**Why it's nearly free here.** The event log is already monotonic, gapless, and
replayable from `seq=0` — the protocol was designed for reconnect, and replay is
the same primitive pointed at the past. Redis archive already persists it.

**Server.** Endpoint `GET /session/{id}/timeline` returning the indexed event
log plus computed keyframes (approvals, failures, writes). Reconstructed
file-state-at-seq derived by folding diffs — computed server-side per constraint
#2.

**Client.** A timeline scrubber component; the shared reducer already folds
events, so replay = feeding it historical events with a clock. Add
`replayToSeq(n)` to `@sani/client`.

**Cost.** Medium-low. High demo value.

---

### 6.2 Blast-Radius Preview + Risk Scoring ⭐ flagship

**What.** Before you approve anything, see exactly what it will touch: files,
lines added/removed, dependencies affected, whether it's reversible, whether it
leaves the workspace, whether it reaches the network — plus a computed 0–100 risk
score with the reasoning that produced it.

**Why it's novel.** The research names this precisely: *"approval must block side
effects, not review them afterward,"* and the top complaint is code that looks
fine but isn't. Every competitor shows you a diff and asks "ok?". None of them
tell you the blast radius first.

**Why it fits.** `propose()` is already side-effect free and already returns a
`preview` (it's how `runs_in` is shown before approval). This extends an existing
seam rather than inventing one.

**Server.** New `sani_core.risk` module computing a `RiskAssessment` from the
proposed action. New additive event `risk.assessed` emitted alongside
`approval.required`. Score factors: action type tier, reversibility, file count,
LOC delta, whether tests cover the touched paths, whether it's outside the
workspace, network reach.

**Client.** Redesigned approval card — the money shot of the whole product. Risk
dial, expandable reasoning, per-hunk checkboxes (already supported), and a
"what happens if I reject" line.

**Cost.** Medium. Highest strategic value — it is the thesis made visible.

---

### 6.3 Multiplayer Observer Mode

**What.** Share a link; others watch the session live — same frames, same diffs,
same approval state. Presence avatars. Optionally hand approval rights to
another viewer.

**Why it's nearly free.** *"Multiple clients may subscribe to one session; they
all receive identical frames"* is already a protocol invariant with a test. The
socket is broadcast-only by design. This is largely a UI and auth affordance over
behaviour that already exists.

**Server.** Presence tracking (who's connected to which session), a scoped
read-only share token, and an explicit approval-delegation grant.

**Client.** Presence bar, viewer cursors on the timeline, "X is watching" state.

**Cost.** Low-medium. Disproportionate demo impact (pair-review a live agent).

---

### 6.4 ⌘K Command Palette

**What.** The universal control surface: run a session, jump to a file, switch
theme, approve/reject, pause/kill, open Mission Control, scrub to an event,
change quality tier. Fuzzy, keyboard-first, with recent/contextual ranking.

**Why.** Table stakes for a premium developer tool, and the product currently has
none. It is also the fastest way to make a dense UI feel fast.

**Cost.** Low. Built on `cmdk`. Ship early — it improves every later phase.

---

### 6.5 Agent Cognition Graph (3D)

Specified in §5.2C. Surfaces `rag.retrieved`, which today has no UI despite being
emitted before every plan — the "code silently steering a plan" opacity the
project's own docs call out as unacceptable.

**Server.** None required (events already exist); optionally enrich
`plan.proposed` with step dependency edges so the graph is a DAG rather than a
chain.

**Cost.** Medium-high (it's the hardest 3D to make *legible* rather than pretty).

---

### 6.6 Provenance Heatmap — "git blame for AI"

**What.** Every line in the workspace color-coded by origin: human, agent (which
session, which model, when), or mixed. Age decay so old agent code fades toward
neutral. A workspace-level heatmap showing which regions of the codebase are
increasingly agent-authored.

**Why it's novel.** Nobody ships this. It directly answers the enterprise
question the research raises — *what did the agent actually write, and can I
audit it* — and it makes the violet semantic rule scale from a single diff to an
entire repository.

**Server.** A provenance store (line-range attribution per file, updated on every
`diff.generated`), persisted alongside the session archive. New endpoint
`GET /provenance?workspace=`. New additive event `provenance.updated`.

**Client.** Monaco decorations for the open file; a workspace treemap for the
overview.

**Cost.** High — attribution must survive edits, which means range-mapping on
every human save. Highest novelty of anything in this plan.

---

### 6.7 Self-Critique Pass

**What.** Before a diff reaches you, a second model reviews the agent's own
output against the task and the retrieved context, and attaches a verdict:
confidence, specific concerns, and lines it thinks are wrong.

**Why.** Targets the #1 documented failure mode — plausible-looking wrong code —
and it composes with the existing gate rather than replacing it: the critique is
*advisory input to your approval*, never an auto-approver.

**Server.** New `critique.emitted` event. A `Critic` adapter in core (model-backed,
scripted fallback so the test suite stays deterministic and API-key-free).

**Cost.** Medium. Note: costs a second inference per diff — surfaced in 6.8.

---

### 6.8 Live Cost & Token Economics

**What.** Real-time spend: tokens in/out, cost per step, cost per session,
burn rate, projected cost to completion, and cost-per-accepted-diff. Historical
cost across sessions.

**Why.** `context.usage` already fires after every step and the UI shows a bare
number. Token economics is named in the research as a first-class 2026 skill, and
no IDE surfaces it well.

**Server.** Extend `context.usage` with model pricing and cumulative cost. Real
token counts from LiteLLM rather than the current `len/4` estimate (which the
docs already flag as `"estimated": true`).

**Cost.** Low. Very high perceived polish.

---

### 6.9 Parallel Agent Race (Tier 3 — staged)

**What.** Dispatch N agents at one task in isolated git worktrees. Watch them
race live in Mission Control 3D. Diff their solutions side-by-side. Keep the
winner, discard the rest — or cherry-pick hunks across solutions.

**Why.** This is Cursor's headline feature, but with the approval gate and risk
scoring on top — which is the differentiator, not the parallelism.

**Server.** Worktree orchestration, a race coordinator, per-worktree sandboxes,
and cross-session diff comparison. This is the largest infrastructure lift in the
plan.

**Cost.** High. Explicitly staged to Phase 6 and cuttable without harming
anything else.

---

## 7. Technical architecture

### 7.1 Stack additions

| Layer | Addition | Why |
|---|---|---|
| Motion | `motion` v12 (`motion/react`) | All 2D animation. WAAPI-backed, 120fps-capable |
| 3D | `@react-three/fiber`, `@react-three/drei` | Hero, Mission Control, cognition graph |
| Post | `@react-three/postprocessing` | Ultra tier only, lazy |
| Scroll | `lenis` | Marketing/Mission Control **only** — never the editor |
| Palette | `cmdk` | Command palette |
| Primitives | Radix UI (via shadcn) | Accessible dialog/popover/tooltip/tabs |
| Charts | `visx` or hand-rolled SVG | Cost + provenance viz; no heavyweight chart lib |

Everything lazy-loaded and code-split. The shell must be interactive before any
of it initialises.

### 7.2 Where state lives

```
sani-core            risk scoring · critique · provenance model · replay folding
   ↓ (events, additive types only)
sani-server          orchestration · worktrees · presence · provenance store
   ↓ (WS protocol v1, unchanged envelope)
@sani/client         reducer · replay · SessionStream  ← single source of truth
   ↓
web IDE  +  VS Code extension     pure renderers
```

New UI-only state (theme, quality tier, panel layout, palette open) lives in a
small separate client store and never mixes with session state.

### 7.3 New event types (all additive — no protocol bump)

```
risk.assessed          computed blast radius + score, alongside approval.required
critique.emitted       second-model verdict on a proposed diff
provenance.updated     line attribution delta after a write
race.started/progress  parallel agent race coordination
presence.changed       observers joined/left
```

Clients ignore unknown event types — there is already a test for this — so older
clients keep working against a newer server.

### 7.4 New endpoints

```
GET  /session/{id}/timeline        indexed replay data + keyframes
GET  /session/{id}/blast-radius    current pending action's computed impact
GET  /provenance?workspace=        line-level attribution for a workspace
POST /race                         start a parallel agent race
GET  /race/{id}                    race state + per-agent diffs
POST /session/{id}/share           mint a scoped read-only observer token
```

### 7.5 Security posture (cloud-capable)

Moving beyond a single shared bearer token is a prerequisite for real
multiplayer, and `CLAUDE.md` already names it as the top blocker for exposure:

- Per-user identity and revocable tokens, replacing the one shared secret.
- Scoped share tokens: read-only by default, approval rights explicitly granted.
- Workspace isolation enforced per user in cloud mode.
- Sandbox default flips to `sandbox-exec` on macOS / `docker` on Linux for any
  non-local deployment. (`LocalSandbox` stays honest about providing no isolation.)

---

## 8. Phasing — 8 weeks

Each phase is independently shippable. Stop after any phase and the product is
coherent.

### Phase 0 — Foundation (Week 1)
Design tokens and the six themes · theme engine + cross-fade · reactive-state
color plumbing · motion primitive library · quality-tier detection · install and
code-split the stack · glass panel / button / input primitives · **⌘K command
palette** (early, because it accelerates everything after).
*Ships:* the app looks and feels new even before any new features exist.

### Phase 1 — Decision surfaces (Week 2)
Landing + session launcher with hero 3D · **Mission Control 3D** · session tabs ·
status bar · shared-element `morph` from session card into session view.
*Ships:* the signature moment and the strongest screenshot in the product.

### Phase 2 — Work surface (Week 3)
Editor pane, file tree, terminal, right dock rebuilt · **redesigned approval
card** · diff view with per-hunk controls · ambient shader integrated.
*Ships:* the daily-driver half is now as good as the cinematic half.

### Phase 3 — Tier 1 features (Week 4)
**Time-travel replay** (server + client) · **cost/token economics** ·
**multiplayer observer mode** + presence.
*Ships:* three features nobody else has, on top of a finished UI.

### Phase 4 — Risk + cognition (Week 5)
**Blast-radius + risk scoring** end to end · **agent cognition graph 3D** ·
`rag.retrieved` finally gets a UI.
*Ships:* the thesis — governance made visible — is now literally on screen.

### Phase 5 — Provenance + critique (Week 6)
**Provenance heatmap** (store, endpoint, Monaco decorations, workspace treemap) ·
**self-critique pass**.
*Ships:* the enterprise/audit story.

### Phase 6 — Parallel agent race (Week 7, cuttable)
Worktree orchestration · race coordinator · side-by-side solution diffing ·
race visualisation in Mission Control 3D.

### Phase 7 — Hardening (Week 8)
Performance passes against the §5.3 budget · full keyboard/a11y audit ·
`prefers-reduced-motion` verification at every tier · Playwright coverage of new
surfaces · cross-client parity check (web vs VS Code) · docs and `CLAUDE.md`
update.

---

## 9. Risks and mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| 3D everywhere tanks the work surface | **High** | Tiered budget (§5.1); hard 60fps contract; graph auto-drops to 2D; workspace wins every tradeoff |
| Provenance attribution drifts after human edits | **High** | Range-map on every save; treat drift as expected and decay confidence rather than claiming false precision |
| Scope: 9 features + full redesign in 8 weeks | **High** | Phases are independently shippable; Phase 6 explicitly cuttable; Tier 1 lands by Week 4 |
| Critique pass doubles inference cost | Medium | Off by default; surfaced live in the cost meter; scripted fallback keeps tests free |
| Business logic drifting into the client | Medium | Constraint #2 enforced at review; all scoring/attribution computed server-side |
| Motion becoming decoration | Medium | Every animation must encode state or direct attention; the only looping animation permitted is the attention pulse |
| Multi-theme weakening the semantic color rule | Medium | Agent violet and attention amber are re-tuned per theme for contrast but never re-assigned; contrast asserted in tests |
| Cloud auth is a real project, not a flag | Medium | Phase 7 scope; local-first remains the default and stays fully functional |

---

## 10. Success criteria

**Experiential**
- A first-time viewer understands what the product does within 10 seconds of the
  landing page, without reading body copy.
- The approval card makes the risk of an action obvious *before* the decision.
- A finished session can be replayed and understood by someone who wasn't there.

**Technical**
- 60fps on the work surface, mid-range laptop, cognition graph open, session
  streaming.
- Fully usable and visually coherent at quality tier **Off**.
- `prefers-reduced-motion` honoured on every surface.
- Lighthouse ≥ 90 performance on the landing page.
- Contrast ≥ 4.5:1 for body text in all six themes.
- Zero business logic added to either client.
- `PROTOCOL_VERSION` still `1`; older clients still work against the new server.

**Strategic**
- At least four features that no shipping competitor has.
- The interview narrative is defensible and true: *the industry optimised
  autonomy while trust collapsed; this is the instrument panel for it.*

---

## 11. Open questions for later phases

1. Should the critique pass use a *different* model family than the planner
   (diversity of failure modes) or the same one (cost/latency)?
2. Does provenance need to survive `git` operations (rebase, squash), or is
   working-tree attribution sufficient for v2?
3. Should Mission Control 3D scale to hundreds of sessions, or is it explicitly a
   tens-of-sessions surface with a 2D table as the escape hatch?
4. Is the VS Code extension expected to reach parity on the new features, or does
   it deliberately stay the lightweight surface?
