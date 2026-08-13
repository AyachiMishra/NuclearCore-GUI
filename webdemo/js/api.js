/* api.js (Pyodide build) — same export surface as the server-backed api.js
 * in s3dash/web/static/js/, backed by s3dash.web.browser running inside
 * Pyodide instead of fetch(). app.js imports this file by the same relative
 * path ('./api.js') either way and cannot tell the two apart.
 */

import { call } from './pyodide-bridge.js';

let sampleBytes = null; // Uint8Array, fetched once and cached

const BEAVRS_SAMPLE = { name: '9074.out', sizeKb: null };

/** Static stand-in for GET /api/samples -- this demo ships exactly one
 *  bundled sample (BEAVRS), matching the project's example-data policy. */
export async function listSamples() {
  if (sampleBytes === null) {
    const res = await fetch('./sample_data/9074.out');
    if (!res.ok) return [];
    sampleBytes = new Uint8Array(await res.arrayBuffer());
    BEAVRS_SAMPLE.sizeKb = Math.round(sampleBytes.length / 1024);
  }
  return [{ name: BEAVRS_SAMPLE.name, sizeKb: BEAVRS_SAMPLE.sizeKb }];
}

export async function parseSample(name) {
  await listSamples(); // ensures sampleBytes is populated
  if (name !== BEAVRS_SAMPLE.name || sampleBytes === null) {
    throw new Error(`Unknown sample: ${name}`);
  }
  const r = await call('parse', sampleBytes, name);
  const { ok, ...payload } = r;
  return payload;
}

export async function parseUpload(file) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  const r = await call('parse', bytes, file.name);
  const { ok, ...payload } = r;
  return payload;
}

export async function fetchSection(runId, start, end, context = 2) {
  const r = await call(
    'section_text', runId,
    Math.max(0, start | 0), Math.max(0, end | 0), Math.min(200, Math.max(0, context | 0))
  );
  return r.text;
}

export async function searchText(runId, query) {
  const r = await call('search', runId, query, 200);
  const { ok, ...body } = r;
  return body;
}

export async function fetchLoadingPattern(runId) {
  const r = await call('loading_pattern', runId);
  const { ok, ...body } = r;
  return body;
}

export async function applyLoadingPattern(runId, changes) {
  const r = await call('apply_loading_pattern', runId, JSON.stringify(changes));
  const { ok, ...body } = r;
  return body;
}

export async function exportJson(runId) {
  const r = await call('export_json', runId);
  const text = JSON.stringify(r.payload, null, 2);
  return { blob: new Blob([text], { type: 'application/json' }), filename: null };
}

export async function exportCsv(runId, step) {
  const r = await call('export_csv', runId, step);
  return { blob: new Blob([r.csv], { type: 'text/csv' }), filename: null };
}

export async function fetchReportPdf(runId, step) {
  const r = await call('report_pdf', runId, step);
  const binary = atob(r.pdfBase64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return { blob: new Blob([bytes], { type: 'application/pdf' }), filename: null };
}
