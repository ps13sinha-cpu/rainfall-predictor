"""Seed districts + reservoirs from the existing frontend data."""
import asyncio
from sqlalchemy import select
from app.database import async_session, init_db
from app.models import District, Reservoir


# ── Districts (from project/src/data.js RIIS.districts) ───────────────────────
DISTRICTS = [
    {"code":"IN-TN-CH","name":"Chennai","state":"Tamil Nadu","lat":13.0827,"lon":80.2707,"pop":11500000},
    {"code":"IN-TN-KA","name":"Kanchipuram","state":"Tamil Nadu","lat":12.8342,"lon":79.7036,"pop":1800000},
    {"code":"IN-TN-TN","name":"Thiruvananthapuram","state":"Kerala","lat":8.5241,"lon":76.9366,"pop":950000},
    {"code":"IN-KL-ER","name":"Ernakulam","state":"Kerala","lat":9.9816,"lon":76.3012,"pop":2100000},
    {"code":"IN-TG-HY","name":"Hyderabad","state":"Telangana","lat":17.3850,"lon":78.4867,"pop":10000000},
    {"code":"IN-KA-BL","name":"Bangalore Urban","state":"Karnataka","lat":12.9716,"lon":77.5946,"pop":12300000},
    {"code":"IN-KA-MY","name":"Mysuru","state":"Karnataka","lat":12.2958,"lon":76.6394,"pop":980000},
    {"code":"IN-MH-MU","name":"Mumbai","state":"Maharashtra","lat":19.0760,"lon":72.8777,"pop":21000000},
    {"code":"IN-MH-PU","name":"Pune","state":"Maharashtra","lat":18.5204,"lon":73.8567,"pop":7400000},
    {"code":"IN-GJ-AH","name":"Ahmedabad","state":"Gujarat","lat":23.0225,"lon":72.5714,"pop":8400000},
    {"code":"IN-RJ-JP","name":"Jaipur","state":"Rajasthan","lat":26.9124,"lon":75.7873,"pop":3900000},
    {"code":"IN-MP-BH","name":"Bhopal","state":"Madhya Pradesh","lat":23.2599,"lon":77.4126,"pop":2400000},
    {"code":"IN-UP-LK","name":"Lucknow","state":"Uttar Pradesh","lat":26.8467,"lon":80.9462,"pop":3500000},
    {"code":"IN-WB-KO","name":"Kolkata","state":"West Bengal","lat":22.5726,"lon":88.3639,"pop":15000000},
    {"code":"IN-DL-NW","name":"Delhi","state":"Delhi","lat":28.7041,"lon":77.1025,"pop":20000000},
    {"code":"IN-HR-CH","name":"Chandigarh","state":"Haryana","lat":30.7333,"lon":76.7794,"pop":1100000},
    {"code":"IN-PB-LO","name":"Ludhiana","state":"Punjab","lat":30.9010,"lon":75.8573,"pop":1600000},
    {"code":"IN-OR-BU","name":"Bhubaneswar","state":"Odisha","lat":20.2961,"lon":85.8245,"pop":1100000},
    {"code":"IN-WB-SI","name":"Siliguri","state":"West Bengal","lat":26.7271,"lon":88.3953,"pop":1100000},
    {"code":"IN-JH-RN","name":"Ranchi","state":"Jharkhand","lat":23.3441,"lon":85.3096,"pop":1200000},
    {"code":"IN-CG-RP","name":"Raipur","state":"Chhattisgarh","lat":21.2514,"lon":81.6296,"pop":1100000},
    {"code":"IN-GA-PN","name":"Panaji","state":"Goa","lat":15.4989,"lon":73.8278,"pop":120000},
    {"code":"IN-AS-GW","name":"Guwahati","state":"Assam","lat":26.1445,"lon":91.7362,"pop":1100000},
    {"code":"IN-MN-IM","name":"Imphal","state":"Manipur","lat":24.8170,"lon":93.9368,"pop":300000},
    {"code":"IN-MZ-AI","name":"Aizawl","state":"Mizoram","lat":23.7271,"lon":92.7176,"pop":300000},
    {"code":"IN-TR-AG","name":"Agartala","state":"Tripura","lat":23.8315,"lon":91.2868,"pop":500000},
    {"code":"IN-SK-GA","name":"Gangtok","state":"Sikkim","lat":27.3389,"lon":88.6065,"pop":100000},
    {"code":"IN-ML-SH","name":"Shillong","state":"Meghalaya","lat":25.5788,"lon":91.8933,"pop":350000},
    {"code":"IN-NL-KO","name":"Kohima","state":"Nagaland","lat":25.6586,"lon":94.1086,"pop":100000},
    {"code":"IN-BR-PT","name":"Patna","state":"Bihar","lat":25.6093,"lon":85.1376,"pop":2500000},
    {"code":"IN-AP-VJ","name":"Vijayawada","state":"Andhra Pradesh","lat":16.5062,"lon":80.6480,"pop":1500000},
    {"code":"IN-TN-MU","name":"Madurai","state":"Tamil Nadu","lat":9.9252,"lon":78.1198,"pop":1500000},
    {"code":"IN-TN-CO","name":"Coimbatore","state":"Tamil Nadu","lat":11.0168,"lon":76.9558,"pop":1700000},
    {"code":"IN-KA-HR","name":"Hubli-Dharwad","state":"Karnataka","lat":15.3647,"lon":75.1240,"pop":1100000},
    {"code":"IN-AS-DM","name":"Dibrugarh","state":"Assam","lat":27.4728,"lon":94.9120,"pop":200000},
    {"code":"IN-AS-KM","name":"Kamrup Metro","state":"Assam","lat":26.1700,"lon":91.7400,"pop":1200000},
]

