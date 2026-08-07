/* views.js — client-side view routing.
 *
 * Three views share one document and one state object: switching a view only
 * toggles visibility, so the loaded run, the selected step, the selected
 * assembly and the active layer all survive a switch by construction.
 *
 * The route lives in location.hash ("#/plots"), so a reload — or a pasted
 * link — returns to the same view. The nav is built from real <a href>
 * elements, which makes it keyboard-reachable and focusable without any
 * roving-tabindex bookkeeping.
 */

import { state, update } from './state.js';

export const VIEWS = ['map', 'plots', 'sections'];
const DEFAULT_VIEW = 'map';

const VIEW_LABEL = { map: 'Core map', plots: 'Plots', sections: 'Sections & Search' };

/** Parse "#/plots" -> "plots". Unknown or absent routes fall back to the map. */
export function viewFromHash(hash = window.location.hash) {
  const name = String(hash || '').replace(/^#\/?/, '').split(/[?&/]/)[0].toLowerCase();
  return VIEWS.includes(name) ? name : DEFAULT_VIEW;
}

/** Show `view`, hide the rest, and tell the toolbar which groups still apply. */
export function applyView(view) {
  const name = VIEWS.includes(view) ? view : DEFAULT_VIEW;

  for (const v of VIEWS) {
    const el = document.getElementById(`view-${v}`);
    if (el) el.hidden = v !== name;
  }

  // The navigator and the section viewer live inside the Sections view itself,
  // so they need no separate toggle. The RUN metadata card is deliberately not
  // part of that view — there the left column is the navigator and the raw
  // text under it, nothing else. The detail panels belong to the map.
  const meta = document.getElementById('meta-card');
  if (meta) meta.hidden = name === 'sections' || !state.payload;
  const rail = document.getElementById('rail-right');
  if (rail) rail.hidden = name !== 'map' || !state.payload;

  document.querySelectorAll('#toolbar .tool-group[data-views]').forEach((g) => {
    g.hidden = !g.dataset.views.split(/\s+/).includes(name);
  });

  document.querySelectorAll('.viewtab').forEach((a) => {
    const on = a.dataset.view === name;
    a.classList.toggle('is-active', on);
    if (on) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });

  document.body.dataset.view = name;
  return name;
}

/** Programmatic navigation. Writing the hash lets the browser Back button work. */
export function goTo(view) {
  const name = VIEWS.includes(view) ? view : DEFAULT_VIEW;
  if (viewFromHash() === name && state.view === name) return;
  window.location.hash = `#/${name}`;
}

/** Wire the hash to state. `onEnter(view)` runs after each switch. */
export function initRouter(onEnter) {
  const sync = () => {
    const name = viewFromHash();
    applyView(name);
    if (state.view !== name) update({ view: name }, 'view');
    if (onEnter) onEnter(name);
  };
  window.addEventListener('hashchange', sync);
  // Normalise a bare or bad hash so the address bar always shows the real route.
  if (viewFromHash() !== String(window.location.hash).replace(/^#\/?/, '')) {
    history.replaceState(null, '', `#/${viewFromHash()}`);
  }
  state.view = viewFromHash();
  sync();
}

export function viewLabel(view) {
  return VIEW_LABEL[view] || view;
}
