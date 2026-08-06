"""Self-consistency check for an arbitrary SIMULATE-3 listing.

Run this against a file the parser has never seen to find out whether it was
understood, without needing a known-good reference. Every check compares the
parser's output against a number the listing states about *itself*, so a
disagreement means one of the two is wrong and both are worth looking at.

    python -m s3dash.check path/to/run.out [more.out ...]

Exit status is 0 when every check passes, 1 otherwise, so it can gate a batch
conversion.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .parser import BuildResult, parse_file

_OK, _WARN, _FAIL = "PASS", "WARN", "FAIL"


class Check:
    def __init__(self, name: str, status: str, detail: str):
        self.name, self.status, self.detail = name, status, detail

    def line(self, colour: bool) -> str:
        mark = {"PASS": "  ok ", "WARN": " warn", "FAIL": "FAIL "}[self.status]
        if colour:
            code = {"PASS": "32", "WARN": "33", "FAIL": "31"}[self.status]
            mark = f"\033[{code}m{mark}\033[0m"
        return f" {mark}  {self.name:<38} {self.detail}"


def run_checks(result: BuildResult) -> list[Check]:
    payload = result.payload
    geom = payload["geometry"]
    meta = payload["meta"]
    checks: list[Check] = []

    def add(name, ok, detail, warn_only=False):
        status = _OK if ok else (_WARN if warn_only else _FAIL)
        checks.append(Check(name, status, detail))

    # --- structure -----------------------------------------------------
    n_sections = len(payload["sections"])
    add("Sections recognised", n_sections > 0, f"{n_sections} sections")
    add(
        "Code identified",
        bool(meta.get("version")),
        f"{meta.get('code')} {meta.get('version')}",
    )
    add(
        "Geometry resolved",
        bool(geom["iafull"]),
        f"{geom['reactorType']} {geom['iafull']}x{geom['iafull']} "
        f"{geom['fraction']}-core {geom['symmetry'].lower()}, "
        f"{'3D ' + str(geom['fuelNodes']) + ' nodes' if geom['is3d'] else '2D'}",
    )

    # --- the strongest check: the listing states its own assembly count --
    declared = geom.get("nAssemblies")
    found = len(payload["assemblies"])
    if declared:
        add(
            "Assembly count vs Input Summary",
            declared == found,
            f"{found} parsed vs {declared} declared",
        )
    else:
        add("Assembly count", found > 0, f"{found} parsed (no declared total to compare)", True)

    # --- inventory must total the core ----------------------------------
    inv_total = sum(r["count"] for r in payload["inventory"])
    add("Inventory totals the core", inv_total == found, f"{inv_total} vs {found}")

    # --- segment equivalent-assemblies ------------------------------------
    # Several fuel types can share one segment (burnable-poison variants of a
    # design), so counts are aggregated by segment before comparing. A per-type
    # comparison would falsely fail on any deck where that happens.
    counted_by_seg: dict[int, float] = {}
    for row in payload["inventory"]:
        seg = row.get("segment")
        if seg is not None:
            counted_by_seg[seg] = counted_by_seg.get(seg, 0) + row["count"]
    declared_by_seg = {
        s["number"]: s["equivalentAssemblies"]
        for s in payload["segments"]
        if s.get("equivalentAssemblies") is not None
    }
    unmapped = sum(r["count"] for r in payload["inventory"] if r.get("segment") is None)
    if declared_by_seg:
        declared_total = sum(declared_by_seg.values())
        add(
            "Segment totals equal the core",
            abs(declared_total - found) < 1.0,
            f"{declared_total:.0f} declared vs {found} assemblies",
        )
        if unmapped:
            # Per-segment equality is only decidable when every fuel type has
            # a stated segment; otherwise the shortfall is unattributed rather
            # than wrong, so this is reported and not failed.
            add(
                "Per-segment counts",
                True,
                f"not compared: {unmapped} assemblies have no stated segment",
                warn_only=True,
            )
        else:
            # "Equivalent assemblies" is height-weighted: an assembly whose
            # active segment spans 351 of 381 cm contributes 351/381 of an
            # assembly to that segment. Comparing raw counts would falsely
            # fail on any deck with axial blankets or cutbacks.
            expected = _equivalent_by_segment(payload)
            shared = set(expected) & set(declared_by_seg)
            bad = [s for s in shared if abs(expected[s] - declared_by_seg[s]) > 0.6]
            add(
                "Height-weighted counts vs Fueled Segments",
                not bad,
                f"{len(shared)} segment(s) match"
                if not bad
                else f"differ for segment(s) {sorted(bad)}",
            )

    # --- the listing states a per-type assembly count of its own -----------
    declared_types = [
        t for t in payload.get("assemblyTypes", []) if t["isFuel"] and t["countInCore"]
    ]
    if declared_types:
        stated = sum(t["countInCore"] for t in declared_types)
        add(
            "Type counts vs Assembly Descriptions",
            abs(stated - found) < 1.0,
            f"{stated:.0f} declared vs {found} in the map",
        )
        counted = {r["fuelType"]: r["count"] for r in payload["inventory"]}
        described = {t["fuelType"] for t in declared_types}
        undescribed = sorted(t for t in counted if t is not None and t not in described)
        if undescribed:
            # The core map references types the listing never describes --
            # typically rotational sub-type variants. Their assemblies are
            # counted correctly but cannot be attributed to a described type,
            # so a per-type comparison would be misleading rather than wrong.
            n = sum(counted[t] for t in undescribed)
            add(
                "Per-type counts vs Assembly Descriptions",
                True,
                f"not compared: types {undescribed} ({n} assemblies) are undescribed",
                warn_only=True,
            )
        else:
            bad = [
                t["fuelType"]
                for t in declared_types
                if t["fuelType"] in counted
                and abs(counted[t["fuelType"]] - t["countInCore"]) > 0.5
            ]
            add(
                "Per-type counts vs Assembly Descriptions",
                not bad,
                "all match" if not bad else f"differ for type(s) {sorted(bad)}",
            )

    # --- state points ----------------------------------------------------
    sps = payload["statePoints"]
    depl = payload["depletion"]
    add("State points found", bool(sps), f"{len(sps)} state points")
    if depl:
        add(
            "Depletion rows vs state points",
            len(depl) == len(sps),
            f"{len(depl)} rows vs {len(sps)} state points",
        )
        by_step = {d["step"]: d["keff"] for d in depl}
        mismatched = [
            sp["step"]
            for sp in sps
            if sp["keff"] is not None
            and sp["step"] in by_step
            and abs(sp["keff"] - by_step[sp["step"]]) > 1e-5
        ]
        add(
            "k-eff agrees across two sources",
            not mismatched,
            "Output Summary matches depletion table"
            if not mismatched
            else f"differs at step(s) {mismatched[:5]}",
        )
    else:
        add("Depletion table", False, "not found", True)

    # --- value arrays align ----------------------------------------------
    misaligned = [
        f"step {sp['step']}:{code}"
        for sp in sps
        for code, arr in sp["values"].items()
        if len(arr) != found
    ]
    add(
        "Value arrays align with assemblies",
        not misaligned,
        "all aligned" if not misaligned else f"{len(misaligned)} misaligned",
    )

    # --- map coverage -----------------------------------------------------
    if sps:
        first = sps[0]
        thin = [
            code
            for code, arr in first["values"].items()
            if sum(1 for v in arr if v is not None) < found
        ]
        add(
            "Maps cover every assembly",
            not thin,
            "full coverage" if not thin else f"partial: {thin}",
            warn_only=True,
        )

    # --- control rods self-check -------------------------------------------
    rods = sps[0].get("controlRods") if sps else None
    if rods and rods.get("totalWithdrawn") and rods.get("fullWithdrawalSteps"):
        implied = rods["totalWithdrawn"] / rods["fullWithdrawalSteps"]
        actual = len(rods["withdrawn"]) + len(rods["inserted"])
        add(
            "Rod positions vs listing total",
            abs(implied - actual) < 0.5,
            f"{actual} positions vs {implied:.0f} implied by total/steps",
        )

    # --- axial ---------------------------------------------------------
    if sps and geom["is3d"]:
        ax = sps[0].get("axialState") or {}
        nodes = ax.get("nodes") or []
        add(
            "Axial nodes vs geometry",
            len(nodes) == geom["fuelNodes"],
            f"{len(nodes)} rows vs {geom['fuelNodes']} fuel nodes",
        )

    # --- termination ----------------------------------------------------
    completion = (meta.get("timing") or {}).get("completion")
    if completion:
        add(
            "Run terminated normally",
            completion.lower().startswith("normal"),
            completion,
            warn_only=True,
        )

    # --- parse notes ------------------------------------------------------
    notes = payload["parseNotes"]
    add(
        "No sections failed to parse",
        not notes,
        "clean" if not notes else f"{len(notes)}: {notes[0][:60]}",
        warn_only=True,
    )
    return checks


def _equivalent_by_segment(payload: dict) -> dict[int, float]:
    """Height-weighted assembly count per segment.

    An assembly contributes ``height(segment) / total height`` of itself to
    each segment in its axial stack, which is how the listing computes the
    "Equivalent Assemblies" column.
    """
    counted = {r["fuelType"]: r["count"] for r in payload["inventory"]}
    out: dict[int, float] = {}
    for spec in payload.get("assemblyTypes", []):
        if not spec["isFuel"]:
            continue
        count = counted.get(spec["fuelType"])
        heights = {int(k): v for k, v in (spec.get("segmentHeights") or {}).items()}
        total = sum(heights.values())
        if not count or not total:
            continue
        for seg, height in heights.items():
            out[seg] = out.get(seg, 0.0) + count * height / total
    return out


def check_file(path: Path, colour: bool) -> tuple[int, int]:
    print(f"\n\033[1m{path.name}\033[0m" if colour else f"\n{path.name}")
    try:
        result = parse_file(path)
    except Exception as exc:
        print(f"  FAIL   could not parse: {exc.__class__.__name__}: {exc}")
        return 0, 1

    checks = run_checks(result)
    for c in checks:
        print(c.line(colour))
    failed = sum(1 for c in checks if c.status == _FAIL)
    warned = sum(1 for c in checks if c.status == _WARN)
    verdict = "OK" if not failed else f"{failed} FAILED"
    print(f"  -> {verdict}, {warned} warning(s), {len(checks)} checks")
    return len(checks), failed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m s3dash.check",
        description="Self-consistency check for SIMULATE-3 output listings.",
    )
    ap.add_argument("files", nargs="+", type=Path, help="one or more .out files")
    ap.add_argument("--no-colour", action="store_true", help="disable ANSI colour")
    args = ap.parse_args(argv)

    colour = not args.no_colour and sys.stdout.isatty()
    total_failed = 0
    paths: list[Path] = []
    for spec in args.files:
        paths.extend(sorted(spec.parent.glob(spec.name)) if "*" in spec.name else [spec])

    for path in paths:
        if not path.is_file():
            print(f"\n{path}: not found")
            total_failed += 1
            continue
        _, failed = check_file(path, colour)
        total_failed += failed

    print(f"\n{len(paths)} file(s) checked, {total_failed} failed check(s).")
    return 1 if total_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
