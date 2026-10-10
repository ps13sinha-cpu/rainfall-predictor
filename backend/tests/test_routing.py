"""Runoff routing: water goes from high ground to low ground and collects where the terrain says."""
import numpy as np

from app.services import routing as RT
from app.services.inundation import priority_flood, routed_depth_grid, depth_grid


def _grid(dem):
    n = dem.shape[0]
    return {"dem": dem.astype(np.float32), "lats": np.linspace(13.0, 13.01, n), "lons": np.linspace(80.0, 80.01, n),
            "cell_w_m": 10.0, "cell_h_m": 10.0, "z": 15, "n": n, "res_m": 10.0, "span_km": n * 0.01, "source": "test"}


def test_tilted_plane_exits_everything():
    n = 40
    dem = np.tile(np.linspace(20, 10, n), (n, 1))          # falls to the east edge
    g = _grid(dem)
    r = RT.route_runoff(g, 20.0)
    assert r["n_pits"] == 0
    assert abs(r["exited_m3"] - r["generated_m3"]) < 1e-6
    assert r["depth"].max() == 0.0


def test_bowl_collects_runoff_from_its_slopes():
    n = 41
    y, x = np.mgrid[0:n, 0:n]
    dem = 10.0 + 0.02 * ((y - 20) ** 2 + (x - 20) ** 2)   # bowl with the bottom in the middle, rim 18 m
    dem[0, :] = dem[-1, :] = dem[:, 0] = dem[:, -1] = 9.0   # a channel around the edge so the rim spills
    g = _grid(dem)
    r = RT.route_runoff(g, 10.0)
    assert r["n_pits"] >= 1 and r["n_pits_wet"] >= 1
    assert r["depth"][20, 20] > 0.3                        # the bottom holds water
    assert r["depth"][2, 2] == 0.0                         # the rim does not
    # routed water in the bowl exceeds what fell on the bottom cell alone
    assert r["through_m3"][20, 20] > 50 * (10.0 / 1000.0 * 100.0)
    pm = RT.point_metrics(g)
    assert pm["flow_convergence_pct"] > 90 and pm["upslope_cells"] > 100 and pm["catchment_relief_m"] > 5


def test_routed_grid_matches_depth_grid_contract():
    n = 41
    y, x = np.mgrid[0:n, 0:n]
    dem = 10.0 + 0.02 * ((y - 20) ** 2 + (x - 20) ** 2)
    dem[0, :] = dem[-1, :] = dem[:, 0] = dem[:, -1] = 9.0
    g = _grid(dem)
    g["filled"] = priority_flood(g["dem"].astype(np.float64))
    a, b = routed_depth_grid(g, 10.0), depth_grid(g, 10.0)
    assert a["depth"].shape == b["depth"].shape
    assert set(("depth", "mode", "spilled", "pit_storage", "volume", "cell_a")) <= set(a)
    assert a["routing"]["mode"] == "d8_fill_spill"
    assert a["mode"].startswith("routed")
