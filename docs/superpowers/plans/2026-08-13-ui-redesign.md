# UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the dashboard's visual hierarchy — core map as the clear primary workspace, every other panel visibly secondary — via a real spacing/typography scale, consolidated controls, and legible navigation, while preserving every existing interaction, the full data density, and the WCAG-verified color work.

**Architecture:** This is a CSS-and-markup pass, not a behavior change. New design tokens (spacing scale, typography scale) get defined once on `:root`; every subsequent task consumes them rather than hardcoding new magic numbers. Two small, explicitly-scoped, non-behavioral additions touch JS-adjacent rendering (a k-effective headline stat in `panels.js`, a marker-opacity constant in `app.css`) — everything else is pure CSS/HTML.

**Tech Stack:** Plain CSS custom properties (already the codebase's pattern), no build step, no new dependencies.

## Global Constraints

- No changes to `RAMP_LIGHT`/`RAMP_DARK`/`CATEGORICAL` in `coremap.js` — the sequential ramp and categorical palette are WCAG-AA-verified and colorblind-checked; out of scope per the design spec.
- No interaction/behavior changes. Every click handler, every piece of app state, every existing test-verified flow (loading-editor, exports, filters, search) stays exactly as-is.
- Every new color-carrying token must follow the existing three-place pattern if it needs a dark-mode variant (bare `:root`, then `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { ... } }`, then `:root[data-theme="dark"] { ... }`). Pure-size tokens (spacing, type scale) need none of this — a single bare `:root` definition is correct and sufficient.
- This sandbox's Browser pane cannot composite frames for self-screenshots (`computer: screenshot` times out — confirmed repeatedly this session). Verification is programmatic (`getComputedStyle`, `getBoundingClientRect` via `javascript_tool`) against a dev server on a **fresh port per task** — this environment aggressively HTTP-caches static JS/CSS per-origin even through hard reloads, and the only reliable fix found this session is a never-before-used port. Pattern per task: start `python -m uvicorn s3dash.web.app:app --port <N>` in the background, `preview_start`/`navigate` to it, `resize_window` (viewport can report 0×0 on a fresh tab), then verify.
- Test command for the untouched Python backend: `python -m pytest -q` (283 passing; this plan touches no `.py` file, so this should never move).
- Direct commits to `main` after each task, per this session's established convention.

---

## Task 1: Design tokens — spacing scale, typography scale, panel-tone hierarchy

**Files:**
- Modify: `s3dash/web/static/css/app.css`
- Modify: `s3dash/web/static/index.html`
- Modify: `webdemo/index.html`

**Interfaces:**
- Produces: `--space-1` through `--space-6` (4/8/12/16/24/32px), `--text-2xl`/`--text-lg`/`--text-base`/`--text-sm` (24/15/12.5/10.5px) on `:root` — every later task in this plan consumes these instead of hardcoding new values. `.card-secondary` class and `.panel`'s own background change — the "this is supporting, not primary" signal every later task's panels rely on already being in place.

- [ ] **Step 1: Add the spacing and typography scale tokens**

In `s3dash/web/static/css/app.css`, the `:root` block currently ends:

```css
  --radius:        7px;
  --mono: ui-monospace, "SF Mono", SFMono-Regular, "Cascadia Mono", Consolas,
          "Liberation Mono", "DejaVu Sans Mono", monospace;
```

Insert the new tokens between those two lines:

```css
  --radius:        7px;
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 24px;
  --space-6: 32px;
  --text-2xl:  24px;
  --text-lg:   15px;
  --text-base: 12.5px;
  --text-sm:   10.5px;
  --mono: ui-monospace, "SF Mono", SFMono-Regular, "Cascadia Mono", Consolas,
          "Liberation Mono", "DejaVu Sans Mono", monospace;
```

These are pure sizes with no color component, so — unlike every other token in this block — they need no dark-mode counterpart in the `@media (prefers-color-scheme: dark)` or `:root[data-theme="dark"]` blocks below.

- [ ] **Step 2: Give `.panel` its own, permanently-secondary background**

`.panel` (line 886 as of this plan) is only ever applied to the right-rail tab content
(`#panel-inspector`/`#panel-diagnostics`/`#panel-inventory`) — never to the map. Change:

```css
.panel {
  background: var(--panel); border: 1px solid var(--border);
```

to:

```css
.panel {
  background: var(--panel-2); border: 1px solid var(--border);
```

`--panel-2` already has correct light/dark values (`#f4f7fa` / `#1a222c`) — no new token needed.

- [ ] **Step 3: Add a `.card-secondary` modifier**

`.card` (line 554) is shared between primary contexts (the map cards) and secondary ones
(Run metadata, text hits, the loading-editor's change panel), so its own default can't
change. Add a modifier right after the existing `.card-flush` rule:

```css
.card-flush { padding: 0; overflow: hidden; }
.card-secondary { background: var(--panel-2); }
```

- [ ] **Step 4: Apply `.card-secondary` to the three side-rail cards**

In `s3dash/web/static/index.html`, change:

```html
    <section class="card" id="meta-card" data-resizable>
```

to:

```html
    <section class="card card-secondary" id="meta-card" data-resizable>
```

Change:

```html
    <section class="card card-flush" id="search-card" data-resizable hidden>
```

to:

```html
    <section class="card card-flush card-secondary" id="search-card" data-resizable hidden>
```

Change:

```html
        <aside class="card card-flush" id="edit-panel-card" aria-label="Change summary and validation">
```

to:

```html
        <aside class="card card-flush card-secondary" id="edit-panel-card" aria-label="Change summary and validation">
```

Make the identical three changes in `webdemo/index.html`.

- [ ] **Step 5: Verify**

- Start a fresh server: `python -m uvicorn s3dash.web.app:app --port 8020` (background).
- `preview_start`/`navigate` to it, `resize_window` to 1280×800, patch rAF
  (`window.requestAnimationFrame = (cb) => setTimeout(() => cb(performance.now()), 0);`),
  load `case_002495.out`.
- Via `javascript_tool`:
  ```js
  const cs = getComputedStyle(document.documentElement);
  const meta = getComputedStyle(document.getElementById('meta-card'));
  const map = getComputedStyle(document.getElementById('view-map'));
  JSON.stringify({
    space3: cs.getPropertyValue('--space-3').trim(),
    text2xl: cs.getPropertyValue('--text-2xl').trim(),
    metaBg: meta.backgroundColor,
    mapBg: map.backgroundColor,
    tonesDiffer: meta.backgroundColor !== map.backgroundColor,
  })
  ```
  Expected: `space3` is `"12px"`, `text2xl` is `"24px"`, `tonesDiffer` is `true`.

- [ ] **Step 6: Commit**

```bash
git add s3dash/web/static/css/app.css s3dash/web/static/index.html webdemo/index.html
git commit -m "feat(ui): add spacing/typography scale tokens and panel-tone hierarchy"
```

---

## Task 2: Layout — the core map becomes the primary, growing workspace

**Files:**
- Modify: `s3dash/web/static/css/app.css`

**Interfaces:**
- Consumes: nothing new from Task 1 directly (this is a structural grid change), but is the change Task 1's panel-tone work exists to visually reinforce.
- Produces: the map view's center column now receives all leftover viewport width; `.coremap` has no width ceiling. No later task depends on new class names from this one.

- [ ] **Step 1: Flip which column grows**

Change (this is the map view's own override of the base `.layout` grid — the base rule
and the plots/edit/sections overrides are untouched):

```css
body[data-view="map"] .layout {
  grid-template-columns: minmax(230px, 290px) minmax(0, 672px) minmax(340px, 1fr);
}
```

to:

```css
body[data-view="map"] .layout {
  grid-template-columns: minmax(220px, 260px) minmax(680px, 1fr) minmax(300px, 380px);
}
```

- [ ] **Step 2: Remove the map's own width ceiling**

Change:

```css
.coremap { width: 100%; min-width: 0; max-width: 600px; margin-inline: auto; }
```

to:

```css
.coremap { width: 100%; min-width: 0; margin-inline: auto; }
```

Update the stale comment above it (currently describes the now-removed cap). Change:

```css
/* The map is capped so it sits inside the page rather than being the page; it
   still fills the column below that width, so narrow viewports lose nothing.
   Cap and column were both grown 20% (500 -> 600 px) — cell labels scale with
   the viewBox, so bigger cap means bigger type, not just more white. */
```

to:

```css
/* Uncapped: the map is the primary workspace, so it fills whatever the
   layout's center column gives it. Cell labels scale with the viewBox
   (coremap.js's own CELL/PAD constants), so a wider column means bigger,
   more legible cells, not just more surrounding white space. */
```

- [ ] **Step 3: Verify**

- Fresh server: `python -m uvicorn s3dash.web.app:app --port 8021` (background).
- Same setup as Task 1 (navigate, resize to 1280×800, patch rAF, load `case_002495.out`).
- Via `javascript_tool`:
  ```js
  JSON.stringify({
    coremapWidth: Math.round(document.getElementById('coremap').getBoundingClientRect().width),
    coremapMaxWidth: getComputedStyle(document.getElementById('coremap')).maxWidth,
  })
  ```
  Expected: `coremapMaxWidth` is `"none"`; `coremapWidth` is substantially larger than the
  old 600px ceiling (at 1280px viewport width, with the new column split, expect roughly
  650-750px — confirm it's clearly above 600, not that it hits an exact number, since the
  grid's `1fr` track depends on the two rail widths too).

- [ ] **Step 4: Commit**

```bash
git add s3dash/web/static/css/app.css
git commit -m "feat(ui): let the core map fill its column instead of capping at 600px"
```

---

## Task 3: Navigation — give the primary view tabs real affordance

**Files:**
- Modify: `s3dash/web/static/css/app.css`

**Interfaces:**
- Consumes: `--space-1`/`--space-2`/`--space-4`/`--text-base` from Task 1.
- Produces: nothing later tasks depend on. The rail's `.tab` (Inspector/Diagnostics/Inventory) is deliberately left unchanged in this task — the contrast between it and the strengthened `.viewtab` is what signals "this nav is primary, that one's subordinate," so leaving it alone is the correct move, not an oversight.

- [ ] **Step 1: Strengthen the view-nav tabs**

Change:

```css
.view-nav {
  display: flex; gap: 2px; flex: 0 0 auto;
  padding: 3px; border-radius: var(--radius);
  background: var(--panel-2); border: 1px solid var(--border);
}
.viewtab {
  padding: 6px 14px; border-radius: 5px;
  color: var(--text-dim); text-decoration: none;
  font: 650 11.5px/1.3 var(--sans); letter-spacing: .02em; white-space: nowrap;
}
.viewtab:hover { color: var(--text); background: var(--panel-3); }
.viewtab.is-active {
  background: var(--panel); color: var(--text);
  box-shadow: var(--shadow);
}
```

to:

```css
.view-nav {
  display: flex; gap: 2px; flex: 0 0 auto;
  padding: var(--space-1); border-radius: var(--radius);
  background: var(--panel-2); border: 1px solid var(--border);
}
.viewtab {
  padding: var(--space-2) var(--space-4); border-radius: 5px;
  color: var(--text-dim); text-decoration: none;
  font: 650 var(--text-base)/1.3 var(--sans); letter-spacing: .02em; white-space: nowrap;
}
.viewtab:hover { color: var(--text); background: var(--panel-3); }
.viewtab.is-active {
  background: var(--panel); color: var(--accent);
  box-shadow: var(--shadow);
}
```

(Only the `padding`/`font` values and `.is-active`'s `color` change — the `.viewtab.is-active::before` dot rule right after stays exactly as-is.)

- [ ] **Step 2: Verify**

- Fresh server: `python -m uvicorn s3dash.web.app:app --port 8022` (background).
- Same setup as Task 1, load `case_002495.out`.
- Via `javascript_tool`:
  ```js
  const active = document.querySelector('.viewtab.is-active');
  const accentHex = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();
  JSON.stringify({
    activeColor: getComputedStyle(active).color,
    padding: getComputedStyle(active).paddingLeft,
  })
  ```
  Expected: `padding` is `"16px"` (`--space-4`); `activeColor` is the `rgb(...)` form of
  `--accent` (`#14568f` in light mode → `rgb(20, 86, 143)`) — confirm it is NOT the same as
  an inactive tab's color (`getComputedStyle(document.querySelector('.viewtab:not(.is-active)')).color`,
  which should still resolve to `--text-dim`'s color).

- [ ] **Step 3: Commit**

```bash
git add s3dash/web/static/css/app.css
git commit -m "feat(ui): give the primary view tabs real active-state affordance"
```

---

## Task 4: Header — consolidate the status chips and add a real button hierarchy

**Files:**
- Modify: `s3dash/web/static/css/app.css`
- Modify: `s3dash/web/static/index.html`
- Modify: `webdemo/index.html`

**Interfaces:**
- Produces: `.status-group` (wraps the termination + warnings chips into one visually
  joined unit) and `.btn-primary` (the one solid-fill button style, applied to "Load
  listing"). No later task depends on these names, but Task 7's final pass re-checks them.

- [ ] **Step 1: Wrap the status chips in one group**

In `s3dash/web/static/index.html`, change:

```html
  <div class="header-actions">
    <span id="completion-chip" class="completion-chip" hidden></span>
    <div id="status-badge" class="status-badge" role="group" aria-label="Run diagnostics summary" hidden></div>

    <details class="menu menu-export" id="export-menu" hidden>
```

to:

```html
  <div class="header-actions">
    <div class="status-group">
      <span id="completion-chip" class="completion-chip" hidden></span>
      <div id="status-badge" class="status-badge" role="group" aria-label="Run diagnostics summary" hidden></div>
    </div>

    <details class="menu menu-export" id="export-menu" hidden>
```

Make the identical change in `webdemo/index.html`.

- [ ] **Step 2: Give "Load listing" the primary button treatment**

In `s3dash/web/static/index.html`, change:

```html
    <button type="button" id="btn-load" class="btn">Load listing</button>
```

to:

```html
    <button type="button" id="btn-load" class="btn btn-primary">Load listing</button>
```

Make the identical change in `webdemo/index.html`.

- [ ] **Step 3: Add the `.status-group` and `.btn-primary` CSS**

Add `.status-group` right after the `.header-actions` rule's responsive note (after the
`@media (max-width: 1120px) { .view-nav { order: 3; flex: 0 0 100%; } }` block, before
`.completion-chip`):

```css
.status-group {
  display: flex; align-items: center; gap: var(--space-2);
  padding: var(--space-1); border-radius: 20px;
  background: var(--panel-2); border: 1px solid var(--border);
}
```

Add `.btn-primary` right after the existing `.btn:active { transform: translateY(1px); }` rule:

```css
.btn:active { transform: translateY(1px); }
.btn-primary {
  background: var(--accent); color: var(--accent-text); border-color: var(--accent);
}
.btn-primary:hover {
  background: color-mix(in srgb, var(--accent) 88%, black);
  border-color: color-mix(in srgb, var(--accent) 88%, black);
}
```

- [ ] **Step 4: Verify**

- Fresh server: `python -m uvicorn s3dash.web.app:app --port 8023` (background).
- Same setup as Task 1, load `case_002495.out`.
- Via `javascript_tool`:
  ```js
  const btn = document.getElementById('btn-load');
  const accentHex = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();
  const group = document.querySelector('.status-group');
  const chip = document.getElementById('completion-chip');
  JSON.stringify({
    btnBg: getComputedStyle(btn).backgroundColor,
    groupContainsChip: group.contains(chip),
  })
  ```
  Expected: `groupContainsChip` is `true`; `btnBg` is the `rgb(...)` form of `--accent`
  (not the old `--panel-2` gray).

- [ ] **Step 5: Commit**

```bash
git add s3dash/web/static/css/app.css s3dash/web/static/index.html webdemo/index.html
git commit -m "feat(ui): consolidate header status chips and add a primary button style"
```

---

## Task 5: Checkpoint — request a real screenshot before going deeper

**Files:** none.

**Interfaces:** none — this is a pause point, not a code task.

Tasks 1-4 together are the "first substantial pass" the design spec's Verification
section calls for: hierarchy (tone + layout), primary navigation, and header
consolidation are all in place. Before continuing into the remaining component-level
polish (Tasks 6-7), stop and ask the user for a fresh screenshot of the map view (and,
if convenient, one other view) at a normal desktop width. This is the one thing this
session's tooling cannot self-verify — programmatic checks confirm the CSS resolves to
the intended values, not that the result actually reads well. Do not proceed to Task 6
until either a screenshot confirms the direction or the user explicitly says to continue
without one.

---

## Task 6: Typography scale on data — section headers, the Run panel, and a real headline for k-effective

**Files:**
- Modify: `s3dash/web/static/js/panels.js`
- Modify: `s3dash/web/static/css/app.css`

**Interfaces:**
- Consumes: `--text-2xl`/`--text-lg`/`--text-base`/`--text-sm`/`--space-2`/`--space-3` from
  Task 1 — this is the task where `--text-lg` (defined in Task 1, unused until now) gets
  its first consumer.
- Produces: `.stat-headline` — a reusable pattern; no other panel in this plan adopts it
  beyond k-effective, since it's explicitly a "the single most important number" pattern,
  not a general replacement for `kvTable()`.

- [ ] **Step 1: Apply the scale to section headers and the Run panel**

Two existing rules already carry the "identity vs. provenance" split the design calls
for structurally (`.card-head h2` for section titles, `.meta-k`/`.meta-v` for the Run
panel's labels/values) — they just hardcode sizes instead of using the new scale. Change:

```css
.card-head h2 {
  font-size: 12px; text-transform: uppercase; letter-spacing: .07em;
  color: var(--text-dim); font-weight: 700;
}
```

to:

```css
.card-head h2 {
  font-size: var(--text-lg); text-transform: uppercase; letter-spacing: .07em;
  color: var(--text-dim); font-weight: 700;
}
```

Change:

```css
.meta-k {
  font-size: 9.5px; text-transform: uppercase; letter-spacing: .07em;
  color: var(--text-faint); font-weight: 700; white-space: nowrap;
}
.meta-v {
  font-size: 11.5px; font-weight: 550; line-height: 1.4;
  min-width: 0; overflow-wrap: anywhere;
  font-variant-numeric: tabular-nums;
}
```

to:

```css
.meta-k {
  font-size: var(--text-sm); text-transform: uppercase; letter-spacing: .07em;
  color: var(--text-faint); font-weight: 700; white-space: nowrap;
}
.meta-v {
  font-size: var(--text-base); font-weight: 550; line-height: 1.4;
  min-width: 0; overflow-wrap: anywhere;
  font-variant-numeric: tabular-nums;
}
```

Broader per-panel "identity vs. provenance" differentiation beyond these two
highest-traffic spots (e.g. re-splitting every field in Control rods, Assembly detail,
and the Output Summary table) is intentionally deferred — it needs real per-panel
judgment about which specific fields count as which, not a mechanical value swap, and is
better scoped as its own follow-up once Task 5's checkpoint confirms this direction is
right.

- [ ] **Step 2: Add the headline stat, additive to the existing table**

In `s3dash/web/static/js/panels.js`, `renderInspector()` currently reads (this is the
exact current block, `stepRows` unchanged — k-effective stays in the full table too, for
scanability alongside the other State Point values):

```js
  if (is3d(p) && state.axialNode) {
    const nd = axialNodes().find((x) => x.node === state.axialNode);
    if (nd) {
      const cols = Object.keys(nd).filter((k) => k !== 'node');
      stepRows.push([
        `Axial node ${nd.node}`,
        cols.map((c) => `${c} ${fmt(nd[c], 4)}`).join(' · '),
      ]);
    }
  }
  out.push(section('State point', kvTable(stepRows)));
```

Insert a new headline block between the `if (is3d...)` block and the existing
`out.push(section('State point', ...))` line:

```js
  if (is3d(p) && state.axialNode) {
    const nd = axialNodes().find((x) => x.node === state.axialNode);
    if (nd) {
      const cols = Object.keys(nd).filter((k) => k !== 'node');
      stepRows.push([
        `Axial node ${nd.node}`,
        cols.map((c) => `${c} ${fmt(nd[c], 4)}`).join(' · '),
      ]);
    }
  }
  if (sp) {
    out.push(
      `<div class="stat-headline"><span class="stat-headline-label">k-effective</span>` +
      `<span class="stat-headline-value">${esc(fmtFixed(sp.keff, 5))}</span></div>`
    );
  }
  out.push(section('State point', kvTable(stepRows)));
```

- [ ] **Step 3: Add the `.stat-headline` CSS**

Add right after the `.sub > h3 { ... }` rule (which ends the block starting
`.sub { margin-bottom: 14px; }`):

```css
.stat-headline {
  display: flex; align-items: baseline; gap: var(--space-3);
  margin-bottom: var(--space-3); padding-bottom: var(--space-2);
  border-bottom: 1px solid var(--border);
}
.stat-headline-label {
  font-size: var(--text-sm); text-transform: uppercase; letter-spacing: .07em;
  color: var(--text-faint); font-weight: 700;
}
.stat-headline-value {
  font: 700 var(--text-2xl)/1 var(--mono); font-variant-numeric: tabular-nums;
  color: var(--text);
}
```

- [ ] **Step 4: Verify**

- Fresh server: `python -m uvicorn s3dash.web.app:app --port 8024` (background).
- Same setup as Task 1, load `case_002495.out`.
- Via `javascript_tool`:
  ```js
  const el = document.querySelector('.stat-headline-value');
  const h2 = getComputedStyle(document.querySelector('#view-map .card-head h2'));
  const metaK = getComputedStyle(document.querySelector('.meta-k'));
  JSON.stringify({
    text: el ? el.textContent : null,
    fontSize: el ? getComputedStyle(el).fontSize : null,
    h2FontSize: h2.fontSize,
    metaKFontSize: metaK.fontSize,
  })
  ```
  Expected: `fontSize` is `"24px"`; `text` matches the k-eff value already visible
  elsewhere in the State Point table (e.g. `"1.14074"` for `case_002495.out`'s first step);
  `h2FontSize` is `"15px"` (`--text-lg`); `metaKFontSize` is `"10.5px"` (`--text-sm`).

- [ ] **Step 5: Commit**

```bash
git add s3dash/web/static/js/panels.js s3dash/web/static/css/app.css
git commit -m "feat(ui): give k-effective a real headline treatment in the Inspector"
```

---

## Task 7: Core map marker polish + final full-app verification

**Files:**
- Modify: `s3dash/web/static/css/app.css`

**Interfaces:** none — this is the plan's last task.

- [ ] **Step 1: Quiet the flag marker at rest**

Change:

```css
.cell-flag { fill: var(--err); stroke-width: 3; pointer-events: none; }
```

to:

```css
.cell-flag { fill: var(--err); stroke-width: 3; pointer-events: none; opacity: .78; }
```

(`.cell-hatch` already carries its own opacity (`.42`) with a comment explaining the
"texture, not a shout" intent — left as-is; the flag triangle was the one marker with no
opacity control at all, making it the loudest of the three at rest.)

- [ ] **Step 2: Verify the marker change**

- Fresh server: `python -m uvicorn s3dash.web.app:app --port 8025` (background).
- Same setup as Task 1, load `case_002495.out`.
- Via `javascript_tool`: `getComputedStyle(document.querySelector('.cell-flag')).opacity`
  — expected `"0.78"` (only present if at least one symmetry-flagged cell exists in this
  run, which `case_002495.out` has — 8 per the header's own warnings count).

- [ ] **Step 3: Full-app regression pass**

On the same fresh server/tab:
- Switch to every view (`#/map`, `#/plots`, `#/sections`, `#/edit`) via `location.hash`
  and confirm each renders without a console error (`read_console_messages`,
  `onlyErrors: true`).
- Toggle dark mode (click `#btn-theme` twice to cycle auto → light → dark, or three times
  back to auto) and re-run Task 1's tone-check script — `tonesDiffer` must still be `true`
  in dark mode (confirms `--panel-2` swap wasn't accidentally hardcoded to a light-only
  color anywhere in this plan's changes).
- Perform one loading-editor drag (same technique as this session's earlier verification:
  dispatch real `pointerdown`/`pointermove`/`pointerup` on two `#edit-coremap` cells) and
  confirm it still works end-to-end — this plan changed `.card`/`.panel` backgrounds and
  `.coremap` sizing, both of which the edit view also uses, so this is a real regression
  check, not a formality.
- Run `python -m pytest -q` — expect `283 passed` (this plan touches no `.py` file, so
  this is a sanity confirmation, not expected to catch anything).

- [ ] **Step 4: Ask for a final screenshot**

Request one more screenshot from the user covering the map view, confirming the
consolidated header, the primary/secondary tone split, the larger map, and the
k-effective headline all read correctly together. Note any follow-up polish requests as
new, separately-scoped work rather than reopening this plan's tasks.

- [ ] **Step 5: Commit**

```bash
git add s3dash/web/static/css/app.css
git commit -m "feat(ui): quiet the core-map flag marker; final redesign pass"
```
