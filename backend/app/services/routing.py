"""Runoff routing on the DEM: water flows from high ground to low ground.

The uniform ponding model (inundation.depth_grid) spreads net runoff evenly over the window, so a
pit at the foot of a hill and a pit on a plateau fill the same. This module routes every cell's
runoff downslope by D8 on the raw DEM, lets it collect in depressions, and spills the overflow of
a full depression on to the next one downstream (fill-and-spill), until it leaves the window.

Outputs, all on the grid from inundation.get_dem():
  - depth (n, n) metres of ponded water after routing
  - routed flow accumulation in m3 per cell (how much water passed through)
  - flow paths (GeoJSON lines) where the routed flow is large
  - the catchment polygon of the centre point and its routed inflow
  - per-point metrics for the impact engine: flow convergence, upslope area, time of concentration

Everything is numpy; a 384 x 384 window routes in about a second after the one-off D8 pass,
which is cached on the grid dict together with the depression-filled surface.
"""
import math
import numpy as np
from scipy import ndimage

from app.services import terrain as T

FLOW_VELOCITY_M_S = 0.5          # overland flow speed used for time of concentration (Kerby-type order of magnitude)
PATH_SHARE = 0.02                 # a cell is a flow path when it carries >= 2% of the window's routed runoff
MAX_CASCADE = 50_000


def ensure_hydrology(grid: dict) -> dict:
    """D8 on the raw DEM (pits are sinks) and on the filled surface (for spill paths), cached on the grid."""
    if "hydro" in grid:
        return grid["hydro"]
    dem = grid["dem"].astype(np.float64)
    cw, ch = float(grid["cell_w_m"]), float(grid["cell_h_m"])
    filled = grid.get("filled")
    if filled is None:
        from app.services.inundation import priority_flood
        filled = priority_flood(dem)
        grid["filled"] = filled
        if grid.get("cache_key"):
            from app.services.inundation import _dem_disk_save
            _dem_disk_save(tuple(grid["cache_key"]), grid)
    fdir_raw, surf_raw = T.flow_direction(dem, cw, ch)          # water stops in pits
    fdir_fill, surf_fill = T.flow_direction(filled, cw, ch)     # water crosses full pits
    acc_cells = T.flow_accumulation(surf_fill, fdir_fill)       # topographic accumulation across full pits (channels)
    acc_raw = T.flow_accumulation(surf_raw, fdir_raw)           # accumulation into pits: what actually arrives at a cell
    storage = np.clip(filled - dem, 0, None)
    pits, n_pits = ndimage.label(storage > 0.01, structure=np.ones((3, 3), dtype=int))
    order_raw = np.argsort(surf_raw, axis=None)[::-1]
    hydro = {"fdir_raw": fdir_raw, "fdir_fill": fdir_fill, "acc_cells": acc_cells, "acc_raw": acc_raw, "storage": storage,
             "pits": pits, "n_pits": int(n_pits), "order_raw": order_raw, "surf_fill": surf_fill}
    grid["hydro"] = hydro
    return hydro


def _route_volumes(fdir: np.ndarray, order: np.ndarray, src: np.ndarray):
    """Push per-cell volumes downslope along D8 (high to low). Returns (through, sink_volume, exited).

    through[r, c] = total volume that passed through or landed in the cell; sink_volume holds what
    stopped in sink cells (fdir < 0 inside the window); exited is what left through the boundary.
    """
    n, m = fdir.shape
    through = src.astype(np.float64).copy()
    sink = np.zeros((n, m), dtype=np.float64)
    exited = 0.0
    rows, cols = np.unravel_index(order, (n, m))
    for r, c in zip(rows, cols):
        v = through[r, c]
        if v <= 0:
            continue
        k = fdir[r, c]
        if k == T.EXIT:
            exited += v
            continue
        if k < 0:
            sink[r, c] += v
            continue
        rr, cc = r + T._D8[k][0], c + T._D8[k][1]
        if 0 <= rr < n and 0 <= cc < m:
            through[rr, cc] += v
        else:
            exited += v
    return through, sink, exited


