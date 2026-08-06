"""Assemble parsed sections into the single JSON document the UI consumes.

Layout choice: assembly *identity* is static across a run, so it is emitted
once as an ordered array. Each state point then carries plain value arrays
aligned to that order. This keeps a 30-step, 241-assembly run to a few
hundred kilobytes and lets the front end recolour the map by swapping one
array instead of rebuilding objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import controlrods, inputcards, primitives, sections
from .document import Document, Section
from .geometry import Geometry, expand_to_full_core, parse_geometry

# Human-readable names and units for the edit codes seen in the wild. Unknown
# codes still render -- they just fall back to the raw code as their label.
_VARIABLE_INFO: dict[str, tuple[str, str]] = {
    "RPF": ("Relative Power Fraction", ""),
    "RPD": ("Relative Power Density", "kW/ft"),
    "EXP": ("Exposure", "GWd/MT"),
    "KIN": ("K-infinity", ""),
    "KINF": ("K-infinity", ""),
    "TFU": ("Fuel Temperature", "K"),
    "TMO": ("Moderator Temperature", "K"),
    "DEN": ("Moderator Density", "g/cc"),
    "VOI": ("Void Fraction", ""),
    "CRD": ("Control Rod Fraction", ""),
    "FLX": ("Neutron Flux", ""),
    "XEN": ("Xenon-135", "atom/b-cm"),
    "IOD": ("Iodine-135", "atom/b-cm"),
    "SAM": ("Samarium-149", "atom/b-cm"),
    "PRO": ("Promethium-149", "atom/b-cm"),
    "EBP": ("Burnable Poison Exposure", "GWd/MT"),
    "HIS": ("Spectral History", ""),
    "HBOR": ("Boron History", "ppm"),
    "HTMO": ("Moderator Density History", "g/cc"),
    "HTFU": ("Fuel Temperature History", "K"),
    "HVOI": ("Void History", ""),
    "HCRD": ("Control Rod History", ""),
    "SDC": ("Shutdown Cooling Interval", "days"),
    "PIN": ("Peak Pin Power", ""),
    "PLO": ("Peak Pin Location", ""),
    "XPO": ("Peak Pin Exposure", "GWd/MT"),
    "RR1": ("Detector Reaction Rate 1", ""),
    "RR2": ("Detector Reaction Rate 2", ""),
}

_PREFIX_INFO = {
    "2": "2D assembly",
    "3": "3D assembly",
    "Z": "Axial peaking",
    "Q": "2D nodal",
    "N": "3D nodal",
    "P": "3D peak in 2D",
    "S": "2D to summary",
    "X": "3D to summary",
}


def describe_variable(code: str) -> dict:
    """Split an edit code such as ``2EXP`` into prefix + variable metadata."""
    prefix, stem = (code[0], code[1:]) if len(code) > 1 and code[0] in _PREFIX_INFO else ("", code)
    name, unit = _VARIABLE_INFO.get(stem, _VARIABLE_INFO.get(stem[:3], (stem, "")))
    return {
        "code": code,
        "prefix": prefix,
        "basis": _PREFIX_INFO.get(prefix, ""),
        "name": name,
        "unit": unit,
    }


@dataclass
class Assembly:
    """Static identity of one core position."""

    row: int
    col: int
    site: str
    serial: str | None = None
    label: str | None = None
    fuel_type: int | None = None
    sub_type: str | None = None
    rotation: int | None = None
    batch: int | None = None
    enrichment: float | None = None
    bp_rods: int | None = None
    previous_location: str | None = None
    printed: bool = True  # False when only reachable via symmetry expansion

    def to_json(self) -> dict:
        return {
            "row": self.row,
            "col": self.col,
            "site": self.site,
            "serial": self.serial,
            "label": self.label,
            "fuelType": self.fuel_type,
            "subType": self.sub_type,
            "rotation": self.rotation,
            "batch": self.batch,
            "enrichment": self.enrichment,
            "bpRods": self.bp_rods,
            "previousLocation": self.previous_location,
            "printed": self.printed,
        }


@dataclass
class BuildResult:
    document: Document
    geometry: Geometry
    payload: dict
    warnings: list[str] = field(default_factory=list)


def build(doc: Document) -> BuildResult:
    """Parse every recognised section and assemble the UI payload."""
    geom = parse_geometry(doc.lines)
    notes: list[str] = []

    deck = _first(doc, "input", "Input Cards", inputcards.parse_input_deck, notes)
    deck = deck or inputcards.InputDeck()
    segments = _first(doc, "summary", "Fueled Segments", inputcards.parse_fueled_segments, notes) or []
    diagnostics = _first(doc, "diag", "Diagnostics", sections.parse_diagnostics, notes) or []
    symgroups = _collect(doc, "err.chk", "SYMGRP", sections.parse_symmetry_groups, notes)
    depletion = _first(doc, "depletion", "Depletion Table", sections.parse_depletion_table, notes) or []

    fmap = _merge_grid(doc, "FMAP", notes)
    cmap = _merge_grid(doc, "CMAP", notes)

    state_points, order, assemblies = _build_state_points(doc, geom, fmap, cmap, deck, segments, notes)

    timing = _timing(doc, notes)

    payload = {
        "meta": {**_meta(doc, deck, geom, state_points), "timing": timing},
        "geometry": geom.to_json(),
        "status": _status(diagnostics, symgroups),
        "assemblies": [a.to_json() for a in assemblies],
        "assemblyIndex": {f"{a.row},{a.col}": i for i, a in enumerate(assemblies)},
        "statePoints": state_points,
        "depletion": depletion,
        "diagnostics": [d.to_json() for d in diagnostics],
        "symmetryGroups": [g.to_json() for g in symgroups],
        "inventory": _inventory(assemblies, deck),
        "segments": [s.to_json() for s in segments],
        "inputDeck": deck.to_json(),
        "maps": {"fmap": fmap.to_json() if fmap else None, "cmap": cmap.to_json() if cmap else None},
        "navTree": _nav_tree(doc),
        "sections": _section_index(doc),
        "variableOrder": order,
        "parseNotes": notes,
    }
    return BuildResult(document=doc, geometry=geom, payload=payload, warnings=notes)


# --------------------------------------------------------------------- parts


def _first(doc: Document, kind: str, name: str, fn, notes: list[str]):
    """Parse the first occurrence of a section that actually yields content.

    Some builds echo a heading twice (listing and console streams), which
    leaves an empty stub section ahead of the real one. Trying each in turn
    makes the choice independent of which stream came first.
    """
    best = None
    for sec in doc.find(kind, name):
        try:
            got = fn(doc.lines, sec.start, sec.end)
        except Exception as exc:  # a bad section must not sink the whole file
            notes.append(f"{kind}:{name}@{sec.start} failed ({exc.__class__.__name__}: {exc})")
            continue
        if got:
            return got
        best = best if best is not None else got
    return best


def _collect(doc: Document, kind: str, name: str, fn, notes: list[str]) -> list:
    out: list = []
    for sec in doc.find(kind, name):
        try:
            out.extend(fn(doc.lines, sec.start, sec.end))
        except Exception as exc:
            notes.append(f"{kind}:{name}@{sec.start} failed ({exc.__class__.__name__}: {exc})")
    return out


def _merge_grid(doc: Document, name: str, notes: list[str]) -> primitives.BorderedGrid | None:
    grid: primitives.BorderedGrid | None = None
    for sec in doc.find("pri.inp", name):
        try:
            part = primitives.parse_bordered_grid(doc.lines, sec.start, sec.end)
        except Exception as exc:
            notes.append(f"pri.inp:{name}@{sec.start} failed ({exc.__class__.__name__}: {exc})")
            continue
        if part:
            grid = part if grid is None else grid.merge(part)
    return grid


def _build_state_points(
    doc: Document,
    geom: Geometry,
    fmap: primitives.BorderedGrid | None,
    cmap: primitives.BorderedGrid | None,
    deck: inputcards.InputDeck,
    segments: list[inputcards.SegmentSpec],
    notes: list[str],
) -> tuple[list[dict], list[str], list[Assembly]]:
    """Group map/summary sections by (case, step) and emit aligned arrays."""
    buckets: dict[tuple[int, int], dict[str, primitives.BandedMap]] = {}
    extras: dict[tuple[int, int], dict] = {}
    var_order: list[str] = []

    for sec in doc.sections:
        key = (sec.case if sec.case is not None else 0, sec.step if sec.step is not None else 0)
        if sec.kind in {"pri.sta", "pin.edt"}:
            try:
                bm = primitives.parse_banded_map(doc.lines, sec.start, sec.end)
            except Exception as exc:
                notes.append(f"{sec.key}@{sec.start} failed ({exc.__class__.__name__}: {exc})")
                continue
            if not bm:
                continue
            slot = buckets.setdefault(key, {})
            slot[sec.name] = slot[sec.name].merge(bm) if sec.name in slot else bm
            if sec.name not in var_order:
                var_order.append(sec.name)
        elif sec.kind == "summary" and sec.name == "Output Summary":
            kv = primitives.parse_key_values(doc.lines, sec.start, sec.end)
            extras.setdefault(key, {})["summary"] = kv.entries
        elif sec.kind == "axial":
            slot = extras.setdefault(key, {})
            tag = "axialState" if sec.name == "Axial State" else "axialDepletion"
            slot[tag] = sections.parse_axial_table(doc.lines, sec.start, sec.end)
        elif sec.kind == "bat.edt":
            extras.setdefault(key, {})["batchEdits"] = sections.parse_batch_edits(
                doc.lines, sec.start, sec.end
            )
        elif sec.kind == "crd":
            rods = controlrods.parse_control_rod_map(doc.lines, sec.start, sec.end)
            if rods:
                extras.setdefault(key, {})["controlRods"] = rods.to_json()

    assemblies = _resolve_assemblies(geom, buckets, fmap, cmap, deck, segments)
    index = {(a.row, a.col): i for i, a in enumerate(assemblies)}

    page_ctx = {}
    for p in doc.pages:
        if p.case is not None:
            page_ctx.setdefault((p.case, p.step), p)

    out: list[dict] = []
    for key in sorted(set(buckets) | set(extras)):
        case, step = key
        maps = buckets.get(key, {})
        values: dict[str, list] = {}
        for code, bm in maps.items():
            full = expand_to_full_core(bm.values, geom) if bm.numeric else bm.values
            raw_full = bm.raw if bm.numeric else _expand_raw(bm.raw, geom)
            arr: list = [None] * len(assemblies)
            for (r, c), idx in index.items():
                if bm.numeric:
                    arr[idx] = full.get((r, c))
                else:
                    arr[idx] = raw_full.get((r, c))
            values[code] = arr

        page = page_ctx.get(key)
        extra = extras.get(key, {})
        summary = extra.get("summary", {})
        out.append(
            {
                "case": case,
                "step": step,
                "exposure": page.exposure if page else None,
                "exposureUnit": page.exposure_unit if page else None,
                "boron": page.boron_ppm if page else None,
                "title": page.title if page else None,
                "keff": _pick(summary, "K-effective"),
                "coreExposure": _pick(summary, "Core Average Exposure"),
                "peakNodal": _pick(summary, "Peak Nodal Power"),
                "axialOffset": _pick(summary, "Axial Offset"),
                "values": values,
                "summary": summary,
                "axialState": extra.get("axialState"),
                "axialDepletion": extra.get("axialDepletion"),
                "batchEdits": extra.get("batchEdits"),
                "controlRods": extra.get("controlRods"),
            }
        )
    return out, var_order, assemblies


def _expand_raw(raw: dict[tuple[int, int], str], geom: Geometry) -> dict[tuple[int, int], str]:
    """Symmetry-expand a non-numeric map by reusing the numeric machinery."""
    keys = list(raw)
    numeric_stub = {k: float(i) for i, k in enumerate(keys)}
    expanded = expand_to_full_core(numeric_stub, geom)
    return {pos: raw[keys[int(v)]] for pos, v in expanded.items() if int(v) < len(keys)}


def _pick(summary: dict, label: str):
    entry = summary.get(label)
    return entry["value"] if entry else None


def _resolve_assemblies(
    geom: Geometry,
    buckets: dict,
    fmap: primitives.BorderedGrid | None,
    cmap: primitives.BorderedGrid | None,
    deck: inputcards.InputDeck,
    segments: list[inputcards.SegmentSpec],
) -> list[Assembly]:
    """Determine which positions hold fuel, and everything known about each.

    Occupancy comes from the state-point maps: SIMULATE-3 prints a value at
    exactly the fuelled positions, which is more reliable than inferring the
    core outline from input cards. Identity is layered on from FMAP when the
    run edited it.
    """
    occupied: set[tuple[int, int]] = set()
    for maps in buckets.values():
        for bm in maps.values():
            occupied |= set(expand_to_full_core(bm.values, geom) if bm.numeric else bm.raw)
            if not bm.numeric:
                occupied |= set(_expand_raw(bm.raw, geom))
    if not occupied and fmap:
        occupied = set(fmap.cells)

    printed: set[tuple[int, int]] = set()
    for maps in buckets.values():
        for bm in maps.values():
            printed |= set(bm.raw)

    seg_by_type = {s.number: s for s in segments}
    enr_by_type = {n: s.enrichment for n, s in seg_by_type.items()}
    bp_by_type = {n: s.bp_rods for n, s in seg_by_type.items()}
    cmap_info = _cmap_lookup(cmap, geom)

    out: list[Assembly] = []
    for (r, c) in sorted(occupied):
        a = Assembly(row=r, col=c, site=geom.site_label(r, c), printed=(r, c) in printed)
        if fmap:
            a.label = _grid_field(fmap, r, c, "FUE.LAB") or a.site
            a.serial = _grid_field(fmap, r, c, "FUE.SER")
            typrot = _grid_field(fmap, r, c, "TYP,ROT")
            if typrot:
                parts = typrot.split()
                if len(parts) == 2:
                    a.fuel_type, a.rotation = _int(parts[0]), _int(parts[1])
                elif len(parts) == 1:
                    a.rotation = _int(parts[0])
        if a.fuel_type is None:
            info = cmap_info.get((r, c))
            if info:
                a.fuel_type = info.get("type")
                a.batch = info.get("batch")
                if info.get("enrichment") is not None:
                    a.enrichment = info["enrichment"]
        if a.fuel_type is None and deck.fuel_type_grid:
            # The FUE.TYP matrix includes the reflector ring; offset by NREF.
            a.fuel_type = deck.fuel_type_grid.get((r + geom.nref, c + geom.nref))
        if a.fuel_type is not None:
            if a.enrichment is None:
                a.enrichment = enr_by_type.get(a.fuel_type)
            a.bp_rods = bp_by_type.get(a.fuel_type)
        if a.label is None:
            a.label = a.site
        out.append(a)
    return out


def _cmap_lookup(cmap: primitives.BorderedGrid | None, geom: Geometry) -> dict[tuple[int, int], dict]:
    """Map CMAP's calculated-core cells onto full-core coordinates.

    CMAP covers only the calculated fraction and indexes it locally from 1.
    The listing prints the corresponding full-core row beside each band
    (``row_aliases``), which is used when present; otherwise the offset is
    derived from the geometry. Values are then symmetry-expanded so every
    assembly gets a fuel type, not just the printed quadrant.

    Cell layout is ``(FUE.TYP FUE.BAT)``, enrichment, exposure.
    """
    if not cmap:
        return {}

    origin = 1 if geom.is_full_core else (geom.iafull + 1) // 2
    local: dict[tuple[int, int], dict] = {}
    for (lr, lc), fields in cmap.cells.items():
        alias = cmap.row_aliases.get(lr)
        row = int(alias) if alias and alias.isdigit() else lr + origin - 1
        col = lc + origin - 1
        entry: dict = {}
        if fields:
            parts = fields[0].split()
            if len(parts) >= 2:
                entry["type"], entry["batch"] = _int(parts[0]), _int(parts[1])
            elif len(parts) == 1:
                entry["type"] = _int(parts[0])
        if len(fields) > 1:
            entry["enrichment"] = _float(fields[1])
        if len(fields) > 2:
            entry["exposure"] = _float(fields[2])
        if entry:
            local[(row, col)] = entry

    if geom.is_full_core or not local:
        return local

    # Expand each scalar field independently, then recombine.
    out: dict[tuple[int, int], dict] = {k: dict(v) for k, v in local.items()}
    for key in ("type", "batch", "enrichment", "exposure"):
        subset = {pos: v[key] for pos, v in local.items() if v.get(key) is not None}
        if not subset:
            continue
        for pos, val in expand_to_full_core(subset, geom).items():
            slot = out.setdefault(pos, {})
            slot.setdefault(key, int(val) if key in ("type", "batch") else val)
    return out


def _float(text: str) -> float | None:
    from .textutil import as_float

    return as_float(text)


def _grid_field(grid: primitives.BorderedGrid, r: int, c: int, name: str) -> str | None:
    v = grid.field(r, c, name)
    return v or None


def _int(text: str) -> int | None:
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ metadata


def _meta(doc: Document, deck: inputcards.InputDeck, geom: Geometry, sps: list[dict]) -> dict:
    run = doc.run
    exposures = [s["exposure"] for s in sps if s.get("exposure") is not None]
    unit = next((s["exposureUnit"] for s in sps if s.get("exposureUnit")), None)
    return {
        "fileName": run.source_file,
        "code": run.code,
        "version": run.version,
        "runName": deck.run_name or run.run_name,
        "project": deck.project or run.project,
        "runDate": run.run_date,
        "runTime": run.run_time,
        "caseTitle": deck.case_title or run.title,
        "percentPower": run.percent_power,
        "percentFlow": run.percent_flow,
        "pageCount": run.page_count,
        "lineCount": len(doc.lines),
        "restartFile": deck.restart_file,
        "restartExposure": deck.restart_exposure,
        "stepCount": len(sps),
        "exposureUnit": unit,
        "cycleStart": min(exposures) if exposures else None,
        "cycleEnd": max(exposures) if exposures else None,
        "plant": _plant_guess(doc, deck),
    }


def _timing(doc: Document, notes: list[str]) -> dict:
    """Run timing and termination status from the closing CPU report.

    Scanned to end-of-file rather than to the section end, because the
    completion banner is printed after the timing table.
    """
    secs = doc.find("timing", "CPU Time")
    if not secs:
        return {}
    try:
        info = controlrods.parse_timing(doc.lines, secs[0].start, len(doc.lines))
        info["subroutines"] = controlrods.parse_subroutine_timing(
            doc.lines, secs[0].start, secs[0].end
        )
        return info
    except Exception as exc:
        notes.append(f"timing failed ({exc.__class__.__name__}: {exc})")
        return {}


def _plant_guess(doc: Document, deck: inputcards.InputDeck) -> str | None:
    """Best-effort plant name from the comment banner at the top of the deck.

    Decks conventionally open with a boxed ``'COM'`` banner naming the plant
    ("APR1400 MODEL", "BEAVRS"). The first line inside the box that is real
    text wins; rule lines and the letter-spaced "C Y C L E   2" line are
    skipped. Falls back to the project title.
    """
    for line in doc.lines[:80]:
        stripped = line.lstrip()
        if not stripped.startswith("'COM'") or "*" not in line:
            continue
        text = line.split("'COM'", 1)[1].strip().strip("*").strip()
        if len(text) < 4 or len(text) > 40:
            continue
        if set(text) <= set("-_= "):  # a rule line, not a name
            continue
        tokens = text.split()
        if len(tokens) >= 4 and all(len(t) == 1 for t in tokens[:4]):
            continue  # letter-spaced, e.g. "C Y C L E   2"
        if any(ch.isalpha() for ch in text):
            return " ".join(tokens)
    return deck.project


def _status(diags: list[sections.Diagnostic], groups: list[sections.SymmetryGroup]) -> dict:
    counts = {"ERROR": 0, "WARNING": 0, "CAUTION": 0, "NOTE": 0}
    for d in diags:
        counts[d.severity] = counts.get(d.severity, 0) + d.times
    return {
        "level": sections.overall_status(diags),
        "errors": counts["ERROR"],
        "warnings": counts["WARNING"],
        "cautions": counts["CAUTION"],
        "notes": counts["NOTE"],
        "symmetryViolations": len(groups),
        "distinctLabels": len(diags),
    }


def _inventory(assemblies: list[Assembly], deck: inputcards.InputDeck) -> list[dict]:
    """Assembly counts per fuel type, with batch labels where known."""
    by_type: dict[int | None, int] = {}
    for a in assemblies:
        by_type[a.fuel_type] = by_type.get(a.fuel_type, 0) + 1
    batch_of_type = {b.fuel_type: b for b in deck.batches}
    rows = []
    for ftype, count in sorted(by_type.items(), key=lambda kv: (kv[0] is None, kv[0])):
        batch = batch_of_type.get(ftype)
        rows.append(
            {
                "fuelType": ftype,
                "count": count,
                "batchLabel": batch.label if batch else None,
                "batchNumber": batch.batch_number if batch else None,
                "fresh": batch is not None,
            }
        )
    return rows


def _nav_tree(doc: Document) -> list[dict]:
    """Case -> step -> sections, for the navigation panel."""
    tree: dict[int, dict] = {}
    for sec in doc.sections:
        case = sec.case if sec.case is not None else 0
        step = sec.step if sec.step is not None else 0
        node = tree.setdefault(case, {"case": case, "steps": {}})
        snode = node["steps"].setdefault(step, {"step": step, "sections": []})
        snode["sections"].append(
            {
                "id": f"{sec.start}",
                "kind": sec.kind,
                "name": sec.name,
                "label": sec.label,
                "start": sec.start,
                "end": sec.end,
                "page": sec.page_no,
            }
        )
    return [
        {
            "case": c["case"],
            "steps": [c["steps"][s] for s in sorted(c["steps"])],
        }
        for c in (tree[k] for k in sorted(tree))
    ]


def _section_index(doc: Document) -> list[dict]:
    """Flat searchable index of every recognised section."""
    return [
        {
            "id": f"{s.start}",
            "kind": s.kind,
            "name": s.name,
            "label": s.label,
            "case": s.case,
            "step": s.step,
            "page": s.page_no,
            "start": s.start,
            "end": s.end,
            "lines": s.end - s.start,
            "variable": describe_variable(s.name) if s.kind in {"pri.sta", "pin.edt"} else None,
        }
        for s in doc.sections
    ]
