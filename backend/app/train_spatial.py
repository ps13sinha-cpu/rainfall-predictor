"""
RIIS — Train the spatial nowcasting models: ConvLSTM and ConvGRU.

Input:  the last 12 hourly precipitation frames over the Chennai-centred grid
        (11 x 11 points at 0.25 deg, from app/ingest_grid.py).
Target: accumulated rainfall over the NEXT 6 hours at every grid point
        (regression on log1p(mm), decoded back to mm and to the app's classes:
        safe <5, mod 5-20, high 20-50, extreme >50).

Metrics follow nowcasting practice: RMSE / MAE in mm per 6h, Critical Success
Index at 1, 5 and 20 mm, plus pixel class accuracy, all compared with the
persistence baseline (assume the last 6 hours repeat).

Usage:
    cd backend
    python -m app.train_spatial                # both
    python -m app.train_spatial convlstm
    python -m app.train_spatial convgru
"""
import os
import sys
import json
import time
from datetime import datetime

import numpy as np

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ml_models")
GRID_PATH = os.path.join(MODEL_DIR, "grid_precip.npz")
REGISTRY = os.path.join(MODEL_DIR, "model_registry.json")

IN_FRAMES = 12
HORIZON = 6
TEST_FRACTION = 0.15
# Optional held-out event block "YYYY-MM-DDTHH:MM:YYYY-MM-DDTHH:MM" (target start within it = test).
# Default: November 2024 through Cyclone Fengal, the wettest stretch in the grid.
TEST_BLOCK = os.environ.get("RIIS_SPATIAL_TEST", "2024-11-01T00:00:2024-12-05T00:00")
# Contiguous validation block for checkpoint selection (overlapping windows make a random split in-sample).
VAL_BLOCK = os.environ.get("RIIS_SPATIAL_VAL", "2024-10-10T00:00:2024-10-31T00:00")
MAX_EPOCHS = int(os.environ.get("RIIS_SPATIAL_EPOCHS", "40"))
MAX_MINUTES = float(os.environ.get("RIIS_SPATIAL_MINUTES", "25"))


def rain_class(mm):
    return np.where(mm > 50, 3, np.where(mm > 20, 2, np.where(mm > 5, 1, 0)))


def grid_pins() -> dict:
    """Date range, frame count and content hash of the gridded training file."""
    import hashlib
    z = np.load(GRID_PATH, allow_pickle=True)
    times = [str(t) for t in z["times"]] if "times" in z.files else []
    arr = z[z.files[0]] if "precip" not in z.files else z["precip"]
    h = hashlib.sha256(np.ascontiguousarray(arr).tobytes()).hexdigest()
    return {"frames": int(arr.shape[0]), "grid_shape": list(arr.shape[1:]), "sha256": h,
            "start_time": times[0] if times else None, "end_time": times[-1] if times else None,
            "seed": 42, "label_source": "Open-Meteo archive hourly precipitation on a 0.25 degree grid (ERA5-Land)"}


def load_windows():
    z = np.load(GRID_PATH)
    P = z["precip"].astype(np.float32)          # (T, H, W) mm/h
    times = z["times"]
    T = len(P)
    cs = np.concatenate([np.zeros((1,) + P.shape[1:], np.float32), np.cumsum(P, axis=0)])
    # window ending at t (inclusive) -> input P[t-11..t], target sum P[t+1..t+6]
    ends = np.arange(IN_FRAMES - 1, T - HORIZON)
    y = cs[ends + 1 + HORIZON] - cs[ends + 1]            # (N, H, W) mm per 6h
    persist = cs[ends + 1] - cs[ends + 1 - HORIZON]      # last 6h, baseline
    tstr = np.array([str(t) for t in times])
    if TEST_BLOCK and TEST_BLOCK.lower() != "tail":
        a, b = TEST_BLOCK[:16], TEST_BLOCK[17:]
        va_a, va_b = VAL_BLOCK[:16], VAL_BLOCK[17:]
        tgt_start = tstr[ends + 1]
        is_test = (tgt_start >= a) & (tgt_start < b)
        is_val = (tgt_start >= va_a) & (tgt_start < va_b)
        # drop train windows whose input or target touches either block (no leakage either way)
        touch = ((tstr[ends - IN_FRAMES + 1] < b) & (tstr[ends + HORIZON] >= a)) |                 ((tstr[ends - IN_FRAMES + 1] < va_b) & (tstr[ends + HORIZON] >= va_a))
        tr_idx = np.where(~touch)[0]
        te_idx = np.where(is_test)[0]
        va_idx = np.where(is_val)[0]
        print(f"frames {T} ({times[0]} .. {times[-1]}), grid {P.shape[1]}x{P.shape[2]}, windows {len(ends)} "
              f"(train {len(tr_idx)}, val block {va_a}..{va_b}: {len(va_idx)}, "
              f"held-out test block {a}..{b}: {len(te_idx)})")
        return P, ends, y, persist, (tr_idx, va_idx, te_idx), times
    else:
        n_test = int(len(ends) * TEST_FRACTION)
        split = len(ends) - n_test
        cut = int(split * 0.9)
        print(f"frames {T} ({times[0]} .. {times[-1]}), grid {P.shape[1]}x{P.shape[2]}, windows {len(ends)} "
              f"(train {cut}, val {split - cut}, test {n_test}; test from {times[ends[split]]})")
        return P, ends, y, persist, (np.arange(cut), np.arange(cut, split), np.arange(split, len(ends))), times