def _fill_pit(dem: np.ndarray, mask: np.ndarray, spill: float, volume: float, cell_a: float):
    """Water level inside one depression holding `volume` m3 (capped at the spill level)."""
    z = dem[mask]
    lo, hi = float(z.min()), float(spill)
    cap = float(np.clip(hi - z, 0, None).sum() * cell_a)
    if volume >= cap:
        return hi, cap
    for _ in range(40):
        mid = (lo + hi) / 2
        v = float(np.clip(mid - z, 0, None).sum() * cell_a)
        if v < volume:
            lo = mid
        else:
            hi = mid
    return hi, volume


def _spill_target(hydro: dict, pit_id: int, start_rc) -> tuple:
    """Follow the filled-surface D8 from a full pit's spill cell to the next pit or the edge."""
    fdir, pits = hydro["fdir_fill"], hydro["pits"]
    n, m = fdir.shape
    r, c = start_rc
    for _ in range(MAX_CASCADE):
        k = fdir[r, c]
        if k == T.EXIT or k < 0:
            return ("exit", None)
        r, c = r + T._D8[k][0], c + T._D8[k][1]
        if not (0 <= r < n and 0 <= c < m):
            return ("exit", None)
        p = pits[r, c]
        if p and p != pit_id:
            return ("pit", int(p))
    return ("exit", None)


def route_runoff(grid: dict, net_mm: float, runoff_weights: np.ndarray | None = None) -> dict:
    """Route `net_mm` of net runoff (optionally weighted per cell) downslope and fill depressions.

    Returns {depth, through_m3, pit_volume_m3, exited_m3, n_pits, n_pits_wet, n_overflows,
             generated_m3, ponded_m3, cell_a}.
    """
    dem = grid["dem"].astype(np.float64)
    cell_a = float(grid["cell_w_m"]) * float(grid["cell_h_m"])
    h = ensure_hydrology(grid)
    n, m = dem.shape
    depth = np.zeros((n, m), dtype=np.float64)
    if net_mm <= 0:
        return {"depth": depth, "through_m3": np.zeros((n, m)), "pit_volume_m3": {}, "exited_m3": 0.0,
                "n_pits": h["n_pits"], "n_pits_wet": 0, "n_overflows": 0, "generated_m3": 0.0, "ponded_m3": 0.0,
                "cell_a": cell_a}
    src = np.full((n, m), net_mm / 1000.0 * cell_a, dtype=np.float64)
    if runoff_weights is not None:
        src *= runoff_weights
    src[dem <= 0] = 0.0                                     # sea-level voids generate nothing
    through, sink, exited = _route_volumes(h["fdir_raw"], h["order_raw"], src)

    pits = h["pits"]
    n_pits = h["n_pits"]
    if n_pits == 0:
        return {"depth": depth, "through_m3": through, "pit_volume_m3": {}, "exited_m3": exited + float(sink.sum()),
                "n_pits": 0, "n_pits_wet": 0, "n_overflows": 0, "generated_m3": float(src.sum()), "ponded_m3": 0.0,
                "cell_a": cell_a}
    # direct inflow per pit = sink volume that stopped inside it (plus any sink cells outside pits -> exit)
    inflow = np.zeros(n_pits + 1, dtype=np.float64)
    np.add.at(inflow, pits.ravel(), sink.ravel())
    exited += float(inflow[0])
    inflow[0] = 0.0
    # spill elevation and lowest spill cell per pit, capacity
    spill = ndimage.maximum(grid["filled"], labels=pits, index=np.arange(1, n_pits + 1))
    cap = ndimage.sum(h["storage"], labels=pits, index=np.arange(1, n_pits + 1)) * cell_a
    # process pits from the highest spill down so overflow always lands on pits not yet closed
    order = np.argsort(-np.asarray(spill))
    pit_vol = np.zeros(n_pits + 1, dtype=np.float64)
    received = np.zeros(n_pits + 1, dtype=np.float64)
    objs = ndimage.find_objects(pits)
    n_over = 0
    for idx in order:
        pid = int(idx) + 1
        total = inflow[pid] + received[pid]
        if total <= 0:
            continue
        c_ = float(cap[idx])
        if total <= c_:
            pit_vol[pid] = total
            continue
        pit_vol[pid] = c_
        over = total - c_
        n_over += 1
        sl = objs[pid - 1]
        sub = pits[sl] == pid
        # spill cell: the pit cell on the filled surface with the lowest surrounding exit -> use the first cell at spill level
        rr, cc = np.nonzero(sub)
        r0, c0 = sl[0].start + rr[0], sl[1].start + cc[0]
        kind, target = _spill_target(h, pid, (r0, c0))
        if kind == "pit" and target is not None:
            received[target] += over
        else:
            exited += over
    # water levels per wet pit
    wet_pits = 0
    for pid in range(1, n_pits + 1):
        v = pit_vol[pid]
        if v <= 0:
            continue
        sl = objs[pid - 1]
        sub = pits[sl] == pid
        level, held = _fill_pit(dem[sl], sub, float(spill[pid - 1]), v, cell_a)
        d = np.clip(level - dem[sl], 0, None)
        d[~sub] = 0.0
        depth[sl] = np.maximum(depth[sl], d)
        wet_pits += 1
    depth = np.where(dem <= 0, 0, depth)
    return {"depth": depth, "through_m3": through, "pit_volume_m3": {int(i): float(pit_vol[i]) for i in range(1, n_pits + 1) if pit_vol[i] > 0},
            "exited_m3": float(exited), "n_pits": n_pits, "n_pits_wet": wet_pits, "n_overflows": n_over,
            "generated_m3": float(src.sum()), "ponded_m3": float(depth.sum() * cell_a), "cell_a": cell_a}


