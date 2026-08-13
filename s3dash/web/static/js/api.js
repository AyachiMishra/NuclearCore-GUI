/* api.js — thin fetch wrappers around the FastAPI backend.
 *
 * Every call funnels through `check()` so a backend {"detail": "..."} body is
 * turned into an Error the UI can show verbatim. No third-party code.
 */

async function check(res) {
  if (res.ok) return res;
  let detail = `${res.status} ${res.statusText || 'Request failed'}`;
  try {
    const body = await res.json();
    if (body && typeof body.detail === 'string') detail = body.detail;
    else if (body && Array.isArray(body.detail)) {
      detail = body.detail.map((d) => d.msg || JSON.stringify(d)).join('; ');
    }
  } catch (_) {
    /* non-JSON error body — keep the status line */
  }
  const err = new Error(detail);
  err.status = res.status;
  throw err;
}

/** GET /api/samples -> [{name, sizeKb}] */
export async function listSamples() {
  const res = await check(await fetch('/api/samples'));
  const body = await res.json();
  return Array.isArray(body.samples) ? body.samples : [];
}

/** POST /api/samples/{name} -> {runId, ...payload} */
export async function parseSample(name) {
  const res = await check(
    await fetch(`/api/samples/${encodeURIComponent(name)}`, { method: 'POST' })
  );
  return res.json();
}

/** POST /api/parse (multipart) -> {runId, ...payload} */
export async function parseUpload(file) {
  const form = new FormData();
  form.append('file', file, file.name);
  const res = await check(await fetch('/api/parse', { method: 'POST', body: form }));
  return res.json();
}

/** GET /api/run/{id}/section -> raw listing text */
export async function fetchSection(runId, start, end, context = 2) {
  const q = new URLSearchParams({
    start: String(Math.max(0, start | 0)),
    end: String(Math.max(0, end | 0)),
    context: String(Math.min(200, Math.max(0, context | 0))),
  });
  const res = await check(await fetch(`/api/run/${encodeURIComponent(runId)}/section?${q}`));
  return res.text();
}

/** GET /api/run/{id}/search -> {hits:[{line,text,case,step,page}], truncated} */
export async function searchText(runId, query) {
  const q = new URLSearchParams({ q: query });
  const res = await check(await fetch(`/api/run/${encodeURIComponent(runId)}/search?${q}`));
  return res.json();
}

function filenameFromDisposition(res) {
  const disposition = res.headers.get('Content-Disposition') || '';
  const match = disposition.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
  return match ? decodeURIComponent(match[1]) : null;
}

/** GET /api/run/{id}/loading-pattern -> {supported, entries?, geometry?, suggested?, reason?} */
export async function fetchLoadingPattern(runId) {
  const res = await check(await fetch(`/api/run/${encodeURIComponent(runId)}/loading-pattern`));
  return res.json();
}

/** GET /api/run/{id}/export.json -> {blob, filename} */
export async function exportJson(runId) {
  const res = await check(await fetch(`/api/run/${encodeURIComponent(runId)}/export.json`));
  return { blob: await res.blob(), filename: filenameFromDisposition(res) };
}

/** GET /api/run/{id}/export.csv -> {blob, filename} */
export async function exportCsv(runId, step) {
  const url = `/api/run/${encodeURIComponent(runId)}/export.csv?step=${encodeURIComponent(step)}`;
  const res = await check(await fetch(url));
  return { blob: await res.blob(), filename: filenameFromDisposition(res) };
}

/** GET /api/run/{id}/report.pdf -> {blob, filename}
 *
 * Fetched rather than navigated to. A navigation swallows the backend's
 * {"detail": "..."} body and leaves the reader looking at a blank tab, and the
 * render takes a second or three — which can only be shown as a busy state if
 * the UI is the one waiting.
 */
export async function fetchReportPdf(runId, step) {
  const q = new URLSearchParams({ step: String(Number.isFinite(step) ? step | 0 : 0) });
  const res = await check(
    await fetch(`/api/run/${encodeURIComponent(runId)}/report.pdf?${q}`)
  );
  return { blob: await res.blob(), filename: filenameFromDisposition(res) || 'report.pdf' };
}
