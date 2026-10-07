// RIIS — Flood Simulation, Farmer Advisory, Reservoir Intelligence
const { useState: useState_s, useEffect: useEffect_s } = React;

function SimulateScreen(){
  const p = RIIS.prediction;
  const initialRain = Math.max(20, Math.round(p.rainfall_mm * 2 || 60));
  const [rain, setRain] = useState_s(initialRain);
  const cityName = RIIS.location.city || "Local Area";

  // Hyperlocal impact from backend — engine v2, ten factor groups (debounced)
  const [hl, setHl] = useState_s(null);
  const [hlErr, setHlErr] = useState_s(null);
  const [pattern, setPattern] = useState_s("steady");   // temporal pattern of the event
  const [duration, setDuration] = useState_s(3);        // hours
  const [refreshTick, setRefreshTick] = useState_s(0);
  useEffect_s(() => {
    let alive = true;
    setHlErr(null);
    const t = setTimeout(() => {
      if (!window.RIIS_API || RIIS.location.lat == null) return;
      // Read coords at fire time — the saved-location restore runs right after
      // mount, so effect-start coords may still be the defaults.
      const reqLat = RIIS.location.lat, reqLon = RIIS.location.lon;
      (window.RIIS_API.ready || Promise.resolve()).then(() => window.RIIS_API.getHyperlocalImpact({
        lat: reqLat,
        lon: reqLon,
        rainfall_mm: Math.min(500, rain * duration),   // event total at slider intensity
        duration_h: duration,
        intensity_mm_h: rain,
        pattern,
      })).then(res => {
        // Ignore out-of-order responses if the location moved meanwhile.
        const moved = Math.abs(RIIS.location.lat - reqLat) > 1e-6
                   || Math.abs(RIIS.location.lon - reqLon) > 1e-6;
        if (alive && !moved) setHl(res);
      })
        .catch(e => { if (alive) setHlErr(String(e.message || e)); });
    }, 500);
    return () => { alive = false; clearTimeout(t); };
  }, [rain, pattern, duration, refreshTick, RIIS.location.lat, RIIS.location.lon]);
  // Static layers that were still being fetched when the engine answered: ask again in 8 s.
  const stillLoading = hl && hl.still_loading ? hl.still_loading.join(",") : "";
  useEffect_s(() => {
    if (!stillLoading) return;
    const t = setTimeout(() => setRefreshTick(n => n + 1), 8000);
    return () => clearTimeout(t);
  }, [stillLoading]);

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
              <div style={{display:"flex",gap:14,alignItems:"center",marginTop:12,flexWrap:"wrap"}}>
                <div style={{display:"flex",gap:6,alignItems:"center"}}>
                  <span className="k" style={{marginRight:4}}>DURATION</span>
                  {[1,3,6,12,24].map(h=>(
                    <button key={h} className={"chip "+(duration===h?"active":"")} onClick={()=>setDuration(h)}>{h} h</button>
                  ))}
                </div>
                <div style={{display:"flex",gap:6,alignItems:"center"}}>
                  <span className="k" style={{marginRight:4}}>PATTERN</span>
                  {[["steady","Steady"],["front","Front-loaded"],["back","Back-loaded"],["burst","Burst"]].map(([v,lbl])=>(
                    <button key={v} className={"chip "+(pattern===v?"active":"")} onClick={()=>setPattern(v)} title={v==="front"?"60% of the rain in the first third — floods fastest":v==="burst"?"70% in a short burst, cloudburst-style":v==="back"?"peak late in the event":"uniform rate"}>{lbl}</button>
                  ))}
                </div>
                <span className="mono" style={{fontSize:10.5,color:"var(--text-lo)",marginLeft:"auto"}}>event total {Math.min(500, rain*duration)} mm · peak {hl ? hl.impact.peak_intensity_mm_h : rain} mm/h</span>
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

      {/* Hyperlocal ten-factor analysis (backend engine v2) */}
      <div className="panel brackets" style={{marginTop:16}}>
        <div className="panel-hd">
          <h3>Hyperlocal Factor Analysis — {hl ? `${hl.categories.length} Factor Groups` : "Ten Factor Groups"}</h3>
          <span className="live" style={{background:(cHl||"#22D3EE")+"22",color:cHl||"#22D3EE"}}>
            <span className="d" style={{background:cHl||"#22D3EE"}}/>{hl ? `IMPACT ${hl.impact.score}/100 · ${riskLabel(hl.impact.class)}` : "COMPUTING…"}</span>
          <span className="sub">{hl ? `data confidence ${hl.impact.confidence_pct}% · ${hl.impact.return_period || "return period n/a"} · engine v${hl.engine_version||"2"}${hl.still_loading&&hl.still_loading.length?` · still fetching ${hl.still_loading.join(", ")}`:""}` : "fetching DEM · OSM · soil · tide · reservoirs · flood history"}</span>
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
              {(() => {
                const L = hl.location, F = hl.factors || {}, sm = F.soil_moisture || {}, tide = F.tide || {}, up = F.upstream_reservoirs || {}, fh = F.flood_history || {}, fm = F.forecast_models || {};
                const upNear = (up.reservoirs||[]).filter(r=>r.upstream)[0];
                return [
                  ["District", (L.district||"—")+(fh.dfsi!=null?` · DFSI ${fh.dfsi}`:"")],
                  ["Elevation · Slope", L.elevation_m+" m · "+(L.slope_deg!=null?L.slope_deg+"°":L.slope_m_km+" m/km")],
                  ["Height above drainage", L.hand_m!=null ? L.hand_m+" m"+(L.closed_depression?" · closed depression":"") : "DEM pending"],
                  ["Upstream catchment", L.upstream_area_km2!=null ? L.upstream_area_km2+" km²" : "—"],
                  ["Nearest Water", L.nearest_water_m!=null ? L.nearest_water_m+" m ("+(L.water_type||"water")+")" : "not mapped"],
                  ["Soil", String(L.soil_texture||"—").replace("_"," ")+" · "+L.infiltration_mm_h+" mm/h"],
                  ["Soil Moisture", sm.m3_m3_0_7cm!=null ? sm.m3_m3_0_7cm+" m³/m³ · "+sm.saturation_pct+"% sat" : hl.antecedent.saturation_pct+"% sat (est.)"],
                  ["Antecedent Rain", hl.antecedent.rain_3d_mm+" mm/3d · "+hl.antecedent.rain_7d_mm+" mm/7d"],
                  ["Land cover", "impervious "+L.impervious_pct+"% · green "+L.green_pct+"%"+(L.wetland_pct?" · wetland "+L.wetland_pct+"%":"")],
                  ["Buildings", (L.buildings_per_km2||0)+" /km²"],
                  ["Coast · Tide", L.coast_km!=null ? L.coast_km+" km"+(tide.now_m!=null?` · tide ${tide.now_m>=0?"+":""}${tide.now_m} m`:"") : "inland"],
                  ["Upstream reservoir", upNear ? `${upNear.name} ${upNear.storage_pct}% · ${upNear.distance_km} km` : (up.upstream_count ? up.upstream_count+" upstream" : "none within 40 km")],
                  ["Forecast models (6h)", fm.next_6h_mm ? Object.entries(fm.next_6h_mm).map(([k,v])=>`${k.split("_")[0]} ${v}`).join(" · ") : "—"],
                  ["Runoff Coeff. C", hl.runoff.coefficient],
                  ["Effective Drainage", hl.runoff.drainage_capacity_mm_h+" mm/h"],
                  ["Flood history", fh.district ? `${fh.district_events||0} events · ${fh.district_events_since_2010||0} since 2010` : "no district match"],
                ];
              })().map(([k,v],i)=>(
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

            {/* Drainage system, ponding timeline, secondary hazards */}
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:12,marginTop:14}}>
              <div style={{padding:"10px 12px",background:"rgba(10,18,28,0.5)",border:"1px solid var(--stroke)",borderRadius:8}}>
                <div className="k">DRAINAGE SYSTEM</div>
                {(() => { const d = hl.drainage || {}; const m = d.mapped || {}; return [
                  ["Design capacity", d.design_capacity_mm_h+" mm/h"],
                  ["Seasonal blockage", "×"+d.blockage_factor],
                  ["Outfall (tide / river)", "×"+d.outfall_factor],
                  ["Structures", "×"+d.structural_factor],
                  ["Natural conveyance", "+"+(d.natural_conveyance_mm_h||0)+" mm/h"],
                  ["Effective", d.effective_capacity_mm_h+" mm/h"],
                  ["Mapped", `${d.drains_mapped||0} drains · ${m.culverts||0} culverts · ${m.embankments||0} embankments · ${m.railways||0} rail · ${m.pumping_stations||0} pumps · ${m.underpasses||0} underpasses`],
                ].map(([k,v],i)=>(
                  <div key={i} style={{display:"flex",justifyContent:"space-between",gap:8,fontSize:11.5,padding:"3px 0",borderBottom:"1px dashed rgba(120,180,255,0.08)"}}>
                    <span style={{color:"var(--text-mid)"}}>{k}</span><span className="mono" style={{textAlign:"right",fontWeight:k==="Effective"?700:500}}>{v}</span>
                  </div>
                )); })()}
                {(hl.drainage && hl.drainage.notes || []).map((n,i)=><div key={i} style={{fontSize:10.5,color:"#F59E0B",marginTop:4}}>• {n}</div>)}
              </div>
              <div style={{padding:"10px 12px",background:"rgba(10,18,28,0.5)",border:"1px solid var(--stroke)",borderRadius:8}}>
                <div className="k">STANDING WATER — HOURLY BALANCE</div>
                <div style={{display:"flex",alignItems:"end",gap:12,marginTop:6}}>
                  <Sparkline data={(hl.inundation.storage_series_mm||[0,0]).length>1?hl.inundation.storage_series_mm:[0,0]} w={200} h={54} color={cHl||"#22D3EE"}/>
                  <div>
                    <div className="num" style={{fontSize:18,fontWeight:700}}>{hl.inundation.peak_storage_mm} <span style={{fontSize:11,color:"var(--text-mid)"}}>mm peak</span></div>
                    <div style={{fontSize:11,color:"var(--text-mid)"}}>{hl.inundation.ponding_hours} h above 15 mm</div>
                  </div>
                </div>
                <div style={{fontSize:10.5,color:"var(--text-lo)",marginTop:6,lineHeight:1.5}}>
                  Inflow = runoff ({Math.round(hl.runoff.coefficient*100)}% of rain, {hl.impact.pattern}) + upstream; outflow = drainage decaying as receiving waters fill.
                  Ponded fraction {Math.round((hl.inundation.ponded_fraction||0)*100)}% of the cell → mean {hl.inundation.depth_mean_m} m, max {hl.inundation.depth_max_m} m.
                  Score = 0.6 × factor composite ({hl.impact.factor_composite}) + 0.4 × inundation severity ({hl.impact.inundation_severity}).
                </div>
              </div>
              <div style={{padding:"10px 12px",background:"rgba(10,18,28,0.5)",border:"1px solid var(--stroke)",borderRadius:8}}>
                <div className="k">SECONDARY HAZARDS</div>
                {(hl.secondary_hazards||[]).length===0 && <div style={{fontSize:11.5,color:"var(--text-lo)",marginTop:6}}>None triggered for this scenario.</div>}
                {(hl.secondary_hazards||[]).map((h,i)=>{
                  const hc = h.level==="high"?"#EF4444":"#F59E0B";
                  return (
                    <div key={i} style={{display:"flex",gap:8,alignItems:"start",padding:"5px 0",borderBottom:"1px dashed rgba(120,180,255,0.08)"}}>
                      <span style={{fontSize:9.5,fontWeight:700,letterSpacing:".08em",color:hc,border:`1px solid ${hc}55`,borderRadius:4,padding:"1px 5px",marginTop:2,flex:"0 0 auto",textTransform:"uppercase"}}>{h.level}</span>
                      <div><div style={{fontSize:12,fontWeight:600,color:"var(--text-hi)",textTransform:"capitalize"}}>{h.hazard.replace(/_/g," ")}</div>
                        <div style={{fontSize:10.5,color:"var(--text-mid)",lineHeight:1.4}}>{h.reason}</div></div>
                    </div>
                  );
                })}
              </div>
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
            <div style={{fontSize:10.5,color:"var(--text-lo)",marginTop:10}}>
              Data: {Object.entries(hl.data_confidence||{}).map(([k,v])=>`${k} ${v?"✓":"✗"}`).join(" · ")}
            </div>
          </>)}
        </div>
      </div>
    </div>
  );
}

