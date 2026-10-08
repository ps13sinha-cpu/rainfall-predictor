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
    # State capitals / hubs added so every state and major UT carries a risk index
    {"code":"IN-UK-DD","name":"Dehradun","state":"Uttarakhand","lat":30.3165,"lon":78.0322,"pop":800000},
    {"code":"IN-UK-NA","name":"Nainital","state":"Uttarakhand","lat":29.3919,"lon":79.4542,"pop":955000},
    {"code":"IN-HP-SH","name":"Shimla","state":"Himachal Pradesh","lat":31.1048,"lon":77.1734,"pop":200000},
    {"code":"IN-JK-SR","name":"Srinagar","state":"Jammu and Kashmir","lat":34.0837,"lon":74.7973,"pop":1500000},
    {"code":"IN-LA-LE","name":"Leh","state":"Ladakh","lat":34.1526,"lon":77.5771,"pop":35000},
    {"code":"IN-AR-IT","name":"Itanagar","state":"Arunachal Pradesh","lat":27.0844,"lon":93.6053,"pop":60000},
    {"code":"IN-PY-PY","name":"Puducherry","state":"Puducherry","lat":11.9416,"lon":79.8083,"pop":950000},
    {"code":"IN-AN-PB","name":"Port Blair","state":"Andaman and Nicobar","lat":11.6234,"lon":92.7265,"pop":140000},
    {"code":"IN-HR-GU","name":"Gurugram","state":"Haryana","lat":28.4595,"lon":77.0266,"pop":1500000},
    {"code":"IN-TN-CB","name":"Cuddalore","state":"Tamil Nadu","lat":11.7480,"lon":79.7714,"pop":2600000},
    {"code":"IN-TN-TJ","name":"Thanjavur","state":"Tamil Nadu","lat":10.7870,"lon":79.1378,"pop":2400000},
    {"code":"IN-TN-NI","name":"Nilgiris (Ooty)","state":"Tamil Nadu","lat":11.4102,"lon":76.6950,"pop":735000},
]

# ── Reservoirs (Tamil Nadu + Kerala major reservoirs) ─────────────────────────
RESERVOIRS = [
    # Only reservoirs with a public feed or a real identity. Chennai lakes and Kerala dams are updated
    # daily by services/reservoir_live.py; the three below have no free daily feed yet (CWC weekly PDF only).
    {"code":"PO","name":"Poondi","lat":13.25,"lon":80.07,"cap":3231,"cur":772,"in":0,"out":15},
    {"code":"CH","name":"Cholavaram","lat":13.23,"lon":80.23,"cap":1081,"cur":128,"in":0,"out":0.2},
    {"code":"RD","name":"Puzhal (Red Hills)","lat":13.18,"lon":80.18,"cap":3300,"cur":1871,"in":6.4,"out":5.8},
    {"code":"CB","name":"Chembarambakkam","lat":13.00,"lon":80.06,"cap":3645,"cur":1254,"in":6.1,"out":4.7},
    {"code":"KT","name":"Kannankottai Thervoy Kandigai","lat":13.33,"lon":80.03,"cap":500,"cur":248,"in":0,"out":0.6},
    {"code":"VR","name":"Veeranam","lat":11.33,"lon":79.55,"cap":1465,"cur":543,"in":11.9,"out":8.9},
    {"code":"MT","name":"Mettur (Stanley)","lat":11.79,"lon":77.80,"cap":93470,"cur":60000,"in":120,"out":100},
    {"code":"BM","name":"Bhavanisagar","lat":11.46,"lon":77.13,"cap":32800,"cur":20000,"in":40,"out":35},
    {"code":"ML","name":"Mullaperiyar","lat":9.53,"lon":77.14,"cap":15661,"cur":9000,"in":30,"out":25},
    {"code":"ID","name":"Idukki","lat":9.85,"lon":76.98,"cap":51541,"cur":31074,"in":33,"out":55},
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
        if existing_r:
            RESERVOIRS_TO_ADD = []   # table already populated: leave it to the live sync
        else:
            RESERVOIRS_TO_ADD = RESERVOIRS
        existing_rc = {r.code for r in existing_r}
        added_r = 0
        for r in RESERVOIRS_TO_ADD:
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
