"""Bundle the dashboard into one self-contained HTML file.

The served dashboard talks to FastAPI for parsing, raw section text and
search. A standalone file has no backend, so the parsed payload and the
listing's raw lines are baked in and `api.js` is swapped for an offline shim
that answers from those. Everything else -- the same CSS, the same modules,
the same rendering -- is byte-identical to what the server serves, so what you
test here is what the app does.

    python -m s3dash.bundle sample_data/case_002495.out -o output/dash.html

The result opens with a double-click, needs no Python and no network.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .parser import parse_file

STATIC = Path(__file__).parent / "web" / "static"

# Emission order must respect the import graph: a module may only depend on
# ones already registered. api.js is replaced by the offline shim below.
MODULE_ORDER = ["state.js", "coremap.js", "views.js", "charts.js", "panels.js", "loadingeditor.js", "app.js"]

# Each module keeps its own scope. Flattening them into one shared scope looks
# simpler but breaks the moment two modules declare the same private helper --
# several here define a top-level `$` DOM shorthand.
_NAMED_IMPORT_RE = re.compile(
    r"^[ \t]*import\s*\{(?P<names>[^}]*)\}\s*from\s*['\"]\./(?P<mod>[\w.]+)['\"];?[ \t]*$",
    re.M,
)
_NS_IMPORT_RE = re.compile(
    r"^[ \t]*import\s*\*\s*as\s+(?P<ns>\w+)\s*from\s*['\"]\./(?P<mod>[\w.]+)['\"];?[ \t]*$",
    re.M,
)
_DEFAULT_IMPORT_RE = re.compile(
    r"^[ \t]*import\s+(?P<name>\w+)\s*from\s*['\"]\./(?P<mod>[\w.]+)['\"];?[ \t]*$",
    re.M,
)
_BARE_IMPORT_RE = re.compile(r"^[ \t]*import\s+['\"][^'\"]+['\"];?[ \t]*$", re.M)
_EXPORT_DECL_RE = re.compile(
    r"^([ \t]*)export\s+(?=(?:async\s+)?(?:function|const|let|var|class)\b)", re.M
)
_EXPORT_NAME_RE = re.compile(
    r"^[ \t]*export\s+(?:async\s+)?(?:function|const|let|var|class)\s+(\w+)", re.M
)
_EXPORT_LIST_RE = re.compile(r"^[ \t]*export\s*\{(?P<names>[^}]*)\}\s*;?[ \t]*$", re.M)

_LOADER = """
/* Minimal module registry. Each module runs in its own function scope and
 * publishes its exports, so private helpers with the same name in different
 * modules cannot collide. */
const __defs = {};
const __cache = {};
function __req(name) {
  if (__cache[name]) return __cache[name];
  const exports = {};
  __cache[name] = exports;
  __defs[name](exports, __req);
  return exports;
}
function __def(name, fn) { __defs[name] = fn; }
"""

_OFFLINE_API = """
/* Offline API shim: answers from data baked into this file. Signatures match
 * api.js exactly, so every caller is unchanged. */
const __DATA = window.__S3_BUNDLE__;

export async function listSamples() {
  return __DATA.samples.map((s) => ({ name: s.name, sizeKb: s.sizeKb }));
}

export async function parseSample(name) {
  const s = __DATA.samples.find((x) => x.name === name);
  if (!s) throw new Error(`Sample ${name} is not bundled in this file.`);
  return { runId: s.name, ...s.payload };
}

export async function parseUpload(file) {
  /* A snapshot carries no parser, but it does carry these listings. Picking
   * one of them through the file browser is the obvious thing to try, so
   * match it and serve the embedded copy instead of refusing. */
  const wanted = String(file && file.name || '').toLowerCase();
  const hit = __DATA.samples.find((s) => s.name.toLowerCase() === wanted);
  if (hit) return { runId: hit.name, ...hit.payload };

  const stem = wanted.replace(/\\.(out|txt|lis|log)$/, '');
  const near = __DATA.samples.find(
    (s) => s.name.toLowerCase().replace(/\\.(out|txt)$/, '') === stem
  );
  if (near) return { runId: near.name, ...near.payload };

  const names = __DATA.samples.map((s) => s.name).join(', ');
  const err = new Error(
    `This is a standalone snapshot: it has the parsed results baked in, but not the `
    + `parser itself, so it cannot read a listing it was not built with. `
    + `Available here: ${names}. `
    + `To open your own listings run the dashboard with "python -m s3dash", or build `
    + `a new snapshot with "python -m s3dash.bundle your_run.out -o your_run.html".`
  );
  err.status = 501;
  throw err;
}