function FarmerScreen(){
  const CROPS = [["paddy","Paddy"],["sugarcane","Sugarcane"],["cotton","Cotton"],["groundnut","Groundnut"],["millets","Millets"],["tomato","Tomato"]];
  const STAGES = ["Sowing","Vegetative","Flowering","Grain-filling","Harvest"];
  const ICONS = { droplet: Icon.droplet, sun: Icon.flame, bug: Icon.siren, flame: Icon.flame, wind: Icon.wave, calendar: Icon.clock, leaf: Icon.leaf, chart: Icon.chart, shield: Icon.shield };
  const [crop, setCrop] = useState_s(() => { try { return localStorage.getItem("riis:farm:crop") || "paddy"; } catch(e) { return "paddy"; } });
  const [stage, setStage] = useState_s(() => { try { return localStorage.getItem("riis:farm:stage") || "Vegetative"; } catch(e) { return "Vegetative"; } });
  // the advisory has its own location so a farmer can look at any field without moving the app's location
  const [site, setSite] = useState_s(() => ({ lat: RIIS.location.lat, lon: RIIS.location.lon, label: RIIS.location.city || "Your location" }));
  const [query, setQuery] = useState_s("");
  const [results, setResults] = useState_s([]);
  const [adv, setAdv] = useState_s(null);
  const [state, setState] = useState_s("idle");
  const [err, setErr] = useState_s(null);
  const [tick, setTick] = useState_s(0);

  useEffect_s(() => { try { localStorage.setItem("riis:farm:crop", crop); localStorage.setItem("riis:farm:stage", stage); } catch(e) {} }, [crop, stage]);

  // India-wide place search (400 ms debounce, via the backend Nominatim proxy)
  useEffect_s(() => {
    if (!window.RIIS_API || query.trim().length < 2) { setResults([]); return; }
    let alive = true;
    const t = setTimeout(() => {
      const coord = query.trim().match(/^(-?\d+(\.\d+)?)[,\s]+(-?\d+(\.\d+)?)$/);
      if (coord) { setResults([{ name: `${coord[1]}, ${coord[3]}`, lat: +coord[1], lon: +coord[3] }]); return; }
      window.RIIS_API.farmerGeocode(query.trim()).then(r => { if (alive) setResults(r.results || []); }).catch(() => { if (alive) setResults([]); });
    }, 400);
    return () => { alive = false; clearTimeout(t); };
  }, [query]);

  // The advisory itself: every factor for this point, crop and stage
  useEffect_s(() => {
    if (!window.RIIS_API || site.lat == null) return;
    let alive = true;
    setState("loading"); setErr(null);
    (window.RIIS_API.ready || Promise.resolve()).then(() => window.RIIS_API.getFarmerAdvisory(site.lat, site.lon, crop, stage))
      .then(r => { if (!alive) return; setAdv(r); setState("ok"); })
      .catch(e => { if (alive) { setErr(e.message); setState("error"); } });
    return () => { alive = false; };
  }, [site.lat, site.lon, crop, stage, tick]);
  useEffect_s(() => { const iv = setInterval(() => setTick(t => t + 1), 15 * 60 * 1000); return () => clearInterval(iv); }, []);

  const color = t => t === "warn" ? "#F97316" : t === "info" ? "#22D3EE" : "#10B981";
  const lvl = l => l === "high" ? "#EF4444" : l === "moderate" ? "#F59E0B" : "#10B981";
  const fmtDay = d => d ? new Date(d + "T00:00").toLocaleDateString(undefined, { weekday: "short", day: "numeric" }) : "";
  const input = { background: "none", border: "none", outline: "none", color: "var(--text-hi)", flex: 1, fontSize: 13 };
  const a = adv;
  const soil = a && a.soil, irr = a && a.irrigation, wl = a && a.waterlogging;

  return (
    <div className="screen">
      <div className="screen-title">
        <div>
          <div className="crumb">ADVISORY <b>Farmer Module</b></div>
          <h1 style={{marginTop:6}}>Precision Agriculture &amp; Weather Advisory — {site.label}</h1>
          <p style={{marginTop:4}}>Live forecast, soil moisture at three depths, terrain, flood history and the nearest reservoir, reasoned over your crop and growth stage</p>
        </div>
        <div className="id">CROP AI · {a ? `${a.location.district || site.label} · ${a.data_sources.forecast.split(" ")[0]}` : "LOADING"}</div>
      </div>

      {/* Inputs */}
      <div className="panel brackets" style={{marginBottom:16}}>
        <div className="panel-bd" style={{display:"grid",gridTemplateColumns:"1.3fr 1fr 1fr auto",gap:12,alignItems:"end"}}>
          <div style={{position:"relative"}}>
            <div className="k mb2">FIELD LOCATION</div>
            <div style={{background:"rgba(10,18,28,0.6)",border:"1px solid var(--stroke)",borderRadius:10,padding:"9px 12px",display:"flex",alignItems:"center",gap:8}}>
              <span style={{color:"var(--cyan)"}}>{Icon.pin}</span>
              <input value={query} placeholder={`${site.label} · type a village, town or "lat, lon"`} onChange={e=>setQuery(e.target.value)} style={input}/>
              {query && <button className="chip" onClick={()=>{ setQuery(""); setResults([]); }}>×</button>}
            </div>
            {results.length > 0 && (
              <div style={{position:"absolute",left:0,right:0,top:"100%",zIndex:20,marginTop:4,border:"1px solid var(--stroke-2)",borderRadius:8,overflow:"hidden",background:"var(--bg-1)"}}>
                {results.map((r,i)=>(
                  <div key={i} onClick={()=>{ setSite({ lat:r.lat, lon:r.lon, label:(r.name||"").split(",").slice(0,2).join(",") }); setQuery(""); setResults([]); }}
                    style={{padding:"7px 10px",fontSize:12,cursor:"pointer",borderBottom:"1px solid var(--stroke)"}}>
                    {(r.name||"").split(",").slice(0,3).join(",")}{r.district ? <span className="mono" style={{color:"var(--text-lo)"}}> · {r.district}</span> : null}
                  </div>
                ))}
              </div>
            )}
            <div style={{fontSize:10.5,color:"var(--text-lo)",marginTop:4}}>{site.lat != null ? `${site.lat.toFixed(4)}, ${site.lon.toFixed(4)}` : "no location"}{a && a.location.district ? ` · ${a.location.district}, ${a.location.state || ""}` : ""}</div>
          </div>
          <div>
            <div className="k mb2">CROP TYPE</div>
            <div style={{display:"flex",gap:6,flexWrap:"wrap"}}>
              {CROPS.map(([k,l])=>(<button key={k} className={"chip"+(crop===k?" active":"")} onClick={()=>setCrop(k)}>{l}</button>))}
            </div>
          </div>
          <div>
            <div className="k mb2">GROWTH STAGE</div>
            <div style={{display:"flex",gap:6,flexWrap:"wrap"}}>
              {STAGES.map(s=>(<button key={s} className={"chip"+(stage===s?" active":"")} onClick={()=>setStage(s)}>{s}</button>))}
            </div>
          </div>
          <div style={{display:"flex",gap:6}}>
            <button className="btn ghost" onClick={()=>setSite({ lat:RIIS.location.lat, lon:RIIS.location.lon, label:RIIS.location.city || "Your location" })}>My location</button>
            <button className="btn primary" style={{padding:"10px 18px"}} onClick={()=>setTick(t=>t+1)}>{state==="loading" ? "Fetching…" : "Refresh ⚡"}</button>
          </div>
        </div>
      </div>

      {state === "error" && <div className="panel" style={{padding:12,marginBottom:16,borderLeft:"3px solid #EF4444",color:"#FCA5A5",fontSize:12.5}}>Advisory unavailable: {err}. Is the backend running?</div>}
      {state === "loading" && !a && <div className="panel" style={{padding:12,marginBottom:16,color:"var(--text-lo)",fontSize:12.5}}>Fetching forecast, soil moisture, terrain and flood history for this point… first visit to a new place takes up to 30 s.</div>}

      {a && (<>
        {/* Live strip */}
        <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(130px,1fr))",gap:10,marginBottom:16}}>
          {[
            ["Now", `${a.now.temperature != null ? a.now.temperature.toFixed(1) : "—"}°C`, `feels ${a.now.feels_like != null ? a.now.feels_like.toFixed(1) : "—"}° · RH ${a.now.humidity}%`, "#7DD3FC"],
            ["Rain now", `${a.now.rain_mm_h || 0} mm/h`, `past 7 d ${a.past_7d.rain_mm} mm`, "#22D3EE"],
            ["Next 7 days", `${irr.rain_7d_forecast_mm} mm`, `next 3 d ${irr.rain_3d_forecast_mm} mm`, "#3B82F6"],
            ["Crop water need", `${irr.etc_7d_mm} mm/wk`, `Kc ${irr.kc} · ${a.crop.stage}`, "#10B981"],
            ["Topsoil moisture", soil.moisture_0_7 != null ? `${soil.moisture_0_7} m³/m³` : "—", `${soil.saturation_pct}% saturated · ${String(soil.texture).replace("_"," ")}`, soil.saturation_pct >= 85 ? "#F59E0B" : "#10B981"],
            ["Available water", irr.plant_available_water_pct != null ? `${irr.plant_available_water_pct}%` : "—", `root zone ${a.crop.root_depth_cm} cm`, irr.plant_available_water_pct != null && irr.plant_available_water_pct < 35 ? "#F59E0B" : "#10B981"],
            ["Wind", `${a.now.wind_kmh != null ? Math.round(a.now.wind_kmh) : "—"} km/h`, `gusts to ${a.lodging.gust_max_3d_kmh} km/h (3 d)`, a.lodging.level === "high" ? "#EF4444" : "#7DD3FC"],
            ["Waterlogging", wl.level.toUpperCase(), `~${wl.ponding_hours_72h} h vs ${wl.tolerance_hours} h tolerance`, lvl(wl.level)],
          ].map(([k,v,s,c],i)=>(
            <div key={i} className="panel" style={{padding:"10px 12px",borderLeft:`3px solid ${c}`}}>
              <div className="k">{k}</div>
              <div className="num" style={{fontSize:18,fontWeight:700,color:c,marginTop:2}}>{v}</div>
              <div style={{fontSize:10.5,color:"var(--text-lo)",marginTop:2}} className="mono">{s}</div>
            </div>
          ))}
        </div>

        <div style={{display:"grid",gridTemplateColumns:"1.4fr 1fr",gap:16}}>
          <div className="vstack" style={{gap:16}}>
            <div className="panel brackets">
              <div className="panel-hd">
                <h3>Recommendations for {a.crop.name} · {a.crop.stage}</h3>
                <span className="live"><span className="d"/>{a.advisories.length} ACTIONS</span>
                <span className="sub">{a.location.district || site.label} · computed {new Date(a.computed_at + "Z").toLocaleTimeString()}</span>
              </div>
              <div className="panel-bd" style={{display:"flex",flexDirection:"column",gap:10}}>
                {a.advisories.map((x,i)=>{
                  const c = color(x.type);
                  return (
                    <div key={i} style={{display:"flex",gap:12,padding:14,background:"rgba(10,18,28,0.5)",border:"1px solid var(--stroke)",borderRadius:12,borderLeft:`3px solid ${c}`}}>
                      <div style={{width:38,height:38,borderRadius:10,background:c+"22",color:c,display:"grid",placeItems:"center",flex:"0 0 auto"}}>{ICONS[x.icon] || Icon.leaf}</div>
                      <div style={{flex:1}}>
                        <div style={{fontSize:13.5,fontWeight:600,color:"var(--text-hi)"}}>{x.title}</div>
                        <div style={{fontSize:12,color:"var(--text-mid)",marginTop:4,lineHeight:1.5}}>{x.desc}</div>
                      </div>
                      <span className="mono" style={{fontSize:10,color:c,letterSpacing:".08em",alignSelf:"start"}}>PRIORITY {x.priority}</span>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="panel brackets">
              <div className="panel-hd"><h3>7-day field forecast</h3><span className="sub">rain · temperature · ET0 · wind · UV</span></div>
              <div className="panel-bd">
                <table className="data">
                  <thead><tr><th>Day</th><th>Rain</th><th>Prob.</th><th>Tmax / Tmin</th><th>ET0</th><th>Crop need</th><th>Balance</th><th>Gusts</th><th>UV</th></tr></thead>
                  <tbody>
                    {a.forecast_7d.map((d,i)=>{ const w = irr.daily[i] || {}; const heat = a.stress.heat_days.includes(d.date), cold = a.stress.cold_days.includes(d.date);
                      return (
                        <tr key={d.date}>
                          <td style={{fontWeight:600}}>{fmtDay(d.date)}</td>
                          <td className="mono" style={{color:d.rain_mm>=20?"#F59E0B":d.rain_mm>0?"#22D3EE":"var(--text-mid)"}}>{d.rain_mm} mm</td>
                          <td className="mono" style={{color:"var(--text-mid)"}}>{d.rain_prob != null ? d.rain_prob + "%" : "—"}</td>
                          <td className="mono" style={{color: heat ? "#EF4444" : cold ? "#7DD3FC" : "var(--text-hi)"}}>{d.tmax}° / {d.tmin}°</td>
                          <td className="mono">{d.et0_mm != null ? d.et0_mm.toFixed(1) : "—"}</td>
                          <td className="mono">{w.etc_mm != null ? w.etc_mm : "—"}</td>
                          <td className="mono" style={{color: (w.balance_mm||0) >= 0 ? "#10B981" : "#F59E0B"}}>{w.balance_mm != null ? (w.balance_mm >= 0 ? "+" : "") + w.balance_mm : "—"}</td>
                          <td className="mono" style={{color:(d.gust_max||0) >= a.lodging.threshold_kmh ? "#EF4444" : "var(--text-mid)"}}>{d.gust_max != null ? Math.round(d.gust_max) : "—"}</td>
                          <td className="mono" style={{color:"var(--text-mid)"}}>{d.uv_max != null ? d.uv_max.toFixed(0) : "—"}</td>
                        </tr>
                      ); })}
                  </tbody>
                </table>
                <div style={{fontSize:10.5,color:"var(--text-lo)",marginTop:6}}>Crop need = Kc × ET0 (FAO-56). Balance = 80% of rain minus crop need. Past 7 days: {a.past_7d.rain_mm} mm rain, {a.past_7d.gdd} growing degree-days; next 7: {a.stress.gdd_next_7d} GDD.</div>
              </div>
            </div>
          </div>

          <div className="vstack" style={{gap:16}}>
            <div className="panel brackets">
              <div className="panel-hd"><h3>Soil &amp; water</h3><span className="sub">{soil.source === "soilgrids" || soil.source === "soilgrids_nearby" ? "SoilGrids + ERA5-Land" : "regional default + ERA5-Land"}</span></div>
              <div className="panel-bd">
                {[
                  ["Topsoil 0-7 cm", soil.moisture_0_7, "#22D3EE"], ["Subsoil 7-28 cm", soil.moisture_7_28, "#3B82F6"], ["Deep 28-100 cm", soil.moisture_28_100, "#7DD3FC"],
                ].map(([k,v,c],i)=>(
                  <div className="crop-gauge" key={i} style={{marginBottom:8}}>
                    <div className="lbl"><span>{k}</span><b style={{color:c}} className="num">{v != null ? v.toFixed(3) + " m³/m³" : "—"}</b></div>
                    <div className="track"><div className="fill" style={{width:(v != null ? Math.min(100, v / 0.5 * 100) : 0)+"%",background:c}}/></div>
                  </div>
                ))}
                <div className="crop-gauge" style={{marginBottom:8}}>
                  <div className="lbl"><span>Plant-available water (root zone)</span><b style={{color: irr.plant_available_water_pct < 35 ? "#F59E0B" : "#10B981"}} className="num">{irr.plant_available_water_pct != null ? irr.plant_available_water_pct + "%" : "—"}</b></div>
                  <div className="track"><div className="fill" style={{width:(irr.plant_available_water_pct||0)+"%",background: irr.plant_available_water_pct < 35 ? "#F59E0B" : "#10B981"}}/></div>
                </div>
                <div style={{fontSize:11.5,color:"var(--text-mid)",lineHeight:1.6,marginTop:6}}>
                  {String(soil.texture).replace("_"," ")} soil · infiltration {soil.infiltration_mm_h} mm/h · field capacity {irr.field_capacity_m3m3} · wilting point {irr.wilting_point_m3m3}<br/>
                  Soil temperature {soil.soil_temperature_c != null ? soil.soil_temperature_c.toFixed(1) + " °C" : "—"} · VPD {a.now.vpd_kpa != null ? a.now.vpd_kpa.toFixed(2) + " kPa" : "—"}<br/>
                  Irrigation: <b style={{color:"var(--text-hi)"}}>{irr.recommended_mm > 0 ? `${irr.recommended_mm} mm ${irr.recommended_when}` : "not needed this week"}</b>{irr.days_until_stress != null ? ` · stress in ${irr.days_until_stress} day(s) without water` : ""}
                </div>
              </div>
            </div>

            <div className="panel brackets">
              <div className="panel-hd"><h3>Risks this week</h3></div>
              <div className="panel-bd" style={{display:"flex",flexDirection:"column",gap:8,fontSize:12}}>
                {[
                  ["Waterlogging", wl.level, `${wl.ponding_hours_72h} h ponding on ${irr.rain_3d_forecast_mm} mm / 3 d · HAND ${wl.hand_m != null ? wl.hand_m + " m" : "n/a"} · drains ${wl.drainage_capacity_mm_h} mm/h`],
                  ["Disease pressure", a.disease.overall, a.disease.list.slice(0,3).map(d=>`${d.name} ${d.favourable_hours_72h} h`).join(" · ") + ` · leaf wetness ${a.disease.leaf_wetness_hours_72h} h`],
                  ["Heat stress", a.stress.heat_days.length ? (a.stress.heat_days.length >= 3 ? "high" : "moderate") : "low", a.stress.heat_days.length ? `${a.stress.heat_days.length} day(s) ≥ ${a.stress.t_heat} °C` : `no day above ${a.stress.t_heat} °C`],
                  ["Lodging / wind", a.lodging.level, `gusts to ${a.lodging.gust_max_3d_kmh} km/h vs ${a.lodging.threshold_kmh} km/h threshold`],
                  ["Flood exposure", a.context.impact_class_72h === "safe" ? "low" : a.context.impact_class_72h === "mod" ? "moderate" : "high", `impact ${a.context.impact_score_72h}/100 on 3-day rain · district floods on record: ${a.context.district_floods != null ? a.context.district_floods : "—"}`],
                ].map(([k,l,s],i)=>(
                  <div key={i} style={{display:"grid",gridTemplateColumns:"110px 70px 1fr",gap:8,alignItems:"center",padding:"6px 0",borderBottom:"1px dashed rgba(120,180,255,0.08)"}}>
                    <span style={{color:"var(--text-hi)",fontWeight:600}}>{k}</span>
                    <span className="sev" style={{color:lvl(l),background:lvl(l)+"22",fontSize:10,textAlign:"center"}}>{String(l).toUpperCase()}</span>
                    <span style={{color:"var(--text-mid)",fontSize:11}}>{s}</span>
                  </div>
                ))}
                <div style={{fontSize:11,color:"var(--text-mid)",marginTop:4}}>Pests to watch for {a.crop.name}: {a.disease.pests_to_watch.join(", ")}.</div>
              </div>
            </div>

            <div className="panel brackets">
              <div className="panel-hd"><h3>Work windows</h3><span className="sub">next 48 h sprays · 7 d harvest / sowing</span></div>
              <div className="panel-bd" style={{fontSize:12,lineHeight:1.7}}>
                <div><b style={{color:"var(--text-hi)"}}>Spraying:</b> {a.spray_windows.length ? a.spray_windows.slice(0,3).map(w=>`${w.start.slice(5).replace("T"," ")}–${w.end.slice(11)} (${w.hours} h)`).join(" · ") : "no suitable window in 48 h"}</div>
                <div><b style={{color:"var(--text-hi)"}}>Harvest:</b> {a.field.harvest_window ? `${fmtDay(a.field.harvest_window[0])} to ${fmtDay(a.field.harvest_window[1])} (${a.field.harvest_dry_days_needed} dry days)` : `no ${a.field.harvest_dry_days_needed}-day dry run this week`}</div>
                <div><b style={{color:"var(--text-hi)"}}>Sowing / transplanting:</b> {a.field.sowing_ok_now ? "conditions favourable now" : "hold — see recommendations"}</div>
                {a.context.reservoir && <div><b style={{color:"var(--text-hi)"}}>Nearest reservoir:</b> {a.context.reservoir.name} {a.context.reservoir.storage_pct != null ? `${a.context.reservoir.storage_pct}% full` : ""} · {a.context.reservoir.distance_km} km{a.context.reservoir.observed_at ? ` · report ${a.context.reservoir.observed_at}` : " · seeded"}</div>}
                <div style={{fontSize:10.5,color:"var(--text-lo)",marginTop:4}}>Sources: {a.data_sources.forecast}; soil {a.data_sources.soil || "default"}; terrain {a.data_sources.terrain ? "SRTM" : "pending"}; {a.data_sources.flood_history ? "India Flood Inventory" : ""}. Refreshes every 15 min.</div>
              </div>
            </div>
          </div>
        </div>
      </>)}
    </div>
  );
}

function ReservoirScreen(){
  const [sel, setSel] = useState_s(() => RIIS.reservoirs[0]);
  const [status, setStatus] = useState_s(null);
  const [hist, setHist] = useState_s(null);
  const [syncing, setSyncing] = useState_s(false);
  const [tick, setTick] = useState_s(0);
  const p = RIIS.prediction;
  const SRC = { cmwssb: ["CMWSSB", "#22D3EE"], kseb: ["KSEB", "#A78BFA"], manual: ["MANUAL", "#F59E0B"], seed: ["SEEDED", "#64748B"] };

  // Feed status once; history whenever the selection changes
  useEffect_s(() => {
    let alive = true;
    if (!window.RIIS_API) return;
    (window.RIIS_API.ready || Promise.resolve()).then(() => window.RIIS_API.getReservoirStatus())
      .then(r => { if (alive) setStatus(r); }).catch(() => {});
    return () => { alive = false; };
  }, [tick]);
  useEffect_s(() => {
    let alive = true;
    setHist(null);
    if (!window.RIIS_API || !sel || sel.source !== "cmwssb") return;
    window.RIIS_API.getReservoirHistory(sel.id, 14).then(r => { if (alive) setHist(r.history || []); }).catch(() => {});
    return () => { alive = false; };
  }, [sel && sel.id, tick]);

  const refresh = () => {
    if (!window.RIIS_API || syncing) return;
    setSyncing(true);
    window.RIIS_API.syncReservoirs()
      .then(() => window.syncRiisBackendData ? window.syncRiisBackendData() : null)
      .then(() => { const cur = RIIS.reservoirs.find(r => r.id === (sel && sel.id)) || RIIS.reservoirs[0]; setSel(cur); setTick(t => t + 1); })
      .catch(() => {}).finally(() => setSyncing(false));
  };

  // mcft per day gained at the current net inflow (1 mcft = 28,316.8 m³)
  const netMcftDay = (r) => ((r.inflow || 0) - (r.outflow || 0)) * 86400 / 28316.8;
  const pctOf = (r) => r.pct != null ? r.pct : Math.round(1000 * r.cur / r.cap) / 10;
  const daysToFull = (r) => { const n = netMcftDay(r); return n > 0.5 ? Math.round((r.cap - r.cur) / n) : null; };

  // Trajectory: observed daily storage % (CMWSSB) followed by a net-flow projection
  const traj = (() => {
    if (!sel) return { labels: [], series: [] };
    const cap = sel.cap || 1;
    const obs = (hist && hist.length ? hist : []).map(h => ({ d: h.date.slice(5), pct: h.storage_pct != null ? h.storage_pct : Math.round(1000 * h.storage_mcft / cap) / 10, inflow: h.inflow_cms, outflow: h.outflow_cms }));
    const basePct = pctOf(sel);
    const perDay = netMcftDay(sel) / cap * 100;
    const rainBoost = Math.max(0, (p.rainfall_mm || 0) - 5) * 0.15;   // forecast rain lifts the projection
    const proj = [1, 2, 3].map(k => Math.max(0, Math.min(100, basePct + perDay * k + rainBoost * k)));
    const labels = [...obs.map(o => o.d), "today", "+1d", "+2d", "+3d"];
    const storage = [...obs.map(o => o.pct), basePct, ...proj];
    const inflow = [...obs.map(o => o.inflow), sel.inflow, sel.inflow, sel.inflow, sel.inflow];
    return { labels, series: [{ name: "Storage %", color: "#22D3EE", data: storage }, { name: "Inflow m³/s", color: "#3B82F6", data: inflow }], nObs: obs.length };
  })();

  const feedLine = status && status.sources ? Object.entries(status.sources).map(([k, v]) => `${k.toUpperCase()} ${v.ok ? (v.as_on || "ok") : "offline"}`).join(" · ") : "feed status pending";
  const liveCount = RIIS.reservoirs.filter(r => r.source && r.source !== "seed").length;

  return (
    <div className="screen">
      <div className="screen-title">
        <div>
          <div className="crumb">INFRASTRUCTURE <b>Reservoir Intelligence</b></div>
          <h1 style={{marginTop:6}}>Reservoir Network — Hydrological Inflow &amp; Storage</h1>
          <p style={{marginTop:4}}>Daily reports from Chennai Metro Water and KSEB · {liveCount} of {RIIS.reservoirs.length} reservoirs on a live feed · {feedLine}</p>
        </div>
        <div style={{display:"flex",gap:8,alignItems:"center"}}>
          <button className="btn ghost" onClick={refresh} disabled={syncing}>{syncing ? "Fetching…" : "Refresh feeds"}</button>
          <div className="id">HYDROLOGY · {liveCount ? "LIVE REPORTS" : "SEEDED"}</div>
        </div>
      </div>

      {/* Reservoir grid */}
      <div className="reservoir-grid" style={{gridTemplateColumns:"repeat(auto-fill,minmax(230px,1fr))"}}>
        {RIIS.reservoirs.map(r=>{
          const c = riskColor(r.class);
          const fillPct = Math.round(pctOf(r));
          const [srcLbl, srcCol] = SRC[r.source] || SRC.seed;
          const ly = r.last_year_mcft != null && r.cur != null ? Math.round(r.cur - r.last_year_mcft) : null;
          return (
            <div key={r.id} className="panel brackets" onClick={()=>setSel(r)} style={{cursor:"pointer",padding:14,borderColor:sel&&sel.id===r.id?c:undefined}}>
              <div style={{display:"flex",justifyContent:"space-between",alignItems:"center"}}>
                <div>
                  <div className="k" style={{display:"flex",gap:6,alignItems:"center"}}>{r.id} · <span style={{color:srcCol,fontWeight:700}}>{srcLbl}</span>{r.observed_at && <span style={{color:"var(--text-lo)"}}>{r.observed_at.slice(5)}</span>}</div>
                  <div style={{fontSize:15,fontWeight:700,marginTop:2}}>{r.name}</div>
                </div>
                <span className="sev" style={{color:c,background:c+"22"}}>{r.alert_level ? r.alert_level.toUpperCase()+" ALERT" : riskLabel(r.class)}</span>
              </div>
              <div style={{display:"flex",alignItems:"center",gap:10,marginTop:12}}>
                <CircularGauge value={fillPct} size={90} thickness={8} color={c} label={fillPct+"%"} sublabel="FILL"/>
                <div style={{fontSize:11,color:"var(--text-mid)",lineHeight:1.6}}>
                  <div>Cap · <b className="mono" style={{color:"var(--text-hi)"}}>{Math.round(r.cap).toLocaleString()} mcft</b></div>
                  <div>Cur · <b className="mono" style={{color:"var(--text-hi)"}}>{Math.round(r.cur).toLocaleString()} mcft</b></div>
                  {r.level_ft != null && <div>Level · <b className="mono" style={{color:"var(--text-hi)"}}>{r.level_ft}</b>{r.full_level_ft != null && <span> / {r.full_level_ft} ft</span>}</div>}
                  <div>In · <b className="mono" style={{color:"#5EEAD4"}}>+{Math.round(r.inflow*10)/10} m³/s</b> · Out · <b className="mono" style={{color:"#FCA5A5"}}>−{Math.round(r.outflow*10)/10}</b></div>
                  {ly != null && <div>vs last yr · <b className="mono" style={{color:ly>=0?"#5EEAD4":"#FCA5A5"}}>{ly>=0?"+":""}{ly.toLocaleString()} mcft</b></div>}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {sel && (
      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:16,marginTop:16}}>
        <div className="panel brackets">
          <div className="panel-hd">
            <h3>{sel.name} · Storage Trajectory</h3>
            <span className="live"><span className="d"/>{sel.source === "cmwssb" ? (hist ? `${traj.nObs} OBSERVED DAYS` : "LOADING HISTORY") : (SRC[sel.source] || SRC.seed)[0]}</span>
            <span className="sub">{sel.source === "cmwssb" ? "CMWSSB daily reports → net-flow projection" : "net-flow projection from today's report"}</span>
          </div>
          <div className="panel-bd">
            <LineChart w={620} h={220} xLabels={traj.labels} series={traj.series}/>
            <div style={{fontSize:10.5,color:"var(--text-lo)",marginTop:6}}>
              Projection: storage {pctOf(sel)}% {netMcftDay(sel)>=0?"+":""}{Math.round(netMcftDay(sel)*10)/10} mcft/day at today's net inflow
              {p.rainfall_mm > 5 ? `, lifted by the ${p.rainfall_mm} mm forecast` : ""}.
              {daysToFull(sel) != null ? ` About ${daysToFull(sel)} days to full tank at this rate.` : " Not filling at today's rate."}
            </div>
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
                  {sel.class==="extreme" ? "Controlled release — open gates" : sel.class==="high" ? "Pre-release ahead of forecast rain" : pctOf(sel) < 40 ? "Conserve storage" : "Normal gate configuration"}
                </div>
                <div style={{fontSize:11.5,color:"var(--text-mid)",marginTop:8,lineHeight:1.6}}>
                  Storage: <b className="mono" style={{color:"var(--text-hi)"}}>{Math.round(sel.cur).toLocaleString()} / {Math.round(sel.cap).toLocaleString()} mcft ({pctOf(sel)}%)</b><br/>
                  Inflow <b className="mono" style={{color:"#5EEAD4"}}>{Math.round(sel.inflow*10)/10} m³/s</b> · Outflow <b className="mono" style={{color:"#FCA5A5"}}>{Math.round(sel.outflow*10)/10} m³/s</b> · net <b className="mono" style={{color:"var(--text-hi)"}}>{Math.round(netMcftDay(sel)*10)/10} mcft/day</b><br/>
                  {sel.rainfall_mm != null && <span>Rain at dam: <b className="mono" style={{color:"var(--text-hi)"}}>{sel.rainfall_mm} mm</b> · </span>}
                  {sel.last_year_mcft != null && <span>Same day last year: <b className="mono" style={{color:"var(--text-hi)"}}>{Math.round(sel.last_year_mcft).toLocaleString()} mcft</b><br/></span>}
                  {sel.remarks && <span>Operator note: <b style={{color:"var(--text-hi)"}}>{sel.remarks}</b><br/></span>}
                  Source: <b className="mono" style={{color:(SRC[sel.source]||SRC.seed)[1]}}>{(SRC[sel.source]||SRC.seed)[0]}{sel.observed_at ? ` · report of ${sel.observed_at}` : ""}</b>
                  {sel.source_url && <span> · <a href={sel.source_url} target="_blank" rel="noreferrer" style={{color:"var(--cyan)"}}>open report</a></span>}
                  {sel.source === "seed" && <span style={{color:"#F59E0B"}}><br/>No public daily feed for this reservoir yet (CWC weekly bulletin is PDF only); values are placeholders.</span>}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
      )}
    </div>
  );
}

window.SimulateScreen = SimulateScreen;
window.FarmerScreen = FarmerScreen;
window.ReservoirScreen = ReservoirScreen;