def upslope_mask(hydro: dict, r: int, c: int) -> tuple:
    """Cells draining to (r, c) on the raw-DEM D8, and the longest path length (steps) to it."""
    fdir = hydro["fdir_raw"]
    n, m = fdir.shape
    # build reverse adjacency lazily: for each cell, its downstream target index
    rows, cols = np.indices((n, m))
    k = fdir
    valid = k >= 0
    tr = rows + np.where(valid, np.array([d[0] for d in T._D8] + [0, 0])[np.clip(k, 0, 9)], 0)
    tc = cols + np.where(valid, np.array([d[1] for d in T._D8] + [0, 0])[np.clip(k, 0, 9)], 0)
    inside = valid & (tr >= 0) & (tr < n) & (tc >= 0) & (tc < m)
    target = np.where(inside, tr * m + tc, -1).ravel()
    # reverse graph as CSR
    src_idx = np.nonzero(target >= 0)[0]
    dst_idx = target[src_idx]
    order = np.argsort(dst_idx, kind="stable")
    dst_sorted, src_sorted = dst_idx[order], src_idx[order]
    starts = np.searchsorted(dst_sorted, np.arange(n * m + 1))
    mask = np.zeros(n * m, dtype=bool)
    dist = np.zeros(n * m, dtype=np.int32)
    root = r * m + c
    mask[root] = True
    frontier = [root]
    longest = 0
    while frontier:
        nxt = []
        for u in frontier:
            for v in src_sorted[starts[u]:starts[u + 1]]:
                if not mask[v]:
                    mask[v] = True
                    dist[v] = dist[u] + 1
                    longest = max(longest, int(dist[v]))
                    nxt.append(int(v))
        frontier = nxt
    return mask.reshape(n, m), longest


