"""Re-evaluate a saved sequence checkpoint on the held-out windows and print
probability diagnostics (how the heavy-rain probability is distributed).

Usage:
    cd backend
    python -m app.eval_sequence lstm_impact
    python -m app.eval_sequence transformer
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from app.train_sequence import load_series, build_models, batches, rain_class, MODEL_DIR  # noqa: E402


def main():
    import torch
    from sklearn.metrics import roc_auc_score, average_precision_score
    name = sys.argv[1] if len(sys.argv) > 1 else "lstm_impact"
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    ck = torch.load(os.path.join(MODEL_DIR, f"{name}.pt"), map_location=device)
    X, y_mm, ends, is_test, norm = load_series()
    y_cls = rain_class(y_mm)
    model = build_models()[name](X.shape[1]).to(device)
    model.load_state_dict(ck["state_dict"])
    model.eval()
    te = np.where(is_test)[0]
    probs = []
    with torch.no_grad():
        for xb, _ in batches(X, ends, te, 2048, device, False, None):
            probs.append(torch.softmax(model(xb), 1).cpu().numpy())
    probs = np.concatenate(probs)
    yt = y_cls[ends[te]]
    heavy = (yt >= 2).astype(int)
    hp = probs[:, 2:].sum(1)
    print(f"{name}: test windows {len(te)}, heavy positives {heavy.sum()}")
    print(f"  heavy prob: mean {hp.mean():.4f}  p50 {np.median(hp):.4f}  p99 {np.percentile(hp, 99):.4f}  max {hp.max():.4f}")
    print(f"  heavy prob on positives: mean {hp[heavy == 1].mean():.4f}   on negatives: mean {hp[heavy == 0].mean():.4f}")
    print(f"  AUC(heavy, p2+p3) {roc_auc_score(heavy, hp):.4f}   AUC(heavy, 1-p0) {roc_auc_score(heavy, 1 - probs[:, 0]):.4f}   "
          f"AP(heavy, 1-p0) {average_precision_score(heavy, 1 - probs[:, 0]):.4f}")
    print(f"  AUC(any rain>=5mm, 1-p0) {roc_auc_score((yt >= 1).astype(int), 1 - probs[:, 0]):.4f}")
    print(f"  mean predicted class probs {probs.mean(0).round(4).tolist()}   true dist {np.bincount(yt, minlength=4).tolist()}")


if __name__ == "__main__":
    main()
