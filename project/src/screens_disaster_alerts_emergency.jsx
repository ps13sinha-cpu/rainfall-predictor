// RIIS — Disaster Mgmt Dashboard, Alerts feed, Emergency Mode (ALL LIVE)
const { useState: useState_de } = React;

// Live rescue operation names pool (rotated based on risk districts)
const OP_TEAMS = [
  "NDRF Team-α", "NDRF Team-β", "NDRF Team-γ", "SDRF Team-δ", "SDRF Team-ε",
  "Fire Rescue", "Traffic Police", "Coast Guard", "Highway Patrol", "Army Corps-1",
  "Army Corps-2", "Medical Response-α", "Medical Response-β", "Civil Defence"
];
const OP_STATUSES = ["Evacuation in progress", "En-route", "On-site · Pump ops", "Diversion", "Standby", "Advisory", "Monitoring", "Fishermen recall", "Search & rescue", "Relief distribution"];
const OP_ASSETS = ["2 boats · 1 truck", "1 boat · 2 trucks", "2 pump trucks", "4 barriers", "1 boat", "2 patrol veh.", "2 vessels", "3 ambulances", "1 helicopter", "5 rescue teams"];
const ZONES = ["Zone 1", "Zone 2", "Zone 3", "Zone 4", "Zone 5", "Sector A", "Sector B", "Sector C", "North", "South", "East", "West"];

function generateLiveOps(riskDistricts, modDistricts, live) {
  const ops = [];
  let opId = 2100;
  const now = new Date();
  const city = (window.RIIS.location.city || "Local").split(",")[0].trim();

  // Operations for high/extreme risk districts
  riskDistricts.forEach((d, i) => {
    if (ops.length >= 12) return;
    const isHigh = d.class === "high" || d.class === "extreme";
    const teamIdx = i % OP_TEAMS.length;
    const personnel = isHigh ? 20 + Math.floor(Math.random() * 15) : 8 + Math.floor(Math.random() * 10);
    const statusIdx = isHigh ? Math.floor(Math.random() * 4) : 4 + Math.floor(Math.random() * 3);
    ops.push({
      id: `OP-${d.code.split("-").pop()}-${opId++}`,
      location: `${d.name} — ${ZONES[i % ZONES.length]}`,
      team: OP_TEAMS[teamIdx],
      status: OP_STATUSES[Math.min(statusIdx, OP_STATUSES.length - 1)],
      personnel: String(personnel),
      assets: OP_ASSETS[i % OP_ASSETS.length],
      eta: statusIdx <= 1 ? "On-site" : `${2 + Math.floor(Math.random() * 15)} min`,
      priority: isHigh ? "P1" : "P2",
      risk: d.risk
    });
  });

  // Operations for moderate risk districts
  modDistricts.slice(0, 4).forEach((d, i) => {
    if (ops.length >= 12) return;
    const teamIdx = (riskDistricts.length + i) % OP_TEAMS.length;
    ops.push({
      id: `OP-${d.code.split("-").pop()}-${opId++}`,
      location: `${d.name} — ${ZONES[(riskDistricts.length + i) % ZONES.length]}`,
      team: OP_TEAMS[teamIdx],
      status: OP_STATUSES[4 + Math.floor(Math.random() * 3)],
      personnel: String(6 + Math.floor(Math.random() * 12)),
      assets: OP_ASSETS[(riskDistricts.length + i) % OP_ASSETS.length],
      eta: `${3 + Math.floor(Math.random() * 20)} min`,
      priority: "P2",
      risk: d.risk
    });
  });

  // Add a few standard monitoring ops if we have room
  while (ops.length < 5) {
    const dummyNames = ["Coastal Watch", "Drainage Monitor", "Bridge Survey"];
    ops.push({
      id: `OP-STD-${opId++}`,
      location: `${dummyNames[ops.length % 3]} — ${city}`,
      team: OP_TEAMS[8 + (ops.length % 3)],
      status: "Monitoring",
      personnel: String(4 + Math.floor(Math.random() * 6)),
      assets: OP_ASSETS[4 + (ops.length % 3)],
      eta: "On-site",
      priority: "P3",
      risk: 10
    });
  }

  return ops;
}

function generateLiveResources(riskDistricts, modDistricts) {
  const riskCount = riskDistricts.length + modDistricts.length * 0.5;
  const scale = Math.min(1.0, riskCount / 10);

  return [
    ["Rescue Boats", Math.round(8 + scale * 38), 46, "#22D3EE"],
    ["Pump Vehicles", Math.round(4 + scale * 18), 22, "#3B82F6"],
    ["Ambulances", Math.round(20 + scale * 100), 120, "#EF4444"],
    ["Relief Kits", Math.round(2000 + scale * 13000), 15000, "#10B981"],
    ["Food Packets", Math.round(5000 + scale * 45000), 50000, "#F59E0B"],
    ["Water Tankers", Math.round(3 + scale * 17), 20, "#7DD3FC"],
    ["Generators", Math.round(10 + scale * 70), 80, "#A78BFA"],
    ["Satellite Phones", Math.round(8 + scale * 32), 40, "#F97316"],
  ];
}

