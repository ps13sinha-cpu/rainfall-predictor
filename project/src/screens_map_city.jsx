// RIIS — India Map & Hyperlocal City View with Real-Time Data Sync
const { useState: useState_mc, useEffect: useEffect_mc } = React;

function MapScreen({ go }){
  const [selected, setSelected] = useState_mc(() => RIIS.districts[0]);
  const [hover, setHover] = useState_mc(null);
  const [filter, setFilter] = useState_mc("all");
  const filtered = filter==="all" ? RIIS.districts : RIIS.districts.filter(d=>d.class===filter);

  return (
    <div className="screen">
      <div className="screen-title">
        <div>
          <div className="crumb">MAPS <b>National Risk Matrix</b></div>
          <h1 style={{marginTop:6}}>National Risk Overlay &amp; Live Stations</h1>
          <p style={{marginTop:4}}>Live weather &amp; AI-classified rainfall risk across <b className="mono" style={{color:"var(--text-hi)"}}>{RIIS.districts.length} regional sectors</b></p>
        </div>
        <div className="id">MODE · INDIA-GRID · WGS-84</div>
      </div>

      <div style={{display:"grid",gridTemplateColumns:"1.55fr 1fr",gap:16}}>
        <div className="panel brackets" style={{padding:12}}>
          <div style={{display:"flex",alignItems:"center",gap:10,padding:"6px 8px 12px",flexWrap:"wrap"}}>
            <div className="tabs">
              {["all","extreme","high","mod","safe"].map(f=>(
                <button key={f} className={filter===f?"active":""} onClick={()=>setFilter(f)}>{f==="all"?"All":riskLabel(f)}</button>
              ))}
            </div>
            <span className="chip active">Live Doppler</span>
            <span className="chip">Satellite IR</span>
            <span className="chip">Reservoirs</span>
            <span className="mono" style={{marginLeft:"auto",color:"var(--text-lo)",fontSize:11}}>{filtered.length}/{RIIS.districts.length} SHOWN</span>
          </div>
          <IndiaMap districts={filtered} selectedCode={selected?.code} onSelect={setSelected} hover={hover} setHover={setHover}/>
        </div>

        {selected && <DistrictPanel d={selected} go={go}/>}
      </div>

      {/* Bottom: Top-risk table */}
      <div className="panel brackets" style={{marginTop:16}}>
        <div className="panel-hd">
          <h3>Active Regional Risk Summary</h3>
          <span className="sub">Live Open-Meteo &amp; Doppler Data</span>
        </div>
        <div className="panel-bd" style={{padding:0}}>
          <table className="data">
            <thead>
              <tr>
                <th>Rank</th><th>District / City</th><th>Sector</th><th>Risk Index</th><th>Classification</th>
                <th>Rainfall</th><th>Population</th><th>Action</th>
              </tr>
            </thead>
            <tbody>
              {[...RIIS.districts].sort((a,b)=>b.risk-a.risk).slice(0,8).map((d,i)=>{
                const c = riskColor(d.class);
                return (
                  <tr key={d.code} style={{cursor:"pointer",background:selected?.code===d.code?"rgba(34,211,238,0.05)":undefined}} onClick={()=>setSelected(d)}>
                    <td className="mono" style={{color:"var(--text-lo)"}}>#{String(i+1).padStart(2,"0")}</td>
                    <td style={{fontWeight:600}}>{d.name} {d.isUser && <span className="chip active" style={{fontSize:9,padding:"1px 5px",marginLeft:4}}>YOU</span>}</td>
                    <td style={{color:"var(--text-mid)"}}>{d.code.split("-")[0]}</td>
                    <td>
                      <div style={{display:"flex",alignItems:"center",gap:8}}>
                        <div style={{width:80,height:6,background:"rgba(20,32,48,0.7)",borderRadius:3,overflow:"hidden"}}>
                          <div style={{width:d.risk+"%",height:"100%",background:c,boxShadow:`0 0 6px ${c}`}}/>
                        </div>
                        <span className="mono" style={{color:c,fontWeight:600}}>{d.risk}</span>
                      </div>
                    </td>
                    <td><span className="sev" style={{color:c,background:c+"22"}}>{riskLabel(d.class)}</span></td>
                    <td className="mono">{d.rain.toFixed(1)} mm</td>
                    <td className="mono" style={{color:"var(--text-mid)"}}>{(d.pop/1_000_000).toFixed(2)}M</td>
                    <td>
                      <button 
                        className="btn" 
                        style={{padding:"4px 10px",fontSize:11}}
                        onClick={(e)=>{
                          e.stopPropagation();
                          if (window.searchAndLoadLocation) {
                            window.searchAndLoadLocation(d.name);
                          }
                        }}
                      >
                        Load Live ⚡
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function DistrictPanel({ d, go }){
  const c = riskColor(d.class);
  return (
    <div className="panel brackets" style={{alignSelf:"start"}}>
      <div className="panel-hd">
        <h3>Sector Detail</h3>
        <span className="live" style={{background:c+"22",color:c}}><span className="d" style={{background:c,boxShadow:`0 0 6px ${c}`}}/>{riskLabel(d.class)}</span>
        <span className="sub mono">{d.code}</span>
      </div>
      <div className="panel-bd">
        <div style={{display:"flex",alignItems:"center",gap:14}}>
          <HalfGauge value={d.risk} color={c} size={140} label="RISK"/>
          <div>
            <div style={{fontSize:22,fontWeight:700,letterSpacing:"-0.02em"}}>{d.name}</div>
            <div style={{fontSize:11,color:"var(--text-mid)",marginTop:2}} className="mono">EST POP {(d.pop/1_000_000).toFixed(2)}M · PREDICTED RAIN {d.rain.toFixed(1)}mm</div>
            <div style={{display:"flex",gap:6,marginTop:10}}>
              <button 
                className="btn primary" 
                style={{padding:"6px 12px",fontSize:11}}
                onClick={()=>{
                  if (window.searchAndLoadLocation) {
                    window.searchAndLoadLocation(d.name);
                  }
                }}
              >
                Set as Active Location 📍
              </button>
            </div>
          </div>
        </div>

        <div style={{marginTop:16,display:"grid",gridTemplateColumns:"1fr 1fr",gap:8}}>
          {[
            ["Predicted Rainfall", d.rain.toFixed(1)+" mm"],
            ["Flood Risk", Math.round(d.risk*0.85)+"%"],
            ["Drainage Status", d.risk>60?"Critical Load":"Nominal"],
            ["Waterlogging Index", Math.round(d.risk*0.75)+"%"],
            ["Population at Risk", (d.pop*d.risk/100/1000).toFixed(0)+"K"],
            ["Infrastructure Load", Math.round(d.risk*0.6)+"%"]
          ].map(([k,v],i)=>(
            <div key={i} style={{padding:10,background:"rgba(10,18,28,0.5)",border:"1px solid var(--stroke)",borderRadius:8}}>
              <div className="k">{k}</div>
              <div style={{fontWeight:600,marginTop:2,fontSize:13}} className="num">{v}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function CityScreen({ go }){
  const cityName = RIIS.location.city || "Local";
  const wards = RIIS.chennaiWards || [];
  const [selected, setSelected] = useState_mc(() => wards[0] || null);

  useEffect_mc(() => {
    if (wards.length > 0 && (!selected || !wards.find(w => w.id === selected.id))) {
      setSelected(wards[0]);
    }
  }, [wards]);

  return (
    <div className="screen">
      <div className="screen-title">
        <div>
          <div className="crumb">MAPS · {cityName.toUpperCase()} <b>Hyperlocal Sector View</b></div>
          <h1 style={{marginTop:6}}>{cityName} — Hyperlocal Flood Intelligence</h1>
          <p style={{marginTop:4}}>{wards.length} monitoring zones · live water-depth risk &amp; drainage status</p>
        </div>
        <div className="id">CITY · {cityName.toUpperCase()} · 1:50k</div>
      </div>

      <div style={{display:"grid",gridTemplateColumns:"1.55fr 1fr",gap:16}}>
        <div className="panel brackets" style={{padding:12}}>
          <div style={{display:"flex",alignItems:"center",gap:10,padding:"6px 8px 12px",flexWrap:"wrap"}}>
            <span className="chip active">Zone Risk</span>
            <span className="chip">Drainage</span>
            <span className="chip">Traffic Index</span>
            <span className="mono" style={{marginLeft:"auto",color:"var(--text-lo)",fontSize:11}}>Live Resolution: 100m</span>
          </div>
          <ChennaiMap wards={wards} onSelect={setSelected} selected={selected}/>
        </div>

        {selected && <WardPanel ward={selected}/>}
      </div>

      {/* Ward table */}
      <div className="panel brackets" style={{marginTop:16}}>
        <div className="panel-hd">
          <h3>Monitoring Zones — {cityName}</h3>
          <span className="sub">Live sensor status</span>
        </div>
        <div className="panel-bd" style={{padding:0}}>
          <table className="data">
            <thead>
              <tr><th>Zone / Area</th><th>Class</th><th>Flood Prob.</th><th>Water Depth</th><th>Drainage Eff.</th><th>Population</th></tr>
            </thead>
            <tbody>
              {[...wards].sort((a,b)=>b.risk-a.risk).map((w,i)=>{
                const c = riskColor(w.class);
                return (
                  <tr key={w.id} style={{cursor:"pointer",background:selected?.id===w.id?"rgba(34,211,238,0.05)":undefined}} onClick={()=>setSelected(w)}>
                    <td style={{fontWeight:600}}>{w.name}</td>
                    <td><span className="sev" style={{color:c,background:c+"22"}}>{riskLabel(w.class)}</span></td>
                    <td>
                      <div style={{display:"flex",alignItems:"center",gap:8}}>
                        <div style={{width:80,height:5,background:"rgba(20,32,48,0.7)",borderRadius:3,overflow:"hidden"}}><div style={{width:w.risk+"%",height:"100%",background:c}}/></div>
                        <span className="mono">{w.risk}%</span>
                      </div>
                    </td>
                    <td className="mono">{w.depth} m</td>
                    <td className="mono">{Math.max(30, 100 - w.risk)}%</td>
                    <td className="mono" style={{color:"var(--text-mid)"}}>{w.pop.toLocaleString()}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function WardPanel({ ward }){
  const c = riskColor(ward.class);
  return (
    <div className="panel brackets" style={{alignSelf:"start"}}>
      <div className="panel-hd">
        <h3>Zone Detail</h3>
        <span className="live" style={{background:c+"22",color:c}}><span className="d" style={{background:c,boxShadow:`0 0 6px ${c}`}}/>{riskLabel(ward.class)}</span>
        <span className="sub mono">{ward.id}</span>
      </div>
      <div className="panel-bd">
        <div style={{display:"flex",alignItems:"center",gap:14}}>
          <HalfGauge value={ward.risk} color={c} size={130} label="FLOOD PROB."/>
          <div>
            <div style={{fontSize:20,fontWeight:700}}>{ward.name}</div>
            <div style={{fontSize:11,color:"var(--text-mid)",marginTop:2}} className="mono">POP {(ward.pop/1000).toFixed(0)}K · DEPTH {ward.depth}m</div>
            <div style={{marginTop:10}}>
              <span className="chip active">{ward.class==="safe" ? "Status: Nominal" : "Status: Active Advisory"}</span>
            </div>
          </div>
        </div>

        <div style={{marginTop:16,display:"grid",gridTemplateColumns:"1fr 1fr",gap:8}}>
          {[
            ["Predicted Depth", ward.depth+" m"],
            ["Drainage Efficiency", Math.max(30, 100-ward.risk)+"%"],
            ["Population Exposed", (ward.pop*ward.risk/100/1000).toFixed(0)+"K"],
            ["Response Level", ward.risk>75?"Tier-1 Emergency":ward.risk>45?"Tier-2 Standby":"Normal Operations"]
          ].map(([k,v],i)=>(
            <div key={i} style={{padding:10,background:"rgba(10,18,28,0.5)",border:"1px solid var(--stroke)",borderRadius:8}}>
              <div className="k">{k}</div>
              <div style={{fontWeight:600,marginTop:2,fontSize:13}} className="num">{v}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

window.MapScreen = MapScreen;
window.CityScreen = CityScreen;
window.DistrictPanel = DistrictPanel;
window.WardPanel = WardPanel;