export async function fetchSection(runId, start, end, context = 2) {
  const s = __DATA.samples.find((x) => x.name === runId);
  if (!s) throw new Error('Run not found in this snapshot.');
  const lo = Math.max(0, (start | 0) - (context | 0));
  const hi = Math.min(s.lines.length, (end | 0) + (context | 0));
  return s.lines.slice(lo, hi).join('\\n');
}

export async function searchText(runId, query) {
  const s = __DATA.samples.find((x) => x.name === runId);
  if (!s) throw new Error('Run not found in this snapshot.');
  const needle = String(query).toLowerCase();
  const hits = [];
  for (let i = 0; i < s.lines.length && hits.length < 200; i += 1) {
    if (s.lines[i].toLowerCase().includes(needle)) {
      const ctx = s.context[String(i)] || {};
      hits.push({
        line: i,
        text: s.lines[i].replace(/\\s+$/, '').slice(0, 220),
        case: ctx.case ?? null,
        step: ctx.step ?? null,
        page: ctx.page ?? null,
      });
    }
  }
  return { query, count: hits.length, hits, truncated: hits.length >= 200 };
}

function __downloadBlob(name, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
  return url;
}

/* Exports are normally URLs the browser navigates to. Offline they become
 * blobs built here, so the buttons still do what they say. */
export function exportJsonUrl(runId) {
  const s = __DATA.samples.find((x) => x.name === runId);
  if (!s) return '#';
  return __downloadBlob(
    `${runId.replace(/\\.out$/, '')}.parsed.json`,
    JSON.stringify(s.payload, null, 2),
    'application/json'
  );
}

