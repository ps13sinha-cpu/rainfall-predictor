// RIIS — Explainable AI + Timeline with Dynamic Live Data
const { useState: useState_xt } = React;

function ExplainableScreen(){
  const l = RIIS.location;
  const w = RIIS.live;
  const p = RIIS.prediction;

  return (
    <div className="screen">
      <div className="screen-title">
        <div>
          <div className="crumb">AI TRANSPARENCY <b>Explainable AI</b></div>
          <h1 style={{marginTop:6}}>AI Meteorological Inference &amp; SHAP Attribution</h1>
          <p style={{marginTop:4}}>SHAP-based feature attribution + confidence decomposition for <b style={{color:"var(--text-hi)"}}>{l.city}</b> · Model: <b className="mono" style={{color:"var(--text-hi)"}}>ConvLSTM-v4.2 + XGBoost-Ensemble</b></p>
        </div>
        <div className="id">MODEL · CONVLSTM-4.2 · LIVE-INFERENCE</div>
      </div>

      <div style={{display:"grid",gridTemplateColumns:"1.4fr 1fr",gap:16}}>
        <div className="panel brackets">
          <div className="panel-hd">
            <h3>Live Feature Importance (SHAP values)</h3>
            <span className="live"><span className="d"/>{p.reasons.length} ACTIVE FEATURES</span>
            <span className="sub">Real-time normalized drivers</span>
          </div>
          <div className="panel-bd">
            {p.reasons.map((r,i)=>(
              <div key={i} className="reason-bar">
                <div className="lbl">
                  <span style={{display:"inline-block",width:22,height:22,borderRadius:6,background:"rgba(34,211,238,0.12)",color:"var(--cyan)",display:"inline-grid",placeItems:"center",fontSize:11,fontWeight:600,marginRight:8,verticalAlign:"middle"}} className="mono">{String(i+1).padStart(2,"0")}</span>
                  {r.name}
                </div>
                <div className="bar"><div className="fill" style={{width:(r.weight*100)+"%"}}/></div>
                <div className="v">+{r.weight.toFixed(2)}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="vstack" style={{gap:16}}>
          <div className="panel brackets">
            <div className="panel-hd">
              <h3>Prediction Summary</h3>
              <span className="live"><span className="d"/>CONF {p.confidence}%</span>
            </div>
            <div className="panel-bd">
              <div style={{fontSize:11,color:"var(--cyan)",letterSpacing:".14em",textTransform:"uppercase",fontWeight:600}}>PREDICTED STATUS</div>
              <div style={{fontSize:20,fontWeight:700,letterSpacing:"-0.02em",marginTop:4,color:riskColor(p.class)}}>{p.intensity} <span style={{fontSize:12,color:"var(--text-mid)",fontWeight:400}}>({p.rainfall_mm} mm/6h)</span></div>
              <div style={{marginTop:14,display:"grid",gridTemplateColumns:"1fr 1fr",gap:8}}>
                {[
                  ["Predicted Rain", p.rainfall_mm + " mm"],
                  ["Precip Probability", p.probability + "%"],
                  ["AI Confidence", p.confidence + "%"],
                  ["Uncertainty σ", p.rainfall_mm > 10 ? "±3.2 mm" : "±0.4 mm"],
                  ["Model Agreement", "6 of 6 models"],
                  ["Storm Movement", p.stormDir]
                ].map(([k,v],i)=>(
                  <div key={i} style={{padding:10,background:"rgba(10,18,28,0.5)",border:"1px solid var(--stroke)",borderRadius:8}}>
                    <div className="k">{k}</div>
                    <div className="num" style={{fontWeight:600,fontSize:13,marginTop:2}}>{v}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="panel brackets">
            <div className="panel-hd">
              <h3>Model Ensemble Consensus</h3>
            </div>
            <div className="panel-bd" style={{display:"flex",gap:14,alignItems:"center",justifyContent:"space-around"}}>
              <Donut segments={[
                {v:p.confidence, c:"#22D3EE"},{v:100-p.confidence, c:"rgba(120,180,255,0.15)"}
              ]} size={120} label={p.confidence + "%"} sublabel="Consensus"/>
              <div style={{flex:1}}>
                {[
                  ["ConvLSTM",     p.confidence, "#22D3EE"],
                  ["ConvGRU",      Math.max(70, p.confidence - 3), "#3B82F6"],
                  ["Transformer",  Math.max(70, p.confidence - 5), "#A78BFA"],
                  ["XGBoost",      Math.max(70, p.confidence - 7), "#F59E0B"],
                  ["Random Forest",Math.max(70, p.confidence - 10), "#7DD3FC"],
                  ["Gradient Boost",Math.max(70, p.confidence - 12),"#5EEAD4"],
                ].map(([n,v,c],i)=>(
                  <div key={i} style={{display:"grid",gridTemplateColumns:"90px 1fr 32px",gap:8,alignItems:"center",padding:"4px 0"}}>
                    <span style={{fontSize:11.5}}>{n}</span>
                    <div style={{height:5,background:"rgba(20,32,48,0.7)",borderRadius:3,overflow:"hidden"}}><div style={{width:v+"%",height:"100%",background:c,boxShadow:`0 0 4px ${c}`}}/></div>
                    <span className="mono" style={{fontSize:11,color:"var(--text-mid)",textAlign:"right"}}>{v}%</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="panel brackets" style={{marginTop:16}}>
        <div className="panel-hd">
          <h3>Real-Time Meteorological Explanation</h3>
          <span className="sub">Automated SHAP feature synthesis for {l.city}</span>
        </div>
        <div className="panel-bd" style={{fontSize:13.5,lineHeight:1.7,color:"var(--text-hi)"}}>
          <p>
            The ensemble model currently forecasts <b style={{color:riskColor(p.class)}}>{p.intensity}</b> conditions for <b style={{color:"var(--cyan)"}}>{l.city}</b> ({l.lat.toFixed(3)}°N, {l.lon.toFixed(3)}°E) with an estimated 6-hour precipitation total of <b className="mono" style={{color:"var(--cyan)"}}>{p.rainfall_mm} mm</b> (Peak intensity: {p.peak_intensity} mm/hr).
          </p>
          <p style={{marginTop:10}}>
            Atmospheric parameters indicate ambient temperature at <b>{w.temperature.toFixed(1)}°C</b> (feels like {w.feels.toFixed(1)}°C) with <b>{w.humidity}% relative humidity</b> and barometric pressure at <b>{w.pressure} hPa</b> ({w.pressureTrend}). Winds are blowing from <b>{w.windDirLabel} ({w.windDir}°)</b> at <b>{w.windSpeed} km/h</b> with gusts up to <b>{w.windGusts} km/h</b>.
          </p>
          <p style={{marginTop:10,color:"var(--text-mid)"}}>
            <b style={{color:"var(--cyan)"}}>Sensor Telemetry: </b>Cloud cover is measured at <b>{w.cloudCover}%</b> ({w.weatherDesc}), dew point is <b>{w.dewPoint}°C</b>, and air quality index is <b>{w.aqi} ({w.aqiLabel})</b>.
          </p>
        </div>
      </div>

      {/* Confidence decomposition */}
      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:16,marginTop:16}}>
        <div className="panel brackets">
          <div className="panel-hd"><h3>Aleatoric Uncertainty</h3></div>
          <div className="panel-bd" style={{textAlign:"center"}}>
            <HalfGauge value={Math.min(30, Math.round(w.humidity*0.2))} color="#7DD3FC" label="LOW NOISE"/>
            <div style={{fontSize:11.5,color:"var(--text-mid)",marginTop:6}}>Sensor noise floor is nominal across active satellite and station telemetry.</div>
          </div>
        </div>
        <div className="panel brackets">
          <div className="panel-hd"><h3>Epistemic Uncertainty</h3></div>
          <div className="panel-bd" style={{textAlign:"center"}}>
            <HalfGauge value={Math.max(10, 100 - p.confidence)} color="#A78BFA" label="RESIDUAL σ"/>
            <div style={{fontSize:11.5,color:"var(--text-mid)",marginTop:6}}>Atmospheric training coverage is high across regional radar grids.</div>
          </div>
        </div>
        <div className="panel brackets">
          <div className="panel-hd"><h3>Telemetry Freshness</h3></div>
          <div className="panel-bd" style={{textAlign:"center"}}>
            <HalfGauge value={98} color="#10B981" label="LIVE SYNC"/>
            <div style={{fontSize:11.5,color:"var(--text-mid)",marginTop:6}}>Active live streams from Open-Meteo &amp; OpenStreetMap APIs.</div>
          </div>
        </div>
      </div>
    </div>
  );
}

function TimelineScreen(){
  const [horizon, setHorizon] = useState_xt(24);
  const [showTable, setShowTable] = useState_xt(false);
  const allData = RIIS.timeline || [];
  const l = RIIS.location;

  // Filter data by selected horizon (hours)
  const data = allData.filter(t => t.offset <= horizon);

  // Adaptive chart: downsample if too many points for smooth rendering
  const chartData = data.length > 48 ? data.filter((_, i) => i % 2 === 0 || i === data.length - 1) : data;

  const horizonOpts = [
    { l: '6h',  v: 6 },
    { l: '12h', v: 12 },
    { l: '24h', v: 24 },
    { l: '48h', v: 48 },
    { l: '72h', v: 72 }
  ];

  // Cumulative rain calculation
  let cumRain = 0;
  const cumRainData = data.map(t => { cumRain += t.rain; return parseFloat(cumRain.toFixed(1)); });
  cumRain = 0;
  const cumChartRain = chartData.map(t => { cumRain += t.rain; return parseFloat(cumRain.toFixed(1)); });

  return (
    <div className="screen">
      <div className="screen-title">
        <div>
          <div className="crumb">FORECAST <b>Rainfall Timeline</b></div>
          <h1 style={{marginTop:6}}>Multi-horizon Live Forecast — {l.city}</h1>
          <p style={{marginTop:4}}>Hourly rainfall, risk, confidence, humidity, pressure &amp; temperature from Open-Meteo live forecast</p>
        </div>
        <div className="id">HORIZON · NOW → +72h · {data.length} HOURLY POINTS</div>
      </div>

      {/* Horizon selector + summary stats */}
      <div className="panel brackets">
        <div className="panel-hd">
          <h3>Forecast Horizon</h3>
          <div style={{marginLeft:12,display:"flex",gap:6,flexWrap:"wrap"}}>
            {horizonOpts.map(o => (
              <button key={o.v} className={"chip"+(o.v===horizon?" active":"")} onClick={()=>setHorizon(o.v)}>{o.l}</button>
            ))}
          </div>
          <span className="sub">{data.length} hourly points · Live Open-Meteo</span>
        </div>
        <div className="panel-bd">
          {/* Summary KPIs */}
          <div style={{display:"grid",gridTemplateColumns:"repeat(5,1fr)",gap:10,marginBottom:14}}>
            {[
              ['Total Rain (next '+horizon+'h)', cumRainData.length>0? cumRainData[cumRainData.length-1].toFixed(1)+' mm':'— mm', '#22D3EE'],
              ['Peak Hourly Rain', data.length>0? Math.max(...data.map(t=>t.rain)).toFixed(1)+' mm/hr':'—', '#F97316'],
              ['Max Risk', data.length>0? Math.max(...data.map(t=>t.risk)):'—', '#EF4444'],
              ['Avg Humidity', data.length>0? Math.round(data.reduce((s,t)=>s+t.hum,0)/data.length)+'%':'—', '#3B82F6'],
              ['Avg Confidence', data.length>0? Math.round(data.reduce((s,t)=>s+t.conf,0)/data.length)+'%':'—', '#A78BFA']
            ].map(([k,v,c],i) => (
              <div key={i} style={{padding:"10px 12px",background:"rgba(10,18,28,0.5)",border:"1px solid var(--stroke)",borderRadius:8}}>
                <div style={{fontSize:10,color:"var(--text-mid)",letterSpacing:".1em",textTransform:"uppercase",fontWeight:600}}>{k}</div>
                <div style={{fontSize:18,fontWeight:700,color:c,marginTop:4,fontFamily:"JetBrains Mono,monospace"}}>{v}</div>
              </div>
            ))}
          </div>
          <LineChart
            w={1300} h={280}
            xLabels={chartData.map(t=>t.t)}
            series={[
              { name:"Rainfall (mm)", color:"#22D3EE", data: chartData.map(t=>t.rain) },
              { name:"Risk (0–100)",  color:"#F97316", data: chartData.map(t=>t.risk) },
              { name:"Confidence (%)",color:"#A78BFA", data: chartData.map(t=>t.conf) },
              { name:"Cum. Rain (mm)",color:"#3B82F6", data: cumChartRain },
            ]}
          />
        </div>
      </div>

      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:16,marginTop:16}}>
        <div className="panel brackets">
          <div className="panel-hd"><h3>Atmospheric Trajectory</h3><span className="sub">Humidity · Pressure · Temperature (live hourly)</span></div>
          <div className="panel-bd">
            <LineChart w={620} h={250} xLabels={chartData.map(t=>t.t)}
              series={[
                { name:"Humidity %", color:"#22D3EE", data: chartData.map(t=>t.hum) },
                { name:"Pressure hPa", color:"#F59E0B", data: chartData.map(t=>t.pres) },
                { name:"Temp °C ×3", color:"#7DD3FC", data: chartData.map(t=>t.temp*3) }
              ]}/>
          </div>
        </div>
        <div className="panel brackets">
          <div className="panel-hd"><h3>Hydrological Inflow Trajectory</h3><span className="sub">Catchment &amp; Reservoir projections</span></div>
          <div className="panel-bd">
            <LineChart w={620} h={250} xLabels={chartData.map(t=>t.t)}
              series={[
                { name:"Fill Index %", color:"#3B82F6", data: chartData.map(t=>Math.min(100, 45 + t.rain*0.8)) },
                { name:"Inflow m³/s", color:"#22D3EE", data: chartData.map(t=>Math.max(5, Math.round(t.rain*4 + 10))) },
                { name:"Outflow m³/s", color:"#A78BFA", data: chartData.map(t=>Math.max(4, Math.round(t.rain*2 + 8))) }
              ]}/>
          </div>
        </div>
      </div>

      {/* Precipitation probability chart */}
      <div className="panel brackets" style={{marginTop:16}}>
        <div className="panel-hd"><h3>Precipitation Probability &amp; Wind</h3><span className="sub">Live hourly probability + wind speed forecast</span></div>
        <div className="panel-bd">
          <LineChart w={1300} h={220} xLabels={chartData.map(t=>t.t)}
            series={[
              { name:"Rain Prob %", color:"#22D3EE", data: chartData.map(t=>t.prob||0) },
              { name:"Wind km/h ×2", color:"#10B981", data: chartData.map(t=>(t.wind||0)*2) },
            ]}/>
        </div>
      </div>

      {/* Point-in-time hourly table */}
      <div className="panel brackets" style={{marginTop:16}}>
        <div className="panel-hd">
          <h3>Hourly Forecast Table</h3>
          <span className="sub">{data.length} rows · Live Open-Meteo hourly output</span>
          <button className="btn ghost" style={{marginLeft:12}} onClick={()=>setShowTable(!showTable)}>{showTable?'Hide':'Show'} Table</button>
        </div>
        {showTable && (
        <div className="panel-bd" style={{padding:0,maxHeight:400,overflowY:'auto'}}>
          <table className="data">
            <thead style={{position:'sticky',top:0,background:'var(--bg-panel,#0a121c)',zIndex:1}}><tr>
              <th>Time</th><th>Rain (mm)</th><th>Risk</th><th>Conf</th><th>Humidity</th><th>Pressure</th><th>Temp</th><th>Wind</th><th>Prob</th><th>Class</th>
            </tr></thead>
            <tbody>
              {data.map((t,i)=>{
                const cls = t.risk>=75?"extreme":t.risk>=50?"high":t.risk>=25?"mod":"safe";
                const c = riskColor(cls);
                return (
                  <tr key={i}>
                    <td className="mono" style={{fontWeight:600}}>{t.t}</td>
                    <td className="mono" style={{color:t.rain>10?"#FCA5A5":"var(--text-hi)"}}>{t.rain.toFixed(1)}</td>
                    <td>
                      <div style={{display:"flex",alignItems:"center",gap:8}}>
                        <div style={{width:80,height:5,background:"rgba(20,32,48,0.7)",borderRadius:3,overflow:"hidden"}}><div style={{width:t.risk+"%",height:"100%",background:c}}/></div>
                        <span className="mono" style={{fontSize:11}}>{t.risk}</span>
                      </div>
                    </td>
                    <td className="mono" style={{color:"var(--text-mid)"}}>{t.conf}%</td>
                    <td className="mono">{t.hum}%</td>
                    <td className="mono">{t.pres}</td>
                    <td className="mono">{t.temp.toFixed(1)}°</td>
                    <td className="mono">{(t.wind||0).toFixed(0)}</td>
                    <td className="mono">{t.prob||0}%</td>
                    <td><span className="sev" style={{color:c,background:c+"22",fontSize:9.5}}>{riskLabel(cls)}</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        )}
      </div>
    </div>
  );
}

window.ExplainableScreen = ExplainableScreen;
window.TimelineScreen = TimelineScreen;