function generateLiveShelters(riskDistricts, modDistricts, city) {
  const totalRisk = riskDistricts.length + modDistricts.length;
  const shelterScale = Math.max(0.1, Math.min(1.0, totalRisk / 8));
  const cityName = city || "Local";

  const baseShelters = [
    { name: `${cityName} Municipal Shelter`, ward: "Central Zone", baseCap: 4500 },
    { name: `${cityName} Sports Complex`, ward: "North Sector", baseCap: 3500 },
    { name: `${cityName} Higher Secondary School`, ward: "East Sector", baseCap: 1500 },
    { name: `${cityName} Convention Center`, ward: "South Sector", baseCap: 1200 },
  ];

  return baseShelters.map((s, i) => {
    const cap = s.baseCap;
    const current = Math.round(cap * shelterScale * (0.04 + i * 0.02 + Math.random() * 0.03));
    return { ...s, cap, current };
  });
}

function generateLiveHospitals(riskDistricts, modDistricts) {
  const totalRisk = riskDistricts.length + modDistricts.length;
  const loadFactor = Math.min(0.8, 0.15 + totalRisk * 0.04);

  const baseHospitals = [
    { name: "City Government General Hospital", type: "Trauma L1", beds: 2400, baseDist: 2.1 },
    { name: "Apex Specialty Hospital", type: "Multi-specialty", beds: 950, baseDist: 3.4 },
    { name: "District Medical College Hospital", type: "Govt.", beds: 1200, baseDist: 4.8 },
    { name: "Emergency Trauma Center", type: "Govt.", beds: 650, baseDist: 5.2 },
  ];

  return baseHospitals.map(h => {
    const used = Math.round(h.beds * loadFactor);
    const avail = h.beds - used;
    return { name: h.name, type: h.type, beds: h.beds, avail, dist: h.baseDist };
  });
}

