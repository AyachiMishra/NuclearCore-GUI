# UI Redesign — Visual Hierarchy & Polish Pass

Status: approved. Date: 2026-08-13.

## Goal

Redesign the dashboard's visual language so it reads as a professional
nuclear engineering analysis workstation, not an internal prototype —
without becoming a generic SaaS dashboard. Preserve every existing
interaction, the full data density, and the accessibility work already
baked into the core-map color ramp (WCAG-AA contrast, colorblind-safe
categorical palette, dark/light theming). This is a visual-system pass,
not a features or behavior change.

## Baseline critique (grounded in real screenshots of the deployed app)

1. No primary/secondary hierarchy — left rail, center map, and right rail
   carry roughly equal visual weight; nothing signals "look here first."
2. Flat typography scale — nearly everything sits at ~11-13px, so
   important numbers (k-effective) look as important as incidental ones
   (listing page count).
3. Controls scattered across three separate toolbar rows with no
   grouping.
4. Dense, undifferentiated label:value stacks (Run panel, Inspector's
   State Point block) — every row reads the same.
5. The warnings badge is a run-on sentence: "WARNINGS · 8 symmetry
   violations · 71 warnings" in one pill.
6. Primary navigation (view tabs, rail tabs) has almost no visual
   affordance — plain text with a small dot.
7. Every core-map cell fires four visual signals simultaneously (label,
   number, fill color, sometimes a flag triangle) at all times.
8. No deliberate spacing rhythm — panels butt against thin borders
   rather than composed whitespace.
9. Five adjacent header elements use five different button/pill styles.
10. The core map — the actual subject of the tool — is undersized,
    boxed into a modest center column instead of dominating the layout.

## Design principles

- **Map is the primary workspace.** Every other panel is visibly
  secondary — by background tone, not just position.
- **Hierarchy through scale, not decoration.** A real typographic and
  spacing scale does the work; no gradients, no SaaS card-shadow
  aesthetic, no rounded-everything treatment.
- **Density is a feature, not the bug.** Nothing gets removed or hidden;
  the fix is grouping, scale, and tone — not simplification.
- **Accessibility work is a floor, not a target.** The WCAG-AA-verified
  sequential ramp, the Okabe-Ito categorical palette, and dark/light
  theming are preserved exactly. Any color changes are re-verified
  against the same contrast bars already documented in `app.css`.

## Concrete design

### 1. Layout: map gets the growing space

`.layout`'s grid currently gives fixed-ish width to the rails and hands
*all* leftover space to the right rail (`minmax(230px,290px)
minmax(0,672px) minmax(340px,1fr)` on the map view) — backwards, since
the right rail can end up wider than the map. New column spec caps
*both* rails and gives the center column the growing share, e.g.
`minmax(220px,260px) minmax(680px,1fr) minmax(300px,380px)`. The map's
own container cap (`.coremap { max-width:600px }`) is removed outright
(back to the same `width:100%` its sibling `.legend` already uses) so it
fills whatever the new center column gives it, on any viewport.

### 2. Panel-tone hierarchy

Side-rail cards (`#meta-card`, `#panel-inspector`/`-diagnostics`/
`-inventory`, the edit panel) move to the existing `--panel-2` token
instead of `--panel`; the map card keeps `--panel`. This makes "primary
vs. supporting" legible from background tone alone, in both themes,
without touching layout.

### 3. Spacing scale

New tokens `--space-1` through `--space-6` (4/8/12/16/24/32px) on
`:root`, replacing ad hoc padding values across cards, toolbars, and
list rows. Applied first to the highest-visibility surfaces (header,
toolbar, card padding), then to list/table row spacing.

### 4. Typography scale

New tokens on `:root`: `--text-2xl` (24px, for the single most important
reactor metric — k-effective), `--text-lg` (15px, section headers),
`--text-base` (12.5px, primary data values — close to current, this
isn't shrinking further), `--text-sm` (10.5px, metadata/secondary
values, using the already-tuned `--text-faint`). k-effective in the
Inspector's State Point block gets the `--text-2xl` treatment as the
pilot application; other panels adopt the scale's base/sm split between
"identity" fields and "provenance" fields.

### 5. Button and status-chip system

One primary button style (solid `--accent` fill, reserved for "Load
listing"), the existing `.btn` becomes the secondary/default (outline),
`.btn-icon` stays for the theme toggle. The termination chip and
warnings chip move into one visually joined status group (shared
container, internal divider) instead of two floating pills. The
warnings chip's resting state shows a compact count only (detail already
surfaces on click, via the existing diagnostics-filter behavior) —
no behavior change, just a scannable resting state.

### 6. Navigation tabs

`.viewtab` (Core map / Plots / Sections & Search / Edit Loading Pattern)
gets a real active-state treatment (underline + weight change) and a
visible hover state. The rail's `.tab` (Inspector/Diagnostics/Inventory)
gets an analogous but visually lighter treatment, reinforcing that it's
subordinate to the main view nav.

### 7. Core map cell polish

Cell content is unchanged (site label + value stays — this is the
"necessary density" the brief explicitly preserves). Flag triangles and
hatch/calc markers drop in opacity/size so they read as available detail
rather than competing with the color data at rest. Label uses `--sans`,
value uses `--mono` with tabular-nums, sized per the new scale.

## Explicitly out of scope

- The sequential ramp's actual color math (`RAMP_LIGHT`/`RAMP_DARK` in
  `coremap.js`) and the categorical palette — both already WCAG-verified
  and colorblind-checked; touching them risks silently breaking that
  work for a purely aesthetic gain.
- Any interaction/behavior change. This is styling and markup grouping
  only.
- The loading-editor feature's own logic (Tasks 1-10, already shipped)
  — its UI inherits the new tokens automatically since it already reuses
  `.card`/`.btn`/`.notice-strip` etc.

## Files touched

- `s3dash/web/static/css/app.css` — the large majority of the work.
- `s3dash/web/static/index.html` / `webdemo/index.html` — structural
  regrouping only where a new wrapper element is needed (e.g. the status
  chip group); no new interactive elements, no JS changes expected.

## Verification

No visual-regression tooling exists, and this sandbox's Browser pane
cannot composite frames for self-screenshots (confirmed earlier this
session — `document.hidden` stays true regardless of viewport size, so
`computer: screenshot` times out). Verification is therefore two-track:
programmatic checks I run myself (computed styles, `getBoundingClientRect`
measurements, contrast-ratio recomputation for any touched colors)
covering correctness, plus an explicit screenshot checkpoint from the
user after the first substantial pass (layout + typography + spacing +
panel tone) before going deep on the remaining component-level polish —
so a wrong direction is caught early, not after the full pass.

## Known limitations

- Visual judgment ("does this look right") ultimately depends on the
  user's own screenshots at checkpoints, not on this session's own
  tooling.
- No automated way to prevent visual regressions on future changes;
  this pass establishes the token system but doesn't add tests.
