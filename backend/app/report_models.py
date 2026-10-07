"""Print a markdown summary of every trained model from ml_models/model_registry.json.

Usage:
    cd backend
    python -m app.report_models
"""
import os
import json

REGISTRY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ml_models", "model_registry.json")
NAMES = {
    "xgboost": "XGBoost", "random_forest": "Random Forest", "gradient_boost": "Gradient Boost",
    "ensemble_vote": "Ensemble Vote", "lstm_impact": "LSTM-Impact", "transformer": "Transformer",
    "convlstm": "ConvLSTM", "convgru": "ConvGRU",
}
ORDER = list(NAMES)


def fmt(v, d=3):
    return "-" if v is None else (f"{v:.{d}f}" if isinstance(v, float) else str(v))


def main():
    with open(REGISTRY) as f:
        reg = json.load(f)

    print("## Classification models (next-day for tabular, next-6h for sequence)\n")
    print("| Model | Family | Train rows | Test rows | Accuracy | Macro F1 | Heavy-rain AUC | Extreme recall | Train time |")
    print("|---|---|---|---|---|---|---|---|---|")
    for k in ORDER:
        e = reg.get(k)
        if not e or e["family"] == "spatial":
            continue
        m = e["metrics"]
        print(f"| {NAMES[k]} | {e['family']} | {e.get('train_rows', e.get('train_windows'))} | "
              f"{e.get('test_rows', e.get('test_windows'))} | {fmt(m['accuracy'])} | {fmt(m['macro_f1'])} | "
              f"{fmt(m.get('heavy_rain_auc'))} | {fmt(m['per_class']['extreme']['recall'])} | {e['train_seconds']:.0f}s |")

    if any(reg.get(k, {}).get("family") == "spatial" for k in ORDER):
        print("\n## Spatial nowcasting models (next-6h rain map, 11x11 grid at 0.25 deg)\n")
        print("| Model | RMSE mm/6h | MAE mm/6h | CSI 1mm | CSI 5mm | CSI 20mm | POD 5mm | Pixel class acc | Train time |")
        print("|---|---|---|---|---|---|---|---|---|")
        for k in ORDER:
            e = reg.get(k)
            if not e or e["family"] != "spatial":
                continue
            for label, m in ((NAMES[k], e["metrics"]), (f"{NAMES[k]} persistence baseline", e["persistence_baseline"])):
                t = f"{e['train_seconds']:.0f}s" if "baseline" not in label else "-"
                print(f"| {label} | {fmt(m['rmse_mm'])} | {fmt(m['mae_mm'])} | {fmt(m['csi_1mm'])} | {fmt(m['csi_5mm'])} | "
                      f"{fmt(m['csi_20mm'])} | {fmt(m['pod_5mm'])} | {fmt(m['pixel_class_accuracy'])} | {t} |")

    print("\n## Per-class F1 (classification models)\n")
    print("| Model | safe | mod | high | extreme |")
    print("|---|---|---|---|---|")
    for k in ORDER:
        e = reg.get(k)
        if not e or e["family"] == "spatial":
            continue
        pc = e["metrics"]["per_class"]
        print(f"| {NAMES[k]} | {fmt(pc['safe']['f1'])} | {fmt(pc['mod']['f1'])} | {fmt(pc['high']['f1'])} | {fmt(pc['extreme']['f1'])} |")

    if "xgboost" in reg and "feature_importance" in reg["xgboost"]:
        top = list(reg["xgboost"]["feature_importance"].items())[:8]
        print("\nTop XGBoost features: " + ", ".join(f"{k} ({v:.3f})" for k, v in top))


if __name__ == "__main__":
    main()
