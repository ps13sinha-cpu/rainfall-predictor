// RIIS — Main Dashboard with Real-Time Data Integration
const { useState: useState_d, useEffect: useEffect_d, useMemo: useMemo_d } = React;

function LiveWeatherCard({ lbl, val, unit, trend, icon, color="var(--cyan)", extra }){
  return (
    <div className="wxcard">
      <div className="lbl">{icon}{lbl}</div>
      <div className="val num">{val}<small>{unit}</small></div>
      {extra}
      {trend && <div className={"trend "+(trend.dir==="up"?"up":trend.dir==="dn"?"dn":"")}>
        {trend.dir==="up"?"↑":trend.dir==="dn"?"↓":"→"} {trend.text}
      </div>}
    </div>
  );
}

function ImpactCard({ imp }){
  const c = riskColor(imp.class);
  return (
    <div className="impact">
      <div className="side-bar" style={{background:c}}/>
      <div className="gauge-mini">
        <CircularGauge value={imp.unit==="m³/s"? Math.min(100, Math.round(imp.value*0.6)) : imp.value} size={70} thickness={6} color={c}
          label={imp.value} sublabel={imp.unit}/>
      </div>
      <div className="info">
        <div className="lbl">{imp.name}</div>
        <div className="sev" style={{color:c,background:c+"22"}}>{riskLabel(imp.class)}</div>
        <Sparkline data={[
          Math.max(1, Math.round(imp.value*0.65)),
          Math.max(1, Math.round(imp.value*0.75)),
          Math.max(1, Math.round(imp.value*0.88)),
          Math.max(1, Math.round(imp.value*0.95)),
          imp.value,
          Math.round(imp.value*1.05),
          Math.round(imp.value*1.08)
        ]} w={110} h={22} color={c} dots={false}/>
      </div>
    </div>
  );
}

