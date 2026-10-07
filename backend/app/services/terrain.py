"""Terrain hydrology for a hyperlocal point, derived from the SRTM-based DEM
that app/services/inundation.py already downloads (AWS Terrain Tiles).

Computes, for the grid centred on the point:
  - slope (degrees) and aspect at the point (Horn 3x3 on the raw DEM)
  - D8 flow direction on the depression-filled surface
  - flow accumulation (upstream cell count -> upstream area in km2)
  - HAND: height above nearest drainage, following the D8 path from the point
    to the first channel cell (accumulation above a threshold)
  - closed-depression (sink) flag and depth where the point sits in a filled pit
  - fraction of the window that drains through the point

Everything is numpy; a 256x256 window takes well under a second.
"""
import math

import numpy as np

# D8 neighbour offsets (row, col) and their planimetric distance factor
_D8 = [(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)]
_D8_DIST = [1.0, math.sqrt(2), 1.0, math.sqrt(2), 1.0, math.sqrt(2), 1.0, math.sqrt(2)]


def slope_aspect(dem: np.ndarray, r: int, c: int, cell_w: float, cell_h: float):
    """Horn slope (deg) and aspect (deg clockwise from north) at (r, c)."""
    n = dem.shape[0]
    r0, r1 = max(r - 1, 0), min(r + 1, n - 1)
    c0, c1 = max(c - 1, 0), min(c + 1, n - 1)
    z = dem
    a, b, cc = z[r0, c0], z[r0, c], z[r0, c1]
    d, _, f = z[r, c0], z[r, c], z[r, c1]
    g, h, i = z[r1, c0], z[r1, c], z[r1, c1]
    dzdx = ((cc + 2 * f + i) - (a + 2 * d + g)) / (8 * cell_w)
    dzdy = ((g + 2 * h + i) - (a + 2 * b + cc)) / (8 * cell_h)
    slope = math.degrees(math.atan(math.hypot(dzdx, dzdy)))
    aspect = (math.degrees(math.atan2(dzdx, -dzdy)) + 360) % 360
    return slope, aspect


EXIT = -2  # boundary cell that drains out of the window


def resolve_flats(filled: np.ndarray) -> np.ndarray:
    """Add a tiny gradient across flat areas so D8 can cross them.

    Cells with a strictly lower neighbour are seeds (level 0). Flat neighbours
    (equal elevation) get level 1, 2, ... by breadth-first search, and the
    pseudo-elevation rises with the level, so water inside a flat drains toward
    the seed that actually has an outlet. Standard towards-lower-edge flat routing.
    """
    n, m = filled.shape
    pad = np.pad(filled, 1, mode="edge")
    has_drop = np.zeros((n, m), dtype=bool)
    for dr, dc in _D8:
        nb = pad[1 + dr:1 + dr + n, 1 + dc:1 + dc + m]
        has_drop |= nb < filled
    # boundary cells are outlets too (water can leave the window)
    has_drop[0, :] = has_drop[-1, :] = has_drop[:, 0] = has_drop[:, -1] = True
    level = np.full((n, m), -1, dtype=np.int32)
    level[has_drop] = 0
    frontier = np.argwhere(has_drop)
    k = 0
    while len(frontier):
        k += 1
        nxt = []
        for r, c in frontier:
            z = filled[r, c]
            for dr, dc in _D8:
                rr, cc = r + dr, c + dc
                if 0 <= rr < n and 0 <= cc < m and level[rr, cc] < 0 and filled[rr, cc] == z:
                    level[rr, cc] = k
                    nxt.append((rr, cc))
        frontier = np.array(nxt, dtype=np.int64) if nxt else np.empty((0, 2), dtype=np.int64)
    level[level < 0] = 0
    return filled + level.astype(np.float32) * 1e-3


def flow_direction(filled: np.ndarray, cell_w: float, cell_h: float):
    """D8 steepest-descent direction index (0..7) per cell on the flat-resolved
    surface; EXIT for boundary cells draining out, -1 for true pits.
    Returns (fdir, surf) where surf is the flat-resolved surface used for ordering."""
    n, m = filled.shape
    surf = resolve_flats(filled)
    best = np.full((n, m), -1, dtype=np.int8)
    best_drop = np.zeros((n, m), dtype=np.float32)
    big = np.pad(surf, 1, mode="constant", constant_values=np.inf)
    for k, ((dr, dc), dist) in enumerate(zip(_D8, _D8_DIST)):
        nb = big[1 + dr:1 + dr + n, 1 + dc:1 + dc + m]
        step = dist * (cell_w if dr == 0 else cell_h if dc == 0 else (cell_w + cell_h) / 2)
        drop = (surf - nb) / step
        better = drop > best_drop
        best[better] = k
        best_drop[better] = drop[better]
    # boundary cells with no lower inside neighbour drain out of the window
    edge = np.zeros((n, m), dtype=bool)
    edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = True
    best[edge & (best < 0)] = EXIT
    return best, surf


