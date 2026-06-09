"""Plan-free obstacle detection from coverage holes.

We never receive a planned route, so obstacles can't be found as "actual vs planned
deviations". Instead: an obstacle is an UN-MOWED island fully surrounded by mowed area
inside a go-zone (the mower routed around it), and NOT explained by a no-go zone. Holes
connected to the not-yet-mowed frontier / zone edge are excluded by a flood-fill, so this
works progressively during a mow and cleanly at the end.
"""
from __future__ import annotations

import math

from .map_tuning import MIN_OBJECT_DIM

# Keep-out distance the mower leaves around an obstacle (deck reach + safety margin).
# The un-mowed hole ≈ object + this on every side; subtract it to estimate object size.
STANDOFF_M = 0.5


def _pip(px, py, poly) -> bool:
    """Ray-cast point-in-polygon. poly = list of (x, y)."""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i][0], poly[i][1]
        xj, yj = poly[j][0], poly[j][1]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / ((yj - yi) or 1e-9) + xi):
            inside = not inside
        j = i
    return inside


def detect_obstacles(go_zones, nogo_polys, coverage, cell: float = 0.4,
                     min_cells: int = 4, max_obstacles: int = 40,
                     lowconf=None, lowconf_r: float = 2.5, max_seg: float = 2.0):
    """go_zones = [{"name","polygon":[(x,y)...]}], nogo_polys = [[(x,y)...]],
    coverage = [(x,y)...] (ORDERED pose-trail). Returns [{center,cells,footprint,zone}].

    lowconf = optional list of (x,y) LOW-CONFIDENCE poses (e.g. back-propagated burst points
    after a comms blackout): coverage there is sparse, so a 'hole' near one is a sampling
    artifact, not a real object — holes within lowconf_r m of one are dropped."""
    if not coverage:
        return []
    # COVERED = the swath rasterised as a DENSE, continuous path (interpolate along each
    # segment + mark the endpoints), NOT one cell per breadcrumb point. Sparse sampling —
    # a back-prop burst at ~5 m spacing, or even normal ~0.5 m live spacing against the 0.4 m
    # grid — otherwise leaves gaps BETWEEN points that read as enclosed holes = false obstacles
    # (16 phantom obstacles on the 2026-06-07 backyard mow, all from this). Segments longer
    # than max_seg are JUMPS (zone transit / back-prop shortcut), not real swath — mark only
    # their endpoints so we never fabricate a coverage corridor across a gap.
    covered = set()
    def _cov(x, y):
        covered.add((int(math.floor(x / cell)), int(math.floor(y / cell))))
    _cov(*coverage[0])
    for k in range(1, len(coverage)):
        (x0, y0), (x1, y1) = coverage[k - 1], coverage[k]
        _cov(x1, y1)
        seg = math.hypot(x1 - x0, y1 - y0)
        if seg <= max_seg:
            n = max(1, int(seg / (cell * 0.5)))
            for s in range(1, n):
                _cov(x0 + (x1 - x0) * s / n, y0 + (y1 - y0) * s / n)

    obstacles = []
    for zone in go_zones:
        poly = zone.get("polygon") or []
        if len(poly) < 3:
            continue
        xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
        cx0, cx1 = int(math.floor(min(xs) / cell)), int(math.ceil(max(xs) / cell))
        cy0, cy1 = int(math.floor(min(ys) / cell)), int(math.ceil(max(ys) / cell))
        inside = set()
        for cx in range(cx0, cx1 + 1):
            for cy in range(cy0, cy1 + 1):
                px, py = (cx + 0.5) * cell, (cy + 0.5) * cell
                if _pip(px, py, poly) and not any(_pip(px, py, ng) for ng in nogo_polys):
                    inside.add((cx, cy))
        uncovered = {c for c in inside if c not in covered}
        if not uncovered:
            continue
        # Seeds = uncovered cells touching the zone edge (a neighbour outside `inside`),
        # i.e. the reachable frontier / unmowable border. Flood within uncovered.
        seen = {c for c in uncovered
                if any((c[0] + dx, c[1] + dy) not in inside for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)))}
        stack = list(seen)
        while stack:
            c = stack.pop()
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nb = (c[0] + dx, c[1] + dy)
                if nb in uncovered and nb not in seen:
                    seen.add(nb); stack.append(nb)
        enclosed = uncovered - seen   # islands NOT connected to the edge/frontier
        # single-link cluster the enclosed cells
        rem = set(enclosed)
        while rem:
            start = rem.pop()
            comp = [start]; stk = [start]
            while stk:
                c = stk.pop()
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nb = (c[0] + dx, c[1] + dy)
                        if nb in rem:
                            rem.discard(nb); comp.append(nb); stk.append(nb)
            if len(comp) >= min_cells:
                gx = [c[0] * cell + cell / 2 for c in comp]
                gy = [c[1] * cell + cell / 2 for c in comp]
                fw = max(gx) - min(gx) + cell
                fh = max(gy) - min(gy) + cell
                # Reject SLIVERS: a long, thin hole is the gap a U-turn pivot leaves between
                # the inbound/outbound swaths, not a real object the mower drove around. Real
                # obstacles (tree, post, bed) read blob-ish. (Validated vs Nate's 2026-06-05
                # backyard: false corner hole 0.4×2.0 m = 5.0 aspect, real middle 1.2×0.8 =
                # 1.5 aspect.)
                if max(fw, fh) / max(0.01, min(fw, fh)) > 3.5:
                    continue
                # The un-mowed HOLE = the object + the mower's keep-out standoff on every
                # side (the deck can't reach right up to it). Subtract ~1 standoff per side
                # to estimate the real OBJECT footprint, which is what the map should depict.
                ow = max(0.1, fw - 2 * STANDOFF_M)
                oh = max(0.1, fh - 2 * STANDOFF_M)
                # Reject PHANTOMS: a hole barely bigger than the standoff ring has no real object
                # inside it — it's a small enclosed coverage gap on a straight pass, not something
                # the mower drove around. (Real objects keep a meaningful longest side.)
                if max(ow, oh) < MIN_OBJECT_DIM:
                    continue
                ocx, ocy = round(sum(gx) / len(gx), 2), round(sum(gy) / len(gy), 2)
                # Drop holes in a low-confidence (sparse back-prop) region — coverage there is
                # too sparse to tell a real object from a sampling gap.
                if lowconf and any((ocx - bx) ** 2 + (ocy - by) ** 2 < lowconf_r ** 2
                                   for bx, by in lowconf):
                    continue
                obstacles.append({
                    "center": (ocx, ocy),
                    "cells": len(comp),
                    "footprint_m": (round(fw, 2), round(fh, 2)),  # un-mowed hole (avoidance)
                    "object_m": (round(ow, 2), round(oh, 2)),      # estimated real object
                    "zone": zone.get("name"),
                })
    obstacles.sort(key=lambda o: -o["cells"])
    return obstacles[:max_obstacles]