function AISystemStatus(){
  const items = Object.values(RIIS.systems);
  return (
    <div className="panel brackets">
      <div className="panel-hd">
        <h3>AI System Status</h3>
        <span className="live"><span className="d"/>LIVE</span>
        <span className="sub">{RIIS.systems.ai.version}</span>
      </div>
      <div className="panel-bd">
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8}}>
          {items.map((s,i)=>(
            <div key={i} style={{display:"flex",alignItems:"center",gap:8,padding:"6px 8px",background:"rgba(10,18,28,0.5)",borderRadius:8,border:"1px solid var(--stroke)"}}>
              <span style={{width:6,height:6,borderRadius:"50%",background:s.status==="nominal"?"#10B981":"#F59E0B",boxShadow:`0 0 6px ${s.status==="nominal"?"#10B981":"#F59E0B"}`}}/>
              <span style={{fontSize:11,color:"var(--text-hi)",fontWeight:500,flex:1,minWidth:0,overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{s.name}</span>
              <span className="mono" style={{fontSize:9.5,color:"var(--text-lo)",letterSpacing:".06em"}}>
                {s.latency? s.latency+"ms": s.count? "×"+s.count : "OK"}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function RiskIndexPanel(){
  return (
    <div className="panel brackets">
      <div className="panel-hd">
        <h3>Today's Risk Index</h3>
        <span className="live" style={{background:riskColor(RIIS.riskClass)+"22", color:riskColor(RIIS.riskClass)}}><span className="d" style={{background:riskColor(RIIS.riskClass)}}/>LIVE</span>
        <span className="sub">RIIS-COMPOSITE-v4.2</span>
      </div>
      <div className="panel-bd" style={{display:"grid",gridTemplateColumns:"auto 1fr",gap:20,alignItems:"center"}}>
        <HalfGauge value={RIIS.riskIndex} color={riskColor(RIIS.riskClass)} label="RISK INDEX / 100" size={210}/>
        <div>
          <div className="k mb2">CLASSIFICATION</div>
          <div style={{fontSize:22,fontWeight:700,color:riskColor(RIIS.riskClass),letterSpacing:"-0.01em"}}>{riskLabel(RIIS.riskClass)}</div>
          <div style={{fontSize:11.5,color:"var(--text-mid)",marginTop:8,lineHeight:1.5}}>
            Composite of ten live factor groups for <b style={{color:"var(--text-hi)"}}>{RIIS.location.city}</b>. Peak risk window: <b className="mono" style={{color:"var(--text-hi)"}}>{RIIS.prediction.peakRiskWindow}</b>.
          </div>
          <div style={{display:"flex",gap:6,marginTop:12,flexWrap:"wrap"}}>
            <span className="chip active">Local</span>
            <span className="chip">District</span>
            <span className="chip">State</span>
            <span className="chip">National</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function DashboardScreen({ go }){
  const l = RIIS.location, w = RIIS.live, p = RIIS.prediction;
  const [tick, setTick] = useState_d(0);
  useEffect_d(()=>{ const i = setInterval(()=>setTick(t=>t+1),1000); return ()=>clearInterval(i); },[]);

  const nowTimeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const isHighRadar = (w.cloudCover > 70 || p.rainfall_mm > 2 || w.currentRain > 0);

  return (
    <div className="screen">
      {/* Title */}
      <div className="screen-title">
        <div>
          <div className="crumb">
            {(l.city || "LOCAL").toUpperCase()} {l.state ? `/ ${l.state.toUpperCase()}` : ''} {l.country ? `/ ${l.country.toUpperCase()}` : ''} <b>Live Dashboard</b>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 6, flexWrap: "wrap" }}>
            <h1 style={{ margin: 0 }}>{l.city} — Rainfall Impact Intelligence</h1>
            <button
              className={`btn locate-badge-btn ${window.RIIS?.locationLoading ? 'loading' : ''} ${window.RIIS?.isDeviceLocation ? 'active' : ''}`}
              onClick={() => window.relocateFromDevice ? window.relocateFromDevice() : (window.fetchDeviceLocationAndWeather && window.fetchDeviceLocationAndWeather(true))}
              title="Forget the saved location and locate from this device"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "4px 10px",
                fontSize: 11,
                borderRadius: 20,
                border: "1px solid var(--stroke)",
                background: window.RIIS?.isDeviceLocation ? "rgba(34,211,238,0.15)" : "rgba(10,18,28,0.4)",
                color: window.RIIS?.isDeviceLocation ? "var(--cyan)" : "var(--text-mid)",
                cursor: "pointer",
                transition: "all 0.2s"
              }}
            >
              {window.RIIS?.locationLoading ? (
                <>
                  <span className="spinner-mini" style={{ width: 10, height: 10, display: "inline-block" }} />
                  <span>Fetching GPS...</span>
                </>
              ) : window.RIIS?.isDeviceLocation ? (
                <>
                  <span style={{ display: "inline-block", width: 6, height: 6, borderRadius: "50%", background: "var(--cyan)", boxShadow: "0 0 6px var(--cyan)" }} />
                  <span>Live GPS Connected</span>
                </>
              ) : (
                <>
                  {Icon.pin}
                  <span>Fetch Device Location</span>
                </>
              )}
            </button>
          </div>
          <p style={{marginTop:4}}>
            <span className="mono">{l.lat.toFixed(4)}°N {l.lon.toFixed(4)}°E {l.elevation ? `· ELEV ${l.elevation}m` : ''}</span>
            &nbsp;·&nbsp; Weather condition: <b style={{color:"var(--cyan)"}}>{w.weatherDesc}</b> · Last live sync <b className="mono" style={{color:"var(--text-hi)"}}>Just now</b>
          </p>
        </div>
        <div className="id">SESSION · RIIS-{("00000"+((tick%1000)+42871)).slice(-5)} · T+{("00"+Math.floor(tick/60)).slice(-2)}:{("00"+(tick%60)).slice(-2)}</div>
      </div>

      {/* Live weather row */}
      <div className="wxrow">
        <LiveWeatherCard lbl={<>{Icon.sun} Temperature</>} val={w.temperature.toFixed(1)} unit="°C"
          extra={<div style={{fontSize:11,color:"var(--text-mid)"}}>Feels like <b className="num">{w.feels.toFixed(1)}°C</b> · Dew {w.dewPoint}°C</div>}
          trend={{dir: w.tempTrend.startsWith("-")?"dn":"up", text: w.tempTrend}}/>
        
        <LiveWeatherCard lbl={<>{Icon.droplet} Humidity</>} val={w.humidity} unit="%"
          extra={<div className="crop-gauge"><div className="track"><div className="fill" style={{width:w.humidity+"%",background:"linear-gradient(90deg,#22D3EE,#3B82F6)"}}/></div></div>}
          trend={{dir: w.humidity>80?"up":"dn", text: w.humidity>80?"High moisture":"Optimal"}}/>
        
        <LiveWeatherCard lbl={<>{Icon.wave} Pressure</>} val={w.pressure} unit="hPa"
          extra={<div style={{fontSize:11,color:w.pressure<1005?"#FCA5A5":"var(--text-mid)"}}>{w.pressureTrend}</div>}
          trend={{dir: w.pressureDelta.startsWith("-")?"dn":"up", text: w.pressureDelta}}/>
        
        <LiveWeatherCard lbl={<>{Icon.wind} Wind</>} val={w.windSpeed} unit="km/h"
          extra={<div style={{display:"flex",alignItems:"center",gap:8}}>
            <WindCompass dir={w.windDir} speed={w.windSpeed} size={44}/>
            <div style={{fontSize:11,color:"var(--text-mid)"}}>{w.windDirLabel} · {w.windDir}°<br/><span className="mono" style={{color:"var(--text-lo)"}}>Gusts {w.windGusts} km/h</span></div>
          </div>}/>
        
        <LiveWeatherCard lbl={<>{Icon.eye} Visibility</>} val={w.visibility} unit="km"
          extra={<div style={{fontSize:11,color:w.visibility<5?"#FCA5A5":"var(--text-mid)"}}>{w.visibilityStatus}</div>}
          trend={{dir: w.visibility<8?"dn":"up", text: w.visibility<8?"Scatter":"Optimal"}}/>
      </div>

      {/* Second row */}
      <div className="wxrow" style={{gridTemplateColumns:"repeat(5,1fr)"}}>
        <LiveWeatherCard lbl={<>{Icon.cloud} Cloud Cover</>} val={w.cloudCover} unit="%"
          extra={<div style={{fontSize:11,color:"var(--text-mid)"}}>{w.weatherDesc}</div>}/>
        
        <LiveWeatherCard lbl={<>{Icon.radar} Radar Activity</>} val={isHighRadar ? "ACTIVE" : "QUIET"} unit=""
          extra={<div style={{fontSize:11,color:"var(--text-mid)"}}>{w.currentRain>0 ? "Echoes 35-50 dBZ" : w.cloudCover>60 ? "Scattered 15-30 dBZ" : "Clean scan <10 dBZ"} · <b style={{color:isHighRadar?"#FCA5A5":"#5EEAD4"}}>{w.currentRain>0 ? "Precip Cell" : "Nominal"}</b></div>}/>
        
        <LiveWeatherCard lbl={<>{Icon.layer} INSAT / Satellite</>} val="LIVE" unit=""
          extra={<div style={{fontSize:11,color:"var(--text-mid)"}}>Cloud Top {w.cloudCover>60?"-58°C":"-12°C"} · <b className="mono" style={{color:"#5EEAD4"}}>IR+VIS</b></div>}/>
        
        <LiveWeatherCard lbl={<>{Icon.leaf} Air Quality</>} val={w.aqi} unit="AQI"
          extra={<div style={{display:"flex",justifyContent:"space-between",fontSize:11,marginTop:4}}><span style={{color:w.aqi<=50?"#10B981":w.aqi<=100?"#F59E0B":"#EF4444"}}>{w.aqiLabel}</span><span className="mono" style={{color:"var(--text-lo)"}}>US-AQI</span></div>}/>
        
        <LiveWeatherCard lbl={<>{Icon.flame} UV Index</>} val={w.uv} unit=""
          extra={<div style={{fontSize:11,color:"var(--text-mid)"}}>{w.uv>8?"Very High":w.uv>5?"Moderate":w.uv>2?"Low":"Minimal"}</div>}/>
      </div>

      {/* Main split: prediction hero + right column */}
      <div style={{display:"grid",gridTemplateColumns:"1.55fr 1fr",gap:16,marginTop:4}}>
        {/* Prediction Hero */}
        <div className="pred-hero">
          <div className="grid-bg"/>
          <div style={{position:"absolute",top:16,left:22,display:"flex",alignItems:"center",gap:10,zIndex:2}}>
            <h3 style={{fontSize:12,fontWeight:600,letterSpacing:".14em",textTransform:"uppercase",color:"var(--text-mid)"}}>AI Rainfall Prediction</h3>
            <span className="live"><span className="d"/>ConvLSTM</span>
          </div>
          <div style={{position:"absolute",top:16,right:22,zIndex:2}}>
            <div className="tabs">
              <button>Now</button>
              <button className="active">+3h</button>
              <button>+12h</button>
              <button>+24h</button>
            </div>
          </div>

          <div className="pred-hero-inner" style={{marginTop:36}}>
            <div>
              <div className="pred-big">
                <div className="kicker" style={{color:riskColor(p.class)}}>{p.kicker}</div>
                <h2>{p.title}</h2>
                <div className="mm">{p.rainfall_mm}<small>mm / 6h</small></div>
                <div className="conf">
                  {Icon.brain}
                  <span>CONFIDENCE {p.confidence}% · RAIN PROB {p.probability}%</span>
                </div>
              </div>
              <div className="pred-meta">
                <div className="m"><div className="l">Current Time</div><div className="v mono">{nowTimeStr}<small>LOC</small></div></div>
                <div className="m"><div className="l">Rainfall Category</div><div className="v" style={{fontSize:13}}>{p.intensity}</div></div>
                <div className="m"><div className="l">Storm Movement</div><div className="v mono">{p.stormDir}<small>@{p.stormSpeed}km/h</small></div></div>
                <div className="m"><div className="l">Rain Duration</div><div className="v mono">{Math.floor(p.duration_min/60)}h {p.duration_min%60}m</div></div>
                <div className="m"><div className="l">Precip. Onset</div><div className="v mono" style={{color:"var(--cyan)"}}>{p.startsInText}</div></div>
                <div className="m"><div className="l">Peak Intensity</div><div className="v mono">{p.peak_intensity}<small>mm/hr</small></div></div>
              </div>
            </div>
            <div className="radar-wrap">
              <RainCurtain intensity={p.rainfall_mm > 20 ? 0.85 : p.rainfall_mm > 2 ? 0.4 : 0.05} w={310} h={280}/>
              <div style={{position:"absolute",inset:0,display:"grid",placeItems:"center"}}>
                <RadarSweep size={300} cityName={l.city.toUpperCase()} stormDir={p.stormDir} stormSpeed={p.stormSpeed}/>
              </div>
            </div>
          </div>
        </div>

        {/* Right col */}
        <div className="vstack" style={{gap:16}}>
          <RiskIndexPanel/>
          <AISystemStatus/>
        </div>
      </div>

      {/* Impact Intelligence Engine */}
      <div className="panel brackets" style={{marginTop:16}}>
        <div className="panel-hd">
          <h3>AI Rainfall Impact Intelligence Engine</h3>
          <span className="live"><span className="d"/>10 FACTOR GROUPS</span>
          <span className="sub">Ensemble Vote · 8 trained models · SHAP</span>
          <div style={{marginLeft:12,display:"flex",gap:6}}>
            <button className="btn ghost">Export Data</button>
            <button className="btn primary" onClick={()=>go("#/simulate")}>Simulate Flood →</button>
          </div>
        </div>
        <div className="panel-bd">
          <div className="impact-grid">
            {RIIS.impacts.map(i => <ImpactCard key={i.id} imp={i}/>)}
          </div>
        </div>
      </div>

      {/* Bottom row: Alerts + Timeline mini */}
      <div style={{display:"grid",gridTemplateColumns:"1.1fr 1fr",gap:16,marginTop:16}}>
        <div className="panel brackets">
          <div className="panel-hd">
            <h3>Confidence-Based Alerts &amp; Advisories</h3>
            <span className="live"><span className="d"/>{RIIS.alerts.length} ACTIVE</span>
            <span className="sub">Live for {l.city}</span>
            <button className="btn ghost" style={{marginLeft:12}} onClick={()=>go("#/alerts")}>All →</button>
          </div>
          <div className="panel-bd" style={{display:"flex",flexDirection:"column",gap:10}}>
            {RIIS.alerts.slice(0,3).map(a=>{
              const c = riskColor(a.sev);
              return (
                <div key={a.id} className="alert-item">
                  <div className="icb" style={{background:c+"22",color:c}}>{Icon.siren}</div>
                  <div className="body">
                    <div className="h">
                      <span>{a.title}</span>
                      <span className="sev" style={{color:c,background:c+"22",padding:"2px 6px",borderRadius:4,fontSize:9.5,fontFamily:"JetBrains Mono",letterSpacing:".08em"}}>{riskLabel(a.sev)} · {a.conf}%</span>
                      <span className="meta">{a.ago} · {a.area}</span>
                    </div>
                    <div className="d">{a.body}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="panel brackets">
          <div className="panel-hd">
            <h3>Rainfall &amp; Risk — 24-hour Trajectory</h3>
            <span className="sub">Live Open-Meteo Forecast</span>
            <button className="btn ghost" style={{marginLeft:"auto"}} onClick={()=>go("#/timeline")}>Full →</button>
          </div>
          <div className="panel-bd">
            <LineChart
              w={560} h={210}
              xLabels={RIIS.timeline.slice(0,8).map(t=>t.t)}
              series={[
                { name:"Rainfall (mm)", color:"#22D3EE", data: RIIS.timeline.slice(0,8).map(t=>t.rain) },
                { name:"Risk (0–100)",  color:"#F97316", data: RIIS.timeline.slice(0,8).map(t=>t.risk) },
                { name:"Confidence (%)",color:"#A78BFA", data: RIIS.timeline.slice(0,8).map(t=>t.conf) },
              ]}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

window.DashboardScreen = DashboardScreen;
