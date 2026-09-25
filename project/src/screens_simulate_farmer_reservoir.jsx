// RIIS — Flood Simulation, Farmer Advisory, Reservoir Intelligence
const { useState: useState_s, useEffect: useEffect_s } = React;

function SimulateScreen(){
  const p = RIIS.prediction;
  const initialRain = Math.max(20, Math.round(p.rainfall_mm * 2 || 60));
  const [rain, setRain] = useState_s(initialRain);
  const cityName = RIIS.location.city || "Local Area";

  // Hyperlocal impact from backend — all 8 factor categories (debounced)
  const [hl, setHl] = useState_s(null);
  const [hlErr, setHlErr] = useState_s(null);
  useEffect_s(() => {
    let alive = true;
    setHlErr(null);
    const t = setTimeout(() => {
      if (!window.RIIS_API || RIIS.location.lat == null) return;
      // Read coords at fire time — the saved-location restore runs right after
      // mount, so effect-start coords may still be the defaults.
      const reqLat = RIIS.location.lat, reqLon = RIIS.location.lon;
      window.RIIS_API.getHyperlocalImpact({
        lat: reqLat,
        lon: reqLon,
        rainfall_mm: Math.min(500, rain * 3),   // 3-hour event at slider intensity
        duration_h: 3,
        intensity_mm_h: rain,
      }).then(res => {
        // Ignore out-of-order responses if the location moved meanwhile.
        const moved = Math.abs(RIIS.location.lat - reqLat) > 1e-6
                   || Math.abs(RIIS.location.lon - reqLon) > 1e-6;
        if (alive && !moved) setHl(res);
      })
        .catch(e => { if (alive) setHlErr(String(e.message || e)); });
    }, 500);
    return () => { alive = false; clearTimeout(t); };
  }, [rain, RIIS.location.lat, RIIS.location.lon]);

  const hlClass = hl ? hl.impact.class : null;
  const cHl = hlClass ? riskColor(hlClass) : null;

  // Real DEM inundation (from RealFloodMap) — overrides the engine's
  // rational-method estimate so the numbers match the picture exactly.
  const [inund, setInund] = useState_s(null);

  const buckets = [
    { th:0,   labels:["Water accumulation minimal","Localized dry/safe runoff","All road segments normal","0 evacuations needed"], class:"safe" },
    { th:40,  labels:["Light water accumulation","Localized puddles in low-lying zones","Minor surface wetness","Transit nominal"], class:"safe" },
    { th:90,  labels:["Waterlogging in known low zones","Drainage nearing 70% capacity","2-4 road segments impacted","Advisory: light traffic slowdowns"], class:"mod" },
    { th:150, labels:["Significant drainage overflow","Waterlogging depth 0.4-0.6m","8+ road segments closed","Emergency response standby"], class:"high" },
    { th:220, labels:["Severe flood inundation","River/drainage overflow imminent","Road network significantly impacted","Evacuation zones activated"], class:"extreme" },
  ];
  const active = buckets.filter(b=>rain>=b.th).slice(-1)[0] || buckets[0];
  const c = riskColor(active.class);

  return (
    <div className="screen">
      <div className="screen-title">
        <div>
          <div className="crumb">SIMULATION <b>Flood Simulation Engine</b></div>
          <h1 style={{marginTop:6}}>What-if Flood Scenario Modeling — {cityName}</h1>
          <p style={{marginTop:4}}>Adjust rainfall intensity to simulate catchment runoff, drainage overflow, and critical infrastructure stress.</p>
        </div>
        <div className="id">GIS ENGINE · v2.1 · {cityName.toUpperCase()}</div>
      </div>

      <div style={{display:"grid",gridTemplateColumns:"1.5fr 1fr",gap:16}}>
        <div className="panel brackets">
          <div className="panel-hd">
            <h3>Simulated Inundation Map — {cityName}</h3>
            <span className="live" style={{background:(cHl||c)+"22",color:cHl||c}}><span className="d" style={{background:cHl||c,boxShadow:`0 0 6px ${cHl||c}`}}/>{riskLabel(hlClass||active.class)}</span>
            <span className="sub">{hl ? "LIVE GEOFACATORS · OSM · SOILGRIDS · DEM" : "DEM 30m · Hydrodynamic fusion"}</span>
          </div>
          <div className="panel-bd">
            <RealFloodMap intensity={rain} onResult={setInund}/>

            {/* Slider */}
            <div style={{marginTop:22,padding:"14px 18px",background:"rgba(10,18,28,0.5)",border:"1px solid var(--stroke)",borderRadius:12}}>
              <div style={{display:"flex",alignItems:"end",gap:16,marginBottom:8}}>
                <div>
                  <div className="k">SIMULATED RAINFALL INTENSITY</div>
                  <div style={{fontSize:32,fontWeight:700,letterSpacing:"-0.02em",lineHeight:1}} className="num">{rain}<span style={{fontSize:14,color:"var(--text-mid)",marginLeft:4}}>mm / hr</span></div>
                </div>
                <div style={{marginLeft:"auto",display:"flex",gap:8}}>
                  {[30,75,120,180,250].map(v=>(
                    <button key={v} className={"chip "+(rain===v?"active":"")} onClick={()=>setRain(v)}>{v}</button>
                  ))}
                </div>
              </div>
              <input className="sim" type="range" min="0" max="300" step="5" value={rain} onChange={(e)=>setRain(+e.target.value)}/>
              <div style={{display:"flex",justifyContent:"space-between",fontSize:10,color:"var(--text-lo)",marginTop:6}} className="mono">
                <span>0 · Dry</span><span>50 · Light</span><span>100 · Moderate</span><span>150 · Heavy</span><span>200 · Very Heavy</span><span>300 · Cloudburst</span>
              </div>
            </div>
          </div>
        </div>

        <div className="vstack" style={{gap:16}}>
          <div className="panel brackets">
            <div className="panel-hd">
              <h3>Simulation Results</h3>
              <span className="sub">{inund ? `DEM ${(inund.grid||{}).res_m} m/px` : "engine estimate"} · {rain} mm/hr</span>
            </div>
            <div className="panel-bd">
              <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8}}>
                {(() => {
                  const inn = inund ? {
                    depth_mean_m: inund.stats.mean_depth_m,
                    depth_max_m: inund.stats.max_depth_m,
                    area_km2: inund.stats.wet_area_km2,
                    structures: hl && hl.inundation ? hl.inundation.structures : 0,
                    roads_km: hl && hl.inundation ? hl.inundation.roads_km : 0,
                    evacuation: hl && hl.inundation ? hl.inundation.evacuation : "None",
                    people_exposed: hl && hl.inundation ? hl.inundation.people_exposed : 0,
                    drainage_saturation_pct: hl && hl.inundation ? hl.inundation.drainage_saturation_pct : 0,
                    dem: true,
                  } : (hl && hl.inundation);
                  return [
                    ["Water Depth (mean)", inn ? inn.depth_mean_m.toFixed(2)+" m" : (rain*0.0035).toFixed(2)+" m", c],
                    ["Water Depth (max)",  inn ? inn.depth_max_m.toFixed(2)+" m"  : (rain*0.0075).toFixed(2)+" m", c],
                    ["Inundated Area",     inn ? inn.area_km2.toFixed(2)+" km²"   : (rain*0.45).toFixed(1)+" km²", "#3B82F6"],
                    ["Structures Impacted",inn ? inn.structures.toLocaleString() : Math.round(rain*8.5), "#F97316"],
                    ["Roads Affected",     inn ? inn.roads_km+" km" : Math.round(rain*0.12)+" km", "#F59E0B"],
                    ["Evacuation Status",  inn ? inn.evacuation : rain>180?"Tier-1 Active":rain>100?"Standby":"None", "#EF4444"],
                    ["Est. People Exposed",inn ? inn.people_exposed.toLocaleString() : (rain*180).toLocaleString(), "#A78BFA"],
                    ["Drainage Saturation",inn ? inn.drainage_saturation_pct+"%" : Math.min(100,Math.round(rain*0.52))+"%", "#22D3EE"],
                  ];
                })().map(([k,v,cc],i)=>(
                  <div key={i} style={{padding:10,background:"rgba(10,18,28,0.5)",border:"1px solid var(--stroke)",borderRadius:8,borderLeft:`3px solid ${cc}`}}>
                    <div className="k">{k}</div>
                    <div className="num" style={{fontWeight:600,fontSize:15,marginTop:2}}>{v}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
          <div className="panel brackets">
            <div className="panel-hd"><h3>Cascade System Effects</h3></div>
            <div className="panel-bd" style={{display:"flex",flexDirection:"column",gap:8}}>
              {active.labels.map((lbl,i)=>(
                <div key={i} style={{display:"flex",gap:10,alignItems:"center",padding:"8px 10px",background:"rgba(10,18,28,0.5)",border:"1px solid var(--stroke)",borderRadius:8}}>
                  <span style={{width:6,height:6,borderRadius:"50%",background:c,boxShadow:`0 0 6px ${c}`}}/>
                  <span style={{fontSize:12.5,color:"var(--text-hi)"}}>{lbl}</span>
                </div>
              ))}
              <button className="btn primary mt3" style={{alignSelf:"start"}}>Export Simulation Report →</button>
            </div>
          </div>
        </div>
      </div>

      {/* Hyperlocal 8-category factor analysis (backend-driven) */}
      <div className="panel brackets" style={{marginTop:16}}>
        <div className="panel-hd">
          <h3>Hyperlocal Factor Analysis — All 8 Categories</h3>
          <span className="live" style={{background:(cHl||"#22D3EE")+"22",color:cHl||"#22D3EE"}}>
            <span className="d" style={{background:cHl||"#22D3EE"}}/>{hl ? `IMPACT ${hl.impact.score}/100 · ${riskLabel(hl.impact.class)}` : "COMPUTING…"}</span>
          <span className="sub">{hl ? `confidence ${hl.impact.confidence_pct}% · ${hl.impact.return_period || "return period n/a"}` : "fetching elevation · OSM · soil · 3y archive"}</span>
        </div>
        <div className="panel-bd">
          {!hl && !hlErr && (
            <div style={{fontSize:12.5,color:"var(--text-lo)",padding:"6px 0"}}>
              Loading live geofactors for {RIIS.location.city} ({RIIS.location.lat?.toFixed(4)}, {RIIS.location.lon?.toFixed(4)})…
            </div>
          )}
          {hlErr && (
            <div style={{fontSize:12.5,color:"#F59E0B",padding:"6px 0"}}>
              Backend unreachable ({hlErr}) — Simulation Results above are heuristic-only.
            </div>
          )}
          {hl && (<>
            {/* Location facts */}
            <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(155px,1fr))",gap:8,marginBottom:14}}>
              {[
                ["Elevation", hl.location.elevation_m+" m"],
                ["Slope", hl.location.slope_m_km+" m/km"],
                ["Nearest Water", hl.location.nearest_water_m!=null ? hl.location.nearest_water_m+" m ("+(hl.location.water_type||"water")+")" : "not mapped"],
                ["Soil", String(hl.location.soil_texture||"—").replace("_"," ")+" · "+hl.location.infiltration_mm_h+" mm/h"],
                ["Impervious Surface", hl.location.impervious_pct+"%"],
                ["Antecedent Rain", hl.antecedent.rain_7d_mm+" mm/7d · "+hl.antecedent.saturation_pct+"% sat"],
                ["Runoff Coeff. C", hl.runoff.coefficient],
                ["Drainage Capacity", hl.runoff.drainage_capacity_mm_h+" mm/h"],
              ].map(([k,v],i)=>(
                <div key={i} style={{padding:"8px 10px",background:"rgba(10,18,28,0.5)",border:"1px solid var(--stroke)",borderRadius:8}}>
                  <div className="k">{k}</div>
                  <div className="num" style={{fontSize:13,fontWeight:600,marginTop:2}}>{v}</div>
                </div>
              ))}
            </div>

            {/* Category bars */}
            <div style={{display:"flex",flexDirection:"column",gap:8}}>
              {hl.categories.map((cat,i)=>{
                const cc = cat.score>=75?"#EF4444":cat.score>=50?"#F97316":cat.score>=25?"#F59E0B":"#10B981";
                return (
                  <div key={i} className="crop-gauge" style={{margin:0}}>
                    <div className="lbl">
                      <span>{cat.name} <span style={{color:"var(--text-lo)",fontSize:10}}>weight {Math.round(cat.weight*100)}% · {cat.share_pct}% of total score</span></span>
                      <b style={{color:cc}} className="num">{cat.score}/100</b>
                    </div>
                    <div className="track"><div className="fill" style={{width:cat.score+"%",background:cc}}/></div>
                    <div style={{fontSize:10.5,color:"var(--text-lo)",marginTop:2}}>{cat.source}</div>
                  </div>
                );
              })}
            </div>

            {/* Advisories */}
            {hl.advisories.length>0 && (
              <div style={{marginTop:12,display:"flex",flexDirection:"column",gap:6}}>
                {hl.advisories.map((a,i)=>(
                  <div key={i} style={{display:"flex",gap:9,alignItems:"start",padding:"8px 10px",background:"rgba(249,115,22,0.07)",border:"1px solid var(--stroke)",borderRadius:8}}>
                    <span style={{width:6,height:6,borderRadius:"50%",background:"#F97316",boxShadow:"0 0 6px #F97316",marginTop:5,flex:"0 0 auto"}}/>
                    <span style={{fontSize:12,color:"var(--text-hi)",lineHeight:1.5}}>{a}</span>
                  </div>
                ))}
              </div>
            )}
          </>)}
        </div>
      </div>
    </div>
  );
}