def build_cells():
    import torch
    import torch.nn as nn

    class ConvLSTMCell(nn.Module):
        def __init__(self, cin, hid, k=3):
            super().__init__()
            self.hid = hid
            self.conv = nn.Conv2d(cin + hid, 4 * hid, k, padding=k // 2)

        def forward(self, x, state):
            h, c = state
            i, f, o, g = torch.chunk(self.conv(torch.cat([x, h], 1)), 4, dim=1)
            i, f, o, g = torch.sigmoid(i), torch.sigmoid(f), torch.sigmoid(o), torch.tanh(g)
            c = f * c + i * g
            h = o * torch.tanh(c)
            return h, (h, c)

        def init(self, b, hw, device):
            z = torch.zeros(b, self.hid, *hw, device=device)
            return (z, z.clone())

    class ConvGRUCell(nn.Module):
        def __init__(self, cin, hid, k=3):
            super().__init__()
            self.hid = hid
            self.gates = nn.Conv2d(cin + hid, 2 * hid, k, padding=k // 2)
            self.cand = nn.Conv2d(cin + hid, hid, k, padding=k // 2)

        def forward(self, x, state):
            h = state
            z, r = torch.chunk(torch.sigmoid(self.gates(torch.cat([x, h], 1))), 2, dim=1)
            n = torch.tanh(self.cand(torch.cat([x, r * h], 1)))
            h = (1 - z) * n + z * h
            return h, h

        def init(self, b, hw, device):
            return torch.zeros(b, self.hid, *hw, device=device)

    class SpatialNowcaster(nn.Module):
        """Stacked recurrent conv encoder over the input frames -> 6h accumulation map."""
        def __init__(self, cell, hidden=(32, 48)):
            super().__init__()
            cins = (1,) + tuple(hidden[:-1])
            self.cells = nn.ModuleList([cell(ci, h) for ci, h in zip(cins, hidden)])
            self.norms = nn.ModuleList([nn.GroupNorm(4, h) for h in hidden])
            self.head = nn.Sequential(nn.Conv2d(hidden[-1], 32, 3, padding=1), nn.GELU(),
                                      nn.Conv2d(32, 1, 1))

        def forward(self, x):  # x: (B, T, 1, H, W)
            b, t = x.shape[:2]
            hw = x.shape[-2:]
            states = [c.init(b, hw, x.device) for c in self.cells]
            for step in range(t):
                inp = x[:, step]
                for li, (cell, norm) in enumerate(zip(self.cells, self.norms)):
                    out, states[li] = cell(inp, states[li])
                    inp = norm(out)
            return torch.nn.functional.softplus(self.head(inp)).squeeze(1)  # log1p-mm, (B, H, W)

    return {"convlstm": ConvLSTMCell, "convgru": ConvGRUCell}, SpatialNowcaster


def metrics(pred_mm, y_mm):
    out = {"rmse_mm": round(float(np.sqrt(np.mean((pred_mm - y_mm) ** 2))), 3),
           "mae_mm": round(float(np.mean(np.abs(pred_mm - y_mm))), 3)}
    for th in (1.0, 5.0, 20.0):
        hit = np.sum((pred_mm >= th) & (y_mm >= th))
        miss = np.sum((pred_mm < th) & (y_mm >= th))
        fa = np.sum((pred_mm >= th) & (y_mm < th))
        out[f"csi_{th:g}mm"] = round(float(hit / max(hit + miss + fa, 1)), 3)
        out[f"pod_{th:g}mm"] = round(float(hit / max(hit + miss, 1)), 3)
    pc, yc = rain_class(pred_mm), rain_class(y_mm)
    out["pixel_class_accuracy"] = round(float(np.mean(pc == yc)), 4)
    out["heavy_pixel_recall"] = round(float(np.sum((pc >= 2) & (yc >= 2)) / max(np.sum(yc >= 2), 1)), 3)
    out["wet_fraction_truth"] = round(float(np.mean(y_mm >= 1.0)), 4)
    return out


def predict_all(model, P, ends, idx, device, bs=256):
    import torch
    model.eval()
    outs = []
    ar = np.arange(-IN_FRAMES + 1, 1)
    with torch.no_grad():
        for i in range(0, len(idx), bs):
            e = ends[idx[i:i + bs]]
            xb = np.log1p(P[e[:, None] + ar[None, :]])[:, :, None]  # (B, T, 1, H, W)
            xb = torch.from_numpy(xb).to(device)
            outs.append(np.expm1(model(xb).cpu().numpy()))
    return np.concatenate(outs)


def train_one(name, cell, Net, P, ends, y, persist, split, device):
    import torch
    import torch.nn as nn
    torch.manual_seed(42)
    rng = np.random.default_rng(42)
    tr, va, te = split

    model = Net(cell).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    opt = torch.optim.AdamW(model.parameters(), lr=1.5e-3, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=MAX_EPOCHS)
    y_log = np.log1p(y).astype(np.float32)
    ar = np.arange(-IN_FRAMES + 1, 1)
    bs = 32
    t0, best, best_state, history = time.time(), 1e9, None, []

    for epoch in range(MAX_EPOCHS):
        model.train()
        order = rng.permutation(tr)
        tot, nb = 0.0, 0
        for i in range(0, len(order), bs):
            bi = order[i:i + bs]
            e = ends[bi]
            xb = torch.from_numpy(np.log1p(P[e[:, None] + ar[None, :]])[:, :, None]).to(device)
            yb = torch.from_numpy(y_log[bi]).to(device)
            # weight wet targets more so the model does not collapse to "no rain"
            w = 1.0 + 3.0 * (yb > np.log1p(1.0)) + 6.0 * (yb > np.log1p(10.0))
            opt.zero_grad()
            loss = (w * (model(xb) - yb) ** 2).mean()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            tot += loss.item()
            nb += 1
        sched.step()
        pv = predict_all(model, P, ends, va, device)
        vm = metrics(pv, y[va])
        history.append({"epoch": epoch + 1, "loss": round(tot / nb, 4), "val_rmse": vm["rmse_mm"],
                        "val_csi_5mm": vm["csi_5mm"]})
        print(f"  epoch {epoch+1:2d} loss {tot/nb:.4f}  val rmse {vm['rmse_mm']:.3f}  "
              f"csi5 {vm['csi_5mm']:.3f}  csi1 {vm['csi_1mm']:.3f}  ({time.time()-t0:.0f}s)")
        score = vm["rmse_mm"] - 2.0 * vm["csi_5mm"]
        if score < best:
            best = score
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        if (time.time() - t0) / 60 > MAX_MINUTES:
            print("  time budget reached")
            break

    model.load_state_dict(best_state)
    pt = predict_all(model, P, ends, te, device)
    test = metrics(pt, y[te])
    base = metrics(persist[te], y[te])
    secs = time.time() - t0
    torch.save({"state_dict": best_state, "model": name, "in_frames": IN_FRAMES, "horizon": HORIZON,
                "grid_shape": list(P.shape[1:]), "hidden": [32, 48]}, os.path.join(MODEL_DIR, f"{name}.pt"))
    entry = {
        "family": "spatial", "task": "next_6h_rain_grid", "input": f"last {IN_FRAMES} hourly frames, {P.shape[1]}x{P.shape[2]} grid",
        "params": int(n_params), "device": str(device), "epochs_run": len(history),
        "train_windows": int(len(tr)), "val_windows": int(len(va)), "test_windows": int(len(te)),
        "test_block": TEST_BLOCK, "val_block": VAL_BLOCK, "data_pins": grid_pins(), "train_seconds": round(secs, 1), "trained_at": datetime.utcnow().isoformat(),
        "history": history, "metrics": test, "persistence_baseline": base,
    }
    print(f"  {name}: TEST rmse {test['rmse_mm']} mm (persistence {base['rmse_mm']}), "
          f"CSI5 {test['csi_5mm']} (persistence {base['csi_5mm']}), class acc {test['pixel_class_accuracy']}  "
          f"({secs:.0f}s, {n_params} params)")
    return entry


def main():
    import torch
    which = sys.argv[1:] or ["convlstm", "convgru"]
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"device: {device}  torch {torch.__version__}")
    if device.type == "cpu":
        torch.set_num_threads(max(1, os.cpu_count() - 2))
    P, ends, y, persist, split, times = load_windows()
    cells, Net = build_cells()
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from app.services.features import update_registry
    for name in which:
        print(f"\n== {name} ==")
        entry = train_one(name, cells[name], Net, P, ends, y, persist, split, device)
        entry["grid"] = {"lat_min": 11.0, "lat_max": 13.5, "lon_min": 78.0, "lon_max": 80.5,
                         "step_deg": 0.25, "frames": int(len(P)),
                         "period": [str(times[0]), str(times[-1])]}
        update_registry(REGISTRY, {name: entry})
    print(f"\nSPATIAL TRAINING COMPLETE -> {REGISTRY}")


if __name__ == "__main__":
    main()
