"""
RIIS — Road flood-risk model: sample generation + training.

Generates (segment, scenario) samples for every road site by running the DEM
ponding scorer over a scenario grid, ingests community road reports as real
labels, and trains the XGBoost surrogate (services/roads_ml.py).

The simulation is the teacher for the initial model: label_source = "sim".
Reports give label_source = "report" and are weighted 5x.

Usage:
    cd backend
    python -m app.train_roads            # generate + train
    python -m app.train_roads generate
    python -m app.train_roads train
"""
import sys
import asyncio
import time
from datetime import datetime

from sqlalchemy import select, delete

SEED_SITES = [  # name, lat, lon
    ("Potheri", 12.823, 80.044), ("Velachery", 12.979, 80.221), ("T Nagar", 13.040, 80.234),
    ("Tambaram", 12.925, 80.127), ("Madurai centre", 9.925, 78.120), ("Coimbatore centre", 11.017, 76.956),
]
RAIN_GRID = [20, 40, 60, 80, 100, 150, 200]
DUR_GRID = [1, 3, 6, 12]


async def generate(db, sites=SEED_SITES) -> dict:
    from app.models import RoadRiskSample, RoadReport, RoadSegment
    from app.services import roads as R
    from app.services.roads_ml import segment_features, site_context, LABELS
    t0 = time.time()
    summary = {"sites": [], "samples": 0, "report_samples": 0}
    await db.execute(delete(RoadRiskSample).where(RoadRiskSample.label_source == "sim"))
    await db.commit()
    for name, lat, lon in sites:
        t = time.time()
        try:
            b = await R.ensure_site(db, lat, lon)
        except Exception as e:
            summary["sites"].append({"name": name, "error": str(e)[:120]})
            continue
        ctx = site_context(b)
        n = 0
        for mm in RAIN_GRID:
            for dur in DUR_GRID:
                st = await R.score_segments(db, b, mm, dur)
                key = R.scenario_key(mm, dur)
                scn = {"rainfall_mm": mm, "duration_h": dur}
                rows = [RoadRiskSample(segment_id=sid, scenario_key=key, features_json=segment_features(seg, scn, ctx),
                                       label=LABELS[st[sid]["status"]], label_source="sim")
                        for sid, seg in b["segments"].items() if sid in st]
                db.add_all(rows)
                n += len(rows)
            await db.commit()
        summary["sites"].append({"name": name, "site_id": b["site"]["id"], "segments": len(b["segments"]), "samples": n,
                                 "seconds": round(time.time() - t, 1)})
        summary["samples"] += n
        print(f"[train_roads] {name}: {len(b['segments'])} segments x 28 scenarios = {n} samples ({time.time()-t:.0f}s)")

    # community reports as observed labels
    await db.execute(delete(RoadRiskSample).where(RoadRiskSample.label_source == "report"))
    reports = (await db.execute(select(RoadReport).where(RoadReport.segment_id.isnot(None)))).scalars().all()
    for rep in reports:
        seg = (await db.execute(select(RoadSegment).where(RoadSegment.id == rep.segment_id))).scalar_one_or_none()
        if seg is None:
            continue
        b = R._sites.get(seg.site_id)
        if b is None:
            continue
        parts = (rep.scenario_key or "60|3|20").split("|")
        scn = {"rainfall_mm": float(parts[0]), "duration_h": float(parts[1])}
        sd = {c.name: getattr(seg, c.name) for c in RoadSegment.__table__.columns}
        db.add(RoadRiskSample(segment_id=seg.id, scenario_key=rep.scenario_key or R.scenario_key(60, 3),
                              features_json=segment_features(sd, scn, site_context(b)),
                              label={"open": 0, "caution": 1, "closed": 2}[rep.status], label_source="report"))
        summary["report_samples"] += 1
    await db.commit()
    summary["seconds"] = round(time.time() - t0, 1)
    return summary


async def train_from_db(db) -> dict:
    from app.models import RoadRiskSample, RoadSegment
    from app.services.roads_ml import train
    rows = (await db.execute(select(RoadRiskSample, RoadSegment.site_id).join(RoadSegment, RoadSegment.id == RoadRiskSample.segment_id))).all()
    samples = [{"features": s.features_json, "label": s.label, "label_source": s.label_source, "site_id": site_id} for s, site_id in rows]
    if len(samples) < 50:
        return {"status": "insufficient_data", "samples": len(samples)}
    print(f"[train_roads] training on {len(samples)} samples from {len({s['site_id'] for s in samples})} sites")
    m = train(samples, held_out_site=None)
    print(f"[train_roads] held-out site {m.get('held_out_site')}: macro F1 {m.get('macro_f1')} acc {m.get('accuracy')} recall {m.get('per_class_recall')}")
    return m


async def run_all() -> dict:
    from app.database import init_db, async_session
    await init_db()
    async with async_session() as db:
        gen = await generate(db)
        metrics = await train_from_db(db)
    return {"generation": gen, "metrics": metrics}


def main():
    from app.database import init_db, async_session
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    async def _run():
        await init_db()
        async with async_session() as db:
            if mode in ("generate", "all"):
                print(await generate(db))
            if mode in ("train", "all"):
                print(await train_from_db(db))
    if mode not in ("generate", "train", "all"):
        print("Usage: python -m app.train_roads [generate|train|all]")
        return
    asyncio.run(_run())


if __name__ == "__main__":
    main()