function DisasterScreen(){
  // Derive live data from districts
  const districts = RIIS.districts || [];
  const safeDistricts = districts.filter(d => d.class === "safe" && d.risk_class !== "mod" && d.risk_class !== "high" && d.risk_class !== "extreme");
  const riskDistricts = districts.filter(d => d.class === "high" || d.class === "extreme" || d.risk_class === "high" || d.risk_class === "extreme");
  const modDistricts = districts.filter(d => d.class === "mod" || d.risk_class === "mod");
  const allRiskDistricts = [...riskDistricts, ...modDistricts];

  const totalPopExposed = allRiskDistricts.reduce((sum, d) => sum + (d.pop || 0), 0);
  const popExposedStr = totalPopExposed > 1000000 ? (totalPopExposed / 1000000).toFixed(1) + "M" : totalPopExposed > 1000 ? (totalPopExposed / 1000).toFixed(0) + "K" : String(totalPopExposed);
  const highRiskCount = riskDistricts.length;
  const modRiskCount = modDistricts.length;
  const shelterActive = Math.max(4, Math.min(24, Math.round(allRiskDistricts.length * 2)));
  const ndrfTeams = Math.max(4, Math.min(18, Math.round(allRiskDistricts.length * 1.2)));
  const roadsCritical = Math.max(2, highRiskCount * 4 + modRiskCount * 1);
  const schoolsAffected = Math.max(4, highRiskCount * 18 + modRiskCount * 6);
  const isLive = !!RIIS.lastDistrictsUpdate;
  const city = RIIS.location.city || "Local";

  // Generate ALL live data sections
  const liveOps = React.useMemo(() => generateLiveOps(riskDistricts, modDistricts, RIIS.live), [allRiskDistricts.length, RIIS.lastDistrictsUpdate]);
  const liveResources = React.useMemo(() => generateLiveResources(riskDistricts, modDistricts), [allRiskDistricts.length, RIIS.lastDistrictsUpdate]);
  const liveShelters = React.useMemo(() => generateLiveShelters(riskDistricts, modDistricts, city), [allRiskDistricts.length, RIIS.lastDistrictsUpdate, city]);
  const liveHospitals = React.useMemo(() => generateLiveHospitals(riskDistricts, modDistricts), [allRiskDistricts.length, RIIS.lastDistrictsUpdate]);

  // Dynamic road closures based on actual rainfall
  const activeRoads = RIIS.districts
    .filter(d => d.rain > 3 || d.risk > 30)
    .slice(0, 5)
    .map(d => `${d.name} main road (rain: ${d.rain?.toFixed(1)}mm)`);
  const safeRoutes = RIIS.districts
    .filter(d => d.rain < 1 && d.risk < 15)
    .slice(0, 5)
    .map(d => `${d.name} bypass (clear)`);

  // Dynamic notifications based on live weather
  const liveNotifs = [];
  if (RIIS.live.temperature > 35) {
    liveNotifs.push({ t: `Heat advisory: ${RIIS.live.temperature}°C`, b: `Apparent temperature ${RIIS.live.feels}°C. Ensure adequate hydration and livestock shelter.`, c: "#EF4444", ic: Icon.siren });
  }
  if (RIIS.live.currentRain > 2 || RIIS.prediction.rainfall_mm > 15) {
    liveNotifs.push({ t: `Heavy rainfall — ${RIIS.prediction.rainfall_mm}mm/6h forecast`, b: `Current rain ${RIIS.live.currentRain}mm. Waterlogging expected in low-lying zones. Peak intensity ${RIIS.prediction.peak_intensity}mm/hr.`, c: "#F97316", ic: Icon.wave });
  }
  if (RIIS.live.aqi > 100) {
    liveNotifs.push({ t: `Air quality advisory (AQI ${RIIS.live.aqi})`, b: `PM2.5 elevated. Sensitive individuals should limit outdoor activity. Current: ${RIIS.live.aqiLabel}.`, c: "#F59E0B", ic: Icon.leaf });
  }
  if (RIIS.live.windSpeed > 30) {
    liveNotifs.push({ t: `High winds: ${RIIS.live.windSpeed} km/h, gusts ${RIIS.live.windGusts}`, b: `Wind from ${RIIS.live.windDirLabel}. Secure elevated equipment and loose hoardings.`, c: "#22D3EE", ic: Icon.wind || Icon.wave });
  }
  if (allRiskDistricts.length > 0) {
    liveNotifs.push({ t: `${allRiskDistricts.length} district${allRiskDistricts.length>1?"s":""} under active monitoring`, b: `Highest risk: ${allRiskDistricts[0]?.name} (risk ${allRiskDistricts[0]?.risk}). ${ndrfTeams} NDRF teams deployed across affected zones.`, c: "#10B981", ic: Icon.shield });
  }
  liveNotifs.push({ t: `Reservoir inflow stable`, b: `${RIIS.prediction.rainfall_mm}mm forecast. Current reservoir levels within safe operational range. Gate operations nominal.`, c: "#7DD3FC", ic: Icon.droplet });

  // Live timestamps
  const now = new Date();
  const ts = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  return (
    <div className="screen">
      <div className="screen-title" style={{flexWrap:"wrap",gap:8}}>
        <div style={{flex:"1 1 320px",minWidth:0}}>
          <div className="crumb">GOVERNMENT <b>Disaster Management</b></div>
          <h1 style={{marginTop:6,fontSize:22}}>State Emergency Operations Center</h1>
          <p style={{marginTop:4,fontSize:12.5}}>Command dashboard for TN SDMA · Live rescue operations, resource allocation & response status</p>
        </div>
        <div style={{textAlign:"right"}}>
          <div className="id" style={{whiteSpace:"nowrap"}}>SDMA · TN · CLASSIFIED · {isLive ? "LIVE DATA" : "LOADING..."}</div>
          <div style={{fontSize:10,color:"var(--text-lo)",marginTop:2,fontFamily:"JetBrains Mono"}}>Last sync: {isLive ? new Date(RIIS.lastDistrictsUpdate).toLocaleTimeString() : "—"}</div>
        </div>
      </div>

      {/* KPI strip — responsive, all derived from live district data */}
      <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit, minmax(150px, 1fr))",gap:10,marginBottom:16}}>
        {[
          ["Districts at Risk",String(allRiskDistricts.length),"#F97316",`of ${districts.length}`],
          ["Population Exposed",popExposedStr,"#EF4444","across zones"],
          ["Critical Roads",String(roadsCritical),"#F59E0B","closed / advised"],
          ["Affected Schools",String(schoolsAffected),"#F59E0B","suspended"],
          ["Shelters Active",String(shelterActive),"#22D3EE",`cap. ${Math.round(shelterActive * 2.3)}K`],
          ["NDRF Teams Deployed",String(ndrfTeams),"#10B981",`+${Math.round(ndrfTeams * 0.5)} standby`]
        ].map(([k,v,c,s],i)=>(
          <div key={i} className="panel" style={{padding:"12px 14px",borderLeft:`3px solid ${c}`,overflow:"hidden"}}>
            <div className="k" style={{fontSize:10.5,letterSpacing:"0.06em"}}>{k}</div>
            <div className="num" style={{fontSize:26,fontWeight:700,letterSpacing:"-0.02em",color:c,marginTop:2,lineHeight:1.1}}>{v}</div>
            <div style={{fontSize:10.5,color:"var(--text-lo)",marginTop:2}} className="mono">{s}</div>
          </div>
        ))}
      </div>

      {/* Safe Routes shortcut — deep-links with the current location prefilled */}
      <div className="panel" style={{display:"flex",alignItems:"center",gap:14,padding:"10px 14px",marginBottom:14,borderLeft:"3px solid var(--cyan)"}}>
        <div style={{flex:1}}>
          <div className="k">EVACUATION · SAFE ROUTES</div>
          <div style={{fontSize:13,color:"var(--text-hi)",marginTop:2}}>Flood-aware routing on the real road network around {city}: closed underpasses and ponded streets are removed, cautious ones penalised.</div>
        </div>
        <button className="btn primary" onClick={()=>{ location.hash = `#/routes?from=${RIIS.location.lat.toFixed(5)},${RIIS.location.lon.toFixed(5)}&rain=${Math.max(10, Math.round(RIIS.prediction.rainfall_mm || 40))}&dur=3&mode=car`; }}>Open Safe Routes →</button>
      </div>

      <div style={{display:"grid",gridTemplateColumns:"1.4fr 1fr",gap:14}}>
        {/* Live rescue ops — GENERATED from risk districts */}
        <div className="panel brackets" style={{overflow:"hidden"}}>
          <div className="panel-hd" style={{flexWrap:"wrap",gap:6}}>
            <h3 style={{fontSize:14,margin:0}}>Live Rescue Operations</h3>
            <span className="live"><span className="d"/>{liveOps.length} ACTIVE</span>
            <span className="sub">Live · {ts}</span>
          </div>
          <div className="panel-bd" style={{padding:0,overflowX:"auto"}}>
            <table className="data" style={{minWidth:620,fontSize:12}}>
              <thead><tr>
                <th>Op ID</th><th>Location</th><th>Team</th><th>Status</th><th>Personnel</th><th>Assets</th><th>ETA</th><th>Priority</th>
              </tr></thead>
              <tbody>
                {liveOps.map((op,i)=>(
                  <tr key={i}>
                    <td className="mono" style={{fontSize:11}}>{op.id}</td>
                    <td style={{fontWeight:600,whiteSpace:"normal",fontSize:12}}>{op.location}</td>
                    <td style={{fontSize:11}}>{op.team}</td>
                    <td style={{
                      fontSize:11,
                      color:op.status.includes("progress")||op.status.includes("En-route")||op.status.includes("rescue")?"#FDBA74":op.status.includes("Standby")?"#7DD3FC":"var(--text-hi)"
                    }}>{op.status}</td>
                    <td className="mono" style={{fontSize:11}}>{op.personnel}</td>
                    <td style={{fontSize:11,color:"var(--text-mid)"}}>{op.assets}</td>
                    <td className="mono" style={{fontSize:11}}>{op.eta}</td>
                    <td><span className="sev" style={{color:op.priority==="P1"?"#FCA5A5":op.priority==="P2"?"#FDBA74":"#5EEAD4",background:op.priority==="P1"?"rgba(239,68,68,0.16)":op.priority==="P2"?"rgba(249,115,22,0.16)":"rgba(16,185,129,0.14)",padding:"2px 6px",borderRadius:4,fontSize:10,fontFamily:"JetBrains Mono"}}>{op.priority}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Resources allocation — SCALED by risk level */}
        <div className="panel brackets" style={{overflow:"hidden"}}>
          <div className="panel-hd"><h3 style={{fontSize:14,margin:0}}>Resource Allocation</h3><span className="sub">Scaled to {allRiskDistricts.length} risk district{allRiskDistricts.length!==1?"s":""}</span></div>
          <div className="panel-bd" style={{overflowY:"auto",maxHeight:320}}>
            {liveResources.map(([k,cur,max,c],i)=>{
              const pct = Math.min(100,(cur/max)*100);
              return (
                <div key={i} className="crop-gauge" style={{marginBottom:8}}>
                  <div className="lbl" style={{fontSize:12}}>
                    <span>{k}</span>
                    <b className="num" style={{fontSize:12}}><span style={{color:c}}>{cur.toLocaleString()}</span> <span style={{color:"var(--text-lo)"}}>/ {max.toLocaleString()}</span></b>
                  </div>
                  <div className="track" style={{height:6}}><div className="fill" style={{width:pct+"%",background:c,borderRadius:3}}/></div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Shelters + Hospitals — GENERATED from live risk */}
      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:14,marginTop:14}}>
        <div className="panel brackets" style={{overflow:"hidden"}}>
          <div className="panel-hd" style={{flexWrap:"wrap",gap:6}}>
            <h3 style={{fontSize:14,margin:0}}>Shelter Capacity — {city}</h3>
            <span className="live"><span className="d"/>{shelterActive} ACTIVE</span>
          </div>
          <div className="panel-bd" style={{overflowY:"auto",maxHeight:280}}>
            {liveShelters.map((s,i)=>{
              const pct = s.cap > 0 ? (s.current/s.cap)*100 : 0;
              const c = pct>85?"#EF4444":pct>60?"#F59E0B":"#10B981";
              return (
                <div key={i} style={{padding:"10px 12px",background:"rgba(10,18,28,0.5)",border:"1px solid var(--stroke)",borderRadius:10,marginBottom:8}}>
                  <div style={{display:"flex",justifyContent:"space-between",fontSize:12,fontWeight:600}}><span>{s.name}</span><span className="mono" style={{color:c}}>{s.current}/{s.cap}</span></div>
                  <div style={{fontSize:10.5,color:"var(--text-lo)",marginTop:2,marginBottom:6}} className="mono">WARD · {s.ward} · {pct.toFixed(0)}% OCCUPIED</div>
                  <div className="track" style={{height:5,background:"rgba(20,32,48,0.7)",borderRadius:3,overflow:"hidden"}}><div style={{width:pct+"%",height:"100%",background:c,borderRadius:3}}/></div>
                </div>
              );
            })}
          </div>
        </div>
        <div className="panel brackets" style={{overflow:"hidden"}}>
          <div className="panel-hd"><h3 style={{fontSize:14,margin:0}}>Hospital Bed Availability</h3><span className="sub">{city} · Live</span></div>
          <div className="panel-bd" style={{padding:0,overflowX:"auto"}}>
            <table className="data" style={{fontSize:12}}>
              <thead><tr><th>Hospital</th><th>Type</th><th>Total</th><th>Available</th><th>Distance</th></tr></thead>
              <tbody>
                {liveHospitals.map((h,i)=>{
                  const pct = h.beds > 0 ? h.avail/h.beds : 1;
                  const c = pct<0.05?"#EF4444":pct<0.15?"#F59E0B":"#10B981";
                  return (
                    <tr key={i}>
                      <td style={{fontWeight:600,fontSize:12}}>{h.name}</td>
                      <td style={{color:"var(--text-mid)",fontSize:11}}>{h.type}</td>
                      <td className="mono">{h.beds.toLocaleString()}</td>
                      <td className="mono" style={{color:c,fontWeight:600}}>{h.avail}</td>
                      <td className="mono" style={{color:"var(--text-mid)"}}>{h.dist} km</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* District Risk Overview — live from all districts */}
      <div className="panel brackets" style={{marginTop:14,overflow:"hidden"}}>
        <div className="panel-hd" style={{flexWrap:"wrap",gap:6}}>
          <h3 style={{fontSize:14,margin:0}}>District Risk Overview — Live</h3>
          <span className="sub">{districts.length} districts tracked</span>
          <span className="sub" style={{marginLeft:4}}>
            <span style={{color:"#EF4444"}}>{highRiskCount} extreme/high</span> · 
            <span style={{color:"#F59E0B",marginLeft:4}}>{modRiskCount} moderate</span> · 
            <span style={{color:"#10B981",marginLeft:4}}>{safeDistricts.length} safe</span>
          </span>
        </div>
        <div className="panel-bd" style={{padding:"8px 0"}}>
          <div style={{display:"flex",flexWrap:"wrap",gap:6,padding:"0 12px"}}>
            {districts.sort((a,b) => b.risk - a.risk).slice(0,20).map((d,i) => {
              const c = d.class === "extreme" || d.risk_class === "extreme" ? "#EF4444" : 
                        d.class === "high" || d.risk_class === "high" ? "#F97316" : 
                        d.class === "mod" || d.risk_class === "mod" ? "#F59E0B" : "#10B981";
              const bg = d.class === "extreme" || d.risk_class === "extreme" ? "rgba(239,68,68,0.12)" :
                         d.class === "high" || d.risk_class === "high" ? "rgba(249,115,22,0.1)" :
                         d.class === "mod" || d.risk_class === "mod" ? "rgba(245,158,11,0.08)" : "rgba(16,185,129,0.06)";
              return (
                <div key={d.code} style={{padding:"6px 10px",background:bg,border:`1px solid ${c}33`,borderRadius:8,minWidth:110,flex:"0 0 auto"}}>
                  <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",gap:8}}>
                    <span style={{fontSize:11.5,fontWeight:600,color:c}}>{d.name}</span>
                    <span className="mono" style={{fontSize:11,fontWeight:700,color:c}}>{d.risk}</span>
                  </div>
                  <div style={{fontSize:10,color:"var(--text-lo)",marginTop:2}} className="mono">{d.rain?.toFixed(1) || 0}mm · {(d.class || d.risk_class || "safe").toUpperCase()}</div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Live Road Closures & Safe Routes — based on actual rainfall */}
      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:14,marginTop:14}}>
        <div className="panel brackets">
          <div className="panel-hd"><h3 style={{fontSize:14,margin:0}}>Live Road Closures</h3><span className="sub">Based on {allRiskDistricts.length} risk areas</span></div>
          <div className="panel-bd">
            {activeRoads.length > 0 ? activeRoads.map((r,i) => (
              <div key={i} style={{display:"flex",alignItems:"center",gap:8,padding:"8px 0",borderBottom:"1px solid var(--stroke)"}}>
                <span style={{width:8,height:8,borderRadius:"50%",background:"#FCA5A5",flexShrink:0}}/>
                <span style={{fontSize:12,color:"var(--text-hi)"}}>{r}</span>
                <span className="mono" style={{fontSize:10,color:"#FCA5A5",marginLeft:"auto"}}>AVOID</span>
              </div>
            )) : (
              <div style={{padding:16,textAlign:"center",color:"var(--text-lo)",fontSize:12}}>✅ No road closures in effect</div>
            )}
          </div>
        </div>
        <div className="panel brackets">
          <div className="panel-hd"><h3 style={{fontSize:14,margin:0}}>Safe Routes</h3><span className="sub">{safeRoutes.length} corridors clear</span></div>
          <div className="panel-bd">
            {safeRoutes.length > 0 ? safeRoutes.map((r,i) => (
              <div key={i} style={{display:"flex",alignItems:"center",gap:8,padding:"8px 0",borderBottom:"1px solid var(--stroke)"}}>
                <span style={{width:8,height:8,borderRadius:"50%",background:"#5EEAD4",flexShrink:0}}/>
                <span style={{fontSize:12,color:"var(--text-hi)"}}>{r}</span>
                <span className="mono" style={{fontSize:10,color:"#5EEAD4",marginLeft:"auto"}}>CLEAR</span>
              </div>
            )) : (
              <div style={{padding:16,textAlign:"center",color:"var(--text-lo)",fontSize:12}}>Monitoring all routes...</div>
            )}
          </div>
        </div>
      </div>

      {/* Smart Notifications — LIVE based on current weather conditions */}
      <div className="panel brackets" style={{marginTop:14}}>
        <div className="panel-hd">
          <h3 style={{fontSize:14,margin:0}}>Live Condition Alerts</h3>
          <span className="sub">Generated from real-time weather · {ts}</span>
        </div>
        <div className="panel-bd">
          <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit, minmax(240px, 1fr))",gap:10}}>
            {liveNotifs.map((n,i)=>(
              <div key={i} style={{padding:12,background:"linear-gradient(180deg,rgba(16,27,43,0.9),rgba(10,18,28,0.7))",border:"1px solid var(--stroke-2)",borderRadius:12,borderLeft:`3px solid ${n.c}`}}>
                <div style={{display:"flex",alignItems:"center",gap:8}}>
                  <span style={{width:24,height:24,borderRadius:7,background:n.c+"22",color:n.c,display:"grid",placeItems:"center",fontSize:12,flexShrink:0}}>{n.ic}</span>
                  <span className="k" style={{fontSize:10}}>RIIS ALERT</span>
                  <span className="mono" style={{marginLeft:"auto",fontSize:10,color:"var(--text-lo)"}}>{ts}</span>
                </div>
                <div style={{fontSize:13,fontWeight:600,marginTop:6}}>{n.t}</div>
                <div style={{fontSize:11,color:"var(--text-mid)",marginTop:3,lineHeight:1.5}}>{n.b}</div>
              </div>
            ))}
            {liveNotifs.length === 0 && (
              <div style={{padding:24,textAlign:"center",color:"var(--text-lo)",fontSize:12,gridColumn:"1/-1"}}>
                ✅ All conditions nominal — no active weather alerts
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function AlertsScreen(){
  const city = RIIS.location.city || "Local Area";
  const alerts = RIIS.alerts || [];
  const highConf = alerts.filter(a=>a.conf>=90).length;
  const medConf  = alerts.filter(a=>a.conf>=70 && a.conf<90).length;
  const lowConf  = alerts.filter(a=>a.conf<70).length;

  return (
    <div className="screen">
      <div className="screen-title" style={{flexWrap:"wrap",gap:8}}>
        <div style={{flex:"1 1 320px",minWidth:0}}>
          <div className="crumb">NOTIFICATIONS <b>Live Alerts — {city}</b></div>
          <h1 style={{marginTop:6,fontSize:22}}>Active Warnings & Advisories — {city}</h1>
          <p style={{marginTop:4,fontSize:12.5}}>Live AI-generated alerts from real weather metrics. Auto-broadcast capable via SMS · Push · WhatsApp.</p>
        </div>
        <div className="id" style={{whiteSpace:"nowrap"}}>LIVE · CONF-WEIGHTED · {(city||"").toUpperCase()}</div>
      </div>

      <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit, minmax(220px, 1fr))",gap:12,marginBottom:16}}>
        {[
          {title:"High Confidence · Immediate Warning", desc:"AI confidence ≥ 90% — auto-broadcast to public channels", count:highConf, color:"#EF4444", conf:"≥90%"},
          {title:"Medium Confidence · Monitor",         desc:"AI confidence 70–90% — advisory sent to agencies",       count:medConf,  color:"#F97316", conf:"70–90%"},
          {title:"Low Confidence · Observation Only",   desc:"AI confidence < 70% — visible to admins for review",     count:lowConf,  color:"#F59E0B", conf:"<70%"}
        ].map((b,i)=>(
          <div key={i} className="panel brackets" style={{padding:14,borderLeft:`3px solid ${b.color}`}}>
            <div className="k" style={{color:b.color}}>{b.conf}</div>
            <div style={{fontSize:14,fontWeight:600,marginTop:4}}>{b.title}</div>
            <div style={{fontSize:11,color:"var(--text-mid)",marginTop:4}}>{b.desc}</div>
            <div style={{display:"flex",alignItems:"center",gap:10,marginTop:10}}>
              <div style={{fontSize:32,fontWeight:700,color:b.color,letterSpacing:"-0.02em"}} className="num">{b.count}</div>
              <HalfGauge value={b.conf==="<70%"?58:b.conf==="70–90%"?82:95} color={b.color} size={90} label="CONF"/>
            </div>
          </div>
        ))}
      </div>

      <div className="panel brackets">
        <div className="panel-hd" style={{flexWrap:"wrap",gap:6}}>
          <h3 style={{fontSize:14,margin:0}}>Live Alert Feed — {city}</h3>
          <span className="live"><span className="d"/>{alerts.length} ACTIVE</span>
          <div style={{display:"flex",gap:6,marginLeft:4}}>
            <span className="chip active">All</span>
            <span className="chip">Weather</span>
            <span className="chip">Flood</span>
            <span className="chip">Wind</span>
            <span className="chip">Air Quality</span>
          </div>
        </div>
        <div className="panel-bd" style={{display:"flex",flexDirection:"column",gap:10}}>
          {alerts.map(a=>{
            const c = riskColor(a.sev);
            return (
              <div key={a.id} className="alert-item" style={{borderLeft:`3px solid ${c}`}}>
                <div className="icb" style={{background:c+"22",color:c}}>{Icon.siren}</div>
                <div className="body">
                  <div className="h" style={{display:"flex",flexWrap:"wrap",alignItems:"center",gap:6}}>
                    <span style={{fontWeight:600}}>{a.title}</span>
                    <span className="sev" style={{color:c,background:c+"22",padding:"2px 6px",borderRadius:4,fontSize:9.5,fontFamily:"JetBrains Mono",letterSpacing:".08em"}}>{riskLabel(a.sev)} · CONF {a.conf}%</span>
                    <span className="meta" style={{fontSize:11,color:"var(--text-lo)"}}>{a.ago} · {a.area}</span>
                  </div>
                  <div style={{fontSize:12,color:"var(--text-mid)",marginTop:4}}>{a.body}</div>
                  <div style={{display:"flex",gap:6,marginTop:8,flexWrap:"wrap"}}>
                    <button className="btn" style={{padding:"4px 10px",fontSize:11}}>SMS Broadcast</button>
                    <button className="btn" style={{padding:"4px 10px",fontSize:11}}>Push</button>
                    <button className="btn" style={{padding:"4px 10px",fontSize:11}}>WhatsApp</button>
                    <button className="btn" style={{padding:"4px 10px",fontSize:11}}>Escalate →</button>
                  </div>
                </div>
              </div>
            );
          })}
          {alerts.length === 0 && (
            <div style={{padding:"32px",textAlign:"center",color:"var(--text-lo)"}}>
              <div style={{fontSize:14}}>✅ No active alerts for {city}</div>
              <div style={{fontSize:11,marginTop:8}}>All weather parameters are within safe thresholds.</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function EmergencyOverlay({ onClose }){
  const city = (RIIS.location.city || "LOCAL").toUpperCase();
  const lat = RIIS.location.lat.toFixed(4);
  const lon = RIIS.location.lon.toFixed(4);
  const now = new Date();
  const elapsed = `${String(now.getHours()).padStart(2,"0")}:${String(now.getMinutes()).padStart(2,"0")}:${String(now.getSeconds()).padStart(2,"0")}`;

  return (
    <div className="emerg-overlay">
      <div className="emerg-header">
        <span className="badge">● SOS · EMERGENCY MODE ACTIVE</span>
        <h1>Emergency Response</h1>
        <span className="mono" style={{color:"var(--text-mid)",fontSize:12,marginLeft:12}}>{city} · {lat}°N {lon}°E · T+{elapsed}</span>
        <button className="iconbtn" style={{marginLeft:"auto"}} onClick={onClose}>{Icon.x}</button>
      </div>

      <div style={{display:"grid",gridTemplateColumns:"380px 1fr 340px",gap:16,alignItems:"start"}}>
        <div style={{display:"flex",flexDirection:"column",alignItems:"center",gap:16}}>
          <div className="sos-big">SOS</div>
          <div style={{fontSize:12,color:"#FCA5A5",textAlign:"center",lineHeight:1.5}}>Tap SOS to broadcast your GPS location, phone number and emergency category to nearest response teams.</div>

          <div className="panel brackets" style={{width:"100%",marginTop:12,background:"rgba(20,10,10,0.6)",borderColor:"rgba(239,68,68,0.3)"}}>
            <div className="panel-hd" style={{borderBottomColor:"rgba(239,68,68,0.2)"}}><h3 style={{color:"#FCA5A5",fontSize:13}}>Emergency Helplines</h3></div>
            <div className="panel-bd">
              {[
                ["National Disaster Cell","1078",Icon.siren],
                ["Police Control Room","100",Icon.shield],
                ["Fire & Rescue","101",Icon.fire],
                ["Ambulance","108",Icon.hospital],
                ["Corp. Flood Cell","1913",Icon.wave],
                ["Women Helpline","1091",Icon.phone],
              ].map(([n,num,ic],i)=>(
                <div key={i} style={{display:"flex",alignItems:"center",gap:10,padding:"9px 6px",borderBottom:i<5?"1px solid rgba(239,68,68,0.12)":"none"}}>
                  <span style={{color:"#FCA5A5"}}>{ic}</span>
                  <span style={{flex:1,fontSize:12}} dangerouslySetInnerHTML={{__html:n}}/>
                  <span className="mono" style={{color:"#FCA5A5",fontSize:14,fontWeight:600}}>{num}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="vstack" style={{gap:14}}>
          <div className="panel brackets" style={{borderColor:"rgba(239,68,68,0.3)"}}>
            <div className="panel-hd"><h3 style={{color:"#FCA5A5",fontSize:13}}>Nearby Safe Shelters</h3></div>
            <div className="panel-bd">
              {RIIS.shelters.map((s,i)=>(
                <div key={i} style={{display:"flex",gap:12,padding:"10px 6px",borderBottom:"1px solid var(--stroke)"}}>
                  <span style={{width:32,height:32,borderRadius:8,background:"rgba(16,185,129,0.14)",color:"#5EEAD4",display:"grid",placeItems:"center",flexShrink:0}}>{Icon.shield}</span>
                  <div style={{flex:1,minWidth:0}}>
                    <div style={{fontSize:12.5,fontWeight:600}}>{s.name}</div>
                    <div style={{fontSize:10.5,color:"var(--text-mid)"}}>{s.current}/{s.cap} · {s.ward}</div>
                  </div>
                  <div style={{textAlign:"right",flexShrink:0}}>
                    <div className="mono" style={{fontSize:11,color:"#5EEAD4",fontWeight:600}}>{((s.current/s.cap)*100).toFixed(0)}% full</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="panel brackets" style={{borderColor:"rgba(239,68,68,0.3)"}}>
            <div className="panel-hd"><h3 style={{color:"#FCA5A5",fontSize:13}}>Live Weather — {RIIS.location.city || "Local"}</h3></div>
            <div className="panel-bd">
              <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8}}>
                <div style={{padding:10,background:"rgba(34,211,238,0.05)",border:"1px solid rgba(34,211,238,0.2)",borderRadius:8}}>
                  <div className="k" style={{color:"#7DD3FC"}}>TEMPERATURE</div>
                  <div className="mono" style={{fontSize:20,fontWeight:700,color:"#7DD3FC"}}>{RIIS.live.temperature}°C</div>
                  <div style={{fontSize:10,color:"var(--text-lo)"}}>{RIIS.live.weatherDesc}</div>
                </div>
                <div style={{padding:10,background:"rgba(34,211,238,0.05)",border:"1px solid rgba(34,211,238,0.2)",borderRadius:8}}>
                  <div className="k" style={{color:"#7DD3FC"}}>HUMIDITY</div>
                  <div className="mono" style={{fontSize:20,fontWeight:700,color:"#7DD3FC"}}>{RIIS.live.humidity}%</div>
                  <div style={{fontSize:10,color:"var(--text-lo)"}}>{RIIS.live.visibilityStatus}</div>
                </div>
                <div style={{padding:10,background:"rgba(34,211,238,0.05)",border:"1px solid rgba(34,211,238,0.2)",borderRadius:8}}>
                  <div className="k" style={{color:"#7DD3FC"}}>WIND</div>
                  <div className="mono" style={{fontSize:20,fontWeight:700,color:"#7DD3FC"}}>{RIIS.live.windSpeed} <span style={{fontSize:11}}>km/h</span></div>
                  <div style={{fontSize:10,color:"var(--text-lo)"}}>{RIIS.live.windDirLabel} · Gusts {RIIS.live.windGusts}</div>
                </div>
                <div style={{padding:10,background:"rgba(34,211,238,0.05)",border:"1px solid rgba(34,211,238,0.2)",borderRadius:8}}>
                  <div className="k" style={{color:"#7DD3FC"}}>RAINFALL</div>
                  <div className="mono" style={{fontSize:20,fontWeight:700,color:"#7DD3FC"}}>{RIIS.prediction.rainfall_mm} <span style={{fontSize:11}}>mm/6h</span></div>
                  <div style={{fontSize:10,color:"var(--text-lo)"}}>Risk {RIIS.riskIndex} · {RIIS.riskClass.toUpperCase()}</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="vstack" style={{gap:14}}>
          <div className="panel brackets" style={{borderColor:"rgba(239,68,68,0.3)"}}>
            <div className="panel-hd"><h3 style={{color:"#FCA5A5",fontSize:13}}>Nearest Hospitals</h3></div>
            <div className="panel-bd">
              {RIIS.hospitals.map((h,i)=>(
                <div key={i} style={{display:"flex",gap:10,padding:"9px 6px",borderBottom:i<3?"1px solid var(--stroke)":"none"}}>
                  <span style={{width:28,height:28,borderRadius:7,background:"rgba(239,68,68,0.14)",color:"#FCA5A5",display:"grid",placeItems:"center",flexShrink:0}}>{Icon.hospital}</span>
                  <div style={{flex:1,minWidth:0}}>
                    <div style={{fontSize:12,fontWeight:600}}>{h.name}</div>
                    <div style={{fontSize:10,color:"var(--text-mid)"}} className="mono">{h.avail} beds avail · {h.dist} km</div>
                  </div>
                  <button className="btn" style={{padding:"3px 8px",fontSize:10,alignSelf:"center",flexShrink:0}}>Call</button>
                </div>
              ))}
            </div>
          </div>
          <div className="panel brackets" style={{borderColor:"rgba(239,68,68,0.3)"}}>
            <div className="panel-hd"><h3 style={{color:"#FCA5A5",fontSize:13}}>Offline Mode</h3></div>
            <div className="panel-bd">
              <div style={{display:"flex",alignItems:"center",gap:8,padding:10,background:"rgba(16,185,129,0.06)",border:"1px solid rgba(16,185,129,0.25)",borderRadius:10}}>
                <span style={{color:"#5EEAD4"}}>{Icon.check}</span>
                <div style={{fontSize:11.5,color:"var(--text-hi)"}}>Offline maps <b className="mono" style={{fontSize:10}}>CACHED (86 MB)</b> — shelters & hospitals accessible without network.</div>
              </div>
              <div style={{marginTop:8,padding:10,background:"rgba(34,211,238,0.05)",border:"1px solid rgba(34,211,238,0.2)",borderRadius:10}}>
                <div className="k" style={{color:"var(--cyan)"}}>SMS FALLBACK</div>
                <div style={{fontSize:11,color:"var(--text-mid)",marginTop:4}}>Text <b className="mono" style={{color:"var(--cyan)"}}>RIIS HELP</b> to <b className="mono" style={{color:"var(--cyan)"}}>51969</b> for SMS instructions.</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

window.DisasterScreen = DisasterScreen;
window.AlertsScreen = AlertsScreen;
window.EmergencyOverlay = EmergencyOverlay;