def point_metrics(grid: dict, r: int | None = None, c: int | None = None) -> dict:
    """Routing facts for one cell (default: the grid centre) for the impact engine."""
    h = ensure_hydrology(grid)
    dem = grid["dem"].astype(np.float64)
    n = dem.shape[0]
    r = n // 2 if r is None else r
    c = n // 2 if c is None else c
    cw, ch = float(grid["cell_w_m"]), float(grid["cell_h_m"])
    cell_km2 = cw * ch / 1e6
    acc = h["acc_raw"]
    pit = int(h["pits"][r, c])
    if pit:                                                                   # a pit shares the water its bottom receives
        a_pt = int(acc[h["pits"] == pit].max())
    else:
        a_pt = int(acc[max(r - 1, 0):r + 2, max(c - 1, 0):c + 2].max())
    log_acc = np.log(acc.astype(np.float64))
    convergence = float((log_acc < math.log(a_pt)).mean() * 100.0)          # percentile of accumulation in the window
    mask, longest = upslope_mask(h, r, c)
    up_cells = int(mask.sum())
    step = (cw + ch) / 2
    path_m = longest * step * 1.2                                             # D8 under-estimates true path length
    tc_min = path_m / FLOW_VELOCITY_M_S / 60.0 if path_m > 0 else 0.0
    relief = float(dem[mask].max() - dem[r, c]) if up_cells > 1 else 0.0
    pit_cap = float(h["storage"][h["pits"] == pit].sum() * cw * ch) if pit else 0.0
    return {
        "acc_cells_at_point": a_pt,
        "flow_convergence_pct": round(convergence, 1),
        "upslope_cells": up_cells, "upslope_area_km2": round(up_cells * cell_km2, 4),
        "longest_flow_path_m": round(path_m), "time_of_concentration_min": round(tc_min),
        "catchment_relief_m": round(relief, 1),
        "in_pit": bool(pit), "pit_capacity_m3": round(pit_cap),
        "flow_velocity_m_s": FLOW_VELOCITY_M_S,
    }


def flow_paths_geojson(grid: dict, through_m3: np.ndarray, share: float = PATH_SHARE, max_segments: int = 6000) -> dict:
    """Cells carrying at least `share` of the window's routed runoff, as short line segments to their downstream cell."""
    h = ensure_hydrology(grid)
    fdir = h["fdir_raw"]
    n, m = fdir.shape
    total = float(through_m3.max()) if through_m3.size else 0.0
    if total <= 0:
        return {"type": "FeatureCollection", "features": []}
    thr = share * total
    cand = np.argwhere((through_m3 >= thr) & (fdir >= 0))
    if len(cand) > max_segments:
        # keep the strongest paths
        vals = through_m3[cand[:, 0], cand[:, 1]]
        cand = cand[np.argsort(-vals)[:max_segments]]
    lats, lons = grid["lats"], grid["lons"]
    feats = []
    for r, c in cand:
        k = fdir[r, c]
        rr, cc = r + T._D8[k][0], c + T._D8[k][1]
        if not (0 <= rr < n and 0 <= cc < m):
            continue
        v = float(through_m3[r, c])
        feats.append({"type": "Feature",
                      "geometry": {"type": "LineString", "coordinates": [[round(float(lons[c]), 6), round(float(lats[r]), 6)],
                                                                         [round(float(lons[cc]), 6), round(float(lats[rr]), 6)]]},
                      "properties": {"flow_m3": round(v), "share": round(v / total, 3),
                                     "class": "major" if v >= 0.25 * total else "minor"}})
    return {"type": "FeatureCollection", "features": feats}


def catchment_geojson(grid: dict, mask: np.ndarray) -> dict:
    """Outline of a cell mask as GeoJSON MultiPolygon (reuses the inundation ring stitcher)."""
    from app.services.inundation import _wet_rings, _corner_val
    rings = _wet_rings(mask)
    coords = []
    for ring in rings:
        ring_geo = []
        for (cx, cy) in ring:
            gi = min(max(cx - 1, 0), grid["n"])
            gj = min(max(cy - 1, 0), grid["n"])
            ring_geo.append([round(float(_corner_val(grid["lons"], gi)), 6), round(float(_corner_val(grid["lats"], gj, lat_axis=True)), 6)])
        if ring_geo and ring_geo[0] != ring_geo[-1]:
            ring_geo.append(ring_geo[0])
        coords.append([ring_geo])
    return {"type": "Feature", "geometry": {"type": "MultiPolygon", "coordinates": coords},
            "properties": {"cells": int(mask.sum())}}