export function exportCsvUrl(runId, step) {
  const s = __DATA.samples.find((x) => x.name === runId);
  if (!s) return '#';
  const p = s.payload;
  const sp = p.statePoints.find((x) => x.step === Number(step)) || p.statePoints[0];
  if (!sp) return '#';
  const codes = Object.keys(sp.values);
  const esc = (v) => {
    const t = v === null || v === undefined ? '' : String(v);
    return /[",\\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
  };
  const rows = [
    ['row', 'col', 'site', 'label', 'serial', 'fuelType', 'batch', 'enrichment', ...codes]
      .map(esc).join(','),
  ];
  p.assemblies.forEach((a, i) => {
    rows.push([
      a.row, a.col, a.site, a.label, a.serial, a.fuelType, a.batch, a.enrichment,
      ...codes.map((c) => sp.values[c][i]),
    ].map(esc).join(','));
  });
  return __downloadBlob(
    `${runId.replace(/\\.out$/, '')}.step${sp.step}.csv`,
    rows.join('\\n'),
    'text/csv'
  );
}
"""


def _split_names(raw: str) -> list[str]:
    """Parse an import/export brace list, honouring ``a as b`` aliases."""
    out = []
    for chunk in raw.split(","):
        chunk = " ".join(chunk.split())
        if not chunk:
            continue
        out.append(chunk)
    return out


def _to_module(name: str, source: str) -> str:
    """Rewrite one ES module into a registry definition."""
    exported: list[str] = _EXPORT_NAME_RE.findall(source)

    for m in _EXPORT_LIST_RE.finditer(source):
        for entry in _split_names(m.group("names")):
            exported.append(entry.split(" as ")[-1] if " as " in entry else entry)
    source = _EXPORT_LIST_RE.sub("", source)

    # `import { a, b as c } from './x.js'` -> destructure from the registry.
    def named(m: re.Match[str]) -> str:
        names = ", ".join(
            f"{n.split(' as ')[0]}: {n.split(' as ')[-1]}" if " as " in n else n
            for n in _split_names(m.group("names"))
        )
        return f"const {{ {names} }} = __req('{m.group('mod')}');"

    source = _NAMED_IMPORT_RE.sub(named, source)
    source = _NS_IMPORT_RE.sub(
        lambda m: f"const {m.group('ns')} = __req('{m.group('mod')}');", source
    )
    source = _DEFAULT_IMPORT_RE.sub(
        lambda m: f"const {m.group('name')} = __req('{m.group('mod')}').default;", source
    )
    source = _BARE_IMPORT_RE.sub("", source)
    source = _EXPORT_DECL_RE.sub(lambda m: m.group(1), source)

    leftover = re.search(r"^[ \t]*(import|export)\s", source, re.M)
    if leftover:
        line = source[leftover.start() : source.index("\n", leftover.start())]
        raise RuntimeError(f"{name}: unhandled module syntax -> {line.strip()!r}")

    publish = ""
    if exported:
        unique = sorted(set(exported))
        publish = "\n  Object.assign(exports, { " + ", ".join(unique) + " });\n"

    indented = "\n".join("  " + ln if ln.strip() else ln for ln in source.split("\n"))
    return (
        f"\n/* ===== {name} ===== */\n"
        f"__def('{name}', function (exports, __req) {{\n"
        f"{indented}\n{publish}}});\n"
    )


def _bundle_js() -> str:
    parts = [_LOADER, _to_module("api.js", _OFFLINE_API)]
    for name in MODULE_ORDER:
        parts.append(_to_module(name, (STATIC / "js" / name).read_text("utf-8")))
    # app.js self-starts on import, exactly as the module version does.
    parts.append("\n__req('app.js');\n")
    return "\n".join(parts)


def build(paths: list[Path], title: str | None = None) -> str:
    """Parse each listing and emit one self-contained HTML document."""
    samples = []
    for path in paths:
        result = parse_file(path)
        lines = result.document.lines
        # Only the lines a search hit can land on need page context, but the
        # map is small compared with the lines themselves, so keep it simple.
        context = {}
        for page in result.document.pages:
            if page.case is None:
                continue
            for i in range(page.start, page.end):
                context[str(i)] = {"case": page.case, "step": page.step, "page": page.page_no}
        samples.append(
            {
                "name": path.name,
                "sizeKb": round(path.stat().st_size / 1024),
                "payload": result.payload,
                "lines": lines,
                "context": context,
            }
        )

    html = (STATIC / "index.html").read_text("utf-8")
    css = (STATIC / "css" / "app.css").read_text("utf-8")
    js = _bundle_js()

    data = json.dumps({"samples": samples}, separators=(",", ":"))
    # </script> inside JSON would close the block early.
    data = data.replace("</", "<\\/")

    # Replacements are passed as callables: the payload and the bundled JS are
    # full of backslashes, which re.sub would otherwise read as escapes.
    style_block = f"<style>\n{css}\n</style>"
    script_block = (
        f"<script>window.__S3_BUNDLE__={data};</script>\n<script>\n{js}\n</script>"
    )

    html, n_css = re.subn(
        r'<link[^>]+href=["\'][^"\']*app\.css["\'][^>]*>',
        lambda _: style_block,
        html,
        count=1,
    )
    html, n_js = re.subn(
        r'<script[^>]*type=["\']module["\'][^>]*>\s*</script>',
        lambda _: script_block,
        html,
        count=1,
    )
    if not n_css or not n_js:
        raise RuntimeError(
            f"index.html did not match the expected shape (css={n_css}, js={n_js}); "
            "the bundler needs updating alongside it."
        )
    if title:
        html = re.sub(r"<title>[^<]*</title>", lambda _: f"<title>{title}</title>", html, count=1)
    return html


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m s3dash.bundle",
        description="Bundle the dashboard and one or more listings into a single HTML file.",
    )
    ap.add_argument("files", nargs="+", type=Path, help="SIMULATE-3 .out listings to embed")
    ap.add_argument("-o", "--output", type=Path, required=True, help="HTML file to write")
    ap.add_argument("--title", help="override the document title")
    args = ap.parse_args(argv)

    missing = [p for p in args.files if not p.is_file()]
    if missing:
        for p in missing:
            print(f"not found: {p}")
        return 1

    html = build(args.files, title=args.title)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding="utf-8")
    print(f"{args.output}  ({len(html) / 1024 / 1024:.1f} MB, {len(args.files)} listing(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
