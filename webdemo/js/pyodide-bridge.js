/* pyodide-bridge.js — boots Pyodide and exposes the same call surface
 * api.js normally gets from the FastAPI backend, backed by s3dash.web.browser
 * running in-process instead of over the network. Nothing downstream of
 * api.js knows the difference.
 */

// Check https://pyodide.org for the current stable release before deploying
// -- this is pinned deliberately (an unpinned CDN path would mean a Pyodide
// upstream release could silently change the demo's behaviour underneath
// this repo with no corresponding commit here).
const PYODIDE_VERSION = 'v0.26.4';
const PYODIDE_CDN = `https://cdn.jsdelivr.net/pyodide/${PYODIDE_VERSION}/full/`;

let pyodideReady = null;
let browserModule = null;

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error(`Could not load ${src}`));
    document.head.appendChild(s);
  });
}

/** Boots Pyodide, installs reportlab + our wheel, imports the adapter
 *  module. Safe to call more than once -- later calls await the same
 *  in-flight (or already-settled) boot rather than booting twice. */
export function boot() {
  if (pyodideReady) return pyodideReady;
  pyodideReady = (async () => {
    await loadScript(`${PYODIDE_CDN}pyodide.js`);
    const pyodide = await self.loadPyodide({ indexURL: PYODIDE_CDN });
    await pyodide.loadPackage('micropip');
    const micropip = pyodide.pyimport('micropip');
    await micropip.install('reportlab');
    // Filename fixed by tools/build_webdemo.py -- see the comment there for
    // why the version segment is a placeholder rather than the real one.
    await micropip.install('./s3dash-0-py3-none-any.whl');
    browserModule = pyodide.pyimport('s3dash.web.browser');
  })();
  return pyodideReady;
}

/** Calls a `s3dash.web.browser` function and unwraps its
 *  {ok, detail?, ...fields} envelope into a plain object, or throws
 *  Error(detail) -- the same contract api.js's check() already gives the
 *  rest of the app for HTTP responses. */
export async function call(fn, ...args) {
  await boot();
  const raw = browserModule[fn](...args);
  const result = JSON.parse(raw);
  if (!result.ok) throw new Error(result.detail || `${fn} failed`);
  return result;
}
