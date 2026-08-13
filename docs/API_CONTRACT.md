# Payload & API contract

The backend parses one SIMULATE-3 listing and returns a single JSON document.

Generate a real example to develop against — listings are not committed here,
so produce the payload from one of your own:

```bash
python -c "import json,sys; sys.path.insert(0,'.'); from s3dash.parser import parse_file; json.dump(parse_file('sample_data/your_run.out').payload, open('docs/sample_payload.json','w'), indent=1)"
```

The parser was developed against three listings that differ on **every axis
that matters**, and the UI is written to survive all of them:

| | APR1400 (×2) | BEAVRS |
|---|---|---|
| Core width | 17×17 | **15×15** |
| Fraction | quarter | **full** |
| Axial | 2D (1 node) | **3D (12 nodes)** |
| Exposure unit | `GWd/MT` | **`EFPD`** |
| Extra variables | — | **`2KIN`, `2RR1`** |
| `PRI.INP` maps | 4 | **none** |
| `BAT.EDT` | yes | **none** |
| `ERR.CHK` | SYMGRP | **none** |

If the UI hard-codes 17, assumes quarter-core, assumes a `FMAP` exists, or
assumes axial data exists, it breaks on one of them.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/parse` | multipart `file` upload → `{runId, ...payload}` |
| `GET`  | `/api/samples` | `{samples:[{name,sizeKb}]}` — bundled examples |
| `POST` | `/api/samples/{name}` | parse a bundled example → same shape as `/api/parse` |
| `GET`  | `/api/run/{runId}/section?start=&end=&context=` | raw listing text (`text/plain`) |
| `GET`  | `/api/run/{runId}/search?q=` | `{hits:[{line,text,case,step,page}], truncated}` |
| `GET`  | `/api/run/{runId}/export.json` | download full payload |
| `GET`  | `/api/run/{runId}/export.csv?step=N` | download assembly table for a step |
| `GET`  | `/api/run/{runId}/loading-pattern` | `{supported,entries,geometry,suggested}` or `{supported:false,reason}` |
| `POST` | `/api/run/{runId}/loading-pattern/apply` | replay a change list from the original pattern → `{entries,operations,problems,valid}` |
| `POST` | `/api/run/{runId}/loading-pattern/generate` | replay, validate, and generate the next-cycle `.inp` text → `{text,flaggedCards,filename}`; 422 if invalid |

Errors are `{"detail": "..."}` with 4xx/5xx.

## Payload shape

```jsonc
{
  "runId": "a1b2c3d4e5f6",

  "meta": {
    "fileName": "case_002495.out", "code": "SIMULATE-3", "version": "1.00.04",
    "runName": "RUN NAME", "project": "PROJECT NAME",
    "runDate": "2026/07/09", "runTime": "14.22.34.",
    "caseTitle": "PWR CYCLE 2 U02 CORE - TRANSITION TO EQ - FIRST FEED",
    "plant": "BEAVRS",              // may be null
    "percentPower": 100.0, "percentFlow": 100.0,
    "pageCount": 198, "lineCount": 11002,
    "restartFile": "s3.apr1400...res",  // may be null
    "restartExposure": 20000.0,         // may be null
    "stepCount": 31,
    "exposureUnit": "GWd/MT",       // or "EFPD" — NEVER hard-code
    "cycleStart": 0.0, "cycleEnd": 24.112,

    // Run cost + termination status. Show "completion" prominently: anything
    // other than "Normal Termination" means the results may be incomplete.
    "timing": {
      "cpuSeconds": 0.475, "elapsedSeconds": 1.0, "cpuUtilisation": 47.51,
      "containerWords": 876563,
      "startTime": "14:22:34", "startDate": "26/07/09",
      "endTime": "14:22:35", "endDate": "26/07/09",
      "completion": "Normal Termination",
      "subroutines": [ {"subroutine":"PINS","cpuSeconds":0.17,"percent":35.8,
                        "calls":31.0,"msPerCall":5.34} ]
    }
  },

  "geometry": {
    "reactorType": "PWR",           // or "BWR"
    "iafull": 17,                   // core width — 15 for BEAVRS. Drive the grid off this.
    "kd": 1,                        // axial nodes INCLUDING reflectors
    "fuelNodes": 1,                 // axial FUEL nodes — 12 for BEAVRS
    "is3d": false,                  // fuelNodes > 1
    "ihave": 2,                     // 1=octant 2=quarter 3=half 4=full
    "fraction": "quarter",
    "radialFraction": 0.25,
    "if2x2": 2, "nref": 1,
    "symmetry": "ROTATIONAL",       // or "MIRROR"
    "nAssemblies": 241,
    "isFullCore": false
  },

  "status": {
    "level": "WARNINGS",            // "OK" | "WARNINGS" | "ERRORS"
    "errors": 0, "warnings": 71, "cautions": 33, "notes": 40,
    "symmetryViolations": 8,
    "distinctLabels": 21
  },

  // Static identity, ONE entry per fuelled position. This array's ORDER is the
  // index space used by every statePoints[].values[] array.
  "assemblies": [
    { "row": 1, "col": 6, "site": "M-01", "serial": "H226", "label": "M-01",
      "fuelType": 5, "subType": null, "rotation": 0, "batch": 1,
      "enrichment": 3.76667, "bpRods": 16, "previousLocation": null,
      "printed": true }     // false = filled in by symmetry expansion, not printed
  ],
  "assemblyIndex": { "1,6": 0, "1,7": 1 },   // "row,col" -> index into assemblies

  "statePoints": [
    {
      "case": 1, "step": 0,
      "exposure": 0.0, "exposureUnit": "GWd/MT", "boron": 0.0,
      "title": "PWR CYCLE 2 ...",
      "keff": 1.14074, "coreExposure": 11.542,
      "peakNodal": 1.424, "axialOffset": 0.0,

      // code -> array ALIGNED TO assemblies[]. null = no value at that position.
      // Numeric codes give numbers; 2PLO gives strings like "17, 9".
      "values": { "2RPF": [0.396, ...], "2EXP": [...], "2PIN": [...], "2PLO": ["1, 3", ...] },

      // Every dot-leader entry from the Output Summary block.
      "summary": { "K-effective": {"value":1.14074,"code":null,"unit":null,"line":2628}, ... },

      // 2D files: nodes=[] and only summary.Ave. 3D files: one row per axial node,
      // ordered bottom (node 1) to top regardless of the listing's print order.
      // summary rows can be SPARSE: "P**2" carries only EXPO. Read by key.
      "axialState":     { "columns":["RPF","KINF","EXPO","CRD","DEN","TFU","TMO"],
                          "nodes":[{"node":1,"RPF":0.57392,...}],
                          "summary":{"Ave":{...},"A-O":{...},"P**2":{"EXPO":0.0}} },
      "axialDepletion": { ...same shape, depletion arguments. The listing splits
                          these across 2-3 page-width sub-tables; they are merged,
                          so `columns` here is ~18-20 long, not 9. ... },

      "batchEdits": { "NPIN": [{"batch":"3","name":"","assemblies":121,"value":1.61,
                                "label":"H-16","serial":"F-149","location":"(14, 3, 1)"}] },
                     // null when the run had no BAT.EDT (BEAVRS)

      // Control rod withdrawal map for this state point. Indexed by control-rod
      // DRIVE location, which is its own grid (geometry.irmx wide) — do NOT
      // assume it aligns with the assembly index space.
      // "withdrawn" and an inserted value of 0 are DIFFERENT states.
      "controlRods": {
        "inserted":  [ {"row":1,"col":3,"steps":60.0} ],
        "withdrawn": [ {"row":1,"col":1} ],
        "rows": [1,2], "cols": [1,2,3,4],
        "fullWithdrawalSteps": 100.0,
        "totalWithdrawn": 28900,
        "anyInserted": false,        // false = all rods out; render an "ARO" note
        "note": "CRD positions defined by CRD.ARO ..."
      }
    }
  ],

  // One row per state point, from the end-of-run summary table. Best source
  // for the depletion chart — richer than statePoints and already ordered.
  "depletion": [
    { "case":1,"step":0,"cycleExposure":0.0,"keff":1.14074,"nq":8,"boron":0.0,
      "axialPeak":1.0,"axialPeakNode":1,"axialOffset":0.0,
      "peakRadial":1.39,"peakNodal":1.42,"peak3pin":1.61,
      "density":0.725,"power":100.0,"flow":100.0,"crdPosition":0.0,
      "pressure":2250.0,"inletTemp":555.0,"coreExposure":11.542,"line":10888 }
  ],

  "diagnostics": [   // sorted most-severe first
    { "label":"SYMGRP F","times":1,"severity":"WARNING","where":"RES STEP",
      "info":"not quarter rotational","line":10812 }
  ],

  "symmetryGroups": [
    { "group":"A", "message":"Assembly Group A exposure (or FUE.TYP) fails ...",
      "members":[ { "tag":"A2","row":5,"col":9,"label":"M-06","fuelType":5,
                    "rotation":0,"aveExp":30.82,"quadrantExp":[30.736,30.839,30.839,30.865] } ],
      "expSpread": 0.0, "typeMismatch": false, "line":899 }
  ],

  // Per fuel type. `segment` is the segment the type actually maps to, which
  // is NOT always equal to fuelType — several types can share one segment, and
  // `segment` is null when the listing never states the mapping. Use
  // `enrichment` from here rather than looking it up by fuelType yourself.
  "inventory": [ {"fuelType":8,"typeName":"ASSEMBLYF1","segment":8,"segmentName":"F1",
                  "enrichment":5.56625,"count":56,"batchLabel":"TP01",
                  "batchNumber":3,"fresh":true} ],

  "segments":  [ {"number":8,"name":"F1","loading":2.63569,"enrichment":5.56625,
                  "plutonium":null,"bpLoading":8.0,"bpRods":12,"bpRodsOriginal":12,
                  "equivalentAssemblies":56.0} ],
                  // equivalentAssemblies is HEIGHT-WEIGHTED: an assembly whose
                  // fuel segment spans 351 of 381 cm counts as 351/381. Do not
                  // present it as an assembly count.

  // Physical description per fuel type, incl. the type -> segment mapping.
  "assemblyTypes": [ {"fuelType":8,"name":"ASSEMBLYF1","class":"Fuel","mechDesign":1,
                      "loadingGrams":433522.0,"axialZones":1,"countInCore":56.0,
                      "subTypes":[8,8],"segments":[8],"segmentHeights":{"8":381.0},
                      "activeSegment":8,"isFuel":true} ],

  "maps": { "fmap": {...} | null, "cmap": {...} | null },   // null when not edited

  "inputDeck": { "caseTitle":..., "project":..., "restartFile":...,
                 "batches":[{"label":"TP01","serialBase":"F-101","count":56,
                             "fuelType":8,"batchNumber":3,"line":57}],
                 "batchLabels":{"2":"CYC-2"},
                 "cards":[{"card":"DIM.PWR","args":"17/ ...","line":29}] },

  // Navigation tree: case -> step -> sections
  "navTree": [ { "case":1, "steps":[ { "step":0, "sections":[
      {"id":"2554","kind":"pri.sta","name":"2RPF",
       "label":"Assembly 2D RPF - Relative Power Fraction",
       "start":2554,"end":2567,"page":43} ]}]}],

  // Flat searchable index of every recognised section
  "sections": [ { "id":"2554","kind":"pri.sta","name":"2RPF","label":"...",
                  "case":1,"step":0,"page":43,"start":2554,"end":2567,"lines":13,
                  "variable":{"code":"2RPF","prefix":"2","basis":"2D assembly",
                              "name":"Relative Power Fraction","unit":""} } ],

  "variableOrder": ["2PIN","2PLO","2RPF","2EXP"],  // codes present, in first-seen order
  "parseNotes": []    // non-fatal parse problems — surface these in the UI
}
```

## Rules the UI must honour

1. **Never hard-code the core size.** Build the grid from `geometry.iafull`.
2. **Never assume a variable exists.** Build the view-layer selector from
   `variableOrder` + `sections[].variable`, not a fixed list. `2KIN` and `2RR1`
   appear only in BEAVRS; `2EXP` may be absent in other runs.
3. **Never assume axial data exists.** When `geometry.is3d` is false,
   `axialState.nodes` is `[]` — show "2D case (single axial node)", not an empty chart.
4. **Never assume `maps.fmap` / `batchEdits` exist.** BEAVRS has neither.
5. **`exposureUnit` varies** (`GWd/MT` vs `EFPD`). Always label axes from the payload.
6. **`values[code][i]` aligns to `assemblies[i]`.** `null` means no value there.
7. **`2PLO` values are strings**, not numbers — render as text, exclude from colour scales.
8. **Show `parseNotes`** if non-empty; the file loaded but something was skipped.
9. **`assemblies[i].printed === false`** means the value came from symmetry
   expansion of the calculated quadrant. Worth indicating subtly.