# ── Reservoirs (Tamil Nadu + Kerala major reservoirs) ─────────────────────────
RESERVOIRS = [
    {"code":"PO","name":"POONDI","lat":13.25,"lon":80.07,"cap":3300,"cur":2475,"in":22,"out":15},
    {"code":"SH","name":"SHOLAVARAM","lat":13.30,"lon":80.12,"cap":1081,"cur":810,"in":12,"out":8},
    {"code":"RD","name":"RED HILLS","lat":13.18,"lon":80.18,"cap":2120,"cur":1590,"in":18,"out":12},
    {"code":"CH","name":"CHOLAVARAM","lat":13.23,"lon":80.23,"cap":1225,"cur":918,"in":10,"out":7},
    {"code":"KR","name":"KUNDRAH","lat":13.15,"lon":80.05,"cap":494,"cur":370,"in":6,"out":4},
    {"code":"AK","name":"ANNA KUDAI","lat":13.10,"lon":80.20,"cap":320,"cur":240,"in":5,"out":3},
    {"code":"MB","name":"MADURANTHAKAM","lat":12.50,"lon":79.85,"cap":1617,"cur":1213,"in":14,"out":10},
    {"code":"VB","name":"VHBN","lat":12.65,"lon":79.50,"cap":1460,"cur":1095,"in":12,"out":8},
    {"code":"PE","name":"PEUMBAKKAM","lat":12.70,"lon":79.60,"cap":370,"cur":278,"in":5,"out":3},
    {"code":"ER","name":"ERIE","lat":12.60,"lon":79.45,"cap":285,"cur":214,"in":4,"out":3},
    {"code":"TK","name":"THIRUKKAZHUKUNRAM","lat":12.55,"lon":79.55,"cap":225,"cur":169,"in":3,"out":2},
    {"code":"ML","name":"MULLAPERIYAR","lat":9.85,"lon":77.10,"cap":4440,"cur":3330,"in":45,"out":30},
    {"code":"ID","name":"IDUKKI","lat":9.85,"lon":76.98,"cap":1980,"cur":1485,"in":60,"out":40},
    {"code":"BM","name":"BHAVANI","lat":11.45,"lon":77.60,"cap":3280,"cur":2460,"in":28,"out":18},
    {"code":"HK","name":"HOSUR","lat":12.70,"lon":77.80,"cap":1005,"cur":754,"in":10,"out":7},
]


async def seed():
    await init_db()
    async with async_session() as db:
        # Seed districts
        existing = (await db.execute(select(District))).scalars().all()
        existing_codes = {d.code for d in existing}
        added = 0
        for d in DISTRICTS:
            if d["code"] not in existing_codes:
                db.add(District(**d))
                added += 1
        await db.commit()

        # Seed reservoirs
        existing_r = (await db.execute(select(Reservoir))).scalars().all()
        existing_rc = {r.code for r in existing_r}
        added_r = 0
        for r in RESERVOIRS:
            if r["code"] not in existing_rc:
                db.add(Reservoir(
                    code=r["code"], name=r["name"], lat=r["lat"], lon=r["lon"],
                    capacity_mcft=r["cap"], current_mcft=r["cur"],
                    inflow_cms=r["in"], outflow_cms=r["out"],
                    baseline_inflow=r["in"], baseline_outflow=r["out"],
                    overflow_prob=max(0, (r["cur"] / r["cap"] * 100 - 70)),
                ))
                added_r += 1
        await db.commit()

        print(f"[RIIS-Seed] Added {added} districts, {added_r} reservoirs")


if __name__ == "__main__":
    asyncio.run(seed())