function FarmerScreen(){
  const [crop, setCrop] = useState_s("paddy");
  const [stage, setStage] = useState_s("Vegetative");
  const [loc, setLoc] = useState_s(() => RIIS.location.city || "Local Sector");
  const w = RIIS.live;
  const p = RIIS.prediction;

  // Live geofactors (soil, saturation, antecedent rain) from backend
  const [geo, setGeo] = useState_s(null);
  useEffect_s(() => {
    let alive = true;
    if (window.RIIS_API && RIIS.location.lat != null) {
      window.RIIS_API.getGeofactors(RIIS.location.lat, RIIS.location.lon)
        .then(r => { if (alive) setGeo(r); })
        .catch(() => {});
    }
    return () => { alive = false; };
  }, [RIIS.location.lat, RIIS.location.lon]);
  const soilSat = geo && geo.antecedent ? geo.antecedent.saturation_pct : Math.round(w.humidity * 0.45);
  const soilInfo = geo && geo.geo ? geo.geo.soil : null;

  // Dynamic advisories based on real rainfall & temperature
  const isRainHigh = p.rainfall_mm > 15;
  const isRainMod = p.rainfall_mm > 3;
  const isTempHigh = w.temperature > 33;

  const dynamicAdvisories = [
    // Real soil/antecedent advisory from backend geofactors
    ...(geo ? [{
      type: soilSat >= 70 ? "warn" : soilSat >= 45 ? "info" : "good",
      ic: Icon.droplet,
      title: `Field Saturation ${soilSat}% — ${soilSat >= 70 ? "Waterlogging Risk" : soilSat >= 45 ? "Near Field Capacity" : "Irrigation Needed"}`,
      desc: `Antecedent rainfall ${geo.antecedent.rain_3d_mm}mm/3d, ${geo.antecedent.rain_7d_mm}mm/7d, ${geo.antecedent.rain_30d_mm}mm/30d from Open-Meteo archive. `
        + `Soil is ${String(soilInfo ? soilInfo.texture : "unknown").replace("_"," ")} with ${soilInfo ? soilInfo.infiltration_mm_h : "?"} mm/h infiltration. `
        + (soilSat >= 70 ? "Soils cannot absorb more rain — delay sowing and clear drainage channels."
          : soilSat >= 45 ? "Soils near field capacity — light irrigation only, avoid waterlogging in low patches."
          : "Soils dry — proceed with normal irrigation cycle.")
    }] : []),
    {
      type: isRainHigh ? "warn" : isRainMod ? "info" : "good",
      ic: Icon.droplet,
      title: isRainHigh ? "Delay Irrigation for 48 Hours" : isRainMod ? "Moderate Soil Moisture Window" : "Standard Irrigation Recommended",
      desc: isRainHigh 
        ? `Upcoming forecast of ${p.rainfall_mm}mm rain will adequately saturate fields. Avoid waterlogging in low patches.`
        : isRainMod
        ? `Predicted ${p.rainfall_mm}mm rainfall will supplement irrigation. Monitor field capacity.`
        : `Current soil moisture is stable with dry conditions (${w.humidity}% RH). Regular watering cycle advised.`
    },
    {
      type: isRainHigh ? "warn" : "info",
      ic: Icon.flame,
      title: isRainHigh ? "Postpone Pesticide & Foliar Spraying" : "Pesticide Spraying Window: Open",
      desc: isRainHigh 
        ? `Rain forecast within ${p.startsInText} will wash away foliar applications. Reschedule spraying.`
        : `Favorable wind conditions (${w.windSpeed} km/h from ${w.windDirLabel}) and clear weather suitable for targeted spraying.`
    },
    {
      type: isTempHigh ? "warn" : "good",
      ic: Icon.leaf,
      title: `Thermal Index Advisory (${w.temperature.toFixed(1)}°C)`,
      desc: isTempHigh 
        ? `High ambient temperature (feels like ${w.feels.toFixed(1)}°C). Ensure mulch layer to reduce soil evaporation.`
        : `Current temperature ${w.temperature.toFixed(1)}°C is in optimal physiological range for vegetative growth.`
    },
    {
      type: soilSat > 70 ? "warn" : "info",
      ic: Icon.chart,
      title: `Soil Moisture Status: ${soilSat}%${soilInfo ? " · " + String(soilInfo.texture).replace("_"," ") : ""}`,
      desc: geo && geo.antecedent
        ? `${geo.antecedent.rain_7d_mm}mm rain in the last 7 days and ${geo.antecedent.rain_30d_mm}mm in 30 days — fields at ${soilSat}% saturation.${soilInfo ? ` ${String(soilInfo.texture).replace("_"," ")} soil absorbs at ${soilInfo.infiltration_mm_h} mm/h; rain above that rate becomes runoff.` : ""}`
        : `Atmospheric humidity at ${w.humidity}% and cloud cover at ${w.cloudCover}%. Soil moisture retention is nominal.`
    },
    {
      type: w.humidity > 80 ? "warn" : "good",
      ic: Icon.siren,
      title: w.humidity > 80 ? "Fungal / Pest Risk Elevated" : "Pest & Disease Pressure: Low",
      desc: w.humidity > 80 
        ? `High humidity (${w.humidity}%) creates favorable conditions for foliar blight. Inspect lower leaves.`
        : `Moderate atmospheric conditions discourage fungal spore dissemination.`
    }
  ];

  return (
    <div className="screen">
      <div className="screen-title">
        <div>
          <div className="crumb">ADVISORY <b>Farmer Module</b></div>
          <h1 style={{marginTop:6}}>Precision Agriculture &amp; Weather Advisory — {loc}</h1>
          <p style={{marginTop:4}}>Live weather-driven recommendations for irrigation, crop protection, sowing &amp; harvest</p>
        </div>
        <div className="id">CROP AI · LIVE METRICS · {loc.toUpperCase()}</div>
      </div>

      {/* Inputs */}
      <div className="panel brackets" style={{marginBottom:16}}>
        <div className="panel-bd" style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr auto",gap:12,alignItems:"end"}}>
          <div>
            <div className="k mb2">TARGET LOCATION</div>
            <div style={{background:"rgba(10,18,28,0.6)",border:"1px solid var(--stroke)",borderRadius:10,padding:"9px 12px",display:"flex",alignItems:"center",gap:8}}>
              <span style={{color:"var(--cyan)"}}>{Icon.pin}</span>
              <input value={loc} onChange={e=>setLoc(e.target.value)} style={{background:"none",border:"none",outline:"none",color:"var(--text-hi)",flex:1,fontSize:13}}/>
            </div>
          </div>
          <div>
            <div className="k mb2">CROP TYPE</div>
            <div style={{display:"flex",gap:6,flexWrap:"wrap"}}>
              {["Paddy","Sugarcane","Cotton","Groundnut","Millets","Tomato"].map(c=>(
                <button key={c} className={"chip"+(crop===c.toLowerCase()?" active":"")} onClick={()=>setCrop(c.toLowerCase())}>{c}</button>
              ))}
            </div>
          </div>
          <div>
            <div className="k mb2">GROWTH STAGE</div>
            <div style={{display:"flex",gap:6,flexWrap:"wrap"}}>
              {["Sowing","Vegetative","Flowering","Grain-filling","Harvest"].map(s=>(
                <button key={s} className={"chip"+(stage===s?" active":"")} onClick={()=>setStage(s)}>{s}</button>
              ))}
            </div>
          </div>
          <button 
            className="btn primary" 
            style={{padding:"10px 18px"}}
            onClick={()=>{
              if (window.searchAndLoadLocation && loc !== RIIS.location.city) {
                window.searchAndLoadLocation(loc);
              }
            }}
          >
            Sync Weather ⚡
          </button>
        </div>
      </div>

      <div style={{display:"grid",gridTemplateColumns:"1.4fr 1fr",gap:16}}>
        <div className="panel brackets">
          <div className="panel-hd">
            <h3>Live Meteorological Recommendations</h3>
            <span className="live"><span className="d"/>{dynamicAdvisories.length} ACTIONS</span>
            <span className="sub">Synced with {RIIS.location.city} weather</span>
          </div>
          <div className="panel-bd" style={{display:"flex",flexDirection:"column",gap:10}}>
            {dynamicAdvisories.map((a,i)=>{
              const color = a.type==="warn"?"#F97316":a.type==="info"?"#22D3EE":"#10B981";
              return (
                <div key={i} style={{display:"flex",gap:12,padding:14,background:"rgba(10,18,28,0.5)",border:"1px solid var(--stroke)",borderRadius:12,borderLeft:`3px solid ${color}`}}>
                  <div style={{width:38,height:38,borderRadius:10,background:color+"22",color:color,display:"grid",placeItems:"center",flex:"0 0 auto"}}>{a.ic}</div>
                  <div style={{flex:1}}>
                    <div style={{fontSize:13.5,fontWeight:600,color:"var(--text-hi)"}}>{a.title}</div>
                    <div style={{fontSize:12,color:"var(--text-mid)",marginTop:4,lineHeight:1.5}}>{a.desc}</div>
                  </div>
                  <span className="mono" style={{fontSize:10,color:color,letterSpacing:".08em",alignSelf:"start"}}>PRIORITY {i<2?1:2}</span>
                </div>
              );
            })}
          </div>
        </div>

        <div className="vstack" style={{gap:16}}>
          <div className="panel brackets">
            <div className="panel-hd"><h3>Microclimate &amp; Crop Health</h3></div>
            <div className="panel-bd">
              {[
                [geo ? "Soil Moisture (3y archive)" : "Est. Soil Moisture", `${soilSat}%`, soilSat > 70 ? "#F59E0B" : "#10B981", soilSat],
                ["Canopy Temp.", `${w.temperature.toFixed(1)}°C`, "#7DD3FC", Math.min(100, Math.round(w.temperature * 2.2))],
                ["Vapor Deficit", `${((100-w.humidity)*0.03).toFixed(2)} kPa`, "#22D3EE", Math.max(10, 100-w.humidity)],
                ["Fungal Infection Risk", w.humidity > 80 ? "ELEVATED" : "LOW", w.humidity > 80 ? "#F59E0B" : "#10B981", w.humidity > 80 ? 70 : 25],
                ["Pesticide Wash-off Risk", p.rainfall_mm > 5 ? "HIGH" : "MINIMAL", p.rainfall_mm > 5 ? "#EF4444" : "#10B981", p.rainfall_mm > 5 ? 85 : 15],
              ].map(([k,v,c,pct],i)=>(
                <div className="crop-gauge" key={i} style={{marginBottom:10}}>
                  <div className="lbl"><span>{k}</span><b style={{color:c}} className="num">{v}</b></div>
                  <div className="track"><div className="fill" style={{width:pct+"%",background:c}}/></div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ReservoirScreen(){
  const [sel, setSel] = useState_s(() => RIIS.reservoirs[0]);
  const p = RIIS.prediction;

  return (
    <div className="screen">
      <div className="screen-title">
        <div>
          <div className="crumb">INFRASTRUCTURE <b>Reservoir Intelligence</b></div>
          <h1 style={{marginTop:6}}>Reservoir Network — Hydrological Inflow &amp; Storage</h1>
          <p style={{marginTop:4}}>Real-time storage, inflow prediction &amp; overflow risk based on active precipitation</p>
        </div>
        <div className="id">HYDROLOGY · TELEMETRY · LIVE</div>
      </div>

      {/* Reservoir grid */}
      <div className="reservoir-grid" style={{gridTemplateColumns:"repeat(5,1fr)"}}>
        {RIIS.reservoirs.map(r=>{
          const c = riskColor(r.class);
          const fillPct = Math.round((r.cur/r.cap)*100);
          return (
            <div key={r.id} className="panel brackets" onClick={()=>setSel(r)} style={{cursor:"pointer",padding:14,borderColor:sel.id===r.id?c:undefined}}>
              <div style={{display:"flex",justifyContent:"space-between",alignItems:"center"}}>
                <div>
                  <div className="k">{r.id} · RESERVOIR</div>
                  <div style={{fontSize:15,fontWeight:700,marginTop:2}}>{r.name}</div>
                </div>
                <span className="sev" style={{color:c,background:c+"22"}}>{riskLabel(r.class)}</span>
              </div>
              <div style={{display:"flex",alignItems:"center",gap:10,marginTop:12}}>
                <CircularGauge value={fillPct} size={90} thickness={8} color={c} label={fillPct+"%"} sublabel="FILL"/>
                <div style={{fontSize:11,color:"var(--text-mid)",lineHeight:1.6}}>
                  <div>Cap · <b className="mono" style={{color:"var(--text-hi)"}}>{r.cap} mcft</b></div>
                  <div>Cur · <b className="mono" style={{color:"var(--text-hi)"}}>{r.cur} mcft</b></div>
                  <div>In · <b className="mono" style={{color:"#5EEAD4"}}>+{r.inflow} m³/s</b></div>
                  <div>Out · <b className="mono" style={{color:"#FCA5A5"}}>−{r.outflow} m³/s</b></div>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:16,marginTop:16}}>
        <div className="panel brackets">
          <div className="panel-hd">
            <h3>{sel.name} · Level Trajectory</h3>
            <span className="live"><span className="d"/>LIVE</span>
            <span className="sub">−24h → +24h</span>
          </div>
          <div className="panel-bd">
            <LineChart w={620} h={220}
              xLabels={["−24h","−12h","−6h","Now","+6h","+12h","+24h"]}
              series={[
                { name:"Storage %", color:"#22D3EE", data:[55, 58, 60, Math.round(sel.cur/sel.cap*100), Math.min(100, Math.round(sel.cur/sel.cap*100 + p.rainfall_mm*0.3)), Math.min(100, Math.round(sel.cur/sel.cap*100 + p.rainfall_mm*0.5)), Math.min(100, Math.round(sel.cur/sel.cap*100 + p.rainfall_mm*0.6))] },
                { name:"Inflow m³/s", color:"#3B82F6", data:[sel.inflow*0.8, sel.inflow*0.9, sel.inflow, sel.inflow, sel.inflow + p.rainfall_mm*2, sel.inflow + p.rainfall_mm*1.5, sel.inflow] }
              ]}/>
          </div>
        </div>

        <div className="panel brackets">
          <div className="panel-hd">
            <h3>Gate Management Guidance</h3>
            <span className="live" style={{background:riskColor(sel.class)+"22",color:riskColor(sel.class)}}><span className="d" style={{background:riskColor(sel.class)}}/>{riskLabel(sel.class)}</span>
          </div>
          <div className="panel-bd">
            <div style={{display:"flex",alignItems:"center",gap:14}}>
              <HalfGauge value={Math.round(sel.over*100)} color={riskColor(sel.class)} label="OVERFLOW PROB" size={160}/>
              <div style={{flex:1}}>
                <div className="k">CURRENT RECOMMENDATION</div>
                <div style={{fontSize:22,fontWeight:700,letterSpacing:"-0.02em",marginTop:2}}>
                  {sel.class==="extreme" ? "Open 2 Gates × 1.5m" : sel.class==="high" ? "Open 1 Gate × 0.8m" : "Normal Gate Configuration"}
                </div>
                <div style={{fontSize:11.5,color:"var(--text-mid)",marginTop:8,lineHeight:1.5}}>
                  Current inflow: <b className="mono" style={{color:"var(--text-hi)"}}>{sel.inflow} m³/s</b><br/>
                  Current outflow: <b className="mono" style={{color:"var(--text-hi)"}}>{sel.outflow} m³/s</b><br/>
                  System Status: <b className="mono" style={{color:"var(--cyan)"}}>Nominal Hydrology</b>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

window.SimulateScreen = SimulateScreen;
window.FarmerScreen = FarmerScreen;
window.ReservoirScreen = ReservoirScreen;
