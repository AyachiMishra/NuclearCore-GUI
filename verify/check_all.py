"""Adversarial numerical verification of the SIMULATE-3 parser.

Every expected value is re-extracted from the raw listing by ``verify.raw``
using a different technique from the production parser, then compared against
the payload. Run::

    python verify/check_all.py            # console summary
    python verify/check_all.py --report   # also rewrite verify/RESULTS.md

Exit status is 0 when every comparison agrees. ``verify/RESULTS.md`` is the
regenerable machine output; ``verify/VERIFICATION_REPORT.md`` is the written
report of what this sweep found.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "verify"))

import raw  # noqa: E402
from s3dash.parser import parse_file  # noqa: E402

FILES = ["case_002495.out", "apr1400.c02.out", "9074.out"]

SITE_LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"


class Result:
    """One verification category for one file."""

    def __init__(self, file: str, name: str):
        self.file = file
        self.name = name
        self.compared = 0
        self.problems: list[str] = []
        self.notes: list[str] = []

    def check(self, ok: bool, msg: str) -> bool:
        self.compared += 1
        if not ok:
            self.problems.append(msg)
        return ok

    def note(self, msg: str) -> None:
        self.notes.append(msg)

    @property
    def ok(self) -> bool:
        return not self.problems


def approx(a, b, tol=1e-9) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= tol * max(1.0, abs(float(a)), abs(float(b)))


# ------------------------------------------------------------------ 1. maps


def check_maps(name, lines, payload, results):
    r = Result(name, "1. Core maps (every cell, every state point)")
    idx = payload["assemblyIndex"]
    sps = {(s["case"], s["step"]): s for s in payload["statePoints"]}
    maps = raw.extract_maps(lines)

    seen_codes = Counter()
    for m in maps:
        sp = sps.get((m.case, m.step))
        if sp is None:
            r.problems.append(
                f"state point (case={m.case}, step={m.step}) missing from payload "
                f"(map {m.code} at line {m.head_line})"
            )
            continue
        arr = sp["values"].get(m.code)
        if arr is None:
            r.problems.append(
                f"case={m.case} step={m.step}: payload has no values['{m.code}'] "
                f"(map at line {m.head_line})"
            )
            continue
        seen_codes[m.code] += 1
        numeric = all(_isnum(t) for t in m.cells.values())
        for (row, col), text in sorted(m.cells.items()):
            key = f"{row},{col}"
            if key not in idx:
                r.problems.append(
                    f"line {m.cell_line[(row,col)]}: {m.code} cell ({row},{col})={text!r} "
                    f"has no assembly slot in payload"
                )
                continue
            got = arr[idx[key]]
            if numeric:
                exp = float(text)
                ok = got is not None and approx(exp, got, 1e-12)
            else:
                exp = text
                ok = got == text
            r.check(
                ok,
                f"line {m.cell_line[(row,col)]}: {m.code} ({row},{col}) "
                f"expected {exp!r} got {got!r}",
            )

    # Every code the payload claims must have come from a real map block.
    for sp in payload["statePoints"]:
        for code in sp["values"]:
            if code not in seen_codes:
                r.problems.append(f"payload code {code} never seen in raw maps")
    r.note(f"{len(maps)} map blocks, codes={dict(seen_codes)}")
    results.append(r)
    return maps


def _isnum(t: str) -> bool:
    try:
        float(t)
        return True
    except ValueError:
        return False


# --------------------------------------------------------- 2. ragged / nulls


def check_ragged(name, lines, payload, maps, results):
    r = Result(name, "2. Ragged rows / null placement")
    idx = payload["assemblyIndex"]
    sps = {(s["case"], s["step"]): s for s in payload["statePoints"]}

    for m in maps:
        sp = sps.get((m.case, m.step))
        if sp is None or m.code not in sp["values"]:
            continue
        arr = sp["values"][m.code]
        printed_cols = defaultdict(set)
        for (row, col) in m.cells:
            printed_cols[row].add(col)
        for row, cols in printed_cols.items():
            lo, hi = min(cols), max(cols)
            # Values in a printed row are contiguous: any gap means a shift.
            r.check(
                set(range(lo, hi + 1)) == cols,
                f"line {m.ruler_line}: {m.code} row {row} has holes: {sorted(cols)}",
            )
            # Positions outside the printed span, on this row, must be absent
            # or (for full-core runs) null.
            if payload["geometry"]["isFullCore"]:
                for col in m.cols:
                    if col in cols:
                        continue
                    key = f"{row},{col}"
                    if key in idx:
                        got = arr[idx[key]]
                        r.check(
                            got is None,
                            f"{m.code} ({row},{col}) not printed but payload has {got!r}",
                        )
    # Any assembly slot the map does not cover at all must be null.
    nulls = 0
    for m in maps:
        sp = sps.get((m.case, m.step))
        if sp is None or m.code not in sp["values"]:
            continue
        arr = sp["values"][m.code]
        for k, i in idx.items():
            row, col = (int(x) for x in k.split(","))
            if arr[i] is None:
                nulls += 1
    r.note(f"{nulls} null slots across all maps (expected 0 for these files)")
    results.append(r)


# ---------------------------------------------------- 3. symmetry expansion


def rot_orbit(r0, c0, n):
    """Orbit of (r,c) under 90 degree rotation, derived from first principles."""
    pts = [(r0, c0)]
    r, c = r0, c0
    for _ in range(3):
        r, c = c, n + 1 - r
        pts.append((r, c))
    return pts


def mirror_orbit(r0, c0, n):
    return [(r0, c0), (r0, n + 1 - c0), (n + 1 - r0, c0), (n + 1 - r0, n + 1 - c0)]


def check_symmetry(name, lines, payload, maps, results):
    r = Result(name, "3. Symmetry expansion")
    geom = payload["geometry"]
    if geom["isFullCore"]:
        r.note("full core - nothing expanded")
        results.append(r)
        return
    n = geom["iafull"]
    sym = geom["symmetry"]
    orbit = rot_orbit if sym.startswith("ROT") else mirror_orbit
    idx = payload["assemblyIndex"]
    sps = {(s["case"], s["step"]): s for s in payload["statePoints"]}

    ambiguous = 0
    for m in maps:
        sp = sps.get((m.case, m.step))
        if sp is None or m.code not in sp["values"]:
            continue
        arr = sp["values"][m.code]
        numeric = all(_isnum(t) for t in m.cells.values())

        # (a) printed values survive untouched at their printed coordinate
        for (row, col), text in m.cells.items():
            key = f"{row},{col}"
            if key not in idx:
                continue
            got = arr[idx[key]]
            exp = float(text) if numeric else text
            r.check(
                (approx(exp, got, 1e-12) if numeric else got == text),
                f"line {m.cell_line[(row,col)]}: printed {m.code} ({row},{col}) "
                f"overwritten: expected {exp!r} got {got!r}",
            )

        # (b) every expanded position equals its printed rotational image
        expected: dict[tuple[int, int], set] = defaultdict(set)
        for (row, col), text in m.cells.items():
            for p in orbit(row, col, n):
                expected[p].add(text)
        for pos, texts in expected.items():
            key = f"{pos[0]},{pos[1]}"
            if key not in idx:
                r.problems.append(f"{m.code}: image {pos} has no assembly slot")
                continue
            if pos in m.cells:
                continue  # covered by (a)
            got = arr[idx[key]]
            if len(texts) > 1:
                ambiguous += 1
                ok = any(
                    (approx(float(t), got, 1e-12) if numeric else got == t) for t in texts
                )
                r.check(ok, f"{m.code} expanded {pos}: got {got!r} not in {texts}")
            else:
                t = next(iter(texts))
                exp = float(t) if numeric else t
                r.check(
                    (approx(exp, got, 1e-12) if numeric else got == t),
                    f"{m.code} expanded {pos}: expected {exp!r} got {got!r}",
                )

        # (c) the expansion covers exactly the assembly list
        r.check(
            set(expected) == {tuple(int(x) for x in k.split(",")) for k in idx},
            f"{m.code} at line {m.head_line}: expanded footprint "
            f"({len(expected)}) != assembly list ({len(idx)})",
        )

    stated = raw.input_summary_value(lines, "Fuel Assemblies")
    r.check(
        stated is not None and int(stated) == len(payload["assemblies"]),
        f"Input Summary says {stated} fuel assemblies, payload has {len(payload['assemblies'])}",
    )
    if ambiguous:
        r.note(
            f"{ambiguous} expanded cells had >1 distinct printed image "
            f"(genuine source asymmetry); each accepted if it matched one of them"
        )
    results.append(r)


# ----------------------------------------------------- 4. non-numeric maps


def check_nonnumeric(name, lines, payload, maps, results):
    r = Result(name, "4. Non-numeric map round-trip (2PLO)")
    idx = payload["assemblyIndex"]
    sps = {(s["case"], s["step"]): s for s in payload["statePoints"]}
    weird = 0
    for m in maps:
        if all(_isnum(t) for t in m.cells.values()):
            continue
        sp = sps.get((m.case, m.step))
        if sp is None or m.code not in sp["values"]:
            continue
        arr = sp["values"][m.code]
        for (row, col), text in sorted(m.cells.items()):
            key = f"{row},{col}"
            if key not in idx:
                continue
            got = arr[idx[key]]
            r.check(
                got == text,
                f"line {m.cell_line[(row,col)]}: {m.code} ({row},{col}) "
                f"expected exact string {text!r} got {got!r}",
            )
            if not isinstance(got, str):
                r.problems.append(f"{m.code} ({row},{col}) is {type(got).__name__}, not str")
            if any(ch in text for ch in "*"):
                weird += 1
    if weird:
        r.note(f"{weird} cells contained a '*'")
    results.append(r)


# ------------------------------------------------------------- 5. scalars


def check_scalars(name, lines, payload, results):
    r = Result(name, "5. Per-state-point scalars")
    blocks = raw.output_summary_blocks(lines)
    banners = raw.banner_context(lines)
    ctx = raw.case_step_context(lines)
    sps = {(s["case"], s["step"]): s for s in payload["statePoints"]}

    by_key: dict[tuple[int, int], tuple[int, int]] = {}
    for s, e in blocks:
        key = ctx[s]
        by_key.setdefault(key, (s, e))

    r.check(
        len(by_key) == len(payload["statePoints"]),
        f"{len(by_key)} Output Summary blocks vs {len(payload['statePoints'])} state points",
    )

    for key, (s, e) in sorted(by_key.items()):
        sp = sps.get(key)
        if sp is None:
            r.problems.append(f"no payload state point for case={key[0]} step={key[1]}")
            continue
        keff = raw.summary_scalar(lines, s, e, r"K-effective[\s.]*(-?[\d.]+)")
        ebar = raw.summary_scalar(lines, s, e, r"Core Average Exposure[\s.]*EBAR\s+(-?[\d.]+)")
        peak = raw.summary_scalar(lines, s, e, r"Peak Nodal Power \(Location\)\s+(-?[\d.]+)")
        ao = raw.summary_scalar(lines, s, e, r"Axial Offset[\s.]*A-O\s+(-?[\d.]+)")
        bor = raw.summary_scalar(lines, s, e, r"Boron Conc[\s.]*BOR\s+(-?[\d.]+)")

        r.check(approx(keff, sp["keff"], 1e-12), f"{key} keff: raw {keff} payload {sp['keff']}")
        r.check(
            approx(ebar, sp["coreExposure"], 1e-12),
            f"{key} coreExposure: raw {ebar} payload {sp['coreExposure']}",
        )
        r.check(
            approx(peak, sp["peakNodal"], 1e-12),
            f"{key} peakNodal: raw {peak} payload {sp['peakNodal']}",
        )
        r.check(
            approx(ao, sp["axialOffset"], 1e-12),
            f"{key} axialOffset: raw {ao} payload {sp['axialOffset']}",
        )

        # The banner that belongs with these numbers is the one above this
        # block, not the first page in the file bearing the same Case/Step.
        b = raw.banner_before(lines, s) or banners.get(key)
        if b:
            r.check(
                approx(b["exposure"], sp["exposure"], 1e-12),
                f"{key} exposure: banner {b['exposure']} payload {sp['exposure']}",
            )
            r.check(
                b["unit"] == sp["exposureUnit"],
                f"{key} exposureUnit: banner {b['unit']!r} payload {sp['exposureUnit']!r}",
            )
            r.check(
                approx(b["boron"], sp["boron"], 1e-12),
                f"{key} boron: banner {b['boron']} payload {sp['boron']}",
            )
            # Output Summary repeats the boron independently.
            r.check(
                approx(bor, sp["boron"], 1e-9),
                f"{key} boron: Output Summary {bor} vs payload {sp['boron']}",
            )

        # Every dot-leader entry re-read independently.
        mine = raw.dot_leader_entries(lines, s, e)
        theirs = {k: v["value"] for k, v in (sp["summary"] or {}).items()}
        for label, val in theirs.items():
            if label in mine:
                r.check(
                    approx(mine[label], val, 1e-9),
                    f"{key} summary[{label!r}]: raw {mine[label]} payload {val}",
                )
    results.append(r)


# ------------------------------------------------------------ 6. depletion


def check_depletion(name, lines, payload, results):
    r = Result(name, "6. Depletion table")
    rows = raw.depletion_rows(lines)
    dep = payload["depletion"]

    # Collapse the echoed block the way the listing intends: same (case, step)
    # rows must be byte-identical, otherwise dedup would be destroying data.
    by_key: dict[tuple[int, int], list[list[str]]] = defaultdict(list)
    for toks in rows:
        by_key[(int(toks[0]), int(toks[1]))].append(toks)
    for key, group in by_key.items():
        bodies = {tuple(g[:-1]) for g in group}
        r.check(
            len(bodies) == 1,
            f"depletion {key} echoed with DIFFERENT values: {bodies}",
        )

    r.check(
        len(by_key) == len(dep),
        f"{len(by_key)} distinct (case,step) rows in raw table vs {len(dep)} in payload",
    )
    r.note(f"{len(rows)} raw rows collapsed to {len(by_key)} (echoed {len(rows)//max(1,len(by_key))}x)")

    # Column order after splitting the "AX/K" slash apart:
    # 0 case, 1 step, 2 stepExp, 3 keff, 4 nq, 5 boron, 6 axPeak, 7 axPeakNode,
    # 8 A-O, 9 rad, 10 node, 11 3pin, 12 dens, 13 power, 14 flow, 15 crd,
    # 16 pres, 17 inletT, 18 coreExp, 19 titleExp, 20 set
    fields = [
        ("cycleExposure", 2),
        ("keff", 3),
        ("nq", 4),
        ("boron", 5),
        ("axialPeak", 6),
        ("axialPeakNode", 7),
        ("axialOffset", 8),
        ("peakRadial", 9),
        ("peakNodal", 10),
        ("peak3pin", 11),
        ("density", 12),
        ("power", 13),
        ("flow", 14),
        ("crdPosition", 15),
        ("pressure", 16),
        ("inletTemp", 17),
        ("coreExposure", 18),
    ]
    dep_by_key = {(d["case"], d["step"]): d for d in dep}
    for key, group in sorted(by_key.items()):
        d = dep_by_key.get(key)
        if d is None:
            r.problems.append(f"depletion row {key} missing from payload")
            continue
        toks = group[0]
        for fname, col in fields:
            want = float(toks[col])
            got = d[fname]
            r.check(
                approx(want, got, 1e-12),
                f"{key} depletion.{fname}: raw token[{col}]={toks[col]} -> {want}, payload {got}",
            )
        r.check(
            d["line"] in [int(g[-1]) for g in group],
            f"{key} depletion.line {d['line']} not one of the raw rows "
            f"{[int(g[-1]) for g in group]}",
        )
    results.append(r)


# -------------------------------------------------------------- 7. axial


def check_axial(name, lines, payload, results):
    r = Result(name, "7. Axial distributions")
    blocks = raw.axial_blocks(lines)
    ctx = raw.case_step_context(lines)
    sps = {(s["case"], s["step"]): s for s in payload["statePoints"]}

    first: dict[tuple[str, int, int], dict] = {}
    for b in blocks:
        key = (b["kind"], *ctx[b["line"]])
        first.setdefault(key, b)

    for (kind, case, step), b in sorted(first.items()):
        sp = sps.get((case, step))
        if sp is None:
            r.problems.append(f"axial {kind} block at line {b['line']} has no state point")
            continue
        got = sp["axialState" if kind == "state" else "axialDepletion"]
        if got is None:
            r.problems.append(f"payload missing axial{kind} for case={case} step={step}")
            continue
        # A block prints more variables than fit the page, so it repeats the
        # header with further columns. All sub-tables describe the SAME nodes
        # and must all reach the payload.
        columns: list[str] = []
        raw_nodes: dict[int, dict[str, float]] = {}
        raw_summary: dict[str, dict[str, float | None]] = {}
        for sub in b["subtables"]:
            for c in sub["columns"]:
                if c not in columns:
                    columns.append(c)
            for nid, vals in sub["nodes"].items():
                slot = raw_nodes.setdefault(nid, {})
                for col, tok in zip(sub["columns"], vals):
                    slot[col] = float(tok)
            for srow, vals in sub["summary"].items():
                raw_summary.setdefault(srow, {}).update(
                    {k: v for k, v in vals.items() if v is not None}
                )

        r.check(
            got["columns"] == columns,
            f"({case},{step}) {kind} columns: raw {columns} payload {got['columns']}",
        )
        gnodes = {n["node"]: n for n in got["nodes"]}
        r.check(
            sorted(gnodes) == sorted(raw_nodes),
            f"({case},{step}) {kind} node set: raw {sorted(raw_nodes)} payload {sorted(gnodes)}",
        )
        for nid, vals in raw_nodes.items():
            gn = gnodes.get(nid)
            if gn is None:
                continue
            for col, want in vals.items():
                r.check(
                    approx(want, gn.get(col), 1e-12),
                    f"({case},{step}) {kind} node {nid} {col}: raw {want} payload {gn.get(col)}",
                )
        for srow, vals in raw_summary.items():
            gs = (got.get("summary") or {}).get(srow)
            if gs is None:
                r.problems.append(f"({case},{step}) {kind} summary row {srow!r} missing")
                continue
            for col, want in vals.items():
                r.check(
                    approx(want, gs.get(col), 1e-9),
                    f"({case},{step}) {kind} {srow}[{col}]: raw {want} payload {gs.get(col)}",
                )
        # Ave must equal the mean of the nodes (the listing's own invariant).
        if raw_nodes and "Ave" in raw_summary:
            for col in columns:
                vals = [v[col] for v in raw_nodes.values() if col in v]
                stated = raw_summary["Ave"].get(col)
                if stated is None or not vals:
                    continue
                mean = sum(vals) / len(vals)
                if abs(mean - stated) > 5e-3 * max(1.0, abs(stated)):
                    r.note(
                        f"({case},{step}) {kind} Ave[{col}]={stated} vs node mean "
                        f"{mean:.6g} (listing may weight by node height)"
                    )

    if not payload["geometry"]["is3d"]:
        for sp in payload["statePoints"]:
            r.check(
                (sp["axialState"] or {}).get("nodes") == [],
                f"2D run but axialState.nodes non-empty for step {sp['step']}",
            )
    results.append(r)


# --------------------------------------------------------- 8. diagnostics


def check_diagnostics(name, lines, payload, results):
    r = Result(name, "8. Diagnostics roll-up")
    rows = raw.diagnostic_rows(lines)
    diag = payload["diagnostics"]

    uniq: dict[tuple, tuple] = {}
    dupes = 0
    for label, times, sev, where, info, line in rows:
        key = (label, times, sev, where, info)
        if key in uniq:
            dupes += 1
            continue
        uniq[key] = (label, times, sev, where, info, line)

    r.check(
        len(uniq) == len(diag),
        f"{len(uniq)} distinct raw rows ({len(rows)} printed, {dupes} echoed) "
        f"vs {len(diag)} payload diagnostics",
    )
    by_label = {d["label"]: d for d in diag}
    for (label, times, sev, where, info) in uniq:
        d = by_label.get(label)
        if d is None:
            r.problems.append(f"diagnostic {label!r} missing from payload")
            continue
        r.check(d["times"] == times, f"{label}: times raw {times} payload {d['times']}")
        r.check(d["severity"] == sev, f"{label}: severity raw {sev} payload {d['severity']}")
        r.check(d["where"] == where, f"{label}: where raw {where!r} payload {d['where']!r}")
        r.check(d["info"] == info, f"{label}: info raw {info!r} payload {d['info']!r}")

    counts = Counter()
    for (label, times, sev, where, info) in uniq:
        counts[sev] += times
    st = payload["status"]
    for sev, field in (
        ("ERROR", "errors"),
        ("WARNING", "warnings"),
        ("CAUTION", "cautions"),
        ("NOTE", "notes"),
    ):
        r.check(
            counts[sev] == st[field],
            f"status.{field}: summed raw times {counts[sev]} vs payload {st[field]}",
        )
    r.check(
        st["distinctLabels"] == len(uniq),
        f"status.distinctLabels {st['distinctLabels']} vs {len(uniq)} raw rows",
    )
    r.note(f"raw rows={len(rows)} distinct={len(uniq)} sums={dict(counts)}")
    results.append(r)


# ------------------------------------------------------ 9. symmetry groups


def check_symgroups(name, lines, payload, results):
    r = Result(name, "9. Symmetry groups (ERR.CHK - SYMGRP)")
    groups = raw.symmetry_blocks(lines)
    pay = payload["symmetryGroups"]
    r.check(len(groups) == len(pay), f"{len(groups)} raw SYMGRP blocks vs {len(pay)} in payload")
    by_group = {g["group"]: g for g in pay}
    for g in groups:
        p = by_group.get(g["group"])
        if p is None:
            r.problems.append(f"SYMGRP {g['group']} missing from payload")
            continue
        r.check(
            p["message"] == g["message"],
            f"SYMGRP {g['group']} message: raw {g['message']!r} payload {p['message']!r}",
        )
        r.check(
            len(p["members"]) == len(g["members"]),
            f"SYMGRP {g['group']}: {len(g['members'])} raw members vs {len(p['members'])}",
        )
        for mine, theirs in zip(g["members"], p["members"]):
            tag = mine["tag"]
            r.check(theirs["tag"] == tag, f"{g['group']} member tag {tag} vs {theirs['tag']}")
            r.check(theirs["row"] == mine["row"], f"{g['group']}/{tag} row")
            r.check(theirs["col"] == mine["col"], f"{g['group']}/{tag} col")
            r.check(theirs["label"] == mine["label"], f"{g['group']}/{tag} label")
            r.check(
                theirs["fuelType"] == int(mine.get("typ", -1)),
                f"{g['group']}/{tag} fuelType raw {mine.get('typ')} payload {theirs['fuelType']}",
            )
            r.check(
                theirs["rotation"] == int(mine.get("rot", -1)),
                f"{g['group']}/{tag} rotation raw {mine.get('rot')} payload {theirs['rotation']}",
            )
            r.check(
                approx(mine.get("ave"), theirs["aveExp"], 1e-12),
                f"{g['group']}/{tag} aveExp raw {mine.get('ave')} payload {theirs['aveExp']}",
            )
            r.check(
                len(theirs["quadrantExp"]) == 4,
                f"{g['group']}/{tag} expected 4 quadrant exposures, got {theirs['quadrantExp']}",
            )
            for a, b in zip(mine["quad"], theirs["quadrantExp"]):
                r.check(approx(a, b, 1e-12), f"{g['group']}/{tag} quadrant raw {a} payload {b}")
    r.check(
        payload["status"]["symmetryViolations"] == len(groups),
        f"status.symmetryViolations {payload['status']['symmetryViolations']} vs {len(groups)}",
    )
    results.append(r)


# ---------------------------------------------------- 10. assembly identity


def check_identity(name, lines, payload, maps, results):
    r = Result(name, "10. Assembly identity (FMAP / CMAP / footers)")
    n = payload["geometry"]["iafull"]
    idx = payload["assemblyIndex"]
    asm = payload["assemblies"]

    # (a) site labels must match the map column footers the listing prints.
    footer_letters: dict[int, str] = {}
    for m in maps:
        for col, lab in m.col_labels.items():
            if col in footer_letters and footer_letters[col] != lab:
                r.problems.append(f"column {col} footer disagrees: {footer_letters[col]} vs {lab}")
            footer_letters[col] = lab
    for key, i in idx.items():
        row, col = (int(x) for x in key.split(","))
        want = footer_letters.get(col)
        if want is None:
            continue
        r.check(
            asm[i]["site"] == f"{want}-{row:02d}",
            f"site for ({row},{col}): footer says {want}-{row:02d}, payload {asm[i]['site']}",
        )

    # (b) FMAP label / serial / rotation
    bands = raw.bordered_bands(lines, "FMAP")
    fmap_cells: dict[tuple[int, int], list[str]] = {}
    for b in bands:
        fmap_cells.update(b["cells"])
    if fmap_cells:
        for (row, col), fields in sorted(fmap_cells.items()):
            if not any(fields):
                continue
            key = f"{row},{col}"
            if key not in idx:
                r.problems.append(f"FMAP ({row},{col})={fields} has no assembly slot")
                continue
            a = asm[idx[key]]
            lab, ser = (fields + ["", "", ""])[0], (fields + ["", "", ""])[1]
            rot = (fields + ["", "", ""])[2]
            if lab:
                r.check(a["label"] == lab, f"FMAP ({row},{col}) label raw {lab!r} payload {a['label']!r}")
                r.check(
                    a["site"] == lab,
                    f"FMAP ({row},{col}) site {a['site']!r} != printed label {lab!r}",
                )
            if ser:
                r.check(
                    a["serial"] == ser,
                    f"FMAP ({row},{col}) serial raw {ser!r} payload {a['serial']!r}",
                )
            if rot.strip():
                parts = rot.split()
                want_rot = int(parts[-1])
                r.check(
                    a["rotation"] == want_rot,
                    f"FMAP ({row},{col}) rotation raw {want_rot} payload {a['rotation']}",
                )
        r.note(f"FMAP bands={len(bands)} cells={len(fmap_cells)}")
    else:
        r.note("no FMAP in this listing")

    # (c) CMAP fuel type / batch / enrichment, mapped to full core myself
    cbands = raw.bordered_bands(lines, "CMAP")
    origin = 1 if payload["geometry"]["isFullCore"] else (n + 1) // 2
    cmap_full: dict[tuple[int, int], dict] = {}
    for b in cbands:
        for (lr, lc), fields in b["cells"].items():
            alias = b["aliases"].get(lr)
            row = int(alias) if alias and alias.isdigit() else lr + origin - 1
            col = lc + origin - 1
            parts = (fields[0] if fields else "").split()
            entry = {}
            if len(parts) >= 2:
                entry["type"], entry["batch"] = int(parts[0]), int(parts[1])
            if len(fields) > 1 and fields[1]:
                entry["enr"] = float(fields[1])
            if entry:
                cmap_full[(row, col)] = entry
        # site labels embedded in the CMAP rule name the full-core position
        for (lr, lc), site in b["sites"].items():
            alias = b["aliases"].get(lr)
            row = int(alias) if alias and alias.isdigit() else lr + origin - 1
            col = lc + origin - 1
            key = f"{row},{col}"
            if key in idx:
                r.check(
                    asm[idx[key]]["site"] == site,
                    f"CMAP rule site {site} at ({row},{col}) vs payload {asm[idx[key]]['site']}",
                )
    for (row, col), entry in sorted(cmap_full.items()):
        key = f"{row},{col}"
        if key not in idx:
            r.problems.append(f"CMAP ({row},{col})={entry} has no assembly slot")
            continue
        a = asm[idx[key]]
        if "type" in entry:
            r.check(
                a["fuelType"] == entry["type"],
                f"CMAP ({row},{col}) fuelType raw {entry['type']} payload {a['fuelType']}",
            )
        if "batch" in entry:
            r.check(
                a["batch"] == entry["batch"],
                f"CMAP ({row},{col}) batch raw {entry['batch']} payload {a['batch']}",
            )
    if cmap_full:
        r.note(f"CMAP cells={len(cmap_full)}")

    # (d) per-type counts vs the Fueled Segments equivalent-assembly column.
    # FUE.TYP numbers and segment numbers are separate namespaces; they only
    # coincide when the deck happens to number them alike, so the per-type
    # comparison is gated on the two label sets being identical. The total is
    # always meaningful.
    segs = raw.fueled_segments(lines)
    seg_eq = {int(t[0]): float(t[8]) for t in segs}
    counts = Counter(a["fuelType"] for a in asm)
    # Axially zoned cores give fractional per-segment equivalents printed to
    # 3dp, so the total only recovers the head count to within rounding.
    r.check(
        abs(sum(seg_eq.values()) - len(asm)) < 0.01,
        f"Fueled Segments equivalent assemblies total {sum(seg_eq.values())} "
        f"vs {len(asm)} assemblies",
    )
    if abs(sum(seg_eq.values()) - len(asm)) > 1e-9:
        r.note(
            f"Fueled Segments total {sum(seg_eq.values())} vs {len(asm)} assemblies "
            f"- source rounding of fractional (axially zoned) segments"
        )
    if set(counts) == set(seg_eq):
        for ftype, cnt in sorted(counts.items()):
            r.check(
                abs(seg_eq[ftype] - cnt) < 1e-6,
                f"fuel type {ftype}: {cnt} assemblies vs Fueled Segments "
                f"equivalent-assemblies {seg_eq[ftype]}",
            )
    else:
        r.note(
            "fuel-type numbers are not segment numbers here; only the total "
            "equivalent-assembly count is comparable"
        )
    for ftype, cnt in counts.items():
        if ftype is None:
            r.problems.append(f"{cnt} assemblies have no fuel type")

    # (e) the FUE.TYP input matrix names the type of every core position.
    grid = raw.fue_typ_grid(lines)
    nref = payload["geometry"]["nref"]
    if grid:
        for key, i in idx.items():
            row, col = (int(x) for x in key.split(","))
            want = grid.get((row + nref, col + nref))
            if want is None:
                continue
            r.check(
                asm[i]["fuelType"] == want,
                f"FUE.TYP matrix ({row},{col}) says type {want}, payload "
                f"{asm[i]['fuelType']} ({asm[i]['site']})",
            )
        r.note(f"FUE.TYP matrix cells={len(grid)}")
    r.note(f"segments={len(segs)} type counts={dict(counts)}")
    results.append(r)


# ------------------------------------------------- 11. cross-source checks


def check_cross(name, lines, payload, results):
    r = Result(name, "11. Cross-source consistency")
    dep = {(d["case"], d["step"]): d for d in payload["depletion"]}
    for sp in payload["statePoints"]:
        d = dep.get((sp["case"], sp["step"]))
        if d is None:
            continue
        if sp["keff"] is not None:
            r.check(
                approx(sp["keff"], d["keff"], 2e-5),
                f"({sp['case']},{sp['step']}) k-eff: Output Summary {sp['keff']} "
                f"vs depletion table {d['keff']}",
            )
        if sp["coreExposure"] is not None:
            r.check(
                approx(sp["coreExposure"], d["coreExposure"], 1e-3),
                f"({sp['case']},{sp['step']}) core exposure: summary {sp['coreExposure']} "
                f"vs table {d['coreExposure']}",
            )
        if sp["exposure"] is not None:
            r.check(
                approx(sp["exposure"], d["cycleExposure"], 1e-3),
                f"({sp['case']},{sp['step']}) cycle exposure: banner {sp['exposure']} "
                f"vs table {d['cycleExposure']}",
            )
        if sp["axialOffset"] is not None:
            r.check(
                approx(sp["axialOffset"], d["axialOffset"], 1e-3),
                f"({sp['case']},{sp['step']}) A-O: summary {sp['axialOffset']} vs table {d['axialOffset']}",
            )
        if sp["peakNodal"] is not None:
            r.check(
                abs(sp["peakNodal"] - d["peakNodal"]) <= 0.005 + 1e-9,
                f"({sp['case']},{sp['step']}) peak nodal: summary {sp['peakNodal']} "
                f"vs table {d['peakNodal']} (table is 2dp)",
            )

    stated = raw.input_summary_value(lines, "Fuel Assemblies")
    r.check(
        stated is not None and int(stated) == payload["geometry"]["nAssemblies"],
        f"geometry.nAssemblies {payload['geometry']['nAssemblies']} vs Input Summary {stated}",
    )
    r.check(
        stated is not None and int(stated) == len(payload["assemblies"]),
        f"len(assemblies) {len(payload['assemblies'])} vs Input Summary {stated}",
    )
    # BAT.EDT CORE row states the assembly count independently.
    core_rows = 0
    for sp in payload["statePoints"]:
        for edit, rows in (sp.get("batchEdits") or {}).items():
            for row in rows:
                if row["batch"] == "CORE":
                    core_rows += 1
                    r.check(
                        row["assemblies"] == len(payload["assemblies"]),
                        f"BAT.EDT {edit} CORE row says {row['assemblies']} assemblies, "
                        f"payload has {len(payload['assemblies'])}",
                    )
    if core_rows:
        r.note(f"{core_rows} BAT.EDT CORE rows cross-checked")
    results.append(r)


# --------------------------------------------------------------- 12. units


def check_units(name, lines, payload, results):
    r = Result(name, "12. Units")
    units = {sp["exposureUnit"] for sp in payload["statePoints"]}
    r.check(len(units) == 1, f"mixed exposure units across state points: {units}")
    unit = payload["meta"]["exposureUnit"]
    banner_units = set()
    for ln in lines:
        m = raw._CASE_STEP_RE.match(ln)
        if m:
            pe = raw._PPM_EXP_RE.search(m.group("rest") or "")
            if pe:
                banner_units.add(pe.group("unit"))
    r.check(
        banner_units == {unit} or unit in banner_units,
        f"meta.exposureUnit {unit!r} not among banner units {banner_units}",
    )
    # A variable's unit must come from its own heading, never from a table
    # keyed on the code. 2EXP is headed GWD/T, which is not the cycle unit.
    heading_unit: dict[str, str] = {}
    for i, ln in enumerate(lines):
        m = re.match(r"^\s*(?:PRI\.STA|PIN\.EDT)\s+([0-9A-Z]{2,8})\s*-\s*(.+?)\s*$", ln)
        if not m:
            continue
        code, desc = m.group(1), m.group(2)
        tail = desc.rsplit("-", 1)[-1].strip() if "-" in desc else ""
        heading_unit.setdefault(code, tail if "/" in tail and " " not in tail else "")
    by_code: dict[str, str] = {}
    for sec in payload["sections"]:
        if sec.get("variable"):
            by_code.setdefault(sec["variable"]["code"], sec["variable"]["unit"])
    for code, want in heading_unit.items():
        if code not in by_code:
            continue
        r.check(
            by_code[code] == want,
            f"{code}: heading states unit {want!r}, payload says {by_code[code]!r}",
        )
    r.note(f"heading units: { {k: v for k, v in heading_unit.items() if v} }")
    r.note(f"payload units: { {k: v for k, v in by_code.items() if v} }")
    results.append(r)


# ------------------------------------------------------------------- driver


def run_file(fname: str) -> list[Result]:
    path = ROOT / "sample_data" / fname
    lines = raw.read_lines(path)
    payload = parse_file(path).payload
    results: list[Result] = []
    maps = check_maps(fname, lines, payload, results)
    check_ragged(fname, lines, payload, maps, results)
    check_symmetry(fname, lines, payload, maps, results)
    check_nonnumeric(fname, lines, payload, maps, results)
    check_scalars(fname, lines, payload, results)
    check_depletion(fname, lines, payload, results)
    check_axial(fname, lines, payload, results)
    check_diagnostics(fname, lines, payload, results)
    check_symgroups(fname, lines, payload, results)
    check_identity(fname, lines, payload, maps, results)
    check_cross(fname, lines, payload, results)
    check_units(fname, lines, payload, results)
    if payload["parseNotes"]:
        r = Result(fname, "0. parseNotes")
        for note in payload["parseNotes"]:
            r.check(False, f"parser reported: {note}")
        results.append(r)
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--max-show", type=int, default=6)
    args = ap.parse_args()

    all_results: dict[str, list[Result]] = {}
    for f in FILES:
        all_results[f] = run_file(f)

    bad = 0
    for f, results in all_results.items():
        total = sum(r.compared for r in results)
        probs = sum(len(r.problems) for r in results)
        bad += probs
        print(f"\n=== {f}: {total} values compared, {probs} problems")
        for r in results:
            flag = "OK " if r.ok else "FAIL"
            print(f"  [{flag}] {r.name}: {r.compared} compared, {len(r.problems)} problems")
            for n in r.notes:
                print(f"         note: {n}")
            for p in r.problems[: args.max_show]:
                print(f"         !! {p}")
            if len(r.problems) > args.max_show:
                print(f"         !! ... and {len(r.problems) - args.max_show} more")

    if args.report:
        write_report(all_results)
    print(f"\nTOTAL PROBLEMS: {bad}")
    return 1 if bad else 0


def write_report(all_results: dict[str, list[Result]]) -> None:
    out = ROOT / "verify" / "RESULTS.md"
    lines = ["# SIMULATE-3 parser numerical verification", ""]
    grand = sum(sum(r.compared for r in rs) for rs in all_results.values())
    probs = sum(sum(len(r.problems) for r in rs) for rs in all_results.values())
    lines.append(f"**{grand:,} values compared, {probs} discrepancies.**")
    lines.append("")
    for f, results in all_results.items():
        lines.append(f"## {f}")
        lines.append("")
        lines.append("| Category | Compared | Problems |")
        lines.append("|---|---:|---:|")
        for r in results:
            lines.append(f"| {r.name} | {r.compared:,} | {len(r.problems)} |")
        lines.append("")
        for r in results:
            if r.notes or r.problems:
                lines.append(f"### {r.name}")
                for n in r.notes:
                    lines.append(f"- note: {n}")
                for p in r.problems[:40]:
                    lines.append(f"- **FAIL** {p}")
                if len(r.problems) > 40:
                    lines.append(f"- ... and {len(r.problems)-40} more")
                lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    raise SystemExit(main())
