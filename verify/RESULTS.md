# SIMULATE-3 parser numerical verification

**147,151 values compared, 0 discrepancies.**

## case_002495.out

| Category | Compared | Problems |
|---|---:|---:|
| 1. Core maps (every cell, every state point) | 8,556 | 0 |
| 2. Ragged rows / null placement | 1,116 | 0 |
| 3. Symmetry expansion | 30,009 | 0 |
| 4. Non-numeric map round-trip (2PLO) | 2,139 | 0 |
| 5. Per-state-point scalars | 776 | 0 |
| 6. Depletion table | 590 | 0 |
| 7. Axial distributions | 992 | 0 |
| 8. Diagnostics roll-up | 90 | 0 |
| 9. Symmetry groups (ERR.CHK - SYMGRP) | 306 | 0 |
| 10. Assembly identity (FMAP / CMAP / footers) | 1,305 | 0 |
| 11. Cross-source consistency | 219 | 0 |
| 12. Units | 6 | 0 |

### 1. Core maps (every cell, every state point)
- note: 124 map blocks, codes={'2PIN': 31, '2PLO': 31, '2RPF': 31, '2EXP': 31}

### 2. Ragged rows / null placement
- note: 0 null slots across all maps (expected 0 for these files)

### 6. Depletion table
- note: 62 raw rows collapsed to 31 (echoed 2x)

### 8. Diagnostics roll-up
- note: raw rows=34 distinct=21 sums={'WARNING': 71, 'CAUTION': 33, 'NOTE': 40}

### 10. Assembly identity (FMAP / CMAP / footers)
- note: FMAP bands=2 cells=289
- note: CMAP cells=69
- note: segments=4 type counts={5: 64, 8: 56, 4: 56, 9: 65}

### 11. Cross-source consistency
- note: 62 BAT.EDT CORE rows cross-checked

### 12. Units
- note: heading units: {'2EXP': 'GWD/T'}
- note: payload units: {'2EXP': 'GWD/T'}

## apr1400.c02.out

| Category | Compared | Problems |
|---|---:|---:|
| 1. Core maps (every cell, every state point) | 7,728 | 0 |
| 2. Ragged rows / null placement | 1,008 | 0 |
| 3. Symmetry expansion | 27,105 | 0 |
| 4. Non-numeric map round-trip (2PLO) | 1,932 | 0 |
| 5. Per-state-point scalars | 701 | 0 |
| 6. Depletion table | 533 | 0 |
| 7. Axial distributions | 896 | 0 |
| 8. Diagnostics roll-up | 74 | 0 |
| 9. Symmetry groups (ERR.CHK - SYMGRP) | 78 | 0 |
| 10. Assembly identity (FMAP / CMAP / footers) | 1,301 | 0 |
| 11. Cross-source consistency | 198 | 0 |
| 12. Units | 6 | 0 |

### 1. Core maps (every cell, every state point)
- note: 112 map blocks, codes={'2PIN': 28, '2PLO': 28, '2RPF': 28, '2EXP': 28}

### 2. Ragged rows / null placement
- note: 0 null slots across all maps (expected 0 for these files)

### 6. Depletion table
- note: 56 raw rows collapsed to 28 (echoed 2x)

### 8. Diagnostics roll-up
- note: raw rows=32 distinct=17 sums={'WARNING': 4, 'CAUTION': 31, 'NOTE': 94}

### 10. Assembly identity (FMAP / CMAP / footers)
- note: FMAP bands=2 cells=289
- note: CMAP cells=69
- note: Fueled Segments total 241.001 vs 241 assemblies - source rounding of fractional (axially zoned) segments
- note: fuel-type numbers are not segment numbers here; only the total equivalent-assembly count is comparable
- note: segments=5 type counts={8: 56, 4: 56, 9: 65, 5: 64}

### 11. Cross-source consistency
- note: 56 BAT.EDT CORE rows cross-checked

### 12. Units
- note: heading units: {'2EXP': 'GWD/T'}
- note: payload units: {'2EXP': 'GWD/T'}

## 9074.out

| Category | Compared | Problems |
|---|---:|---:|
| 1. Core maps (every cell, every state point) | 37,056 | 0 |
| 2. Ragged rows / null placement | 2,880 | 0 |
| 3. Symmetry expansion | 0 | 0 |
| 4. Non-numeric map round-trip (2PLO) | 6,176 | 0 |
| 5. Per-state-point scalars | 801 | 0 |
| 6. Depletion table | 609 | 0 |
| 7. Axial distributions | 11,360 | 0 |
| 8. Diagnostics roll-up | 46 | 0 |
| 9. Symmetry groups (ERR.CHK - SYMGRP) | 2 | 0 |
| 10. Assembly identity (FMAP / CMAP / footers) | 387 | 0 |
| 11. Cross-source consistency | 162 | 0 |
| 12. Units | 8 | 0 |

### 1. Core maps (every cell, every state point)
- note: 192 map blocks, codes={'2RR1': 32, '2PIN': 32, '2PLO': 32, '2RPF': 32, '2KIN': 32, '2EXP': 32}

### 2. Ragged rows / null placement
- note: 0 null slots across all maps (expected 0 for these files)

### 3. Symmetry expansion
- note: full core - nothing expanded

### 4. Non-numeric map round-trip (2PLO)
- note: 3966 cells contained a '*'

### 6. Depletion table
- note: 64 raw rows collapsed to 32 (echoed 2x)

### 8. Diagnostics roll-up
- note: raw rows=20 distinct=10 sums={'WARNING': 1, 'CAUTION': 2, 'NOTE': 40}

### 10. Assembly identity (FMAP / CMAP / footers)
- note: no FMAP in this listing
- note: fuel-type numbers are not segment numbers here; only the total equivalent-assembly count is comparable
- note: FUE.TYP matrix cells=289
- note: segments=11 type counts={6: 32, 8: 8, 4: 28, 7: 8, 2: 65, 17: 3, 19: 1, 5: 32, 20: 1, 14: 3, 13: 3, 3: 4, 16: 3, 18: 1, 15: 1}

### 12. Units
- note: heading units: {'2EXP': 'GWD/T'}
- note: payload units: {'2EXP': 'GWD/T'}
