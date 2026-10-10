"""Write app/ml_models/feature_medians.json from the historical_weather table.

    cd backend && python -m app.build_feature_medians

The medians are a safety net: every current tabular model (XGBoost, RandomForest,
HistGradientBoosting) predicts on NaN directly, so ml.predict passes missing inputs
through as NaN and only falls back to these medians when a model raises on NaN.
Rerun after ingesting new history or retraining, so the fallback stays on the same
distribution the models saw.
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from app.services.features import compute_feature_medians  # noqa: E402

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "riis.db")
OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ml_models", "feature_medians.json")


def main():
    out = compute_feature_medians(DB_PATH)
    out["computed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out["source"] = "historical_weather (+ historical_hourly aggregates) via features.build_training_frame"
    tmp = OUT_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(out, f, indent=2)
    os.replace(tmp, OUT_PATH)
    print(f"wrote {OUT_PATH} from {out['rows']} training rows")
    for k, v in out["medians"].items():
        print(f"  {k:15s} {v!s:>12}  non-null {out['non_null_share'][k]:.0%}")


if __name__ == "__main__":
    main()