def flow_accumulation(filled: np.ndarray, fdir: np.ndarray) -> np.ndarray:
    """Upstream cell count (including self) by processing cells high to low."""
    n, m = filled.shape
    acc = np.ones((n, m), dtype=np.int32)
    order = np.argsort(filled, axis=None)[::-1]
    rows, cols = np.unravel_index(order, (n, m))
    fd = fdir
    for r, c in zip(rows, cols):
        k = fd[r, c]
        if k < 0:
            continue
        rr, cc = r + _D8[k][0], c + _D8[k][1]
        if 0 <= rr < n and 0 <= cc < m:
            acc[rr, cc] += acc[r, c]
    return acc


def trace_to_channel(dem, filled, fdir, acc, r, c, channel_thresh, max_steps=4000):
    """Follow the D8 path from (r, c) to the first channel cell.

    Returns (hand_m, path_cells, reached_channel, exit_edge).
    """
    n, m = dem.shape
    z0 = float(dem[r, c])
    steps = 0
    rr, cc = r, c
    while steps < max_steps:
        if acc[rr, cc] >= channel_thresh and (rr, cc) != (r, c):
            return max(0.0, z0 - float(dem[rr, cc])), steps, True, False
        k = fdir[rr, cc]
        if k == EXIT:
            return max(0.0, z0 - float(dem[rr, cc])), steps, False, True
        if k < 0:
            return max(0.0, z0 - float(dem[rr, cc])), steps, False, False
        nr, nc = rr + _D8[k][0], cc + _D8[k][1]
        if not (0 <= nr < n and 0 <= nc < m):
            return max(0.0, z0 - float(dem[rr, cc])), steps, False, True
        rr, cc = nr, nc
        steps += 1
    return max(0.0, z0 - float(dem[rr, cc])), steps, False, False


def analyse(grid: dict, filled: np.ndarray, channel_area_km2: float = 0.15) -> dict:
    """Terrain hydrology summary for the centre of a DEM grid from get_dem()."""
    dem = grid["dem"].astype(np.float32)
    n = dem.shape[0]
    r = c = n // 2
    cw, ch = float(grid["cell_w_m"]), float(grid["cell_h_m"])
    cell_km2 = cw * ch / 1e6

    slope_deg, aspect = slope_aspect(dem, r, c, cw, ch)
    # smoother slope over ~5 cells for the landslide check (single-cell SRTM noise is large)
    k = 2
    sub = dem[max(r - k, 0):r + k + 1, max(c - k, 0):c + k + 1]
    reg_slope = math.degrees(math.atan((float(sub.max()) - float(sub.min())) / (2 * k * (cw + ch) / 2)))

    fdir, surf = flow_direction(filled, cw, ch)
    acc = flow_accumulation(surf, fdir)
    thresh = max(3, int(channel_area_km2 / cell_km2))
    hand, path_len, reached, exit_edge = trace_to_channel(dem, filled, fdir, acc, r, c, thresh)

    # upstream area through the point (3x3 max so a one-cell offset does not miss the channel)
    up_cells = int(acc[max(r - 1, 0):r + 2, max(c - 1, 0):c + 2].max())
    upstream_km2 = up_cells * cell_km2
    window_km2 = n * n * cell_km2

    pit_depth = float(filled[r, c] - dem[r, c])
    in_sink = pit_depth > 0.3
    # closed-basin check: does the point's path leave the window or reach a channel?
    no_outlet = (not reached) and (not exit_edge)

    # relative relief of the surrounding ~1 km
    rad = max(1, int(500 / ((cw + ch) / 2)))
    ring = dem[max(r - rad, 0):r + rad + 1, max(c - rad, 0):c + rad + 1]
    rel_low = float((ring > dem[r, c]).mean())  # share of nearby cells higher than the point

    return {
        "elevation_m": round(float(dem[r, c]), 1),
        "slope_deg": round(slope_deg, 2),
        "slope_deg_regional": round(reg_slope, 2),
        "aspect_deg": round(aspect, 0),
        "hand_m": round(hand, 2),
        "hand_path_m": round(path_len * (cw + ch) / 2),
        "reached_channel": bool(reached),
        "upstream_area_km2": round(upstream_km2, 3),
        "upstream_share_of_window": round(upstream_km2 / window_km2, 4),
        "in_closed_depression": bool(in_sink),
        "depression_depth_m": round(pit_depth, 2),
        "no_outlet_in_window": bool(no_outlet),
        "share_of_neighbours_higher": round(rel_low, 3),
        "window_km": round(float(grid["span_km"]), 2),
        "resolution_m": float(grid["res_m"]),
        "channel_threshold_km2": channel_area_km2,
        "source": grid.get("source", "dem"),
    }
